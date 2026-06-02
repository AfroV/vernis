#!/bin/bash
##############################################
# Vernis Display Output Handler
# Manages Auto, Internal, External, Mirror modes
# Called by: udev hotplug, API, kiosk-launcher
# Usage: display-output.sh [apply|status]
##############################################

CONFIG_FILE="/opt/vernis/display-output-config.json"
ROTATION_FILE="/opt/vernis/rotation-config.json"
LOG_TAG="[display-output]"

# Read saved mode (default: auto)
get_mode() {
    if [ -f "$CONFIG_FILE" ]; then
        python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('mode', 'auto'))" 2>/dev/null || echo "auto"
    else
        echo "auto"
    fi
}

# Read saved HDMI resolution (default: auto)
get_resolution() {
    if [ -f "$CONFIG_FILE" ]; then
        python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('resolution', 'auto'))" 2>/dev/null || echo "auto"
    else
        echo "auto"
    fi
}

# Detect Pi model (returns 4 or 5)
get_pi_model() {
    local MODEL_STR
    MODEL_STR=$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0')
    if echo "$MODEL_STR" | grep -q "Pi 5"; then
        echo "5"
    else
        echo "4"
    fi
}

# Read saved rotation for a target display (internal or external)
get_rotation() {
    local TARGET="$1"  # "internal" or "external"
    if [ -f "$ROTATION_FILE" ]; then
        if [ "$TARGET" = "external" ]; then
            python3 -c "import json; d=json.load(open('$ROTATION_FILE')); print(d.get('rotation_external', 0))" 2>/dev/null || echo "0"
        else
            python3 -c "import json; d=json.load(open('$ROTATION_FILE')); print(d.get('rotation', 0))" 2>/dev/null || echo "0"
        fi
    else
        echo "0"
    fi
}

# Get current transform of a display from cached wlr-randr output
get_current_transform() {
    local OUTPUT_NAME="$1"
    if [ -z "$WLR_OUTPUT" ] || [ -z "$OUTPUT_NAME" ]; then
        echo ""
        return
    fi
    local BLOCK
    BLOCK=$(echo "$WLR_OUTPUT" | sed -n "/^${OUTPUT_NAME}/,/^[A-Z]/{ /^[A-Z]/!p; /^${OUTPUT_NAME}/p; }")
    echo "$BLOCK" | grep -oP 'Transform:\s+\K\S+' | head -1
}

# Check if a display is currently enabled
is_output_enabled() {
    local OUTPUT_NAME="$1"
    if [ -z "$WLR_OUTPUT" ] || [ -z "$OUTPUT_NAME" ]; then
        echo "no"
        return
    fi
    local BLOCK
    BLOCK=$(echo "$WLR_OUTPUT" | sed -n "/^${OUTPUT_NAME}/,/^[A-Z]/{ /^[A-Z]/!p; /^${OUTPUT_NAME}/p; }")
    if echo "$BLOCK" | grep -q "Enabled: yes"; then
        echo "yes"
    else
        echo "no"
    fi
}

# Apply rotation to a display using wlr-randr (skips if already correct)
apply_rotation() {
    local OUTPUT_NAME="$1"
    local ROTATION="$2"
    if [ -z "$OUTPUT_NAME" ] || [ -z "$ROTATION" ]; then
        return
    fi
    # Map degrees to wlr-randr transform
    case "$ROTATION" in
        0)   TRANSFORM="normal" ;;
        90)  TRANSFORM="90" ;;
        180) TRANSFORM="180" ;;
        270) TRANSFORM="270" ;;
        *)   TRANSFORM="normal" ;;
    esac
    # Check current transform — skip wlr-randr if already correct
    # (each wlr-randr call triggers a DRM change event which re-triggers udev hotplug)
    local CURRENT
    CURRENT=$(get_current_transform "$OUTPUT_NAME")
    if [ "$CURRENT" = "$TRANSFORM" ]; then
        echo "$LOG_TAG Rotation already ${ROTATION}° ($TRANSFORM) on $OUTPUT_NAME, skipped"
        return
    fi
    wlr-randr --output "$OUTPUT_NAME" --transform "$TRANSFORM" 2>/dev/null
    echo "$LOG_TAG Applied rotation ${ROTATION}° ($TRANSFORM) to $OUTPUT_NAME"
}

