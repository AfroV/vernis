# Vernis Troubleshooting Guide — Prompt for Claude Code

Copy everything below this line and paste it as your first message to Claude Code on the Raspberry Pi (or on your laptop while SSH'd into the Pi).

---

You are helping me set up and troubleshoot **Vernis**, an NFT digital art frame running on a Raspberry Pi. Here is everything you need to know:

## What is Vernis?

Vernis is a kiosk-mode art display system. It runs on Raspberry Pi with:
- **Caddy** web server serving the UI from `/var/www/vernis/`
- **Flask API** backend at `/opt/vernis/app.py` (systemd service: `vernis-api`)
- **IPFS (Kubo)** daemon for pinning artwork (systemd service: `ipfs`)
- **Chromium** in kiosk mode via labwc (Wayland compositor)
- NFT artwork stored in `/opt/vernis/nfts/`
- CSV library files in `/opt/vernis/csv-library/`
- Storage config in `/opt/vernis/storage-config.json`
- User files in `/opt/vernis/files/`

## Key Services

| Service | Purpose | Config |
|---------|---------|--------|
| `vernis-api` | Flask backend (port 5000) | `/opt/vernis/app.py` |
| `caddy` | Web server (port 80), reverse proxy to Flask | `/etc/caddy/Caddyfile` |
| `ipfs` | IPFS daemon for pinning | `~/.ipfs/config` |
| `vernis-watchdog` | Screen watchdog | `/opt/vernis/scripts/watchdog.sh` |
| `vernis-touch-wake` | Touch-to-wake display | `/opt/vernis/scripts/touch-to-wake.sh` |
| `vernis-hue-stream` | Hue light sync (on-demand) | `/opt/vernis/scripts/hue-entertainment-daemon.py` |

## Diagnostics — Run These First

Run these commands and share the output so we can understand the current state:

```bash
# 1. System overview
echo "=== HOSTNAME ===" && hostname
echo "=== OS ===" && cat /etc/os-release | head -4
echo "=== KERNEL ===" && uname -a
echo "=== UPTIME ===" && uptime
echo "=== MEMORY ===" && free -h
echo "=== DISK ===" && df -h
echo "=== CPU ===" && cat /proc/cpuinfo | grep "Model\|model name" | head -1

# 2. Service status
echo "=== SERVICES ==="
for svc in vernis-api caddy ipfs vernis-watchdog vernis-touch-wake; do
    echo "$svc: $(systemctl is-active $svc)"
done

# 3. Check if web UI and API are responding
echo "=== API HEALTH ==="
curl -s http://localhost/api/health 2>&1 | head -5

# 4. Storage detection
echo "=== BLOCK DEVICES ==="
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL
echo "=== MOUNTS ==="
mount | grep -E '/mnt/|/media/'

# 5. USB devices
echo "=== USB DEVICES ==="
lsusb

# 6. Logs (last errors)
echo "=== VERNIS API ERRORS (last 20) ==="
journalctl -u vernis-api --no-pager -n 20 --priority=err 2>/dev/null || echo "no errors"
echo "=== DMESG USB/STORAGE (last 20) ==="
dmesg | grep -iE 'usb|sd[a-z]|mount|error|fail' | tail -20
```

## Common SSD/Storage Issues

### Problem: SSD not detected
- Check `lsblk` — does the drive appear?
- Check `dmesg | grep -i usb` — USB enumeration errors?
- Some USB-SATA adapters don't support UAS. Fix: `echo "options usb-storage quirks=VENDOR:PRODUCT:u" | sudo tee /etc/modprobe.d/usb-storage.conf` then reboot
- Pi USB ports may not provide enough power for 2.5" SSDs. Try a powered USB hub.

### Problem: SSD detected but not mounted
- Find partition: `lsblk` (look for `sda1` or similar)
- Check filesystem: `sudo blkid /dev/sda1`
- Mount manually: `sudo mkdir -p /mnt/ssd && sudo mount /dev/sda1 /mnt/ssd`
- For auto-mount on boot, add to `/etc/fstab`:
  ```
  UUID=<uuid-from-blkid>  /mnt/ssd  ext4  defaults,noatime,nofail  0  2
  ```
  Use `nofail` so boot doesn't hang if SSD is disconnected.

### Problem: SSD mounted but Vernis doesn't see it
- Vernis looks for external drives under `/media/` and `/mnt/`
- Check the web UI: Settings > Storage > External Storage section
- Use "Detect Drives" button, or check the API: `curl -s http://localhost/api/storage/external/detect | python3 -m json.tool`
- The drive must have >1GB capacity and be writable
- To configure: go to Settings > Storage, select the drive, enable external storage
- Or via API: `curl -X POST http://localhost/api/storage/external/configure -H 'Content-Type: application/json' -d '{"use_external": true, "external_path": "/mnt/ssd"}'`

### Problem: Permission denied on SSD
- Check ownership: `ls -la /mnt/ssd`
- Fix: `sudo chown -R $(whoami):$(whoami) /mnt/ssd`
- If NTFS: mount with proper permissions: `sudo mount -o uid=$(id -u),gid=$(id -g) /dev/sda1 /mnt/ssd`
- If ext4: just chown. If exFAT: `sudo apt install exfat-fuse exfat-utils` then remount

### Problem: SSD randomly disconnects
- Check `dmesg | tail -50` for USB reset errors
- UAS incompatibility: disable UAS for the drive (see "SSD not detected" above)
- Power issue: use powered USB hub
- Cable issue: try a different USB cable (short, high-quality)
- Check SMART health: `sudo apt install smartmontools && sudo smartctl -a /dev/sda`

## Formatting an SSD for Vernis

If the SSD needs formatting (WARNING: destroys all data):
```bash
# Find the device (usually /dev/sda)
lsblk

# Create partition table and ext4 filesystem
sudo parted /dev/sda mklabel gpt
sudo parted /dev/sda mkpart primary ext4 0% 100%
sudo mkfs.ext4 -L vernis-storage /dev/sda1

# Mount and set permissions
sudo mkdir -p /mnt/ssd
sudo mount /dev/sda1 /mnt/ssd
sudo chown -R $(whoami):$(whoami) /mnt/ssd

# Auto-mount on boot
UUID=$(sudo blkid -s UUID -o value /dev/sda1)
echo "UUID=$UUID  /mnt/ssd  ext4  defaults,noatime,nofail  0  2" | sudo tee -a /etc/fstab
```

## General Vernis Troubleshooting

### Web UI not loading
1. Check Caddy: `sudo systemctl status caddy`
2. Check Flask API: `sudo systemctl status vernis-api`
3. Check Caddy config: `cat /etc/caddy/Caddyfile`
4. Restart both: `sudo systemctl restart vernis-api caddy`

### Screen is black / kiosk not starting
1. Check if labwc is running: `pgrep labwc`
2. Check kiosk launcher: `cat /opt/vernis/scripts/kiosk-launcher.sh`
3. Check autostart: `cat ~/.config/labwc/autostart`
4. Check Chromium process: `pgrep chromium`

### IPFS not working
1. Check daemon: `sudo systemctl status ipfs`
2. Check peers: `ipfs swarm peers | wc -l`
3. Restart: `sudo systemctl restart ipfs`

### Display issues (Waveshare 4" DPI LCD)
- Config file: `/boot/firmware/config.txt` (Pi 5) or `/boot/config.txt`
- `over_voltage` MUST be >= 4 for DPI displays (lower causes scan lines)
- Do NOT use `pwm-2chan` overlay (conflicts with backlight driver)
- GPIO fan must NOT be on DPI pins (0-9, 12-17, 20-25). Safe pins: 10, 11, 18, 19, 26, 27

### NFTs not showing in gallery
1. Check NFT directory: `ls /opt/vernis/nfts/ | head`
2. Check API: `curl -s http://localhost/api/artworks | python3 -m json.tool | head -20`
3. If using external storage, verify config: `cat /opt/vernis/storage-config.json`

## Low-RAM Optimization (Pi Zero 2W, old Pi 3)

If the Pi has < 2GB RAM:
```bash
sudo bash /opt/vernis/scripts/setup-swap.sh
```

## Files Reference

- Install script: `/opt/vernis/scripts/install-vernis.sh`
- All scripts: `/opt/vernis/scripts/`
- Web UI: `/var/www/vernis/` (index.html, gallery.html, settings.html, lab.html, manage.html, add.html, library.html)
- Backend: `/opt/vernis/app.py`
- Firewall: `sudo ufw status`
- Sudoers: `/etc/sudoers.d/vernis-api`

## Important

- Always check service logs with `journalctl -u <service-name> -n 50 --no-pager`
- Always check `dmesg` for hardware issues
- The diagnostic endpoint `curl -s http://localhost/api/diagnostics` generates a full system report
- After fixing issues, restart the relevant service: `sudo systemctl restart vernis-api`
- After boot config changes: `sudo reboot`
