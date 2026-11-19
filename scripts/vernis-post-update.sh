#!/bin/bash
##############################################
# Root setup a Vernis version needs beyond its files: root-owned helpers and
# their sudo rules, root services pointed at root-owned scripts (run as root).
# Idempotent.
#
# Run by:
# - install-vernis.sh (fresh install)
# - vernis-update.sh (3.6+), from the NEW release it just downloaded
#   (root-owned clone)
# - touch-to-wake.sh at boot, with --if-needed: an update is run by the
#   updater already on the device, and updaters before 3.6 don't run this.
#   touch-to-wake.sh runs the copy next to itself:
#   * first boot after an older updater: vernis-touch-wake.service still runs
#     /opt/vernis/scripts/touch-to-wake.sh, so this runs from there - the one
#     time root code is taken from the editable folder, as in 3.6.0.
#     install-root-scripts.sh then moves the service to a root-owned copy.
#   * after that: /usr/local/lib/vernis/vernis-post-update.sh. It can't take
#     new code from /opt/vernis/scripts (the app account can edit that), so
#     it only re-checks: units re-pointed, sudo rules. New root setup comes
#     with the updater, which runs the new release's copy.
#
#   --if-needed   do nothing if this version's setup has already run
##############################################

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB=/usr/local/lib/vernis
MARK=/var/lib/vernis/post-update.version

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash vernis-post-update.sh"
    exit 1
fi

VERSION=$(python3 -c "import json; print(json.load(open('/var/www/vernis/version.json'))['version'])" 2>/dev/null || echo unknown)

# One run at a time (the boot service restarts every few seconds on frames
# without a touchscreen)
mkdir -p /var/lib/vernis
exec 9>/var/lib/vernis/post-update.lock
flock 9

# Skip only when this version's setup ran AND the updater's sudo rule is in
# place (Settings tells the owner to restart if an update can't start). The
# root-owned copy can't install that rule, so it only checks the version.
API_USER=$(systemctl show -p User --value vernis-api 2>/dev/null)
if [ "${1:-}" = "--if-needed" ] && [ "$(cat "$MARK" 2>/dev/null)" = "$VERSION" ] && \
   { [ "$DIR" = "$LIB" ] || [ -f /etc/sudoers.d/vernis-update ] || [ -z "$API_USER" ] || [ "$API_USER" = "root" ]; }; then
    exit 0
fi

echo "Vernis $VERSION: root setup"
if [ "$DIR" = "$LIB" ]; then
    # Root-owned copy at boot: nothing new to install, only re-check
    bash "$DIR/install-api-sudo.sh" || true
    bash "$DIR/install-root-scripts.sh" || true
else
    bash "$DIR/install-updater.sh" || true
    bash "$DIR/install-password-helper.sh" || true
    bash "$DIR/install-storage-helper.sh" || true
    bash "$DIR/install-api-sudo.sh" || true
    bash "$DIR/install-root-scripts.sh" || true
fi

echo "$VERSION" > "$MARK"
echo "Vernis $VERSION: root setup done"
