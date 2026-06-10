#!/bin/bash
##############################################################################
# Vernis — Public-IPFS-Node Hardening Script
#
# Applies firewall, IPFS, and systemd hardening for a Vernis Pi operating
# as a full public IPFS node (port 4001 open) while restricting the admin
# web UI to the local network.
#
# Idempotent. Run as root.
#
# Usage:
#   sudo bash harden-public-node.sh                # auto-detect LAN CIDR
#   sudo VERNIS_LAN_CIDR=192.168.1.0/24 bash harden-public-node.sh
#   sudo VERNIS_NETWORK_MODE=private bash harden-public-node.sh
#
# Env vars:
#   VERNIS_LAN_CIDR       LAN range that may reach admin web + SSH
#   VERNIS_NETWORK_MODE   "public" (default) or "private" — private mode
#                         omits the 4001 ufw allow rule
#
# Exit codes:
#   0  success
#   1  precondition failed (not root, kubo not installed, etc.)
#   2  ufw could not be enabled
#   3  ipfs config or daemon restart failed
##############################################################################
set -euo pipefail

err()  { echo "  ❌ $*" >&2; }
ok()   { echo "  ✓  $*"; }
info() { echo "ℹ️   $*"; }

[ "$EUID" -eq 0 ] || { err "must be run as root (sudo)"; exit 1; }
command -v ipfs >/dev/null || { err "ipfs (kubo) not installed"; exit 1; }
command -v ufw  >/dev/null || { err "ufw not installed — apt install -y ufw"; exit 1; }

MODE="${VERNIS_NETWORK_MODE:-public}"
case "$MODE" in
    public|private) ;;
    *) err "invalid VERNIS_NETWORK_MODE='$MODE' (expected public|private)"; exit 1 ;;
esac
info "Network mode: $MODE"

# -- Detect the user that runs the ipfs service ------------------------------
IPFS_USER=$(systemctl show -p User ipfs --value 2>/dev/null || true)
[ -z "$IPFS_USER" ] && IPFS_USER=$(stat -c '%U' "${IPFS_PATH:-/var/lib/ipfs}" 2>/dev/null || echo "")
[ -z "$IPFS_USER" ] && IPFS_USER=$(stat -c '%U' "$HOME/.ipfs" 2>/dev/null || echo "")
[ -z "$IPFS_USER" ] && { err "could not determine ipfs runtime user"; exit 1; }
info "IPFS runs as: $IPFS_USER"

IPFS_PATH=$(systemctl show -p Environment ipfs --value 2>/dev/null | tr ' ' '\n' | sed -n 's/^IPFS_PATH=//p')
[ -z "$IPFS_PATH" ] && IPFS_PATH=$(getent passwd "$IPFS_USER" | cut -d: -f6)/.ipfs
[ -d "$IPFS_PATH" ] || { err "IPFS_PATH not found ($IPFS_PATH)"; exit 1; }
info "IPFS_PATH: $IPFS_PATH"

# -- Detect LAN CIDR ---------------------------------------------------------
if [ -n "${VERNIS_LAN_CIDR:-}" ]; then
    LAN_CIDR="$VERNIS_LAN_CIDR"
else
    DEFAULT_IF=$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}')
    LAN_ADDR=$(ip -o -4 addr show "$DEFAULT_IF" 2>/dev/null | awk '{print $4; exit}')
    [ -z "$LAN_ADDR" ] && { err "could not autodetect LAN; pass VERNIS_LAN_CIDR=X.X.X.X/N"; exit 1; }
    LAN_CIDR=$(echo "$LAN_ADDR" | cut -d/ -f1 | awk -F. '{print $1"."$2"."$3".0/24"}')
fi
info "LAN CIDR: $LAN_CIDR"

# -- (1) Firewall: IPv4 + IPv6 ----------------------------------------------
echo
echo "── ufw ─────────────────────────────────────────────────"
sed -i 's/^IPV6=.*/IPV6=yes/' /etc/default/ufw
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing

if [ "$MODE" = "public" ]; then
    ufw allow 4001/tcp comment 'IPFS libp2p swarm (public)' >/dev/null
    ufw allow 4001/udp comment 'IPFS QUIC (public)'          >/dev/null
