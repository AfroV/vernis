#!/bin/bash
##############################################
# Vernis Preload Package Creator
# Helps prepare preload packages for device deployment
# Usage: bash prepare-preload-package.sh [lite|full]
##############################################

set -e

MODE="${1:-lite}"
PRELOAD_DIR="./preload-package"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

echo "=========================================="
echo "Vernis v3 - Preload Package Builder"
echo "Mode: $MODE"
echo "=========================================="
echo ""

# Create directory structure
echo "[1/4] Creating preload directory structure..."
mkdir -p "$PRELOAD_DIR/csv-library"
if [ "$MODE" = "full" ]; then
    mkdir -p "$PRELOAD_DIR/nfts"
fi

echo "  ✓ Directory structure created"

# Check for CSV files
echo ""
echo "[2/4] Looking for CSV collections..."
CSV_COUNT=0

# Check if user has a csv-collections directory
if [ -d "./csv-collections" ]; then
    echo "  Found csv-collections directory"
    cp ./csv-collections/*.csv "$PRELOAD_DIR/csv-library/" 2>/dev/null || true
    cp ./csv-collections/*.json "$PRELOAD_DIR/csv-library/" 2>/dev/null || true
    CSV_COUNT=$(find "$PRELOAD_DIR/csv-library" -name "*.csv" | wc -l)
fi

if [ $CSV_COUNT -eq 0 ]; then
    echo ""
    echo "  ⚠️  No CSV files found!"
    echo ""
    echo "  Please add CSV files to one of:"
    echo "    - $PRELOAD_DIR/csv-library/"
    echo "    - ./csv-collections/"
    echo ""
    echo "  CSV format:"
    echo "    contract_address,token_id"
    echo "    0xABC...,1"
    echo "    0xDEF...,2"
    echo ""
    echo "  Optional: Add matching .json metadata files"
    echo ""
    read -p "Press Enter to continue once files are added..."
    CSV_COUNT=$(find "$PRELOAD_DIR/csv-library" -name "*.csv" | wc -l)
fi

echo "  ✓ Found $CSV_COUNT CSV collection(s)"

# Full mode: Download NFTs
if [ "$MODE" = "full" ]; then
    echo ""
    echo "[3/4] Downloading NFTs for full mode..."
    echo "  This may take a while depending on collection size..."
    echo ""

    for csv in "$PRELOAD_DIR/csv-library"/*.csv; do
        if [ -f "$csv" ]; then
            filename=$(basename "$csv")
            echo "  Downloading: $filename"

            # Run the downloader
            python3 scripts/nft_downloader.py \
                --csv "$csv" \
                --output "$PRELOAD_DIR/nfts" \
                --workers 4 || echo "    ⚠️  Some downloads may have failed"
        fi
    done

    NFT_COUNT=$(find "$PRELOAD_DIR/nfts" -type f | wc -l)
    echo ""
    echo "  ✓ Downloaded $NFT_COUNT NFT files"
else
    echo ""
    echo "[3/4] Skipping NFT download (lite mode)"
fi

# Create package info
echo ""
echo "[4/4] Creating package info..."

cat > "$PRELOAD_DIR/package-info.txt" <<EOF
Vernis v3 Preload Package
Generated: $(date)
Mode: $MODE
CSV Collections: $CSV_COUNT
EOF

if [ "$MODE" = "full" ]; then
    echo "NFT Files: $NFT_COUNT" >> "$PRELOAD_DIR/package-info.txt"

    # Calculate size
    SIZE=$(du -sh "$PRELOAD_DIR/nfts" 2>/dev/null | cut -f1)
    echo "Total Size: $SIZE" >> "$PRELOAD_DIR/package-info.txt"
fi

cat >> "$PRELOAD_DIR/package-info.txt" <<EOF

Deployment Instructions:
1. Copy this preload-package folder to /home/pi/preload on target device
2. Run: sudo bash vernis/scripts/preload-device.sh $MODE /home/pi/preload

Or place it before running install.sh for automatic detection.
EOF

echo "  ✓ Package info created"

# Create compressed archive
echo ""
echo "Creating compressed archive..."
ARCHIVE_NAME="vernis-preload-${MODE}-${TIMESTAMP}.tar.gz"
tar -czf "$ARCHIVE_NAME" -C "$PRELOAD_DIR" .

ARCHIVE_SIZE=$(du -sh "$ARCHIVE_NAME" | cut -f1)

echo ""
echo "=========================================="
echo "Preload Package Ready!"
echo "=========================================="
echo ""
echo "Mode: $MODE"
echo "CSV Collections: $CSV_COUNT"
if [ "$MODE" = "full" ]; then
    echo "NFT Files: $NFT_COUNT"
fi
echo ""
echo "Package:"
echo "  Directory: $PRELOAD_DIR/"
echo "  Archive: $ARCHIVE_NAME ($ARCHIVE_SIZE)"
echo ""
echo "To deploy:"
echo "  1. Copy to device:"
echo "     scp -r $PRELOAD_DIR pi@vernis.local:/home/pi/preload"
echo ""
echo "  2. SSH and run preload:"
echo "     ssh pi@vernis.local 'sudo bash vernis/scripts/preload-device.sh $MODE /home/pi/preload'"
echo ""
echo "Or extract archive on device first:"
echo "  scp $ARCHIVE_NAME pi@vernis.local:/home/pi/"
echo "  ssh pi@vernis.local 'mkdir -p preload && tar -xzf $ARCHIVE_NAME -C preload/'"
echo ""
echo "=========================================="
