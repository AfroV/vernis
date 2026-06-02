# Vernis v3 - Local Testing Script (Mac)
# Quickly test Vernis on your Mac before flashing to Pi

set -e

echo "=========================================="
echo "Vernis v3 - Local Testing Setup"
echo "=========================================="
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Create local test directories
echo "[1/6] Creating local test directories..."
mkdir -p ./local-test/nfts
mkdir -p ./local-test/uploads
mkdir -p ./local-test/csv-library
mkdir -p ./local-test/scripts

# Copy scripts
if [ -d "./scripts" ]; then
    cp -r scripts/* ./local-test/scripts/ 2>/dev/null || true
fi

# Create config files
echo "[2/6] Creating test config files..."
echo '{"downloads":[]}' > ./local-test/download-status.json
echo '[]' > ./local-test/hidden-nfts.json
echo '{"image_duration":15,"video_duration":30,"frosted_background":false,"force_horizontal":false,"shuffle":true}' > ./local-test/display-config.json
echo '{"device_mode":"full","version":"3.0.0"}' > ./local-test/device-config.json

# Check Python
echo "[3/6] Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found! Please install Python 3.8+"
    exit 1
fi
echo "✅ Python 3 found: $(python3 --version)"

# Install dependencies
echo "[4/6] Installing Python dependencies..."
pip3 install flask requests --quiet || {
    echo "⚠️  Warning: Could not install dependencies. Trying to continue..."
}

# Create local version of app.py
echo "[5/6] Creating local Flask app..."
cat > backend/app-local.py << 'EOF'
#!/usr/bin/env python3
"""
# Vernis v3 - Flask API (LOCAL TEST VERSION)
# Modified paths for local Mac testing
"""
from flask import Flask, request, jsonify, send_from_directory
import subprocess
import os
import json
from pathlib import Path
import shutil

app = Flask(__name__)

# Configuration - LOCAL PATHS
BASE_DIR = Path(__file__).parent.parent / "local-test"
NFT_DIR = BASE_DIR / "nfts"
UPLOAD_DIR = BASE_DIR / "uploads"
SCRIPTS_DIR = BASE_DIR / "scripts"
CSV_LIBRARY_DIR = BASE_DIR / "csv-library"
CONFIG_FILE = BASE_DIR / "device-config.json"
DOWNLOAD_STATUS_FILE = BASE_DIR / "download-status.json"
HIDDEN_NFTS_FILE = BASE_DIR / "hidden-nfts.json"
DISPLAY_CONFIG_FILE = BASE_DIR / "display-config.json"

NFT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CSV_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

print(f"✅ Using local test directory: {BASE_DIR}")
print(f"✅ NFT directory: {NFT_DIR}")

@app.route("/api/pinned-art")
def pinned_art():
    """Return list of all pinned artwork URLs"""
    try:
        files = []
        for ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4']:
            files.extend([f"/nfts/{f.name}" for f in NFT_DIR.glob(f"*.{ext}")])
        return jsonify(files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/nfts/<path:filename>")
def serve_nft(filename):
    """Serve NFT files"""
    return send_from_directory(NFT_DIR, filename)

@app.route("/api/status")
def status():
    """Get system status"""
    try:
        nft_count = len(list(NFT_DIR.glob("*.*")))

        return jsonify({
            "nft_count": nft_count,
            "storage_used": "N/A (local test)",
            "storage_total": "N/A (local test)",
            "wifi_connected": True,
            "wifi_ssid": "Local Test Network",
            "local_test": True
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/device-config")
def device_config():
    """Get device configuration"""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        else:
            config = {"device_mode": "full", "version": "3.0.0"}
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/display-config", methods=["GET", "POST"])
def display_config():
    """Get or set display configuration"""
    try:
        if request.method == "POST":
            data = request.json
            with open(DISPLAY_CONFIG_FILE, 'w') as f:
                json.dump(data, f)
            return jsonify({"success": True, "config": data})
        else:
            if DISPLAY_CONFIG_FILE.exists():
                with open(DISPLAY_CONFIG_FILE, 'r') as f:
                    config = json.load(f)
            else:
                config = {
                    "image_duration": 15,
                    "video_duration": 30,
                    "frosted_background": False,
                    "force_horizontal": False,
                    "shuffle": True
                }
            return jsonify(config)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/nft-list-detailed")
def nft_list_detailed():
    """List all NFTs with detailed metadata"""
    try:
        nfts = []
        hidden = []

        if HIDDEN_NFTS_FILE.exists():
            with open(HIDDEN_NFTS_FILE, 'r') as f:
                hidden = json.load(f)

        for ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4']:
            for file in NFT_DIR.glob(f"*.{ext}"):
                stat = file.stat()
                nfts.append({
                    "filename": file.name,
                    "url": f"/nfts/{file.name}",
                    "size": stat.st_size,
                    "modified": int(stat.st_mtime),
                    "hidden": file.name in hidden,
                    "type": "video" if ext == "mp4" else "image"
                })

        return jsonify(nfts)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/nft-visibility", methods=["POST"])
def nft_visibility():
    """Hide or show NFTs"""
    try:
        data = request.json
        filenames = data.get('filenames', [])
        action = data.get('action', 'hide')  # hide or show

        # Load current hidden list
        if HIDDEN_NFTS_FILE.exists():
            with open(HIDDEN_NFTS_FILE, 'r') as f:
                hidden = json.load(f)
        else:
            hidden = []

        if action == 'hide':
            for filename in filenames:
                if filename not in hidden:
                    hidden.append(filename)
        elif action == 'show':
            hidden = [f for f in hidden if f not in filenames]

        # Save updated list
        with open(HIDDEN_NFTS_FILE, 'w') as f:
            json.dump(hidden, f)

        return jsonify({"success": True, "hidden_count": len(hidden)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/download-status")
def download_status():
    """Get CSV download status"""
    try:
        if DOWNLOAD_STATUS_FILE.exists():
            with open(DOWNLOAD_STATUS_FILE, 'r') as f:
                status = json.load(f)
        else:
            status = {"downloads": []}

        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/health/storage")
def health_storage():
    """Get storage health metrics (MOCK for Local Test)"""
    try:
        # Mocking SD card like stats or using local
        total, used, free = shutil.disk_usage("/")
        usage_percent = (used / total) * 100
        
        # Mock read only status (always false for local)
        is_ro = False
        
        health_status = "Healthy"
        if usage_percent > 90:
            health_status = "Critical Space"
        
        return jsonify({
            "usage_percent": round(usage_percent, 1),
            "total_gb": round(total / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1),
            "is_read_only": is_ro,
            "status": health_status,
            "message": "Filesystem writable (Local Mac)"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/")
def home():
    """Root endpoint"""
    return jsonify({
        "service": "Vernis v3 API",
        "version": "3.0.0",
        "mode": "LOCAL TEST",
        "endpoints": [
            "/api/pinned-art",
            "/api/status",
            "/api/device-config",
            "/api/display-config",
            "/api/nft-list-detailed",
            "/api/nft-visibility",
            "/api/download-status"
        ]
    })

if __name__ == "__main__":
    print("\n" + "="*50)
    print("🎨 Vernis v3 - Local Test API Server")
    print("="*50)
    print(f"NFT Directory: {NFT_DIR}")
    print(f"Config Directory: {BASE_DIR}")
    print("\nAPI running at: http://localhost:5001")
    print("Test endpoint: http://localhost:5001/api/pinned-art")
    print("\nPress Ctrl+C to stop")
    print("="*50 + "\n")

    app.run(debug=True, host='0.0.0.0', port=5001)
EOF

chmod +x backend/app-local.py

# Add sample test images
echo "[6/6] Adding sample test images..."
if command -v curl &> /dev/null; then
    curl -s -o "./local-test/nfts/sample1.jpg" "https://picsum.photos/800/600" 2>/dev/null || true
    curl -s -o "./local-test/nfts/sample2.jpg" "https://picsum.photos/600/800" 2>/dev/null || true
    echo "✅ Added 2 sample images"
else
    echo "⚠️  curl not found, skipping sample images"
fi

echo ""
echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Start Flask API:"
echo "   python3 backend/app-local.py"
echo ""
echo "2. In a NEW terminal, start web server:"
echo "   cd \"$SCRIPT_DIR\""
echo "   python3 -m http.server 8000"
echo ""
echo "3. Open in browser:"
echo "   http://localhost:8000/index.html"
echo ""
echo "API endpoints:"
echo "   http://localhost:5000/api/pinned-art"
echo "   http://localhost:5000/api/status"
echo ""
echo "=========================================="
echo ""

# Ask if user wants to start servers now
read -p "Start Flask API server now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Starting Flask API..."
    echo "Press Ctrl+C to stop"
    echo ""
    python3 backend/app-local.py
fi
