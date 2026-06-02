# Vernis Installation Guide

Complete setup instructions for new Raspberry Pi devices.

## Prerequisites

- Raspberry Pi 4 or 5
- Waveshare 4inch DPI LCD (C) display
- MicroSD card (32GB+ recommended)
- Raspberry Pi Imager installed on your computer

## Step 1: Prepare SD Card

1. Open **Raspberry Pi Imager**
2. Choose OS: **Raspberry Pi OS (64-bit)** - Desktop version
3. Choose Storage: Select your SD card
4. Click the **gear icon** (settings) and configure:
   - Set hostname (e.g., `afroX`)
   - Enable SSH (password authentication)
   - Set username and password (e.g., `<username>` / `<password>`)
   - Configure WiFi (SSID and password)
   - Set locale/timezone
5. Write the image to SD card

## Step 2: First Boot

1. Insert SD card into Pi
2. Connect to power (HDMI monitor optional for debugging)
3. Wait 2-3 minutes for first boot
4. Find Pi's IP address:
   - Check your router's DHCP list
   - Or use: `ping vernis.local`
   - Or scan your LAN (e.g. `nmap -sn 192.168.1.0/24`)

## Step 3: Install Vernis

SSH into the Pi and run these commands:

```bash
# Connect to Pi
ssh username@IP_ADDRESS

# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y caddy python3-pip python3-flask xinput xdotool unclutter chromium-browser
sudo pip3 install qrcode pillow --break-system-packages

# Create directories
sudo mkdir -p /var/www/vernis /opt/vernis/scripts /opt/vernis/csv-library /opt/vernis/nfts
sudo chown -R $USER:$USER /var/www/vernis /opt/vernis
```

## Step 4: Copy Vernis Files

From your Mac (replace `USERNAME` and `IP_ADDRESS`):

```bash
cd "/path/to/artboxv3"

# Copy web files
for f in *.html *.css *.js *.svg; do
  [ -f "$f" ] && scp "$f" USERNAME@IP_ADDRESS:/var/www/vernis/
done

# Copy backend
scp backend/app.py USERNAME@IP_ADDRESS:/opt/vernis/

# Copy scripts
scp scripts/*.sh scripts/*.py USERNAME@IP_ADDRESS:/opt/vernis/scripts/
ssh USERNAME@IP_ADDRESS "chmod +x /opt/vernis/scripts/*.sh /opt/vernis/scripts/*.py"

# Copy CSV library (optional - from existing Pi)
scp -r USERNAME@EXISTING_PI:/opt/vernis/csv-library/* USERNAME@IP_ADDRESS:/opt/vernis/csv-library/
```

## Step 5: Configure Caddy Web Server

SSH into Pi and run:

```bash
sudo tee /etc/caddy/Caddyfile > /dev/null << 'EOF'
:80 {
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
```

## Step 6: Configure Flask API Service

```bash
sudo tee /etc/systemd/system/vernis-api.service > /dev/null << 'EOF'
[Unit]
Description=Vernis Flask API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vernis
ExecStart=/usr/bin/python3 /opt/vernis/app.py
Restart=always
RestartSec=5
Environment=FLASK_ENV=production

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable vernis-api
sudo systemctl start vernis-api
```

## Step 7: Setup Waveshare 4inch DPI LCD

```bash
sudo bash /opt/vernis/scripts/setup-waveshare-4dpi.sh
```

This script:
- Downloads and installs Waveshare overlay files
- Configures `/boot/firmware/config.txt`
- Sets up backlight control
- Configures touch input

## Step 8: Setup Kiosk Mode

Newer Raspberry Pi OS uses labwc (Wayland compositor). For proper kiosk mode:

```bash
# Create labwc autostart (for Wayland - newer Pi OS)
mkdir -p ~/.config/labwc
cat > ~/.config/labwc/autostart << 'EOF'
# Vernis Kiosk Mode - Clean desktop for kiosk
# Kill any desktop components that might have started
pkill -f lwrespawn 2>/dev/null
pkill -f wf-panel-pi 2>/dev/null
pkill -f pcmanfm 2>/dev/null

# Run kiosk launcher
/opt/vernis/scripts/kiosk-launcher.sh &
EOF
chmod +x ~/.config/labwc/autostart

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
```

