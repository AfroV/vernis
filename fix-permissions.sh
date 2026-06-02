#!/bin/bash
##############################################
# Vernis v3 - Permission Fix Script
# Run this if you're getting Error 13 during CSV installation
##############################################

echo "=========================================="
echo "Vernis v3 - Fixing File Permissions"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash fix-permissions.sh"
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-pi}

echo "Setting ownership of /opt/vernis to $ACTUAL_USER..."

# Fix ownership of all Vernis directories
chown -R $ACTUAL_USER:$ACTUAL_USER /opt/vernis

echo ""
echo "=========================================="
echo "Permissions Fixed!"
echo "=========================================="
echo ""
echo "The following directories are now owned by $ACTUAL_USER:"
echo "  - /opt/vernis/nfts"
echo "  - /opt/vernis/uploads"
echo "  - /opt/vernis/scripts"
echo "  - /opt/vernis/backup"
echo "  - /opt/vernis/csv-library"
echo ""
echo "You should now be able to install CSV collections without Error 13."
echo ""
