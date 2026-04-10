#!/bin/bash
##############################################
# Vernis Full Installation Script
# Run on a fresh Raspberry Pi OS installation
##############################################

set -e

echo "==========================================="
echo "Vernis Installation Script"
echo "==========================================="

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "Please run as normal user (not root)"
    echo "Usage: bash install-vernis.sh"
    exit 1
fi

USER_NAME=$(whoami)
echo "Installing for user: $USER_NAME"
echo ""

# Step 1: Update and install dependencies
echo "[1/17] Installing dependencies..."
sudo apt update
sudo apt install -y python3-pip python3-flask xinput xdotool unclutter \
    chromium curl libssl-dev gcc wayvnc ufw fail2ban wtype mpv wlrctl log2ram \
    librsvg2-bin imagemagick swaybg \
    bluez bluez-tools bridge-utils dnsmasq python3-dbus python3-gi
sudo pip3 install qrcode pillow requests pycryptodome websocket-client --break-system-packages

# Disable rpcbind (unnecessary NFS service, exposes port 111)
sudo systemctl disable --now rpcbind rpcbind.socket 2>/dev/null || true
echo "rpcbind disabled"

# Install Caddy from official repo (latest stable)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
sudo apt update
sudo apt install -y caddy

# Step 2: Install IPFS (Kubo) for pinning support
echo "[2/17] Installing IPFS (Kubo)..."
KUBO_VERSION="v0.39.0"
ARCH=$(dpkg --print-architecture)
if [ "$ARCH" = "arm64" ]; then
    KUBO_ARCH="linux-arm64"
elif [ "$ARCH" = "armhf" ]; then
    KUBO_ARCH="linux-arm"
else
    KUBO_ARCH="linux-amd64"
fi

if ! command -v ipfs >/dev/null 2>&1; then
    echo "Downloading Kubo ${KUBO_VERSION} for ${KUBO_ARCH}..."
    cd /tmp
    wget -q "https://dist.ipfs.tech/kubo/${KUBO_VERSION}/kubo_${KUBO_VERSION}_${KUBO_ARCH}.tar.gz" -O kubo.tar.gz
    sudo tar xzf kubo.tar.gz
    sudo bash kubo/install.sh
    sudo rm -rf kubo kubo.tar.gz
    echo "Kubo $(ipfs --version) installed"
else
    echo "IPFS already installed: $(ipfs --version)"
fi

# Initialize IPFS repo if not already done
if [ ! -d "$HOME/.ipfs" ]; then
    echo "Initializing IPFS repo with lowpower profile..."
    IPFS_PATH="$HOME/.ipfs" ipfs init --profile=lowpower
    IPFS_PATH="$HOME/.ipfs" ipfs config --json Swarm.ConnMgr.LowWater 20
    IPFS_PATH="$HOME/.ipfs" ipfs config --json Swarm.ConnMgr.HighWater 40
    IPFS_PATH="$HOME/.ipfs" ipfs config --json Datastore.StorageMax '"50GB"'
    IPFS_PATH="$HOME/.ipfs" ipfs config Addresses.Gateway /ip4/127.0.0.1/tcp/8080
    echo "IPFS repo initialized at $HOME/.ipfs"
else
    echo "IPFS repo already exists at $HOME/.ipfs"
fi

# Create IPFS systemd service
echo "Setting up IPFS daemon service..."
sudo tee /etc/systemd/system/ipfs.service > /dev/null << IPFS_EOF
[Unit]
Description=IPFS Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=$USER_NAME
Environment=IPFS_PATH=/home/$USER_NAME/.ipfs
ExecStart=/usr/local/bin/ipfs daemon --enable-gc
Restart=on-failure
RestartSec=10
MemoryMax=512M
Nice=10

[Install]
WantedBy=multi-user.target
IPFS_EOF
sudo systemctl daemon-reload
sudo systemctl enable ipfs
echo "IPFS daemon service enabled"

