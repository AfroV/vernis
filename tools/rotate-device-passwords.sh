#!/bin/bash
##############################################################################
# Vernis — rotate device Linux passwords + recovery owner_pwd_hash
#
# For each reachable device:
#   1. Generate a random new password (24 chars, base64 alphabet without +/=)
#   2. SSH in with the CURRENT password (from secrets.env)
#   3. Change the Linux account password via `chpasswd`
#   4. Update /opt/vernis/security.json owner_pwd_hash so PIN recovery still
#      works with the new password
#   5. Verify the new password works (fresh SSH login)
#   6. Atomically write the new value to secrets.env + handover/<device>.md
#
# Safety:
#   - Old secrets.env is backed up to secrets.env.bak.<timestamp> before any
#     change.
#   - Per-device staging file holds OLD + NEW until verify passes; if verify
#     fails the script aborts and prints both values so you can recover.
#   - --dry-run shows what would change without touching devices.
#   - Filter to specific devices by listing names as args.
#
# Usage:
#   bash tools/rotate-device-passwords.sh                  # all reachable
#   bash tools/rotate-device-passwords.sh afrol            # just one
#   bash tools/rotate-device-passwords.sh --dry-run        # preview only
##############################################################################
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SECRETS_ENV="$REPO_ROOT/secrets.env"
HANDOVER_DIR="$REPO_ROOT/handover"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

[ -f "$SECRETS_ENV" ] || {
    echo "❌ $SECRETS_ENV not found. Copy secrets.env.template, fill in the"
    echo "   CURRENT device passwords, then re-run." >&2
    exit 1
}
command -v sshpass >/dev/null || { echo "❌ install sshpass"; exit 1; }

DRY_RUN=0
FILTER=()
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        -*) echo "Unknown flag: $arg" >&2; exit 2 ;;
        *) FILTER+=("$arg") ;;
    esac
done

# Source current passwords
set -a
# shellcheck disable=SC1090
. "$SECRETS_ENV"
set +a

# ── Fleet inventory: name | ip | lan_cidr ────────────────────────────────
# (Passwords come from $VERNIS_PASS_<name>; never inlined here.)
FLEET=(
  "afrom     | 10.0.0.39"
  "afrol     | 10.0.0.28"
  "vernis1   | 10.0.0.40"
  "vernis2   | 10.0.0.41"
  "vernis3   | 10.0.0.43"
  "vernis4   | 10.0.0.44"
  "vernis5   | 10.0.0.45"
  "vernis6   | 10.0.0.42"
  "vernis7   | 10.0.0.46"
)

