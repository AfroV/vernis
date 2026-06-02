#!/bin/bash
##############################################
# Vernis HDMI Hotplug Handler
# Triggered by udev on HDMI connect/disconnect
# udev rule: /etc/udev/rules.d/99-vernis-hdmi.rules
##############################################

LOG="/tmp/vernis-hdmi.log"

# Skip if a manual rotation is in progress (API sets this lock).
# wlr-randr transforms trigger udev drm change events — without this check,
# the hotplug script would re-apply the OLD rotation and undo the user's change.
ROTATION_LOCK="/tmp/vernis-rotation-lock"
if [ -f "$ROTATION_LOCK" ]; then
    RLOCK_TIME=$(cat "$ROTATION_LOCK" 2>/dev/null || echo 0)
    NOW=$(date +%s)
    AGE=$(( NOW - RLOCK_TIME ))
    if [ "$AGE" -lt 15 ]; then
        echo "[hdmi-hotplug] $(date '+%Y-%m-%d %H:%M:%S') Skipped — manual rotation in progress (${AGE}s ago)" >> "$LOG"
        exit 0
    fi
    rm -f "$ROTATION_LOCK"
fi

# Debounce: udev fires multiple change events per HDMI plug/unplug.
# Also, wlr-randr calls trigger DRM change events — without sufficient debounce,
# the hotplug handler can loop (15s HDMI wait > old 10s debounce window).
# Use 30s window to cover: HDMI wait (15s) + display-output.sh execution + margin.
LOCK_FILE="/tmp/vernis-hdmi-hotplug.lock"
if [ -f "$LOCK_FILE" ]; then
    LOCK_TIME=$(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)
    NOW=$(date +%s)
    AGE=$(( NOW - LOCK_TIME ))
    if [ "$AGE" -lt 30 ]; then
        echo "[hdmi-hotplug] $(date '+%Y-%m-%d %H:%M:%S') Debounced (${AGE}s since last)" >> "$LOG"
        exit 0
    fi
fi
touch "$LOCK_FILE"

# Find the Vernis user (first non-root user in /home)
VERNIS_USER=$(ls /home/ 2>/dev/null | head -1)
if [ -z "$VERNIS_USER" ]; then
    echo "[hdmi-hotplug] No user found in /home/" >> "$LOG"
    exit 1
fi

VERNIS_UID=$(id -u "$VERNIS_USER" 2>/dev/null)
if [ -z "$VERNIS_UID" ]; then
    echo "[hdmi-hotplug] Cannot find UID for $VERNIS_USER" >> "$LOG"
    exit 1
fi

# Wait for compositor to detect the new HDMI output (poll up to 15s)
WAITED=0
MAX_WAIT=15
HDMI_FOUND=false
while [ $WAITED -lt $MAX_WAIT ]; do
    sleep 2
    WAITED=$((WAITED + 2))
    if sudo -u "$VERNIS_USER" \
        WAYLAND_DISPLAY=wayland-0 \
        XDG_RUNTIME_DIR="/run/user/$VERNIS_UID" \
        wlr-randr 2>/dev/null | grep -q "^HDMI"; then
        HDMI_FOUND=true
        echo "[hdmi-hotplug] $(date '+%Y-%m-%d %H:%M:%S') HDMI detected after ${WAITED}s" >> "$LOG"
        break
    fi
done

if [ "$HDMI_FOUND" = false ]; then
    echo "[hdmi-hotplug] $(date '+%Y-%m-%d %H:%M:%S') HDMI not detected after ${MAX_WAIT}s (unplug event?), applying anyway" >> "$LOG"
fi

echo "[hdmi-hotplug] $(date '+%Y-%m-%d %H:%M:%S') Applying display config for $VERNIS_USER" >> "$LOG"

# Run display-output.sh as the Vernis user with Wayland environment
sudo -u "$VERNIS_USER" \
    WAYLAND_DISPLAY=wayland-0 \
    XDG_RUNTIME_DIR="/run/user/$VERNIS_UID" \
    /opt/vernis/scripts/display-output.sh apply >> "$LOG" 2>&1

# Refresh lock timestamp after execution so debounce window starts from completion
touch "$LOCK_FILE"
