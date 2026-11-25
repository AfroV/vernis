#!/bin/bash
##############################################
# Keep the Vernis boot splash selected (run as root). Idempotent: does nothing
# when it already is, or on a frame without the Vernis theme.
#
# Something outside Vernis can switch Plymouth back to Raspberry Pi's "pix"
# theme (raspi-config, a package). The next initramfs rebuild - an OS update
# with a new kernel or firmware - bakes that in, and the frame boots with a
# Raspberry Pi logo turned 90 degrees (pix isn't rotated for the panel; the
# Vernis splash.png is).
#
# Run by vernis-post-update.sh on every run, so also at every boot
# (touch-to-wake.sh), and by vernis-update.sh after its OS upgrade.
##############################################

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash ensure-boot-splash.sh"
    exit 1
fi

THEME=/usr/share/plymouth/themes/vernis/vernis.plymouth
SET=/usr/sbin/plymouth-set-default-theme

[ -f "$THEME" ] && [ -x "$SET" ] || exit 0

CURRENT=$("$SET" 2>/dev/null)
[ "$CURRENT" = "vernis" ] && exit 0

echo "Boot splash was '${CURRENT:-none}' - selecting the Vernis splash (rebuilds the initramfs)"
"$SET" -R vernis
