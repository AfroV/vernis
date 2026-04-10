#!/bin/bash
##############################################
# Vernis Kiosk Launcher
# Waits for server, then launches Chromium
# Compatible with both X11 and Wayland (labwc)
##############################################

# Kill any existing Chromium, panel, desktop icons, and wizards (for clean kiosk mode)
# Prevents duplicate browser instances if autostart runs more than once
pkill -f 'chromium.*--kiosk' 2>/dev/null
sleep 0.5
pkill -f wf-panel-pi 2>/dev/null
pkill -f pcmanfm 2>/dev/null
pkill -f lwrespawn 2>/dev/null
pkill -f piwiz 2>/dev/null
pkill -f kanshi 2>/dev/null
pkill -f lxsession-xdg 2>/dev/null

# Show Vernis splash wallpaper while waiting for server + Chromium to load
# swaybg runs as a Wayland layer-shell background — Chromium renders on top naturally
# Skip splash when HDMI is connected — the image is pre-rotated for DPI's
# physical orientation and would appear sideways on an HDMI TV.
SWAYBG_PID=""
SPLASH_IMG="/usr/share/plymouth/themes/vernis/splash.png"
HDMI_AT_BOOT=$(wlr-randr 2>/dev/null | grep -c "^HDMI")
if [ -n "$WAYLAND_DISPLAY" ] && [ -f "$SPLASH_IMG" ] && [ "$HDMI_AT_BOOT" -eq 0 ] && command -v swaybg >/dev/null 2>&1; then
    swaybg -i "$SPLASH_IMG" -m fill -c '#0f0d0d' &
    SWAYBG_PID=$!
    echo "[$(date)] Boot splash wallpaper started (PID $SWAYBG_PID)"
elif [ "$HDMI_AT_BOOT" -gt 0 ]; then
    echo "[$(date)] HDMI detected at boot, skipping DPI splash"
fi

# Wait for server to be ready (max 60 seconds)
echo "[$(date)] Waiting for Vernis server..."
MAX_WAIT=60
WAITED=0

while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -sk -o /dev/null -w "%{http_code}" https://localhost/favicon.svg 2>/dev/null | grep -q "200"; then
        echo "[$(date)] Server ready after ${WAITED}s"
        break
    fi
    sleep 1
    WAITED=$((WAITED + 1))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo "[$(date)] Server not ready after ${MAX_WAIT}s, launching anyway"
fi

# Kill boot splash before display rotation is applied — rotation would
# double-rotate the pre-rotated splash image.
if [ -n "$SWAYBG_PID" ]; then
    kill $SWAYBG_PID 2>/dev/null
    wait $SWAYBG_PID 2>/dev/null
    echo "[$(date)] Splash wallpaper removed before display setup"
    SWAYBG_PID=""
fi

# Apply saved display output mode (Internal/External/Mirror)
DISPLAY_OUTPUT_SCRIPT="/opt/vernis/scripts/display-output.sh"
if [ -f "$DISPLAY_OUTPUT_SCRIPT" ]; then
    echo "[$(date)] Applying saved display output mode..."
    bash "$DISPLAY_OUTPUT_SCRIPT" apply 2>/dev/null | while read -r line; do echo "[$(date)] $line"; done
    # Give displays time to settle after switching
    sleep 2
fi

# DPI signal refresh: the vc4 DRM driver can leave the DPI display signal
# corrupted during boot (grey screen, color lines). Toggle the output off/on
# to force a clean re-initialization. Only needed when DPI is the active display.
# Skip in external mode — display-output.sh already disabled DPI for HDMI.
DPI_OUTPUT=$(wlr-randr 2>/dev/null | grep -oP '^DPI[^\s]+' | head -1)
DPI_SHOULD_BE_ACTIVE=true
DISPLAY_MODE=$(python3 -c "import json; print(json.load(open('/opt/vernis/display-output-config.json')).get('mode', 'auto'))" 2>/dev/null || echo "auto")
if [ "$DISPLAY_MODE" = "external" ]; then
    DPI_SHOULD_BE_ACTIVE=false
