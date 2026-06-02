# Vernis v3 – Full Premium System

**One Codebase, Two Models: Phone UI + Kiosk Display**

A self-hosted, offline-first NFT gallery system for Raspberry Pi with luxury web UI, automatic Wi-Fi fallback, and OTA updates.

---

## Features

✨ **Beautiful Web UI** – Cinematic dark theme with glassmorphism, gradient text, Cinzel + Inter fonts
📱 **Phone + Screen** – Same codebase serves http://vernis.local on phone AND built-in screen (kiosk mode)
🔌 **Always Accessible** – Bulletproof Wi-Fi fallback creates recovery AP when internet is down
🎨 **NFT Gallery** – Upload CSV or single NFTs, automatic download & IPFS pinning
📚 **CSV Library** – Browse curated collections, download CSV lists, or install & pin directly
📦 **Device Preload** – Ship devices with CSV collections or full NFT galleries pre-installed
🖼️ **Fullscreen Gallery** – Rotating gallery with touch controls and adjustable intervals
🔄 **OTA Updates** – One-click remote updates without SSH
⚡ **Self-Hosted** – No cloud, no subscriptions, fully offline-capable

---

## Quick Start

### 1. Flash Raspberry Pi OS Lite (64-bit)

Use Raspberry Pi Imager:
- **OS**: Raspberry Pi OS Lite (64-bit)
- **Storage**: USB SSD recommended (faster + more space)
- **Settings**: Enable SSH, set hostname to `vernis`

### 2. Boot and Connect

```bash
ssh pi@vernis.local
```

### 3. Install Vernis

```bash
# Upload the entire vernis v3 folder to /home/pi/vernis
cd /home/pi/vernis
sudo bash install.sh
```

The installer will ask:
> **Is this Vernis v2 with a built-in screen? (y/n)**

- **y** = Kiosk mode (boots to fullscreen gallery)
- **n** = Headless (phone access only)

After 5-10 minutes, the Pi will reboot automatically.

### 4. Access Vernis

**Normal Mode:**
Open http://vernis.local on your phone or laptop

**Fallback Mode (no internet):**
Connect to Wi-Fi AP:
- SSID: `Vernis-XXXXXXXX` (XXXXXXXX = CPU serial)
- Password: `<ap-password>`
- Visit: http://vernis.local or http://192.168.50.1

---

## Architecture

```
Raspberry Pi OS Lite (64-bit) + SSD
├── Caddy → http://vernis.local (auto mDNS)
├── Flask API (/api/*)
├── Static web UI in /var/www/vernis/
├── Systemd services:
│   ├─ vernis-api.service (Flask backend)
│   ├─ vernis-ap-check.timer (Wi-Fi fallback monitor)
│   ├─ vernis-watchdog.service (screen watchdog, kiosk only)
│   └─ caddy.service (web server)
└── IPFS + NFT downloader scripts
```

---

## File Structure

```
/var/www/vernis/           → Web UI (index.html, add.html, gallery.html, settings.html)
/opt/vernis/               → Backend & scripts
    ├── app.py             → Flask API
    ├── nfts/              → Downloaded NFT media
    ├── uploads/           → CSV uploads
    ├── scripts/
    │   ├── nft_downloader.py         → NFT download script
    │   ├── enable-setup-ap.sh        → Wi-Fi fallback AP
    │   ├── disable-setup-ap.sh       → Disable fallback AP
    │   ├── updater.sh                → OTA update handler
    │   ├── watchdog.sh               → Screen monitor (kiosk)
    │   └── create-update-package.sh  → Build update bundle
    └── backup/            → Update backups

/etc/systemd/system/       → Service files
/etc/caddy/Caddyfile       → Web server config
/etc/avahi/services/       → mDNS advertisement
/home/pi/.config/lxsession/LXDE-pi/autostart  → Kiosk autostart (v2 only)
```

---

