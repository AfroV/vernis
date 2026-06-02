#!/usr/bin/env python3
import os
import json
import time
import random
from pathlib import Path
from flask import Flask, send_from_directory, jsonify, request, send_file

app = Flask(__name__, static_folder='.')

# --- Configuration & State ---
BASE_DIR = Path("local-test")
CSV_LIB_DIR = BASE_DIR / "csv-library"
NFT_DIR = BASE_DIR / "nfts"
UPLOADS_DIR = BASE_DIR / "uploads"
STATE_FILE = BASE_DIR / "state.json"

# Ensure directories exist
for d in [BASE_DIR, CSV_LIB_DIR, NFT_DIR, UPLOADS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Mock State
state = {
    "downloads": {},  # filename -> {progress, pinned, total, status}
    "pinned_files": [],
    "hidden_nfts": [],
    "theme": "classic",
    "display_config": {
        "image_duration": 15,
        "video_duration": 30,
        "frosted_background": False,
        "force_horizontal": False,
        "shuffle": True
    }
}

# --- Helper Functions ---
def get_mock_storage():
    return {
        "used": "10.5 GB",
        "total": "32.0 GB",
        "free": "21.5 GB",
        "usage_percent": 32.8
    }

# --- Routes ---

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    # Check if file exists in root
    if os.path.exists(path):
        return send_from_directory('.', path)
    # Check if it is an NFT
    if path.startswith('nfts/'):
        return send_from_directory(NFT_DIR, path.replace('nfts/', ''))
    return "File not found", 404

# --- API Endpoints ---

@app.route('/api/status')
def api_status():
    return jsonify({
        "statusText": "Online",
        "ssid": "Test WiFi",
        "ip_address": "127.0.0.1",
        "pinned": len(state["pinned_files"]),
        "ipfs_running": True,
        "ipfs_pinned": len(state["pinned_files"]),
        "storage": get_mock_storage(),
        "storage_warning": None
    })

@app.route('/api/cards')
def api_cards():
    return jsonify({
        "cards": [
            {
                "title": "Welcome to Vernis",
                "description": "This is a local test environment.",
                "link": "#",
                "button": "Cool"
            }
        ]
    })

@app.route('/api/qrcode')
def api_qrcode():
    # Return a dummy image (1x1 transparent pixel or similar, or generate one)
    # For now, let's just return a placeholder logic or 404 handled gracefully by frontend
    # Creating a simple SVG QR mock
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200"><rect width="200" height="200" fill="#eee"/><text x="100" y="100" text-anchor="middle" dominant-baseline="middle" font-family="Arial" fill="#333">QR Code Mock</text></svg>'
    from io import BytesIO
    return send_file(BytesIO(svg.encode('utf-8')), mimetype='image/svg+xml')

@app.route('/api/screen/off', methods=['POST'])
def api_screen_off():
    print(" [MOCK] Screen turned off")
    return jsonify({"success": True})

@app.route('/api/shutdown')
def api_shutdown():
    print(" [MOCK] Shutdown requested")
    return jsonify({"success": True})

# --- Add Art API ---

@app.route('/api/quick-add-cid', methods=['POST'])
def api_quick_add():
    data = request.json
    cid = data.get('cid')
    name = data.get('name')
    print(f" [MOCK] Quick Add: {cid} ({name})")
    
    # Simulate adding
    entry = {"filename": f"{cid}.jpg", "cid": cid, "name": name}
    state["pinned_files"].append(entry)
    
    # Create dummy file
    (NFT_DIR / f"{cid}.jpg").touch()
    
    return jsonify({"success": True, "message": f"Added {name}"})

@app.route('/api/csv-library/upload', methods=['POST'])
def api_csv_upload():
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file part"})
    
    file = request.files['file']
    name = request.form.get('name')
    if file.filename == '':
        return jsonify({"success": False, "error": "No selected file"})
        
    if file:
        filename = file.filename
        save_path = CSV_LIB_DIR / filename
        file.save(save_path)
        
        # Count lines
        count = 0
        with open(save_path, 'r') as f:
            count = sum(1 for line in f) - 1 # minus header
            
        print(f" [MOCK] CSV Uploaded: {filename} ({count} items)")
        return jsonify({"success": True, "filename": filename, "count": count, "message": "Upload successful"})

# --- Library API ---

@app.route('/api/csv-library/list')
def api_library_list():
    collections = []
    for f in CSV_LIB_DIR.glob("*.csv"):
        # Mock parsing to get name/count
        collections.append({
            "filename": f.name,
            "name": f.stem.replace('-', ' ').title(),
            "count": 10,  # Mock count
            "source": "upload"
        })
    return jsonify(collections)

@app.route('/api/csv-library/status/<path:filename>')
def api_library_status(filename):
    # Return mock status
    # Check mock state
    mock_stat = state["downloads"].get(filename, {
        "downloaded": 0,
        "pinned": 0,
        "total": 10,
        "percent_downloaded": 0,
        "percent_pinned": 0,
        "active": False
    })
    return jsonify(mock_stat)

@app.route('/api/library/install', methods=['POST']) # Is this used? Or just pin-downloaded?
# Library.html seemed to have 'Install & Pin' which likely triggers install
def api_library_install():
    # If this endpoint exists
    return jsonify({"success": True})

@app.route('/api/csv-library/pin-downloaded', methods=['POST'])
def api_pin_downloaded():
    data = request.json
    filename = data.get('filename')
    print(f" [MOCK] Pinning {filename}")
    
    # Update mock state
    start_mock_download(filename, pin=True)
    
    return jsonify({"success": True, "message": "Pinning started", "pinned": 0}) 

@app.route('/api/download-progress')
def api_download_progress():
    # Find any active download in state
    for filename, stat in state["downloads"].items():
        if stat["active"]:
            # Increment progress
            stat["downloaded"] += 1
            if stat["downloaded"] >= stat["total"]:
                stat["downloaded"] = stat["total"]
                stat["active"] = False
            
            stat["percent_downloaded"] = int((stat["downloaded"] / stat["total"]) * 100)
            
            return jsonify({
                "source_csv": filename,
                "completed": stat["downloaded"],
                "total": stat["total"],
                "active": stat["active"]
            })
            
    return jsonify({"active": False})

@app.route('/api/csv-library/clear-files', methods=['POST'])
def api_clear_files():
    data = request.json
    filename = data.get('filename')
    if filename in state["downloads"]:
        del state["downloads"][filename]
    return jsonify({"success": True, "message": "Files cleared"})

@app.route('/api/csv-library/delete', methods=['POST'])
def api_library_delete():
    data = request.json
    filename = data.get('filename')
    path = CSV_LIB_DIR / filename
    if path.exists():
        path.unlink()
    if filename in state["downloads"]:
        del state["downloads"][filename]
    return jsonify({"success": True})

@app.route('/api/external-storage')
def api_external_storage():
    return jsonify({"is_read_only": False, "available": True})

@app.route('/api/health/storage')
def api_storage_health():
    return jsonify({
        "status": "Healthy",
        "usage_percent": 32.8,
        "message": "Filesystem writable"
    })

# --- Simulation Logic ---

def start_mock_download(filename, pin=False):
    state["downloads"][filename] = {
        "downloaded": 0,
        "pinned": 0,
        "total": 10,
        "percent_downloaded": 0,
        "percent_pinned": 0,
        "active": True
    }

if __name__ == '__main__':
    print(f"🚀 Vernis Test Server running at http://localhost:5001")
    app.run(port=5001, debug=True)
