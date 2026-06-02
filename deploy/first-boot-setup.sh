#!/bin/bash
#
# Vernis v3 - First Boot Auto-Setup Script
#
# This script runs once on first boot to configure the Vernis device.
# It installs all dependencies, configures services, and prepares the system.
#

set -e  # Exit on error

VERNIS_DIR="/opt/vernis"
LOG_FILE="/var/log/vernis-setup.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[Vernis Setup]${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
    exit 1
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "$LOG_FILE"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    error "Please run as root (sudo)"
fi

log "Starting Vernis v3 first-boot setup..."
log "Log file: $LOG_FILE"

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VERSION=$VERSION_ID
    log "Detected OS: $OS $VERSION"
else
    error "Cannot detect OS"
fi

#==============================================================================
# 1. System Update (Optional - can be skipped for faster deployment)
#==============================================================================
log "Step 1/8: Updating system packages..."

if [ "${SKIP_UPDATE:-0}" = "0" ]; then
    apt-get update -y >> "$LOG_FILE" 2>&1 || warn "apt-get update failed"
    # Don't upgrade on first boot to save time
    # apt-get upgrade -y >> "$LOG_FILE" 2>&1
else
    info "Skipping system update (SKIP_UPDATE=1)"
fi

#==============================================================================
# 2. Install Dependencies
#==============================================================================
log "Step 2/8: Installing dependencies..."

# Python and pip
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    wget \
    >> "$LOG_FILE" 2>&1 || error "Failed to install Python dependencies"

# Python packages
pip3 install --upgrade pip >> "$LOG_FILE" 2>&1
pip3 install \
    flask \
    requests \
    pillow \
    qrcode \
    websocket-client \
    >> "$LOG_FILE" 2>&1 || error "Failed to install Python packages"

# Network tools
apt-get install -y \
    network-manager \
    avahi-daemon \
    >> "$LOG_FILE" 2>&1 || error "Failed to install network tools"

# Install Caddy web server
log "Installing Caddy web server..."
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https >> "$LOG_FILE" 2>&1
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>> "$LOG_FILE"
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list >> "$LOG_FILE" 2>&1
apt-get update >> "$LOG_FILE" 2>&1
apt-get install -y caddy >> "$LOG_FILE" 2>&1 || error "Failed to install Caddy"

log "Dependencies installed successfully"

#==============================================================================
# 3. Install IPFS (Kubo)
#==============================================================================
log "Step 3/8: Installing IPFS (Kubo)..."

# Detect architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64)
        IPFS_ARCH="amd64"
        ;;
    aarch64|arm64)
        IPFS_ARCH="arm64"
        ;;
    armv7l)
        IPFS_ARCH="arm"
        ;;
    *)
        error "Unsupported architecture: $ARCH"
        ;;
esac

IPFS_VERSION="v0.24.0"
IPFS_URL="https://dist.ipfs.tech/kubo/${IPFS_VERSION}/kubo_${IPFS_VERSION}_linux-${IPFS_ARCH}.tar.gz"

log "Downloading IPFS for $IPFS_ARCH..."
cd /tmp
wget -q "$IPFS_URL" -O kubo.tar.gz >> "$LOG_FILE" 2>&1 || error "Failed to download IPFS"

tar -xzf kubo.tar.gz >> "$LOG_FILE" 2>&1
cd kubo
bash install.sh >> "$LOG_FILE" 2>&1 || error "Failed to install IPFS"

rm -rf /tmp/kubo /tmp/kubo.tar.gz

log "IPFS installed: $(ipfs --version)"

#==============================================================================
# 4. Configure IPFS
#==============================================================================
log "Step 4/8: Configuring IPFS..."

# Initialize IPFS for vernis user (will be created later)
export IPFS_PATH=/opt/vernis/.ipfs

if [ ! -d "$IPFS_PATH" ]; then
    ipfs init >> "$LOG_FILE" 2>&1 || error "Failed to initialize IPFS"
    log "IPFS repository initialized"
else
    log "IPFS repository already exists"
fi

# Configure IPFS for optimal Vernis usage
ipfs config Addresses.Gateway /ip4/127.0.0.1/tcp/8080 >> "$LOG_FILE" 2>&1
ipfs config Addresses.API /ip4/127.0.0.1/tcp/5001 >> "$LOG_FILE" 2>&1

# Enable garbage collection (every 6 hours for large storage)
ipfs config --json Datastore.GCPeriod '"6h"' >> "$LOG_FILE" 2>&1

# Set storage limits (2TB for production use)
ipfs config --json Datastore.StorageMax '"2000GB"' >> "$LOG_FILE" 2>&1

