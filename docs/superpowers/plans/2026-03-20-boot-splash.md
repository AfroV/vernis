# Boot Splash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the 30-60 second blank screen between Plymouth exit and Chromium render by showing the Vernis splash as a Wayland wallpaper during boot.

**Architecture:** `swaybg` displays the Vernis splash PNG as a layer-shell background wallpaper immediately when kiosk-launcher.sh starts. It stays visible during server wait, display setup, and Chromium initialization. A delayed kill removes swaybg after Chromium has rendered.

**Tech Stack:** swaybg (wlroots wallpaper tool), bash, systemd

**Spec:** `docs/superpowers/specs/2026-03-20-onboarding-fixes-design.md`

**Note — Fix 1 (Routing):** The spec documents that existing routing guards already prevent redirect loops on the kiosk. No code changes needed — see spec for analysis.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `scripts/kiosk-launcher.sh` | Modify (after line 17, lines 157-158) | Add swaybg launch at top, delayed kill before exec |
| `scripts/install-vernis.sh` | Modify (line 28, after line 426) | Add swaybg package, save unrotated splash PNG |

---

### Task 1: Add swaybg to install dependencies

**Files:**
- Modify: `scripts/install-vernis.sh` (apt install line, currently line 28)

- [ ] **Step 1: Add swaybg to the apt install list**

In `scripts/install-vernis.sh`, add `swaybg` to the end of the existing apt install line:

```bash
# Before:
sudo apt install -y python3-pip python3-flask xinput xdotool unclutter \
    chromium curl libssl-dev gcc wayvnc ufw fail2ban wtype mpv wlrctl log2ram \
    librsvg2-bin imagemagick

# After:
sudo apt install -y python3-pip python3-flask xinput xdotool unclutter \
    chromium curl libssl-dev gcc wayvnc ufw fail2ban wtype mpv wlrctl log2ram \
    librsvg2-bin imagemagick swaybg
```

- [ ] **Step 2: Commit**

```bash
git add scripts/install-vernis.sh
git commit -m "feat: add swaybg dependency for boot splash wallpaper"
```

---

### Task 2: Save unrotated splash PNG during install

**Files:**
- Modify: `scripts/install-vernis.sh` (Plymouth splash setup section)

- [ ] **Step 1: Add unrotated PNG copy after Plymouth splash.png is copied**

In `scripts/install-vernis.sh`, the Plymouth splash setup flow is:
- Line 421: `rsvg-convert` creates `/tmp/vernis-splash-raw.png` (unrotated)
- Line 423: `convert` rotates it to `/tmp/vernis-splash.png` (270° for direct framebuffer)
- Line 425: `sudo mkdir -p` creates Plymouth theme directory
- Line 426: `sudo cp /tmp/vernis-splash.png ...` copies rotated splash

Add one line **immediately after line 426** (after `sudo cp /tmp/vernis-splash.png`):

```bash
    sudo cp /tmp/vernis-splash-raw.png /usr/share/plymouth/themes/vernis/splash-upright.png
```

The full section after the edit (lines 425-427):
```bash
    sudo mkdir -p /usr/share/plymouth/themes/vernis
    sudo cp /tmp/vernis-splash.png /usr/share/plymouth/themes/vernis/splash.png
    sudo cp /tmp/vernis-splash-raw.png /usr/share/plymouth/themes/vernis/splash-upright.png
```

Note: The existing `rm -f /tmp/vernis-splash-raw.png` on line 449 will clean up the temp file after.

- [ ] **Step 2: Commit**

```bash
git add scripts/install-vernis.sh
git commit -m "feat: save unrotated splash PNG for swaybg boot wallpaper"
```

---

### Task 3: Add swaybg splash to kiosk-launcher.sh

**Files:**
- Modify: `scripts/kiosk-launcher.sh` (after line 17, before line 19)
- Modify: `scripts/kiosk-launcher.sh` (lines 157-158, before exec chromium)

- [ ] **Step 1: Add swaybg launch at the top of the script**

After line 17 (`pkill -f lxsession-xdg 2>/dev/null`) and before line 19 (`# Wait for server to be ready`), add the swaybg splash block:

```bash
# Show Vernis splash wallpaper while waiting for server + Chromium to load
# swaybg runs as a Wayland layer-shell background — Chromium renders on top naturally
SWAYBG_PID=""
SPLASH_IMG="/usr/share/plymouth/themes/vernis/splash-upright.png"
if [ -n "$WAYLAND_DISPLAY" ] && [ -f "$SPLASH_IMG" ] && command -v swaybg >/dev/null 2>&1; then
    swaybg -i "$SPLASH_IMG" -m center -c '#0f0d0d' &
    SWAYBG_PID=$!
    echo "[$(date)] Boot splash wallpaper started (PID $SWAYBG_PID)"
fi
```

- [ ] **Step 2: Add delayed swaybg kill before Chromium exec**

Replace lines 157-158:

```bash
# Before (lines 157-158):
echo "[$(date)] Launching Chromium..."
exec chromium $CHROME_FLAGS http://localhost/$START_PAGE
```

With:

```bash
# Kill boot splash wallpaper after Chromium has time to render its first paint.
# The backgrounded subshell survives exec (it's a separate process).
if [ -n "$SWAYBG_PID" ]; then
    (sleep 5 && kill $SWAYBG_PID 2>/dev/null) &
    echo "[$(date)] Splash wallpaper will be cleaned up in 5s"
fi

echo "[$(date)] Launching Chromium..."
exec chromium $CHROME_FLAGS http://localhost/$START_PAGE
```

- [ ] **Step 3: Commit**

```bash
git add scripts/kiosk-launcher.sh
git commit -m "feat: show Vernis splash wallpaper during boot (eliminates blank screen)"
```

---

### Task 4: Deploy and test on Pi

- [ ] **Step 1: Install swaybg on afrol**

```bash
sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrol@10.0.0.28 "echo '<device-password>' | sudo -S apt-get install -y swaybg"
```

- [ ] **Step 2: Create unrotated splash PNG on afrol**

The installed `splash.png` is rotated 270° CCW. Rotating it 90° CW gives the upright version. Use ImageMagick `convert` (already installed):

```bash
sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrol@10.0.0.28 "echo '<device-password>' | sudo -S convert /usr/share/plymouth/themes/vernis/splash.png -rotate 90 /usr/share/plymouth/themes/vernis/splash-upright.png && echo 'Created splash-upright.png'"
```

If `convert` is not available, use the SVG source directly with `rsvg-convert`:

```bash
sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrol@10.0.0.28 "rsvg-convert -w 720 -h 720 /var/www/vernis/assets/vernis-nft.svg -o /tmp/splash-upright.png && echo '<device-password>' | sudo -S mv /tmp/splash-upright.png /usr/share/plymouth/themes/vernis/splash-upright.png && echo 'Created splash-upright.png'"
```

- [ ] **Step 3: Deploy updated kiosk-launcher.sh**

```bash
cat scripts/kiosk-launcher.sh | sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrol@10.0.0.28 "cat > /tmp/kiosk-launcher.sh && echo '<device-password>' | sudo -S mv /tmp/kiosk-launcher.sh /opt/vernis/scripts/kiosk-launcher.sh && echo '<device-password>' | sudo -S chmod +x /opt/vernis/scripts/kiosk-launcher.sh"
```

- [ ] **Step 4: Reboot and verify**

```bash
sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrol@10.0.0.28 "echo '<device-password>' | sudo -S reboot"
```

After reboot (wait ~90s), verify:

```bash
# Check swaybg ran and was killed
sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrol@10.0.0.28 "journalctl --user -u vernis-kiosk --no-pager | grep -i splash && echo '---' && pgrep swaybg || echo 'swaybg not running (good — cleaned up)'"
```

- [ ] **Step 5: Visual verification**

Watch the Pi's screen during reboot. Expected:
1. Plymouth splash (Vernis gold logo) appears during kernel boot
2. Plymouth exits → swaybg takes over seamlessly (same image, may have brief transition)
3. Splash stays visible during entire server wait + display setup
4. Chromium renders → splash disappears underneath
5. Gallery or index.html is visible — no blank screen at any point

If there is a brief black flash between Plymouth exit and swaybg start, that's acceptable (labwc needs a moment to initialize before swaybg can connect). It should be <1 second.

- [ ] **Step 6: Verify graceful degradation**

If swaybg is missing or splash image doesn't exist, boot should work normally (just with the blank gap, no crash). The `if` guards in kiosk-launcher.sh handle this — verify by checking logs show no errors related to swaybg when conditions aren't met.