# Update labwc touch config: remap digitizer to target display with calibration
# Usage: update_touch_config <output_name> <rotation_correction>
# rotation_correction: degrees to correct for digitizer physical orientation
#   - For internal mode: INT_ROT (match display transform)
#   - For external mode: INT_ROT (digitizer's physical offset from HDMI)
update_touch_config() {
    local TARGET_OUTPUT="$1"
    local CORRECTION="${2:-0}"
    local RCXML="$HOME/.config/labwc/rc.xml"

    if [ ! -f "$RCXML" ]; then
        return
    fi

    # Build calibration matrix element (only needed when correction != 0)
    local CALIB_XML=""
    if [ "$CORRECTION" != "0" ]; then
        case "$CORRECTION" in
            90)  CALIB_XML='<libinput><device category="touch"><calibrationMatrix>0 1 0 -1 0 1 0 0 1</calibrationMatrix></device></libinput>' ;;
            180) CALIB_XML='<libinput><device category="touch"><calibrationMatrix>-1 0 1 0 -1 1 0 0 1</calibrationMatrix></device></libinput>' ;;
            270) CALIB_XML='<libinput><device category="touch"><calibrationMatrix>0 -1 1 1 0 0 0 0 1</calibrationMatrix></device></libinput>' ;;
        esac
    fi

    # Auto-detect touch device name from kernel (i2c address varies per Pi)
    local TOUCH_DEVICE
    TOUCH_DEVICE=$(grep -oP 'N: Name="\K[^"]*Goodix Capacitive TouchScreen[^"]*' /proc/bus/input/devices 2>/dev/null | head -1)
    if [ -z "$TOUCH_DEVICE" ]; then
        # Fallback: read from existing rc.xml
        TOUCH_DEVICE=$(grep -oP 'deviceName="\K[^"]+' "$RCXML" 2>/dev/null | head -1)
    fi
    if [ -z "$TOUCH_DEVICE" ]; then
        TOUCH_DEVICE="Goodix Capacitive TouchScreen"
    fi

    # Write updated rc.xml
    cat > "$RCXML" << RCEOF
<?xml version='1.0' encoding='utf-8'?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
	<touch deviceName="$TOUCH_DEVICE" mapToOutput="$TARGET_OUTPUT" mouseEmulation="yes" />
	$CALIB_XML
	<keyboard>
		<keybind key="A-W-h">
			<action name="HideCursor" />
		</keybind>
	</keyboard>
</openbox_config>
RCEOF

    # Reload labwc config
    pkill -SIGHUP labwc 2>/dev/null || true
    echo "$LOG_TAG Touch remapped to $TARGET_OUTPUT (correction=${CORRECTION}°)"
}