## Web UI Pages

| Page | URL | Purpose |
|------|-----|---------|
| **Home** | `/` | Welcome screen with 4 action cards |
| **Add Art** | `/add.html` | Upload CSV or add single NFT |
| **CSV Library** | `/library.html` | Browse & install curated collections |
| **Gallery** | `/gallery.html` | Fullscreen rotating gallery with touch controls |
| **Settings** | `/settings.html` | Wi-Fi, storage, updates, reboot |

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/pinned-art` | GET | List all NFT files |
| `/api/upload-csv` | POST | Upload CSV for batch download |
| `/api/add-single` | POST | Add single NFT (contract + token_id) |
| `/api/csv-library` | GET | List CSV collections in library |
| `/api/csv-library/download/<filename>` | GET | Download CSV file from library |
| `/api/csv-library/install` | POST | Install & pin collection from library |
| `/api/device-config` | GET | Get device configuration |
| `/api/status` | GET | System status (Wi-Fi, storage, count) |
| `/api/wifi` | POST | Change Wi-Fi network |
| `/api/update` | GET | Trigger OTA update |
| `/api/reboot` | GET | Reboot system |
| `/nfts/<file>` | GET | Serve NFT media files |

---

## Kiosk Mode (Vernis v2 with Screen)

When installed with kiosk mode:

1. **Auto-boots to fullscreen gallery** at startup
2. **Chromium kiosk mode** loads http://vernis.local/gallery.html
3. **Screen watchdog** restarts if frozen (every 5 min check)
4. **No screensaver** or power management

Configured via:
- `/home/pi/.config/lxsession/LXDE-pi/autostart`
- `vernis-watchdog.service`

---

## Wi-Fi Fallback System

The `vernis-ap-check.timer` runs every 5 minutes and:

1. Checks internet connectivity (ping 8.8.8.8)
2. If offline for 90s+ → starts fallback AP
3. Creates `Vernis-XXXXXXXX` Wi-Fi network
4. Serves Vernis at http://vernis.local or http://192.168.50.1

**To disable fallback AP manually:**
```bash
sudo /opt/vernis/scripts/disable-setup-ap.sh
```

**Fallback AP credentials:**
- SSID: `Vernis-` + last 8 digits of CPU serial
- Password: `<ap-password>`

---

## OTA Updates

### Create Update Package

On your dev machine:

```bash
cd "vernis v3"
bash scripts/create-update-package.sh
```

This creates: `vernis-update-YYYYMMDD-HHMMSS.tar.gz`

### Deploy Update

1. Upload to your web server at `https://yourdomain.com/vernis/latest.tar.gz`
2. Update `UPDATE_URL` in `scripts/updater.sh` to match your domain
3. On Vernis: Click "Check for Updates" in Settings page
4. System downloads, applies update, and reboots

**Backup:** Each update creates backup at `/opt/vernis/backup-YYYYMMDD-HHMMSS/`

---

## Customization

### Change Gallery Timing
The Gallery now features on-screen touch controls to adjust the interval (5s to 60s) dynamically.

### Change Theme Colors

Edit `vernis-themes.css`:
```css
:root {
  --bg-primary: #0a0a0a;        /* Background */
  --text-primary: #f0f0f0;      /* Text */
  --accent-primary: #d4af37;    /* Primary accent */
  --card-bg: rgba(30,30,40,0.85);
}
```

### Custom NFT Downloader

Replace [scripts/nft_downloader.py](scripts/nft_downloader.py) with your own implementation.

Current script uses OpenSea API as example. Adapt for:
- Alchemy NFT API
- Moralis
- Direct IPFS gateway
- Your custom metadata format

---

## Troubleshooting

### Can't access http://vernis.local

**Check mDNS:**
```bash
sudo systemctl status avahi-daemon
```

**Try IP address:**
```bash
ip addr show | grep "inet "
# Access via http://192.168.x.x
```

