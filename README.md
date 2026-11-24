# Vernis v3 – Full Premium System

**One Codebase, Two Models: Phone UI + Kiosk Display**

A self-hosted, offline-first NFT gallery system for Raspberry Pi with luxury web UI, a local IPFS node, and one-click updates.

---

## Features

✨ **Beautiful Web UI** – Cinematic dark theme with glassmorphism, gradient text, Cinzel + Inter fonts
📱 **Phone + Screen** – Same codebase serves http://vernis.local on phone AND built-in screen (kiosk mode)
🔌 **Always Accessible** – Bluetooth network access (SSH + web UI) when Wi-Fi is down
🎨 **NFT Gallery** – Upload CSV or single NFTs, automatic download & IPFS pinning
📚 **CSV Library** – Browse curated collections, download CSV lists, or install & pin directly
📦 **Device Preload** – Ship devices with CSV collections or full NFT galleries pre-installed
🖼️ **Fullscreen Gallery** – Rotating gallery with touch controls and adjustable intervals
🔄 **OTA Updates** – One-click remote updates without SSH
⚡ **Self-Hosted** – No cloud, no subscriptions, fully offline-capable

---

## Quick Start

The full guide, including screen, rotation, touch, NFT import and troubleshooting, is in [INSTALL.md](INSTALL.md). The short version:

### 1. Get the hardware

