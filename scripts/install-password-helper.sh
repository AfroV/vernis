#!/bin/bash
##############################################
# Install the device-password helper (run as root).
# Called by install-vernis.sh and vernis-update.sh.
#
# vernis-api runs as the owner's account and needs root only to check or set
# that account's password (setup wizard, Settings > Password). The helper is
# copied OUT of /opt/vernis/scripts (owned by that account, so it could edit
# it) to a root-owned path, and one sudo rule allows exactly that file.
##############################################

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/vernis-device-password.py"
DEST=/usr/local/sbin/vernis-device-password
SUDOERS=/etc/sudoers.d/vernis-device-password

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash install-password-helper.sh"
    exit 1
fi

# The account vernis-api runs as. Empty or root = it can change passwords itself.
API_USER=$(systemctl show -p User --value vernis-api 2>/dev/null)
if [ -z "$API_USER" ] || [ "$API_USER" = "root" ]; then
    echo "vernis-api runs as root - password helper not needed"
    exit 0
fi
if [ ! -f "$SRC" ]; then
    echo "WARN: $SRC missing - password helper not installed"
    exit 0
fi

install -o root -g root -m 755 "$SRC" "$DEST"
TMP=$(mktemp)
echo "$API_USER ALL=(root) NOPASSWD: $DEST" > "$TMP"
if visudo -cf "$TMP" >/dev/null; then
    install -o root -g root -m 440 "$TMP" "$SUDOERS"
    echo "Password helper installed for $API_USER"
else
    echo "WARN: sudo rule for the password helper failed validation - not installed"
fi
rm -f "$TMP"