# Step 3: Create directories and deploy application files
echo "[3/17] Creating directories and deploying files..."
sudo mkdir -p /var/www/vernis /opt/vernis/scripts /opt/vernis/csv-library /opt/vernis/nfts /opt/vernis/files
sudo chown -R $USER_NAME:$USER_NAME /var/www/vernis /opt/vernis

# Deploy files from staging directory (web/, backend/, scripts/ next to install script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR=""
if [ -d "$SCRIPT_DIR/../web" ] && [ -d "$SCRIPT_DIR/../backend" ]; then
    DEPLOY_DIR="$SCRIPT_DIR/.."
elif [ -d "/tmp/vernis-deploy/web" ] && [ -d "/tmp/vernis-deploy/backend" ]; then
    DEPLOY_DIR="/tmp/vernis-deploy"
elif [ -d "$SCRIPT_DIR/web" ] && [ -d "$SCRIPT_DIR/backend" ]; then
    DEPLOY_DIR="$SCRIPT_DIR"
fi

if [ -n "$DEPLOY_DIR" ]; then
    echo "Found staging files in $DEPLOY_DIR"
    if [ -d "$DEPLOY_DIR/web" ]; then
        sudo cp -r "$DEPLOY_DIR/web/"* /var/www/vernis/
        sudo chown -R $USER_NAME:$USER_NAME /var/www/vernis
        echo "  Web UI files deployed to /var/www/vernis/"
    fi
    if [ -d "$DEPLOY_DIR/backend" ]; then
        sudo cp -r "$DEPLOY_DIR/backend/"* /opt/vernis/
        sudo chown -R $USER_NAME:$USER_NAME /opt/vernis
        echo "  Backend files deployed to /opt/vernis/"
    fi
    if [ -d "$DEPLOY_DIR/scripts" ]; then
        sudo cp -r "$DEPLOY_DIR/scripts/"* /opt/vernis/scripts/
        sudo chown -R $USER_NAME:$USER_NAME /opt/vernis/scripts
        echo "  Scripts deployed to /opt/vernis/scripts/"
    fi
    echo "Application files deployed"
else
    echo "No staging directory found (web/, backend/, scripts/)"
    echo "Files can be deployed manually after install completes"
fi

