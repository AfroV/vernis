#!/bin/bash
# Vernis Device Health Check
# Usage: bash check-device-health.sh [device_ip] [username] [password]
# Or run without args to check all known devices

check_device() {
    local IP="$1"
    local USER="$2"
    local PASS="$3"
    local NAME="$USER"

    echo "=== $NAME ($IP) ==="

    # Check connectivity
    if ! sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$USER@$IP" "echo OK" >/dev/null 2>&1; then
        echo "  OFFLINE"
        echo ""
        return
    fi

    sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$USER@$IP" "
        # --- Files ---
        echo '  [Files]'
        echo -n '  app.py: '; md5sum /opt/vernis/app.py 2>/dev/null | awk '{print \$1}'
        echo -n '  gallery.html: '; md5sum /var/www/vernis/gallery.html 2>/dev/null | awk '{print \$1}'
        echo -n '  index.html: '; md5sum /var/www/vernis/index.html 2>/dev/null | awk '{print \$1}'
        echo -n '  library.html: '; md5sum /var/www/vernis/library.html 2>/dev/null | awk '{print \$1}'
        echo -n '  settings.html: '; md5sum /var/www/vernis/settings.html 2>/dev/null | awk '{print \$1}'
        echo -n '  nft_downloader_advanced.py: '; md5sum /opt/vernis/scripts/nft_downloader_advanced.py 2>/dev/null | awk '{print \$1}'
        echo -n '  kiosk-launcher.sh: '; md5sum /opt/vernis/scripts/kiosk-launcher.sh 2>/dev/null | awk '{print \$1}'
        echo -n '  install-vernis.sh: '; md5sum /opt/vernis/scripts/install-vernis.sh 2>/dev/null | awk '{print \$1}'

        # --- Service Config ---
        echo '  [Service]'
        echo -n '  User: '; grep '^User=' /etc/systemd/system/vernis-api.service 2>/dev/null || echo 'MISSING'
        echo -n '  NoNewPrivileges: '; grep -o 'NoNewPrivileges=[a-z]*' /etc/systemd/system/vernis-api.service 2>/dev/null || echo 'NOT SET'
        echo -n '  Service running: '; systemctl is-active vernis-api 2>/dev/null

        # --- Sudoers ---
        echo '  [Sudoers]'
        SUDOERS_COUNT=\$(sudo cat /etc/sudoers.d/vernis 2>/dev/null | wc -l)
        echo \"  Entries: \$SUDOERS_COUNT\"
        echo -n '  reboot: '; sudo cat /etc/sudoers.d/vernis 2>/dev/null | grep -c '/sbin/reboot'
        echo -n '  shutdown: '; sudo cat /etc/sudoers.d/vernis 2>/dev/null | grep -c '/sbin/shutdown'
        echo -n '  systemctl: '; sudo cat /etc/sudoers.d/vernis 2>/dev/null | grep -c 'systemctl'
        echo -n '  nmcli: '; sudo cat /etc/sudoers.d/vernis 2>/dev/null | grep -c 'nmcli'
        echo -n '  tee boot: '; sudo cat /etc/sudoers.d/vernis 2>/dev/null | grep -c 'tee /boot'
        echo -n '  tee thermal: '; sudo cat /etc/sudoers.d/vernis 2>/dev/null | grep -c 'tee /sys'
        echo -n '  chpasswd: '; sudo cat /etc/sudoers.d/vernis 2>/dev/null | grep -c 'chpasswd'
        echo -n '  bash scripts: '; sudo cat /etc/sudoers.d/vernis 2>/dev/null | grep -c 'bash /opt/vernis'

        # --- Display ---
        echo '  [Display]'
        echo -n '  Rotation: '; cat /opt/vernis/rotation-config.json 2>/dev/null
        echo ''
        echo -n '  Transform: '; wlr-randr 2>/dev/null | grep Transform | awk '{print \$2}'
        echo -n '  dpi-backlight: '; systemctl is-enabled dpi-backlight 2>/dev/null || echo 'not found'

        # --- Config Files ---
        echo '  [Config Integrity]'
        CORRUPTED=0
        for f in /opt/vernis/display-config.json /opt/vernis/display-output-config.json /opt/vernis/fan-config.json /opt/vernis/setup-complete.json /opt/vernis/rotation-config.json; do
            if [ -f \"\$f\" ]; then
                if ! head -c 1 \"\$f\" | grep -q '{'; then
                    echo \"  CORRUPTED: \$(basename \$f)\"
                    CORRUPTED=\$((CORRUPTED+1))
                fi
            fi
        done
        if [ \$CORRUPTED -eq 0 ]; then echo '  All JSON configs OK'; fi
        echo -n '  config.txt password junk: '; grep -cE '^0x[0-9a-fA-F]{10,}$' /boot/firmware/config.txt 2>/dev/null

        # --- WiFi ---
        echo '  [WiFi]'
        echo -n '  Power save: '; iw wlan0 get power_save 2>/dev/null | awk '{print \$3}' || echo 'unknown'
        echo -n '  Persistent off: '; [ -f /etc/NetworkManager/conf.d/wifi-powersave.conf ] && echo 'yes' || echo 'no'

        # --- Boot Config ---
        echo '  [Boot Config]'
        echo -n '  over_voltage: '; grep '^over_voltage' /boot/firmware/config.txt 2>/dev/null || echo 'not set'
        echo -n '  arm_freq: '; grep '^arm_freq=' /boot/firmware/config.txt 2>/dev/null || echo 'not set'
        echo -n '  DPI overlays: '; grep -c 'DPI\|waveshare' /boot/firmware/config.txt 2>/dev/null

        # --- System ---
        echo '  [System]'
        echo -n '  Load: '; cat /proc/loadavg | awk '{print \$1, \$2, \$3}'
        echo -n '  Temp: '; cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null | awk '{printf \"%.1f°C\n\", \$1/1000}'
        echo -n '  IPFS peers: '; ipfs swarm peers 2>/dev/null | wc -l
        echo -n '  NFT files: '; ls /opt/vernis/nfts/ 2>/dev/null | grep -v '\.json$' | wc -l
    " 2>&1
    echo ""
}

# Credentials live in ../secrets.env (gitignored). Never inlined here.
SECRETS_ENV="$(cd "$(dirname "$0")/.." && pwd)/secrets.env"
[ -f "$SECRETS_ENV" ] || { echo "❌ $SECRETS_ENV missing — copy secrets.env.template" >&2; exit 1; }
set -a; . "$SECRETS_ENV"; set +a

# Default devices: <ip> <user>. Password comes from $VERNIS_PASS_<user>.
DEVICES=(
    "10.0.0.40 vernis1"
    "10.0.0.41 vernis2"
    "10.0.0.43 vernis3"
    "10.0.0.44 vernis4"
    "10.0.0.45 vernis5"
    "10.0.0.42 vernis6"
    "10.0.0.46 vernis7"
    "10.0.0.28 afrol"
    "10.0.0.39 afrom"
)

resolve_pass() {
    local user="$1"
    local var="VERNIS_PASS_$user"
    printf '%s' "${!var:-}"
}

if [ -n "$1" ]; then
    USER="${2:-vernis}"
    PASS="${3:-$(resolve_pass "$USER")}"
    [ -n "$PASS" ] || { echo "❌ no password for $USER (set VERNIS_PASS_$USER in secrets.env)" >&2; exit 1; }
    check_device "$1" "$USER" "$PASS"
else
    echo "Vernis Device Health Check — $(date)"
    echo "========================================"
    echo ""
    for entry in "${DEVICES[@]}"; do
        read -r ip user <<< "$entry"
        pass=$(resolve_pass "$user")
        if [ -z "$pass" ]; then
            echo "── $user ($ip): no password in secrets.env (VERNIS_PASS_$user) ──"; echo
            continue
        fi
        check_device "$ip" "$user" "$pass"
    done
fi
