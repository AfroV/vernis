# Onboarding Fixes — Design Spec

## Problem

Two issues in the Vernis first-boot experience:

1. **Routing safety on Pi kiosk**: The UX audit flagged a potential redirect loop (gallery.html → welcome.html → back to index.html). Investigation shows the existing code already prevents this — gallery.html line 76 skips the setup check on localhost, and index.html has no links to welcome.html. No code changes needed, but documented here for clarity.

2. **Blank screen on boot**: Plymouth splash (Vernis logo) disappears when the login session starts, but Chromium takes 30-60 seconds more to appear (server wait + display setup + browser launch). The user sees a blank/black screen during this gap and may think the device is broken.

## Users

- **Self-setup user**: Powers on Pi, connects WiFi from touchscreen (index.html), then adds wallet from phone/PC (welcome.html).
- **Pre-loaded user**: Powers on Pi with art already loaded. Gallery plays immediately. WiFi setup deferred.

## Constraints

- Keep the existing index.html and gallery.html visual design unchanged.
- index.html's WiFi panel already works well enough for kiosk WiFi setup.
- welcome.html wizard (password + wallet import) is PC/phone only — that's intentional.
- All Vernis devices run labwc (Wayland). X11 is not used in the fleet.

---

## Fix 1: Routing — No Changes Needed

### Analysis

The existing guards already handle all kiosk routing correctly:

- **gallery.html line 76**: `if (location.hostname === 'localhost' || ...) return;` — skips the setup check entirely on the Pi. The kiosk never gets redirected to welcome.html.
- **welcome.html lines 12-14**: Redirects localhost to `/` as a safety net. If any future code path sends the kiosk to welcome.html, it bounces to index.html.
- **index.html**: Contains zero references to `welcome.html` (verified by grep). No navigation path to the wizard from the home screen.
- **kiosk-launcher.sh lines 148-155**: Routes to gallery.html (has art) or index.html (no art). Both are safe.

### Flow (already working)

```
Pi kiosk, has art:
  kiosk-launcher.sh → gallery.html → localhost guard skips setup check → gallery plays

Pi kiosk, no art:
  kiosk-launcher.sh → index.html → WiFi panel available

Remote PC/phone:
  → gallery.html → setup not complete? → welcome.html wizard
  → gallery.html → setup complete? → stays on gallery
```

No code changes required.

---

## Fix 2: Boot Loading Screen

### Current behavior

1. Power on → BIOS/firmware (1-2s)
2. Plymouth splash appears (Vernis gold logo, dark background)
3. Kernel finishes → systemd starts login session → **Plymouth exits**
4. labwc compositor starts and takes DRM master → **blank/black screen begins**
5. kiosk-launcher.sh runs → waits for server (0-60s) → **still blank**
6. Display setup (DPI refresh, rotation) → **still blank** (3-5s)
7. Chromium launches and renders → **screen finally shows content**

Total blank gap: **30-60 seconds** between Plymouth exit and Chromium render.

### Target behavior

1. Power on → BIOS/firmware (1-2s)
2. Plymouth splash appears (Vernis gold logo)
3. Plymouth exits when labwc takes DRM master
4. **labwc shows Vernis splash as wallpaper** — seamless visual continuity
5. kiosk-launcher.sh runs, server starts → splash wallpaper still visible
6. Chromium launches and renders → covers the wallpaper
7. **No blank gap** — splash image visible the entire boot

### Technical approach: swaybg wallpaper splash

Plymouth and labwc cannot coexist — when labwc claims DRM master, Plymouth loses framebuffer access and the splash disappears. Instead of fighting Plymouth timing, we use labwc's own rendering to display the splash:

