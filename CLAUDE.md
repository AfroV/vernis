# Vernis v3 - Project Notes

## Pi Device Credentials

| Name | Host | Username | Password | Auth Method |
|------|------|----------|----------|-------------|
| afrol | 10.0.0.28 | afrol | <device-password> | Password |
| afroz | 10.0.0.34 | afroz | <device-password> | Password |
| afrom | 10.0.0.39 | afrom | <device-password> | Password |
| afromini | 10.2.0.8 | afromini | <device-password> | Password |

## Deployment

**IMPORTANT: Two different directories!**
- Web UI (HTML, CSS, JS): `/var/www/vernis/` (served by Caddy)
- Backend (app.py, scripts): `/opt/vernis/` (Flask API)

To deploy files:
```bash
# For afroz (password) - WEB UI FILES (html, css, js)
cat file.html | sshpass -p '<device-password>' ssh afroz@10.0.0.34 "cat > /tmp/file.html && echo '<device-password>' | sudo -S mv /tmp/file.html /var/www/vernis/"

# For afroz (password) - BACKEND FILES (app.py)
cat app.py | sshpass -p '<device-password>' ssh afroz@10.0.0.34 "cat > /tmp/app.py && echo '<device-password>' | sudo -S mv /tmp/app.py /opt/vernis/"

# Restart Flask after backend changes
sshpass -p '<device-password>' ssh afroz@10.0.0.34 "echo '<device-password>' | sudo -S systemctl restart vernis-api"

# For afromini (password) - WEB UI FILES
cat file.html | sshpass -p '<device-password>' ssh afromini@10.2.0.8 "cat > /tmp/file.html && echo '<device-password>' | sudo -S mv /tmp/file.html /var/www/vernis/"

# For afro (SSH key) - WEB UI FILES
cat file.html | ssh afro@10.2.0.14 "cat > /tmp/file.html && sudo mv /tmp/file.html /var/www/vernis/"
```

## Key Files

- `backend/app.py` - Flask backend with all API endpoints
- `settings.html` - Settings page with IPFS, storage, WiFi, thermal monitoring
- `gallery.html` - Fullscreen gallery view
- `scripts/nft_downloader_advanced.py` - NFT download and pinning script
- `scripts/kiosk-launcher.sh` - Chromium kiosk mode launcher
- `scripts/setup-swap.sh` - Swap and memory optimization for low-RAM Pis
- `scripts/setup-waveshare-4dpi.sh` - Waveshare 4inch DPI LCD (C) display setup
- `scripts/enrich_nft_csv.py` - Enrich CSV files with IPFS CIDs via Reservoir API

## Memory Optimization

For low-RAM Pis (<2GB), run:
```bash
sudo bash /opt/vernis/scripts/setup-swap.sh
```

This script:
- Creates 2GB swapfile
- Sets up zram (compressed RAM swap)
- Adds memory-saving Chromium flags
- Configures process memory limits

Device RAM status:
- afro (10.2.0.14): 7.6GB - no optimization needed
- afroz (10.2.0.9): 416MB - optimizations applied
- afromini (10.2.0.8): unknown - check and apply if needed

## Waveshare 4inch DPI LCD (C) Setup (Testing)

For devices with Waveshare 4inch DPI LCD (C) display:
```bash
sudo bash /opt/vernis/scripts/setup-waveshare-4dpi.sh
```

Manual setup if needed:
1. Edit `/boot/config.txt` (or `/boot/firmware/config.txt` on Pi 5)
2. Add overlays:
   ```
   dtoverlay=vc4-kms-v3d
   dtoverlay=waveshare-4dpic-4b
   dtoverlay=waveshare-touch-4dpi
   ```
3. Download overlay files from https://www.waveshare.com/wiki/4inch_DPI_LCD_(C)
4. Copy .dtbo files to `/boot/overlays/`
5. Reboot

Troubleshooting:
- Comment out `dtoverlay=vc4-fkms-v3d` if present (conflicts)
- Use latest 64-bit Raspberry Pi OS (Bookworm+) for best KMS/DPI support
- If backlight on but no image = config issue
- If no backlight = connection/power issue

## Completed Tasks (2026-01-25)

- [x] Toggle switches instead of checkboxes (premium look)
- [x] CSV template download button on Add Collection page
- [x] Renamed library subtitle to "Right click and save..."
- [x] Download progress bar visible for Install and Pin
- [x] Connect card with QR code added to index page
- [x] Removed Wallet Manager section
- [x] Removed Collection Management section
- [x] Removed "Pin All Artworks" from settings
- [x] Import Backup button added
- [x] External drive read-only option added
- [x] XCOPY theme created (neon cyan/magenta, glitch effects, logo changes to "XCOPY")

