#!/bin/bash
##############################################
# Vernis v3 - Update Package Creator
# Run this on your dev machine to create an update bundle
##############################################

VERSION=$(date +%Y%m%d-%H%M%S)
PACKAGE_NAME="vernis-update-$VERSION.tar.gz"

echo "Creating Vernis update package: $PACKAGE_NAME"

# Create temporary directory structure
mkdir -p "$TEMP"/{www,scripts,systemd}

# Copy files
echo "Copying files..."
cp *.html "$TEMP/www/"
cp backend/app.py "$TEMP/"
cp scripts/*.sh scripts/*.py "$TEMP/scripts/" 2>/dev/null || true
cp systemd/*.service systemd/*.timer "$TEMP/systemd/" 2>/dev/null || true

# Create tarball
cd "$TEMP"
tar -czf "../$OUTPUT" .
cd ..

# Cleanup
rm -rf "$TEMP"

echo "Update package created: $OUTPUT"
echo "Upload this to your server at: $UPDATE_URL"
