#!/bin/bash
##############################################
# Vernis - Update an ALREADY-INSTALLED device to the latest code.
#
# Pushes: web UI, backend/app.py, scripts/, csv-library/, hardened
# Caddyfile, vernis-api unit + sudoers, then runs the security
# migration and restarts services.
#
# Deliberately does NOT touch (device-specific, set at install time):
#   - /boot/firmware/config.txt or display overlays
#   - dpi-backlight.service (must stay disabled - corrupts GPIO 18)
#   - labwc autostart / kiosk setup
#
# For fresh installs use install-vernis.sh / deploy-to-pi.sh instead.
#
# Usage: bash update-deployed-pi.sh <username> <host> <password> [--reboot]
##############################################

set -e

if [ "$#" -lt 3 ]; then
    echo "Usage: bash update-deployed-pi.sh <username> <host> <password> [--reboot]"
    echo "Example: bash update-deployed-pi.sh vernis2 vernis2.local 'pass' --reboot"
    exit 1
fi

PI_USER="$1"
PI_HOST="$2"
PI_PASS="$3"
DO_REBOOT="${4:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if ! command -v sshpass &> /dev/null; then
    echo "sshpass not found. Install with: brew install hudochenkov/sshpass/sshpass"
    exit 1
fi

SSH=(sshpass -p "$PI_PASS" ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$PI_USER@$PI_HOST")

echo "=== Vernis update: $PI_USER@$PI_HOST ==="

echo "[1/4] Testing connection..."
if ! "${SSH[@]}" hostname; then
    echo ""
    echo "Could not reach $PI_HOST."
    echo "  1. Is this Mac on the SAME network as the Pi (VF hotspot)?"
    echo "  2. Try: ping ${PI_USER}.local"
    echo "  3. Find the Pi by scanning (replace 192.168.1 with your subnet):"
    echo "     for i in \$(seq 1 254); do (ping -c1 -W300 -t1 192.168.1.\$i >/dev/null 2>&1 &); done; sleep 4; arp -a | grep -v incomplete"
    echo "     then re-run this script with the IP instead of the hostname."
    exit 1
fi

echo "[2/4] Staging files..."
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/web" "$STAGE/backend" "$STAGE/scripts" "$STAGE/csv-library" "$STAGE/conf" "$STAGE/wheels"

cd "$PROJECT_DIR"
for f in *.html *.css *.js *.svg *.webmanifest version.json; do
    [ -f "$f" ] && cp "$f" "$STAGE/web/"
done
cp backend/app.py backend/curator.py backend/curator_claude.py "$STAGE/backend/"
for f in scripts/*.sh scripts/*.py scripts/*.c scripts/*.dts; do
    [ -f "$f" ] && cp "$f" "$STAGE/scripts/"
done
for f in csv-library/*.csv; do
    [ -f "$f" ] && cp "$f" "$STAGE/csv-library/"
done
# Offline pip wheels (bcrypt for the security system - app.py hard-imports it).
# Refresh with: python3 -m pip download bcrypt --only-binary=:all: \
#   --platform manylinux2014_aarch64 --python-version 311 -d scripts/offline-wheels/
for f in "$SCRIPT_DIR"/offline-wheels/*.whl; do
    [ -f "$f" ] && cp "$f" "$STAGE/wheels/"
done

# Hardened Caddyfile - keep in sync with install-vernis.sh
cat > "$STAGE/conf/Caddyfile" << 'EOF'
{
    auto_https off
}

http://localhost, :80 {
    root * /var/www/vernis
    file_server

    # IMPORTANT: no trusted_proxies — Caddy is the only proxy. Without
    # this directive, Caddy ignores any client-supplied X-Forwarded-For
    # and overrides it with the real client IP, so a LAN attacker can't
    # spoof their source as 127.0.0.1 to bypass kiosk trust.
    reverse_proxy /api/* localhost:5000 {
        header_up X-Forwarded-For {client_ip}
        header_up X-Real-IP {client_ip}
    }
    reverse_proxy /nfts/* localhost:5000 {
        header_up X-Forwarded-For {client_ip}
        header_up X-Real-IP {client_ip}
    }
    reverse_proxy /nfts-ext/* localhost:5000 {
        header_up X-Forwarded-For {client_ip}
        header_up X-Real-IP {client_ip}
    }

    encode gzip

    header {
        Cache-Control "no-cache, no-store, must-revalidate"
    }
}
EOF

# vernis-api unit - keep in sync with install-vernis.sh
cat > "$STAGE/conf/vernis-api.service" << 'EOF'
[Unit]
Description=Vernis Flask API
# remote-fs.target: start after fstab network mounts (CIFS/NFS external
# storage) are attempted, so the NFT library isn't missing at boot
After=network-online.target remote-fs.target
Wants=network-online.target

[Service]
Type=simple
User=__VERNIS_USER__
WorkingDirectory=/opt/vernis
ExecStart=/usr/bin/python3 /opt/vernis/app.py
Restart=always
RestartSec=5
Environment=FLASK_ENV=production
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF

# sudoers - keep in sync with install-vernis.sh (fan control needs the tee rules)
cat > "$STAGE/conf/vernis-api.sudoers" << 'EOF'
# Vernis API — limited sudo for specific operations
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /sbin/reboot
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /sbin/shutdown
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart vernis-*
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart caddy
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart ipfs
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart hciuart
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart bluetooth
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/systemctl start vernis-*
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop vernis-*
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/systemctl status *
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/apt update
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/apt upgrade -y
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/sbin/ufw *
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/nmcli *
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/tee /sys/class/thermal/*
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/tee /sys/devices/platform/*
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/tee /boot/firmware/config.txt
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/tee /boot/config.txt
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/tee /boot/firmware/cmdline.txt
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/tee /boot/cmdline.txt
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/sbin/badblocks *
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/dpkg *
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/apt-mark *
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/bluetoothctl *
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/brctl *
__VERNIS_USER__ ALL=(ALL) NOPASSWD: /usr/bin/dnsmasq *
EOF

# Remote installer - runs as root on the Pi
cat > "$STAGE/remote-install.sh" << 'EOF'
#!/bin/bash
set -e
U="$1"
SRC="/tmp/vernis-update"

echo "--- [1/8] Web files -> /var/www/vernis"
mkdir -p /var/www/vernis
cp "$SRC"/web/* /var/www/vernis/
chown -R "$U:$U" /var/www/vernis

echo "--- [2/8] Backend + scripts + CSV library -> /opt/vernis"
mkdir -p /opt/vernis/scripts /opt/vernis/csv-library
cp /opt/vernis/app.py /opt/vernis/app.py.pre-update 2>/dev/null || true
cp "$SRC"/backend/app.py /opt/vernis/app.py
cp "$SRC"/backend/curator.py "$SRC"/backend/curator_claude.py /opt/vernis/
cp "$SRC"/scripts/* /opt/vernis/scripts/
chmod +x /opt/vernis/scripts/*.sh /opt/vernis/scripts/*.py 2>/dev/null || true
if ls "$SRC"/csv-library/*.csv > /dev/null 2>&1; then
    cp "$SRC"/csv-library/*.csv /opt/vernis/csv-library/
fi
chown "$U:$U" /opt/vernis/app.py /opt/vernis/curator.py /opt/vernis/curator_claude.py
chown -R "$U:$U" /opt/vernis/scripts /opt/vernis/csv-library

echo "--- [3/8] Hardened Caddyfile"
install -m 644 "$SRC/conf/Caddyfile" /etc/caddy/Caddyfile

echo "--- [4/8] vernis-api unit + sudoers"
sed "s/__VERNIS_USER__/$U/g" "$SRC/conf/vernis-api.service" > /etc/systemd/system/vernis-api.service
sed "s/__VERNIS_USER__/$U/g" "$SRC/conf/vernis-api.sudoers" > "$SRC/sudoers.tmp"
visudo -c -f "$SRC/sudoers.tmp"
install -m 440 "$SRC/sudoers.tmp" /etc/sudoers.d/vernis-api
# Old updater.sh runs copied systemd/vernis-watchdog.service with User=pi,
# which crash-loops (status=217/USER) on devices without a pi account
if [ -f /etc/systemd/system/vernis-watchdog.service ]; then
    sed -i "s/^User=.*/User=$U/" /etc/systemd/system/vernis-watchdog.service
fi
systemctl daemon-reload

echo "--- [5/8] Fix root-owned state files"
find /opt/vernis -maxdepth 1 -type f -name '*.json' -user root -exec chown "$U:$U" {} + 2>/dev/null || true

echo "--- [6/8] Ensure bcrypt (app.py hard-imports it; offline wheel first)"
if ! python3 -c 'import bcrypt' 2>/dev/null; then
    if ls "$SRC"/wheels/*.whl > /dev/null 2>&1; then
        pip3 install --no-index --find-links "$SRC/wheels" bcrypt --break-system-packages
    else
        pip3 install bcrypt --break-system-packages
    fi
fi
if ! python3 -c 'import bcrypt' 2>/dev/null; then
    echo "FATAL: bcrypt unavailable - restoring previous app.py so Flask keeps working"
    [ -f /opt/vernis/app.py.pre-update ] && cp /opt/vernis/app.py.pre-update /opt/vernis/app.py
    systemctl restart vernis-api
    exit 1
fi

# ffmpeg makes video and AVIF thumbnails. Optional: never fail the update for it
if ! command -v ffmpeg > /dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ffmpeg || \
        echo "WARNING: ffmpeg not installed - video/AVIF thumbnails use a fallback"
fi

echo "--- [7/8] Security migration (idempotent)"
bash /opt/vernis/scripts/migrate-security-init.sh || \
    echo "WARNING: migration failed - re-run later: INSTALL_USER_PASSWORD='<pwd>' sudo -E bash /opt/vernis/scripts/migrate-security-init.sh"

echo "--- [8/8] Restart + verify"
systemctl reload-or-restart caddy
systemctl restart vernis-api
sleep 3
echo "vernis-api: $(systemctl is-active vernis-api)"
echo "caddy:      $(systemctl is-active caddy)"
curl -fsS -m 5 -o /dev/null -w "web:  HTTP %{http_code}\n" http://localhost/ || echo "web:  FAILED"
curl -fsS -m 5 -o /dev/null -w "api:  HTTP %{http_code}\n" http://localhost/api/nft-metadata || echo "api:  FAILED"
EOF

echo "[3/4] Uploading to Pi..."
tar czf - -C "$STAGE" . | "${SSH[@]}" "rm -rf /tmp/vernis-update && mkdir -p /tmp/vernis-update && tar xzf - -C /tmp/vernis-update"

echo "[4/4] Installing on Pi..."
printf '%s\n' "$PI_PASS" | "${SSH[@]}" "sudo -S -p '' env INSTALL_USER_PASSWORD='$PI_PASS' bash /tmp/vernis-update/remote-install.sh '$PI_USER'"

"${SSH[@]}" "rm -rf /tmp/vernis-update"

echo ""
echo "=== Update complete: http://$PI_HOST ==="

if [ "$DO_REBOOT" = "--reboot" ]; then
    echo "Rebooting Pi (refreshes kiosk UI)..."
    printf '%s\n' "$PI_PASS" | "${SSH[@]}" "sudo -S -p '' reboot" || true
else
    echo "Note: kiosk browser still shows the old UI until reboot/reload."
    echo "Reboot with: sshpass -p '<pass>' ssh $PI_USER@$PI_HOST 'sudo reboot'"
fi