elif [ "$DISPLAY_MODE" = "auto" ] && [ "$HDMI_AT_BOOT" -gt 0 ]; then
    DPI_SHOULD_BE_ACTIVE=false
fi
if [ -n "$DPI_OUTPUT" ] && [ "$DPI_SHOULD_BE_ACTIVE" = true ]; then
    # Read rotation from saved config (not wlr-randr — may be stale during boot race)
    DPI_ROT=$(python3 -c "import json; print(json.load(open('/opt/vernis/rotation-config.json')).get('rotation', 0))" 2>/dev/null || echo "0")
    case "$DPI_ROT" in
        90)  DPI_TRANSFORM="90" ;;
        180) DPI_TRANSFORM="180" ;;
        270) DPI_TRANSFORM="270" ;;
        *)   DPI_TRANSFORM="normal" ;;
    esac
    echo "[$(date)] Refreshing DPI signal ($DPI_OUTPUT, transform=$DPI_TRANSFORM)..."
    # Touch hotplug debounce lock so the off/on toggle doesn't re-trigger udev handler
    touch /tmp/vernis-hdmi-hotplug.lock 2>/dev/null || true
    wlr-randr --output "$DPI_OUTPUT" --off 2>/dev/null
    sleep 1
    wlr-randr --output "$DPI_OUTPUT" --on --transform "$DPI_TRANSFORM" 2>/dev/null
    pinctrl set 18 op dl 2>/dev/null || true  # Ensure backlight stays on
    sleep 1
    # Re-apply touch calibration — the off/on toggle invalidates labwc's mapping
    pkill -SIGHUP labwc 2>/dev/null || true
    touch /tmp/vernis-hdmi-hotplug.lock 2>/dev/null || true
    echo "[$(date)] DPI signal refreshed"
fi

# Detect display environment and resolution
if [ -n "$WAYLAND_DISPLAY" ]; then
    echo "[$(date)] Running on Wayland"

    DISPLAY_COUNT=$(wlr-randr 2>/dev/null | grep -c "^[A-Z]")
    echo "[$(date)] Detected $DISPLAY_COUNT display(s)"

    # Get resolution from the current (active) mode of the enabled display
    SCREEN_RES=$(wlr-randr 2>/dev/null | grep 'current' | grep -oP '\d+x\d+(?= px)' | head -1)
    # If HDMI is active but resolution still shows DPI size, retry — HDMI may be initializing
    if [ "$HDMI_AT_BOOT" -gt 0 ] && { [ -z "$SCREEN_RES" ] || [ "$SCREEN_RES" = "720x720" ]; }; then
        for _try in 1 2 3; do
            sleep 1
            SCREEN_RES=$(wlr-randr 2>/dev/null | grep 'current' | grep -oP '\d+x\d+(?= px)' | head -1)
            if [ -n "$SCREEN_RES" ] && [ "$SCREEN_RES" != "720x720" ]; then
                echo "[$(date)] HDMI resolution detected on retry $_try: $SCREEN_RES"
                break
            fi
        done
    fi
else
    echo "[$(date)] Running on X11"
    export DISPLAY=:0
    # Fallback: detect from xrandr
    SCREEN_RES=$(xrandr 2>/dev/null | grep -E '\*' | head -1 | awk '{print $1}')
fi

# Rotation is handled by display-output.sh (called above) which applies
# the correct per-target rotation (internal vs external). No need to
# re-apply here — doing so would use the wrong rotation value when
# internal and external have different orientations.

# Fallback resolution (4" Waveshare display is 720x720)
if [ -z "$SCREEN_RES" ]; then
    SCREEN_RES="720x720"
fi

SCREEN_W=$(echo "$SCREEN_RES" | cut -d'x' -f1)
SCREEN_H=$(echo "$SCREEN_RES" | cut -d'x' -f2)
echo "[$(date)] Using screen resolution: ${SCREEN_W}x${SCREEN_H}"