# Detect displays using wlr-randr (Wayland) or xrandr (X11)
detect_displays() {
    HDMI_NAME=""
    HDMI_CONNECTED=false
    HDMI_ENABLED=false
    DPI_NAME=""
    DPI_CONNECTED=false

    if [ -n "$WAYLAND_DISPLAY" ] || [ -S "${XDG_RUNTIME_DIR}/wayland-0" ]; then
        # Ensure WAYLAND_DISPLAY is set for wlr-randr
        export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"

        WLR_OUTPUT=$(wlr-randr 2>/dev/null)
        if [ -z "$WLR_OUTPUT" ]; then
            echo "$LOG_TAG wlr-randr failed" >&2
            return 1
        fi

        # Find HDMI output (HDMI-A-1, HDMI-A-2, HDMI-1, etc.)
        HDMI_NAME=$(echo "$WLR_OUTPUT" | grep -oP '^HDMI[^\s]+' | head -1)
        if [ -n "$HDMI_NAME" ]; then
            # Extract the block for this output (from its header to the next output header or EOF)
            HDMI_BLOCK=$(echo "$WLR_OUTPUT" | sed -n "/^${HDMI_NAME}/,/^[A-Z]/{ /^[A-Z]/!p; /^${HDMI_NAME}/p; }")
            # HDMI is connected if it has modes (EDID readable = cable plugged in)
            HDMI_MODE_COUNT=$(echo "$HDMI_BLOCK" | grep -c "px")
            if [ "$HDMI_MODE_COUNT" -gt 0 ]; then
                HDMI_CONNECTED=true
            fi
            # Check if HDMI output is currently enabled
            if echo "$HDMI_BLOCK" | grep -q "Enabled: yes"; then
                HDMI_ENABLED=true
            fi
        fi

        # Find DPI output
        DPI_NAME=$(echo "$WLR_OUTPUT" | grep -oP '^DPI[^\s]+' | head -1)
        if [ -n "$DPI_NAME" ]; then
            DPI_CONNECTED=true
        fi

        # Get HDMI resolution (preferred mode)
        if [ -n "$HDMI_NAME" ] && [ "$HDMI_CONNECTED" = true ]; then
            HDMI_RES=$(echo "$HDMI_BLOCK" | grep -oP '\d+x\d+(?= px)' | head -1)
        fi
        # Get DPI resolution
        if [ -n "$DPI_NAME" ]; then
            DPI_BLOCK=$(echo "$WLR_OUTPUT" | sed -n "/^${DPI_NAME}/,/^[A-Z]/{ /^[A-Z]/!p; /^${DPI_NAME}/p; }")
            DPI_RES=$(echo "$DPI_BLOCK" | grep -oP '\d+x\d+(?= px)' | head -1)
        fi

        IS_WAYLAND=true
    else
        # X11 fallback
        export DISPLAY="${DISPLAY:-:0}"

        XRANDR_OUTPUT=$(xrandr 2>/dev/null)
        if [ -z "$XRANDR_OUTPUT" ]; then
            echo "$LOG_TAG xrandr failed" >&2
            return 1
        fi

        HDMI_NAME=$(echo "$XRANDR_OUTPUT" | grep -oP 'HDMI[^\s]+(?= connected)' | head -1)
        if [ -n "$HDMI_NAME" ]; then
            HDMI_CONNECTED=true
            HDMI_RES=$(echo "$XRANDR_OUTPUT" | grep -A1 "^$HDMI_NAME" | grep -oP '\d+x\d+' | head -1)
        fi

        DPI_NAME=$(echo "$XRANDR_OUTPUT" | grep -oP 'DPI[^\s]+(?= connected)' | head -1)
        if [ -n "$DPI_NAME" ]; then
            DPI_CONNECTED=true
            DPI_RES=$(echo "$XRANDR_OUTPUT" | grep -A1 "^$DPI_NAME" | grep -oP '\d+x\d+' | head -1)
        fi

        IS_WAYLAND=false
    fi
}

# Apply display configuration based on mode
apply_mode() {
    MODE=$(get_mode)
    detect_displays

    # Auto mode: HDMI connected → use external, otherwise → use internal
    if [ "$MODE" = "auto" ]; then
        if [ "$HDMI_CONNECTED" = true ]; then
            EFFECTIVE_MODE="external"
        else
            EFFECTIVE_MODE="internal"
        fi
        echo "$LOG_TAG $(date '+%Y-%m-%d %H:%M:%S') mode=auto effective=$EFFECTIVE_MODE hdmi=$HDMI_NAME($HDMI_CONNECTED,$HDMI_ENABLED) dpi=$DPI_NAME($DPI_CONNECTED)"
    else
        EFFECTIVE_MODE="$MODE"
        echo "$LOG_TAG $(date '+%Y-%m-%d %H:%M:%S') mode=$MODE hdmi=$HDMI_NAME($HDMI_CONNECTED,$HDMI_ENABLED) dpi=$DPI_NAME($DPI_CONNECTED)"
    fi

    if [ "$IS_WAYLAND" = true ]; then
        apply_wayland "$EFFECTIVE_MODE"
    else
        apply_x11 "$EFFECTIVE_MODE"
    fi
}

