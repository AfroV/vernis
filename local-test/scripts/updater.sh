#!/bin/bash
##############################################
# Vernis v3 - System Updater
# Automatically downloads and applies updates from the web
# 
# Usage: bash updater.sh
##############################################

set -e

UPDATE_URL="https://yourdomain.com/vernis/latest.tar.gz"
BACKUP_DIR="/opt/vernis/backup-$(date +%Y%m%d-%H%M%S)"
INSTALL_DIR="/opt/vernis"
WEB_DIR="/var/www/vernis"
TEMP_DIR="/tmp/vernis-update"

echo "=========================================="
echo "Vernis v3 - OTA Update"
echo "=========================================="

# Create backup of current installation
echo "Creating backup..."
mkdir -p "$BACKUP_DIR"
cp -r /opt/vernis/* "$BACKUP_DIR/" || true
cp -r /var/www/vernis/* "$BACKUP_DIR/www/" || true

# Download update
echo "Downloading update from $UPDATE_URL..."
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"
cd "$TEMP_DIR"

if curl -fsSL "$UPDATE_URL" -o latest.tar.gz; then
    echo "Download successful"
else
    echo "Download failed! Aborting update."
    exit 1
fi

# Extract update
echo "Extracting update..."
tar -xzf latest.tar.gz

# Apply update
echo "Applying update..."

# Update web files
if [ -d "www" ]; then
    cp -r www/* /var/www/vernis/
    echo "Web files updated"
fi

# Update backend
if [ -f "app.py" ]; then
    cp app.py /opt/vernis/
    echo "API updated"
fi

# Update scripts
if [ -d "scripts" ]; then
    cp -r scripts/* /opt/vernis/scripts/
    chmod +x /opt/vernis/scripts/*.sh
    echo "Scripts updated"
fi

# Update systemd services if changed
if [ -d "systemd" ]; then
    cp -r systemd/* /etc/systemd/system/
    systemctl daemon-reload
    echo "Systemd services updated"
fi

# Restart services
echo "Restarting services..."
systemctl restart vernis-api
systemctl restart caddy

# Cleanup
rm -rf "$TEMP_DIR"

echo "=========================================="
echo "Update completed successfully!"
echo "Backup saved to: $BACKUP_DIR"
echo "Rebooting in 10 seconds..."
echo "=========================================="

sleep 10
reboot