See [Hardware Recommendations](#hardware-recommendations). The reference build is a Raspberry Pi 5 with a Waveshare 4inch DPI LCD (C) screen.

### 2. Flash Raspberry Pi OS (64-bit, with desktop)

In Raspberry Pi Imager:
- **OS:** Raspberry Pi OS (64-bit), the normal desktop version, current (Trixie-based) release.
  - Not **Lite**: the kiosk runs inside the desktop's Wayland (labwc) session.
  - Not **Bookworm / Legacy**: the installer needs packages (e.g. `log2ram`) that only exist in the Trixie repositories.
- **OS customisation:** set a hostname (e.g. `vernis`), a username and password, your Wi-Fi, and enable SSH.

### 3. Clone and install

```bash
ssh <your-user>@vernis.local

sudo apt update && sudo apt install -y git   # git is usually already installed
git clone https://github.com/AfroV/vernis.git
cd vernis
bash install.sh                  # as your normal user - NOT with sudo
sudo reboot
```

`install.sh` stages the files from your clone and runs the real installer, `scripts/install-vernis.sh`. Do not run `scripts/install-vernis.sh` directly from a clone: it would not find the app files to deploy. The installer uses `sudo` itself where needed, needs internet access, and takes a while. It does **not** reboot on its own.

It installs Caddy, the Flask API, an IPFS node (Kubo), Chromium in kiosk mode, the Waveshare screen drivers with a touch fix, and sets the built-in screen to 90° rotation. Details in [INSTALL.md](INSTALL.md#what-the-installer-does).

### 4. After the reboot

- The screen shows Vernis full-screen. On the Waveshare screen it comes up rotated 90° with touch mapped to match. If an HDMI display is plugged in, Vernis uses that instead.
- On your phone or laptop, open `http://vernis.local` (your hostname) or `http://<pi-ip-address>`.
- The frame shows a QR code: scan it with your phone to open the setup wizard (or open the address shown and type the 6-digit code). Set a device password, then import your wallet (needs a free OpenSea API key, see [Importing your NFTs](INSTALL.md#importing-your-nfts)) or skip to **Library → Add Collection** to upload a CSV.

---

## Architecture

```
Raspberry Pi OS (64-bit, desktop) on microSD or USB SSD
├── Caddy (:80) → static web UI in /var/www/vernis/, proxies /api/* and /nfts/* to Flask
├── Flask API on localhost:5000 (/opt/vernis/app.py)
├── IPFS node (Kubo), gateway on 127.0.0.1:8080, repo in ~/.ipfs
├── Chromium kiosk, started by the labwc desktop session
├── Systemd services:
│   ├─ vernis-api.service (Flask backend)
│   ├─ ipfs.service (IPFS daemon)
│   ├─ caddy.service (web server)
│   ├─ vernis-watchdog.service (restarts Chromium if it dies)
│   ├─ vernis-touch-wake.service (touch to wake the screen)
│   └─ bt-agent.service + bt-pan.service (Bluetooth network access)
└── NFT downloader scripts in /opt/vernis/scripts/
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
    │   ├── nft_downloader_advanced.py → NFT download script
    │   ├── vernis-update.sh          → Updater run by Settings → Install update
    │   ├── kiosk-launcher.sh         → Starts the Chromium kiosk
    │   ├── watchdog.sh               → Screen monitor (kiosk)
    │   └── create-update-package.sh  → Build update bundle
    └── backup/            → Update backups

/etc/systemd/system/       → Service files
/etc/caddy/Caddyfile       → Web server config
~/.config/labwc/autostart  → Kiosk autostart (runs kiosk-launcher.sh)
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

## Kiosk Mode (built-in screen)

The installer always sets up kiosk mode. On boot:

1. The desktop logs in automatically and labwc runs `~/.config/labwc/autostart`, which hides the desktop panel and starts `/opt/vernis/scripts/kiosk-launcher.sh`
2. The launcher waits for the web server, applies the saved display output and rotation (`display-output.sh`), and starts Chromium in kiosk mode on `http://127.0.0.1/`
3. `vernis-watchdog.service` restarts Chromium if it stops or the page crashes

Screen setup, rotation and touch: see [INSTALL.md](INSTALL.md#screen).

---

## When Wi-Fi Is Down

The installer does not create a Wi-Fi fallback access point. It sets up Bluetooth networking (`scripts/setup-bluetooth-pan.sh`) so you can still reach the frame:

1. Pair once while Wi-Fi still works: over SSH run `sudo bluetoothctl discoverable on`, pair your phone or laptop with `Vernis-<hostname>`, then run `sudo bluetoothctl discoverable off`
2. When Wi-Fi is down, connect to the frame's Bluetooth network (PAN) from that paired device
3. SSH to `<your-user>@10.44.0.1` (same login as usual) or open `http://10.44.0.1`

Wi-Fi itself can be changed in Settings → Wi-Fi.

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

**Backup:** Updates installed from Settings (from 3.5.1) save the previous web UI, backend and scripts to `/opt/vernis/backups/` first (last 3 kept) and roll back automatically if Vernis doesn't start afterwards. To go back by hand: `sudo bash /opt/vernis/scripts/rollback-update.sh`. Your art and settings are not part of these backups — use Settings → Backup for those.

---

## AI Curator

Settings → AI Curator lets you talk to the frame through Grok, OpenAI, Claude or a local model (Ollama / LM Studio). Grok, OpenAI and local models work out of the box.

**Claude needs a one-time setup.** The Anthropic SDK needs newer Python packages than Raspberry Pi OS ships, so it runs in its own virtual environment. Over SSH:

```bash
sudo python3 -m venv /opt/vernis/curator-venv
sudo /opt/vernis/curator-venv/bin/pip install anthropic
```

If the Curator itself is unavailable, `journalctl -u vernis-api | grep curator` shows why; installing the latest update restores missing Curator files.

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

More in [INSTALL.md](INSTALL.md#troubleshooting).

### Can't access http://vernis.local

Use your own hostname (`http://<hostname>.local`). If `.local` names don't resolve on your network, use the IP address:
```bash
hostname -I
# then open http://<first address>
```

### Flask API not running

```bash
sudo systemctl status vernis-api
sudo journalctl -u vernis-api -f
```

### Kiosk mode not starting

```bash
# The kiosk is started by the labwc desktop session
cat ~/.config/labwc/autostart
```
If the Pi stops at a login screen (the installer normally turns on autologin), enable it: `sudo raspi-config` → System Options → Boot / Auto Login → Desktop Autologin, then reboot.

### No NFTs downloading

Check that the IPFS node is running (Settings → IPFS Pinning, or `sudo systemctl status ipfs`) and, for wallet imports, that an OpenSea API key is set. See [INSTALL.md](INSTALL.md#ipfs-node).

---

## Security Notes

⚠️ **This is designed for local/private networks**

- No HTTPS by default (add with Caddy if exposing publicly)
- Open by default; optional PIN protection (see [Security](#security) below)
- Runs Flask in production without WSGI (fine for local use, use Gunicorn if public)
- The installer gives the install user passwordless sudo for a fixed list of commands the API needs (reboot, service restarts, Wi-Fi, firewall, display settings) in `/etc/sudoers.d/vernis-api`
- The installer enables the `ufw` firewall (SSH, HTTP and IPFS port 4001 only) and `fail2ban`

**For public deployment:**
1. Enable Caddy automatic HTTPS
2. Add authentication to Flask endpoints
3. Run Flask via Gunicorn/uWSGI
4. Firewall non-essential ports
5. Change default passwords

---

## Hardware Recommendations

- **Raspberry Pi 5** (reference build) or **Raspberry Pi 4**. Boards with less than 2 GB RAM: after installing, run `sudo bash /opt/vernis/scripts/setup-swap.sh`.
- **Screen (reference): Waveshare 4inch DPI LCD (C)**, 720x720, mounted on the 40-pin GPIO header. The installer sets it up automatically, rotated 90°, with touch.
- **Or any HDMI monitor or TV.** Vernis switches to HDMI automatically when one is connected (Settings → Display Settings → Display Output).
- **Storage:** microSD card (32 GB minimum) or a USB SSD. Your art and the IPFS store (capped at 50 GB) live on this drive, so pick a size that fits your collection.
- **Official power supply** for your Pi model.
- **Fan (optional):** with the DPI screen, GPIO 0-25 are taken by the display. Put a `gpio-fan` on GPIO 26 or 27; the installer disables a `gpio-fan` overlay on any of GPIO 0-25.

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

1. **Hold the VERNIS logo** on the frame's home screen, then tap **Reset PIN** in the menu that opens. A modal asks for your device password. Enter it, optionally set a new PIN, and you're back in.
2. **SSH into the Pi** and run `sudo /opt/vernis/scripts/reset-pin.sh` to wipe the PIN and drop back to Open mode.

The logo recovery only works once the frame knows your device password. On a fresh install that is the case only if you ran the installer with `INSTALL_USER_PASSWORD` set (see [INSTALL.md](INSTALL.md#4-run-the-installer)); otherwise run `sudo /opt/vernis/scripts/update-owner-password.sh` once after installing.

### Changed your device password via `passwd`?

If you change your Linux password via `passwd` over SSH (instead of through Settings), the recovery hash goes stale. Re-sync it:

```bash
sudo /opt/vernis/scripts/update-owner-password.sh
```

Settings → Security → Change Password keeps everything in sync automatically.