apply_wayland() {
    local MODE="$1"
    local NEED_RESTART=false

    # Get per-display rotations
    local INT_ROT=$(get_rotation "internal")
    local EXT_ROT=$(get_rotation "external")

    # Determine HDMI resolution based on user setting and Pi model
    HDMI_MODE_FLAG=""
    local RES_SETTING=$(get_resolution)
    local PI_MODEL=$(get_pi_model)

    if [ -n "$HDMI_NAME" ] && [ "$HDMI_CONNECTED" = true ]; then
        HDMI_BLOCK=$(echo "$WLR_OUTPUT" | sed -n "/^${HDMI_NAME}/,/^[A-Z]/{ /^[A-Z]/!p; /^${HDMI_NAME}/p; }")

        # Map resolution setting to actual mode
        case "$RES_SETTING" in
            1080p)
                HDMI_MODE_FLAG="--mode 1920x1080"
                echo "$LOG_TAG HDMI resolution forced to 1080p"
                ;;
            1440p)
                if echo "$HDMI_BLOCK" | grep -q "2560x1440 px"; then
                    HDMI_MODE_FLAG="--mode 2560x1440"
                    echo "$LOG_TAG HDMI resolution set to 1440p"
                else
                    echo "$LOG_TAG 1440p not available, using display preferred mode"
                fi
                ;;
            4k)
                if echo "$HDMI_BLOCK" | grep -q "3840x2160 px"; then
                    HDMI_MODE_FLAG="--mode 3840x2160"
                    echo "$LOG_TAG HDMI resolution set to 4K"
                else
                    echo "$LOG_TAG 4K not available, using display preferred mode"
                fi
                ;;
            auto|*)
                # Auto: Pi 4 caps to 1080p, Pi 5+ uses display preferred
                if [ "$PI_MODEL" = "4" ]; then
                    if echo "$HDMI_BLOCK" | grep -qP '1920x1080 px, 60\.\d+ Hz'; then
                        HDMI_MODE_FLAG="--mode 1920x1080"
                        echo "$LOG_TAG Auto: Pi 4 detected, capping to 1080p@60Hz"
                    fi
                else
                    echo "$LOG_TAG Auto: Pi $PI_MODEL detected, using display preferred resolution"
                fi
                ;;
        esac
    fi

    case "$MODE" in
        internal)
            # DPI on, HDMI off
            if [ -n "$DPI_NAME" ]; then
                if [ "$(is_output_enabled "$DPI_NAME")" != "yes" ]; then
                    wlr-randr --output "$DPI_NAME" --on --pos 0,0 2>/dev/null
                    echo "$LOG_TAG Enabled $DPI_NAME"
                fi
                apply_rotation "$DPI_NAME" "$INT_ROT"
            fi
            pinctrl set 18 op dl 2>/dev/null || true  # Backlight on
            # Remap touch to DPI with rotation calibration
            if [ -n "$DPI_NAME" ]; then
                update_touch_config "$DPI_NAME" "$INT_ROT"
            fi
            if [ -n "$HDMI_NAME" ] && [ "$HDMI_CONNECTED" = true ]; then
                if [ "$HDMI_ENABLED" = true ]; then
                    wlr-randr --output "$HDMI_NAME" --off 2>/dev/null
                    NEED_RESTART=true
                fi
            fi
            echo "$LOG_TAG Internal mode applied"
            ;;

        external)
            if [ "$HDMI_CONNECTED" = true ] && [ -n "$HDMI_NAME" ]; then
                # HDMI on as primary display — always apply mode flag to enforce resolution
                if [ "$(is_output_enabled "$HDMI_NAME")" != "yes" ]; then
                    wlr-randr --output "$HDMI_NAME" --on --pos 0,0 $HDMI_MODE_FLAG 2>/dev/null
                    echo "$LOG_TAG Enabled $HDMI_NAME"
                    NEED_RESTART=true
                elif [ -n "$HDMI_MODE_FLAG" ]; then
                    wlr-randr --output "$HDMI_NAME" $HDMI_MODE_FLAG 2>/dev/null
                    echo "$LOG_TAG Applied $HDMI_MODE_FLAG to $HDMI_NAME"
                    NEED_RESTART=true
                fi
                apply_rotation "$HDMI_NAME" "$EXT_ROT"
                # Turn DPI off — one screen at a time to avoid GPU flickering
                if [ -n "$DPI_NAME" ] && [ "$(is_output_enabled "$DPI_NAME")" = "yes" ]; then
                    wlr-randr --output "$DPI_NAME" --off 2>/dev/null
                    echo "$LOG_TAG Disabled $DPI_NAME"
                    NEED_RESTART=true
                fi
                pinctrl set 18 op dh 2>/dev/null || true  # Backlight off

                # Remap touch digitizer to HDMI with calibration for DPI physical rotation
                update_touch_config "$HDMI_NAME" "$INT_ROT"

                echo "$LOG_TAG External mode applied (HDMI: $HDMI_NAME ${HDMI_RES:-})"
            else
                # HDMI not connected — fallback to internal
                echo "$LOG_TAG HDMI not connected, falling back to internal"
                if [ -n "$DPI_NAME" ]; then
                    if [ "$(is_output_enabled "$DPI_NAME")" != "yes" ]; then
                        wlr-randr --output "$DPI_NAME" --on --pos 0,0 2>/dev/null
                    fi
                    apply_rotation "$DPI_NAME" "$INT_ROT"
                fi
                pinctrl set 18 op dl 2>/dev/null || true
            fi
            ;;

        mirror)
            if [ "$HDMI_CONNECTED" = true ] && [ -n "$HDMI_NAME" ]; then
                # Both on, same position (0,0) for overlay/mirror effect
                if [ -n "$DPI_NAME" ]; then
                    if [ "$(is_output_enabled "$DPI_NAME")" != "yes" ]; then
                        wlr-randr --output "$DPI_NAME" --on --pos 0,0 2>/dev/null
                        echo "$LOG_TAG Enabled $DPI_NAME"
                        NEED_RESTART=true
                    fi
                    apply_rotation "$DPI_NAME" "$INT_ROT"
                fi
                if [ "$(is_output_enabled "$HDMI_NAME")" != "yes" ]; then
                    wlr-randr --output "$HDMI_NAME" --on --pos 0,0 $HDMI_MODE_FLAG 2>/dev/null
                    echo "$LOG_TAG Enabled $HDMI_NAME"
                    NEED_RESTART=true
                elif [ -n "$HDMI_MODE_FLAG" ]; then
                    wlr-randr --output "$HDMI_NAME" $HDMI_MODE_FLAG 2>/dev/null
                    echo "$LOG_TAG Applied $HDMI_MODE_FLAG to $HDMI_NAME"
                    NEED_RESTART=true
                fi
                apply_rotation "$HDMI_NAME" "$EXT_ROT"
                pinctrl set 18 op dl 2>/dev/null || true  # Backlight on
                echo "$LOG_TAG Mirror mode applied (both at 0,0)"
            else
                # HDMI not connected — just keep DPI
                echo "$LOG_TAG HDMI not connected, showing internal only"
                if [ -n "$DPI_NAME" ]; then
                    if [ "$(is_output_enabled "$DPI_NAME")" != "yes" ]; then
                        wlr-randr --output "$DPI_NAME" --on --pos 0,0 2>/dev/null
                    fi
                    apply_rotation "$DPI_NAME" "$INT_ROT"
                fi
                pinctrl set 18 op dl 2>/dev/null || true
            fi
            ;;

        *)
            echo "$LOG_TAG Unknown mode: $MODE, defaulting to internal"
            apply_wayland "internal"
            return
            ;;
    esac

    # Only restart Chromium if display geometry actually changed
    if [ "$NEED_RESTART" = true ]; then
        sleep 1
        pkill -f 'chromium.*kiosk' 2>/dev/null || true
        echo "$LOG_TAG Chromium restarted (display geometry changed)"
    else
        echo "$LOG_TAG No display change needed, Chromium untouched"
    fi
}