The labwc autostart:
- Kills the desktop panel (wf-panel-pi) and file manager (pcmanfm)
- Runs Chromium in fullscreen kiosk mode
- Works with Wayland (newer Raspberry Pi OS)

## Step 9: Setup Touch Rotation Service

```bash
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
```

## Step 10: Final Reboot

```bash
sudo reboot
```

After reboot (~30 seconds), the Pi should:
- Display the Vernis gallery on the 4" screen
- Run in kiosk mode (fullscreen Chromium)
- Have touch input working

## Verification Checklist

- [ ] Web UI accessible at `http://IP_ADDRESS`
- [ ] API working at `http://IP_ADDRESS/api/health`
- [ ] 4" display showing gallery
- [ ] Touch input responding
- [ ] Kiosk mode active (fullscreen, no browser UI)
- [ ] CSV Library showing collections

## Troubleshooting

### Display not working
- Check ribbon cable connection
- Backlight on but no image = config issue, check `/boot/firmware/config.txt`
- No backlight = power/connection issue

### Touch not aligned with display
```bash
sudo bash /opt/vernis/scripts/touch-rotate.sh
```

### API not responding
```bash
sudo systemctl status vernis-api
sudo journalctl -u vernis-api -f
```

### Web server not responding
```bash
sudo systemctl status caddy
sudo journalctl -u caddy -f
```

### Low memory warning (Pi with <1GB RAM)
The kiosk launcher includes `--disable-features=InsufficientResourcesWarning` flag.

### Screen flickering
Check `/boot/firmware/config.txt` for conflicting overlays. Only use:
```
dtoverlay=waveshare-4dpic-4b
dtoverlay=waveshare-4dpi
dtoverlay=waveshare-touch-4dpi
```

### Desktop showing instead of kiosk
If the regular desktop (panel/taskbar) appears instead of kiosk mode:
```bash
# Check if labwc autostart exists
cat ~/.config/labwc/autostart

# If missing or incorrect, recreate it:
mkdir -p ~/.config/labwc
cat > ~/.config/labwc/autostart << 'EOF'
pkill -f lwrespawn 2>/dev/null
pkill -f wf-panel-pi 2>/dev/null
pkill -f pcmanfm 2>/dev/null
/opt/vernis/scripts/kiosk-launcher.sh &
EOF
chmod +x ~/.config/labwc/autostart
sudo reboot
```

## Quick Deploy Script

For faster deployment, use this one-liner from your Mac:

```bash
# Set variables
PI_USER="afroX"
PI_IP="10.0.0.XX"
PI_PASS="<your-password>"

# Run full install
sshpass -p "$PI_PASS" ssh -o StrictHostKeyChecking=no $PI_USER@$PI_IP "sudo apt update && sudo apt install -y caddy python3-pip python3-flask xinput xdotool unclutter && sudo mkdir -p /var/www/vernis /opt/vernis/scripts /opt/vernis/csv-library /opt/vernis/nfts && sudo chown -R $PI_USER:$PI_USER /var/www/vernis /opt/vernis"
```

Then copy files and run setup scripts as described above.

## File Structure

```
/var/www/vernis/          # Web UI files (HTML, CSS, JS)
├── index.html
├── gallery.html
├── library.html
├── manage.html
├── settings.html
├── setup.html
├── add.html
├── vernis-themes.css
├── vernis-notifications.js
├── vernis-keyboard.js
└── favicon.svg

/opt/vernis/              # Backend files
├── app.py                # Flask API
├── nfts/                 # Downloaded NFT images
├── csv-library/          # CSV collection files
└── scripts/
    ├── kiosk-launcher.sh
    ├── setup-waveshare-4dpi.sh
    ├── touch-rotate.sh
    ├── enable-kiosk.sh
    └── nft_downloader_advanced.py
```

## Adding to CLAUDE.md

After setup, add the new Pi to `/artboxv3/CLAUDE.md`:

```markdown
| name | IP | username | password | Auth Method |
|------|-----|----------|----------|-------------|
| <hostname> | <ip> | <user> | <password> | Password |
```
