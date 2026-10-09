#!/bin/bash
##############################################
# Vernis v3 - Update from GitHub (what Settings > Install update runs)
#
# Usage: sudo bash vernis-update.sh <repo> <branch>
#
# 1. Runs from a private copy in /tmp, so installing a new version of this
#    script can't change it while bash is still reading it.
# 2. Backs up the web UI, backend and scripts before touching them
#    (/opt/vernis/backups, last 3 kept; restore with rollback-update.sh).
# 3. Rolls back automatically if the API doesn't come back after the update.
#
# github-update.sh is the updater of 3.5.0 and older. Keep it byte-for-byte
# unchanged: those versions copy it over themselves while it runs, which is
# only harmless when the content is identical.
##############################################

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash vernis-update.sh <repo> <branch>"
    exit 1
fi

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: sudo bash vernis-update.sh <repo> <branch>"
    exit 1
fi

# Re-run from a private copy (see 1. above)
if [ "${VERNIS_UPDATE_STAGED:-}" != "1" ]; then
    SELF_COPY=$(mktemp /tmp/vernis-update-run.XXXXXX)
    cp "$0" "$SELF_COPY"
    VERNIS_UPDATE_STAGED=1 exec bash "$SELF_COPY" "$@"
fi
trap 'rm -f "$0"' EXIT

GITHUB_REPO="$1"
GITHUB_BRANCH="$2"

# Only the official repo, or one the owner listed over SSH, may be installed:
# whatever is cloned here is copied into /opt/vernis and run as root.
ALLOWED_REPOS_FILE="/etc/vernis/allowed-update-repos"
REPO_LC=$(printf '%s' "$GITHUB_REPO" | tr '[:upper:]' '[:lower:]')
if [ "$REPO_LC" != "afrov/vernis" ] && \
   ! { [ -f "$ALLOWED_REPOS_FILE" ] && grep -qixF -- "$GITHUB_REPO" "$ALLOWED_REPOS_FILE"; }; then
    echo "❌ Refusing to update from $GITHUB_REPO (not an allowed update repo)"
    exit 1
fi
case "$GITHUB_BRANCH" in
    -*|*..*|*[!A-Za-z0-9._/-]*) echo "❌ Invalid branch name"; exit 1 ;;
esac

WEB_DIR="/var/www/vernis"
APP_DIR="/opt/vernis"
BACKUP_DIR="$APP_DIR/backups"
TEMP_DIR=$(mktemp -d /tmp/vernis-github-update.XXXXXX)

echo "=========================================="
echo "Vernis v3 - Update"
echo "=========================================="
echo "Repository: $GITHUB_REPO"
echo "Branch: $GITHUB_BRANCH"
echo ""

cd "$TEMP_DIR"

echo "[1/7] Downloading update..."
git clone --depth 1 --branch "$GITHUB_BRANCH" "https://github.com/$GITHUB_REPO.git" vernis || {
    echo "❌ Failed to download update"
    exit 1
}
cd vernis
if [ ! -f "backend/app.py" ]; then
    echo "❌ Invalid repository structure - backend/app.py not found"
    exit 1
fi
echo "✅ Downloaded"

echo "[2/7] Backing up current version..."
OLD_VERSION=$(python3 -c "import json; print(json.load(open('$WEB_DIR/version.json'))['version'])" 2>/dev/null || echo unknown)
mkdir -p "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/vernis-$OLD_VERSION-$(date +%Y%m%d-%H%M%S).tar.gz"
# Code only: art, settings and other state files are never touched by updates
tar czf "$BACKUP" -C / \
    "${WEB_DIR#/}" \
    "${APP_DIR#/}/app.py" \
    $(cd / && ls -d "${APP_DIR#/}/curator.py" "${APP_DIR#/}/curator_claude.py" 2>/dev/null) \
    "${APP_DIR#/}/scripts" || {
    rm -f "$BACKUP"
    echo "❌ Backup failed - nothing was changed"
    exit 1
}
ls -1t "$BACKUP_DIR"/vernis-*.tar.gz 2>/dev/null | tail -n +4 | xargs -r rm -f
echo "✅ Backup: $BACKUP"