apply_x11() {
    local MODE="$1"
    local NEED_RESTART=false

    case "$MODE" in
        internal)
            if [ -n "$DPI_NAME" ]; then
                xrandr --output "$DPI_NAME" --auto --primary 2>/dev/null
            fi
            pinctrl set 18 op dl 2>/dev/null || true
            if [ -n "$HDMI_NAME" ] && [ "$HDMI_CONNECTED" = true ]; then
                xrandr --output "$HDMI_NAME" --off 2>/dev/null
                NEED_RESTART=true
            fi
            echo "$LOG_TAG Internal mode applied (X11)"
            ;;

        external)
            if [ "$HDMI_CONNECTED" = true ] && [ -n "$HDMI_NAME" ]; then
                xrandr --output "$HDMI_NAME" --auto --primary 2>/dev/null
                if [ -n "$DPI_NAME" ]; then
                    xrandr --output "$DPI_NAME" --off 2>/dev/null
                fi
                pinctrl set 18 op dh 2>/dev/null || true
                NEED_RESTART=true
                echo "$LOG_TAG External mode applied (X11)"
            else
                echo "$LOG_TAG HDMI not connected, falling back to internal (X11)"
                if [ -n "$DPI_NAME" ]; then
                    xrandr --output "$DPI_NAME" --auto --primary 2>/dev/null
                fi
                pinctrl set 18 op dl 2>/dev/null || true
            fi
            ;;

        mirror)
            if [ "$HDMI_CONNECTED" = true ] && [ -n "$HDMI_NAME" ] && [ -n "$DPI_NAME" ]; then
                xrandr --output "$DPI_NAME" --auto --primary \
                       --output "$HDMI_NAME" --auto --same-as "$DPI_NAME" 2>/dev/null
                pinctrl set 18 op dl 2>/dev/null || true
                NEED_RESTART=true
                echo "$LOG_TAG Mirror mode applied (X11)"
            else
                if [ -n "$DPI_NAME" ]; then
                    xrandr --output "$DPI_NAME" --auto --primary 2>/dev/null
                fi
                pinctrl set 18 op dl 2>/dev/null || true
            fi
            ;;
    esac

    if [ "$NEED_RESTART" = true ]; then
        sleep 1
        pkill -f 'chromium.*kiosk' 2>/dev/null || true
        echo "$LOG_TAG Chromium restarted (display geometry changed)"
    else
        echo "$LOG_TAG No display change needed, Chromium untouched"
    fi
}

# Output status as JSON
print_status() {
    detect_displays
    MODE=$(get_mode)

    # Show effective mode for auto
    if [ "$MODE" = "auto" ]; then
        if [ "$HDMI_CONNECTED" = true ]; then
            EFFECTIVE="external"
        else
            EFFECTIVE="internal"
        fi
    else
        EFFECTIVE="$MODE"
    fi

    cat << STATUSEOF
{"mode": "$MODE", "effective": "$EFFECTIVE", "hdmi_connected": $HDMI_CONNECTED, "hdmi_enabled": $HDMI_ENABLED, "hdmi_name": "$HDMI_NAME", "dpi_name": "$DPI_NAME", "hdmi_res": "${HDMI_RES:-}", "dpi_res": "${DPI_RES:-}"}
STATUSEOF
}

# Main
case "${1:-apply}" in
    apply)
        apply_mode
        ;;
    status)
        print_status
        ;;
    *)
        echo "Usage: $0 [apply|status]"
        exit 1
        ;;
esac
