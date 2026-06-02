#!/bin/bash
##############################################
# Vernis v3 - Device Preload Script
# Preload devices with CSV collections and/or IPFS files
# Usage: bash preload-device.sh [lite|full] [source_dir]
##############################################

set -e

DEVICE_MODE="${1:-full}"
SOURCE_DIR="${2:-./preload}"
VERNIS_DIR="/opt/vernis"
CSV_LIBRARY="$VERNIS_DIR/csv-library"
NFT_DIR="$VERNIS_DIR/nfts"
CONFIG_FILE="$VERNIS_DIR/device-config.json"

echo "=========================================="
echo "Vernis v3 - Device Preload"
echo "Mode: $DEVICE_MODE"
echo "=========================================="

# Create directories
mkdir -p "$CSV_LIBRARY"
mkdir -p "$NFT_DIR"

# Set device mode in config
cat > "$CONFIG_FILE" <<EOF
{
  "device_mode": "$DEVICE_MODE",
  "preload": {
    "enabled": true,
    "preloaded_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  },
  "library": {
    "enabled": true,
    "collections_dir": "$CSV_LIBRARY"
  }
}
EOF

echo "Device mode set to: $DEVICE_MODE"

# Copy CSV collections (both lite and full devices get these)
if [ -d "$SOURCE_DIR/csv-library" ]; then
    echo ""
    echo "Copying CSV library..."
    cp -r "$SOURCE_DIR/csv-library/"* "$CSV_LIBRARY/" 2>/dev/null || true
    CSV_COUNT=$(find "$CSV_LIBRARY" -name "*.csv" | wc -l)
    echo "  Installed $CSV_COUNT CSV collections"
fi

# Copy IPFS files (only full devices get these)
if [ "$DEVICE_MODE" = "full" ]; then
    if [ -d "$SOURCE_DIR/nfts" ]; then
        echo ""
        echo "Copying preloaded NFT files..."
        cp -r "$SOURCE_DIR/nfts/"* "$NFT_DIR/" 2>/dev/null || true
        NFT_COUNT=$(find "$NFT_DIR" -type f | wc -l)
        echo "  Installed $NFT_COUNT NFT files"
    fi
else
    echo ""
    echo "Lite mode: Skipping NFT file preload (CSV only)"
fi

# Set permissions
chown -R pi:pi "$VERNIS_DIR"

echo ""
echo "=========================================="
echo "Preload Complete!"
echo "=========================================="
echo "Device Mode: $DEVICE_MODE"
echo "CSV Collections: $CSV_COUNT"
if [ "$DEVICE_MODE" = "full" ]; then
    echo "Preloaded NFTs: $NFT_COUNT"
fi
echo "=========================================="
