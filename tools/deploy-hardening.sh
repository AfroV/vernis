#!/bin/bash
##############################################################################
# Vernis — fleet deploy of public-node hardening
#
# Pushes harden-public-node.sh + the new Caddyfile to each reachable device,
# reloads Caddy, and runs the hardening script. Skips offline devices.
#
# Credentials live in ../secrets.env (gitignored). Never inlined here.
#
# Usage:
#   bash tools/deploy-hardening.sh                 # all reachable devices
#   bash tools/deploy-hardening.sh afrom vernis2   # only listed devices
#   DRY_RUN=1 bash tools/deploy-hardening.sh       # show what would happen
##############################################################################
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SECRETS_ENV="$REPO_ROOT/secrets.env"
ROOT="$REPO_ROOT/audit-package"
SCRIPT_SRC="$ROOT/scripts/harden-public-node.sh"
CADDY_SRC="$ROOT/config/Caddyfile"

[ -f "$SCRIPT_SRC" ] || { echo "❌ $SCRIPT_SRC missing"; exit 1; }
[ -f "$CADDY_SRC"  ] || { echo "❌ $CADDY_SRC missing";  exit 1; }
[ -f "$SECRETS_ENV" ] || { echo "❌ $SECRETS_ENV missing — copy secrets.env.template"; exit 1; }
command -v sshpass >/dev/null || { echo "❌ install sshpass"; exit 1; }

set -a; . "$SECRETS_ENV"; set +a

# ── Fleet inventory (user | ip | lan_cidr | mode) ─────────────────────────
#   mode = public | private (defaults to public if unspecified)
#   Passwords come from $VERNIS_PASS_<user> in secrets.env.
FLEET=(
  "afrom     | 10.0.0.39 | 10.0.0.0/24 | public"
  "afrol     | 10.0.0.28 | 10.0.0.0/24 | public"
  "vernis1   | 10.0.0.40 | 10.0.0.0/24 | public"
  "vernis2   | 10.0.0.41 | 10.0.0.0/24 | public"
  "vernis3   | 10.0.0.43 | 10.0.0.0/24 | public"
  "vernis4   | 10.0.0.44 | 10.0.0.0/24 | public"
  "vernis5   | 10.0.0.45 | 10.0.0.0/24 | public"
  "vernis6   | 10.0.0.42 | 10.0.0.0/24 | public"
  "vernis7   | 10.0.0.46 | 10.0.0.0/24 | public"
)

