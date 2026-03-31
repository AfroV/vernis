#!/bin/bash
##############################################
# Vernis Remote Deployment Script
# Run from Mac to install Vernis on a Pi
##############################################

# Check arguments
if [ "$#" -lt 3 ]; then
    echo "Usage: bash deploy-to-pi.sh <username> <ip_address> <password>"
    echo "Example: bash deploy-to-pi.sh myuser 192.168.1.100 mypassword"
    exit 1
fi

PI_USER="$1"
PI_IP="$2"
PI_PASS="$3"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "==========================================="
echo "Vernis Remote Deployment"
echo "==========================================="
echo "Target: $PI_USER@$PI_IP"
echo "Project: $PROJECT_DIR"
echo ""

# Check sshpass is installed
if ! command -v sshpass &> /dev/null; then
    echo "sshpass not found. Install with: brew install hudochenkov/sshpass/sshpass"
    exit 1
fi

SSH_CMD="sshpass -p '$PI_PASS' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 $PI_USER@$PI_IP"
SCP_CMD="sshpass -p '$PI_PASS' scp -o StrictHostKeyChecking=no"

# Test connection
echo "[1/10] Testing connection..."
eval "$SSH_CMD 'hostname'" || { echo "Connection failed"; exit 1; }
echo "Connected!"

# Install dependencies
echo "[2/10] Installing dependencies..."
eval "$SSH_CMD 'sudo apt update && sudo apt install -y caddy python3-pip python3-flask xinput xdotool unclutter chromium-browser && sudo pip3 install qrcode pillow --break-system-packages'" 2>&1 | tail -5

# Create directories
echo "[3/10] Creating directories..."
eval "$SSH_CMD 'sudo mkdir -p /var/www/vernis /opt/vernis/scripts /opt/vernis/csv-library /opt/vernis/nfts && sudo chown -R $PI_USER:$PI_USER /var/www/vernis /opt/vernis'"

# Copy web files
echo "[4/10] Copying web files..."
cd "$PROJECT_DIR"
for f in *.html *.css *.js *.svg; do
    [ -f "$f" ] && cat "$f" | eval "$SSH_CMD 'cat > /var/www/vernis/$f'"
done
echo "Web files copied"

# Copy backend
echo "[5/10] Copying backend..."
cat backend/app.py | eval "$SSH_CMD 'cat > /opt/vernis/app.py'"
echo "Backend copied"

# Copy scripts
echo "[6/10] Copying scripts..."
cd "$PROJECT_DIR/scripts"
for f in *.sh *.py; do
    [ -f "$f" ] && cat "$f" | eval "$SSH_CMD 'cat > /opt/vernis/scripts/$f'"
done
eval "$SSH_CMD 'chmod +x /opt/vernis/scripts/*.sh /opt/vernis/scripts/*.py 2>/dev/null'"
echo "Scripts copied"

# Copy CSV library
echo "[7/10] Copying CSV library..."
cd "$PROJECT_DIR/csv-library"
for f in *.csv; do
    [ -f "$f" ] && cat "$f" | eval "$SSH_CMD 'cat > /opt/vernis/csv-library/$f'"
done
echo "CSV library copied"

# Configure Caddy
echo "[8/10] Configuring Caddy..."
eval "$SSH_CMD \"sudo tee /etc/caddy/Caddyfile > /dev/null << 'CADDYEOF'
:80 {
    root * /var/www/vernis
    file_server
    reverse_proxy /api/* localhost:5000
    reverse_proxy /nfts/* localhost:5000
    reverse_proxy /nfts-ext/* localhost:5000
    encode gzip
    header {
        Cache-Control \\\"no-cache, no-store, must-revalidate\\\"
    }
}
CADDYEOF
sudo systemctl restart caddy && sudo systemctl enable caddy\""

# Configure Flask service
echo "[9/10] Configuring Flask API..."
eval "$SSH_CMD \"sudo tee /etc/systemd/system/vernis-api.service > /dev/null << 'SERVICEEOF'
[Unit]
Description=Vernis Flask API
After=network.target

[Service]
Type=simple
User=$PI_USER
WorkingDirectory=/opt/vernis
ExecStart=/usr/bin/python3 /opt/vernis/app.py
Restart=always
RestartSec=5
Environment=FLASK_ENV=production

[Install]
WantedBy=multi-user.target
SERVICEEOF
sudo systemctl daemon-reload && sudo systemctl enable vernis-api && sudo systemctl restart vernis-api\""

# Setup kiosk and touch
echo "[10/10] Setting up kiosk and display..."

# Setup labwc autostart (for Wayland - newer Pi OS)
eval "$SSH_CMD 'mkdir -p ~/.config/labwc && cat > ~/.config/labwc/autostart << LABWCEOF
# Vernis Kiosk Mode - Clean desktop for kiosk
pkill -f lwrespawn 2>/dev/null
pkill -f wf-panel-pi 2>/dev/null
pkill -f pcmanfm 2>/dev/null
/opt/vernis/scripts/kiosk-launcher.sh &
LABWCEOF
chmod +x ~/.config/labwc/autostart'"

# Also create XDG autostart (for X11 - older Pi OS fallback)
eval "$SSH_CMD 'mkdir -p ~/.config/autostart && cat > ~/.config/autostart/vernis-kiosk.desktop << KIOSKEOF
[Desktop Entry]
Type=Application
Name=Vernis Kiosk
Exec=/opt/vernis/scripts/kiosk-launcher.sh
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
KIOSKEOF'"

# Setup touch service
eval "$SSH_CMD \"sudo tee /etc/systemd/system/vernis-touch.service > /dev/null << 'TOUCHEOF'
[Unit]
Description=Vernis Touch Rotation
After=display-manager.service

[Service]
Type=oneshot
ExecStart=/opt/vernis/scripts/touch-rotate.sh
RemainAfterExit=yes

[Install]
WantedBy=graphical.target
TOUCHEOF
sudo systemctl daemon-reload && sudo systemctl enable vernis-touch.service\""

# Run Waveshare display setup
echo "Running Waveshare display setup..."
eval "$SSH_CMD 'sudo bash /opt/vernis/scripts/setup-waveshare-4dpi.sh'" 2>&1 | tail -10

echo ""
echo "==========================================="
echo "Deployment Complete!"
echo "==========================================="
echo ""
echo "Test: http://$PI_IP"
echo ""
read -p "Reboot Pi now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    eval "$SSH_CMD 'sudo reboot'" && echo "Rebooting..."
fi
