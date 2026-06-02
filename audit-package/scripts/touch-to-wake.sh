#!/bin/bash
# Touch-to-Wake daemon for Vernis
# Monitors touchscreen hardware events and wakes screen when touched.
# Runs as a systemd service, independent of Chromium.
#
# Screen off only toggles backlight (GPIO18 dh/dl). DPI output stays enabled
# so the touch controller remains powered via the ribbon cable.

ACTIVITY_FILE="/opt/vernis/last-activity"

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
            touch "$ACTIVITY_FILE" 2>/dev/null
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
