#!/bin/bash
# vernis-seal.sh - Prepare device for shipping
#
# Removes all Wi-Fi credentials so the device boots in "Setup Mode"
# for the customer.

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

echo "=========================================="
echo "SEALING VERNIS FOR SHIPPING"
echo "=========================================="

# 1. Clear Wi-Fi Credentials
echo "Removing Wi-Fi configurations..."
rm -f /etc/wpa_supplicant/wpa_supplicant.conf
cat > /etc/wpa_supplicant/wpa_supplicant.conf <<EOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US
EOF

# 2. Clear Logs (Optional transparency)
echo "Clearing logs..."
rm -f /var/log/vernis*
journalctl --vacuum-time=1s

# 3. Reset Setup Wizard
echo "Resetting setup wizard..."
rm -f /opt/vernis/setup-complete.json
rm -f /opt/vernis/password-changed.marker

# 4. Clear History
history -c

echo "=========================================="
echo "DEVICE SEALED."
echo "Wi-Fi is blank. Next boot will trigger BLE Setup."
echo "Powering off in 5 seconds..."
echo "=========================================="
sleep 5
poweroff
