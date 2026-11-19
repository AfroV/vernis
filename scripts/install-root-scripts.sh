#!/bin/bash
##############################################
# Root services and udev rules must not run files the Vernis app account can
# edit (run as root). Called by vernis-post-update.sh and setup-bluetooth-pan.sh.
#
# /opt/vernis is owned by vernis-api's account, so root services should not
# run files from there. Like the storage/password helpers and the updater,
# each such script is copied to a root-owned folder and the unit or rule
# points at the copy:
#
#   /usr/local/lib/vernis/   root:root 755, files root:root 755
#
# Found by scanning, not by a list, so units from older installers are
# covered too (vernis-touch-wake, vernis-touch, bt-pan, bt-agent,
# vernis-ap-check, vernis-bluetooth, 99-vernis-hdmi.rules, ...). Units that
# run as another user (vernis-api, vernis-watchdog) are left alone: the
# account runs its own code.
#
# vernis-hue-stream is the exception: it runs hue-stream, which the API
# compiles into /opt/vernis/scripts, and needs no root - it runs as the app
# account instead (the API starts the same daemon as that account itself).
#
# Copies come from the folder this script is in: the release just downloaded
# (updater, root-owned), or /opt/vernis/scripts on a fresh install. A script
# a unit needs but the release doesn't ship is copied from /opt/vernis/scripts
# once - the unit was running that file as root anyway; after this it can't
# be swapped. Run from /usr/local/lib/vernis itself (boot check on a frame
# already done) nothing is copied: units are only re-pointed.
##############################################

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB=/usr/local/lib/vernis

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash install-root-scripts.sh"
    exit 1
fi

install -d -o root -g root -m 755 "$LIB"

# Copy one file into $LIB (root:root 755) from the trusted source, or as a
# last resort from where the unit ran it. Prints nothing; fails if neither.
copy_in() {   # copy_in <name> <path the unit used>
    local name="$1" used="$2"
    [ "$SRC_DIR" = "$LIB" ] && { [ -f "$LIB/$name" ]; return; }
    if [ -f "$SRC_DIR/$name" ]; then
        install -o root -g root -m 755 "$SRC_DIR/$name" "$LIB/$name"
    elif [ -f "$used" ] && [ ! -L "$used" ]; then
        echo "  $name is not in this release - copying the installed one"
        install -o root -g root -m 755 "$used" "$LIB/$name"
    else
        [ -f "$LIB/$name" ]
    fi
}

# The root setup itself, so the boot check (touch-to-wake.sh) can run it
# without touching /opt/vernis/scripts. Not on a frame without them (copy_in
# from $LIB only checks).
for f in vernis-post-update.sh install-root-scripts.sh install-api-sudo.sh; do
    copy_in "$f" "" || true
done

# Copies made by an earlier version: replace with this release's. Units that
# already point here are not found by the scan below. (The updater reboots,
# so running services pick them up.)
if [ "$SRC_DIR" != "$LIB" ]; then
    for f in "$LIB"/*; do
        [ -f "$f" ] && [ -f "$SRC_DIR/$(basename "$f")" ] || continue
        install -o root -g root -m 755 "$SRC_DIR/$(basename "$f")" "$f"
    done
fi

API_USER=$(systemctl show -p User --value vernis-api 2>/dev/null)

# Hue streaming daemon: as the app account, not root
HUE=/etc/systemd/system/vernis-hue-stream.service
if [ -f "$HUE" ] && [ -n "$API_USER" ] && [ "$API_USER" != "root" ] && \
   ! grep -q '^User=' "$HUE"; then
    sed -i "/^\[Service\]/a User=$API_USER" "$HUE"
    echo "  vernis-hue-stream runs as $API_USER"
fi

systemctl daemon-reload 2>/dev/null || true

# Paths in a unit/rule that point at an editable executable
PATTERN='/opt/vernis/(scripts/)?[A-Za-z0-9._-]+'

changed_units=""
migrate_file() {   # migrate_file <file> <unit name, or "" for a udev rule>
    local file="$1" unit="$2" user="" lines path name ok=1
    if [ -n "$unit" ]; then
        user=$(systemctl show -p User --value "$unit" 2>/dev/null)
    fi
    # Which lines run as root: all of a root unit or a udev rule; in a unit
    # with User=, only Exec lines with the "+" (full privileges) prefix.
    if [ -z "$user" ] || [ "$user" = "root" ] || [ "$user" = "0" ]; then
        lines='^(Exec[A-Za-z]*=|.*RUN\+?=)'
    else
        lines='^Exec[A-Za-z]*=[-@:!]*\+'
    fi
    for path in $(grep -E "$lines" "$file" | grep -oE "$PATTERN" | sort -u); do
        name=$(basename "$path")
        # Data files and folders are not run (e.g. WorkingDirectory=/opt/vernis)
        [ -d "$path" ] && continue
        case "$name" in *.json|*.log|*.csv|*.txt) continue ;; esac
        if copy_in "$name" "$path"; then
            # Replace only whole paths on root-run lines (address delimited
            # by %, so the pattern needs no escaping)
            sed -E -i "\\%$lines% s#$path([^A-Za-z0-9._/-]|\$)#$LIB/$name\\1#g" "$file"
            if grep -E "$lines" "$file" | grep -qE "$path([^A-Za-z0-9._/-]|\$)"; then
                echo "WARN: $(basename "$file"): could not re-point $path"
                ok=0
            else
                echo "  $(basename "$file"): $path -> $LIB/$name"
            fi
        else
            echo "WARN: $(basename "$file") runs $path as root and no root-owned copy could be made"
            ok=0
        fi
    done
    [ -n "$unit" ] && grep -qE "$LIB/" "$file" && changed_units="$changed_units $unit"
    return $((1 - ok))
}

status=0
for file in /etc/systemd/system/*.service /etc/systemd/system/*.service.d/*.conf; do
    [ -f "$file" ] || continue
    grep -qE "$PATTERN" "$file" || continue
    case "$file" in
        *.service.d/*) unit=$(basename "$(dirname "$file")"); unit=${unit%.d} ;;
        *) unit=$(basename "$file") ;;
    esac
    migrate_file "$file" "$unit" || status=1
done
for file in /etc/udev/rules.d/*.rules; do
    [ -f "$file" ] || continue
    grep -qE "$PATTERN" "$file" || continue
    migrate_file "$file" "" || status=1
done

systemctl daemon-reload 2>/dev/null || true
udevadm control --reload-rules 2>/dev/null || true

# Running services keep the old file open until restarted. Not
# vernis-touch-wake: it may be the caller (boot check); it restarts itself.
for unit in $(echo "$changed_units" | tr ' ' '\n' | sort -u); do
    [ "$unit" = "vernis-touch-wake.service" ] && continue
    systemctl --no-block try-restart "$unit" 2>/dev/null || true
done

echo "Root services run root-owned scripts ($LIB)"
exit $status
