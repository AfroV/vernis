#!/bin/bash
# Touch-to-Wake daemon for Vernis
# Monitors touchscreen hardware events and wakes screen when touched.
# Runs as a systemd service, independent of Chromium.
#
# Screen off only toggles backlight (GPIO18 dh/dl). DPI output stays enabled
# so the touch controller remains powered via the ribbon cable.

ACTIVITY_FILE="/opt/vernis/last-activity"
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB=/usr/local/lib/vernis

# Finish the root setup of a newly installed version (sudo rules, helpers,
# root services moved to root-owned scripts). An update is run by the updater
# already on the frame, and updaters before 3.6 don't do this; this root boot
# service is the first code of the new version to run as root. Cheap after
# the first time (version marker). In the foreground: on frames without a
# touchscreen this script exits right below, and systemd would kill a
# background job with it.
# Runs the copy next to this script: the service normally runs the root-owned
# copy in $LIB, never /opt/vernis/scripts, which the app account can edit
# (see vernis-post-update.sh for the first boot after an older updater).
if [ "$EUID" -eq 0 ] && [ -f "$SELF_DIR/vernis-post-update.sh" ]; then
    timeout 300 bash "$SELF_DIR/vernis-post-update.sh" --if-needed || true
    # That just moved this service to the root-owned copy: run it from there
    if [ "$SELF_DIR" != "$LIB" ] && [ -x "$LIB/touch-to-wake.sh" ] && \
       systemctl show -p ExecStart --value vernis-touch-wake.service 2>/dev/null | grep -q "$LIB/touch-to-wake.sh"; then
        echo "Restarting from the root-owned copy ($LIB)"
        systemctl --no-block restart vernis-touch-wake.service
        exit 0
    fi
fi

# The activity file is in the app account's folder: write it as that account
# (as root, a symlink planted there would make this create files anywhere)
APP_USER=$(stat -c %U /opt/vernis 2>/dev/null)
mark_activity() {
    if [ "$EUID" -eq 0 ] && [ -n "$APP_USER" ] && [ "$APP_USER" != "root" ]; then
        runuser -u "$APP_USER" -- touch "$ACTIVITY_FILE" 2>/dev/null
    else
        touch "$ACTIVITY_FILE" 2>/dev/null
    fi
}

# Find the Goodix touchscreen event device dynamically
find_touch_device() {
    for f in /sys/class/input/event*/device/name; do
        if grep -qi "goodix\|touch" "$f" 2>/dev/null; then
            echo "$f" | sed 's|.*/\(event[0-9]*\)/.*|/dev/input/\1|'
            return
        fi
    done
}

TOUCH_DEV=$(find_touch_device)
if [ -z "$TOUCH_DEV" ]; then
    echo "No touchscreen input device found, exiting"
    exit 1
fi
echo "Touch-to-wake monitoring: $TOUCH_DEV"

while true; do
    # Block until a touch event arrives (timeout 10s to allow device re-detection)
    if timeout 10 dd if="$TOUCH_DEV" of=/dev/null bs=24 count=1 2>/dev/null; then
        # Check if screen is off (GPIO18 high = backlight off)
        # Pi 5 shows "dh" (drive-high), Pi 4 shows "| hi" — match both
        if pinctrl get 18 2>/dev/null | grep -qE "dh|\| hi"; then
            mark_activity
            pinctrl set 18 op dl
            echo "$(date): Touch wake — screen ON"
            # Notify app.py to clear manual-off state
            curl -s -X POST http://localhost:5000/api/screen/on >/dev/null 2>&1 &
        fi

        # Drain queued events and pause briefly to avoid rapid re-triggers
        dd if="$TOUCH_DEV" of=/dev/null bs=24 count=100 iflag=nonblock 2>/dev/null
        sleep 0.5
    fi
done