# Enable file pinning
ipfs config --json Experimental.FilestoreEnabled true >> "$LOG_FILE" 2>&1

# Optimize for large collections
ipfs config --json Datastore.BloomFilterSize 1048576 >> "$LOG_FILE" 2>&1
ipfs config --json Reprovider.Interval '"12h"' >> "$LOG_FILE" 2>&1

log "IPFS configured with 2TB storage limit"

# Create symlink for API compatibility (backend expects /opt/vernis/ipfs)
rm -f /opt/vernis/ipfs 2>/dev/null || true
ln -sf "$IPFS_PATH" /opt/vernis/ipfs
if [ -L /opt/vernis/ipfs ]; then
    log "IPFS symlink created: /opt/vernis/ipfs -> $IPFS_PATH"
else
    log "WARNING: Failed to create IPFS symlink"
fi

#==============================================================================
# 5. Create Vernis User (Optional - can run as pi user)
#==============================================================================
log "Step 5/8: Setting up user permissions..."

# Create vernis user if doesn't exist
if ! id -u vernis >/dev/null 2>&1; then
    useradd -r -s /bin/bash -d "$VERNIS_DIR" -m vernis >> "$LOG_FILE" 2>&1
    log "Created vernis user"
else
    log "User vernis already exists"
fi

# Set ownership
chown -R vernis:vernis "$VERNIS_DIR" >> "$LOG_FILE" 2>&1
chown -R vernis:vernis "$IPFS_PATH" >> "$LOG_FILE" 2>&1

log "Permissions configured"

#==============================================================================
# 6. Install Systemd Services
#==============================================================================
log "Step 6/8: Installing systemd services..."

# Install service files
bash "$VERNIS_DIR/deploy/install-services.sh" >> "$LOG_FILE" 2>&1 || error "Failed to install services"

log "Systemd services installed"

#==============================================================================
# 7. Configure Network
#==============================================================================
log "Step 7/8: Configuring network..."

# Set hostname
hostnamectl set-hostname vernis >> "$LOG_FILE" 2>&1

# Enable mDNS (vernis.local)
systemctl enable avahi-daemon >> "$LOG_FILE" 2>&1
systemctl start avahi-daemon >> "$LOG_FILE" 2>&1

log "Hostname set to 'vernis' (accessible via vernis.local)"

#==============================================================================
# 8. Configure Firewall (UFW)
#==============================================================================
log "Step 8/9: Configuring firewall..."

# Install UFW if not present
if ! command -v ufw &> /dev/null; then
    apt-get install -y ufw >> "$LOG_FILE" 2>&1 || warn "Failed to install UFW"
fi

if command -v ufw &> /dev/null; then
    # Reset UFW to defaults
    ufw --force reset >> "$LOG_FILE" 2>&1

    # Set default policies
    ufw default deny incoming >> "$LOG_FILE" 2>&1
    ufw default allow outgoing >> "$LOG_FILE" 2>&1

    # Allow SSH (port 22) - can be disabled after setup
    ufw allow 22/tcp comment 'SSH' >> "$LOG_FILE" 2>&1

    # Allow HTTP (port 80) - Caddy web server
    ufw allow 80/tcp comment 'HTTP (Caddy)' >> "$LOG_FILE" 2>&1

    # Allow HTTPS (port 443) - Caddy web server
    ufw allow 443/tcp comment 'HTTPS (Caddy)' >> "$LOG_FILE" 2>&1

    # Allow Vernis API (port 5000) - internal Flask API
    ufw allow 5000/tcp comment 'Vernis API' >> "$LOG_FILE" 2>&1

    # Allow IPFS swarm (port 4001) - for IPFS peer connections
    ufw allow 4001/tcp comment 'IPFS Swarm' >> "$LOG_FILE" 2>&1

    # Allow mDNS for vernis.local discovery
    ufw allow 5353/udp comment 'mDNS (vernis.local)' >> "$LOG_FILE" 2>&1

    # Enable firewall
    ufw --force enable >> "$LOG_FILE" 2>&1

    log "Firewall enabled and configured"
    log "  ✓ Port 22   - SSH (can disable after setup)"
    log "  ✓ Port 80   - HTTP (Web Interface)"
    log "  ✓ Port 443  - HTTPS (Web Interface)"
    log "  ✓ Port 5000 - Vernis API"
    log "  ✓ Port 4001 - IPFS Swarm"
    log "  ✓ Port 5353 - mDNS (vernis.local)"
else
    warn "UFW not available, skipping firewall setup"
fi

#==============================================================================
# 9. Optimize System
#==============================================================================
log "Step 9/9: Optimizing system..."

