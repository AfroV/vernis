#!/bin/bash
##############################################
# Vernis v3 - Complete Installation Script
# Run this on a fresh Raspberry Pi OS Lite installation
##############################################

set -e

echo "=========================================="
echo "Vernis v3 Installation"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash install.sh"
    exit 1
fi

# Get the actual user (not root) - needed early for various steps
ACTUAL_USER=${SUDO_USER:-pi}

# Detect if this is a kiosk installation
echo "> Enable kiosk mode now? (boots into fullscreen gallery)"
echo "  You can toggle this later with: sudo bash /opt/vernis/scripts/enable-kiosk.sh"
echo "  (y/n)"
read -r KIOSK_MODE
KIOSK_MODE=$(echo "$KIOSK_MODE" | tr '[:upper:]' '[:lower:]')

echo ""
echo "Starting installation..."
echo ""

# Update system
echo "[1/10] Updating system packages..."
apt-get update
apt-get upgrade -y

# Configure automatic security updates
echo "[1.5/10] Configuring automatic security updates..."
apt-get install -y unattended-upgrades
echo 'Unattended-Upgrade::Allowed-Origins {
        "${distro_id}:${distro_codename}-security";
        "${distro_id}:${distro_codename}-updates";
};' > /etc/apt/apt.conf.d/50unattended-upgrades
echo 'APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";' > /etc/apt/apt.conf.d/20auto-upgrades

# Install required packages
echo "[2/10] Installing dependencies..."
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    wget \
    hostapd \
    dnsmasq \
    avahi-daemon \
    network-manager \
    debian-keyring \
    debian-archive-keyring \
    apt-transport-https \
    zram-tools \
    python3-dbus \
    python3-gi \
    bluez

# Optimize for SD Card Endurance
echo "[2.5/10] Optimizing for SD Card endurance..."

# 1. Disable Swap (to prevent SD thrashing)
if systemctl list-unit-files 2>/dev/null | grep -q dphys-swapfile; then
    dphys-swapfile swapoff 2>/dev/null || true
    dphys-swapfile uninstall 2>/dev/null || true
    systemctl disable dphys-swapfile 2>/dev/null || true
    apt-get purge -y dphys-swapfile 2>/dev/null || true
else
    echo "Swapfile service not found (already removed or not present), skipping..."
fi

# 2. Configure noatime (reduce write cycles)
# Only add noatime if it's not already there
sed -i -e '/noatime/!s/defaults/defaults,noatime/' /etc/fstab

# 3. Install Log2RAM (offload logs to RAM)
if ! command -v log2ram &> /dev/null; then
    echo "Installing Log2RAM..."
    curl -L https://github.com/azlux/log2ram/archive/master.tar.gz | tar zxf -
    cd log2ram-master
    chmod +x install.sh && ./install.sh
    cd ..
    rm -rf log2ram-master
else
    echo "Log2RAM already installed, skipping..."
fi

# 4. Install IPFS (Kubo)
if ! command -v ipfs &> /dev/null; then
    echo "Installing IPFS..."
    ARCH=$(uname -m)
    if [ "$ARCH" = "aarch64" ]; then
        IPFS_ARCH="linux-arm64"
    elif [ "$ARCH" = "armv7l" ]; then
        IPFS_ARCH="linux-arm"
    else
        IPFS_ARCH="linux-amd64"
    fi
    cd /tmp
    curl -L -o kubo.tar.gz "https://dist.ipfs.tech/kubo/v0.24.0/kubo_v0.24.0_${IPFS_ARCH}.tar.gz"
    tar -xzf kubo.tar.gz
    mv kubo/ipfs /usr/local/bin/
    rm -rf kubo kubo.tar.gz
    echo "IPFS installed: $(ipfs --version)"
else
    echo "IPFS already installed, skipping..."
fi

# 5. Initialize IPFS and create systemd service
IPFS_PATH="/home/$ACTUAL_USER/.ipfs"
if [ ! -d "$IPFS_PATH" ]; then
    echo "Initializing IPFS for $ACTUAL_USER..."
    sudo -u $ACTUAL_USER IPFS_PATH="$IPFS_PATH" ipfs init 2>/dev/null || true
fi

