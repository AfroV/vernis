#!/bin/bash
##############################################
# Vernis v3 - Display Border Fix Script
# Run this if your screen has black borders and doesn't fill horizontally
##############################################

echo "=========================================="
echo "Vernis v3 - Fixing Display Borders"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash fix-display-borders.sh"
    exit 1
fi

echo "This script will disable overscan to eliminate black borders."
echo ""

# Backup the config file
cp /boot/config.txt /boot/config.txt.backup
echo "Backed up /boot/config.txt to /boot/config.txt.backup"

# Check if disable_overscan is already set
if grep -q "^disable_overscan=1" /boot/config.txt; then
    echo "Overscan is already disabled in /boot/config.txt"
else
    # Check if there's a commented disable_overscan line
    if grep -q "^#disable_overscan" /boot/config.txt; then
        # Uncomment it
        sed -i 's/^#disable_overscan=.*/disable_overscan=1/' /boot/config.txt
        echo "Uncommented and enabled disable_overscan=1"
    else
        # Add it to the file
        echo "" >> /boot/config.txt
        echo "# Disable overscan to fill the entire screen" >> /boot/config.txt
        echo "disable_overscan=1" >> /boot/config.txt
        echo "Added disable_overscan=1 to /boot/config.txt"
    fi
fi

echo ""
echo "=========================================="
echo "Display Configuration Updated!"
echo "=========================================="
echo ""
echo "Changes made:"
echo "  - Disabled overscan in /boot/config.txt"
echo "  - This will eliminate black borders on your display"
echo ""
echo "A reboot is required for changes to take effect."
echo ""
read -p "Reboot now? (y/n): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Rebooting in 3 seconds..."
    sleep 3
    reboot
else
    echo "Please reboot manually when ready: sudo reboot"
fi
