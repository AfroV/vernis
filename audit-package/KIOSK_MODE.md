# Kiosk Mode - Quick Reference

## Overview

Kiosk mode makes your Raspberry Pi boot directly into a fullscreen web browser displaying your Vernis gallery. Perfect for devices with attached screens/displays.

## How It Works

1. **Console Auto-Login** - Pi automatically logs in to the console
2. **Auto-Start X** - X server starts automatically on login
3. **Launch Browser** - Chromium opens in fullscreen kiosk mode
4. **Display Gallery** - Shows `http://localhost/gallery.html`

## Enabling Kiosk Mode

### Via Deployment Script (Recommended)

In `pi-devices.json`, set `"kiosk_mode": true`:

```json
{
  "name": "Pi-Gallery",
  "host": "<device-ip>",
  "username": "<username>",
  "password": "<password>",
  "kiosk_mode": true,
  "enabled": true
}
```

Then run:
```bash
python3 deploy-to-pi.py
```

### Manually

SSH into your Pi and run:
```bash
cd ~/vernisv3
sudo bash enable-kiosk-simple.sh
sudo reboot
```

## Disabling Kiosk Mode

### Quick Disable (keeps packages installed)

SSH into the Pi:
```bash
nano ~/.bash_profile
```

Remove or comment out the X auto-start section:
```bash
# Auto-start X session on tty1
#if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
#    exec startx
#fi
```

Reboot:
```bash
sudo reboot
```

### Complete Removal

```bash
cd ~/vernisv3
sudo bash disable-kiosk.sh
sudo reboot
```

## Changing the Displayed Page

Edit `~/.xinitrc` and change the URL at the end:

```bash
nano ~/.xinitrc
```

Change `http://localhost/gallery.html` to:
- `http://localhost/` - Home page
- `http://localhost/splash.html` - Splash screen
- `http://localhost/manage.html` - Management page
- Or any other page

Then restart X:
```bash
sudo systemctl restart getty@tty1
```

## Troubleshooting

### Screen Goes Blank
The kiosk disables screen blanking, but if it still happens:
```bash
# Add to ~/.xinitrc before chromium line:
xset s off
xset -dpms
xset s noblank
```

### Chromium Not Starting
Check if X is running:
```bash
ps aux | grep Xorg
```

Check for errors:
```bash
cat ~/.xsession-errors
```

### Wrong Display Resolution
Add to `~/.xinitrc` before chromium:
```bash
xrandr --output HDMI-1 --mode 1920x1080
```

### Mouse Cursor Visible
Install unclutter (should be automatic):
```bash
sudo apt-get install unclutter
```

## Technical Details

### What Gets Installed
- `xserver-xorg` - X Window System
- `xinit` - X initialization
- `chromium` - Web browser
- `unclutter` - Hide mouse cursor

### Files Modified
- `/etc/systemd/system/getty@tty1.service.d/autologin.conf` - Console auto-login
- `~/.xinitrc` - X session startup
- `~/.bash_profile` - Auto-start X on login

### Resource Usage
- **RAM**: ~250MB (X + Chromium)
- **Boot Time**: +30-60 seconds
- **CPU**: Minimal when idle

## Benefits vs LightDM Approach

✅ **Simpler** - No display manager needed
✅ **More Reliable** - Fewer moving parts
✅ **Lighter** - Uses less RAM
✅ **Faster Boot** - Skips desktop environment
✅ **No Password Issues** - Console auto-login is straightforward
✅ **Easier to Debug** - Simple bash scripts

## Use Cases

- **Gallery Display** - Digital art frame
- **Information Display** - Dashboard or status board
- **Kiosk Terminal** - Public information terminal
- **Digital Signage** - Advertising or wayfinding
