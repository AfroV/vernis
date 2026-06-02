#!/bin/bash
##############################################
# Vernis - Waveshare 4inch DPI LCD (C) Setup
# Run this script to configure the display
##############################################

set -e

echo "==========================================="
echo "Waveshare 4inch DPI LCD (C) Setup"
echo "==========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash setup-waveshare-4dpi.sh"
    exit 1
fi

# Detect boot config location (Pi 5 / newer OS uses /boot/firmware/)
if [ -d "/boot/firmware" ]; then
    BOOT_DIR="/boot/firmware"
else
    BOOT_DIR="/boot"
fi

CONFIG_FILE="$BOOT_DIR/config.txt"
OVERLAYS_DIR="$BOOT_DIR/overlays"

echo "Boot directory: $BOOT_DIR"
echo "Config file: $CONFIG_FILE"
echo ""

# Backup existing config
BACKUP_FILE="${CONFIG_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$CONFIG_FILE" "$BACKUP_FILE"
echo "Backed up config to: $BACKUP_FILE"

# Check if overlays are already installed
OVERLAYS_INSTALLED=0
if [ -f "$OVERLAYS_DIR/waveshare-4dpic-4b.dtbo" ]; then
    OVERLAYS_INSTALLED=1
    echo "Waveshare overlay files found in $OVERLAYS_DIR"
fi

# Download and install overlay files if not present
if [ "$OVERLAYS_INSTALLED" = "0" ]; then
    echo ""
    echo "Downloading Waveshare overlay files..."

    # Create temp directory
    TEMP_DIR=$(mktemp -d)
    cd "$TEMP_DIR"

    # Download from Waveshare (correct URL for Bookworm/Bullseye)
    DOWNLOAD_URL="https://files.waveshare.com/upload/8/8a/4DPIC-DTBO.zip"

    if wget -q --show-progress "$DOWNLOAD_URL" -O 4DPIC-DTBO.zip 2>/dev/null; then
        echo "Extracting overlay files..."
        unzip -q 4DPIC-DTBO.zip

        # Copy .dtbo files to overlays directory
        find . -name "*.dtbo" -exec cp {} "$OVERLAYS_DIR/" \;
        echo "Overlay files installed to $OVERLAYS_DIR"
    else
        echo ""
        echo "WARNING: Could not download overlay files automatically."
        echo "Please download manually from:"
        echo "  https://www.waveshare.com/wiki/4inch_DPI_LCD_(C)"
        echo ""
        echo "Look for: '4DPIC-DTBO.zip' (for Bookworm/Bullseye)"
        echo "Extract and copy .dtbo files to: $OVERLAYS_DIR/"
        echo ""
        read -p "Press Enter after manually installing overlays, or Ctrl+C to cancel..."
    fi

    # Cleanup
    cd /
    rm -rf "$TEMP_DIR"
fi

# Configure /boot/config.txt
echo ""
echo "Configuring $CONFIG_FILE..."

# Comment out conflicting overlays
sed -i 's/^dtoverlay=vc4-fkms-v3d/#dtoverlay=vc4-fkms-v3d  # Disabled for DPI LCD/' "$CONFIG_FILE"
sed -i 's/^display_auto_detect=1/#display_auto_detect=1  # Disabled for DPI LCD/' "$CONFIG_FILE"

# Check if Waveshare config already exists
if grep -q "waveshare-4dpi" "$CONFIG_FILE"; then
    echo "Waveshare DPI config already exists in config.txt"
else
    # Add Waveshare DPI LCD configuration
    cat >> "$CONFIG_FILE" << 'EOF'

# =========================================
# Waveshare 4inch DPI LCD (C) Configuration
# Added by Vernis setup script
# =========================================
dtoverlay=vc4-kms-DPI-4inch
dtoverlay=waveshare-4dpic-4b
dtoverlay=waveshare-4dpi
dtoverlay=waveshare-touch-4dpi
EOF
    echo "Added Waveshare DPI LCD configuration to config.txt"
fi

# Create backlight service (GPIO18, active LOW)
echo ""
echo "Creating backlight service..."
cat > /etc/systemd/system/dpi-backlight.service << 'EOF'
[Unit]
Description=DPI LCD Backlight
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/bin/pinctrl set 18 op dl
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable dpi-backlight
echo "Backlight service enabled (GPIO18, active LOW)"

echo ""
echo "Display configuration complete!"
echo ""
echo "==========================================="
echo "Next Steps:"
echo "==========================================="
echo ""
echo "1. Reboot the device:"
echo "   sudo reboot"
echo ""
echo "2. Wait ~30 seconds for the display to initialize"
echo ""
echo "3. If the display doesn't work:"
echo "   - Connect an HDMI monitor to verify Pi boots"
echo "   - Check backlight (faint glow = config issue, no glow = connection/power)"
echo "   - Try editing $CONFIG_FILE and enabling additional overlays"
echo ""
echo "4. To rotate display (after it works):"
echo "   - Use Screen Configuration tool: DPI-1 > Orientation"
echo "   - Or add to config.txt: display_rotate=1 (90°), 2 (180°), 3 (270°)"
echo ""
echo "5. If touch is not aligned after rotation:"
echo "   - The waveshare-touch-4dpi overlay should auto-sync"
echo "   - Or calibrate with: sudo apt install xinput-calibrator && xinput_calibrator"
echo ""
echo "Reference: https://www.waveshare.com/wiki/4inch_DPI_LCD_(C)"
echo ""
echo "==========================================="

# Ask to reboot
read -p "Reboot now? (y/n): " REBOOT_NOW
if [ "$REBOOT_NOW" = "y" ] || [ "$REBOOT_NOW" = "Y" ]; then
    echo "Rebooting in 5 seconds..."
    sleep 5
    reboot
fi
