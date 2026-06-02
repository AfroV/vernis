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
import requests
import zipfile
from datetime import datetime

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
GITHUB_CONFIG_FILE = BASE_DIR / "github-config.json"

NFT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CSV_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

print(f"✅ Using local test directory: {BASE_DIR}")

def get_github_config():
    """Get GitHub configuration"""
    if GITHUB_CONFIG_FILE.exists():
        try:
            with open(GITHUB_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {
        "enabled": False,
        "owner": "",
        "repo": "",
        "path": "",
        "token": ""
    }

def fetch_github_csv_files():
    """Fetch list of CSV files from GitHub repository"""
    config = get_github_config()

    if not config.get('enabled', False):
        return []

    owner = config.get('owner', '').strip()
    repo = config.get('repo', '').strip()
    path = config.get('path', '').strip()
    token = config.get('token', '').strip()

    if not owner or not repo:
        return []

    try:
        # GitHub API URL
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

        # Headers for authentication
        headers = {}
        if token:
            headers['Authorization'] = f"token {token}"
        headers['Accept'] = 'application/vnd.github.v3+json'

        # Fetch directory contents
        response = requests.get(api_url, headers=headers, timeout=10)

        if response.status_code != 200:
            return []

        files = response.json()

        # Filter for CSV files
        csv_files = []
        for file in files:
            if file['type'] == 'file' and file['name'].endswith('.csv'):
                csv_files.append({
                    'filename': file['name'],
                    'name': file['name'].replace('.csv', '').replace('_', ' ').title(),
                    'description': 'Collection from GitHub',
                    'size': f"{file['size']/1024:.1f} KB" if file['size'] < 1024**2 else f"{file['size']/(1024**2):.1f} MB",
                    'count': '?',
                    'source': 'github',
                    'download_url': file['download_url'],
                    'featured': False
                })

        return csv_files
    except Exception as e:
        print(f"Error fetching GitHub files: {e}")
        return []
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

        for ext in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'mp4']:
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

@app.route("/api/csv-library")
def csv_library():
    """List all available CSV collections in the library (local + GitHub)"""
    try:
        collections = []

        # Scan local CSV library directory
        for csv_file in CSV_LIBRARY_DIR.glob("*.csv"):
            # Try to read metadata file if exists
            meta_file = csv_file.with_suffix('.json')
            metadata = {}

            if meta_file.exists():
                try:
                    with open(meta_file, 'r') as f:
                        metadata = json.load(f)
                except:
                    pass

            # Count lines in CSV (excluding header)
            try:
                with open(csv_file, 'r') as f:
                    count = sum(1 for line in f) - 1
            except:
                count = 0

            # Get file size
            size_bytes = csv_file.stat().st_size
            if size_bytes < 1024:
                size = f"{size_bytes} B"
            elif size_bytes < 1024**2:
                size = f"{size_bytes/1024:.1f} KB"
            else:
                size = f"{size_bytes/(1024**2):.1f} MB"

            collections.append({
                "filename": csv_file.name,
                "name": metadata.get("name", csv_file.stem.replace('_', ' ').title()),
                "description": metadata.get("description", "NFT collection"),
                "count": count,
                "size": size,
                "source": "local",
                "featured": metadata.get("featured", False)
            })

        # Add GitHub CSV files
        github_files = fetch_github_csv_files()
        collections.extend(github_files)

        # Sort by featured first, then by name
        collections.sort(key=lambda x: (not x["featured"], x["name"]))

        return jsonify(collections)  # Return array directly for local version
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/csv-library/download/<filename>")
def download_csv(filename):
    """Download a CSV file from the library (local or GitHub)"""
    try:
        # Security: prevent directory traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            return jsonify({"error": "Invalid filename"}), 400

        csv_path = CSV_LIBRARY_DIR / filename

        # If file exists locally, serve it
        if csv_path.exists():
            return send_from_directory(CSV_LIBRARY_DIR, filename, as_attachment=True)

        # Otherwise, try to fetch from GitHub
        github_files = fetch_github_csv_files()
        for file in github_files:
            if file['filename'] == filename:
                # Download from GitHub
                response = requests.get(file['download_url'], timeout=30)
                if response.status_code == 200:
                    # Save to local library
                    with open(csv_path, 'wb') as f:
                        f.write(response.content)
                    return send_from_directory(CSV_LIBRARY_DIR, filename, as_attachment=True)

        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/csv-library/install", methods=["POST"])