1. **kiosk-launcher.sh** — at the very top (before server wait loop), launch `swaybg` with the Vernis splash image as a fullscreen wallpaper:
   ```bash
   # Show splash wallpaper while waiting for server
   SPLASH_IMG="/usr/share/plymouth/themes/vernis/splash-upright.png"
   if [ -n "$WAYLAND_DISPLAY" ] && [ -f "$SPLASH_IMG" ] && command -v swaybg >/dev/null 2>&1; then
       swaybg -i "$SPLASH_IMG" -m fill -c '#0f0d0d' &
       SWAYBG_PID=$!
   fi
   ```

2. The splash image stays visible during the entire server wait, display setup, and Chromium initialization.

3. **Kill swaybg after Chromium starts** — use a delayed kill so Chromium has time to render its first paint before the wallpaper disappears. The `exec` replaces the shell process, but the backgrounded subshell survives:
   ```bash
   # Kill splash wallpaper after Chromium has time to render
   [ -n "$SWAYBG_PID" ] && (sleep 5 && kill $SWAYBG_PID 2>/dev/null) &

   echo "[$(date)] Launching Chromium..."
   exec chromium $CHROME_FLAGS http://localhost/$START_PAGE
   ```
   This avoids a black flash between swaybg death and Chromium's first paint.

### Why swaybg?

- `swaybg` is a standard wlroots wallpaper tool, compatible with labwc
- It runs as a Wayland layer-shell client (background layer) — doesn't interfere with Chromium
- Chromium renders on top of it naturally (application layer > background layer)
- Lightweight (~2MB RSS), no GPU overhead

### Install dependency

**install-vernis.sh** — add `swaybg` to the package install list:
```bash
sudo apt-get install -y swaybg
```

### Splash image: unrotated version for swaybg

The Plymouth splash is pre-rotated 270° for direct framebuffer display on the DPI screen (install-vernis.sh lines 422-423: `convert ... -rotate 270`). For swaybg, the labwc compositor handles screen rotation via wlr-randr transform, so swaybg needs the **unrotated** image.

**install-vernis.sh** — save the unrotated PNG alongside the rotated one:
```bash
# After the existing rsvg-convert (line 421):
rsvg-convert -w 720 -h 720 /var/www/vernis/assets/vernis-nft.svg -o /tmp/vernis-splash-raw.png

# Existing: rotated for Plymouth direct framebuffer
convert /tmp/vernis-splash-raw.png -rotate 270 /tmp/vernis-splash.png

# New: unrotated for swaybg (compositor handles rotation)
sudo cp /tmp/vernis-splash-raw.png /usr/share/plymouth/themes/vernis/splash-upright.png
```

The swaybg command in kiosk-launcher.sh references `/usr/share/plymouth/themes/vernis/splash-upright.png`.

---

## Files Changed

| File | Change | Risk |
|------|--------|------|
| welcome.html | No change | None |
| gallery.html | No change | None |
| kiosk-launcher.sh | Add swaybg splash at top, delayed kill before exec Chromium | Low |
| install-vernis.sh | Add `swaybg` to apt install, save unrotated splash PNG | Low |

## Testing

1. **Pre-loaded device boot**: Power on Pi with art. Verify: Plymouth → swaybg splash (no blank gap) → gallery appears.
2. **Empty device boot**: Power on Pi without art. Verify: Plymouth → swaybg splash → index.html with WiFi panel.
3. **Remote wizard**: From phone, visit gallery.html. Verify: setup check redirects to welcome.html, wizard works.
4. **Splash timing**: Verify swaybg covers the full gap between Plymouth exit and Chromium render. No flicker.
5. **Splash cleanup**: After Chromium renders, verify swaybg process is gone (not leaking memory).
6. **DPI rotation**: Verify splash image displays correctly on rotated 720x720 screen (compositor transform applied).
7. **swaybg missing**: If swaybg is not installed, verify boot still works (just with blank gap, no crash).

## Out of Scope

- No visual redesign of index.html, gallery.html, or welcome.html
- No changes to the wallet import flow
- No auth on setup endpoints
- No mDNS/device discovery
- No BLE setup integration
