# Vernis Device Version Tracker

Last updated: 2026-04-29

## Current Repo Hashes (latest)

| File | MD5 | Deploy to |
|------|-----|-----------|
| app.py | `6e68ec756ebeafe73bc52c6d0315ffc1` | /opt/vernis/ |
| gallery.html | `81bb5ec22a6acb14f84230c800cd6751` | /var/www/vernis/ |
| index.html | `2ee342c3127563561e3b539199332de4` | /var/www/vernis/ |
| library.html | `d7a135019f095b7dc182c29bd4ed11ab` | /var/www/vernis/ |
| settings.html | `f90597df9a1ab06f41b5bd5cfc78054a` | /var/www/vernis/ |
| nft_downloader_advanced.py | `d5dbe4729bc61080c53d109510b9d66c` | /opt/vernis/scripts/ |
| kiosk-launcher.sh | `8b2a1d677431145904a9cb0306c795e8` | /opt/vernis/scripts/ |
| install-vernis.sh | `8ad858207cb69a7d519046dd8f7e566e` | /opt/vernis/scripts/ |
| setup-bluetooth-pan.sh | `7558979584677871218a8f10bfbb17ab` | /opt/vernis/scripts/ |

## Boot Splash Rotation

The Waveshare 4" DPI panel requires the boot splash to be rotated 270° CW from the upright source image.
- Source file: `splash-upright.png` (md5: `d0e7875b853ffd1b3a2ff6e337c81b77`)
- Correct rotation: `convert splash-upright.png -rotate 270 splash.png` then `update-initramfs -u`

| Device | Splash hash | Upright source | Rotated correctly | Verified |
|--------|-------------|----------------|-------------------|----------|
| vernis1 | `27e7fa39` | `d0e7875b` | Yes (fixed 2026-04-10) | Was 90° CW, corrected to 270° CW |
| vernis2 | Unknown | Unknown | Likely yes (fixed earlier) | Offline |
| vernis3 | Unknown | Unknown | Likely yes (fixed earlier) | Offline |
| vernis4 | `dd99427b` | No upright file* | Yes (270° CW) | Visually confirmed |
| vernis5 | `50827f28` | `d0e7875b` | Yes (fixed 2026-04-10) | Visually confirmed |
| vernis6 | `42fa1c6d` | `d0e7875b` | Yes (fixed 2026-04-10) | Visually confirmed |
| vernis7 | Unknown | Unknown | Likely yes (fixed earlier) | Offline |

*vernis4 has no splash-upright.png (older install) but splash was already rotated correctly.

## Device Status

| Device | IP | Files | Sudoers (28) | NoNewPriv=false | JSON configs | config.txt clean | WiFi PS off | Splash 270° | Balanced | Source map repaired | Status |
|--------|-----|-------|-------------|-----------------|--------------|-----------------|-------------|-------------|----------|---------------------|--------|
| vernis1 | 10.0.0.40 | All current | 28 entries | Yes | OK | OK | Yes | Yes (fixed) | Yes | – (no wallets) | **Up to date** |
| vernis2 | 10.0.0.41 | All current | 28 entries | Yes | OK | OK | Yes | Yes | Yes | – (no wallets) | **Up to date** (offline) |
| vernis3 | 10.0.0.43 | All current | 28 entries | Yes | OK | OK | Yes | Yes | Yes | – (no wallets) | **Up to date** (offline) |
| vernis4 | 10.0.0.44 | All current | 28 entries | Yes | OK | OK | Yes | Yes | Yes | – (no wallets) | **Up to date** |
| vernis5 | 10.0.0.45 | All current | 28 entries | Yes | OK | OK | Yes | Yes | Yes | – (no wallets) | **Up to date** |
| vernis6 | 10.0.0.42 | All current | 28 entries | Yes | OK | OK | Yes | Yes | Yes | – (no wallets) | **Up to date** |
| vernis7 | 10.0.0.46 | All current | 28 entries | Yes | OK | OK | Yes | Yes | Yes | – (no wallets) | **Up to date** (offline) |
| afrol | 10.0.0.28 | All current | 24 entries (vernis-api) | Yes | OK | OK | Yes | Unknown | Yes | Pending (offline) | **Up to date** (splash unverified) |
| afroz | 10.0.0.34 | Needs update | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | Pending (offline) | **Offline - Needs Update** |
| afrom | 10.0.0.39 | All current | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | Yes (2026-04-29) | **Up to date** |
| afromini | 10.2.0.8 | Needs update | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | Pending | **Separate net (10.2.x)** |

## Vernis1 Splash Fix (completed 2026-04-10)

Splash was rotated 90° CW instead of 270° CW. Fixed from splash-upright.png source and initramfs updated.

## Checklist for updating a device

1. **Files**: Deploy all files from repo (app.py, gallery, index, library, settings, downloader, kiosk-launcher, install, bt-pan)
2. **Sudoers**: 28 entries covering reboot, shutdown, systemctl, nmcli, tee, chpasswd, bash scripts
3. **Service**: `User=<devicename>`, `NoNewPrivileges=false`
4. **JSON configs**: display-config, display-output-config, fan-config, setup-complete — must start with `{`
5. **config.txt**: No `<device-password>` junk lines, `over_voltage=4`, DPI overlays present
6. **WiFi**: `/etc/NetworkManager/conf.d/wifi-powersave.conf` with `wifi.powersave = 2`
7. **Splash**: Rotated 270° CW from `splash-upright.png`, then `update-initramfs -u`
8. **CPU profile**: Balanced (`arm_freq=1500`)
9. **dpi-backlight**: Disabled
10. **Source map repair** (only on devices with wallet auto-sync that ran the buggy downloader — see next section)

## Source map repair (one-time, post 2026-04-29)

Before 2026-04-29 the downloader's source-map writer claimed every existing file in `/opt/vernis/nfts/` for whichever CSV ran most recently. Result: `nft-source-map.json` ended up entirely tagged with one collection (the last wallet auto-sync), corrupting "Pin IPFS Files" totals and per-collection file lists.

**Detection** (run on the Pi):

```bash
python3 -c "import json,collections;print(collections.Counter(json.load(open('/opt/vernis/nfts/nft-source-map.json')).values()))"
```

If the output shows ~all entries under one CSV, the source map is corrupted.

**Repair** (idempotent, backs up the old map to `nft-source-map.json.bak`):

```bash
sudo python3 /opt/vernis/scripts/rebuild_source_map.py
```

Only matters on Pis that have multiple CSVs sharing `/opt/vernis/nfts/` (typically wallet auto-sync devices). Stock vernis devices without wallets are unaffected.

## Health check script

```bash
bash scripts/check-device-health.sh
```
