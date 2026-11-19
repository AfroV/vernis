#!/bin/bash
##############################################
# Write /etc/sudoers.d/vernis-api: what vernis-api may run as root without a
# password (run as root). The only copy of this list - install-vernis.sh,
# vernis-post-update.sh (every update, so older frames get it too) and
# update-deployed-pi.sh all use this script.
#
# Only what backend/app.py actually runs. Rules nothing used were removed
# (dpkg, apt-mark, dnsmasq, badblocks, ufw, brctl, bluetoothctl, systemctl
# status), and the fan rules name the exact sysfs files instead of a
# wildcard.
#
# Root helpers with their own narrow rules: vernis-update, vernis-storage,
# vernis-device-password (install-updater.sh, install-storage-helper.sh,
# install-password-helper.sh).
##############################################

SUDOERS=/etc/sudoers.d/vernis-api

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash install-api-sudo.sh"
    exit 1
fi

API_USER="${1:-$(systemctl show -p User --value vernis-api 2>/dev/null)}"
if [ -z "$API_USER" ] || [ "$API_USER" = "root" ]; then
    echo "vernis-api runs as root - no sudo rules needed"
    exit 0
fi

U="$API_USER"
TMP=$(mktemp)
cat > "$TMP" << EOF
# Vernis API - limited sudo for specific operations.
# Written by install-api-sudo.sh: edits here are replaced on the next update.
$U ALL=(ALL) NOPASSWD: /sbin/reboot
$U ALL=(ALL) NOPASSWD: /sbin/shutdown
$U ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart vernis-*
$U ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart caddy
$U ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart ipfs
$U ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart hciuart
$U ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart bluetooth
$U ALL=(ALL) NOPASSWD: /usr/bin/systemctl start vernis-*
$U ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop vernis-*
$U ALL=(ALL) NOPASSWD: /usr/bin/apt update
$U ALL=(ALL) NOPASSWD: /usr/bin/apt upgrade -y
$U ALL=(ALL) NOPASSWD: /usr/bin/nmcli *
$U ALL=(ALL) NOPASSWD: /usr/bin/tee /sys/class/thermal/thermal_zone[0-9]/trip_point_[0-9]_temp
$U ALL=(ALL) NOPASSWD: /usr/bin/tee /sys/class/thermal/cooling_device[0-9]/cur_state
$U ALL=(ALL) NOPASSWD: /usr/bin/tee /sys/class/thermal/cooling_device[0-9][0-9]/cur_state
$U ALL=(ALL) NOPASSWD: /usr/bin/tee /boot/firmware/config.txt
$U ALL=(ALL) NOPASSWD: /usr/bin/tee /boot/config.txt
$U ALL=(ALL) NOPASSWD: /usr/bin/tee /boot/firmware/cmdline.txt
$U ALL=(ALL) NOPASSWD: /usr/bin/tee /boot/cmdline.txt
EOF

if ! visudo -cf "$TMP" >/dev/null; then
    echo "WARN: vernis-api sudo rules failed validation - left unchanged"
    rm -f "$TMP"
    exit 1
fi
if cmp -s "$TMP" "$SUDOERS"; then
    rm -f "$TMP"
else
    install -o root -g root -m 440 "$TMP" "$SUDOERS"
    rm -f "$TMP"
    echo "vernis-api sudo rules written ($SUDOERS)"
fi
