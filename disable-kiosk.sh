#!/bin/bash
##############################################
# Vernis v3 - Disable Kiosk Mode
# Run this to return to normal boot mode
##############################################

set -e

echo "=========================================="
echo "Vernis v3 - Disable Kiosk Mode"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash disable-kiosk.sh"
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-pi}
USER_HOME=$(eval echo ~$ACTUAL_USER)

echo "Disabling kiosk mode for user: $ACTUAL_USER"
echo ""

# Remove auto-login
echo "Removing auto-login..."
rm -f /etc/lightdm/lightdm.conf.d/01-autologin.conf

# Remove autostart
echo "Removing kiosk autostart..."
rm -f $USER_HOME/.config/lxsession/LXDE-pi/autostart

# Set back to multi-user target (no GUI)
systemctl set-default multi-user.target

echo ""
echo "=========================================="
echo "Kiosk Mode Disabled!"
echo "=========================================="
echo ""
echo "The Pi will boot to command line."
echo ""
echo "Reboot to apply changes:"
echo "  sudo reboot"
echo "=========================================="
