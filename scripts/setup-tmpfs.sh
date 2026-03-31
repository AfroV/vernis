#!/bin/bash
# Setup tmpfs RAM disk for Vernis temp work
# Reduces SD card writes, improves performance
# Run with: sudo bash setup-tmpfs.sh [size]
# Size defaults to 512M. Use "auto" for 25% of RAM.

set -e

echo "=== Vernis tmpfs RAM Disk Setup ==="

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash setup-tmpfs.sh"
    exit 1
fi

MOUNT_POINT="/opt/vernis/tmp"
TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
SIZE_ARG="${1:-512M}"

# Auto-size: 25% of RAM, capped at 2G
if [ "$SIZE_ARG" = "auto" ]; then
    AUTO_MB=$((TOTAL_RAM / 4))
    [ "$AUTO_MB" -gt 2048 ] && AUTO_MB=2048
    [ "$AUTO_MB" -lt 256 ] && AUTO_MB=256
    SIZE_ARG="${AUTO_MB}M"
fi

echo "RAM: ${TOTAL_RAM}MB | tmpfs size: ${SIZE_ARG}"

# Create mount point
mkdir -p "$MOUNT_POINT"

# Check if already mounted
if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo "tmpfs already mounted at $MOUNT_POINT"
    df -h "$MOUNT_POINT"
    exit 0
fi

# Add to fstab if not already there
FSTAB_LINE="tmpfs $MOUNT_POINT tmpfs defaults,noatime,nosuid,nodev,noexec,size=$SIZE_ARG,mode=1777 0 0"
if ! grep -q "$MOUNT_POINT" /etc/fstab; then
    echo "$FSTAB_LINE" >> /etc/fstab
    echo "Added to /etc/fstab"
else
    # Update existing entry with new size
    sed -i "\|$MOUNT_POINT|c\\$FSTAB_LINE" /etc/fstab
    echo "Updated /etc/fstab entry"
fi

# Mount now
mount "$MOUNT_POINT"
echo "Mounted tmpfs at $MOUNT_POINT"
df -h "$MOUNT_POINT"

# Also reduce SD card journal writes
if [ -f /etc/systemd/journald.conf ]; then
    if ! grep -q "^Storage=volatile" /etc/systemd/journald.conf; then
        sed -i 's/^#\?Storage=.*/Storage=volatile/' /etc/systemd/journald.conf
        sed -i 's/^#\?RuntimeMaxUse=.*/RuntimeMaxUse=32M/' /etc/systemd/journald.conf
        systemctl restart systemd-journald 2>/dev/null || true
        echo "Journal moved to RAM (volatile, 32M max)"
    fi
fi

echo ""
echo "Done. Vernis will use $MOUNT_POINT for temp work."
echo "Survives reboot via fstab. Data is lost on power off (intended)."