### Flask API not running

```bash
sudo systemctl status vernis-api
sudo journalctl -u vernis-api -f
```

### Kiosk mode not starting

```bash
# Check autostart file
cat /home/pi/.config/lxsession/LXDE-pi/autostart

# Check display manager
sudo systemctl status lightdm

# Restart X session
sudo systemctl restart lightdm
```

### Fallback AP not working

```bash
sudo systemctl status hostapd
sudo systemctl status dnsmasq
sudo journalctl -u vernis-ap-check -f
```

### No NFTs downloading

```bash
# Test downloader manually
cd /opt/vernis
python3 scripts/nft_downloader.py --contract 0xYOURCONTRACT --token 1 --output ./nfts

# Check logs
ls -lh /opt/vernis/nfts
```

---

## Security Notes

⚠️ **This is designed for local/private networks**

- No HTTPS by default (add with Caddy if exposing publicly)
- No authentication (add if needed)
- Runs Flask in production without WSGI (fine for local use, use Gunicorn if public)
- `sudo` commands in API require passwordless sudo for `pi` user

**For public deployment:**
1. Enable Caddy automatic HTTPS
2. Add authentication to Flask endpoints
3. Run Flask via Gunicorn/uWSGI
4. Firewall non-essential ports
5. Change default passwords

---

## Hardware Recommendations

### Vernis v1 (Headless)
- Raspberry Pi 4B (4GB+)
- 128GB+ USB SSD
- Official power supply
- No screen needed

### Vernis v2 (Kiosk with Screen)
- Raspberry Pi 4B (4GB+)
- 128GB+ USB SSD
- Official 7" touchscreen or HDMI monitor
- Official power supply
- Case with screen mount

---

## License

MIT License – Use freely for personal or commercial projects

---

## Credits

Built with:
- [Flask](https://flask.palletsprojects.com/) – Python web framework
- [Caddy](https://caddyserver.com/) – Modern web server
- [Chromium](https://www.chromium.org/) – Kiosk browser
- [Cinzel](https://fonts.google.com/specimen/Cinzel) & [Inter](https://fonts.google.com/specimen/Inter) fonts

---

## Device Preloading

Vernis v3 supports preloading devices with curated collections:

- **Lite Mode** - Preload CSV lists only (users download NFTs on demand)
- **Full Mode** - Preload CSV lists + all NFT files (instant gallery display)

See the `scripts/` directory for preloading tools.

---

## Support

For issues, questions, or contributions, open an issue or PR.

**Enjoy your forever gallery! 🎨**

## Security

Vernis has three access-control modes selectable from Settings → Security:

- **Open** — default. Anyone with the link can use the device fully.
- **Protected** — anyone can browse and control; **deleting** files/libraries/carousels requires a PIN.
- **Locked** — PIN required to open Settings/Library/Manage/Lab/Add. The home page (gallery + connect QR) stays viewable.

The PIN is 6 digits, bcrypt-hashed server-side. Your browser remembers a session for 30 days so you don't re-enter the PIN constantly.

### Setting up a PIN

1. Open Settings → Security
2. Click **Set PIN**
3. Enter your device password and choose a 6-digit PIN
4. Pick a mode (Protected or Locked) when you're ready

### Forgot your PIN?

Two recovery paths:

1. **Hold the VERNIS logo for 5 seconds** on the home page or PIN entry screen. A modal asks for your device password. Enter it, optionally set a new PIN, and you're back in.
2. **SSH into the Pi** and run `sudo /opt/vernis/scripts/reset-pin.sh` to wipe the PIN and drop back to Open mode.

### Changed your device password via `passwd`?

If you change your Linux password via `passwd` over SSH (instead of through Settings), the recovery hash goes stale. Re-sync it:

```bash
sudo /opt/vernis/scripts/update-owner-password.sh
```

Settings → Security → Change Password keeps everything in sync automatically.
