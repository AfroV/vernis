#!/bin/bash
# Quick deploy script - run this on your Mac after starting dev server

PI_HOST="10.2.0.8"
DEV_SERVER="10.2.0.7:8080"

echo "=========================================="
echo "Deploying to Raspberry Pi..."
echo "=========================================="
echo ""

# Test Pi connectivity
echo "Testing connection to $PI_HOST..."
if ! ping -c 1 -W 2 $PI_HOST &> /dev/null; then
    echo "❌ Cannot reach $PI_HOST"
    echo "   Make sure the Pi is on and connected to the network"
    exit 1
fi
echo "✅ Pi is reachable"
echo ""

# Trigger update via SSH
echo "Triggering update from $DEV_SERVER..."
ssh pi@$PI_HOST "sudo bash /opt/vernis/scripts/dev-update.sh $DEV_SERVER"

echo ""
echo "=========================================="
echo "✅ Deployment Complete!"
echo "=========================================="
echo ""
echo "View your Pi at: http://vernis.local"
echo ""