match_filter() {
    [ ${#FILTER[@]} -eq 0 ] && return 0
    local name="$1"
    for f in "${FILTER[@]}"; do [ "$f" = "$name" ] && return 0; done
    return 1
}

# Cryptographically-random 24-char password (no shell-special chars)
gen_password() {
    LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24
    echo
}

# Read the password for a device from the sourced env (`VERNIS_PASS_<name>`)
get_current_pass() {
    local var="VERNIS_PASS_$1"
    printf '%s' "${!var:-}"
}

# Atomic update of one key=value line in secrets.env (preserves order/comments)
write_secret() {
    local key="$1" val="$2"
    local tmp="${SECRETS_ENV}.tmp"
    if grep -q "^${key}=" "$SECRETS_ENV" 2>/dev/null; then
        # Replace existing line
        awk -v k="$key" -v v="$val" 'BEGIN{FS=OFS="="} {
            if ($1==k) print k"="v; else print $0
        }' "$SECRETS_ENV" > "$tmp"
    else
        cp "$SECRETS_ENV" "$tmp"
        printf '%s=%s\n' "$key" "$val" >> "$tmp"
    fi
    mv "$tmp" "$SECRETS_ENV"
    chmod 600 "$SECRETS_ENV"
}

write_handover() {
    local name="$1" ip="$2" pass="$3"
    mkdir -p "$HANDOVER_DIR"
    chmod 700 "$HANDOVER_DIR"
    local out="$HANDOVER_DIR/${name}.md"
    cat > "$out" <<EOF
# Vernis device — $name

**IP on your local network:** \`$ip\`
**Username:** \`$name\`
**Password:** \`$pass\`

## Web UI
Open in any browser on the same WiFi: <http://$ip>

## Change the password later
\`\`\`
ssh $name@$ip
passwd
sudo /opt/vernis/scripts/update-owner-password.sh
\`\`\`
The second command re-syncs the PIN-recovery hash with your new password.

## Forgot the PIN?
- **From the device:** hold the kiosk logo for 5 seconds, then enter the password above.
- **Via SSH:** \`ssh $name@$ip\` → \`sudo /opt/vernis/scripts/reset-pin.sh\`

Generated: $(date -u +"%Y-%m-%d %H:%M UTC")
EOF
    chmod 600 "$out"
    echo "$out"
}

rotate_one() {
    local NAME="$1" IP="$2"
    local OLD NEW
    OLD=$(get_current_pass "$NAME")
    NEW=$(gen_password)

    echo
    echo "════════ $NAME ($IP) ════════"

    if [ -z "$OLD" ]; then
        echo "  ⚠  no current password in secrets.env (VERNIS_PASS_$NAME) — skipping"
        return 0
    fi

    local SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
                    -o LogLevel=ERROR -o ConnectTimeout=8)

    # 1. Reachability + OLD password works
    if ! SSHPASS="$OLD" sshpass -e ssh "${SSH_OPTS[@]}" "$NAME@$IP" "echo alive" >/dev/null 2>&1; then
        echo "  ⏭️  unreachable or OLD password rejected — skipping"
        return 0
    fi
    echo "  ✓ reachable, OLD pass works"

    if [ "$DRY_RUN" = "1" ]; then
        echo "  [DRY_RUN] would rotate to a 24-char random password"
        echo "  [DRY_RUN] would update owner_pwd_hash in /opt/vernis/security.json"
        echo "  [DRY_RUN] would write VERNIS_PASS_$NAME to secrets.env and handover/$NAME.md"
        return 0
    fi

    # 2. Stage NEW value to a per-device file BEFORE remote change.
    # If verify fails, this file is your only record of the new password.
    local STAGE="$REPO_ROOT/secrets.env.bak.${STAMP}.${NAME}.staging"
    {
        echo "# Vernis rotation staging — $NAME @ $IP"
        echo "# $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
        echo "# If verify fails, the NEW password MAY have been applied."
        echo "# Try logging in with NEW first; if it fails fall back to OLD."
        echo "VERNIS_PASS_${NAME}_OLD=$OLD"
        echo "VERNIS_PASS_${NAME}_NEW=$NEW"
    } > "$STAGE"
    chmod 600 "$STAGE"

    # 3. Change Linux password + update owner_pwd_hash in one sudo block
    SSHPASS="$OLD" sshpass -e ssh "${SSH_OPTS[@]}" "$NAME@$IP" \
        "echo '$OLD' | sudo -S bash -c '
            set -e
            # Change shell password (chpasswd takes user:pass on stdin)
            echo \"$NAME:$NEW\" | chpasswd

            # Update bcrypt owner_pwd_hash in security.json so PIN recovery
            # works with the new password. Preserves PIN if one is set.
            python3 - <<PYEOF
import json, bcrypt
SEC = \"/opt/vernis/security.json\"
NEW_PASS = \"\"\"$NEW\"\"\"
try:
    with open(SEC) as f:
        cfg = json.load(f)
except FileNotFoundError:
    # security.json missing — leave for migrate-security-init.sh
    print(\"security.json missing; skipping owner hash update\")
    raise SystemExit(0)
cfg[\"owner_pwd_hash\"] = bcrypt.hashpw(NEW_PASS.encode(), bcrypt.gensalt(rounds=12)).decode()
with open(SEC, \"w\") as f:
    json.dump(cfg, f)
print(\"owner_pwd_hash updated\")
PYEOF
        '" 2>&1 | grep -vE 'sudo|\[sudo' | tail -3
    local rc=${PIPESTATUS[0]}
    if [ "$rc" != "0" ]; then
        echo "  ❌ password change failed on device (rc=$rc)"
        echo "     NEW value retained in: $STAGE"
        return 1
    fi

    # 4. Verify NEW password works (fresh SSH session)
    if ! SSHPASS="$NEW" sshpass -e ssh "${SSH_OPTS[@]}" "$NAME@$IP" "echo verified" >/dev/null 2>&1; then
        echo "  ❌ NEW password rejected on verify — device may be in mixed state!"
        echo "     STAGE: $STAGE"
        echo "     Try SSH with NEW first; if that fails fall back to OLD."
        return 1
    fi
    echo "  ✓ verified, NEW pass works"

    # 5. Commit to secrets.env (backup first) + write handover sheet
    if [ ! -f "${SECRETS_ENV}.bak.${STAMP}" ]; then
        cp "$SECRETS_ENV" "${SECRETS_ENV}.bak.${STAMP}"
        chmod 600 "${SECRETS_ENV}.bak.${STAMP}"
    fi
    write_secret "VERNIS_PASS_$NAME" "$NEW"
    local hand
    hand=$(write_handover "$NAME" "$IP" "$NEW")
    echo "  ✓ secrets.env updated + handover at $hand"

    # 6. Remove staging
    rm -f "$STAGE"
}

ok=0; failed=0; skipped=0
for row in "${FLEET[@]}"; do
    IFS='|' read -r name ip <<< "$row"
    name=$(echo "$name" | xargs); ip=$(echo "$ip" | xargs)
    if ! match_filter "$name"; then continue; fi
    if rotate_one "$name" "$ip"; then ok=$((ok+1)); else failed=$((failed+1)); fi
done

echo
echo "════════ Summary ════════"
echo "  rotated: $ok"
echo "  failed:  $failed"
[ "$DRY_RUN" = "1" ] && echo "  (DRY_RUN — no changes made)"
if [ -f "${SECRETS_ENV}.bak.${STAMP}" ]; then
    echo "  backup:  ${SECRETS_ENV}.bak.${STAMP}"
fi
exit "$failed"
