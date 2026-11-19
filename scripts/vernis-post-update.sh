#!/bin/bash
##############################################
# Root setup a Vernis version needs beyond its files: root-owned helpers and
# their sudo rules (run as root). Idempotent.
#
# Run by:
# - install-vernis.sh (fresh install)
# - vernis-update.sh (3.6+), from the NEW release it just downloaded
# - touch-to-wake.sh at boot, with --if-needed: an update is run by the
#   updater already on the device, and updaters before 3.6 don't run this.
#   That boot service is the first root code of the new version to start.
#
#   --if-needed   do nothing if this version's setup has already run
##############################################

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
# place (Settings tells the owner to restart if an update can't start).
API_USER=$(systemctl show -p User --value vernis-api 2>/dev/null)
if [ "${1:-}" = "--if-needed" ] && [ "$(cat "$MARK" 2>/dev/null)" = "$VERSION" ] && \
   { [ -f /etc/sudoers.d/vernis-update ] || [ -z "$API_USER" ] || [ "$API_USER" = "root" ]; }; then
    exit 0
fi

echo "Vernis $VERSION: root setup"
bash "$DIR/install-updater.sh" || true
bash "$DIR/install-password-helper.sh" || true
bash "$DIR/install-storage-helper.sh" || true

echo "$VERSION" > "$MARK"
echo "Vernis $VERSION: root setup done"
