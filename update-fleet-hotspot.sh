#!/usr/bin/env bash
# Update Vernis units over the VF hotspot (offline, no GitHub, no Claude needed).
# The Mac pushes its newest vernis-update-*.tar.gz straight to each device
# (no router HTTP staging needed -- always uses your latest local package).
#
# Prereqs:
#   1. Spare-Pi router (VF) booted and STAYS powered (it's the network)
#   2. The unit(s) you're updating are powered on and joined to VF
#   3. This Mac is joined to VF
#   4. sshpass installed (brew install hudochenkov/sshpass/sshpass)
#   5. A package built:  bash scripts/create-update-package.sh
#
# Passwords come from secrets.env (gitignored) and are never printed.
#
# Usage:
#   bash update-fleet-hotspot.sh          # AUTO-DETECT: update whichever Pi(s) are on VF right now
#   bash update-fleet-hotspot.sh afrom    # just afrom (pi-39)
#   bash update-fleet-hotspot.sh 1        # just vernis1  (number -> vernisN)
#   bash update-fleet-hotspot.sh 2 3      # vernis2 and vernis3
set -uo pipefail
cd "$(dirname "$0")"

[ -f secrets.env ] || { echo "secrets.env missing in $(pwd)"; exit 1; }
set -a; . ./secrets.env; set +a

PKG=$(ls -t vernis-update-*.tar.gz 2>/dev/null | head -1)
[ -n "$PKG" ] || { echo "X No vernis-update-*.tar.gz found. Run: bash scripts/create-update-package.sh"; exit 1; }
echo "OK Package: $PKG"

# Confirm we're on the VF network (router gateway reachable)
if ! ping -c1 -t2 10.42.0.1 >/dev/null 2>&1; then
  echo "X Not on VF -- can't reach the router (10.42.0.1). Join VF and retry."
  exit 1
fi
echo "OK On VF."
echo

ping1() { ping -c1 -t2 "$1" >/dev/null 2>&1; }

if [ "$#" -gt 0 ]; then
  UNITS=("$@")                                    # explicit: numbers (->vernisN) or names (afrom)
else
  echo "No unit given -> auto-detecting which Pi(s) are on VF..."
  UNITS=()
  for name in $(grep -E '^VERNIS_PASS_[A-Za-z0-9_]+=.+' secrets.env | sed -E 's/^VERNIS_PASS_([A-Za-z0-9_]+)=.*/\1/'); do
    if ping1 "$name.local"; then echo "   online: $name"; UNITS+=("$name"); fi
  done
  if [ ${#UNITS[@]} -eq 0 ]; then
    echo "X No Vernis device reachable on VF. Power one on, let it join VF, then retry."; exit 1
  fi
  echo "   -> updating: ${UNITS[*]}"; echo
fi

for N in "${UNITS[@]}"; do
  case "$N" in *[!0-9]*) U="$N" ;; *) U="vernis$N" ;; esac   # name (afrom) or number (->vernisN)
  IP="$U.local"
  VAR="VERNIS_PASS_$U"; PW="${!VAR:-}"
  if [ -z "$PW" ]; then echo "-- $U: no password in secrets.env, skipping"; echo; continue; fi
  if ! ping1 "$IP"; then
    echo "-- $U ($IP): not online -> skipping. (Power it on, let it boot, join VernisAP, re-run.)"; echo; continue
  fi

  echo "-- $U ($IP): copying package + applying update..."
  if ! sshpass -p "$PW" scp -o StrictHostKeyChecking=no -o ConnectTimeout=15 "$PKG" "$U@$IP:/tmp/v.tar.gz"; then
    echo "   X  $U: package copy (scp) failed -- skipping"; echo; continue
  fi
  sshpass -p "$PW" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$U@$IP" \
    "echo '$PW' | sudo -S -p '' bash -c 'setsid bash /opt/vernis/scripts/updater.sh /tmp/v.tar.gz >/tmp/vernis-update.log 2>&1 </dev/null &'"
  echo "   OK $U: update launched -- unit will reboot"

  # Wait for the reboot to finish so it's safe to power off / reuse the cable.
  echo "   ... applying + rebooting; DO NOT power off yet"
  for i in $(seq 1 45); do ping1 "$IP" || break; sleep 2; done      # wait until it drops offline
  back=0
  for i in $(seq 1 90); do if ping1 "$IP"; then back=1; break; fi; sleep 2; done   # wait until it returns
  if [ "$back" = 1 ]; then
    echo "   OK $U updated and back online -> SAFE to power off / move the cable"
  else
    echo "   !! $U not back yet -> wait for its gallery screen before powering off"
  fi
  echo
done
echo "Done."
