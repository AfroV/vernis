#!/bin/bash
##############################################
# Vernis Display Auto-Switch
# Uses HDMI if connected, otherwise DPI
##############################################

export DISPLAY=:0

# Check which displays are connected
HDMI_CONNECTED=$(xrandr | grep "HDMI-2 connected" | grep -v "disconnected")
DPI_CONNECTED=$(xrandr | grep "DPI-1 connected" | grep -v "disconnected")

echo "[$(date)] Display check:"
echo "  HDMI-2: $([ -n "$HDMI_CONNECTED" ] && echo 'connected' || echo 'disconnected')"
echo "  DPI-1: $([ -n "$DPI_CONNECTED" ] && echo 'connected' || echo 'disconnected')"

if [ -n "$HDMI_CONNECTED" ]; then
    # HDMI is connected - use it as primary, disable DPI
    echo "[$(date)] Using HDMI display"
    xrandr --output DPI-1 --off --output HDMI-2 --auto --primary

    # Get HDMI resolution for Chromium
    SCREEN_RES=$(xrandr | grep "HDMI-2" -A1 | grep -E '\*' | awk '{print $1}')

elif [ -n "$DPI_CONNECTED" ]; then
    # Only DPI connected - use it
    echo "[$(date)] Using DPI display (built-in)"
    xrandr --output HDMI-2 --off --output DPI-1 --auto --primary

    # Ensure backlight is on (active LOW)
    pinctrl set 18 op dl 2>/dev/null || true

    # DPI resolution
    SCREEN_RES="720x720"

else
    echo "[$(date)] No display detected!"
    SCREEN_RES="1920x1080"
fi

# Export for kiosk launcher
echo "$SCREEN_RES"
