#!/bin/bash
##############################################
# Vernis v3 - Simple Kiosk Mode Setup
# Uses auto-login to console + startx approach
##############################################

set -e

echo "=========================================="
echo "Vernis v3 - Simple Kiosk Mode Setup"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash enable-kiosk-simple.sh"
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-pi}
USER_HOME=$(eval echo ~$ACTUAL_USER)

echo "Setting up kiosk mode for user: $ACTUAL_USER"
echo ""

# Install minimal required packages
echo "Installing display packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y xserver-xorg xinit chromium unclutter

# Configure auto-login to console (tty1)
echo "Configuring console auto-login..."
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $ACTUAL_USER --noclear %I \$TERM
EOF

# Detect screen resolution
echo "Detecting screen resolution..."
RESOLUTION=$(DISPLAY=:0 xrandr 2>/dev/null | grep '\*' | awk '{print $1}' | head -1)
if [ -z "$RESOLUTION" ]; then
  RESOLUTION="1920x1080"  # Default fallback
fi
echo "Detected resolution: $RESOLUTION"

# Create .xinitrc for X session
echo "Creating X session configuration..."
cat > $USER_HOME/.xinitrc <<EOF
#!/bin/bash
# Vernis v3 Kiosk Mode - X Session

# Disable screen blanking
xset s off
xset -dpms
xset s noblank

# Hide cursor
unclutter -idle 0.1 -root &

# Start chromium in kiosk mode with explicit window size
chromium --kiosk \\
  --noerrdialogs \\
  --incognito \\
  --disable-infobars \\
  --start-fullscreen \\
  --start-maximized \\
  --window-size=$RESOLUTION \\
  --window-position=0,0 \\
  --force-device-scale-factor=1 \\
  --disable-translate \\
  --disable-features=TranslateUI \\
  --check-for-update-interval=31536000 \\
  --disable-session-crashed-bubble \\
  --disable-component-update \\
  http://localhost/gallery.html
EOF

chmod +x $USER_HOME/.xinitrc
chown $ACTUAL_USER:$ACTUAL_USER $USER_HOME/.xinitrc

# Auto-start X on login
echo "Configuring auto-start X..."
cat >> $USER_HOME/.bash_profile <<'EOF'

# Auto-start X session on tty1
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx
fi
EOF

chown $ACTUAL_USER:$ACTUAL_USER $USER_HOME/.bash_profile

# Set default to multi-user (console) target
systemctl set-default multi-user.target

echo ""
echo "=========================================="
echo "Simple Kiosk Mode Enabled!"
echo "=========================================="
echo ""
echo "The Pi will:"
echo "  1. Auto-login to console as $ACTUAL_USER"
echo "  2. Auto-start X server"
echo "  3. Launch Chromium in fullscreen kiosk mode"
echo "  4. Display: http://localhost/gallery.html"
echo ""
echo "Reboot to activate:"
echo "  sudo reboot"
echo ""
echo "To disable kiosk mode:"
echo "  Remove the X auto-start from ~/.bash_profile"
echo "=========================================="