fi

ufw allow from "$LAN_CIDR" to any port 80,443 proto tcp \
    comment 'Vernis admin web (LAN only)' >/dev/null
ufw allow from "$LAN_CIDR" to any port 22 proto tcp \
    comment 'SSH (LAN only)' >/dev/null
ufw allow from "fe80::/10" to any port 80,443,22 proto tcp \
    comment 'LAN IPv6 link-local' >/dev/null 2>&1 || true

# Bluetooth-PAN provisioning interface (bt0): a phone pairs over BT, then
# reaches the web UI at 10.44.0.1. The reset above wipes these, so re-add them
# (matches scripts/setup-bluetooth-pan.sh) or BT onboarding breaks.
ufw allow in on bt0 to any port 80,443 proto tcp \
    comment 'Vernis web over BT-PAN' >/dev/null 2>&1 || true
ufw allow in on bt0 to any port 22 proto tcp \
    comment 'SSH over BT-PAN' >/dev/null 2>&1 || true
ufw allow in on bt0 to any port 67 proto udp \
    comment 'DHCP for BT-PAN' >/dev/null 2>&1 || true

ufw deny 5001/tcp comment 'IPFS API — never public' >/dev/null
ufw deny 8080/tcp comment 'IPFS Gateway — local only' >/dev/null

ufw limit from "$LAN_CIDR" to any port 22 proto tcp >/dev/null

ufw logging on >/dev/null
ufw --force enable >/dev/null
ok "ufw enabled, IPv4+IPv6, LAN=$LAN_CIDR, mode=$MODE"

# -- (2) IPFS config --------------------------------------------------------
echo
echo "── IPFS config ─────────────────────────────────────────"
as_ipfs() { sudo -u "$IPFS_USER" IPFS_PATH="$IPFS_PATH" "$@"; }

# Stop the daemon before editing config — otherwise `ipfs config` fails on the
# repo lock, AND a running daemon may auto-restart-loop during our changes.
# We start it again at the end.
systemctl stop ipfs 2>/dev/null || true
# Wait for the lock to be released (daemon shutdown is fast but not instant)
for i in 1 2 3 4 5; do
    [ -f "$IPFS_PATH/repo.lock" ] && fuser -s "$IPFS_PATH/repo.lock" 2>/dev/null && sleep 1 || break
done
[ -f "$IPFS_PATH/repo.lock" ] && ! fuser -s "$IPFS_PATH/repo.lock" 2>/dev/null && rm -f "$IPFS_PATH/repo.lock"


as_ipfs ipfs config Addresses.API     "/ip4/127.0.0.1/tcp/5001"   >/dev/null
as_ipfs ipfs config Addresses.Gateway "/ip4/127.0.0.1/tcp/8080"   >/dev/null

# Swarm bindings depend on mode
if [ "$MODE" = "public" ]; then
    as_ipfs ipfs config --json Addresses.Swarm '[
      "/ip4/0.0.0.0/tcp/4001",
      "/ip6/::/tcp/4001",
      "/ip4/0.0.0.0/udp/4001/quic-v1",
      "/ip6/::/udp/4001/quic-v1"
    ]' >/dev/null
else
    # Private mode: only LAN-side swarm
    as_ipfs ipfs config --json Addresses.Swarm '[
      "/ip4/127.0.0.1/tcp/4001",
      "/ip6/::1/tcp/4001"
    ]' >/dev/null
fi

as_ipfs ipfs config --json Addresses.NoAnnounce '[
  "/ip4/10.0.0.0/ipcidr/8",
  "/ip4/100.64.0.0/ipcidr/10",
  "/ip4/127.0.0.0/ipcidr/8",
  "/ip4/169.254.0.0/ipcidr/16",
  "/ip4/172.16.0.0/ipcidr/12",
  "/ip4/192.168.0.0/ipcidr/16",
  "/ip6/fc00::/ipcidr/7",
  "/ip6/fe80::/ipcidr/10"
]' >/dev/null