FILTER=("$@")
match_filter() {
    [ ${#FILTER[@]} -eq 0 ] && return 0
    local name="$1"
    for f in "${FILTER[@]}"; do [ "$f" = "$name" ] && return 0; done
    return 1
}

# ── Per-device deploy ─────────────────────────────────────────────────────
deploy_one() {
    local USER="$1" PASS="$2" IP="$3" LAN="$4" MODE="$5"
    local SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
                    -o LogLevel=ERROR -o ConnectTimeout=8)

    echo
    echo "════════ $USER ($IP) ════════"

    # 1. Reachability gate
    if ! sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" "echo alive" >/dev/null 2>&1; then
        echo "  ⏭️  offline — skipping"
        return 0
    fi

    if [ "${DRY_RUN:-0}" = "1" ]; then
        echo "  [DRY_RUN] would push script + Caddyfile, then run hardening (mode=$MODE, lan=$LAN)"
        return 0
    fi

    # 2. Backup current Caddyfile (one-time per device)
    sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" \
        "echo '$PASS' | sudo -S bash -c '
            [ ! -f /etc/caddy/Caddyfile.pre-harden-bak ] && \
              cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.pre-harden-bak 2>/dev/null
            true
        '" 2>&1 | grep -vE 'sudo|\[sudo' | tail -1

    # 3. scp both files to /tmp on the device
    sshpass -p "$PASS" scp "${SSH_OPTS[@]}" "$SCRIPT_SRC" "$USER@$IP":/tmp/harden.sh >/dev/null || \
        { echo "  ❌ scp script failed"; return 1; }
    sshpass -p "$PASS" scp "${SSH_OPTS[@]}" "$CADDY_SRC"  "$USER@$IP":/tmp/Caddyfile >/dev/null || \
        { echo "  ❌ scp Caddyfile failed"; return 1; }

    # 4. Install + validate Caddyfile + reload Caddy
    # Note: caddy reload can hang for ~90s × forever if /var/log/caddy/*.log
    # is owned by root rather than the caddy user — observed on afrom. We
    # proactively fix that before reload to prevent the hang.
    sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" "echo '$PASS' | sudo -S bash -c '
        set -e
        # Install script
        mv /tmp/harden.sh /opt/vernis/scripts/harden-public-node.sh
        chown $USER:$USER /opt/vernis/scripts/harden-public-node.sh
        chmod +x /opt/vernis/scripts/harden-public-node.sh

        # Fix caddy log file ownership preemptively
        mkdir -p /var/log/caddy
        chown -R caddy:caddy /var/log/caddy
        find /var/log/caddy -type f -exec chmod 0644 {} +

        # Validate Caddyfile before swapping
        if ! caddy validate --config /tmp/Caddyfile 2>&1 | tail -3; then
            echo \"  ❌ Caddyfile validation failed — keeping current\"
            rm -f /tmp/Caddyfile
            exit 2
        fi
        mv /tmp/Caddyfile /etc/caddy/Caddyfile

        # Use restart not reload — cleaner state, avoids the certmagic reload
        # corner cases we hit during canary.
        systemctl restart caddy
        sleep 2
        systemctl is-active caddy
        echo \"  ✓  caddy restarted\"
    '" 2>&1 | grep -vE '^\[sudo\]'
    local rc=${PIPESTATUS[0]}
    [ $rc -ne 0 ] && { echo "  ❌ install failed (rc=$rc) — see above"; return 1; }

    # 5. Run hardening script with explicit env (don't autodetect; we know the LAN)
    echo "  ── running harden script (mode=$MODE, LAN=$LAN) ──"
    sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" "echo '$PASS' | sudo -S \
        VERNIS_LAN_CIDR='$LAN' VERNIS_NETWORK_MODE='$MODE' \
        bash /opt/vernis/scripts/harden-public-node.sh 2>&1" \
        2>&1 | grep -vE '^\[sudo\]' | sed 's/^/    /'
    local hrc=${PIPESTATUS[0]}
    [ $hrc -ne 0 ] && { echo "  ❌ hardening failed (rc=$hrc)"; return 1; }

    # 6. Quick verification
    echo "  ── verify ──"
    sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" "echo '$PASS' | sudo -S bash -c '
        echo \"    ufw: \$(ufw status | grep -c \"^ALLOW\\|^DENY\\|.*ALLOW\\|.*DENY\") rules\"
        nofetch=\$(sudo -u $USER ipfs config Gateway.NoFetch 2>/dev/null)
        echo \"    Gateway.NoFetch: \$nofetch\"
        api=\$(sudo -u $USER ipfs config Addresses.API 2>/dev/null)
        echo \"    IPFS API: \$api\"
        echo \"    caddy: \$(systemctl is-active caddy)\"
        echo \"    ipfs:  \$(systemctl is-active ipfs)\"
    '" 2>&1 | grep -vE 'sudo|\[sudo'

    echo "  ✅ done: $USER"
}

# ── Run ────────────────────────────────────────────────────────────────────
echo "Vernis fleet hardening deploy"
echo "Script source: $SCRIPT_SRC"
echo "Caddy source:  $CADDY_SRC"
[ ${#FILTER[@]} -gt 0 ] && echo "Filter:        ${FILTER[*]}"
[ "${DRY_RUN:-0}" = "1" ] && echo "DRY_RUN mode — no changes will be made"

SUCCESS=()
FAILED=()
SKIPPED=()

for row in "${FLEET[@]}"; do
    IFS='|' read -r USER IP LAN MODE <<< "$row"
    USER=$(echo "$USER" | xargs); IP=$(echo "$IP" | xargs)
    LAN=$(echo "$LAN" | xargs); MODE=$(echo "$MODE" | xargs)
    PASS_VAR="VERNIS_PASS_$USER"
    PASS="${!PASS_VAR:-}"
    if [ -z "$PASS" ]; then
        echo
        echo "════════ $USER ($IP) ════════"
        echo "  ⚠  no password in secrets.env (VERNIS_PASS_$USER) — skipping"
        SKIPPED+=("$USER")
        continue
    fi

    match_filter "$USER" || continue

    if deploy_one "$USER" "$PASS" "$IP" "$LAN" "$MODE"; then
        # deploy_one may have printed "offline — skipping" and returned 0
        if sshpass -p "$PASS" ssh -o ConnectTimeout=4 -o LogLevel=ERROR "$USER@$IP" "true" 2>/dev/null; then
            SUCCESS+=("$USER")
        else
            SKIPPED+=("$USER")
        fi
    else
        FAILED+=("$USER")
    fi
done

echo
echo "════════ summary ════════"
echo "  ✓  success: ${#SUCCESS[@]}  ${SUCCESS[*]:-}"
echo "  ⏭️  skipped: ${#SKIPPED[@]}  ${SKIPPED[*]:-}"
echo "  ❌ failed:  ${#FAILED[@]}  ${FAILED[*]:-}"

[ ${#FAILED[@]} -eq 0 ]
