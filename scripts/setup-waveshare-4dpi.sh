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
        if [ -t 0 ]; then
            read -p "Press Enter after manually installing overlays, or Ctrl+C to cancel..."
        else
            echo "(non-interactive: continuing without manual overlay install)"
        fi
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

# Working overlay set (DPI-DISPLAY-TROUBLESHOOTING.md, Issue 5). Not
# `waveshare-4dpi`: it conflicts with vc4-kms-DPI-4inch (backlight on, no image).
# Each line is added only if missing, so re-runs and old configs converge.
sed -i 's/^dtoverlay=waveshare-4dpi[[:space:]]*$/#dtoverlay=waveshare-4dpi  # conflicts with vc4-kms-DPI-4inch/' "$CONFIG_FILE"
if ! grep -q "^dtoverlay=vc4-kms-v3d" "$CONFIG_FILE"; then
    echo "dtoverlay=vc4-kms-v3d" >> "$CONFIG_FILE"
fi
if ! grep -q "Waveshare 4inch DPI LCD (C) Configuration" "$CONFIG_FILE"; then
    cat >> "$CONFIG_FILE" << 'EOF'

# =========================================
# Waveshare 4inch DPI LCD (C) Configuration
# Added by Vernis setup script
# (waveshare-4dpi stays off: it conflicts with vc4-kms-DPI-4inch)
# =========================================
EOF
fi
for OVERLAY in vc4-kms-DPI-4inch waveshare-4dpic-4b waveshare-touch-4dpi; do
    if grep -q "^dtoverlay=$OVERLAY\b" "$CONFIG_FILE"; then
        echo "  $OVERLAY already enabled"
    else
        echo "dtoverlay=$OVERLAY" >> "$CONFIG_FILE"
        echo "  Added dtoverlay=$OVERLAY"
    fi
done

# No backlight service. Older versions installed dpi-backlight.service to hold
# GPIO 18 low at boot; it was linked to a dim, striped picture
# (DPI-DISPLAY-TROUBLESHOOTING.md, Issue 1) and install-vernis.sh always
# disabled it. Vernis's Screen off / on controls drive GPIO 18 themselves.
# Remove one left by an older version.
if [ -f /etc/systemd/system/dpi-backlight.service ]; then
    systemctl disable --now dpi-backlight 2>/dev/null || true
    rm -f /etc/systemd/system/dpi-backlight.service
    systemctl daemon-reload
    echo "Removed old dpi-backlight.service"
fi

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
echo "4. Rotation and touch: the Vernis installer sets the built-in screen to 90°."
echo "   Change it in Vernis Settings > Display; touch is remapped to match."
echo ""
echo "Reference: https://www.waveshare.com/wiki/4inch_DPI_LCD_(C)"
echo ""
echo "==========================================="

# Ask to reboot — only when run interactively (a TTY). In the automated installer
# there is no stdin, so `read` would hit EOF and (under set -e) abort the install.
if [ -t 0 ]; then
    read -p "Reboot now? (y/n): " REBOOT_NOW
    if [ "$REBOOT_NOW" = "y" ] || [ "$REBOOT_NOW" = "Y" ]; then
        echo "Rebooting in 5 seconds..."
        sleep 5
        reboot
    fi
fi