# Keystone: don't serve arbitrary unpinned content via the HTTP gateway
as_ipfs ipfs config --json Gateway.NoFetch true   >/dev/null
as_ipfs ipfs config --json Gateway.PublicGateways '{}' >/dev/null

# Don't relay for others, don't auto-open router ports
as_ipfs ipfs config --json Swarm.RelayService.Enabled false >/dev/null
as_ipfs ipfs config --json Swarm.RelayClient.Enabled true   >/dev/null
as_ipfs ipfs config --json Swarm.DisableNatPortMap true     >/dev/null

# Connection + resource caps
as_ipfs ipfs config --json Swarm.ConnMgr.HighWater 600 >/dev/null
as_ipfs ipfs config --json Swarm.ConnMgr.LowWater  300 >/dev/null
as_ipfs ipfs config Swarm.ConnMgr.GracePeriod "30s"    >/dev/null
as_ipfs ipfs config --json Swarm.ResourceMgr.Enabled true            >/dev/null
# kubo's MaxMemory takes a size literal (e.g. "512 MB"), not a percentage.
# Compute 25% of /proc/meminfo and pass as MB. Floor at 256 MB, cap at 4 GB.
TOTAL_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
RM_MB=$(( TOTAL_MB / 4 ))
[ "$RM_MB" -lt 256 ] && RM_MB=256
[ "$RM_MB" -gt 4096 ] && RM_MB=4096
as_ipfs ipfs config Swarm.ResourceMgr.MaxMemory "${RM_MB} MB"        >/dev/null
as_ipfs ipfs config --json Swarm.ResourceMgr.MaxFileDescriptors 8192 >/dev/null

# Announce only what we pinned, not everything we ever cached.
# Kubo 0.39+ renamed Reprovider.* to Provide.*. Old field name is now a FATAL
# deprecation error. Set the new names and unset the old to be safe across
# both 0.39+ and older versions still in the field.
KUBO_VER=$(as_ipfs ipfs version --number 2>/dev/null | tr -d ' ' || echo "0.0.0")
KUBO_MAJOR=$(echo "$KUBO_VER" | cut -d. -f1)
KUBO_MINOR=$(echo "$KUBO_VER" | cut -d. -f2)
if [ "$KUBO_MAJOR" -gt 0 ] || [ "$KUBO_MINOR" -ge 39 ]; then
    # New schema (kubo 0.39+)
    # First, remove any stale Reprovider keys that would fatal-on-start.
    as_ipfs ipfs config --json Reprovider 'null' 2>/dev/null || true
    as_ipfs ipfs config Provide.Strategy "pinned"     >/dev/null
    as_ipfs ipfs config Provide.DHT.Interval "12h"    >/dev/null
else
    # Old schema
    as_ipfs ipfs config Reprovider.Strategy "pinned" >/dev/null
    as_ipfs ipfs config Reprovider.Interval "12h"    >/dev/null
fi

# Disk cap derived from current free space (leave 5 GB headroom, floor at 5 GB)
FREE_GB=$(df -BG --output=avail "$IPFS_PATH" | tail -1 | tr -dc '0-9')
CAP=$(( FREE_GB > 10 ? FREE_GB - 5 : 5 ))
as_ipfs ipfs config Datastore.StorageMax "${CAP}GB" >/dev/null
as_ipfs ipfs config --json Datastore.StorageGCWatermark 90 >/dev/null
as_ipfs ipfs config Datastore.GCPeriod "1h" >/dev/null

# Routing — auto, let kubo decide whether to promote to DHT server
as_ipfs ipfs config Routing.Type "auto" >/dev/null

# Disable experimental / niche features
as_ipfs ipfs config --json Experimental.Libp2pStreamMounting false >/dev/null
as_ipfs ipfs config --json Experimental.P2pHttpProxy false         >/dev/null
as_ipfs ipfs config --json Experimental.FilestoreEnabled false     >/dev/null
as_ipfs ipfs config --json Experimental.UrlstoreEnabled false      >/dev/null
as_ipfs ipfs config --json Pubsub.Enabled false                    >/dev/null

