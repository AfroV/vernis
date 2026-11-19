#!/bin/bash
##############################################
# Install the storage helper (run as root).
# Called by install-vernis.sh and vernis-update.sh.
#
# - /usr/local/sbin/vernis-storage: root-owned copy of vernis-storage-helper.py
#   (copied OUT of /opt/vernis/scripts, which vernis-api's account can edit)
# - udev rule: USB drives are mounted under /media/vernis when plugged in.
#   Raspberry Pi OS only automounts from a desktop file manager, which the
#   kiosk session doesn't run.
# - one sudo rule: vernis-api may run `prepare`, `prepare-backups` and `ipfs-move` only.
##############################################

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/vernis-storage-helper.py"
DEST=/usr/local/sbin/vernis-storage
RULE=/etc/udev/rules.d/99-vernis-automount.rules
SUDOERS=/etc/sudoers.d/vernis-storage

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash install-storage-helper.sh"
    exit 1
fi
if [ ! -f "$SRC" ]; then
    echo "WARN: $SRC missing - storage helper not installed"
    exit 0
fi

install -o root -g root -m 755 "$SRC" "$DEST"
mkdir -p /media/vernis

# systemd-run: udev kills long RUN programs, so the mount runs as its own unit
cat > "$RULE" << EOF
# Vernis: mount USB drives under /media/vernis (see $DEST)
ACTION=="add", SUBSYSTEM=="block", ENV{ID_BUS}=="usb", ENV{ID_FS_USAGE}=="filesystem", RUN+="/usr/bin/systemd-run --no-block --collect $DEST mount %k"
ACTION=="remove", SUBSYSTEM=="block", ENV{ID_BUS}=="usb", RUN+="/usr/bin/systemd-run --no-block --collect $DEST unmount %k"
EOF
udevadm control --reload-rules 2>/dev/null || true
# Mount drives that are already plugged in
udevadm trigger --action=add --subsystem-match=block --property-match=ID_BUS=usb 2>/dev/null || true

API_USER=$(systemctl show -p User --value vernis-api 2>/dev/null)
if [ -n "$API_USER" ] && [ "$API_USER" != "root" ]; then
    TMP=$(mktemp)
    echo "$API_USER ALL=(root) NOPASSWD: $DEST prepare *, $DEST prepare-backups *, $DEST ipfs-move *" > "$TMP"
    if visudo -cf "$TMP" >/dev/null; then
        install -o root -g root -m 440 "$TMP" "$SUDOERS"
    else
        echo "WARN: sudo rule for the storage helper failed validation - not installed"
    fi
    rm -f "$TMP"
fi
echo "Storage helper installed (USB drives mount under /media/vernis)"
