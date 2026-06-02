#!/bin/bash
##############################################
# Vernis Kiosk Mode Toggle
# Run: sudo bash enable-kiosk.sh [enable|disable]
##############################################

set -e

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash enable-kiosk.sh [enable|disable]"
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-pi}

ACTION=${1:-enable}

if [ "$ACTION" = "enable" ]; then
    echo "Enabling kiosk mode for user $ACTUAL_USER..."

    # Create LXDE-pi session file if it doesn't exist
    if [ ! -f /usr/share/xsessions/LXDE-pi.desktop ]; then
        cat > /usr/share/xsessions/LXDE-pi.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=LXDE-pi
Comment=LXDE-pi Desktop Session
Exec=/usr/bin/lxsession -s LXDE-pi -e LXDE
TryExec=/usr/bin/lxsession
Icon=lxde
EOF
        echo "  - Created LXDE-pi session"
    fi

    # Configure auto-login with LXDE-pi session
    mkdir -p /etc/lightdm/lightdm.conf.d
    cat > /etc/lightdm/lightdm.conf.d/01-autologin.conf <<EOF
[Seat:*]
autologin-user=$ACTUAL_USER
autologin-user-timeout=0
user-session=LXDE-pi
autologin-session=LXDE-pi
EOF
    echo "  - Auto-login configured"

    # Update main lightdm.conf to use X11/LXDE instead of Wayland
    if [ -f /etc/lightdm/lightdm.conf ]; then
        sed -i 's/^user-session=.*/user-session=LXDE-pi/' /etc/lightdm/lightdm.conf
        sed -i 's/^autologin-session=.*/autologin-session=LXDE-pi/' /etc/lightdm/lightdm.conf
        echo "  - Switched to X11/LXDE session"
    fi

    # Setup autostart
    AUTOSTART_DIR="/home/$ACTUAL_USER/.config/lxsession/LXDE-pi"
    mkdir -p "$AUTOSTART_DIR"
    cat > "$AUTOSTART_DIR/autostart" <<'EOF'
@xset s off
@xset -dpms
@xset s noblank
@unclutter -idle 0.5 -root
@sleep 2
@bash /opt/vernis/scripts/touch-rotate.sh
@sleep 1
@bash /opt/vernis/scripts/kiosk-launcher.sh
EOF
    chown -R $ACTUAL_USER:$ACTUAL_USER "/home/$ACTUAL_USER/.config"
    echo "  - Autostart configured"

    # Enable graphical target
    systemctl set-default graphical.target
    echo "  - Graphical boot enabled"

    # Enable watchdog if available
    if [ -f /etc/systemd/system/vernis-watchdog.service ]; then
        systemctl enable vernis-watchdog.service
        systemctl start vernis-watchdog.service 2>/dev/null || true
        echo "  - Watchdog enabled"
    fi

    # Setup touch rotation service (syncs touch input with display rotation)
    if [ -f /opt/vernis/scripts/touch-rotate.sh ]; then
        chmod +x /opt/vernis/scripts/touch-rotate.sh
        cat > /etc/systemd/system/vernis-touch.service <<'EOF'
[Unit]
Description=Vernis Touch Rotation
After=display-manager.service
Wants=display-manager.service

[Service]
Type=oneshot
ExecStart=/opt/vernis/scripts/touch-rotate.sh
RemainAfterExit=yes
Environment=DISPLAY=:0

[Install]
WantedBy=graphical.target
EOF
        systemctl daemon-reload
        systemctl enable vernis-touch.service
        echo "  - Touch rotation service enabled"
    fi

    echo ""
    echo "Kiosk mode ENABLED!"
    echo "Reboot to apply: sudo reboot"

elif [ "$ACTION" = "disable" ]; then
    echo "Disabling kiosk mode..."

    # Remove auto-login config
    rm -f /etc/lightdm/lightdm.conf.d/01-autologin.conf
    echo "  - Auto-login disabled"

    # Restore Wayland session in main config (optional, for desktop use)
    if [ -f /etc/lightdm/lightdm.conf ]; then
        sed -i 's/^user-session=LXDE-pi/user-session=rpd-labwc/' /etc/lightdm/lightdm.conf
        sed -i 's/^autologin-session=LXDE-pi/autologin-session=rpd-labwc/' /etc/lightdm/lightdm.conf
        echo "  - Restored Wayland session"
    fi

    # Remove autostart (keep directory)
    AUTOSTART_FILE="/home/$ACTUAL_USER/.config/lxsession/LXDE-pi/autostart"
    if [ -f "$AUTOSTART_FILE" ]; then
        rm -f "$AUTOSTART_FILE"
        echo "  - Autostart removed"
    fi

    # Set multi-user target (headless)
    systemctl set-default multi-user.target
    echo "  - Headless boot enabled"

    # Disable watchdog
    if systemctl is-enabled vernis-watchdog.service 2>/dev/null; then
        systemctl disable vernis-watchdog.service
        systemctl stop vernis-watchdog.service 2>/dev/null || true
        echo "  - Watchdog disabled"
    fi

    # Disable touch rotation service
    if systemctl is-enabled vernis-touch.service 2>/dev/null; then
        systemctl disable vernis-touch.service
        systemctl stop vernis-touch.service 2>/dev/null || true
        echo "  - Touch rotation disabled"
    fi

    echo ""
    echo "Kiosk mode DISABLED!"
    echo "Reboot to apply: sudo reboot"

else
    echo "Usage: sudo bash enable-kiosk.sh [enable|disable]"
    echo ""
    echo "  enable  - Boot into fullscreen gallery kiosk"
    echo "  disable - Boot into headless command line"
    exit 1
fi