# Create symlink for API compatibility (required for backend IPFS operations)
mkdir -p /opt/vernis
rm -f /opt/vernis/ipfs 2>/dev/null || true
ln -sf "$IPFS_PATH" /opt/vernis/ipfs
if [ -L /opt/vernis/ipfs ]; then
    echo "IPFS symlink created: /opt/vernis/ipfs -> $IPFS_PATH"
else
    echo "WARNING: Failed to create IPFS symlink at /opt/vernis/ipfs"
fi

# Create IPFS systemd service
cat > /etc/systemd/system/ipfs.service <<EOF
[Unit]
Description=IPFS Daemon
After=network.target

[Service]
Type=simple
User=$ACTUAL_USER
Environment=IPFS_PATH=$IPFS_PATH
ExecStart=/usr/local/bin/ipfs daemon --enable-gc
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ipfs
systemctl start ipfs || true

# Add weekly IPFS garbage collection to crontab
(crontab -l 2>/dev/null | grep -v "ipfs repo gc"; echo "0 4 * * 0 IPFS_PATH=$IPFS_PATH /usr/local/bin/ipfs repo gc >> /var/log/ipfs-gc.log 2>&1") | crontab -

# Install Caddy
echo "[3/10] Installing Caddy web server..."
rm -f /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy

# Install Python dependencies
echo "[4/10] Installing Python packages..."
# Use --break-system-packages for dedicated device or install via apt where available
apt-get install -y python3-flask python3-requests python3-pil python3-qrcode || pip3 install --break-system-packages flask requests pillow qrcode
pip3 install --break-system-packages websocket-client || true

# Create directory structure
echo "[5/10] Creating directory structure..."
mkdir -p /opt/vernis/{nfts,uploads,scripts,backup,csv-library}
mkdir -p /var/www/vernis
mkdir -p /var/log/caddy

# Set proper ownership of Vernis directories for the user that will run the service
chown -R $ACTUAL_USER:$ACTUAL_USER /opt/vernis
echo "Set ownership of /opt/vernis to $ACTUAL_USER"

# Add useful aliases for the user
echo "[5.5/10] Adding command-line shortcuts..."
BASHRC_FILE="/home/$ACTUAL_USER/.bashrc"
if ! grep -q "alias gallery=" "$BASHRC_FILE" 2>/dev/null; then
    cat >> "$BASHRC_FILE" <<'EOF'

# Vernis shortcuts
alias gallery='pkill chromium; sleep 1; DISPLAY=:0 chromium --kiosk --noerrdialogs --password-store=basic http://localhost/gallery.html &'
alias vernis-logs='journalctl -u vernis-api -f'
alias vernis-restart='sudo systemctl restart vernis-api'
EOF
    echo "Added Vernis aliases to $BASHRC_FILE"
fi

# Copy web files
echo "[6/10] Installing web UI..."
cp *.html /var/www/vernis/
cp *.css /var/www/vernis/ 2>/dev/null || true
cp *.js /var/www/vernis/ 2>/dev/null || true
cp favicon.svg /var/www/vernis/ 2>/dev/null || true
cp *.html /opt/vernis/
cp favicon.svg /opt/vernis/ 2>/dev/null || true
chown -R caddy:caddy /var/www/vernis

