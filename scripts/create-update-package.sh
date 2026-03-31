#!/bin/bash
##############################################
# Vernis v3 - Update Package Creator
# Run this on your dev machine to create an update bundle
# Usage: bash scripts/create-update-package.sh
# Output: vernis-update-YYYYMMDD-HHMMSS.tar.gz
##############################################

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VERSION=$(date +%Y%m%d-%H%M%S)
OUTPUT="vernis-update-$VERSION.tar.gz"
TEMP_DIR="/tmp/vernis-package-$$"

echo "Creating Vernis update package: $OUTPUT"
echo "Source: $PROJECT_DIR"

# Create temporary directory structure
mkdir -p "$TEMP_DIR"/{www,scripts,systemd}

# Copy web files
echo "Copying web files..."
cp "$PROJECT_DIR"/*.html "$TEMP_DIR/www/"
cp "$PROJECT_DIR"/*.css "$TEMP_DIR/www/" 2>/dev/null || true
cp "$PROJECT_DIR"/*.js "$TEMP_DIR/www/" 2>/dev/null || true
cp "$PROJECT_DIR"/*.json "$TEMP_DIR/www/" 2>/dev/null || true
cp "$PROJECT_DIR"/*.svg "$TEMP_DIR/www/" 2>/dev/null || true
if [ -d "$PROJECT_DIR/assets" ]; then
    mkdir -p "$TEMP_DIR/www/assets"
    cp "$PROJECT_DIR"/assets/* "$TEMP_DIR/www/assets/" 2>/dev/null || true
fi

# Copy backend
echo "Copying backend..."
cp "$PROJECT_DIR/backend/app.py" "$TEMP_DIR/"

# Copy scripts
echo "Copying scripts..."
cp "$PROJECT_DIR"/scripts/*.sh "$TEMP_DIR/scripts/" 2>/dev/null || true
cp "$PROJECT_DIR"/scripts/*.py "$TEMP_DIR/scripts/" 2>/dev/null || true
cp "$PROJECT_DIR"/scripts/*.c "$TEMP_DIR/scripts/" 2>/dev/null || true

# Copy systemd files if they exist
if [ -d "$PROJECT_DIR/systemd" ]; then
    cp "$PROJECT_DIR"/systemd/*.service "$TEMP_DIR/systemd/" 2>/dev/null || true
    cp "$PROJECT_DIR"/systemd/*.timer "$TEMP_DIR/systemd/" 2>/dev/null || true
fi

# Create tarball
echo "Creating tarball..."
cd "$TEMP_DIR"
tar -czf "$PROJECT_DIR/$OUTPUT" .
cd "$PROJECT_DIR"

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
echo "=========================================="
echo "Update package created: $OUTPUT"
echo "Size: $(du -h "$OUTPUT" | cut -f1)"
echo "=========================================="
