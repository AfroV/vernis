# Vernis Installation Guide

How to build a Vernis frame from this repository. The whole install is one script, run on the Pi over SSH. It sets up the web UI, the API, an IPFS node, the kiosk browser, and the Waveshare screen with rotation and touch.

## What you need

- **Raspberry Pi 5** (reference build) or **Raspberry Pi 4**
- **Screen:** Waveshare 4inch DPI LCD (C), 720x720 (reference), or any HDMI monitor/TV
- **Storage:** microSD card, 32 GB or more, or a USB SSD. Art and the IPFS store live here.
- **Official power supply** for your Pi
- A computer with **Raspberry Pi Imager**
- **Internet access on the Pi** during the install (Wi-Fi or Ethernet)

## 1. Flash Raspberry Pi OS

In Raspberry Pi Imager:

1. **Device:** your Pi model.
2. **OS:** **Raspberry Pi OS (64-bit)**, the normal version *with desktop*, current (Trixie-based) release.
   - **Not Lite.** The kiosk runs inside the desktop's Wayland session (labwc).
   - **Not Bookworm / "Legacy".** The installer installs `log2ram`, which only exists in the Trixie repositories. On Bookworm the installer stops at step 1 with `Unable to locate package log2ram`.
3. **OS customisation** (the settings/gear step):
   - Hostname, e.g. `vernis`
   - Username and password: any name works; the installer installs for whoever runs it
   - Wi-Fi network, password and country
   - Enable SSH with password authentication
   - Locale and timezone
4. Write the card.

Keep it to one user account. A few helper scripts assume the desktop user is the first (UID 1000) account.

## 2. Connect the screen and boot

1. With the Pi **powered off**, fit the Waveshare screen on the 40-pin GPIO header (or plug in HDMI).
2. Insert the card and power on. Give the first boot a few minutes.
3. The Waveshare screen stays **black until the installer has run and the Pi has rebooted**. Its drivers aren't installed yet, so this is normal. Use SSH.
4. Find the Pi: `ping vernis.local` (your hostname), or look in your router's device list.

```bash
ssh <your-user>@vernis.local
```

Optional check that you flashed the right OS:

```bash
grep VERSION_CODENAME /etc/os-release     # should print: VERSION_CODENAME=trixie
```

## 3. Get the code

```bash
sudo apt update && sudo apt install -y git     # git is usually already installed
git clone https://github.com/AfroV/vernis.git
cd vernis
```

## 4. Run the installer

From the `vernis` folder, **as your normal user, not with sudo**:

```bash
bash install.sh
```

- `install.sh` copies the app files from your clone into the layout the real installer expects, then runs **`scripts/install-vernis.sh`**. Don't run `scripts/install-vernis.sh` directly from a clone: it can't find the app files there, so the Pi ends up with no web UI or API.
- The installer refuses to run as root and calls `sudo` itself where it needs to. If you start it with `sudo bash install.sh`, it switches back to your user.
- It downloads a lot (packages, Caddy, the IPFS node, Waveshare drivers), so it takes a while.
- If it stops partway (usually a network hiccup), fix the cause and run `bash install.sh` again. The script is written to be safe to re-run.
- Optional: to make the PIN recovery described in the README (holding the logo for 5 seconds) work, the frame needs a hash of your device password. Either run the installer as
  `INSTALL_USER_PASSWORD='<your login password>' bash install.sh`
  (the password ends up in your shell history), or after installing run
  `sudo /opt/vernis/scripts/update-owner-password.sh`, which asks for the password.

When it prints **Installation Complete!**, reboot. The installer does not reboot by itself:

```bash
sudo reboot
```

## 5. After the reboot