## Q&A

**Q: Why does Storage Allocation say "Available for NFTs: 10.1 GB" but Storage Health shows 5.5 GB free?**
A: Storage Allocation shows total space allocated/available for NFTs specifically, while Storage Health shows the actual free disk space on the system. The difference is because the system reserves space for OS, logs, swap, and other files.

**Q: Do I need "Force Horizontal Orientation - Rotate vertical images to horizontal"?**
A: No, this is redundant. You already have Orientation settings in Settings > Display. The "Force Horizontal" option can be removed as it duplicates functionality.

## Completed Tasks (2026-01-25 continued)

- [x] HTTPS opt-in setup with user instructions (Settings > Security section)
- [x] Sort NFTs by collection / last downloaded (Manage NFTs page, sort dropdown)
- [x] Custom carousels - save, load, delete, download, import (Manage NFTs page)
- [x] Backup & Restore progress bar
- [x] Disk health scan toggle + execute button with report (Settings > Storage)
- [x] Known Origin IPFS CID scraper (/opt/vernis/scripts/known_origin_scraper.py)
- [x] Removed themes: Classic Deco, Modern Minimal, Luxury Edition
- [x] Removed "Force Horizontal Orientation" option
- [x] NFT Metadata Cache system (Manage NFTs page) - collection/artist filters, scan, edit metadata

## NFT Metadata System

The Manage NFTs page now supports metadata-based organization:
- **Cache file**: `/opt/vernis/nft-metadata-cache.json`
- **API endpoints**:
  - `GET /api/nft-metadata` - Get all cached metadata
  - `POST /api/nft-metadata/scan` - Scan all NFTs and extract metadata from filenames
  - `POST /api/nft-metadata/<filename>` - Update metadata for a single NFT
- **UI Features**:
  - Collection filter dropdown
  - Artist filter dropdown
  - "Scan All" button - indexes NFTs and extracts collection from filename patterns
  - "Edit Selected" button - manually set name, collection, artist, description

## Scripts

**Known Origin Scraper:**
```bash
python3 /opt/vernis/scripts/known_origin_scraper.py --output known_origin.csv --limit 100 -v
```
Scrapes IPFS CIDs from Known Origin NFT marketplace. Requires internet connectivity.

## Q&A (Additional)

**Q: How to use JSON file content to organize IPFS NFT art files?**
A: NFT JSON metadata contains fields like "name", "image", "attributes" (traits), "collection".
To use for organization:
1. Parse JSON metadata files alongside NFT images
2. Extract attributes like collection, artist, category
3. Store parsed metadata in local database or JSON for quick filtering
4. The Manage NFTs page already extracts collection from filename prefixes

## Security — PIN, Modes, Recovery (2026-05-15)

Three modes in Settings → Security: **A — Open**, **B — Protected** (PIN gates deletes), **C — Locked** (PIN gates control + delete; home view stays open).

### Files
- `/opt/vernis/security.json` — config (mode, bcrypt PIN hash, owner password hash)
- `/opt/vernis/security-sessions.json` — active session tokens
- `/opt/vernis/security-failures.json` — per-IP and global lockout counters
- `/opt/vernis/audit.log` — JSON-lines audit log (rotates at 10 MB)

### Recovery
- **SSH:** `sudo /opt/vernis/scripts/reset-pin.sh`
- **Logo long-press:** hold `.kiosk-logo` for 5 s → enter device password.

### After changing device password via `passwd`
Run `sudo /opt/vernis/scripts/update-owner-password.sh` to re-sync the recovery hash.

### Reverse-proxy trust
Caddy sets `X-Forwarded-For: {client_ip}` per `reverse_proxy` directive. **Do NOT set `trusted_proxies`** — that would tell Caddy to honor client-supplied XFF headers, which lets a LAN attacker spoof their source as `127.0.0.1` and bypass the kiosk trust check. Flask reads the header via `ProxyFix(x_for=1)`. The kiosk on the Pi is identified by `127.0.0.1` (genuine localhost loopback) and is always trusted.

### Migration on already-deployed devices
```bash
INSTALL_USER_PASSWORD='<device pwd>' sudo -E bash /opt/vernis/scripts/migrate-security-init.sh
```
