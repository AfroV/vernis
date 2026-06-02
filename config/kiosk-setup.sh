#!/bin/bash
##############################################
# Vernis v3 - Kiosk Mode Setup Script
# Run this ONLY on Vernis v2 with built-in screen
##############################################

echo "Setting up kiosk mode for Vernis v2..."

# Create autostart directory if it doesn't exist
mkdir -p /home/pi/.config/lxsession/LXDE-pi/

# Copy autostart configuration
cat > /home/pi/.config/lxsession/LXDE-pi/autostart <<'EOF'
# Vernis v3 - Kiosk Mode Autostart
@xset s off
@xset -dpms
@xset s noblank
@unclutter -idle 0.1 -root
@chromium-browser --kiosk \
  --noerrdialogs \
  --incognito \
  --disable-infobars \
  --start-fullscreen \
  --disable-translate \
  --disable-features=TranslateUI \
  --check-for-update-interval=31536000 \
  http://vernis.local/display.html
EOF

# Set correct ownership
chown -R pi:pi /home/pi/.config/

# Install required packages
apt-get update
apt-get install -y chromium-browser unclutter

echo "Kiosk mode configured!"
echo "Reboot to start in fullscreen gallery mode"
