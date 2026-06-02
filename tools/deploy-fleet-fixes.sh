#!/bin/bash
##############################################################################
# Vernis — fleet deploy of every fix landed during the 2026-05 session
#
# Bundled fixes:
#   1. Kiosk URL localhost→127.0.0.1 (Chromium 146 auto-upgrades localhost
#      to HTTPS, breaking kiosk when HTTPS is disabled).
#      → kiosk-launcher.sh, watchdog.sh, 7 kiosk-nav URLs in app.py
#   2. /api/https GET false-positive (substring match against Caddyfile
#      comments). → app.py uses exact `tls /etc/caddy/vernis.crt` directive.
#   3. PIN security file ownership: security.json/audit.log/sessions were
#      root-owned, Flask runs as <device-user>, so load_security_config()
#      silently returned defaults and audit log was a 0-byte file. Owner
#      could not set or recover a PIN.
#      → migrate-security-init.sh now repairs perms on re-run.
#   4. /api/nft-list-detailed auto-prunes stale hidden-nfts.json entries
#      whose underlying files don't exist (caused View Art → add.html
#      redirect when re-downloaded CIDs inherited old hide flags).
#      → app.py
#   5. Bluetooth pairing: agent now defers confirm 18s so PC's BT dialog
#      stays open long enough for the user to click Pair.
#      → bt-pairing-agent.py (restart bt-agent.service)
#   6. Connect UX: larger font sizes for QR URL/hint and "More connection
#      options" link.  → connect.html, index.html
#
# Credentials live in ../secrets.env (gitignored). Never committed inline.
#
# Usage:
#   bash tools/deploy-fleet-fixes.sh                  # all reachable
#   bash tools/deploy-fleet-fixes.sh afrol vernis2    # only listed
#   DRY_RUN=1 bash tools/deploy-fleet-fixes.sh        # preview
##############################################################################
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SECRETS_ENV="$REPO_ROOT/secrets.env"
ROOT="$REPO_ROOT/audit-package"
KIOSK_SRC="$ROOT/scripts/kiosk-launcher.sh"
WATCHDOG_SRC="$ROOT/scripts/watchdog.sh"
APP_SRC="$ROOT/backend/app.py"
MIGRATE_SRC="$ROOT/scripts/migrate-security-init.sh"
BT_AGENT_SRC="$ROOT/scripts/bt-pairing-agent.py"
CONNECT_SRC="$ROOT/connect.html"
INDEX_SRC="$ROOT/index.html"
LIBRARY_SRC="$ROOT/library.html"
SPLASH_SRC="$ROOT/assets/vernis-plymouth-splash.png"
SPLASH_MD5="8258057988eb4aaf8914661f18a87b57"

[ -f "$SECRETS_ENV" ] || {
    echo "❌ $SECRETS_ENV not found. Copy secrets.env.template and fill in" >&2
    echo "   device passwords (or run tools/rotate-device-passwords.sh)." >&2
    exit 1
}
set -a
# shellcheck disable=SC1090
. "$SECRETS_ENV"
set +a

for src in "$KIOSK_SRC" "$WATCHDOG_SRC" "$APP_SRC" "$MIGRATE_SRC" \
           "$BT_AGENT_SRC" "$CONNECT_SRC" "$INDEX_SRC" "$LIBRARY_SRC" \
           "$SPLASH_SRC"; do
    [ -f "$src" ] || { echo "❌ $src missing"; exit 1; }
done

# Defensive: the splash check below relies on a stable known-good md5. If
# the file in the repo changes, update SPLASH_MD5 above to match.
actual_md5=$(md5 -q "$SPLASH_SRC" 2>/dev/null || md5sum "$SPLASH_SRC" 2>/dev/null | awk '{print $1}')
[ "$actual_md5" = "$SPLASH_MD5" ] || \
    { echo "❌ $SPLASH_SRC md5 ($actual_md5) != $SPLASH_MD5 — update SPLASH_MD5"; exit 1; }
command -v sshpass >/dev/null || { echo "❌ install sshpass"; exit 1; }

# Sanity-check sources contain the fixes (not the buggy patterns)
grep -q "http://localhost/\$START_PAGE" "$KIOSK_SRC" && \
    { echo "❌ $KIOSK_SRC still has http://localhost — aborting"; exit 1; }
