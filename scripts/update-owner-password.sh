#!/bin/bash
# Vernis — re-sync owner_pwd_hash after changing the device password
# via `passwd` (NOT through the Settings UI).
#
# Usage: sudo /opt/vernis/scripts/update-owner-password.sh

set -e

CONFIG_FILE="/opt/vernis/security.json"

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root (use sudo)." >&2
    exit 1
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "$CONFIG_FILE does not exist; nothing to update." >&2
    exit 1
fi

echo -n "Enter the new device password: "
read -rs NEW_PWD
echo

if [ -z "$NEW_PWD" ]; then
    echo "Aborted: empty password." >&2
    exit 1
fi

NEW_PWD="$NEW_PWD" python3 - <<'PYEOF'
import bcrypt, json, os
pwd = os.environ["NEW_PWD"]
path = "/opt/vernis/security.json"
with open(path) as f:
    cfg = json.load(f)
cfg["owner_pwd_hash"] = bcrypt.hashpw(
    pwd.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(cfg, f, indent=2)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
print("owner_pwd_hash updated.")
PYEOF

systemctl reload vernis-api 2>/dev/null || systemctl restart vernis-api
echo "Done."
