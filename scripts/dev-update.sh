#!/bin/bash
##############################################
# Vernis v3 - Development Update Script
# Pulls latest files from development machine for testing
# Usage: sudo bash dev-update.sh <dev_server_url>
# Example: sudo bash dev-update.sh 192.168.1.100:8080
##############################################

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash dev-update.sh <dev_server_url>"
    exit 1
fi

if [ -z "$1" ]; then
    echo "Usage: sudo bash dev-update.sh <dev_server_url>"
    echo "Example: sudo bash dev-update.sh 192.168.1.100:8080"
    exit 1
fi

DEV_SERVER="$1"
TEMP_DIR="/tmp/vernis-dev-update"

echo "=========================================="
echo "Vernis v3 - Development Update"
echo "=========================================="
echo ""
echo "Fetching from: http://$DEV_SERVER"
echo ""

# Create temp directory
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"
cd "$TEMP_DIR"

# Download file list (we'll use wget to mirror specific files)
echo "[1/6] Downloading web files..."
wget -q "http://$DEV_SERVER/index.html" || { echo "❌ Failed to connect to dev server"; exit 1; }
wget -q "http://$DEV_SERVER/gallery.html"
wget -q "http://$DEV_SERVER/library.html"
wget -q "http://$DEV_SERVER/settings.html"
wget -q "http://$DEV_SERVER/add.html"
wget -q "http://$DEV_SERVER/manage.html"
wget -q "http://$DEV_SERVER/wallet-tool.html" 2>/dev/null || true
wget -q "http://$DEV_SERVER/vernis-themes.css"
echo "✅ Web files downloaded"

echo "[2/6] Downloading backend..."
mkdir -p backend
wget -q "http://$DEV_SERVER/backend/app.py" -O backend/app.py
echo "✅ Backend downloaded"

echo "[3/6] Downloading scripts..."
mkdir -p scripts
wget -q "http://$DEV_SERVER/scripts/wifi-fallback-ap.sh" -O scripts/wifi-fallback-ap.sh 2>/dev/null || true
wget -q "http://$DEV_SERVER/scripts/nft_downloader_advanced.py" -O scripts/nft_downloader_advanced.py 2>/dev/null || true
echo "✅ Scripts downloaded"

echo "[4/6] Installing updates..."
# Copy web files
cp *.html /var/www/vernis/
cp *.css /var/www/vernis/ 2>/dev/null || true
chown -R caddy:caddy /var/www/vernis
echo "✅ Web files installed"

# Copy backend
cp backend/app.py /opt/vernis/
echo "✅ Backend installed"

# Copy scripts if they exist
if [ -d "scripts" ]; then
    cp scripts/*.sh /opt/vernis/scripts/ 2>/dev/null || true
    cp scripts/*.py /opt/vernis/scripts/ 2>/dev/null || true
    chmod +x /opt/vernis/scripts/*.sh 2>/dev/null || true
    chmod +x /opt/vernis/scripts/*.py 2>/dev/null || true
fi
echo "✅ Scripts installed"

echo "[5/6] Restarting services..."
systemctl restart vernis-api.service
systemctl restart caddy
echo "✅ Services restarted"

echo "[6/6] Cleaning up..."
cd /
rm -rf "$TEMP_DIR"
echo "✅ Cleanup complete"

echo ""
echo "=========================================="
echo "✅ Development Update Complete!"
echo "=========================================="
echo ""
echo "Updated components:"
echo "  - Web UI (HTML/CSS files)"
echo "  - Flask API backend"
echo "  - Helper scripts"
echo ""
echo "Services restarted:"
echo "  - vernis-api.service"
echo "  - caddy"
echo ""
echo "You can now test your changes at http://vernis.local"
echo ""