grep -q "127.0.0.1/index.html" "$WATCHDOG_SRC" || \
    { echo "❌ $WATCHDOG_SRC missing 127.0.0.1 URL — aborting"; exit 1; }
grep -qE '"tls " in content or ":443" in content' "$APP_SRC" && \
    { echo "❌ $APP_SRC has old https substring check — aborting"; exit 1; }
grep -q '("tls " + CERT_PATH) in content' "$APP_SRC" || \
    { echo "❌ $APP_SRC missing CERT_PATH check — aborting"; exit 1; }
grep -q "cleaned = \[name for name in hidden if name in present\]" "$APP_SRC" || \
    { echo "❌ $APP_SRC missing hidden-nfts auto-prune — aborting"; exit 1; }
grep -q '"/api/reboot",' "$APP_SRC" || \
    { echo "❌ $APP_SRC missing /api/reboot in _DELETE_EXACT (shutdown/reboot auth fix) — aborting"; exit 1; }
grep -q '"/api/shutdown",' "$APP_SRC" || \
    { echo "❌ $APP_SRC missing /api/shutdown in _DELETE_EXACT (shutdown/reboot auth fix) — aborting"; exit 1; }
grep -q "CONFIRM_DELAY_MS = 18000" "$BT_AGENT_SRC" || \
    { echo "❌ $BT_AGENT_SRC missing 18s delay — aborting"; exit 1; }
grep -q 'fix_perms "$SECURITY_FILE" 0600' "$MIGRATE_SRC" || \
    { echo "❌ $MIGRATE_SRC missing perm-repair logic — aborting"; exit 1; }
grep -q 'fix_data_dirs' "$MIGRATE_SRC" || \
    { echo "❌ $MIGRATE_SRC missing data-dir repair — aborting"; exit 1; }
grep -q "font-size:30px" "$INDEX_SRC" || \
    { echo "❌ $INDEX_SRC missing 30px font fix — aborting"; exit 1; }
grep -q "Queued — waiting for" "$LIBRARY_SRC" || \
    { echo "❌ $LIBRARY_SRC missing multi-card source_csv guard — aborting"; exit 1; }

# ── Fleet inventory ───────────────────────────────────────────────────────
# Passwords come from $VERNIS_PASS_<name> in secrets.env.
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