# Copy CSV library files if they exist
if [ -d "csv-library" ]; then
    echo "Installing CSV library files..."
    cp csv-library/*.csv /opt/vernis/csv-library/ 2>/dev/null || true
    cp csv-library/*.json /opt/vernis/csv-library/ 2>/dev/null || true
fi

# Copy backend
echo "[7/10] Installing Flask API..."
cp backend/app.py /opt/vernis/
cp update-config.json /opt/vernis/ 2>/dev/null || true
cp scripts/*.sh /opt/vernis/scripts/
chmod +x /opt/vernis/scripts/*.sh

# Copy Python scripts if they exist
if ls scripts/*.py 1> /dev/null 2>&1; then
    cp scripts/*.py /opt/vernis/scripts/
    chmod +x /opt/vernis/scripts/*.py
fi

# Install systemd services
echo "[8/10] Installing system services..."

# Replace 'User=pi' with actual user in service files
for service_file in systemd/*.service; do
    sed "s/User=pi/User=$ACTUAL_USER/g" "$service_file" > "/etc/systemd/system/$(basename $service_file)"
done

cp systemd/*.timer /etc/systemd/system/
systemctl daemon-reload

# Enable and start services
systemctl enable vernis-api.service
# Hotspot/BLE disabled — WiFi configured via on-screen UI
# systemctl enable vernis-ap-check.timer
systemctl start vernis-api.service || true
# systemctl start vernis-ap-check.timer || true

# Configure Caddy
echo "[9/10] Configuring Caddy..."
cp config/Caddyfile /etc/caddy/Caddyfile
systemctl enable caddy
if ! systemctl restart caddy; then
    echo "ERROR: Failed to restart Caddy. Checking logs:"
    journalctl -u caddy --no-pager | tail -n 20
    echo "Checking Caddyfile validation:"
    caddy validate --config /etc/caddy/Caddyfile
    exit 1
fi

# Configure mDNS
cp config/avahi-vernis.service /etc/avahi/services/vernis.service
systemctl restart avahi-daemon

# Disable hotspot and BLE services
systemctl disable hostapd || true
systemctl disable dnsmasq || true
systemctl mask hostapd
systemctl mask dnsmasq

# Always install kiosk packages (so user can attach display later)
echo "[10/10] Installing display/kiosk packages..."
apt-get install -y lightdm chromium unclutter xserver-xorg xinit || true

# Configure kiosk mode if requested
if [ "$KIOSK_MODE" = "y" ]; then
    echo "Enabling kiosk mode..."

    # Auto-login
    mkdir -p /etc/lightdm/lightdm.conf.d
    cat > /etc/lightdm/lightdm.conf.d/01-autologin.conf <<EOF
[Seat:*]
autologin-user=$ACTUAL_USER
autologin-user-timeout=0
EOF

    # Setup autostart for kiosk
    AUTOSTART_DIR="/home/$ACTUAL_USER/.config/lxsession/LXDE-pi"
    sudo -u $ACTUAL_USER mkdir -p "$AUTOSTART_DIR"
    cat > "$AUTOSTART_DIR/autostart" <<'AUTOSTART_EOF'
@xset s off
@xset -dpms
@xset s noblank
@unclutter -idle 0.5 -root
@sleep 3
@bash /opt/vernis/scripts/kiosk-launcher.sh
AUTOSTART_EOF
    chown -R $ACTUAL_USER:$ACTUAL_USER "/home/$ACTUAL_USER/.config"

    # Enable graphical boot and watchdog
    systemctl set-default graphical.target
    systemctl enable vernis-watchdog.service
    systemctl start vernis-watchdog.service || true

    echo "Kiosk mode enabled!"
else
    echo "Kiosk mode not enabled (headless installation)"
    echo "To enable later: sudo bash /opt/vernis/scripts/enable-kiosk.sh enable"
    systemctl set-default multi-user.target
fi

# Get device serial for AP name
SERIAL=$(cat /proc/cpuinfo | grep Serial | cut -d' ' -f2 | cut -c9-16)

# Check for preload content
PRELOAD_DIR="/home/$ACTUAL_USER/preload"
if [ -d "$PRELOAD_DIR" ]; then
    echo ""
    echo "Detected preload directory. Preloading content..."
    PRELOAD_MODE="full"
    if [ -d "$PRELOAD_DIR/nfts" ]; then
        PRELOAD_MODE="full"
    else
        PRELOAD_MODE="lite"
    fi
    bash /opt/vernis/scripts/preload-device.sh "$PRELOAD_MODE" "$PRELOAD_DIR"
fi

echo ""
echo "=========================================="
echo "Vernis v3 Installation Complete!"
echo "=========================================="
echo ""
echo "Access Vernis at: http://vernis.local"
echo ""
echo "Fallback AP (when no internet):"
echo "  SSID: Vernis-$SERIAL"
echo "  Password: <ap-password>"
echo ""
if [ "$KIOSK_MODE" = "y" ]; then
    echo "Kiosk mode: ENABLED"
    echo "The device will boot into fullscreen gallery mode"
else
    echo "Kiosk mode: DISABLED (headless)"
    echo "To enable kiosk mode later:"
    echo "  sudo bash /opt/vernis/scripts/enable-kiosk.sh enable"
fi
echo ""
if [ "$SKIP_REBOOT" = "1" ]; then
    echo "Installation complete. Reboot skipped (will reboot after additional setup)."
    echo "=========================================="
else
    echo "Rebooting in 10 seconds..."
    echo "=========================================="
    sleep 10
    reboot
fi