# Step 4: Configure Caddy
echo "[4/17] Configuring Caddy web server..."
sudo tee /etc/caddy/Caddyfile > /dev/null << 'EOF'
localhost, :80 {
    root * /var/www/vernis
    file_server

    reverse_proxy /api/* localhost:5000
    reverse_proxy /nfts/* localhost:5000
    reverse_proxy /nfts-ext/* localhost:5000

    encode gzip

    header {
        Cache-Control "no-cache, no-store, must-revalidate"
    }
}
EOF
sudo systemctl restart caddy
sudo systemctl enable caddy

# Step 5: Configure Flask API service
echo "[5/17] Configuring Flask API service..."
sudo tee /etc/systemd/system/vernis-api.service > /dev/null << APIEOF
[Unit]
Description=Vernis Flask API
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=/opt/vernis
ExecStart=/usr/bin/python3 /opt/vernis/app.py
Restart=always
RestartSec=5
Environment=FLASK_ENV=production
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
APIEOF

# Grant specific sudo permissions the API needs (reboot, systemctl, wlr-randr, etc.)
sudo tee /etc/sudoers.d/vernis-api > /dev/null << SUDOEOF
# Vernis API — limited sudo for specific operations
$USER_NAME ALL=(ALL) NOPASSWD: /sbin/reboot
$USER_NAME ALL=(ALL) NOPASSWD: /sbin/shutdown
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart vernis-*
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart caddy
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart ipfs
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/systemctl start vernis-*
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop vernis-*
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/systemctl status *
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/apt update
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/apt upgrade -y
$USER_NAME ALL=(ALL) NOPASSWD: /usr/sbin/ufw *
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/nmcli *
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/tee /sys/class/thermal/*
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/tee /sys/devices/platform/*
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/tee /boot/firmware/config.txt
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/tee /boot/config.txt
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/tee /boot/firmware/cmdline.txt
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/tee /boot/cmdline.txt
$USER_NAME ALL=(ALL) NOPASSWD: /usr/sbin/badblocks *
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/dpkg *
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/apt-mark *
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/bluetoothctl *
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/brctl *
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/dnsmasq *
SUDOEOF
sudo chmod 440 /etc/sudoers.d/vernis-api
sudo systemctl daemon-reload
sudo systemctl enable vernis-api

# Step 6: Setup kiosk autostart
echo "[6/17] Setting up kiosk mode..."

# Setup labwc autostart (for Wayland - newer Pi OS)
mkdir -p ~/.config/labwc
cat > ~/.config/labwc/autostart << 'EOF'
# Vernis Kiosk Mode - Clean desktop for kiosk
pkill -f lwrespawn 2>/dev/null
pkill -f wf-panel-pi 2>/dev/null
pkill -f pcmanfm 2>/dev/null

# Hide cursor immediately (1s after compositor starts, before Chromium loads)
(sleep 1 && wtype -M alt -M logo -k h -m logo -m alt) &

/opt/vernis/scripts/kiosk-launcher.sh &
EOF
chmod +x ~/.config/labwc/autostart

# Setup labwc rc.xml with HideCursor keybinding (cursor hidden on boot, reappears on mouse move)
if [ -f ~/.config/labwc/rc.xml ]; then
    # Add HideCursor keybinding if not already present
    if ! grep -q "HideCursor" ~/.config/labwc/rc.xml; then
        sed -i 's|</openbox_config>|\t<keyboard>\n\t\t<keybind key="A-W-h">\n\t\t\t<action name="HideCursor" />\n\t\t</keybind>\n\t</keyboard>\n</openbox_config>|' ~/.config/labwc/rc.xml
    fi
else
    cat > ~/.config/labwc/rc.xml << 'RCEOF'
<?xml version="1.0"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
	<keyboard>
		<keybind key="A-W-h">
			<action name="HideCursor" />
		</keybind>
	</keyboard>
</openbox_config>
RCEOF
fi
echo "labwc cursor hiding configured"

# Also create XDG autostart (for X11 - older Pi OS fallback)
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/vernis-kiosk.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=Vernis Kiosk
Exec=/opt/vernis/scripts/kiosk-launcher.sh
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF

# Step 7: Setup touch rotation service
echo "[7/17] Setting up touch rotation service..."
sudo tee /etc/systemd/system/vernis-touch.service > /dev/null << 'EOF'
[Unit]
Description=Vernis Touch Rotation
After=display-manager.service

[Service]
Type=oneshot
ExecStart=/opt/vernis/scripts/touch-rotate.sh
RemainAfterExit=yes

[Install]
WantedBy=graphical.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable vernis-touch.service

# Step 8: Setup watchdog service
echo "[8/17] Setting up screen watchdog service..."
sudo tee /etc/systemd/system/vernis-watchdog.service > /dev/null << WATCHDOG_EOF
[Unit]
Description=Vernis Screen Watchdog
After=graphical.target

[Service]
Type=simple
User=$USER_NAME
ExecStart=/opt/vernis/scripts/watchdog.sh
Restart=always
RestartSec=30

[Install]
WantedBy=graphical.target
WATCHDOG_EOF
sudo systemctl daemon-reload
sudo systemctl enable vernis-watchdog

# Step 9: Setup touch-to-wake service
echo "[9/17] Setting up touch-to-wake service..."
sudo tee /etc/systemd/system/vernis-touch-wake.service > /dev/null << 'EOF'
[Unit]
Description=Vernis Touch-to-Wake
After=multi-user.target
Wants=vernis-api.service

[Service]
Type=simple
ExecStart=/opt/vernis/scripts/touch-to-wake.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable vernis-touch-wake

# Step 10: Compile Hue Entertainment streaming binary and setup service
echo "[10/17] Setting up Hue Entertainment API streaming..."
if [ -f /opt/vernis/scripts/hue-stream.c ]; then
    echo "Compiling hue-stream DTLS client..."
    gcc -O2 -o /opt/vernis/scripts/hue-stream /opt/vernis/scripts/hue-stream.c -lssl -lcrypto
    echo "hue-stream compiled successfully"
else
    echo "hue-stream.c not found. Copy scripts first, then compile:"
    echo "  gcc -O2 -o /opt/vernis/scripts/hue-stream /opt/vernis/scripts/hue-stream.c -lssl -lcrypto"
fi

sudo tee /etc/systemd/system/vernis-hue-stream.service > /dev/null << 'EOF'
[Unit]
Description=Vernis Hue Entertainment Streaming Daemon
After=network-online.target vernis-api.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/vernis/scripts/hue-entertainment-daemon.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=vernis-hue-stream

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
# NOTE: Not auto-enabled — daemon starts on-demand when user presses Hue sun button.
# Auto-starting would hold the Entertainment area active, resetting lights on page exit.
echo "Hue Entertainment streaming service installed (starts on demand)"

# Step 10.5: Setup HDMI hotplug detection
echo "Setting up HDMI hotplug detection..."
sudo tee /etc/udev/rules.d/99-vernis-hdmi.rules > /dev/null << 'EOF'
# Vernis HDMI hotplug — auto-switch display output on connect/disconnect
ACTION=="change", SUBSYSTEM=="drm", RUN+="/opt/vernis/scripts/vernis-hdmi-hotplug.sh"
EOF
sudo udevadm control --reload-rules 2>/dev/null || true
chmod +x /opt/vernis/scripts/display-output.sh /opt/vernis/scripts/vernis-hdmi-hotplug.sh 2>/dev/null || true
echo "HDMI hotplug detection enabled"

# Step 10.6: Install Playfair Display font (used for QR code V logo)
echo "Installing Playfair Display font..."
sudo mkdir -p /usr/share/fonts/truetype/playfair
if [ ! -f /usr/share/fonts/truetype/playfair/PlayfairDisplay-Bold.ttf ]; then
    FONT_URL="https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf"
    if wget -q "$FONT_URL" -O /tmp/PlayfairDisplay.ttf 2>/dev/null; then
        sudo cp /tmp/PlayfairDisplay.ttf /usr/share/fonts/truetype/playfair/PlayfairDisplay-Bold.ttf
        sudo fc-cache -f /usr/share/fonts/truetype/playfair
        rm -f /tmp/PlayfairDisplay.ttf
        echo "Playfair Display font installed"
    else
        echo "WARNING: Could not download Playfair Display font. QR code will use fallback font."
    fi
else
    echo "Playfair Display font already installed"
fi

# Step 10.7: Disable WiFi power save (prevents kworker CPU spikes from brcmfmac interrupt storms)
echo "Disabling WiFi power save..."
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/wifi-powersave.conf << 'WIFIEOF'
[connection]
wifi.powersave = 2
WIFIEOF
iw wlan0 set power_save off 2>/dev/null || true
echo "WiFi power save disabled"

# Step 10.8: Setup Bluetooth PAN (Personal Area Network)
echo "Setting up Bluetooth PAN..."
if [ -f /opt/vernis/scripts/setup-bluetooth-pan.sh ]; then
    bash /opt/vernis/scripts/setup-bluetooth-pan.sh
else
    echo "setup-bluetooth-pan.sh not found. Copy scripts first, then run:"
    echo "  bash /opt/vernis/scripts/setup-bluetooth-pan.sh"
fi

# Step 11: Setup automatic security updates
echo "[11/17] Setting up automatic security updates..."
if [ -f /opt/vernis/scripts/setup-auto-updates.sh ]; then
    sudo bash /opt/vernis/scripts/setup-auto-updates.sh enable
else
    echo "setup-auto-updates.sh not found. Copy scripts first, then run:"
    echo "  sudo bash /opt/vernis/scripts/setup-auto-updates.sh enable"
fi

# Step 12: Run Waveshare display setup if script exists
echo "[12/17] Checking for display setup script..."
if [ -f /opt/vernis/scripts/setup-waveshare-4dpi.sh ]; then
    echo "Running Waveshare 4inch DPI LCD setup..."
    sudo bash /opt/vernis/scripts/setup-waveshare-4dpi.sh
else
    echo "Display setup script not found. Copy files first, then run:"
    echo "  sudo bash /opt/vernis/scripts/setup-waveshare-4dpi.sh"
fi

# Disable dpi-backlight service if present (it corrupts DPI display by hijacking GPIO18)
# See DPI-DISPLAY-TROUBLESHOOTING.md Issue 1 for details
sudo systemctl disable --now dpi-backlight 2>/dev/null || true

# Remove gpio-fan on DPI-unsafe pins (GPIOs 0-25 are used by DPI display)
# GPIO 14 in particular is DPI_D10 — fan driver hijacks the pin, corrupting colors
CONFIG_FILE_FAN=""
if [ -f /boot/firmware/config.txt ]; then
    CONFIG_FILE_FAN="/boot/firmware/config.txt"
elif [ -f /boot/config.txt ]; then
    CONFIG_FILE_FAN="/boot/config.txt"
fi
if [ -n "$CONFIG_FILE_FAN" ]; then
    if grep -qP '^dtoverlay=gpio-fan,gpiopin=1[0-9]\b|^dtoverlay=gpio-fan,gpiopin=[0-9]\b|^dtoverlay=gpio-fan,gpiopin=2[0-5]\b' "$CONFIG_FILE_FAN" 2>/dev/null; then
        sudo sed -i 's/^dtoverlay=gpio-fan,gpiopin=\(1[0-9]\|[0-9]\|2[0-5]\)/#DISABLED — DPI pin conflict: dtoverlay=gpio-fan,gpiopin=\1/' "$CONFIG_FILE_FAN"
        echo "WARNING: Disabled gpio-fan on DPI-unsafe pin (use GPIO 26 or 27 instead)"
    fi
fi

# Ensure user can read touchscreen input for touch-to-wake
sudo usermod -aG input $USER_NAME 2>/dev/null || true

# Ensure over_voltage=4 for DPI displays (lower values cause scan lines / signal artifacts)
CONFIG_FILE=""
if [ -f /boot/firmware/config.txt ]; then
    CONFIG_FILE="/boot/firmware/config.txt"
elif [ -f /boot/config.txt ]; then
    CONFIG_FILE="/boot/config.txt"
fi
if [ -n "$CONFIG_FILE" ]; then
    CURRENT_OV=$(grep -oP '^over_voltage=\K-?\d+' "$CONFIG_FILE" 2>/dev/null || echo "")
    if [ -n "$CURRENT_OV" ] && [ "$CURRENT_OV" -lt 4 ] 2>/dev/null; then
        sudo sed -i 's/^over_voltage=.*/over_voltage=4/' "$CONFIG_FILE"
        echo "Fixed over_voltage from $CURRENT_OV to 4 (minimum for stable DPI display)"
    elif [ -z "$CURRENT_OV" ]; then
        echo "over_voltage=4" | sudo tee -a "$CONFIG_FILE" > /dev/null
        echo "Set over_voltage=4 (minimum for stable DPI display)"
    fi
    # Remove arm_boost from default section — it must only appear in [all] (via CPU profile)
    # Having arm_boost before [cm4] breaks Pi 5 firmware overlay parsing
    if grep -q '^arm_boost=' "$CONFIG_FILE" 2>/dev/null; then
        sudo sed -i '/^arm_boost=/d' "$CONFIG_FILE"
        echo "Removed arm_boost from default section (set via CPU profile in [all])"
    fi
fi

# Fix Waveshare 4" DPI LCD touch overlay — add missing 'interrupts' property
# Without this, the Goodix GT911 driver polls at 60fps via workqueue (~30% CPU).
# The fix adds 'interrupts = <27 2>' so the i2c core populates client->irq and
# the driver uses GPIO 27 edge interrupt instead of polling.
# Also removes the rpi_backlight fragment that claims GPIO 18 (a DPI data pin).
TOUCH_OVERLAY=""
if [ -f /boot/firmware/overlays/waveshare-touch-4dpi.dtbo ]; then
    TOUCH_OVERLAY="/boot/firmware/overlays/waveshare-touch-4dpi.dtbo"
elif [ -f /boot/overlays/waveshare-touch-4dpi.dtbo ]; then
    TOUCH_OVERLAY="/boot/overlays/waveshare-touch-4dpi.dtbo"
fi
if [ -n "$TOUCH_OVERLAY" ] && [ -f /opt/vernis/scripts/waveshare-touch-4dpi-fixed.dts ]; then
    # Check if overlay already has the interrupts fix (skip if already patched)
    if ! dtc -I dtb -O dts "$TOUCH_OVERLAY" 2>/dev/null | grep -q 'interrupts'; then
        echo "Patching waveshare-touch-4dpi overlay (adding touch IRQ support)..."
        sudo cp "$TOUCH_OVERLAY" "${TOUCH_OVERLAY}.bak"
        dtc -I dts -O dtb -o /tmp/waveshare-touch-4dpi-fixed.dtbo /opt/vernis/scripts/waveshare-touch-4dpi-fixed.dts 2>/dev/null
        if [ -f /tmp/waveshare-touch-4dpi-fixed.dtbo ]; then
            sudo cp /tmp/waveshare-touch-4dpi-fixed.dtbo "$TOUCH_OVERLAY"
            rm -f /tmp/waveshare-touch-4dpi-fixed.dtbo
            echo "Touch overlay patched (IRQ mode enabled, ~30% CPU savings)"
        else
            echo "WARNING: Failed to compile touch overlay fix. Touch will use polling mode."
        fi
    else
        echo "Touch overlay already has IRQ support, skipping patch"
    fi
fi

# Step 12.5: Setup Vernis boot splash (Plymouth theme)
echo "Setting up Vernis boot splash..."
if [ -f /var/www/vernis/assets/vernis-nft.svg ]; then
    # Convert SVG to 720x720 PNG
    rsvg-convert -w 720 -h 720 /var/www/vernis/assets/vernis-nft.svg -o /tmp/vernis-splash-raw.png
    # Rotate 270° CW (90° CCW) to compensate for DPI panel physical orientation
    convert /tmp/vernis-splash-raw.png -rotate 270 /tmp/vernis-splash.png
    # Create Plymouth theme
    sudo mkdir -p /usr/share/plymouth/themes/vernis
    sudo cp /tmp/vernis-splash.png /usr/share/plymouth/themes/vernis/splash.png
    sudo cp /tmp/vernis-splash-raw.png /usr/share/plymouth/themes/vernis/splash-upright.png
    sudo tee /usr/share/plymouth/themes/vernis/vernis.script > /dev/null << 'PLYSCRIPT'
Window.SetBackgroundTopColor(0.06, 0.05, 0.05);
Window.SetBackgroundBottomColor(0.06, 0.05, 0.05);
logo.image = Image("splash.png");
logo.sprite = Sprite(logo.image);
logo.sprite.SetX(Window.GetX() + Window.GetWidth() / 2 - logo.image.GetWidth() / 2);
logo.sprite.SetY(Window.GetY() + Window.GetHeight() / 2 - logo.image.GetHeight() / 2);
logo.sprite.SetZ(1000);
logo.sprite.SetOpacity(1);
PLYSCRIPT
    sudo tee /usr/share/plymouth/themes/vernis/vernis.plymouth > /dev/null << 'PLYCFG'
[Plymouth Theme]
Name=Vernis
Description=Vernis boot splash - gold luxury theme
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/vernis
ScriptFile=/usr/share/plymouth/themes/vernis/vernis.script
PLYCFG
    sudo plymouth-set-default-theme vernis
    sudo update-initramfs -u
    rm -f /tmp/vernis-splash-raw.png /tmp/vernis-splash.png
    echo "Vernis boot splash installed"
else
    echo "vernis-nft.svg not found. Copy web assets first, then run:"
    echo "  rsvg-convert -w 720 -h 720 /var/www/vernis/assets/vernis-nft.svg -o /tmp/splash.png"
    echo "  Then re-run install script or manually set up Plymouth theme"
fi

# Suppress boot text and cursor between splash and kiosk
echo "Hiding boot text and cursor..."
CMDLINE_FILE=""
if [ -f /boot/firmware/cmdline.txt ]; then
    CMDLINE_FILE="/boot/firmware/cmdline.txt"
elif [ -f /boot/cmdline.txt ]; then
    CMDLINE_FILE="/boot/cmdline.txt"
fi
if [ -n "$CMDLINE_FILE" ]; then
    # Remove console=tty1 (shows boot text on screen)
    sudo sed -i 's/ console=tty1//g' "$CMDLINE_FILE"
    # Add quiet boot flags if not already present
    for flag in "loglevel=0" "logo.nologo" "vt.global_cursor_default=0" "consoleblank=0"; do
        if ! grep -q "$flag" "$CMDLINE_FILE"; then
            sudo sed -i "s/$/ $flag/" "$CMDLINE_FILE"
        fi
    done
    echo "cmdline.txt updated (boot text hidden)"
fi
CONFIG_FILE=""
if [ -f /boot/firmware/config.txt ]; then
    CONFIG_FILE="/boot/firmware/config.txt"
elif [ -f /boot/config.txt ]; then
    CONFIG_FILE="/boot/config.txt"
fi
if [ -n "$CONFIG_FILE" ]; then
    if ! grep -q "disable_splash=1" "$CONFIG_FILE"; then
        echo "disable_splash=1" | sudo tee -a "$CONFIG_FILE" > /dev/null
    fi
    echo "config.txt updated (rainbow splash disabled)"
fi
# Mask getty on tty1 (prevents login prompt text on screen)
sudo systemctl mask getty@tty1 2>/dev/null || true
echo "getty@tty1 masked (no login prompt on screen)"

# Step 13: Configure firewall
echo "[13/17] Configuring firewall..."
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp comment "SSH"
sudo ufw allow 80/tcp comment "HTTP"
sudo ufw allow 4001/tcp comment "IPFS Swarm TCP"
sudo ufw allow 4001/udp comment "IPFS Swarm UDP"
echo "y" | sudo ufw enable
echo "Firewall enabled (SSH, HTTP, IPFS Swarm allowed)"

# Ensure dnsmasq is enabled (needed for BT PAN DHCP)
sudo systemctl enable dnsmasq 2>/dev/null || true

# Step 13.5: Setup tmpfs RAM disk for temp work (reduces SD card writes)
echo "Setting up tmpfs RAM disk..."
if [ -f /opt/vernis/scripts/setup-tmpfs.sh ]; then
    sudo bash /opt/vernis/scripts/setup-tmpfs.sh auto
else
    echo "setup-tmpfs.sh not found. Copy scripts first, then run:"
    echo "  sudo bash /opt/vernis/scripts/setup-tmpfs.sh auto"
fi

# Step 14: Start services
echo "[14/17] Starting services..."
if [ -f /opt/vernis/app.py ]; then
    sudo systemctl start vernis-api
    echo "Flask API started"
else
    echo "app.py not found - copy files first, then run: sudo systemctl start vernis-api"
fi
sudo systemctl start ipfs
echo "IPFS daemon started"

# Step 15: Fix mislabeled AVIF files (saved as .mp4 by old downloader)
echo "[15/17] Fixing mislabeled AVIF files..."
nft_dir="/opt/vernis/nfts"
if [ -d "$nft_dir" ]; then
    fix_count=0
    for f in "$nft_dir"/*.mp4; do
        [ -f "$f" ] || continue
        brand=$(dd if="$f" bs=1 skip=8 count=4 2>/dev/null)
        if [ "$brand" = "avif" ] || [ "$brand" = "avis" ] || [ "$brand" = "mif1" ]; then
            mv "$f" "${f%.mp4}.avif"
            fix_count=$((fix_count + 1))
        fi
    done
    if [ "$fix_count" -gt 0 ]; then
        echo "Renamed $fix_count AVIF files from .mp4 to .avif"
    else
        echo "No mislabeled files found"
    fi
else
    echo "NFT directory not found yet, skipping"
fi

# Step 16: Enable fail2ban
echo "[16/17] Enabling fail2ban..."
sudo systemctl enable --now fail2ban
echo "fail2ban enabled (SSH brute-force protection)"

# Step 17: Configure log2ram (reduce SD card writes)
echo "[17/17] Configuring log2ram..."
if [ -f /etc/log2ram.conf ]; then
    # Enable zram compression for logs
    sudo sed -i 's/^ZL2R=false/ZL2R=true/' /etc/log2ram.conf
    # Limit journald size to fit within log2ram
    sudo mkdir -p /etc/systemd/journald.conf.d
    sudo tee /etc/systemd/journald.conf.d/size-limit.conf > /dev/null << EOF
[Journal]
SystemMaxUse=64M
RuntimeMaxUse=32M
EOF
    echo "log2ram configured (logs stored in compressed RAM, synced to SD daily)"
    echo "  → Reduces SD card write wear significantly"
else
    echo "log2ram not found, skipping"
fi

# Create default config files for customer devices
echo "Creating default configuration..."

# Display config: frosted blur 12px, 15s image duration, shuffle on
cat > /tmp/display-config.json << 'DCFG'
{
  "image_duration": 15,
  "video_duration": 30,
  "crossfade_duration": 0.8,
  "frosted_background": false,
  "frosted_blur": 12,
  "frosted_opacity": 0.55,
  "force_horizontal": false,
  "shuffle": true,
  "background_color": "#000000",
  "pixel_shift": true
}
DCFG
sudo mv /tmp/display-config.json /opt/vernis/display-config.json

# Fan config: silent mode (whisper-quiet for home use)
cat > /tmp/fan-config.json << 'FCFG'
{"mode": "silent"}
FCFG
sudo mv /tmp/fan-config.json /opt/vernis/fan-config.json

# CPU profile: eco (cool and quiet, sufficient for gallery)
cat > /tmp/cpu-profile.json << 'CCFG'
{"profile": "eco"}
CCFG
sudo mv /tmp/cpu-profile.json /opt/vernis/cpu-profile.json

# Rotation config: 90° for DPI, 0° for external
cat > /tmp/rotation-config.json << 'RCFG'
{"rotation": 90, "rotation_external": 0}
RCFG
sudo mv /tmp/rotation-config.json /opt/vernis/rotation-config.json

# Display output: auto mode, 1080p on HDMI
cat > /tmp/display-output-config.json << 'DOCFG'
{"mode": "auto", "resolution": "1080p"}
DOCFG
sudo mv /tmp/display-output-config.json /opt/vernis/display-output-config.json

## Mark setup wizard as complete (skip welcome screen on gallery)
cat > /tmp/setup-complete.json << 'SCFG'
{"completed_at": "pre-configured", "password_changed": true, "pre_configured": true}
SCFG
sudo mv /tmp/setup-complete.json /opt/vernis/setup-complete.json

echo "Default configs created (blur=12px, fan=silent, cpu=eco, setup=complete)"

echo ""
echo "==========================================="
echo "Installation Complete!"
echo "==========================================="
echo ""
if [ -n "$DEPLOY_DIR" ]; then
    echo "All files deployed. Next steps:"
    echo "  1. Reboot: sudo reboot"
else
    echo "Next steps:"
    echo "  1. Copy web files to /var/www/vernis/"
    echo "  2. Copy backend files to /opt/vernis/"
    echo "  3. Copy scripts to /opt/vernis/scripts/"
    echo "  4. Reboot: sudo reboot"
fi
echo ""
echo "Test URLs after reboot:"
echo "  Web UI: http://$(hostname -I | awk '{print $1}')"
echo "  API:    http://$(hostname -I | awk '{print $1}')/api/health"
echo ""