FILTER=("$@")
match_filter() {
    [ ${#FILTER[@]} -eq 0 ] && return 0
    local name="$1"
    for f in "${FILTER[@]}"; do [ "$f" = "$name" ] && return 0; done
    return 1
}

deploy_one() {
    local USER="$1" IP="$2"
    local PASS_VAR="VERNIS_PASS_$USER"
    local PASS="${!PASS_VAR:-}"
    if [ -z "$PASS" ]; then
        echo
        echo "════════ $USER ($IP) ════════"
        echo "  ⚠  no password in secrets.env (VERNIS_PASS_$USER) — skipping"
        return 0
    fi
    # SSH multiplexing — one TCP session shared across all the curl/scp/ssh
    # calls below. Critical because the hardened devices' ufw uses `limit`
    # on port 22, which trips after ~6 connections in 30s. Without this,
    # the deploy reliably fails partway through.
    local CTRL_DIR="${TMPDIR:-/tmp}/vernis-deploy.$$"
    mkdir -p "$CTRL_DIR"; chmod 700 "$CTRL_DIR"
    local CTRL_PATH="$CTRL_DIR/%h-%p-%r"
    local SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
                    -o LogLevel=ERROR -o ConnectTimeout=8
                    -o ControlMaster=auto -o "ControlPath=$CTRL_PATH"
                    -o ControlPersist=120s)

    echo
    echo "════════ $USER ($IP) ════════"

    if ! sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" "echo alive" >/dev/null 2>&1; then
        echo "  ⏭️  offline — skipping"
        return 0
    fi

    # Pre-state
    local CUR_URL CUR_HTTPS CUR_SECURITY_OWNER
    CUR_URL=$(sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" \
        "curl -s http://localhost:9222/json 2>/dev/null \
         | python3 -c 'import json,sys;\
            t=[p for p in json.load(sys.stdin) if p.get(\"type\")==\"page\"];\
            print(t[0].get(\"url\",\"\") if t else \"\")' 2>/dev/null" 2>/dev/null)
    CUR_HTTPS=$(sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" \
        "curl -s http://localhost:5000/api/https 2>/dev/null" 2>/dev/null)
    CUR_SECURITY_OWNER=$(sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" \
        "stat -c '%U' /opt/vernis/security.json 2>/dev/null || echo missing" 2>/dev/null)
    echo "  tab:               ${CUR_URL:-<no CDP>}"
    echo "  /api/https:        ${CUR_HTTPS:-<no response>}"
    echo "  security.json own: $CUR_SECURITY_OWNER"

    if [ "${DRY_RUN:-0}" = "1" ]; then
        echo "  [DRY_RUN] would push 7 files + run migrate + restart 3 services"
        return 0
    fi

    # scp every file in one batch
    sshpass -p "$PASS" scp "${SSH_OPTS[@]}" \
        "$KIOSK_SRC" "$WATCHDOG_SRC" "$APP_SRC" "$MIGRATE_SRC" \
        "$BT_AGENT_SRC" "$CONNECT_SRC" "$INDEX_SRC" "$LIBRARY_SRC" \
        "$SPLASH_SRC" \
        "$USER@$IP":/tmp/ >/dev/null || \
        { echo "  ❌ scp failed"; return 1; }

    # Install + restart everything in one sudo block
    sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" "echo '$PASS' | sudo -S bash -c '
        set -e
        # Syntax-check app.py and bt-pairing-agent.py before overwriting
        python3 -m py_compile /tmp/app.py             || { echo PYCOMPILE_FAIL_APP;   exit 2; }
        python3 -m py_compile /tmp/bt-pairing-agent.py|| { echo PYCOMPILE_FAIL_AGENT; exit 2; }

        # Backups (idempotent — only first run)
        [ ! -f /opt/vernis/scripts/kiosk-launcher.sh.pre-localhost-fix ] && \
          cp /opt/vernis/scripts/kiosk-launcher.sh /opt/vernis/scripts/kiosk-launcher.sh.pre-localhost-fix 2>/dev/null
        [ ! -f /opt/vernis/scripts/watchdog.sh.pre-localhost-fix ] && \
          cp /opt/vernis/scripts/watchdog.sh /opt/vernis/scripts/watchdog.sh.pre-localhost-fix 2>/dev/null
        [ ! -f /opt/vernis/app.py.pre-https-fix ] && \
          cp /opt/vernis/app.py /opt/vernis/app.py.pre-https-fix 2>/dev/null
        [ ! -f /opt/vernis/scripts/bt-pairing-agent.py.pre-confirm-delay ] && \
          cp /opt/vernis/scripts/bt-pairing-agent.py /opt/vernis/scripts/bt-pairing-agent.py.pre-confirm-delay 2>/dev/null
        [ ! -f /var/www/vernis/connect.html.pre-fontsize ] && \
          cp /var/www/vernis/connect.html /var/www/vernis/connect.html.pre-fontsize 2>/dev/null
        [ ! -f /var/www/vernis/index.html.pre-fontsize ] && \
          cp /var/www/vernis/index.html /var/www/vernis/index.html.pre-fontsize 2>/dev/null

        # /opt/vernis/* — owned by Flask user
        cp /tmp/kiosk-launcher.sh      /opt/vernis/scripts/kiosk-launcher.sh
        cp /tmp/watchdog.sh            /opt/vernis/scripts/watchdog.sh
        cp /tmp/app.py                 /opt/vernis/app.py
        cp /tmp/bt-pairing-agent.py    /opt/vernis/scripts/bt-pairing-agent.py
        cp /tmp/migrate-security-init.sh /opt/vernis/scripts/migrate-security-init.sh
        chown $USER:$USER /opt/vernis/scripts/kiosk-launcher.sh /opt/vernis/scripts/watchdog.sh \
                          /opt/vernis/app.py /opt/vernis/scripts/bt-pairing-agent.py \
                          /opt/vernis/scripts/migrate-security-init.sh
        chmod +x /opt/vernis/scripts/kiosk-launcher.sh /opt/vernis/scripts/watchdog.sh \
                 /opt/vernis/scripts/migrate-security-init.sh

        # /var/www/vernis/* — owned by caddy
        cp /tmp/connect.html /var/www/vernis/connect.html
        cp /tmp/index.html   /var/www/vernis/index.html
        cp /tmp/library.html /var/www/vernis/library.html
        chown caddy:caddy /var/www/vernis/connect.html /var/www/vernis/index.html /var/www/vernis/library.html

        # Plymouth boot splash repair. Past provisioning was inconsistent:
        # some devices got the upright (unrotated) splash.png installed,
        # and some had Theme=pix (Pi default) instead of Theme=vernis. The
        # display panel is mounted rotated 90deg, so the wrong content/
        # theme makes the boot logo appear sideways or as Pi branding.
        # Repair both, only rebuilding initramfs if something actually
        # changed (initramfs rebuild is the slow step ~30s).
        plymouth_changed=0
        # 1. splash.png md5 check — avoid awk/cut/sed (their single quotes
        # would break the outer single-quoted bash -c body). Use bash
        # parameter expansion to strip everything after the first space.
        cur_md5_line=\$(md5sum /usr/share/plymouth/themes/vernis/splash.png 2>/dev/null)
        cur_md5=\${cur_md5_line%% *}
        if [ ! -f /usr/share/plymouth/themes/vernis/splash.png ] || \
           [ \"\$cur_md5\" != \"$SPLASH_MD5\" ]; then
            [ ! -f /usr/share/plymouth/themes/vernis/splash.png.pre-rotate-fix ] && \
                [ -f /usr/share/plymouth/themes/vernis/splash.png ] && \
                cp /usr/share/plymouth/themes/vernis/splash.png /usr/share/plymouth/themes/vernis/splash.png.pre-rotate-fix
            mkdir -p /usr/share/plymouth/themes/vernis
            cp /tmp/vernis-plymouth-splash.png /usr/share/plymouth/themes/vernis/splash.png
            plymouth_changed=1
            echo plymouth splash updated
        fi
        # 2. Theme=vernis check (use grep -F to avoid regex chars and -x to anchor)
        if ! grep -qFx Theme=vernis /etc/plymouth/plymouthd.conf 2>/dev/null; then
            plymouth-set-default-theme vernis >/dev/null
            plymouth_changed=1
            echo plymouth theme set to vernis
        fi
        # 3. Single initramfs rebuild only if needed
        if [ \"\$plymouth_changed\" = 1 ]; then
            update-initramfs -u >/dev/null 2>&1 || true
        fi

        # Repair security file ownership/perms (the critical PIN bug),
        # OR initialize security.json on fresh devices.
        # INSTALL_USER_PASSWORD is needed when security.json does not exist
        # (the script creates the bcrypt owner_pwd_hash from it). When the
        # file already exists, the var is ignored — script just fixes perms.
        # Safe: alphanumeric-only passwords (per rotator), no special chars.
        INSTALL_USER_PASSWORD=$PASS bash /opt/vernis/scripts/migrate-security-init.sh

        # Auto-prune stale hidden-nfts.json entries whose files do not exist.
        # Belt-and-suspenders: the app.py patch does this on every list-detailed
        # read, but a one-time cleanup here saves the first page-load latency.
        python3 - <<PYEOF
import json, os
HID = \"/opt/vernis/hidden-nfts.json\"
NFTDIR = \"/opt/vernis/nfts/\"
try:
    h = json.load(open(HID))
    present = set(os.listdir(NFTDIR))
    cleaned = [n for n in h if n in present]
    if len(cleaned) != len(h):
        json.dump(cleaned, open(HID, \"w\"))
        print(f\"hidden-nfts pruned: {len(h)} -> {len(cleaned)}\")
except Exception as e:
    print(f\"hidden-nfts skip: {e}\")
PYEOF

        # Restart services. bt-agent first (independent), then API, then watchdog.
        systemctl restart bt-agent.service 2>/dev/null || true
        systemctl restart vernis-api
        systemctl restart vernis-watchdog.service

        # Kick chromium so it relaunches under the new kiosk-launcher.sh.
        # Detach so SSH session is not dropped when chromium dies.
        nohup setsid bash -c \"
          sleep 1
          pkill -f /usr/lib/chromium/chromium 2>/dev/null
          sleep 2
          pkill -9 -f /usr/lib/chromium/chromium 2>/dev/null
        \" >/dev/null 2>&1 < /dev/null &
        disown 2>/dev/null || true
    '" 2>&1 | grep -vE 'sudo|\[sudo' | tail -8
    [ "${PIPESTATUS[0]}" = "0" ] || { echo "  ❌ install/restart failed"; return 1; }

    # Verify
    local NEW_URL="" NEW_HTTPS="" NEW_SECURITY_OWNER=""
    for _ in $(seq 1 30); do
        sleep 2
        NEW_URL=$(sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" \
            "curl -s http://localhost:9222/json 2>/dev/null \
             | python3 -c 'import json,sys;\
                t=[p for p in json.load(sys.stdin) if p.get(\"type\")==\"page\"];\
                print(t[0].get(\"url\",\"\") if t else \"\")' 2>/dev/null" 2>/dev/null)
        [ -n "$NEW_URL" ] && break
    done

    for _ in 1 2 3 4 5; do
        sleep 1
        NEW_HTTPS=$(sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" \
            "curl -s http://localhost:5000/api/https 2>/dev/null" 2>/dev/null)
        [ -n "$NEW_HTTPS" ] && break
    done

    NEW_SECURITY_OWNER=$(sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" \
        "stat -c '%U' /opt/vernis/security.json 2>/dev/null" 2>/dev/null)

    # Plymouth state: ok if splash md5 matches AND theme is vernis
    local NEW_SPLASH_MD5 NEW_PLY_THEME
    NEW_SPLASH_MD5=$(sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" \
        "sudo md5sum /usr/share/plymouth/themes/vernis/splash.png 2>/dev/null | awk '{print \$1}'" 2>/dev/null)
    NEW_PLY_THEME=$(sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "$USER@$IP" \
        "sudo grep '^Theme=' /etc/plymouth/plymouthd.conf 2>/dev/null | head -1" 2>/dev/null)

    local STATUS_KIOSK=fail STATUS_HTTPS=fail STATUS_SEC=fail STATUS_PLY=fail
    echo "$NEW_URL"             | grep -q "127.0.0.1"        && STATUS_KIOSK=ok
    echo "$NEW_HTTPS"           | grep -qE '"enabled":(true|false)' && STATUS_HTTPS=ok
    [ "$NEW_SECURITY_OWNER" = "$USER" ]                      && STATUS_SEC=ok
    [ "$NEW_SPLASH_MD5" = "$SPLASH_MD5" ] && [ "$NEW_PLY_THEME" = "Theme=vernis" ] && STATUS_PLY=ok

    local TAG_K="✅" TAG_H="✅" TAG_S="✅" TAG_P="✅"
    [ "$STATUS_KIOSK" = "ok" ] || TAG_K="❌"
    [ "$STATUS_HTTPS" = "ok" ] || TAG_H="❌"
    [ "$STATUS_SEC"   = "ok" ] || TAG_S="❌"
    [ "$STATUS_PLY"   = "ok" ] || TAG_P="❌"
    echo "  $TAG_K kiosk tab:       ${NEW_URL:-<no CDP after 60s>}"
    echo "  $TAG_H /api/https:      ${NEW_HTTPS:-<no response>}"
    echo "  $TAG_S security.json:   owned by $NEW_SECURITY_OWNER (want $USER)"
    echo "  $TAG_P plymouth:        $NEW_PLY_THEME, splash md5 ${NEW_SPLASH_MD5:0:8}…"

    local result=0
    [ "$STATUS_KIOSK" = "ok" ] && [ "$STATUS_HTTPS" = "ok" ] && [ "$STATUS_SEC" = "ok" ] && [ "$STATUS_PLY" = "ok" ] || result=1

    # Close the SSH master so ports clean up immediately for the next device
    ssh -O exit -o "ControlPath=$CTRL_PATH" "$USER@$IP" 2>/dev/null || true
    rm -rf "$CTRL_DIR"
    return $result
}

ok=0; failed=0
for row in "${FLEET[@]}"; do
    IFS='|' read -r name ip <<< "$row"
    name=$(echo "$name" | xargs); ip=$(echo "$ip" | xargs)
    if ! match_filter "$name"; then continue; fi
    if deploy_one "$name" "$ip"; then ok=$((ok+1)); else failed=$((failed+1)); fi
done

echo
echo "════════ Summary ════════"
echo "  ok:      $ok"
echo "  failed:  $failed"
echo "  ${DRY_RUN:+(DRY_RUN — no changes made)}"
