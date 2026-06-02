#!/bin/bash
# Vernis - Boot Partition Installer (Stage 1)
# This script is intended to be run via 'init=' kernel parameter hijack.

# 1. Mount filesystems
mount -t proc proc /proc
mount -t sysfs sys /sys
mount -t devtmpfs dev /dev

# 2. Remount root as Read-Write
mount -o remount,rw /

# 3. Find and Mount Boot Partition
# Try common locations
mkdir -p /boot
mount /dev/mmcblk0p1 /boot || mount /dev/sda1 /boot

# 4. Check for Vernis Source
SOURCE_DIR="/boot/vernis"
if [ ! -d "$SOURCE_DIR" ]; then
    # try firmware path (Bookworm)
    SOURCE_DIR="/boot/firmware/vernis"
fi

if [ ! -d "$SOURCE_DIR" ]; then
    echo "ERROR: Could not find 'vernis' folder in boot partition."
    echo "Dropping to shell..."
    exec /bin/sh
fi

# 5. Copy Files
TARGET_DIR="/home/pi/vernis"
echo "Installing to $TARGET_DIR..."
rm -rf "$TARGET_DIR"
cp -r "$SOURCE_DIR" "$TARGET_DIR"
chown -R pi:pi "$TARGET_DIR"
chmod +x "$TARGET_DIR/install.sh"
chmod +x "$TARGET_DIR/deploy/install-services.sh"

# 6. Setup Stage 2 (Run install.sh on normal boot)
SERVICE_FILE="/etc/systemd/system/vernis-firstrun.service"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Vernis First Run Config
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/bash /home/pi/vernis/install.sh
ExecStartPost=/bin/systemctl disable vernis-firstrun.service
ExecStartPost=/bin/rm /etc/systemd/system/vernis-firstrun.service
StandardOutput=journal+console

[Install]
WantedBy=multi-user.target
EOF

# Enable the service manually
mkdir -p /etc/systemd/system/multi-user.target.wants
ln -s "$SERVICE_FILE" "/etc/systemd/system/multi-user.target.wants/vernis-firstrun.service"

# 7. Restore cmdline.txt
# We assume the user backed up original to cmdline.orig typically
if [ -f "/boot/cmdline.orig" ]; then
    mv /boot/cmdline.orig /boot/cmdline.txt
elif [ -f "/boot/firmware/cmdline.orig" ]; then
    mv /boot/firmware/cmdline.orig /boot/firmware/cmdline.txt
else
    # Fallback to standard cmdline if backup missing (Risky, but better than loop)
    # This is a standard Pi 4 cmdline
    echo "console=serial0,115200 console=tty1 root=PARTUUID=PART_UUID_HERE rootfstype=ext4 fsck.repair=yes rootwait" > /boot/cmdline.txt
    # We can't guess the PARTUUID easily without tools, so we warn
    echo "WARNING: cmdline.orig not found. You might need to dry manual repair."
fi

# 8. Sync and Reboot
sync
echo "Stage 1 Complete. Rebooting into Vernis Installer..."
umount /boot
reboot -f
