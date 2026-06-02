#!/bin/bash
##############################################
# Vernis Touch Rotation
# Syncs touch input with display rotation
##############################################

sleep 2
export DISPLAY=:0

# Find XAUTHORITY
for AUTH in /var/run/lightdm/root/:0 /home/*/.Xauthority /root/.Xauthority; do
    if [ -f "$AUTH" ]; then
        export XAUTHORITY="$AUTH"
        break
    fi
done

# ==========================================
# 1. Apply Persistent Rotation (if set)
# ==========================================
CONFIG_FILE="/opt/vernis/rotation-config.json"
if [ -f "$CONFIG_FILE" ]; then
    # Extract rotation (0, 90, 180, 270)
    # Use python for reliable JSON parsing since jq might not be present
    SAVED_ROTATION=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('rotation', ''))" 2>/dev/null)
    
    if [ -n "$SAVED_ROTATION" ]; then
        echo "[$(date)] Applying saved rotation: $SAVED_ROTATION"
        
        case "$SAVED_ROTATION" in
            "90")  ARG="right" ;;
            "180") ARG="inverted" ;;
            "270") ARG="left" ;;
            *)     ARG="normal" ;;
        esac
        
        # Get output name
        OUTPUT=$(xrandr --query | grep " connected" | head -1 | awk '{print $1}')
        if [ -n "$OUTPUT" ]; then
            xrandr --output "$OUTPUT" --rotate "$ARG"
            sleep 1 # Allow X11 to settle
        fi
    fi
fi

# ==========================================
# 2. Sync Touch Matrix
# ==========================================

# Get display rotation from xrandr
ROTATION=$(xrandr --query 2>/dev/null | grep -E 'connected primary' | grep -oE 'left|right|inverted|normal' | head -1)

# Default to normal if not detected
if [ -z "$ROTATION" ]; then
    ROTATION="normal"
fi

# Set transformation matrix based on rotation
case "$ROTATION" in
    normal)
        MATRIX="1 0 0 0 1 0 0 0 1"
        ;;
    left)
        MATRIX="0 -1 1 1 0 0 0 0 1"
        ;;
    right)
        MATRIX="0 1 0 -1 0 1 0 0 1"
        ;;
    inverted)
        MATRIX="-1 0 1 0 -1 1 0 0 1"
        ;;
    *)
        MATRIX="1 0 0 0 1 0 0 0 1"
        ;;
esac

echo "[$(date)] Display rotation: $ROTATION"
echo "[$(date)] Touch matrix: $MATRIX"

# Apply to touch devices by ID (most reliable)
for ID in 6 7 8 9 10; do
    xinput set-prop $ID "Coordinate Transformation Matrix" $MATRIX 2>/dev/null && \
        echo "[$(date)] Applied to device ID: $ID"
done

# Also try known device names
for DEVICE in "Goodix Capacitive TouchScreen" "22-005d Goodix Capacitive TouchScreen" \
              "FT5406 memory based driver" "SYNAPTICS Synaptics Touch Digitizer V04" \
              "eGalax Inc. eGalaxTouch"; do
    xinput set-prop "$DEVICE" "Coordinate Transformation Matrix" $MATRIX 2>/dev/null && \
        echo "[$(date)] Applied to: $DEVICE"
done

# Try any device with "touch" in the name
xinput list --name-only 2>/dev/null | grep -iE "touch|digitizer|goodix" | while read DEVICE; do
    xinput set-prop "$DEVICE" "Coordinate Transformation Matrix" $MATRIX 2>/dev/null && \
        echo "[$(date)] Applied to: $DEVICE"
done

echo "[$(date)] Touch rotation complete"
