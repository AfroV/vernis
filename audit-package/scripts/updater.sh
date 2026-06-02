#!/bin/bash
##############################################
# Vernis v3 - OTA Updater
# Downloads and applies updates from a URL or local package
#
# Usage:
#   bash updater.sh                    # Use URL from update-config.json
#   bash updater.sh /path/to/pkg.tar.gz  # Install from local package
##############################################

set -e

BACKUP_DIR="/opt/vernis/backup-$(date +%Y%m%d-%H%M%S)"
INSTALL_DIR="/opt/vernis"
WEB_DIR="/var/www/vernis"
TEMP_DIR="/tmp/vernis-update"
CONFIG_FILE="/opt/vernis/update-config.json"

echo "=========================================="
echo "Vernis v3 - OTA Update"
echo "=========================================="

# Determine update source
if [ -n "$1" ] && [ -f "$1" ]; then
    # Local package file
    PACKAGE_FILE="$1"
    echo "Installing from local package: $PACKAGE_FILE"
elif [ -n "$UPDATE_URL" ]; then
    # URL from environment variable
    echo "Update URL: $UPDATE_URL"
elif [ -f "$CONFIG_FILE" ]; then
    # Read URL from config (set via Settings > Update Configuration)
    UPDATE_URL=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('update_url',''))" 2>/dev/null)
    if [ -z "$UPDATE_URL" ]; then
        echo "No update URL configured."
        echo "Set the update URL in Settings > System > Update Configuration,"
        echo "or pass a package file: bash updater.sh /path/to/vernis-update.tar.gz"
        exit 1
    fi
    echo "Update URL (from config): $UPDATE_URL"
else
    echo "No update URL configured."
    echo "Set the update URL in Settings > System > Update Configuration,"
    echo "or pass a package file: bash updater.sh /path/to/vernis-update.tar.gz"
    exit 1
fi

# Create backup of current installation
echo ""
echo "[1/5] Creating backup..."
mkdir -p "$BACKUP_DIR/www"
cp -r /opt/vernis/app.py "$BACKUP_DIR/" 2>/dev/null || true
cp -r /opt/vernis/scripts "$BACKUP_DIR/" 2>/dev/null || true
cp -r /var/www/vernis/*.html "$BACKUP_DIR/www/" 2>/dev/null || true
cp -r /var/www/vernis/*.css "$BACKUP_DIR/www/" 2>/dev/null || true
cp -r /var/www/vernis/*.js "$BACKUP_DIR/www/" 2>/dev/null || true
cp -r /var/www/vernis/version.json "$BACKUP_DIR/www/" 2>/dev/null || true
echo "Backup saved to: $BACKUP_DIR"

# Get the update package
echo ""
echo "[2/5] Getting update package..."
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"
cd "$TEMP_DIR"

if [ -n "$PACKAGE_FILE" ]; then
    cp "$PACKAGE_FILE" latest.tar.gz
else
    if curl -fsSL "$UPDATE_URL" -o latest.tar.gz; then
        echo "Download successful"
    else
        echo "Download failed! Aborting update."
        echo "Backup preserved at: $BACKUP_DIR"
        exit 1
    fi
fi

# Extract update
echo ""
echo "[3/5] Extracting update..."
tar -xzf latest.tar.gz

# Apply update
echo ""
echo "[4/5] Applying update..."

# Update web files
if [ -d "www" ]; then
    cp -r www/* /var/www/vernis/
    chown -R caddy:caddy /var/www/vernis 2>/dev/null || true
    echo "  Web files updated"
fi

# Update backend
if [ -f "app.py" ]; then
    cp app.py /opt/vernis/
    echo "  Backend updated"
fi

# Update scripts
if [ -d "scripts" ]; then
    cp -r scripts/* /opt/vernis/scripts/
    chmod +x /opt/vernis/scripts/*.sh 2>/dev/null || true
    chmod +x /opt/vernis/scripts/*.py 2>/dev/null || true
    echo "  Scripts updated"
fi

# Update systemd services if changed
if [ -d "systemd" ]; then
    cp -r systemd/* /etc/systemd/system/
    systemctl daemon-reload
    echo "  Systemd services updated"
fi

# Restart services
echo ""
echo "[5/5] Restarting services..."
systemctl restart vernis-api
systemctl restart caddy

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
echo "=========================================="
echo "Update completed successfully!"
echo "Backup saved to: $BACKUP_DIR"
echo "Rebooting in 5 seconds..."
echo "=========================================="

sleep 5
reboot
