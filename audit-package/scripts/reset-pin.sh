#!/bin/bash
# Vernis — emergency PIN reset.
# Wipes the PIN, drops to Mode A, revokes all sessions, preserves
# owner_pwd_hash, reloads Flask.
#
# Usage: sudo /opt/vernis/scripts/reset-pin.sh

set -e

CONFIG_FILE="/opt/vernis/security.json"
SESSIONS_FILE="/opt/vernis/security-sessions.json"
FAILURES_FILE="/opt/vernis/security-failures.json"
AUDIT_LOG="/opt/vernis/audit.log"

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root (use sudo)." >&2
    exit 1
fi

echo "This will wipe the PIN and unlock the device. Continue? [y/N]"
read -r CONFIRM
if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
    echo "Aborted."
    exit 0
fi

OWNER_HASH=""
if [ -f "$CONFIG_FILE" ]; then
    OWNER_HASH=$(python3 -c "
import json
try:
    with open('$CONFIG_FILE') as f:
        d = json.load(f)
    print(d.get('owner_pwd_hash') or '')
except Exception:
    print('')
")
fi

NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
cat > "$CONFIG_FILE" <<EOF
{
  "version": 1,
  "mode": "A",
  "pin_hash": null,
  "owner_pwd_hash": $([ -n "$OWNER_HASH" ] && echo "\"$OWNER_HASH\"" || echo "null"),
  "recovery_logo_enabled": true,
  "created_at": "$NOW"
}
EOF
chmod 0600 "$CONFIG_FILE"

echo "{}" > "$SESSIONS_FILE"
chmod 0600 "$SESSIONS_FILE"
echo '{"by_ip": {}, "global": [], "hard_locked_at": null}' > "$FAILURES_FILE"
chmod 0600 "$FAILURES_FILE"

echo "{\"ts\":\"$NOW\",\"ip\":\"localhost\",\"action\":\"recovery_ssh\",\"result\":\"ok\"}" >> "$AUDIT_LOG"

systemctl reload vernis-api 2>/dev/null || systemctl restart vernis-api

echo "PIN cleared. Mode set to Open."