# Disable unnecessary services to save resources
if [ "$OS" = "raspbian" ] || [ "$OS" = "debian" ]; then
    # Disable Bluetooth if not needed
    if [ "${DISABLE_BLUETOOTH:-1}" = "1" ]; then
        systemctl disable bluetooth >> "$LOG_FILE" 2>&1 || true
        log "Bluetooth disabled"
    fi

    # Disable WiFi power management
    if [ -f /etc/NetworkManager/conf.d/default-wifi-powersave-on.conf ]; then
        echo -e "[connection]\nwifi.powersave = 2" > /etc/NetworkManager/conf.d/default-wifi-powersave-on.conf
        log "WiFi power saving disabled"
    fi
fi

# Create necessary directories
mkdir -p "$VERNIS_DIR/nfts"
mkdir -p "$VERNIS_DIR/uploads"
mkdir -p "$VERNIS_DIR/csv-library"
mkdir -p "$VERNIS_DIR/config"
mkdir -p "$VERNIS_DIR/backup"
mkdir -p "$VERNIS_DIR/scripts"
mkdir -p /var/www/vernis
mkdir -p /var/log/caddy

# Set web directory ownership
chown -R caddy:caddy /var/www/vernis
chown -R vernis:vernis "$VERNIS_DIR"

# Configure Caddy if Caddyfile exists
if [ -f "$VERNIS_DIR/config/Caddyfile" ]; then
    cp "$VERNIS_DIR/config/Caddyfile" /etc/caddy/Caddyfile
    systemctl enable caddy >> "$LOG_FILE" 2>&1
    systemctl restart caddy >> "$LOG_FILE" 2>&1 || warn "Failed to start Caddy"
    log "Caddy configured"
fi

# Configure mDNS if avahi service file exists
if [ -f "$VERNIS_DIR/config/avahi-vernis.service" ]; then
    cp "$VERNIS_DIR/config/avahi-vernis.service" /etc/avahi/services/vernis.service
    systemctl restart avahi-daemon >> "$LOG_FILE" 2>&1 || true
fi

log "System optimization complete"

#==============================================================================
# Finalize Setup
#==============================================================================
log "Starting services..."

# Start services
systemctl daemon-reload >> "$LOG_FILE" 2>&1
systemctl enable vernis-ipfs >> "$LOG_FILE" 2>&1
systemctl enable vernis-backend >> "$LOG_FILE" 2>&1
systemctl start vernis-ipfs >> "$LOG_FILE" 2>&1
sleep 3
systemctl start vernis-backend >> "$LOG_FILE" 2>&1

log "Services started successfully"

# Mark setup as complete
touch /opt/vernis/.setup-complete

#==============================================================================
# Display Summary
#==============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✓ Vernis v3 Setup Complete!${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "  ${BLUE}Access your gallery at:${NC}"
echo "    • http://vernis.local"
echo "    • http://$(hostname -I | awk '{print $1}')"
echo ""
echo -e "  ${BLUE}Services running:${NC}"
systemctl is-active --quiet vernis-backend && echo "    ✓ Vernis Backend" || echo "    ✗ Vernis Backend (failed)"
systemctl is-active --quiet vernis-ipfs && echo "    ✓ IPFS Daemon (2TB storage)" || echo "    ✗ IPFS Daemon (failed)"
echo ""
echo -e "  ${BLUE}Security:${NC}"
if command -v ufw &> /dev/null && ufw status | grep -q "Status: active"; then
    echo "    ✓ Firewall enabled"
    echo "    ✓ Port 80/443 (Web) - Open"
    echo "    ✓ Port 5000 (API) - Open"
    echo "    ✓ Port 4001 (IPFS) - Open"
    echo "    ✓ Port 22 (SSH) - Open (disable after setup)"
else
    echo "    ✗ Firewall not enabled"
fi
echo ""
echo -e "  ${BLUE}IPFS Configuration:${NC}"
echo "    • Storage limit: 2000 GB (2TB)"
echo "    • Gateway: http://localhost:8080"
echo "    • Garbage collection: Every 6 hours"
echo ""
echo -e "  ${BLUE}Useful commands:${NC}"
echo "    • View logs:       journalctl -u vernis-backend -f"
echo "    • Restart:         sudo systemctl restart vernis-backend"
echo "    • IPFS status:     IPFS_PATH=/opt/vernis/.ipfs ipfs stats bw"
echo "    • Firewall status: sudo ufw status"
echo "    • Storage usage:   du -sh /opt/vernis/.ipfs"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

log "Setup complete! Vernis is ready to use."

# Optional: Reboot after setup
if [ "${AUTO_REBOOT:-0}" = "1" ]; then
    log "Rebooting in 10 seconds..."
    sleep 10
    reboot
fi