# Disable AutoTLS — it tries to get a Let's Encrypt cert for the libp2p subdomain,
# which fails noisily on devices behind NAT and adds a useless attack surface.
as_ipfs ipfs config --json AutoTLS.Enabled false 2>/dev/null || true

ok "ipfs config hardened (api/gateway=127.0.0.1, NoFetch=true, Routing=auto, StorageMax=${CAP}GB)"

# -- (3) Systemd hardening override -----------------------------------------
echo
echo "── systemd override ────────────────────────────────────"
mkdir -p /etc/systemd/system/ipfs.service.d
cat > /etc/systemd/system/ipfs.service.d/10-vernis-hardening.conf <<EOF
# Vernis — public-node hardening overrides for the IPFS daemon.
# Generated by harden-public-node.sh. Idempotent — safe to re-apply.
#
# NOTES on what is *deliberately not* set:
#   MemoryDenyWriteExecute=true — incompatible with the Go runtime; crashes kubo.
#   ProtectControlGroups=true    — kubo's resource manager writes cgroup limits.
#   ProtectHome=true              — IPFS_PATH is under /home on Vernis; blocks config read.
#   SystemCallFilter ~@resources — would block setrlimit, also needed by kubo RM.

[Service]
ProtectSystem=strict
PrivateTmp=true
ReadWritePaths=$IPFS_PATH
NoNewPrivileges=true

PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectClock=true
ProtectHostname=true
LockPersonality=true
RestrictRealtime=true
RestrictSUIDSGID=true
RestrictNamespaces=true
SystemCallArchitectures=native
SystemCallFilter=@system-service @network-io
SystemCallFilter=~@privileged @reboot @swap @raw-io @mount @obsolete
RestrictAddressFamilies=AF_INET AF_INET6 AF_NETLINK AF_UNIX

MemoryHigh=25%
MemoryMax=40%
CPUQuota=200%
TasksMax=2048
LimitNOFILE=16384

Restart=on-failure
RestartSec=10
EOF
systemctl daemon-reload
ok "systemd override installed at /etc/systemd/system/ipfs.service.d/10-vernis-hardening.conf"

# -- (4) Apply: restart ipfs -----------------------------------------------
echo
echo "── restarting ipfs ─────────────────────────────────────"
systemctl restart ipfs
sleep 5
if systemctl is-active --quiet ipfs; then
    ok "ipfs restarted and running"
else
    err "ipfs failed to start — check 'journalctl -u ipfs -n 80'"
    exit 3
fi

# -- (5) Persist state to /opt/vernis/network-state.json -------------------
mkdir -p /opt/vernis
cat > /opt/vernis/network-state.json <<EOF
{
  "hardened_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "hardened_version": "1.0",
  "mode": "$MODE",
  "lan_cidr": "$LAN_CIDR",
  "ipfs_user": "$IPFS_USER",
  "ipfs_storage_max_gb": $CAP,
  "public_node_consent": $([ "$MODE" = "public" ] && echo "true" || echo "false")
}
EOF
chown "$IPFS_USER:$IPFS_USER" /opt/vernis/network-state.json
chmod 644 /opt/vernis/network-state.json
ok "state recorded at /opt/vernis/network-state.json"

# -- (6) Final report ------------------------------------------------------
echo
echo "── status ──────────────────────────────────────────────"
echo "  ufw:            $(ufw status | grep -c '^[0-9]') rules active"
echo "  ipfs api:       $(as_ipfs ipfs config Addresses.API)"
echo "  ipfs gateway:   $(as_ipfs ipfs config Addresses.Gateway)"
echo "  Gateway.NoFetch: $(as_ipfs ipfs config Gateway.NoFetch)"
echo "  Provide.Strategy: $(as_ipfs ipfs config Provide.Strategy 2>/dev/null || as_ipfs ipfs config Reprovider.Strategy 2>/dev/null)"
echo "  Routing:        $(as_ipfs ipfs config Routing.Type)"
echo "  Disk cap:       ${CAP}GB"
echo
echo "✅ Hardening complete."
echo "   Verify externally:  nmap -p 22,80,443,4001,5001,8080 <public-ip>"
echo "   Expected:           only 4001 open (or none, if mode=private)"