- The Vernis logo shows during boot, then Vernis comes up full-screen. On the Waveshare screen it is **rotated 90°, with touch mapped to match**. If an HDMI display is connected, Vernis uses that instead.
- From your phone or laptop, open `http://vernis.local` (your hostname) or `http://<pi-ip-address>`.
- The frame's screen shows **Set up your Vernis** with a QR code and a 6-digit code. Scan the QR code with your phone (or open the address shown and type the code). This proves you're at the frame, so nobody else on your Wi-Fi can claim it.
- The **setup wizard** then opens on your phone: set the device password, then import your wallet (it asks for the OpenSea API key, see [Importing your NFTs](#importing-your-nfts)). You can skip either step. No code on the screen? The wizard also accepts the password you chose in Raspberry Pi Imager.

Quick health check over SSH:

```bash
systemctl status vernis-api ipfs caddy --no-pager
curl -s http://localhost/api/status
```

## What the installer does

`scripts/install-vernis.sh`, in order (it prints its own `[n/17]` progress markers):

- Installs packages (Chromium, Python/Flask, ffmpeg, ImageMagick, wayvnc, ufw, fail2ban, log2ram, Bluetooth tools and others), Python modules (`qrcode`, `pillow`, `requests`, `pycryptodome`, `websocket-client`, `bcrypt`), and Caddy (from Caddy's repository, or a checksum-pinned official release if that repository is unavailable).
- Installs the **IPFS node** (Kubo v0.39.0) to `/usr/local/bin/ipfs`, creates the repo in `~/.ipfs` (low-power profile, 50 GB storage cap, gateway on `127.0.0.1:8080`), and enables the `ipfs` systemd service.
- Copies the web UI to `/var/www/vernis/`, the backend to `/opt/vernis/`, scripts to `/opt/vernis/scripts/`, and the curated collections to `/opt/vernis/csv-library/` (existing ones are kept). Creates the security config in Open mode with no PIN.
- Writes the Caddy config (serves port 80, proxies `/api/*` and `/nfts/*` to Flask).
- Creates `vernis-api.service` (runs as your user) and a limited sudo rule file, `/etc/sudoers.d/vernis-api`.
- Sets up the kiosk: turns on desktop autologin for your user, and `~/.config/labwc/autostart` hides the desktop panel and runs `/opt/vernis/scripts/kiosk-launcher.sh`. Also hides the mouse cursor.
- Enables `vernis-watchdog` (restarts Chromium if it dies) and `vernis-touch-wake`.
- Installs the Philips Hue streaming service (not enabled; it starts on demand), an HDMI hotplug rule, a font, turns off Wi-Fi power saving, and sets up Bluetooth networking (see the README, "When Wi-Fi Is Down").
- Turns on automatic security updates. The kernel, Chromium and labwc are held back from automatic upgrades.
- **Screen setup** (see [Screen](#screen)): runs `setup-waveshare-4dpi.sh`, disables any `gpio-fan` overlay on GPIO 0-25, raises `over_voltage` to 4 if it is lower or missing, and patches the Waveshare touch overlay to use an interrupt instead of polling. Installs the Vernis boot splash and hides boot text.
- Firewall (`ufw`): blocks incoming connections except SSH (22), HTTP (80) and IPFS (4001).
- Puts temporary files in RAM (`setup-tmpfs.sh`), starts `vernis-api` and `ipfs`, enables `fail2ban`, and configures `log2ram` to cut SD card writes.
- Writes defaults: 15 s per image, shuffle on, silent fan, eco CPU profile, **built-in screen rotation 90° and HDMI rotation 0°**, display output **Auto**, HDMI at 1080p.

## Screen

### Waveshare 4inch DPI LCD (C): automatic

The installer always runs `/opt/vernis/scripts/setup-waveshare-4dpi.sh`, even if you only use HDMI. It:

- downloads Waveshare's overlay files (`4DPIC-DTBO.zip` from files.waveshare.com) into `/boot/firmware/overlays/`
- comments out `dtoverlay=vc4-fkms-v3d` and `display_auto_detect=1` in `/boot/firmware/config.txt`
- makes sure these are enabled (and comments out `dtoverlay=waveshare-4dpi`, which conflicts with `vc4-kms-DPI-4inch`):
  ```
  dtoverlay=vc4-kms-v3d
  dtoverlay=vc4-kms-DPI-4inch
  dtoverlay=waveshare-4dpic-4b
  dtoverlay=waveshare-touch-4dpi
  ```
- removes the old `dpi-backlight.service` if an earlier version created it (Vernis's Screen off / on buttons control the backlight instead)

The script is safe to re-run: it only adds what is missing.

The screen comes up after the reboot. At every kiosk start, `display-output.sh` applies the saved rotation (90° by default) and maps the touch controller to the screen with a matching calibration in `~/.config/labwc/rc.xml`.

If the overlay download failed (the installer prints a warning), download `4DPIC-DTBO.zip` from the [Waveshare wiki](https://www.waveshare.com/wiki/4inch_DPI_LCD_(C)), copy the `.dtbo` files to `/boot/firmware/overlays/`, then run:

```bash
sudo bash /opt/vernis/scripts/setup-waveshare-4dpi.sh
sudo reboot
```

The DPI screen uses GPIO 0-25 as its data bus. Don't connect anything else to those pins. A fan goes on GPIO 26 or 27. More in [DPI-DISPLAY-TROUBLESHOOTING.md](DPI-DISPLAY-TROUBLESHOOTING.md).

### HDMI screens

- Settings → Display Settings → **Display Output**: **Auto** (default) uses HDMI when it's connected and the built-in screen otherwise. **Internal**, **External** and **Mirror** force a choice. Plugging or unplugging HDMI switches automatically.
- HDMI runs at 1920x1080 by default.
- HDMI rotation is separate from the built-in screen: Settings → Orientation → **External Display** (default 0°).
- The boot logo is pre-rotated for the DPI panel, so on HDMI it may show sideways during boot. Vernis itself displays normally.
- Vernis only maps touch for the Waveshare panel's Goodix controller. Other touchscreens are not configured by Vernis.

### Changing rotation

Settings → **Orientation** → **Internal Display** (Waveshare) or **External Display** (HDMI), then rotate left or right. The change applies right away and is saved in `/opt/vernis/rotation-config.json`, for example:

```json
{"rotation": 90, "rotation_external": 0}
```

### Fixing touch alignment

Changing the rotation in Settings also remaps touch, and the mapping is rewritten each time the kiosk starts. If touch still lands in the wrong place, **reboot**, or re-apply without rebooting. Run this over SSH as your normal user (it may restart the kiosk browser):

```bash
WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/$(id -u) /opt/vernis/scripts/display-output.sh apply
```

Check the result:

```bash
cat ~/.config/labwc/rc.xml
# expect: <touch deviceName="...Goodix Capacitive TouchScreen" mapToOutput="DPI-1" ... />
# plus a <calibrationMatrix> line when the rotation is 90, 180 or 270
```

No touch at all:

```bash
grep -i goodix /proc/bus/input/devices          # the touch controller should be listed
grep waveshare-touch-4dpi /boot/firmware/config.txt
```

`scripts/touch-rotate.sh` only works in an old X11 session; on the Wayland desktop it just points you to the command above.

## Importing your NFTs

Open the web UI and go to **Library → Add Collection → Import from Wallet**. Imported wallets appear in Settings → Wallets, where you can turn auto-sync on or off.

- **Ethereum-family wallets need a free OpenSea API key.** Vernis no longer ships a built-in key. Get one at <https://opensea.io/settings/developer>. Enter it when the import asks for it, or in the **OpenSea API Key** section of the Wallet tool. The key is stored only on the frame.
- **Tezos wallets** (`tz…` addresses, read from objkt) don't need a key.
- **Select every chain your art is on.** Supported: Ethereum, Base, Zora, Optimism, Polygon, Arbitrum and Shape. A chain you don't tick is not searched.
- **Custodial holdings don't show up.** NFTs held by a platform rather than in your own wallet, such as Nifty Gateway editions in Nifty's wallet, won't appear in a wallet scan. Add those with a CSV instead (Add Collection page; it has a template download).

Art is downloaded through the frame's own IPFS node (next section).

## IPFS node

Vernis downloads art through the IPFS node running on the Pi, which the installer sets up as the `ipfs` systemd service. It runs as your user with its repo in `~/.ipfs` and a local gateway on `127.0.0.1:8080`.

The public `ipfs.io` and `dweb.link` gateways stopped serving content in 2026. If the node isn't running, downloads fall back to a couple of slower public gateways and may fail.

Check and fix:

- **Settings → IPFS Pinning** shows *Node Online* or *Node Offline*. When it's offline there is a **Restart Node** button.
- When a download runs without the node, the setup wizard and the Library warn you and offer to restart it.
- Over SSH:
  ```bash
  sudo systemctl status ipfs
  sudo systemctl restart ipfs
  journalctl -u ipfs -n 50 --no-pager
  ```

The service is capped at 512 MB of RAM and garbage-collects old blocks. The store is limited to 50 GB (`Datastore.StorageMax`).

## Updating

Settings → System → **Check for Updates**, then **Install Updates & Reboot**. This installs the latest release from `AfroV/vernis` on GitHub. You don't need your clone after the install, and you don't need to re-run the installer.

The previous version is backed up first (`/opt/vernis/backups/`, last 3 kept). To go back:

```bash
sudo bash /opt/vernis/scripts/rollback-update.sh
```

## Troubleshooting

### The installer stopped with an error
Read the last lines. `Unable to locate package log2ram` means the card has Bookworm: re-flash with the current Trixie-based Raspberry Pi OS. For network errors, run `bash install.sh` again.

### Screen stays black, or backlight on but no image
- Check that the four overlay lines above are in `/boot/firmware/config.txt`, that `dtoverlay=waveshare-4dpi` and `dtoverlay=vc4-fkms-v3d` are commented out, then reboot. Re-running `sudo bash /opt/vernis/scripts/setup-waveshare-4dpi.sh` fixes an older config.
- No backlight at all usually means a connection or power problem. Check that the screen sits fully on the GPIO header.

### Dim screen, stripes, green tint or scan lines
These are known DPI problems with known causes: `dpi-backlight.service` enabled, a fan or other overlay on GPIO 0-25, `over_voltage` below 4, or overclocking. See [DPI-DISPLAY-TROUBLESHOOTING.md](DPI-DISPLAY-TROUBLESHOOTING.md).

### Touch not aligned with the screen
See [Fixing touch alignment](#fixing-touch-alignment).

### Login screen or desktop instead of Vernis
The kiosk starts from the desktop session, so the Pi must log in to the desktop automatically. The installer turns this on; if it didn't stick: `sudo raspi-config` → System Options → Boot / Auto Login → **Desktop Autologin**.

If the desktop shows but the gallery doesn't start, check the autostart file:

```bash
cat ~/.config/labwc/autostart
```

It should end with `/opt/vernis/scripts/kiosk-launcher.sh &`. If it's missing, re-run `bash install.sh` from your clone, or recreate it:

```bash
mkdir -p ~/.config/labwc
cat > ~/.config/labwc/autostart << 'EOF'
pkill -f lwrespawn 2>/dev/null
pkill -f wf-panel-pi 2>/dev/null
pkill -f pcmanfm 2>/dev/null
(sleep 1 && wtype -M alt -M logo -k h -m logo -m alt) &
/opt/vernis/scripts/kiosk-launcher.sh &
EOF
chmod +x ~/.config/labwc/autostart
sudo reboot
```

### Web UI shows nothing, or the API is not responding
```bash
sudo systemctl status vernis-api
sudo journalctl -u vernis-api -f
sudo systemctl status caddy
sudo journalctl -u caddy -f
ls /var/www/vernis/index.html /opt/vernis/app.py   # both must exist
```
If the files are missing, the installer was run without its app files, for example as `scripts/install-vernis.sh` straight from a clone. Run `bash install.sh` from the repository root.

### Art not downloading
Check the [IPFS node](#ipfs-node) and, for wallet imports, the [OpenSea API key](#importing-your-nfts).

### SSH says "Connection refused" but the web UI still works
`fail2ban` has temporarily banned your computer after several failed logins. Wait about 10 minutes and log in with the correct password.

### Low memory (Pi with less than 2 GB RAM)
```bash
sudo bash /opt/vernis/scripts/setup-swap.sh
```

## Manual / advanced

- The real installer is `scripts/install-vernis.sh`. It deploys from `web/`, `backend/` and `scripts/` folders found in its parent folder, in its own folder, or in `/tmp/vernis-deploy/`. `install.sh` builds `/tmp/vernis-deploy/` from a git clone.
- Single steps can be re-run on an installed frame:
  `sudo bash /opt/vernis/scripts/setup-waveshare-4dpi.sh`,
  `bash /opt/vernis/scripts/setup-bluetooth-pan.sh` (as your user),
  `sudo bash /opt/vernis/scripts/setup-tmpfs.sh auto`,
  `sudo bash /opt/vernis/scripts/setup-auto-updates.sh enable`.
- The old Raspberry Pi OS Lite installer and the manual copy-files-by-hand procedure are retired. They didn't set up the screen, touch, rotation or the IPFS service.

## Where things live

```
/var/www/vernis/               Web UI (served by Caddy)
/opt/vernis/                   Backend (app.py) and settings (*.json)
/opt/vernis/scripts/           Kiosk, display, update and helper scripts
/opt/vernis/nfts/              Downloaded art
~/.ipfs/                       IPFS node repository
~/.config/labwc/autostart      Starts the kiosk
~/.config/labwc/rc.xml         Touch mapping (written by display-output.sh)
/etc/caddy/Caddyfile           Web server config
/etc/systemd/system/           vernis-api, ipfs, vernis-watchdog, vernis-touch-wake, ... units
/boot/firmware/config.txt      Display overlays
```
