#!/bin/bash
# Setup swap and memory optimizations for low-RAM Raspberry Pis
# Run with: sudo bash setup-swap.sh

set -e

echo "=== Vernis Swap & Memory Optimization ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash setup-swap.sh"
    exit 1
fi

# Get total RAM in MB
TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
echo "Detected RAM: ${TOTAL_RAM}MB"

# Only apply aggressive optimizations for low-RAM devices (<2GB)
if [ "$TOTAL_RAM" -gt 2000 ]; then
    echo "This device has sufficient RAM (${TOTAL_RAM}MB). Skipping aggressive optimizations."
    echo "Only applying basic swap improvements..."
    SWAP_SIZE="1G"
else
    echo "Low-RAM device detected. Applying full optimizations..."
    SWAP_SIZE="2G"
fi

# 1. Setup swapfile
echo ""
echo "=== Setting up ${SWAP_SIZE} swapfile ==="

# Disable existing swap
echo "Disabling existing swap..."
swapoff -a 2>/dev/null || true

# Remove old dphys-swapfile if exists
if [ -f /etc/dphys-swapfile ]; then
    echo "Disabling dphys-swapfile service..."
    systemctl stop dphys-swapfile 2>/dev/null || true
    systemctl disable dphys-swapfile 2>/dev/null || true
fi

# Remove old swapfile if exists
rm -f /var/swap /swapfile 2>/dev/null || true

# Create new swapfile
echo "Creating ${SWAP_SIZE} swapfile..."
fallocate -l ${SWAP_SIZE} /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=progress
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile

# Add to fstab if not already there
if ! grep -q '/swapfile' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "Added swapfile to /etc/fstab"
fi

echo "Swapfile created and enabled"

# 2. Set swappiness (lower = prefer RAM, higher = use swap more)
echo ""
echo "=== Configuring swappiness ==="

# For low-RAM: use swap more freely (swappiness=60)
# For high-RAM: prefer RAM (swappiness=10)
if [ "$TOTAL_RAM" -gt 2000 ]; then
    SWAPPINESS=10
else
    SWAPPINESS=60
fi

echo "Setting vm.swappiness=${SWAPPINESS}"
sysctl vm.swappiness=${SWAPPINESS}

# Make persistent
if grep -q 'vm.swappiness' /etc/sysctl.conf; then
    sed -i "s/vm.swappiness=.*/vm.swappiness=${SWAPPINESS}/" /etc/sysctl.conf
else
    echo "vm.swappiness=${SWAPPINESS}" >> /etc/sysctl.conf
fi

# 3. Setup zram (compressed RAM swap) for low-RAM devices
if [ "$TOTAL_RAM" -lt 2000 ]; then
    echo ""
    echo "=== Setting up zram (compressed RAM swap) ==="

    if ! command -v zramctl &> /dev/null; then
        echo "Installing zram-tools..."
        apt-get update -qq
        apt-get install -y -qq zram-tools
    fi

    # Configure zram to use 50% of RAM
    ZRAM_SIZE=$((TOTAL_RAM / 2))

    # Create zram config
    cat > /etc/default/zramswap << EOF
# Zram swap configuration
ALGO=lz4
PERCENT=50
PRIORITY=100
EOF

    # Enable zram service
    systemctl enable zramswap 2>/dev/null || true
    systemctl restart zramswap 2>/dev/null || true

    echo "zram configured with ${ZRAM_SIZE}MB compressed swap"
fi

# 4. Update kiosk-launcher.sh with memory-saving flags
KIOSK_LAUNCHER="/opt/vernis/scripts/kiosk-launcher.sh"
if [ -f "$KIOSK_LAUNCHER" ]; then
    echo ""
    echo "=== Updating Chromium memory flags ==="

    # Check if memory flags already added
    if ! grep -q 'max-old-space-size' "$KIOSK_LAUNCHER"; then
        # Add memory-saving flags before the URL
        sed -i 's|--password-store=basic|--password-store=basic \\\n    --js-flags="--max-old-space-size=256" \\\n    --disable-features=TranslateUI \\\n    --disable-background-networking \\\n    --disable-component-update \\\n    --disable-domain-reliability|' "$KIOSK_LAUNCHER"
        echo "Added memory-saving flags to kiosk-launcher.sh"
    else
        echo "Memory flags already present in kiosk-launcher.sh"
    fi
fi

# 5. Set memory limits for chromium via systemd override
echo ""
echo "=== Setting process memory limits ==="

mkdir -p /etc/systemd/system/vernis-kiosk.service.d/
cat > /etc/systemd/system/vernis-kiosk.service.d/memory.conf << EOF
[Service]
# Limit memory to prevent OOM affecting other services
MemoryMax=80%
MemoryHigh=70%
OOMScoreAdjust=500
EOF

systemctl daemon-reload 2>/dev/null || true

# Show results
echo ""
echo "=== Configuration Complete ==="
echo ""
free -h
echo ""
echo "Swap status:"
swapon --show 2>/dev/null || cat /proc/swaps
echo ""
echo "Reboot recommended to apply all changes: sudo reboot"
