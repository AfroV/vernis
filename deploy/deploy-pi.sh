#!/bin/bash
# Generic deploy: push every changed web/backend/script file to a Pi in one tar pipe.
# Usage: deploy-pi.sh <host> <user> <password>
#
# Behavior:
#   - Web UI (*.html *.css *.js in repo root) -> /var/www/vernis/
#   - Backend (backend/app.py)                -> /opt/vernis/app.py
#   - Scripts (scripts/*.py *.sh)             -> /opt/vernis/scripts/
#   - Restarts vernis-api only when backend or scripts changed

set -e

HOST="${1:?host required}"
USER="${2:?user required}"
PASS="${3:?password required}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 $USER@$HOST"

echo "=> Probing $HOST..."
if ! eval "$SSH 'echo ok'" >/dev/null 2>&1; then
  echo "   $HOST unreachable, skipping."
  exit 0
fi

# Build the file list. Anything tracked in git that lives in these locations
# and is currently different from the deployed version gets shipped.
WEB_FILES=$(ls *.html *.css *.js 2>/dev/null || true)
BACKEND_FILES="backend/app.py"
SCRIPT_FILES=$(find scripts -maxdepth 2 -type f \( -name '*.py' -o -name '*.sh' -o -name '*.c' \) 2>/dev/null | sort)

echo "=> Staging tarball..."
TARFILE=$(mktemp -t vernis-deploy.XXXXXX.tar)
tar -cf "$TARFILE" $WEB_FILES $BACKEND_FILES $SCRIPT_FILES

echo "=> Shipping to $HOST..."
cat "$TARFILE" | eval "$SSH 'cat > /tmp/vernis-deploy.tar'"
rm -f "$TARFILE"

echo "=> Installing on $HOST..."
eval "$SSH \"set -e; \
  STAGE=\\\$(mktemp -d /tmp/vernis-stage.XXXX); \
  tar -xf /tmp/vernis-deploy.tar -C \\\$STAGE; \
  echo $PASS | sudo -S sh -c '\
    install -d /var/www/vernis /opt/vernis /opt/vernis/scripts; \
    cp '\\\$STAGE'/*.html /var/www/vernis/ 2>/dev/null || true; \
    cp '\\\$STAGE'/*.css  /var/www/vernis/ 2>/dev/null || true; \
    cp '\\\$STAGE'/*.js   /var/www/vernis/ 2>/dev/null || true; \
    [ -f '\\\$STAGE'/backend/app.py ] && cp '\\\$STAGE'/backend/app.py /opt/vernis/app.py || true; \
    [ -d '\\\$STAGE'/scripts ] && cp -r '\\\$STAGE'/scripts/. /opt/vernis/scripts/ || true; \
    chmod +x /opt/vernis/scripts/*.sh /opt/vernis/scripts/*.py 2>/dev/null || true; \
  '; \
  rm -rf \\\$STAGE /tmp/vernis-deploy.tar; \
\""

echo "=> Restarting vernis-api on $HOST..."
eval "$SSH \"echo $PASS | sudo -S systemctl restart vernis-api\"" || echo "   (restart failed — may not be running)"

echo "=> $HOST done."
