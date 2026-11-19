#!/bin/bash
##############################################
# Vernis installer entry point (from a git clone)
#
# The real installer is scripts/install-vernis.sh - see INSTALL.md.
# It deploys from a web/ backend/ scripts/ layout, which a git clone
# does not have, so this wrapper stages the repo into that layout
# (/tmp/vernis-deploy) and then runs it.
#
# Usage, from the repository root, as your normal user (not sudo):
#   bash install.sh
##############################################

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Note: the Vernis installer is now scripts/install-vernis.sh (see INSTALL.md)."
echo "      This wrapper stages the files from this clone and runs it."
echo ""

# install-vernis.sh refuses to run as root (it installs per-user kiosk and
# IPFS config, and calls sudo itself). Hand an old 'sudo bash install.sh'
# back to the user who ran sudo.
if [ "$EUID" -eq 0 ]; then
    if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
        echo "Re-running as $SUDO_USER - the installer must not run as root."
        exec sudo -H -u "$SUDO_USER" bash "$REPO_DIR/install.sh" "$@"
    fi
    echo "Run this as your normal desktop user, without sudo:  bash install.sh"
    exit 1
fi

if [ ! -f "$REPO_DIR/backend/app.py" ] || [ ! -f "$REPO_DIR/scripts/install-vernis.sh" ]; then
    echo "Could not find backend/app.py and scripts/install-vernis.sh next to this script."
    echo "Run install.sh from the root of a complete Vernis clone."
    exit 1
fi

STAGE=/tmp/vernis-deploy
rm -rf "$STAGE"
mkdir -p "$STAGE/web" "$STAGE/backend" "$STAGE/scripts" "$STAGE/csv-library"
cd "$REPO_DIR"
for f in *.html *.css *.js *.svg *.webmanifest version.json; do
    [ -f "$f" ] && cp "$f" "$STAGE/web/"
done
[ -d assets ] && cp -r assets "$STAGE/web/"
for f in backend/app.py backend/curator.py backend/curator_claude.py; do
    [ -f "$f" ] && cp "$f" "$STAGE/backend/"
done
for f in scripts/*.sh scripts/*.py scripts/*.c scripts/*.dts; do
    [ -f "$f" ] && cp "$f" "$STAGE/scripts/"
done
for f in csv-library/*.csv; do
    [ -f "$f" ] && cp "$f" "$STAGE/csv-library/"
done

exec bash "$REPO_DIR/scripts/install-vernis.sh" "$@"