# Build Chromium flags
CHROME_FLAGS="--kiosk --start-maximized --start-fullscreen"
CHROME_FLAGS="$CHROME_FLAGS --force-device-scale-factor=1 --window-size=${SCREEN_W},${SCREEN_H} --window-position=0,0"
CHROME_FLAGS="$CHROME_FLAGS --noerrdialogs --disable-infobars --disable-notifications"
CHROME_FLAGS="$CHROME_FLAGS --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --remote-allow-origins=http://localhost,https://localhost,http://localhost:9222,http://127.0.0.1:9222"
CHROME_FLAGS="$CHROME_FLAGS --touch-events=enabled --disable-smooth-scrolling"
CHROME_FLAGS="$CHROME_FLAGS --overscroll-history-navigation=0"

# GPU flags optimized for Pi 5 with DPI display
CHROME_FLAGS="$CHROME_FLAGS --ignore-gpu-blocklist"
CHROME_FLAGS="$CHROME_FLAGS --enable-gpu-rasterization"
CHROME_FLAGS="$CHROME_FLAGS --disable-software-rasterizer"
CHROME_FLAGS="$CHROME_FLAGS --use-gl=angle --use-angle=gles"
CHROME_FLAGS="$CHROME_FLAGS --enable-native-gpu-memory-buffers"
CHROME_FLAGS="$CHROME_FLAGS --num-raster-threads=2"

# Reduce CPU usage
CHROME_FLAGS="$CHROME_FLAGS --disable-background-networking"
CHROME_FLAGS="$CHROME_FLAGS --disable-checker-imaging"

CHROME_FLAGS="$CHROME_FLAGS --disable-session-crashed-bubble --disable-component-update"
CHROME_FLAGS="$CHROME_FLAGS --disable-features=InsufficientResourcesWarning,OverlayScrollbar,HttpsUpgrades"
CHROME_FLAGS="$CHROME_FLAGS --password-store=basic"
CHROME_FLAGS="$CHROME_FLAGS --allow-insecure-localhost"

# Add Wayland-specific flags if running on Wayland
if [ -n "$WAYLAND_DISPLAY" ]; then
    CHROME_FLAGS="$CHROME_FLAGS --ozone-platform=wayland --enable-features=UseOzonePlatform"

    # Hide cursor via labwc HideCursor action (keybind A-W-h in rc.xml)
    # Cursor reappears when mouse moves (desired for external HDMI mode)
    # gallery.html has its own SVG touch cursor for external HDMI mode
    export WLR_NO_HARDWARE_CURSORS=1
    if command -v wtype >/dev/null 2>&1; then
        (sleep 3 && wtype -M alt -M logo -k h -m logo -m alt) &
    fi
else
    # Hide mouse pointer on X11
    if command -v unclutter >/dev/null 2>&1; then
        unclutter -idle 0.1 -root &
    fi
    xsetroot -cursor_name left_ptr 2>/dev/null
fi

# Wait for Flask API to be ready (up to 30 seconds)
echo "[$(date)] Waiting for API..."
for _wait in $(seq 1 30); do
    if curl -s --max-time 2 http://localhost:5000/api/setup/status >/dev/null 2>&1; then
        echo "[$(date)] API ready after ${_wait}s"
        break
    fi
    sleep 1
done

# Check if gallery has art — if so, start in gallery mode
START_PAGE="index.html"
HAS_ART=$(curl -s --max-time 5 http://localhost:5000/api/setup/status 2>/dev/null | grep -o '"has_art": *true')
if [ -n "$HAS_ART" ]; then
    START_PAGE="gallery.html"
    echo "[$(date)] Art found — starting in gallery mode"
else
    echo "[$(date)] No art — starting on home screen"
fi

echo "[$(date)] Launching Chromium..."
exec chromium $CHROME_FLAGS http://localhost/$START_PAGE
