#!/bin/bash
##############################################
# Vernis v3 - GitHub Update Script
# Pulls latest code from GitHub repository
# Usage: sudo bash github-update.sh <repo> <branch>
# Example: sudo bash github-update.sh yourusername/vernis main
##############################################

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash github-update.sh <repo> <branch>"
    exit 1
fi

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: sudo bash github-update.sh <repo> <branch>"
    echo "Example: sudo bash github-update.sh yourusername/vernis main"
    exit 1
fi

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

TEMP_DIR=$(mktemp -d /tmp/vernis-github-update.XXXXXX)

echo "=========================================="
echo "Vernis v3 - GitHub Update"
echo "=========================================="
echo ""
echo "Repository: $GITHUB_REPO"
echo "Branch: $GITHUB_BRANCH"
echo ""

cd "$TEMP_DIR"

# Clone the repository
echo "[1/6] Cloning repository from GitHub..."
git clone --depth 1 --branch "$GITHUB_BRANCH" "https://github.com/$GITHUB_REPO.git" vernis || {
    echo "❌ Failed to clone repository"
    exit 1
}
cd vernis
echo "✅ Repository cloned"

echo "[2/6] Verifying files..."
if [ ! -f "backend/app.py" ]; then
    echo "❌ Invalid repository structure - backend/app.py not found"
    exit 1
fi
echo "✅ Files verified"

echo "[3/6] Installing updates..."
# Copy web files (HTML, CSS, JS, JSON, SVG, assets)
cp *.html /var/www/vernis/
cp *.css /var/www/vernis/ 2>/dev/null || true
cp *.js /var/www/vernis/ 2>/dev/null || true
cp *.json /var/www/vernis/ 2>/dev/null || true
cp *.svg /var/www/vernis/ 2>/dev/null || true
cp *.webmanifest /var/www/vernis/ 2>/dev/null || true
if [ -d "assets" ]; then
    mkdir -p /var/www/vernis/assets
    cp assets/* /var/www/vernis/assets/ 2>/dev/null || true
fi
chown -R caddy:caddy /var/www/vernis
echo "✅ Web files installed"

# Copy backend
cp backend/app.py /opt/vernis/
cp backend/curator.py backend/curator_claude.py /opt/vernis/ 2>/dev/null || true
echo "✅ Backend installed"

# Copy scripts if they exist
if [ -d "scripts" ]; then
    cp scripts/*.sh /opt/vernis/scripts/ 2>/dev/null || true
    cp scripts/*.py /opt/vernis/scripts/ 2>/dev/null || true
    cp scripts/*.c /opt/vernis/scripts/ 2>/dev/null || true
    chmod +x /opt/vernis/scripts/*.sh 2>/dev/null || true
    chmod +x /opt/vernis/scripts/*.py 2>/dev/null || true
fi
echo "✅ Scripts installed"

echo "[4/6] Restarting services..."
systemctl restart vernis-api.service
systemctl restart caddy
echo "✅ Services restarted"

echo "[5/6] Running system updates..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"
# ffmpeg makes video and AVIF thumbnails. Optional: never fail the update for it
if ! command -v ffmpeg > /dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ffmpeg || \
        echo "⚠ ffmpeg not installed - video/AVIF thumbnails use a fallback"
fi
echo "✅ System updated"

echo "[6/6] Cleaning up..."
cd /
rm -rf "$TEMP_DIR"
echo "✅ Cleanup complete"

echo ""
echo "=========================================="
echo "✅ GitHub Update Complete!"
echo "=========================================="
echo ""
echo "Updated from: https://github.com/$GITHUB_REPO (branch: $GITHUB_BRANCH)"
echo ""
echo "System will reboot in 10 seconds..."
sleep 10
reboot
