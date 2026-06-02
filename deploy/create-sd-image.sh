#!/bin/bash
#
# Vernis v3 - SD Card Image Creator
#
# This script creates a deployable SD card image for Vernis devices
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERNIS_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$VERNIS_DIR/release"

# Configuration
IMAGE_NAME="vernis-v3-$(date +%Y%m%d).img"
IMAGE_SIZE="8G"  # Adjust based on needs

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Vernis v3 - SD Card Image Creator       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}Note: Some operations may require sudo${NC}"
fi

mkdir -p "$OUTPUT_DIR"

echo -e "${GREEN}Step 1/5:${NC} Preparing base image..."
echo ""
echo "Choose your deployment method:"
echo ""
echo "  1. Create installation package (TAR archive) - RECOMMENDED"
echo "     • Easy to deploy on any Raspberry Pi OS"
echo "     • Smaller download size"
echo "     • Works with existing installations"
echo ""
echo "  2. Create full SD card image (IMG file)"
echo "     • Complete system image"
echo "     • Requires base OS image as input"
echo "     • Larger file size"
echo ""
read -p "Select option (1 or 2): " choice

case $choice in
    1)
        echo ""
        echo -e "${GREEN}Creating installation package...${NC}"

        PACKAGE_NAME="vernis-v3-$(date +%Y%m%d).tar.gz"
        PACKAGE_PATH="$OUTPUT_DIR/$PACKAGE_NAME"

        # Create deployment package
        cd "$VERNIS_DIR/.."
        tar -czf "$PACKAGE_PATH" \
            --exclude='vernisv3/.git' \
            --exclude='vernisv3/nfts/*' \
            --exclude='vernisv3/uploads/*' \
            --exclude='vernisv3/__pycache__' \
            --exclude='vernisv3/release' \
            vernisv3/

        echo ""
        echo -e "${GREEN}✓ Package created successfully!${NC}"
        echo ""
        echo "Package: $PACKAGE_PATH"
        echo "Size: $(du -h "$PACKAGE_PATH" | cut -f1)"
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "Deployment Instructions:"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        echo "1. Flash Raspberry Pi OS Lite to SD card"
        echo ""
        echo "2. Boot the Pi and copy this package:"
        echo "   scp $PACKAGE_NAME pi@raspberrypi.local:/tmp/"
        echo ""
        echo "3. SSH into the Pi and extract:"
        echo "   cd /tmp"
        echo "   tar -xzf $PACKAGE_NAME"
        echo "   sudo mv vernisv3 /opt/vernis"
        echo ""
        echo "4. Run first-boot setup:"
        echo "   cd /opt/vernis/deploy"
        echo "   sudo bash first-boot-setup.sh"
        echo ""
        echo "5. Access Vernis at: http://vernis.local"
        echo ""
        ;;

    2)
        echo ""
        echo "Full image creation requires:"
        echo "  • Base Raspberry Pi OS image"
        echo "  • Loop device support"
        echo "  • Significant disk space"
        echo ""
        read -p "Path to base OS image (e.g., raspios-lite.img): " BASE_IMAGE

        if [ ! -f "$BASE_IMAGE" ]; then
            echo "Error: Base image not found: $BASE_IMAGE"
            exit 1
        fi

        echo ""
        echo "This feature requires manual image modification."
        echo "Please use the TAR package method (option 1) for easier deployment."
        echo ""
        echo "For advanced users:"
        echo "  1. Mount the base image"
        echo "  2. Copy Vernis files to /opt/vernis"
        echo "  3. Add first-boot-setup.sh to /etc/rc.local"
        echo "  4. Unmount and distribute"
        echo ""
        ;;

    *)
        echo "Invalid option"
        exit 1
        ;;
esac

# Create installer script
echo ""
echo -e "${GREEN}Creating quick installer script...${NC}"

cat > "$OUTPUT_DIR/install-vernis.sh" << 'EOF'
#!/bin/bash
#
# Vernis Quick Installer
#

set -e

echo "╔════════════════════════════════════════════╗"
echo "║        Vernis v3 Quick Installer          ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash install-vernis.sh"
    exit 1
fi

# Detect if package is in same directory
PACKAGE=$(ls vernis-v3-*.tar.gz 2>/dev/null | head -n1)

if [ -z "$PACKAGE" ]; then
    echo "Error: Vernis package not found in current directory"
    echo "Please download vernis-v3-YYYYMMDD.tar.gz first"
    exit 1
fi

echo "Found package: $PACKAGE"
echo ""
echo "Installing Vernis v3..."
echo ""

# Extract to /opt
tar -xzf "$PACKAGE" -C /opt/
mv /opt/vernisv3 /opt/vernis 2>/dev/null || true

# Run first-boot setup
cd /opt/vernis/deploy
bash first-boot-setup.sh

echo ""
echo "Installation complete!"
echo "Access Vernis at: http://vernis.local"
EOF

chmod +x "$OUTPUT_DIR/install-vernis.sh"

echo ""
echo -e "${GREEN}✓ All files created in:${NC} $OUTPUT_DIR"
echo ""
ls -lh "$OUTPUT_DIR"
echo ""