def install_csv_collection():
    """Install a CSV collection from the library and start downloading NFTs"""
    try:
        data = request.json
        filename = data.get('filename', '').strip()

        # Security: prevent directory traversal
        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            return jsonify({"error": "Invalid filename"}), 400

        csv_path = CSV_LIBRARY_DIR / filename

        # If file doesn't exist locally, try to fetch from GitHub
        if not csv_path.exists():
            github_files = fetch_github_csv_files()
            found = False
            for file in github_files:
                if file['filename'] == filename:
                    # Download from GitHub
                    response = requests.get(file['download_url'], timeout=30)
                    if response.status_code == 200:
                        with open(csv_path, 'wb') as f:
                            f.write(response.content)
                        found = True
                        break

            if not found:
                return jsonify({"error": "Collection not found"}), 404

        # Copy to uploads directory
        dest_path = UPLOAD_DIR / filename
        shutil.copy2(csv_path, dest_path)

        # Get workers parameter (default: 2)
        workers = data.get('workers', '2')

        # For local testing, just return success without actually downloading
        # (You can implement actual download logic here if needed)
        return jsonify({
            "success": True,
            "message": f"Installing {filename} with {workers} workers (LOCAL TEST - no actual download)"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/backup/create", methods=["POST"])
def create_backup():
    """Create a backup archive of all NFTs and CSV files"""
    try:
        # Use BASE_DIR for local testing
        backup_dir = BASE_DIR / "backup"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Generate timestamp for filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"vernis_backup_{timestamp}.zip"
        backup_path = backup_dir / backup_filename

        # Create zip file
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add all NFT files
            if NFT_DIR.exists():
                for file_path in NFT_DIR.glob("*"):
                    if file_path.is_file():
                        zipf.write(file_path, f"nfts/{file_path.name}")

            # Add all CSV library files
            if CSV_LIBRARY_DIR.exists():
                for file_path in CSV_LIBRARY_DIR.glob("*.csv"):
                    if file_path.is_file():
                        zipf.write(file_path, f"csv-library/{file_path.name}")

            # Add all uploaded CSV files
            if UPLOAD_DIR.exists():
                for file_path in UPLOAD_DIR.glob("*.csv"):
                    if file_path.is_file():
                        zipf.write(file_path, f"uploads/{file_path.name}")

        # Get file size
        size_bytes = backup_path.stat().st_size
        size_mb = size_bytes / (1024 * 1024)

        return jsonify({
            "success": True,
            "filename": backup_filename,
            "size": f"{size_mb:.1f} MB",
            "message": f"Backup created: {backup_filename}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/backup/download/<filename>")
def download_backup(filename):
    """Download a backup file"""
    try:
        backup_dir = BASE_DIR / "backup"

        # Security: prevent directory traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            return jsonify({"error": "Invalid filename"}), 400

        backup_path = backup_dir / filename

        if not backup_path.exists():
            return jsonify({"error": "Backup file not found"}), 404

        return send_from_directory(backup_dir, filename, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/backup/list")
def list_backups():
    """List all available backup files"""
    try:
        backup_dir = BASE_DIR / "backup"
        backups = []

        if backup_dir.exists():
            for backup_file in backup_dir.glob("vernis_backup_*.zip"):
                size_bytes = backup_file.stat().st_size
                size_mb = size_bytes / (1024 * 1024)

                backups.append({
                    "filename": backup_file.name,
                    "size": f"{size_mb:.1f} MB",
                    "created": datetime.fromtimestamp(backup_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })

        # Sort by newest first
        backups.sort(key=lambda x: x["created"], reverse=True)

        return jsonify({"backups": backups})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/system/version")
def system_version():
    """Get system version information (LOCAL TEST)"""
    return jsonify({
        "vernis_version": "3.0.0",
        "os_version": "macOS (Local Test)",
        "kernel_version": "Local Development"
    })

@app.route("/api/system/check-updates")
def check_updates():
    """Check for available system updates (LOCAL TEST)"""
    import random
    update_count = random.randint(0, 15)

    sample_packages = ["chromium", "python3", "nodejs", "nginx", "systemd"] if update_count > 0 else []

    return jsonify({
        "updates_available": update_count > 0,
        "update_count": update_count,
        "sample_packages": sample_packages[:5],
        "message": f"{update_count} updates available" if update_count > 0 else "System is up to date"
    })

@app.route("/api/system/update", methods=["POST"])
def system_update():
    """Perform system update (LOCAL TEST - does nothing)"""
    return jsonify({
        "success": True,
        "message": "LOCAL TEST: Update simulated (no actual update performed)"
    })

@app.route("/api/github-config", methods=["GET", "POST"])
def github_config():
    """Get or set GitHub configuration for CSV library"""
    if request.method == "POST":
        try:
            config = request.json

            # Validate required fields
            if config.get('enabled', False):
                if not config.get('owner') or not config.get('repo'):
                    return jsonify({"error": "Owner and repo are required when enabled"}), 400

            # Save configuration
            with open(GITHUB_CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)

            return jsonify({"success": True, "message": "GitHub configuration saved"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        try:
            config = get_github_config()
            return jsonify(config)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route("/api/screen/rotation", methods=["GET", "POST"])
def screen_rotation():
    """Get or set screen rotation (LOCAL TEST - simulated)"""
    ROTATION_FILE = BASE_DIR / "rotation-config.json"

    if request.method == "POST":
        try:
            data = request.json
            rotation = data.get('rotation', 0)

            # Validate rotation value
            if rotation not in [0, 90, 180, 270]:
                return jsonify({"error": "Invalid rotation value. Must be 0, 90, 180, or 270"}), 400

            # Save rotation state
            with open(ROTATION_FILE, 'w') as f:
                json.dump({"rotation": rotation}, f)

            # In local test mode, we can't actually rotate the screen
            return jsonify({
                "success": True,
                "rotation": rotation,
                "message": f"Rotation set to {rotation}° (simulated in local test mode)"
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        # GET - return current rotation
        try:
            if ROTATION_FILE.exists():
                with open(ROTATION_FILE, 'r') as f:
                    config = json.load(f)
                    return jsonify(config)
            else:
                return jsonify({"rotation": 0})
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
            "/api/download-status",
            "/api/csv-library",
            "/api/github-config"
        ]
    })

@app.route("/<path:filename>")
def serve_static(filename):
    """Serve HTML, CSS, JS files from parent directory"""
    parent_dir = Path(__file__).parent.parent

    # Security: only serve specific file types
    allowed_extensions = ['.html', '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico']
    if not any(filename.endswith(ext) for ext in allowed_extensions):
        return jsonify({"error": "File type not allowed"}), 403

    # Security: prevent directory traversal
    if ".." in filename or filename.startswith("/"):
        return jsonify({"error": "Invalid filename"}), 403

    file_path = parent_dir / filename
    if file_path.exists():
        return send_from_directory(parent_dir, filename)
    else:
        return jsonify({"error": "File not found"}), 404

if __name__ == "__main__":
    print("\n" + "="*50)
    print("🎨 Vernis v3 - Local Test API Server")
    print("="*50)
    print(f"NFT Directory: {NFT_DIR}")
    print(f"Config Directory: {BASE_DIR}")
    print("\n📡 Server: http://localhost:5001")
    print("\n📄 Pages:")
    print("   • Library:  http://localhost:5001/library-local.html")
    print("   • Settings: http://localhost:5001/settings-local.html")
    print("   • Home:     http://localhost:5001/index-local.html")
    print("\n🔌 API Endpoints:")
    print("   • http://localhost:5001/api/pinned-art")
    print("   • http://localhost:5001/api/csv-library")
    print("   • http://localhost:5001/api/github-config")
    print("\nPress Ctrl+C to stop")
    print("="*50 + "\n")

    app.run(debug=True, host='0.0.0.0', port=5001)
