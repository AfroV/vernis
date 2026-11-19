#!/bin/bash
##############################################
# Install the updater for Settings > Install update (run as root).
# Called by vernis-post-update.sh.
#
# vernis-api runs as the owner's account. Raspberry Pi OS images made with
# cloud-init (Raspberry Pi Imager, 2025+) don't give that account
# password-free sudo, so a plain `sudo bash vernis-update.sh` from the API
# fails and the update never starts. Instead:
# - /usr/local/sbin/vernis-update: root-owned copy of vernis-update.sh
#   (copied OUT of /opt/vernis/scripts, which vernis-api's account can edit)
# - one sudo rule: vernis-api may run exactly that file. It only installs
#   from AfroV/vernis (or a repo root listed in /etc/vernis/allowed-update-repos).
##############################################

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/vernis-update.sh"
DEST=/usr/local/sbin/vernis-update
SUDOERS=/etc/sudoers.d/vernis-update

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash install-updater.sh"
    exit 1
fi
if [ ! -f "$SRC" ]; then
    echo "WARN: $SRC missing - updater not installed"
    exit 0
fi

install -o root -g root -m 755 "$SRC" "$DEST"

API_USER=$(systemctl show -p User --value vernis-api 2>/dev/null)
if [ -n "$API_USER" ] && [ "$API_USER" != "root" ]; then
    TMP=$(mktemp)
    echo "$API_USER ALL=(root) NOPASSWD: $DEST *" > "$TMP"
    if visudo -cf "$TMP" >/dev/null; then
        install -o root -g root -m 440 "$TMP" "$SUDOERS"
    else
        echo "WARN: sudo rule for the updater failed validation - not installed"
    fi
    rm -f "$TMP"
fi
echo "Updater installed ($DEST)"