wait_for_api() {
    for _ in $(seq 1 30); do
        curl -fsS -m 3 -o /dev/null http://127.0.0.1:5000/api/version && return 0
        sleep 2
    done
    return 1
}

restore_backup() {
    echo "↩ Restoring $BACKUP ..."
    tar xzf "$BACKUP" -C /
    systemctl restart vernis-api.service || true
    systemctl restart caddy || true
    if wait_for_api; then
        echo "✅ Previous version $OLD_VERSION restored and running"
    else
        echo "❌ Previous version restored but not answering - check: journalctl -u vernis-api"
    fi
}

echo "[3/7] Installing update..."
cp *.html "$WEB_DIR/"
cp *.css "$WEB_DIR/" 2>/dev/null || true
cp *.js "$WEB_DIR/" 2>/dev/null || true
cp version.json "$WEB_DIR/" 2>/dev/null || true
cp *.svg "$WEB_DIR/" 2>/dev/null || true
cp *.webmanifest "$WEB_DIR/" 2>/dev/null || true
if [ -d "assets" ]; then
    mkdir -p "$WEB_DIR/assets"
    cp assets/* "$WEB_DIR/assets/" 2>/dev/null || true
fi
chown -R caddy:caddy "$WEB_DIR"
# Every backend module, like a fresh install: a new module (curator.py in
# 3.5.0) must never be left behind by a hard-coded file list.
cp backend/*.py "$APP_DIR/"
if [ -d "scripts" ]; then
    cp scripts/*.sh "$APP_DIR/scripts/" 2>/dev/null || true
    cp scripts/*.py "$APP_DIR/scripts/" 2>/dev/null || true
    cp scripts/*.c "$APP_DIR/scripts/" 2>/dev/null || true
    chmod +x "$APP_DIR"/scripts/*.sh 2>/dev/null || true
    chmod +x "$APP_DIR"/scripts/*.py 2>/dev/null || true
fi

# Check every file landed: a partial install must not be reported as success
missing=""
for f in *.html *.css *.js version.json *.svg *.webmanifest; do
    [ -f "$f" ] && { cmp -s "$f" "$WEB_DIR/$f" || missing="$missing $f"; }
done
for f in backend/*.py; do
    cmp -s "$f" "$APP_DIR/${f#backend/}" || missing="$missing $f"
done
for f in scripts/*.sh scripts/*.py scripts/*.c; do
    [ -f "$f" ] && { cmp -s "$f" "$APP_DIR/$f" || missing="$missing $f"; }
done
if [ -n "$missing" ]; then
    echo "❌ Some files were not installed:$missing"
    restore_backup
    rm -rf "$TEMP_DIR"
    exit 1
fi
echo "✅ Installed (all files verified)"

echo "[4/7] Restarting services..."
systemctl restart vernis-api.service
systemctl restart caddy
echo "✅ Restarted"

echo "[5/7] Checking the new version starts..."
if ! wait_for_api; then
    echo "❌ The updated Vernis did not start - rolling back to $OLD_VERSION"
    journalctl -u vernis-api -n 20 --no-pager 2>/dev/null || true
    restore_backup
    rm -rf "$TEMP_DIR"
    exit 1
fi
echo "✅ Vernis is running"

echo "[6/7] Running system updates..."
apt-get update || true
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" || \
    echo "⚠ System package upgrade failed - Vernis itself is updated"
# ffmpeg makes video and AVIF thumbnails. Optional: never fail the update for it
if ! command -v ffmpeg > /dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ffmpeg || \
        echo "⚠ ffmpeg not installed - video/AVIF thumbnails use a fallback"
fi
echo "✅ System updated"

echo "[7/7] Cleaning up..."
cd /
rm -rf "$TEMP_DIR"
echo "✅ Done"

echo ""
echo "=========================================="
echo "✅ Update complete ($OLD_VERSION -> $(python3 -c "import json; print(json.load(open('$WEB_DIR/version.json'))['version'])" 2>/dev/null || echo '?'))"
echo "=========================================="
echo "Previous version saved in $BACKUP"
echo "System will reboot in 10 seconds..."
sleep 10
reboot
