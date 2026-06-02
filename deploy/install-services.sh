#!/bin/bash
#
# Install Vernis systemd services (including BLE Provisioning)
#

set -e

DEPLOY_DIR="/opt/vernis/deploy"
SYSTEMD_DIR="/etc/systemd/system"

echo "Installing Vernis systemd services..."

# Install Dependencies
echo "Installing Bluetooth dependencies..."
apt-get update
apt-get install -y python3-dbus python3-gi bluez

# Copy service files
# Note: Assuming files are in /opt/vernis/systemd/ or deploy dir
cp "/opt/vernis/systemd/vernis-api.service" "$SYSTEMD_DIR/" || echo "Warning: API service not found"
cp "/opt/vernis/systemd/vernis-ap-check.service" "$SYSTEMD_DIR/" || echo "Warning: AP service not found"
cp "/opt/vernis/systemd/vernis-ap-check.timer" "$SYSTEMD_DIR/" || echo "Warning: AP timer not found"
cp "/opt/vernis/systemd/vernis-bluetooth.service" "$SYSTEMD_DIR/" || echo "Warning: BLE service not found"

# Reload systemd
systemctl daemon-reload
systemctl enable vernis-api.service
systemctl enable vernis-ap-check.timer
systemctl enable vernis-bluetooth.service

echo "✓ Services installed and enabled successfully"
