#!/bin/bash
##############################################
# Vernis v3 - Go back to the version before the last update
#
# vernis-update.sh saves the web UI, backend and scripts to
# /opt/vernis/backups before each update (last 3 kept). Art and settings
# are not part of the backup and are left as they are.
#
# Usage: sudo bash rollback-update.sh            # newest backup
#        sudo bash rollback-update.sh --list     # show backups
#        sudo bash rollback-update.sh <file>     # a specific backup
##############################################

set -e

BACKUP_DIR="/opt/vernis/backups"

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash rollback-update.sh"
    exit 1
fi

if [ "$1" = "--list" ]; then
    ls -1t "$BACKUP_DIR"/vernis-*.tar.gz 2>/dev/null || echo "No backups in $BACKUP_DIR"
    exit 0
fi

BACKUP="${1:-$(ls -1t "$BACKUP_DIR"/vernis-*.tar.gz 2>/dev/null | head -1)}"
if [ -z "$BACKUP" ] || [ ! -f "$BACKUP" ]; then
    echo "❌ No backup found in $BACKUP_DIR"
    exit 1
fi

echo "Restoring $BACKUP ..."
tar xzf "$BACKUP" -C /
systemctl restart vernis-api.service
systemctl restart caddy
echo "✅ Restored. Reload the browser (or reboot) to see the restored version."
