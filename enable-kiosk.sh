#!/bin/bash
##############################################
# Vernis v3 - Enable Kiosk Mode
# Run this on a Pi to enable fullscreen display mode
##############################################

set -e

echo "=========================================="
echo "Vernis v3 - Enable Kiosk Mode"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash enable-kiosk.sh"
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-pi}
USER_HOME=$(eval echo ~$ACTUAL_USER)

echo "Setting up kiosk mode for user: $ACTUAL_USER"
echo ""

# Clean up any broken package states
echo "Checking for broken packages..."
export DEBIAN_FRONTEND=noninteractive
export DEBIAN_PRIORITY=critical
export DEBCONF_NONINTERACTIVE_SEEN=true
dpkg --configure -a -o Dpkg::Options::="--force-confnew" -o Dpkg::Options::="--force-confdef" 2>&1 || true
apt-get install -f -y -o Dpkg::Options::="--force-confnew" -o Dpkg::Options::="--force-confdef" 2>&1 || true

# Install required packages
echo "Installing display packages..."
apt-get update

# Install base packages first
apt-get install -y -o Dpkg::Options::="--force-confnew" -o Dpkg::Options::="--force-confdef" lightdm chromium unclutter xserver-xorg xinit

# Handle raspberrypi-ui-mods conflict with pi-greeter
echo "Installing raspberrypi-ui-mods (may have file conflicts)..."
apt-get install -y -o Dpkg::Options::="--force-confnew" -o Dpkg::Options::="--force-confdef" raspberrypi-ui-mods 2>&1 || {
    echo "Conflict detected, forcing installation..."
    dpkg -i --force-overwrite --force-confnew --force-confdef /var/cache/apt/archives/raspberrypi-ui-mods*.deb 2>&1 || true
    apt-get install -f -y -o Dpkg::Options::="--force-confnew" -o Dpkg::Options::="--force-confdef" 2>&1 || true
}

# Auto-login configuration
echo "Configuring auto-login..."
mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/01-autologin.conf <<EOF
[Seat:*]
autologin-user=$ACTUAL_USER
autologin-user-timeout=0
user-session=LXDE-pi
autologin-session=LXDE-pi
EOF

# Create autostart directory
echo "Setting up autostart..."
sudo -u $ACTUAL_USER mkdir -p $USER_HOME/.config/lxsession/LXDE-pi/

# Create autostart config
cat > $USER_HOME/.config/lxsession/LXDE-pi/autostart <<EOF
# Vernis v3 - Kiosk Mode Autostart

# Disable screen blanking
@xset s off
@xset -dpms
@xset s noblank

# Hide cursor after 0.1s of inactivity
@unclutter -idle 0.1 -root

# Start kiosk mode browser pointing to gallery (auto-detects screen resolution)
@chromium --kiosk \
  --noerrdialogs \
  --incognito \
  --disable-infobars \
  --start-fullscreen \
  --disable-translate \
  --disable-features=TranslateUI \
  --check-for-update-interval=31536000 \
  http://localhost/gallery.html
EOF

chown $ACTUAL_USER:$ACTUAL_USER $USER_HOME/.config/lxsession/LXDE-pi/autostart

# Enable graphical target
systemctl set-default graphical.target

echo ""
echo "=========================================="
echo "Kiosk Mode Enabled!"
echo "=========================================="
echo ""
echo "The Pi will boot into fullscreen gallery mode."
echo "On boot, it will display: http://localhost/gallery.html"
echo ""
echo "Reboot to activate kiosk mode:"
echo "  sudo reboot"
echo ""
echo "To disable kiosk mode later:"
echo "  sudo systemctl set-default multi-user.target"
echo "=========================================="
