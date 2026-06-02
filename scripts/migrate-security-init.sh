#!/bin/bash
# Vernis — one-time migration for already-deployed devices.
# Idempotent: safe to run multiple times.
#
# Usage:
#   INSTALL_USER_PASSWORD='<device pwd>' sudo -E bash /opt/vernis/scripts/migrate-security-init.sh

set -e

SECURITY_FILE="/opt/vernis/security.json"
AUDIT_FILE="/opt/vernis/audit.log"
SESSIONS_FILE="/opt/vernis/security-sessions.json"
FAILURES_FILE="/opt/vernis/security-failures.json"

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root (use sudo)." >&2
    exit 1
fi

# Flask runs as the user the systemd unit declares — detect it so all
# files we create are owned correctly. Falls back to the user that owns
# /opt/vernis (set by install.sh).
FLASK_USER="$(systemctl show -p User --value vernis-api.service 2>/dev/null)"
[ -z "$FLASK_USER" ] && FLASK_USER="$(stat -c '%U' /opt/vernis 2>/dev/null)"
if [ -z "$FLASK_USER" ] || [ "$FLASK_USER" = "root" ]; then
    echo "Could not determine Flask service user (got '$FLASK_USER')." >&2
    echo "Set FLASK_USER manually and re-run." >&2
    exit 1
fi

# Always (re)apply ownership/permissions, even if security.json already
# exists. Past versions of this script left files root-owned, leaving
# Flask unable to read security.json or write audit.log — silently
# falling back to defaults (Mode A, no PIN, recovery broken).
fix_perms() {
    local f="$1" mode="$2"
    [ -e "$f" ] || return 0
    chown "$FLASK_USER:$FLASK_USER" "$f"
    chmod "$mode" "$f"
}

fix_data_dirs() {
    # Data directories that Flask must own. Past root-only operations (CSV
    # imports run via sudo, sidecar JSONs written by background jobs, etc.)
    # have left individual files root-owned, breaking writes — e.g. the
    # auto-update toggle for wallet collections, NFT source-map updates, hide
    # toggles. Recursively chown everything except the scripts/ subtree and
    # any *.pre-* backup files.
    for d in nfts csv-library files; do
        [ -d "/opt/vernis/$d" ] || continue
        find "/opt/vernis/$d" -not -name "*.pre-*" \
            \( ! -user "$FLASK_USER" -o ! -group "$FLASK_USER" \) \
            -exec chown "$FLASK_USER:$FLASK_USER" {} + 2>/dev/null || true
    done
}

if [ -f "$SECURITY_FILE" ]; then
    echo "security.json already exists; re-applying ownership only."
    fix_perms "$SECURITY_FILE" 0600
    fix_perms "$AUDIT_FILE"    0640
    fix_perms "$SESSIONS_FILE" 0600
    fix_perms "$FAILURES_FILE" 0600
    fix_data_dirs
    systemctl restart vernis-api
    echo "Ownership fixed; Flask restarted."
    exit 0
fi

PWD_VAR="${INSTALL_USER_PASSWORD:-}"
if [ -z "$PWD_VAR" ]; then
    echo "Set INSTALL_USER_PASSWORD env var first." >&2
    exit 1
fi

# Ensure bcrypt is installed
pip3 show bcrypt > /dev/null 2>&1 || pip3 install bcrypt --break-system-packages

NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
OWNER_HASH=$(INSTALL_USER_PASSWORD="$PWD_VAR" python3 - <<'PYEOF'
import bcrypt, os
pwd = os.environ["INSTALL_USER_PASSWORD"]
print(bcrypt.hashpw(pwd.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8"))
PYEOF
)

cat > "$SECURITY_FILE" <<EOF
{
  "version": 1,
  "mode": "A",
  "pin_hash": null,
  "owner_pwd_hash": "$OWNER_HASH",
  "recovery_logo_enabled": true,
  "created_at": "$NOW"
}
EOF
touch "$AUDIT_FILE"
echo "{}" > "$SESSIONS_FILE"
echo '{"by_ip": {}, "global": [], "hard_locked_at": null}' > "$FAILURES_FILE"

# CRITICAL: files must be owned by the Flask user, otherwise:
#   - load_security_config() catches PermissionError → returns defaults
#     → server falsely reports Mode A / has_pin:false
#     → owner cannot set or recover a PIN, all auth silently fails
#   - append_audit() silently drops every security event (no forensics)
fix_perms "$SECURITY_FILE" 0600
fix_perms "$AUDIT_FILE"    0640
fix_perms "$SESSIONS_FILE" 0600
fix_perms "$FAILURES_FILE" 0600
fix_data_dirs

systemctl restart vernis-api
systemctl reload caddy

echo "Migration complete. Device runs in Mode A — no behavior change."
echo "To enable PIN: visit Settings → Security."
