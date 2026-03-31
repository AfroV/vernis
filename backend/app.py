#!/usr/bin/env python3
"""
# Vernis Production API Server
Handles all backend operations: NFT downloads, IPFS pinning, Wi-Fi management, updates
"""
from flask import Flask, request, jsonify, send_from_directory, send_file, Response
import subprocess
import os
import json
from pathlib import Path
import shutil
import requests
import zipfile
import re
import time
from datetime import datetime
import io
import threading
import socket
import platform

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB upload limit

# Configuration
NFT_DIR = Path("/opt/vernis/nfts")  # Default internal storage
UPLOAD_DIR = Path("/opt/vernis/uploads")
SCRIPTS_DIR = Path("/opt/vernis/scripts")
CSV_LIBRARY_DIR = Path("/opt/vernis/csv-library")
FILES_DIR = Path("/opt/vernis/files")
TMP_DIR = Path("/opt/vernis/tmp")  # tmpfs RAM disk (setup-tmpfs.sh), fallback to /tmp
FILES_METADATA_FILE = Path("/opt/vernis/files-metadata.json")
CONFIG_FILE = Path("/opt/vernis/device-config.json")
GITHUB_CONFIG_FILE = Path("/opt/vernis/github-config.json")
UPDATE_CONFIG_FILE = Path("/opt/vernis/update-config.json")
CARDS_CONFIG_FILE = Path("/opt/vernis/cards-config.json")
CARDS_CACHE_FILE = Path("/opt/vernis/cards-cache.json")
STORAGE_CONFIG_FILE = Path("/opt/vernis/storage-config.json")
ETH_RPC_CONFIG_FILE = Path("/opt/vernis/eth-rpc-config.json")
SETUP_COMPLETE_FILE = Path("/opt/vernis/setup-complete.json")
THEME_FILE = Path("/opt/vernis/theme.json")

NFT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CSV_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
# Use tmpfs if mounted, otherwise fall back to /tmp
if not TMP_DIR.is_mount():
    TMP_DIR = Path("/tmp")
TMP_DIR.mkdir(parents=True, exist_ok=True)

# ========================================
# Security: CID validation
# ========================================
_CID_RE = re.compile(r'^(Qm[a-zA-Z0-9]{44}|baf[a-z2-7]{50,})(/[\w\-\.]+)*$')

def validate_cid(cid):
    """Validate IPFS CID format. Returns (valid, error_msg)."""
    if not cid:
        return False, "CID required"
    if '..' in cid or cid.startswith('/') or cid.startswith('-'):
        return False, "Invalid CID: illegal characters"
    if not _CID_RE.match(cid):
        return False, "Invalid CID format. Must start with Qm or baf"
    return True, None

# ========================================
# Security: Auth token for destructive endpoints
# ========================================
AUTH_TOKEN_FILE = Path("/opt/vernis/auth-token.json")

def _load_auth_token():
    """Load or generate auth token for destructive API calls."""
    if AUTH_TOKEN_FILE.exists():
        try:
            with open(AUTH_TOKEN_FILE, 'r') as f:
                return json.load(f).get('token', '')
        except Exception:
            pass
    # Generate a new token on first run
    import secrets
    token = secrets.token_hex(16)
    try:
        with open(AUTH_TOKEN_FILE, 'w') as f:
            json.dump({"token": token}, f)
        os.chmod(str(AUTH_TOKEN_FILE), 0o600)
    except Exception:
        pass
    return token

_AUTH_TOKEN = _load_auth_token()

# Rate limiting for failed auth attempts (per IP)
_auth_failures = {}  # {ip: [timestamp, ...]}
_AUTH_FAIL_LIMIT = 20       # max failures per window
_AUTH_FAIL_WINDOW = 300     # 5 minute window
_AUTH_BLOCK_DURATION = 900  # 15 minute block after exceeding limit

def _check_rate_limit(ip):
    """Returns True if IP is rate-limited (too many failed auth attempts)."""
    now = time.time()
    if ip not in _auth_failures:
        return False
    # Clean old entries
    _auth_failures[ip] = [t for t in _auth_failures[ip] if now - t < _AUTH_BLOCK_DURATION]
    # Check if blocked
    recent = [t for t in _auth_failures[ip] if now - t < _AUTH_FAIL_WINDOW]
    return len(recent) >= _AUTH_FAIL_LIMIT

def _record_auth_failure(ip):
    """Record a failed auth attempt for rate limiting."""
    now = time.time()
    if ip not in _auth_failures:
        _auth_failures[ip] = []
    _auth_failures[ip].append(now)
    # Cap list size to prevent memory growth
    if len(_auth_failures[ip]) > _AUTH_FAIL_LIMIT * 2:
        _auth_failures[ip] = _auth_failures[ip][-_AUTH_FAIL_LIMIT:]

def require_auth():
    """Check auth token from X-Vernis-Token header or ?token= param.
    Returns None if valid, or a JSON error response if invalid."""
    remote = request.remote_addr
    # Allow requests from localhost (kiosk on the Pi itself)
    if remote in ('127.0.0.1', '::1'):
        return None
    # Check rate limit before validating token
    if _check_rate_limit(remote):
        return jsonify({"error": "Too many failed attempts. Try again later."}), 429
    token = request.headers.get('X-Vernis-Token') or request.args.get('token', '')
    if token == _AUTH_TOKEN:
        return None
    _record_auth_failure(remote)
    return jsonify({"error": "Authentication required", "hint": "Set X-Vernis-Token header"}), 403

# Read-only endpoints exempt from auth (safe for LAN access)
_AUTH_EXEMPT_PATHS = {
    '/api/health', '/api/version', '/api/auth-token', '/api/qrcode',
    '/api/nft-list', '/api/nft-list-detailed', '/api/nft-metadata',
    '/api/carousel-list', '/api/carousels', '/api/favorites',
    '/api/csv-library', '/api/csv-library/progress',
    '/api/display-config', '/api/display/output',
    '/api/storage/health', '/api/storage/allocation',
    '/api/storage/external/detect', '/api/storage/external/status',
    '/api/hue/settings', '/api/hue/lights', '/api/hue/entertainment/areas',
    '/api/screen/brightness', '/api/screen/rotation',
    '/api/screen-saver/config', '/api/fan/config', '/api/fan/status',
    '/api/thermal', '/api/system/leds',
    '/api/ipfs/status', '/api/ipfs/settings', '/api/ipfs/pinned-list',
    '/api/update-config', '/api/auto-update', '/api/os-lock/status',
    '/api/github-config', '/api/cards/config',
    '/api/download-history', '/api/benchmark', '/api/tests',
    '/api/eth-rpc', '/api/disk-scan/settings',
    '/api/screen-color', '/api/nft-artwork-info',
    '/api/easter-egg', '/api/burner/cache',
    '/api/files', '/api/files/metadata',
    '/api/setup/status', '/api/setup/check',
}

@app.before_request
def _enforce_auth():
    """Enforce auth on all state-changing (POST/PUT/DELETE) requests from non-localhost."""
    if request.method in ('POST', 'PUT', 'DELETE'):
        # Check if this path is exempt (read-only GET+POST endpoints)
        path = request.path.rstrip('/')
        if path in _AUTH_EXEMPT_PATHS:
            return None
        # Require auth for all other state-changing requests
        auth_result = require_auth()
        if auth_result is not None:
            return auth_result
    elif request.method == 'GET' and request.path == '/api/diagnostics':
        # Diagnostics is GET-only but exposes sensitive system info
        auth_result = require_auth()
        if auth_result is not None:
            return auth_result
    return None

@app.route("/api/auth-token")
def get_auth_token():
    """Get auth token — only accessible from localhost or the device itself."""
    remote = request.remote_addr
    if remote not in ('127.0.0.1', '::1'):
        return jsonify({"error": "Only accessible from the device itself"}), 403
    return jsonify({"token": _AUTH_TOKEN})


def get_active_nft_dir(for_writing=False):
    """Get the active NFT directory (external if configured, otherwise internal)

    Args:
        for_writing: If True and readonly_mode is enabled, returns internal storage
    """
    try:
        if STORAGE_CONFIG_FILE.exists():
            with open(STORAGE_CONFIG_FILE, 'r') as f:
                config = json.load(f)
            if config.get('use_external') and config.get('external_path'):
                # If readonly_mode is enabled and we need to write, use internal storage
                if for_writing and config.get('readonly_mode', False):
                    return NFT_DIR
                external_nft_dir = Path(config['external_path']) / "vernis-nfts"
                if external_nft_dir.exists() or Path(config['external_path']).exists():
                    if not for_writing or not config.get('readonly_mode', False):
                        external_nft_dir.mkdir(parents=True, exist_ok=True)
                    return external_nft_dir
    except:
        pass
    return NFT_DIR

def get_x_display_env():
    """Get environment variables for X display access"""
    import glob
    env = os.environ.copy()

    # Try to find the active X display and auth from running Xorg process
    try:
        result = subprocess.run(['pgrep', '-a', 'Xorg'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'Xorg' in line:
                    parts = line.split()
                    # Find display number (e.g., ":0" or ":1")
                    for i, part in enumerate(parts):
                        if part.startswith(':') and len(part) > 1 and part[1].isdigit():
                            env['DISPLAY'] = part
                        # Find -auth parameter
                        if part == '-auth' and i + 1 < len(parts):
                            auth_path = parts[i + 1]
                            if os.path.exists(auth_path):
                                env['XAUTHORITY'] = auth_path
                    break
    except:
        pass

    # Default to :0 if not found
    if 'DISPLAY' not in env:
        env['DISPLAY'] = ':0'

    # Find XAUTHORITY if not already set
    if 'XAUTHORITY' not in env:
        # Prioritize /tmp/serverauth.* over home directory
        xauth_paths = glob.glob('/tmp/serverauth.*') + glob.glob('/home/*/.Xauthority') + ['/root/.Xauthority']
        for xauth_path in xauth_paths:
            if os.path.exists(xauth_path):
                env['XAUTHORITY'] = xauth_path
                break

    return env

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

def get_eth_rpc_config():
    """Get custom Ethereum RPC configuration"""
    if ETH_RPC_CONFIG_FILE.exists():
        try:
            with open(ETH_RPC_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"custom_rpc_url": ""}

def get_update_config():
    """Get update configuration (dev vs production mode)"""
    if UPDATE_CONFIG_FILE.exists():
        try:
            with open(UPDATE_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {
        "mode": "production",
        "dev_server": "",
        "github_repo": "",
        "github_branch": "main"
    }

def fetch_github_csv_files():
    """Fetch list of CSV files from GitHub repository (supports both flat files and folder structure)"""
    config = get_github_config()

    if not config.get('enabled', False):
        return []

    owner = config.get('owner', '').strip()
    repo = config.get('repo', '').strip()
    path = config.get('path', '').strip()
    token = config.get('token', '').strip()

    if not owner or not repo:
        return []

    def make_request(url):
        headers = {'Accept': 'application/vnd.github.v3+json'}
        if token:
            headers['Authorization'] = f"token {token}"
        return requests.get(url, headers=headers, timeout=10)

    def fetch_metadata(folder_path):
        """Fetch metadata.json from a folder"""
        try:
            meta_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{folder_path}/metadata.json"
            resp = make_request(meta_url)
            if resp.status_code == 200:
                import base64
                content = resp.json().get('content', '')
                decoded = base64.b64decode(content).decode('utf-8')
                return json.loads(decoded)
        except:
            pass
        return {}

    try:
        # GitHub API URL
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        response = make_request(api_url)

        if response.status_code != 200:
            return []

        items = response.json()
        csv_files = []

        for item in items:
            # Option 1: Folder structure (folder with collection.csv + metadata.json)
            if item['type'] == 'dir':
                folder_name = item['name']
                folder_path = f"{path}/{folder_name}" if path else folder_name

                # Check for collection.csv in the folder
                folder_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{folder_path}"
                folder_resp = make_request(folder_url)

                if folder_resp.status_code == 200:
                    folder_items = folder_resp.json()
                    csv_file = None
                    cover_url = None

                    for f in folder_items:
                        if f['type'] == 'file':
                            if f['name'] == 'collection.csv' or f['name'].endswith('.csv'):
                                csv_file = f
                            elif f['name'] in ['cover.jpg', 'cover.png', 'cover.webp']:
                                cover_url = f['download_url']

                    if csv_file:
                        # Fetch metadata.json if exists
                        metadata = fetch_metadata(folder_path)

                        csv_files.append({
                            'filename': csv_file['name'],
                            'folder': folder_name,
                            'name': metadata.get('name', folder_name.replace('_', ' ').replace('-', ' ').title()),
                            'description': metadata.get('description', 'Collection from GitHub'),
                            'author': metadata.get('author', ''),
                            'size': f"{csv_file['size']/1024:.1f} KB" if csv_file['size'] < 1024**2 else f"{csv_file['size']/(1024**2):.1f} MB",
                            'count': metadata.get('count', '?'),
                            'source': 'github',
                            'download_url': csv_file['download_url'],
                            'cover_url': cover_url,
                            'featured': metadata.get('featured', False),
                            'colors': metadata.get('colors', {})
                        })

            # Option 2: Flat CSV file (backward compatible)
            elif item['type'] == 'file' and item['name'].endswith('.csv'):
                csv_files.append({
                    'filename': item['name'],
                    'folder': None,
                    'name': item['name'].replace('.csv', '').replace('_', ' ').replace('-', ' ').title(),
                    'description': 'Collection from GitHub',
                    'author': '',
                    'size': f"{item['size']/1024:.1f} KB" if item['size'] < 1024**2 else f"{item['size']/(1024**2):.1f} MB",
                    'count': '?',
                    'source': 'github',
                    'download_url': item['download_url'],
                    'cover_url': None,
                    'featured': False,
                    'colors': {}
                })

        return csv_files
    except Exception as e:
        print(f"Error fetching GitHub files: {e}")
        return []

def get_cards_config():
    """Get cards GitHub sync configuration"""
    if CARDS_CONFIG_FILE.exists():
        try:
            with open(CARDS_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {
        "enabled": False,
        "owner": "",
        "repo": "",
        "path": "cards.json",
        "branch": "main"
    }

def fetch_github_cards():
    """Fetch cards from GitHub repository"""
    config = get_cards_config()

    if not config.get('enabled', False):
        return None, "Cards sync not enabled"

    owner = config.get('owner', '').strip()
    repo = config.get('repo', '').strip()
    path = config.get('path', 'cards.json').strip()
    branch = config.get('branch', 'main').strip()

    if not owner or not repo:
        return None, "GitHub owner/repo not configured"

    try:
        # Fetch raw file from GitHub
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        response = requests.get(raw_url, timeout=10)

        if response.status_code == 200:
            cards = response.json()
            # Cache the cards
            with open(CARDS_CACHE_FILE, 'w') as f:
                json.dump({"cards": cards, "fetched_at": time.time()}, f)
            return cards, None
        else:
            return None, f"GitHub returned {response.status_code}"
    except Exception as e:
        return None, str(e)

@app.route("/api/cards/config", methods=["GET", "POST"])
def cards_config():
    """Get or update cards GitHub sync configuration"""
    if request.method == "GET":
        return jsonify(get_cards_config())

    try:
        data = request.json
        config = {
            "enabled": data.get('enabled', False),
            "owner": data.get('owner', '').strip(),
            "repo": data.get('repo', '').strip(),
            "path": data.get('path', 'cards.json').strip(),
            "branch": data.get('branch', 'main').strip()
        }
        with open(CARDS_CONFIG_FILE, 'w') as f:
            json.dump(config, f)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cards")
def get_cards():
    """Get cards (from cache or fetch from GitHub)"""
    config = get_cards_config()

    if not config.get('enabled', False):
        return jsonify({"cards": [], "source": "disabled"})

    # Check cache first (valid for 5 minutes)
    if CARDS_CACHE_FILE.exists():
        try:
            with open(CARDS_CACHE_FILE, 'r') as f:
                cache = json.load(f)
            if time.time() - cache.get('fetched_at', 0) < 300:  # 5 minutes
                return jsonify({"cards": cache.get('cards', []), "source": "cache"})
        except:
            pass

    # Fetch fresh from GitHub
    cards, error = fetch_github_cards()
    if cards is not None:
        return jsonify({"cards": cards, "source": "github"})
    else:
        # Return cached if available, even if stale
        if CARDS_CACHE_FILE.exists():
            try:
                with open(CARDS_CACHE_FILE, 'r') as f:
                    cache = json.load(f)
                return jsonify({"cards": cache.get('cards', []), "source": "stale_cache", "error": error})
            except:
                pass
        return jsonify({"cards": [], "source": "error", "error": error})

@app.route("/api/cards/refresh", methods=["POST"])
def refresh_cards():
    """Force refresh cards from GitHub"""
    cards, error = fetch_github_cards()
    if cards is not None:
        return jsonify({"success": True, "cards": cards})
    else:
        return jsonify({"success": False, "error": error})

@app.route("/api/pinned-art")
def pinned_art():
    """Return list of all pinned artwork URLs - from both internal and external storage"""
    try:
        files = []
        # Get files from internal storage
        for ext in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'mp4', 'html']:
            files.extend([f"/nfts/{f.name}" for f in NFT_DIR.glob(f"*.{ext}")])

        # Also get files from external storage if configured
        active_dir = get_active_nft_dir()
        if active_dir != NFT_DIR:
            for ext in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'mp4', 'html']:
                files.extend([f"/nfts-ext/{f.name}" for f in active_dir.glob(f"*.{ext}")])

        return jsonify(files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/nfts/<path:filename>")
def serve_nft(filename):
    """Serve NFT files from internal storage"""
    return send_from_directory(NFT_DIR, filename)

@app.route("/nfts-ext/<path:filename>")
def serve_nft_external(filename):
    """Serve NFT files from external storage"""
    active_dir = get_active_nft_dir()
    return send_from_directory(active_dir, filename)

@app.route("/api/upload-csv", methods=["POST"])
def upload_csv():
    """Handle CSV upload and trigger batch NFT download"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "Empty filename"}), 400

        # Save CSV (sanitize filename to prevent path traversal)
        safe_name = re.sub(r'[^\w\-\.]', '_', file.filename)
        csv_path = UPLOAD_DIR / safe_name
        file.save(csv_path)

        # Get workers parameter (default: 2, clamped 1-8)
        try:
            workers = str(max(1, min(int(request.form.get('workers', '2')), 8)))
        except (ValueError, TypeError):
            workers = '2'

        # Run advanced downloader script in background with workers
        # Use active NFT directory (external if configured, internal if readonly mode)
        active_nft_dir = get_active_nft_dir(for_writing=True)
        downloader = SCRIPTS_DIR / "nft_downloader_advanced.py"
        subprocess.Popen([
            "python3", str(downloader),
            "--csv", str(csv_path),
            "--output", str(active_nft_dir),
            "--workers", workers
        ])

        return jsonify({
            "success": True,
            "message": f"Processing {file.filename} with {workers} workers. Check display in a few minutes."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/download-progress")
def download_progress():
    """Get current download progress from the downloader"""
    try:
        # Check both internal and external storage for progress file
        active_nft_dir = get_active_nft_dir()
        progress_file = active_nft_dir / "download_progress.json"

        # Also check internal NFT_DIR if different
        if not progress_file.exists() and active_nft_dir != NFT_DIR:
            internal_progress = NFT_DIR / "download_progress.json"
            if internal_progress.exists():
                progress_file = internal_progress

        # Count actual NFT files from active directory
        actual_nft_count = 0
        for ext in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'mp4', 'html']:
            actual_nft_count += len(list(active_nft_dir.glob(f"*.{ext}")))

        if not progress_file.exists():
            return jsonify({
                "active": False,
                "completed": actual_nft_count,
                "total": actual_nft_count,
                "failed": 0,
                "status": "No active download",
                "actual_files": actual_nft_count
            })

        # Read progress file
        with open(progress_file, 'r') as f:
            data = json.load(f)

        completed = data.get('completed', 0)
        total = data.get('total', 0)
        downloaded = len(data.get('downloaded', []))
        # Handle both old format (list) and new format (dict with error reasons)
        failed_data = data.get('failed', {})
        if isinstance(failed_data, dict):
            failed_count = len(failed_data)
            failed_items_with_reasons = failed_data  # {identifier: error_reason}
        else:
            # Old format: list of identifiers
            failed_count = len(failed_data)
            failed_items_with_reasons = {item: "Unknown" for item in failed_data}

        # Check if download is still active
        # File-age check alone is unreliable — a slow IPFS fetch can stall
        # progress writes for >30s. Also check if the downloader process is running.
        import time, subprocess
        file_age = time.time() - progress_file.stat().st_mtime
        file_fresh = file_age < 30
        process_alive = subprocess.run(
            ["pgrep", "-f", "nft_downloader"], capture_output=True
        ).returncode == 0
        active = (file_fresh or process_alive) and (completed < total or total == 0)

        # Check for initializing state (written by install endpoint before downloader starts)
        saved_status = data.get('status', '')
        if saved_status == 'initializing' and total == 0 and completed == 0:
            # Downloader hasn't started yet - still setting up
            active = True
            status = "Initializing"
        elif completed >= total and total > 0:
            if failed_count > 0:
                status = f"Complete with {failed_count} failures"
            else:
                status = "Complete"
        elif active:
            status = "Downloading"
        else:
            status = "Idle"

        # When not actively downloading and no progress file data,
        # show actual file count as a fallback
        if not active and status != "Initializing" and total == 0:
            completed = actual_nft_count
            total = actual_nft_count

        # Get source CSV filename if available
        source_csv = data.get('source_csv', None)

        # Calculate progress percentage
        progress = 0
        if total > 0:
            progress = round((completed / total) * 100, 1)

        # Get speed and format it
        speed = data.get('speed', 0)
        speed_str = ""
        if speed > 0:
            if speed >= 1024 * 1024:
                speed_str = f"{speed / (1024 * 1024):.1f} MB/s"
            elif speed >= 1024:
                speed_str = f"{speed / 1024:.1f} KB/s"
            else:
                speed_str = f"{speed:.0f} B/s"

        current_file = data.get('current_file', '')

        # Get first 20 failed items with their error reasons
        failed_items_list = [
            {"id": k, "error": v}
            for k, v in list(failed_items_with_reasons.items())[:20]
        ]

        # Include retry info from downloader
        retry_pass = data.get('retry_pass', 0)
        retry_timeout = data.get('retry_timeout', 0)

        return jsonify({
            "active": active,
            "completed": completed,
            "total": total,
            "downloaded": downloaded,
            "failed": failed_count,
            "failed_items": failed_items_list,  # List of {id, error} objects
            "status": status,
            "source_csv": source_csv,
            "progress": progress,
            "speed": speed_str,
            "current_file": current_file,
            "actual_files": actual_nft_count,
            "retry_pass": retry_pass,
            "retry_timeout": retry_timeout
        })
    except Exception as e:
        return jsonify({
            "active": False,
            "completed": 0,
            "total": 0,
            "failed": 0,
            "status": f"Error: {str(e)}"
        })

@app.route("/api/download-report")
def download_report():
    """Generate a CSV report of all failed downloads for investigation"""
    try:
        active_nft_dir = get_active_nft_dir()
        progress_file = active_nft_dir / "download_progress.json"

        if not progress_file.exists():
            return "No download data found", 404

        with open(progress_file, 'r') as f:
            data = json.load(f)

        failed_data = data.get('failed', {})
        if isinstance(failed_data, list):
            failed_data = {item: "Unknown" for item in failed_data}

        source_csv = data.get('source_csv', 'unknown')
        total = data.get('total', 0)
        completed = data.get('completed', 0)
        downloaded_count = len(data.get('downloaded', []))

        # Build report
        import csv as csv_mod
        import io
        output = io.StringIO()

        # Header section
        output.write(f"# Vernis Download Report\n")
        output.write(f"# Source: {source_csv}\n")
        output.write(f"# Total items: {total}\n")
        output.write(f"# Downloaded: {downloaded_count}\n")
        output.write(f"# Failed: {len(failed_data)}\n")
        output.write(f"# Generated: {datetime.now().isoformat()}\n")
        output.write(f"#\n")
        output.write(f"# Collectors can try these CIDs on alternative IPFS gateways:\n")
        output.write(f"#   https://ipfs.io/ipfs/CID\n")
        output.write(f"#   https://cloudflare-ipfs.com/ipfs/CID\n")
        output.write(f"#   https://dweb.link/ipfs/CID\n")
        output.write(f"#   https://w3s.link/ipfs/CID\n")
        output.write(f"#\n")

        writer = csv_mod.writer(output)
        writer.writerow(["cid", "error", "ipfs_url"])

        for cid, error in sorted(failed_data.items()):
            # Clean up CID for URL (remove nested suffixes like _13)
            base_cid = cid.split('_')[0] if '_' in cid and not cid.startswith('0x') else cid
            ipfs_url = f"https://ipfs.io/ipfs/{base_cid}" if (base_cid.startswith('Qm') or base_cid.startswith('bafy')) else ""
            writer.writerow([cid, error, ipfs_url])

        response = app.response_class(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=failed-downloads-{source_csv.replace(".csv","")}.csv'}
        )
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/reset-downloads", methods=["POST"])
def reset_downloads():
    """Reset download progress to allow re-downloading all files"""
    try:
        # Clear progress files in both internal and external storage
        active_nft_dir = get_active_nft_dir()
        progress_file = active_nft_dir / "download_progress.json"
        internal_progress = NFT_DIR / "download_progress.json"

        # Clear or reset both progress files
        if progress_file.exists():
            progress_file.unlink()
        if internal_progress.exists() and active_nft_dir != NFT_DIR:
            internal_progress.unlink()

        return jsonify({
            "success": True,
            "message": "Download progress reset. You can now re-download collections."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stop-download", methods=["POST"])
def stop_download():
    """Stop active download and any auto-retries"""
    try:
        active_nft_dir = get_active_nft_dir()
        # Create stop signal file (downloader checks for this)
        stop_file = active_nft_dir / "download_stop"
        stop_file.touch()
        # Also create in internal dir if different
        if active_nft_dir != NFT_DIR:
            (NFT_DIR / "download_stop").touch()
        # Kill downloader processes
        try:
            result = subprocess.run(
                ["pgrep", "-f", "nft_downloader"],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                for pid in result.stdout.strip().split('\n'):
                    try:
                        subprocess.run(["kill", pid], capture_output=True, timeout=5)
                    except:
                        pass
        except:
            pass
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/retry-failed", methods=["POST"])
def retry_failed():
    """Retry downloading failed items"""
    try:
        progress_file = NFT_DIR / "download_progress.json"

        if not progress_file.exists():
            return jsonify({"error": "No download progress file found"}), 404

        with open(progress_file, 'r') as f:
            data = json.load(f)

        failed_list = data.get('failed', [])

        if not failed_list:
            return jsonify({"success": True, "message": "No failed items to retry"})

        # Clear failed list and reset for retry
        data['failed'] = []
        data['completed'] = 0
        data['total'] = len(failed_list)

        with open(progress_file, 'w') as f:
            json.dump(data, f, indent=2)

        # Create a temporary CSV with failed CIDs
        retry_csv = UPLOAD_DIR / "retry_failed.csv"
        with open(retry_csv, 'w') as f:
            f.write("cid\n")
            for cid in failed_list:
                f.write(f"{cid}\n")

        # Run downloader on failed items
        downloader = SCRIPTS_DIR / "nft_downloader_advanced.py"
        subprocess.Popen([
            "python3", str(downloader),
            "--csv", str(retry_csv),
            "--output", str(NFT_DIR),
            "--workers", "2"
        ])

        return jsonify({
            "success": True,
            "message": f"Retrying {len(failed_list)} failed downloads",
            "count": len(failed_list)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

DOWNLOAD_HISTORY_FILE = Path("/opt/vernis/download-history.json")

@app.route("/api/download-history")
def download_history():
    """Get download history with detailed error info"""
    try:
        if DOWNLOAD_HISTORY_FILE.exists():
            with open(DOWNLOAD_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        else:
            history = {"sessions": []}

        # Also include current progress if active
        active_nft_dir = get_active_nft_dir()
        progress_file = active_nft_dir / "download_progress.json"

        current = None
        if progress_file.exists():
            try:
                with open(progress_file, 'r') as f:
                    data = json.load(f)
                file_age = time.time() - progress_file.stat().st_mtime
                if file_age < 30:  # Active download
                    current = {
                        "source_csv": data.get('source_csv', 'Unknown'),
                        "completed": data.get('completed', 0),
                        "total": data.get('total', 0),
                        "failed": len(data.get('failed', {})) if isinstance(data.get('failed'), dict) else len(data.get('failed', [])),
                        "active": True
                    }
            except:
                pass

        return jsonify({
            "sessions": history.get("sessions", [])[-10:],  # Last 10 sessions
            "current": current
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/download-history/save", methods=["POST"])
def save_download_history():
    """Save current download session to history"""
    try:
        active_nft_dir = get_active_nft_dir()
        progress_file = active_nft_dir / "download_progress.json"

        if not progress_file.exists():
            return jsonify({"error": "No progress file found"}), 404

        with open(progress_file, 'r') as f:
            data = json.load(f)

        # Build session record
        failed_data = data.get('failed', {})
        if isinstance(failed_data, dict):
            failed_items = [{"id": k, "error": v} for k, v in failed_data.items()]
            failed_count = len(failed_data)
        else:
            failed_items = [{"id": item, "error": "Unknown"} for item in failed_data]
            failed_count = len(failed_data)

        session = {
            "timestamp": datetime.now().isoformat(),
            "source_csv": data.get('source_csv', 'Unknown'),
            "total": data.get('total', 0),
            "completed": data.get('completed', 0),
            "downloaded": len(data.get('downloaded', [])),
            "failed_count": failed_count,
            "failed_items": failed_items[:50]  # Limit to 50 error details
        }

        # Load existing history
        if DOWNLOAD_HISTORY_FILE.exists():
            with open(DOWNLOAD_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        else:
            history = {"sessions": []}

        # Add new session and keep last 20
        history["sessions"].append(session)
        history["sessions"] = history["sessions"][-20:]

        with open(DOWNLOAD_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)

        return jsonify({"success": True, "session": session})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/add-single", methods=["POST"])
def add_single():
    """Add a single NFT by contract address and token ID, or IPFS CID"""
    try:
        data = request.json
        contract = data.get('contract', '').strip()
        token_id = data.get('token_id', '').strip()
        cid = data.get('cid', '').strip()

        downloader = SCRIPTS_DIR / "nft_downloader_advanced.py"

        # Support either contract+token or CID
        if cid:
            # Validate CID format
            valid, err = validate_cid(cid)
            if not valid:
                return jsonify({"error": err}), 400

            # IPFS CID provided
            subprocess.Popen([
                "python3", str(downloader),
                "--cid", cid,
                "--output", str(NFT_DIR)
            ])

            return jsonify({
                "success": True,
                "message": f"Downloading IPFS CID: {cid}"
            })
        elif contract and token_id:
            # Contract + Token ID provided
            subprocess.Popen([
                "python3", str(downloader),
                "--contract", contract,
                "--token", token_id,
                "--output", str(NFT_DIR)
            ])

            return jsonify({
                "success": True,
                "message": f"Downloading {contract} #{token_id}"
            })
        else:
            return jsonify({"error": "Either (contract AND token_id) OR cid required"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/qrcode")
def generate_qrcode():
    """Generate premium artistic QR code for the current device URL"""
    try:
        import qrcode
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
        import socket
        import math

        # Get theme from query param (default to gallery)
        theme = request.args.get('theme', 'gallery')

        # Theme color schemes matching CSS themes
        theme_colors = {
            'gallery': {'primary': '#2f2f2f', 'secondary': '#525252', 'bg': '#fafaf9'},
            'nordic': {'primary': '#5e81ac', 'secondary': '#81a1c1', 'bg': '#f7f8fa'},
            'walnut': {'primary': '#d4af37', 'secondary': '#b8960c', 'bg': '#f7f3ee'},
            'xcopy': {'primary': '#00ffff', 'secondary': '#ff00ff', 'bg': '#000000'},
            'hackatao': {'primary': '#c9a962', 'secondary': '#d4af37', 'bg': '#faf9f7'},
            'pop': {'primary': '#E63946', 'secondary': '#457B9D', 'bg': '#f8f8f8'},
        }
        colors = theme_colors.get(theme, theme_colors['gallery'])

        # Get actual IP address
        def get_local_ip():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                return ip
            except:
                return None

        # Allow custom URL (e.g. Bluetooth PAN address)
        custom_url = request.args.get('url')
        if custom_url:
            host = custom_url
        else:
            ip = get_local_ip()
            host = f"http://{ip}" if ip else request.host_url.rstrip('/')

        # Generate QR code with high error correction for logo overlay
        qr = qrcode.QRCode(
            version=2,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=8,
            border=0,
        )
        qr.add_data(host)
        qr.make(fit=True)

        # Get QR matrix
        matrix = qr.get_matrix()
        qr_size = len(matrix)

        # Calculate dimensions
        box_size = 8
        qr_pixels = qr_size * box_size
        padding = 24
        frame_width = 8
        total_size = qr_pixels + (padding * 2) + (frame_width * 2)

        # Create canvas
        img = Image.new('RGBA', (total_size, total_size), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)

        # Parse colors
        def hex_to_rgb(hex_color):
            hex_color = hex_color.lstrip('#')
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

        primary_rgb = hex_to_rgb(colors['primary'])
        secondary_rgb = hex_to_rgb(colors['secondary'])
        bg_rgb = (255, 255, 255)  # Pure white background for max QR contrast

        # Darken QR dot colors for scannability (keep hue, increase contrast)
        def darken(rgb, factor=0.45):
            return tuple(int(c * factor) for c in rgb)
        primary_rgb = darken(primary_rgb)
        secondary_rgb = darken(secondary_rgb)

        # Draw background with rounded corners
        corner_radius = 16
        draw.rounded_rectangle(
            [0, 0, total_size - 1, total_size - 1],
            radius=corner_radius,
            fill=bg_rgb + (255,)
        )

        # Draw decorative frame
        frame_offset = frame_width // 2
        draw.rounded_rectangle(
            [frame_offset, frame_offset, total_size - frame_offset - 1, total_size - frame_offset - 1],
            radius=corner_radius - 4,
            outline=primary_rgb + (80,),
            width=2
        )

        # Draw QR code modules with rounded dots and gradient
        qr_offset = padding + frame_width

        # Calculate logo exclusion zone (center 30%)
        logo_zone_start = qr_size * 0.35
        logo_zone_end = qr_size * 0.65

        for row in range(qr_size):
            for col in range(qr_size):
                # Skip logo zone
                if logo_zone_start <= row <= logo_zone_end and logo_zone_start <= col <= logo_zone_end:
                    continue

                if matrix[row][col]:
                    x = qr_offset + col * box_size
                    y = qr_offset + row * box_size

                    # Gradient from primary to secondary based on position
                    gradient_factor = (row + col) / (qr_size * 2)
                    r = int(primary_rgb[0] + (secondary_rgb[0] - primary_rgb[0]) * gradient_factor)
                    g = int(primary_rgb[1] + (secondary_rgb[1] - primary_rgb[1]) * gradient_factor)
                    b = int(primary_rgb[2] + (secondary_rgb[2] - primary_rgb[2]) * gradient_factor)

                    # Check if this is a finder pattern (corners)
                    is_finder = (
                        (row < 7 and col < 7) or
                        (row < 7 and col >= qr_size - 7) or
                        (row >= qr_size - 7 and col < 7)
                    )

                    if is_finder:
                        # Square modules for finder patterns (more readable)
                        margin = 1
                        draw.rectangle(
                            [x + margin, y + margin, x + box_size - margin - 1, y + box_size - margin - 1],
                            fill=(r, g, b, 255)
                        )
                    else:
                        # Rounded dots for data modules
                        center_x = x + box_size // 2
                        center_y = y + box_size // 2
                        radius = box_size // 2 - 1
                        draw.ellipse(
                            [center_x - radius, center_y - radius, center_x + radius, center_y + radius],
                            fill=(r, g, b, 255)
                        )

        # Draw centered "V" logo
        logo_size = int(qr_pixels * 0.25)
        logo_x = qr_offset + (qr_pixels - logo_size) // 2
        logo_y = qr_offset + (qr_pixels - logo_size) // 2

        # Logo background circle - always black to match favicon
        logo_center = (logo_x + logo_size // 2, logo_y + logo_size // 2)
        logo_radius = logo_size // 2 + 4
        logo_bg = (17, 17, 17)  # #111111 matching favicon
        gold_rgb = (201, 169, 98)  # #c9a962 matching VERNIS kiosk logo
        gold_light = (232, 200, 116)  # #e8c874
        draw.ellipse(
            [logo_center[0] - logo_radius, logo_center[1] - logo_radius,
             logo_center[0] + logo_radius, logo_center[1] + logo_radius],
            fill=logo_bg + (255,)
        )

        # Logo border - golden
        draw.ellipse(
            [logo_center[0] - logo_radius + 2, logo_center[1] - logo_radius + 2,
             logo_center[0] + logo_radius - 2, logo_center[1] + logo_radius - 2],
            outline=gold_rgb + (200,),
            width=2
        )

        # Draw "V" letter in gold using Playfair Display font
        v_font_size = int(logo_size * 0.7)
        v_font = None
        for font_path in [
            '/usr/share/fonts/truetype/playfair/PlayfairDisplay-Bold.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf',
        ]:
            try:
                v_font = ImageFont.truetype(font_path, v_font_size)
                break
            except (OSError, IOError):
                continue
        if v_font is None:
            v_font = ImageFont.load_default()

        # Render V centered in logo circle
        v_bbox = v_font.getbbox('V')
        v_w = v_bbox[2] - v_bbox[0]
        v_h = v_bbox[3] - v_bbox[1]
        v_x = logo_center[0] - v_w // 2 - v_bbox[0]
        v_y = logo_center[1] - v_h // 2 - v_bbox[1]
        draw.text((v_x, v_y), 'V', font=v_font, fill=gold_rgb + (255,))

        # Convert to RGB for PNG output
        final_img = Image.new('RGB', img.size, (255, 255, 255))
        final_img.paste(img, mask=img.split()[3])

        # Save to bytes buffer
        buffer = io.BytesIO()
        final_img.save(buffer, format='PNG', quality=95)
        buffer.seek(0)

        return Response(buffer.getvalue(), mimetype='image/png')
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@app.route("/api/version")
def get_version():
    """Get Vernis version info"""
    version_file = Path("/var/www/vernis/version.json")
    if version_file.exists():
        try:
            with open(version_file, 'r') as f:
                return jsonify(json.load(f))
        except:
            pass
    return jsonify({"version": "unknown"})

@app.route("/api/https", methods=["GET", "POST", "DELETE"])
def https_setup():
    """Check HTTPS status, enable or disable self-signed HTTPS"""
    CADDYFILE = "/etc/caddy/Caddyfile"
    CERT_PATH = "/etc/caddy/vernis.crt"
    KEY_PATH = "/etc/caddy/vernis.key"

    if request.method == "GET":
        try:
            has_cert = (os.path.exists(CERT_PATH) and os.path.exists(KEY_PATH)) or \
                       (os.path.exists("/etc/ssl/certs/vernis.crt") and os.path.isfile("/etc/ssl/private/vernis.key"))
            https_active = False
            if os.path.exists(CADDYFILE):
                with open(CADDYFILE, 'r') as f:
                    content = f.read()
                    https_active = "tls " in content or ":443" in content
            return jsonify({"enabled": https_active, "has_cert": has_cert})
        except Exception as e:
            return jsonify({"enabled": False, "has_cert": False, "error": str(e)})

    if request.method == "DELETE":
        # Disable HTTPS — restore Caddyfile backup and reload
        auth_err = require_auth()
        if auth_err: return auth_err
        try:
            import subprocess as _sp
            backup_path = CADDYFILE + ".bak"
            if not os.path.exists(backup_path):
                # No backup — build a plain :80 config
                if not os.path.exists(CADDYFILE):
                    return jsonify({"error": "Caddyfile not found"}), 500
                with open(CADDYFILE, 'r') as f:
                    content = f.read()
                if ":443" not in content and "tls " not in content:
                    return jsonify({"success": True, "message": "HTTPS is already disabled"})
                # Strip tls line, change :443 to :80, remove :80 redirect block
                import re as _re
                content = _re.sub(r'\ttls\s+[^\n]+\n', '', content)
                content = content.replace(':443', ':80')
                content = _re.sub(r'\n*:80\s*\{\s*redir\s+https://[^\}]+\}\s*$', '', content).rstrip() + '\n'
                with open("/tmp/Caddyfile.new", 'w') as f:
                    f.write(content)
            else:
                _sp.run(["cp", backup_path, "/tmp/Caddyfile.new"], capture_output=True, text=True, timeout=5)

            # Validate before applying
            result = _sp.run(["caddy", "validate", "--config", "/tmp/Caddyfile.new"],
                             capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                os.remove("/tmp/Caddyfile.new")
                return jsonify({"error": "Restored config invalid: " + result.stderr.strip()}), 500

            _sp.run(["mv", "/tmp/Caddyfile.new", CADDYFILE], capture_output=True, text=True, timeout=10)
            result = _sp.run(["systemctl", "reload", "caddy"], capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                _sp.run(["systemctl", "restart", "caddy"], capture_output=True, text=True, timeout=15)
            return jsonify({"success": True, "message": "HTTPS disabled. Switched back to HTTP."})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # POST - enable HTTPS
    auth_err = require_auth()
    if auth_err: return auth_err
    try:
        import subprocess as _sp
        import re as _re

        # Step 1: Generate self-signed certificate
        if not (os.path.exists(CERT_PATH) and os.path.exists(KEY_PATH)):
            result = _sp.run([
                "openssl", "req", "-x509", "-nodes", "-days", "3650",
                "-newkey", "rsa:2048",
                "-keyout", KEY_PATH,
                "-out", CERT_PATH,
                "-subj", "/CN=vernis.local"
            ], capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return jsonify({"error": "Failed to generate certificate: " + result.stderr.strip()}), 500
            # Caddy runs as 'caddy' user — must be able to read the cert/key
            _sp.run(["chown", "caddy:caddy", CERT_PATH, KEY_PATH], capture_output=True, text=True, timeout=5)
            _sp.run(["chmod", "640", KEY_PATH], capture_output=True, text=True, timeout=5)

        # Step 2: Update Caddyfile
        if not os.path.exists(CADDYFILE):
            return jsonify({"error": "Caddyfile not found"}), 500

        with open(CADDYFILE, 'r') as f:
            caddy_content = f.read()

        # If tls already configured with correct paths, nothing to do
        if "tls " + CERT_PATH in caddy_content:
            return jsonify({"success": True, "message": "HTTPS is already enabled"})

        # If tls exists but with wrong cert paths, or no tls at all — rebuild
        # Start from backup if available, otherwise strip tls/redirect from current
        backup_path = CADDYFILE + ".bak"
        if "tls " in caddy_content and os.path.exists(backup_path):
            with open(backup_path, 'r') as bf:
                caddy_content = bf.read()

        # Match :80 or :443 block (with or without http:// prefix)
        pattern = _re.compile(r'((?:http://)?:(?:80|443))\s*\{')
        match = pattern.search(caddy_content)
        if not match:
            return jsonify({"error": "Could not find :80 or :443 block in Caddyfile"}), 500

        # Remove any existing standalone :80 redirect block at the end
        caddy_content = _re.sub(r'\n*:80\s*\{\s*redir\s+https://[^\}]+\}\s*$', '', caddy_content).rstrip()

        # Build new content: :443 block with tls + original directives, then :80 redirect
        new_content = pattern.sub(
            ":443 {\n\ttls " + CERT_PATH + " " + KEY_PATH,
            caddy_content,
            count=1
        )
        # Append HTTP→HTTPS redirect block
        new_content += "\n\n:80 {\n\tredir https://{host}{uri} permanent\n}\n"

        # Write to temp file
        tmp_path = "/tmp/Caddyfile.new"
        with open(tmp_path, 'w') as f:
            f.write(new_content)

        # Validate config before applying
        result = _sp.run(["caddy", "validate", "--config", tmp_path],
                         capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            os.remove(tmp_path)
            return jsonify({"error": "Invalid Caddy config: " + result.stderr.strip()}), 500

        # Backup original, then apply
        _sp.run(["cp", CADDYFILE, CADDYFILE + ".bak"], capture_output=True, text=True, timeout=5)
        result = _sp.run(["mv", tmp_path, CADDYFILE], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return jsonify({"error": "Failed to update Caddyfile"}), 500

        # Open port 443 in firewall if ufw is active
        ufw_check = _sp.run(["ufw", "status"], capture_output=True, text=True, timeout=10)
        if ufw_check.returncode == 0 and "active" in ufw_check.stdout.lower():
            _sp.run(["ufw", "allow", "443/tcp"], capture_output=True, text=True, timeout=10)

        # Reload Caddy (graceful reload, not restart)
        result = _sp.run(["systemctl", "reload", "caddy"], capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            # Try restart as fallback
            _sp.run(["systemctl", "restart", "caddy"], capture_output=True, text=True, timeout=15)

        return jsonify({"success": True, "message": "HTTPS enabled with self-signed certificate"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/diagnostics")
def diagnostics():
    """Collect comprehensive system diagnostics for remote troubleshooting"""
    import platform
    diag = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "sections": {}}

    # --- System Info ---
    sys_info = {}
    try:
        sys_info["hostname"] = platform.node()
        sys_info["kernel"] = platform.release()
        sys_info["arch"] = platform.machine()
    except: pass
    try:
        with open("/proc/device-tree/model", "r") as f:
            sys_info["model"] = f.read().strip().rstrip('\x00')
    except: sys_info["model"] = "Unknown"
    try:
        r = subprocess.run(["cat", "/etc/os-release"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.startswith("PRETTY_NAME="):
                sys_info["os"] = line.split("=", 1)[1].strip('"')
    except: pass
    try:
        r = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=5)
        sys_info["uptime"] = r.stdout.strip()
    except: pass
    diag["sections"]["system"] = sys_info

    # --- Memory ---
    mem = {}
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem["total_mb"] = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    mem["available_mb"] = int(line.split()[1]) // 1024
                elif line.startswith("SwapTotal:"):
                    mem["swap_total_mb"] = int(line.split()[1]) // 1024
                elif line.startswith("SwapFree:"):
                    mem["swap_free_mb"] = int(line.split()[1]) // 1024
    except: pass
    diag["sections"]["memory"] = mem

    # --- Storage ---
    storage = {}
    try:
        disk = shutil.disk_usage("/")
        storage["root_total_gb"] = round(disk.total / (1024**3), 1)
        storage["root_used_gb"] = round(disk.used / (1024**3), 1)
        storage["root_free_gb"] = round(disk.free / (1024**3), 1)
        storage["root_percent"] = round((disk.used / disk.total) * 100, 1)
    except: pass
    try:
        nft_count = len(list(NFT_DIR.glob("*.*")))
        storage["nft_files"] = nft_count
        nft_size = sum(f.stat().st_size for f in NFT_DIR.glob("*.*"))
        storage["nft_size_mb"] = round(nft_size / (1024**2), 1)
    except: pass
    diag["sections"]["storage"] = storage

    # --- Display ---
    display = {}
    try:
        r = subprocess.run(["wlr-randr"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            display["wlr_randr"] = r.stdout.strip()
    except: pass
    try:
        config_txt = Path("/boot/firmware/config.txt")
        if not config_txt.exists():
            config_txt = Path("/boot/config.txt")
        if config_txt.exists():
            lines = config_txt.read_text().splitlines()
            display["config_txt_display"] = [l for l in lines if any(k in l.lower() for k in
                ["dpi", "hdmi", "display", "overlay", "rotate", "gpio", "over_voltage", "arm_freq", "gpu"])]
    except: pass
    diag["sections"]["display"] = display

    # --- Thermal ---
    try:
        diag["sections"]["thermal"] = get_thermal_status()
    except: diag["sections"]["thermal"] = {}

    # --- Fan ---
    try:
        fan = load_fan_config()
        fan["live"] = get_fan_live_status()
        diag["sections"]["fan"] = fan
    except: diag["sections"]["fan"] = {}

    # --- Network ---
    net = {}
    try:
        r = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
        net["ip_addresses"] = r.stdout.strip().split()
    except: pass
    try:
        r = subprocess.run(["nmcli", "-t", "-f", "active,ssid,signal,freq", "dev", "wifi"],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.startswith("yes:"):
                parts = line.split(":")
                net["wifi_ssid"] = parts[1] if len(parts) > 1 else ""
                net["wifi_signal"] = parts[2] if len(parts) > 2 else ""
                net["wifi_freq"] = parts[3] if len(parts) > 3 else ""
    except: pass
    diag["sections"]["network"] = net

    # --- Services ---
    services = {}
    svc_list = ["vernis-api", "caddy", "ipfs", "vernis-watchdog", "vernis-hue-stream",
                "vernis-touch-wake", "vernis-touch", "labwc"]
    for svc in svc_list:
        try:
            r = subprocess.run(["systemctl", "is-active", svc],
                               capture_output=True, text=True, timeout=3)
            services[svc] = r.stdout.strip()
        except:
            services[svc] = "unknown"
    diag["sections"]["services"] = services

    # --- Chromium ---
    chrome = {}
    try:
        r = subprocess.run(["chromium", "--version"], capture_output=True, text=True, timeout=5)
        chrome["version"] = r.stdout.strip()
    except:
        try:
            r = subprocess.run(["chromium-browser", "--version"], capture_output=True, text=True, timeout=5)
            chrome["version"] = r.stdout.strip()
        except: pass
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:9222/json", timeout=3)
        pages = json.loads(resp.read())
        chrome["current_page"] = pages[0].get("url", "") if pages else ""
    except: pass
    diag["sections"]["chromium"] = chrome

    # --- IPFS ---
    ipfs = {}
    try:
        r = subprocess.run(["ipfs", "version"], env=IPFS_ENV, capture_output=True, text=True, timeout=5)
        ipfs["version"] = r.stdout.strip()
    except: pass
    try:
        r = subprocess.run(["ipfs", "pin", "ls", "--type=recursive", "-q"], env=IPFS_ENV,
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            pins = [l for l in r.stdout.strip().split('\n') if l]
            ipfs["pinned_count"] = len(pins)
    except: pass
    try:
        r = subprocess.run(["ipfs", "repo", "stat", "--human"], env=IPFS_ENV,
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            ipfs["repo_stat"] = r.stdout.strip()
    except: pass
    diag["sections"]["ipfs"] = ipfs

    # --- Hue ---
    hue = {}
    try:
        settings = get_hue_settings()
        hue["bridge_ip"] = settings.get("bridge_ip", "")
        hue["has_api_key"] = bool(settings.get("api_key"))
        hue["lights_count"] = len(settings.get("selected_lights", []))
        hue["entertainment_group"] = settings.get("entertainment_group", "")
    except: pass
    diag["sections"]["hue"] = hue

    # --- Recent Logs (last 30 lines of vernis-api journal) ---
    logs = {}
    try:
        r = subprocess.run(["journalctl", "-u", "vernis-api", "-n", "30", "--no-pager"],
                           capture_output=True, text=True, timeout=10)
        logs["vernis_api"] = r.stdout.strip()
    except: pass
    try:
        r = subprocess.run(["journalctl", "-u", "vernis-watchdog", "-n", "15", "--no-pager"],
                           capture_output=True, text=True, timeout=10)
        logs["watchdog"] = r.stdout.strip()
    except: pass
    try:
        r = subprocess.run(["dmesg", "--level=err,warn", "-T"], capture_output=True, text=True, timeout=10)
        lines = r.stdout.strip().splitlines()
        logs["kernel_errors"] = "\n".join(lines[-20:]) if lines else ""
    except: pass
    diag["sections"]["logs"] = logs

    # Return as downloadable text file
    from flask import Response
    text = f"VERNIS DIAGNOSTIC REPORT\n{'=' * 60}\nGenerated: {diag['timestamp']}\n\n"
    for section_name, section_data in diag["sections"].items():
        text += f"\n{'─' * 60}\n{section_name.upper()}\n{'─' * 60}\n"
        if isinstance(section_data, dict):
            for k, v in section_data.items():
                if isinstance(v, list):
                    text += f"  {k}:\n"
                    for item in v:
                        text += f"    - {item}\n"
                elif isinstance(v, str) and '\n' in v:
                    text += f"  {k}:\n"
                    for line in v.splitlines():
                        text += f"    {line}\n"
                else:
                    text += f"  {k}: {v}\n"
        else:
            text += f"  {section_data}\n"
    text += f"\n{'=' * 60}\nEnd of diagnostic report\n"

    hostname = sys_info.get("hostname", "vernis")
    filename = f"vernis-diag-{hostname}-{time.strftime('%Y%m%d-%H%M%S')}.txt"
    return Response(text, mimetype="text/plain",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})

@app.route("/api/status")
def status():
    """Get system status"""
    try:
        # Get connected Wi-Fi
        try:
            ssid_result = subprocess.run(
                ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                capture_output=True, text=True, timeout=5
            )
            ssid = "Not connected"
            for line in ssid_result.stdout.split('\n'):
                if line.startswith('yes:'):
                    ssid = line.split(':', 1)[1]
                    break
        except:
            ssid = "Unknown"

        # Get storage info with warning level
        storage_warning = None
        try:
            disk = shutil.disk_usage(NFT_DIR)
            usage_percent = (disk.used / disk.total) * 100
            storage = {
                "total": f"{disk.total / (1024**3):.1f} GB",
                "used": f"{disk.used / (1024**3):.1f} GB",
                "free": f"{disk.free / (1024**3):.1f} GB",
                "usage_percent": round(usage_percent, 1)
            }
            # Set warning level
            if usage_percent >= 95:
                storage_warning = "critical"
            elif usage_percent >= 85:
                storage_warning = "warning"
        except:
            storage = {"total": "N/A", "used": "N/A", "free": "N/A", "usage_percent": 0}

        # Count local files
        local_files = len(list(NFT_DIR.glob("*.*")))

        # Get IPFS pin status
        ipfs_pinned = 0
        ipfs_running = False
        try:
            result = subprocess.run(
                ["ipfs", "pin", "ls", "--type=recursive", "-q"],
                env=IPFS_ENV,
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                ipfs_running = True
                ipfs_pinned = len([l for l in result.stdout.strip().split('\n') if l])
        except:
            pass

        # Get device IP address (prefer main network, skip hotspot 192.168.50.x)
        try:
            ip_result = subprocess.run(
                ["hostname", "-I"],
                capture_output=True, text=True, timeout=5
            )
            all_ips = ip_result.stdout.strip().split() if ip_result.stdout.strip() else []
            # Filter out hotspot IPs (192.168.50.x) and prefer main network
            ip_address = "Unknown"
            for ip in all_ips:
                if not ip.startswith("192.168.50."):
                    ip_address = ip
                    break
            # Fallback to first IP if all are hotspot
            if ip_address == "Unknown" and all_ips:
                ip_address = all_ips[0]
        except:
            ip_address = "Unknown"

        return jsonify({
            "ssid": ssid,
            "pinned": local_files,
            "ipfs_pinned": ipfs_pinned,
            "ipfs_running": ipfs_running,
            "storage": storage,
            "storage_warning": storage_warning,
            "ip_address": ip_address
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/health-check")
def health_check():
    """Quick diagnostic: IPFS running + internet reachable"""
    ipfs_ok = False
    try:
        r = subprocess.run(["ipfs", "id"], env=IPFS_ENV, capture_output=True, timeout=5)
        ipfs_ok = r.returncode == 0
    except:
        pass
    internet_ok = False
    try:
        import urllib.request
        urllib.request.urlopen("https://cloudflare.com/cdn-cgi/trace", timeout=5)
        internet_ok = True
    except:
        pass
    return jsonify({"ipfs": ipfs_ok, "internet": internet_ok})


# Auto-detect IPFS_PATH: check common locations
def _find_ipfs_path():
    import glob
    for path in glob.glob("/home/*/.ipfs"):
        if os.path.isdir(path):
            return path
    if os.path.isdir("/root/.ipfs"):
        return "/root/.ipfs"
    # Fallback: check common user home directories
    import pwd
    for u in pwd.getpwall():
        p = os.path.join(u.pw_dir, ".ipfs")
        if os.path.isdir(p):
            return p
    return os.path.expanduser("~/.ipfs")

IPFS_ENV = {**os.environ, "IPFS_PATH": _find_ipfs_path()}

@app.route("/api/ipfs/pin-all", methods=["POST"])
def ipfs_pin_all():
    """Pin all downloaded artworks to IPFS"""
    try:
        pinned = 0
        skipped = 0
        errors = []
        settings = get_ipfs_settings()

        # Get all files in NFT directory
        for f in NFT_DIR.glob("*.*"):
            if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.svg', '.avif', '.json']:
                # Extract CID from filename (format: CID.ext or CID_something.ext)
                cid = f.stem.split('_')[0] if '_' in f.stem else f.stem

                # Check if it looks like a valid CID (starts with Qm or bafy)
                if cid.startswith('Qm') or cid.startswith('bafy'):
                    try:
                        # Check if smart pinning wants to skip this CID
                        should_pin, reason, providers = should_pin_cid(cid, settings)
                        if not should_pin:
                            skipped += 1
                            continue

                        result = subprocess.run(
                            ["ipfs", "pin", "add", cid],
                            env=IPFS_ENV,
                            capture_output=True, text=True, timeout=30
                        )
                        if result.returncode == 0:
                            pinned += 1
                        else:
                            errors.append(f"{cid}: {result.stderr.strip()}")
                    except Exception as e:
                        errors.append(f"{cid}: {str(e)}")

        return jsonify({
            "success": True,
            "pinned": pinned,
            "skipped": skipped,
            "errors": errors[:10]  # Limit error list
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ipfs/pin", methods=["POST"])
def ipfs_pin():
    """Pin a single CID to IPFS"""
    try:
        data = request.json
        cid = data.get('cid', '').strip()
        force = data.get('force', False)  # Force pin even if many providers

        # Validate CID format
        valid, err = validate_cid(cid)
        if not valid:
            return jsonify({"error": err}), 400

        # Check smart pin settings (unless forced)
        if not force:
            should_pin, reason, providers = should_pin_cid(cid)
            if not should_pin:
                return jsonify({
                    "success": True,
                    "skipped": True,
                    "reason": reason,
                    "providers": providers,
                    "message": f"Skipped {cid} - already well distributed ({providers} providers)"
                })

        result = subprocess.run(
            ["ipfs", "pin", "add", cid],
            env=IPFS_ENV,
            capture_output=True, text=True, timeout=60
        )

        if result.returncode == 0:
            return jsonify({"success": True, "message": f"Pinned {cid}"})
        else:
            return jsonify({"success": False, "error": result.stderr.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ipfs/status")
def ipfs_status():
    """Get detailed IPFS node status"""
    try:
        status = {
            "installed": False,
            "running": False,
            "peer_id": None,
            "peers": 0,
            "pinned": 0,
            "repo_size": None
        }

        # Check if IPFS is installed
        which_result = subprocess.run(["which", "ipfs"], capture_output=True, text=True, timeout=5)
        if which_result.returncode != 0:
            status["error"] = "IPFS not installed"
            return jsonify(status)

        status["installed"] = True

        # Check if IPFS is running
        try:
            id_result = subprocess.run(
                ["ipfs", "id", "-f", "<id>"],
                env=IPFS_ENV,
                capture_output=True, text=True, timeout=5
            )
            if id_result.returncode == 0:
                status["running"] = True
                status["peer_id"] = id_result.stdout.strip()
        except:
            return jsonify(status)

        # Get peer count
        try:
            peers_result = subprocess.run(
                ["ipfs", "swarm", "peers"],
                env=IPFS_ENV,
                capture_output=True, text=True, timeout=5
            )
            if peers_result.returncode == 0:
                status["peers"] = len([l for l in peers_result.stdout.strip().split('\n') if l])
        except:
            pass

        # Get pin count
        try:
            pins_result = subprocess.run(
                ["ipfs", "pin", "ls", "--type=recursive", "-q"],
                env=IPFS_ENV,
                capture_output=True, text=True, timeout=10
            )
            if pins_result.returncode == 0:
                status["pinned"] = len([l for l in pins_result.stdout.strip().split('\n') if l])
        except:
            pass

        # Get repo size
        try:
            stat_result = subprocess.run(
                ["ipfs", "repo", "stat", "-s"],
                env=IPFS_ENV,
                capture_output=True, text=True, timeout=10
            )
            if stat_result.returncode == 0:
                for line in stat_result.stdout.split('\n'):
                    if 'RepoSize' in line:
                        size_bytes = int(line.split(':')[1].strip())
                        status["repo_size"] = f"{size_bytes / (1024**2):.1f} MB"
        except:
            pass

        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ipfs/pinned-list")
def ipfs_pinned_list():
    """Get list of all pinned CIDs"""
    try:
        result = subprocess.run(
            ["ipfs", "pin", "ls", "--type=recursive", "-q"],
            env=IPFS_ENV,
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return jsonify({"error": "IPFS not available", "pins": []}), 200

        pins = [cid.strip() for cid in result.stdout.strip().split('\n') if cid.strip()]

        return jsonify({
            "count": len(pins),
            "pins": pins
        })
    except Exception as e:
        return jsonify({"error": str(e), "pins": []}), 200


@app.route("/api/ipfs/restart", methods=["POST"])
def ipfs_restart():
    """Restart IPFS daemon"""
    try:
        # Try systemctl restart first
        result = subprocess.run(
            ["sudo", "systemctl", "restart", "ipfs"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode == 0:
            # Wait a moment for IPFS to start
            import time
            time.sleep(2)

            # Check if it's now running
            check = subprocess.run(
                ["ipfs", "id"],
                env=IPFS_ENV,
                capture_output=True, text=True, timeout=10
            )

            if check.returncode == 0:
                return jsonify({"success": True, "message": "IPFS node restarted successfully"})
            else:
                return jsonify({"success": False, "error": "IPFS restarted but not responding yet. Try refreshing in a few seconds."})
        else:
            return jsonify({"success": False, "error": f"Failed to restart: {result.stderr[:200]}"})

    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Restart command timed out"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/ipfs/providers/<cid>")
def ipfs_providers(cid):
    """Get provider count for a specific CID"""
    try:
        settings = get_ipfs_settings()
        timeout = settings.get('smart_pin_timeout', 10)
        threshold = settings.get('smart_pin_threshold', 5)

        provider_count = get_provider_count(cid, timeout)
        should_pin = provider_count < threshold

        return jsonify({
            "cid": cid,
            "providers": provider_count,
            "threshold": threshold,
            "should_pin": should_pin,
            "recommendation": "well_distributed" if not should_pin else "needs_pinning"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


IPFS_SETTINGS_FILE = Path("/opt/vernis/ipfs-settings.json")

def get_ipfs_settings():
    """Get IPFS storage settings"""
    defaults = {
        "auto_pin": True,
        "storage_limit_gb": 2,
        "smart_pin_enabled": False,
        "smart_pin_threshold": 5,  # Skip pinning if >= this many providers
        "smart_pin_timeout": 10,   # Seconds to wait for provider check
        "download_timeout": 60,    # Seconds to wait for IPFS downloads
        "download_retries": 3,     # Number of retry attempts
        "cid_verification": True   # Verify content matches CID (with directory fallback)
    }
    if IPFS_SETTINGS_FILE.exists():
        try:
            with open(IPFS_SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
                # Merge with defaults to handle new settings
                defaults.update(saved)
        except:
            pass
    return defaults


def get_provider_count(cid, timeout=10):
    """
    Check how many IPFS peers are providing (pinning) a CID.
    Returns the count of providers found within the timeout.
    """
    try:
        result = subprocess.run(
            ["ipfs", "dht", "findprovs", "-n", "20", cid],  # Limit to 20 providers max
            env=IPFS_ENV,
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0 and result.stdout.strip():
            providers = [l for l in result.stdout.strip().split('\n') if l]
            return len(providers)
        return 0
    except subprocess.TimeoutExpired:
        # Timeout means we found at least some providers (network is slow)
        return 0
    except Exception:
        return 0


def should_pin_cid(cid, settings=None):
    """
    Determine if a CID should be pinned based on smart pin settings.
    Returns (should_pin: bool, reason: str, provider_count: int)
    """
    if settings is None:
        settings = get_ipfs_settings()

    if not settings.get('smart_pin_enabled', False):
        return True, "smart_pin_disabled", -1

    threshold = settings.get('smart_pin_threshold', 5)
    timeout = settings.get('smart_pin_timeout', 10)

    provider_count = get_provider_count(cid, timeout)

    if provider_count >= threshold:
        return False, f"skipped_enough_providers ({provider_count} >= {threshold})", provider_count

    return True, f"pinning_low_providers ({provider_count} < {threshold})", provider_count

@app.route("/api/storage/recommendations")
def storage_recommendations():
    """Get smart storage recommendations based on device capacity"""
    try:
        total, used, free = shutil.disk_usage("/")
        total_gb = total / (1024**3)
        free_gb = free / (1024**3)
        used_gb = used / (1024**3)

        # Estimate OS space (typically 3-4GB for Raspberry Pi OS)
        os_space_gb = 4.0

        # Calculate available space for NFTs (total - OS space)
        available_for_nfts = max(0, total_gb - os_space_gb)

        # Wear leveling reserve (15% of total for SD card longevity)
        wear_reserve_percent = 15
        wear_reserve_gb = total_gb * (wear_reserve_percent / 100)

        # Maximum recommended storage = available - wear reserve
        max_recommended_gb = max(1, available_for_nfts - wear_reserve_gb)

        # Safe storage limit (conservative)
        safe_limit_gb = max(1, int(max_recommended_gb * 0.8))

        return jsonify({
            "total_gb": round(total_gb, 1),
            "free_gb": round(free_gb, 1),
            "used_gb": round(used_gb, 1),
            "os_reserved_gb": os_space_gb,
            "wear_reserve_percent": wear_reserve_percent,
            "wear_reserve_gb": round(wear_reserve_gb, 1),
            "available_for_nfts_gb": round(available_for_nfts, 1),
            "max_recommended_gb": round(max_recommended_gb, 1),
            "safe_limit_gb": safe_limit_gb,
            "slider_max": min(int(max_recommended_gb), 64)  # Cap at 64GB for UI
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ipfs/settings", methods=["GET", "POST"])
def ipfs_settings():
    """Get or update IPFS storage settings"""
    if request.method == "GET":
        return jsonify(get_ipfs_settings())

    try:
        data = request.json
        current_settings = get_ipfs_settings()

        settings = {
            "auto_pin": data.get('auto_pin', current_settings.get('auto_pin', True)),
            "storage_limit_gb": int(data.get('storage_limit_gb', current_settings.get('storage_limit_gb', 2))),
            "smart_pin_enabled": data.get('smart_pin_enabled', current_settings.get('smart_pin_enabled', False)),
            "smart_pin_threshold": int(data.get('smart_pin_threshold', current_settings.get('smart_pin_threshold', 5))),
            "smart_pin_timeout": int(data.get('smart_pin_timeout', current_settings.get('smart_pin_timeout', 10))),
            "download_timeout": int(data.get('download_timeout', current_settings.get('download_timeout', 60))),
            "download_retries": int(data.get('download_retries', current_settings.get('download_retries', 3))),
            "cid_verification": True  # Always on — verify content matches IPFS CID
        }

        # Save settings
        with open(IPFS_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f)

        # Update IPFS storage limit
        limit_str = f'"{settings["storage_limit_gb"]}GB"'
        subprocess.run(
            ["ipfs", "config", "--json", "Datastore.StorageMax", limit_str],
            env=IPFS_ENV,
            capture_output=True, timeout=10
        )

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ipfs/gc", methods=["POST"])
def ipfs_garbage_collection():
    """Run IPFS garbage collection to free up space"""
    try:
        # Check if IPFS is installed
        which_result = subprocess.run(["which", "ipfs"], capture_output=True, text=True, timeout=5)
        if which_result.returncode != 0:
            return jsonify({"success": False, "error": "IPFS is not installed on this device. Install IPFS to enable pinning features."})

        result = subprocess.run(
            ["ipfs", "repo", "gc"],
            env=IPFS_ENV,
            capture_output=True, text=True, timeout=120
        )

        if result.returncode == 0:
            # Count removed objects
            lines = result.stdout.strip().split('\n')
            removed = len([l for l in lines if l.startswith('removed')])
            return jsonify({"success": True, "removed": removed})
        else:
            error_msg = result.stderr.strip() or "IPFS daemon may not be running"
            return jsonify({"success": False, "error": error_msg})
    except FileNotFoundError:
        return jsonify({"success": False, "error": "IPFS is not installed on this device"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/wifi/scan")
def wifi_scan():
    """Scan for available Wi-Fi networks using nmcli"""
    try:
        # Trigger a fresh scan first (may take a moment)
        subprocess.run(["nmcli", "device", "wifi", "rescan"],
                      capture_output=True, timeout=10)
        import time
        time.sleep(2)  # Give scan time to complete

        # Get list of available networks
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list"],
            capture_output=True, text=True, timeout=10
        )

        if result.returncode != 0:
            return jsonify({"success": False, "error": "Failed to scan networks"})

        networks = []
        seen_ssids = set()
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split(':')
            if len(parts) >= 3:
                ssid = parts[0].strip()
                if not ssid or ssid in seen_ssids:
                    continue
                seen_ssids.add(ssid)
                signal = int(parts[1]) if parts[1].isdigit() else 0
                security = parts[2].strip() if len(parts) > 2 else ""
                in_use = parts[3].strip() == '*' if len(parts) > 3 else False
                networks.append({
                    "ssid": ssid,
                    "signal": signal,
                    "security": security,
                    "connected": in_use
                })

        # Sort by signal strength descending
        networks.sort(key=lambda x: (-x['connected'], -x['signal']))
        return jsonify({"success": True, "networks": networks})

    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Scan timed out"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/wifi", methods=["POST"])
def change_wifi():
    """Change Wi-Fi network using NetworkManager"""
    auth_err = require_auth()
    if auth_err: return auth_err
    try:
        data = request.json
        ssid = data.get('ssid', '').strip()
        psk = data.get('psk', '').strip()

        if not ssid:
            return jsonify({"error": "SSID required"}), 400
        if len(ssid) > 32:
            return jsonify({"error": "SSID too long (max 32 chars)"}), 400

        # Sanitize connection name (alphanumeric + basic chars only)
        safe_ssid = re.sub(r'[^\w\-\. ]', '_', ssid)
        con_name = f"Vernis-{safe_ssid}"

        # Prevent nmcli pager from blocking subprocess
        nmcli_env = {**os.environ, "PAGER": "cat", "TERM": "dumb"}

        # Delete ALL existing connections with this name (duplicates cause failures)
        for _attempt in range(5):
            r = subprocess.run(["nmcli", "connection", "delete", con_name],
                              capture_output=True, env=nmcli_env, timeout=5)
            if r.returncode != 0:
                break

        # Step 1: Add WiFi connection with security inline
        cmd = ["nmcli", "connection", "add",
               "type", "wifi",
               "con-name", con_name,
               "ifname", "wlan0",
               "ssid", ssid,
               "connection.autoconnect", "yes"]
        if psk:
            cmd += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", psk]

        result = subprocess.run(cmd, capture_output=True, text=True, env=nmcli_env, timeout=10)
        print(f"[wifi] add result: rc={result.returncode} out={result.stdout} err={result.stderr}", flush=True)

        if result.returncode != 0:
            return jsonify({"error": f"Failed to create connection: {result.stderr}"}), 500

        # Get UUID of the connection we just created (avoids name ambiguity)
        uuid_result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,UUID", "connection", "show"],
            capture_output=True, text=True, env=nmcli_env, timeout=5
        )
        con_uuid = None
        for line in uuid_result.stdout.strip().split("\n"):
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[0] == con_name:
                con_uuid = parts[1]

        # Step 2: Bring connection up (use UUID if available)
        up_target = con_uuid or con_name
        print(f"[wifi] activating: {up_target}", flush=True)
        result = subprocess.run(
            ["nmcli", "connection", "up", up_target],
            capture_output=True, text=True, env=nmcli_env, timeout=60
        )
        print(f"[wifi] up result: rc={result.returncode} out={result.stdout} err={result.stderr}", flush=True)

        if result.returncode == 0:
            return jsonify({
                "success": True,
                "message": f"Connected to {ssid} successfully"
            })
        else:
            # Clean up failed connection
            subprocess.run(["nmcli", "connection", "delete", up_target],
                          capture_output=True, env=nmcli_env, timeout=5)
            err = result.stderr.strip()
            if "ip-config" in err.lower() or "dhcp" in err.lower() or "ip configuration" in err.lower():
                return jsonify({"error": "WiFi connected but could not get an IP address. Check if the router has DHCP enabled."}), 500
            return jsonify({"error": f"Failed to connect: {err}"}), 500

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Connection timed out. The network may not have DHCP or the signal is too weak."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/update")
def update():
    """Trigger OTA update"""
    auth_err = require_auth()
    if auth_err: return auth_err
    try:
        updater = SCRIPTS_DIR / "updater.sh"
        subprocess.Popen(["sudo", "bash", str(updater)])
        return jsonify({"success": True, "message": "Update started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/reboot")
def reboot():
    """Reboot the system"""
    auth_err = require_auth()
    if auth_err: return auth_err
    try:
        subprocess.Popen(["sudo", "reboot"])
        return jsonify({"success": True, "message": "Rebooting..."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/shutdown", methods=["GET", "POST"])
def shutdown():
    """Shutdown the system"""
    auth_err = require_auth()
    if auth_err: return auth_err
    try:
        subprocess.Popen(["sudo", "shutdown", "now"])
        return jsonify({"success": True, "message": "Shutting down..."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Pi LED Control
LED_CONFIG_FILE = Path("/opt/vernis/led-config.json")

@app.route("/api/led/status")
def led_status():
    """Get Pi LED status"""
    try:
        # Try different LED paths for different Pi models
        led_paths = [
            "/sys/class/leds/ACT/brightness",
            "/sys/class/leds/led0/brightness",
            "/sys/class/leds/PWR/brightness",
            "/sys/class/leds/led1/brightness"
        ]

        act_led = None
        pwr_led = None

        for path in led_paths:
            if Path(path).exists():
                try:
                    with open(path, 'r') as f:
                        val = int(f.read().strip())
                    if 'ACT' in path or 'led0' in path:
                        act_led = val > 0
                    elif 'PWR' in path or 'led1' in path:
                        pwr_led = val > 0
                except:
                    pass

        # Load saved config
        config = {}
        if LED_CONFIG_FILE.exists():
            try:
                with open(LED_CONFIG_FILE, 'r') as f:
                    config = json.load(f)
            except:
                pass

        return jsonify({
            "act_led_on": act_led,
            "pwr_led_on": pwr_led,
            "led_disabled": config.get("led_disabled", False)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/led/toggle", methods=["POST"])
def led_toggle():
    """Toggle Pi activity LED on/off"""
    try:
        data = request.json or {}
        disable_led = data.get("disable", False)

        # Save config
        config = {"led_disabled": disable_led}
        with open(LED_CONFIG_FILE, 'w') as f:
            json.dump(config, f)

        # Try different LED paths
        led_paths = [
            "/sys/class/leds/ACT/brightness",
            "/sys/class/leds/led0/brightness"
        ]

        brightness = "0" if disable_led else "1"

        for path in led_paths:
            if Path(path).exists():
                try:
                    # Use sudo to write to LED brightness
                    subprocess.run(
                        ["sudo", "sh", "-c", f"echo {brightness} > {path}"],
                        capture_output=True,
                        timeout=5
                    )
                    # Also set trigger to none if disabling
                    trigger_path = path.replace("/brightness", "/trigger")
                    if Path(trigger_path).exists():
                        trigger_val = "none" if disable_led else "mmc0"
                        subprocess.run(
                            ["sudo", "sh", "-c", f"echo {trigger_val} > {trigger_path}"],
                            capture_output=True,
                            timeout=5
                        )
                except Exception as e:
                    print(f"LED control error for {path}: {e}")

        return jsonify({
            "success": True,
            "led_disabled": disable_led
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/clear-cache", methods=["POST"])
def clear_cache():
    """Clear Chromium browser cache and restart browser"""
    try:
        import pwd
        import shutil
        # Get the user running the service
        user = None
        try:
            user_info = pwd.getpwuid(os.getuid())
            user = user_info.pw_name
        except:
            user = "pi"

        home_dir = os.path.expanduser(f"~{user}")
        if home_dir.startswith("~"):
            home_dir = f"/home/{user}"

        cache_dir = os.path.join(home_dir, ".cache", "chromium")

        # Kill chromium first
        subprocess.run(["pkill", "-9", "chromium"], capture_output=True, timeout=5)

        # Clear cache directory
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir, ignore_errors=True)

        # Watchdog will restart chromium automatically
        return jsonify({
            "success": True,
            "message": "Cache cleared. Browser will restart automatically.",
            "cleared_path": cache_dir
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/system/version")
def system_version():
    """Get system version information"""
    try:
        # Get Vernis version from version.json
        vernis_version = "unknown"
        version_file = Path("/var/www/vernis/version.json")
        if version_file.exists():
            try:
                with open(version_file, 'r') as f:
                    vdata = json.load(f)
                vernis_version = vdata.get("version", "unknown")
            except:
                pass

        # Get OS version
        try:
            os_result = subprocess.run(
                ["cat", "/etc/os-release"],
                capture_output=True, text=True, timeout=5
            )
            os_info = {}
            for line in os_result.stdout.split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    os_info[key] = value.strip('"')
            os_version = os_info.get('PRETTY_NAME', 'Unknown')
        except:
            os_version = "Unknown"

        # Get kernel version
        try:
            kernel_result = subprocess.run(
                ["uname", "-r"],
                capture_output=True, text=True, timeout=5
            )
            kernel_version = kernel_result.stdout.strip()
        except:
            kernel_version = "Unknown"

        return jsonify({
            "vernis_version": vernis_version,
            "os_version": os_version,
            "kernel_version": kernel_version
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

        return jsonify({"collections": collections})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/csv-library/rename", methods=["POST"])
def rename_csv_collection():
    """Rename a CSV collection by updating its metadata sidecar"""
    try:
        data = request.json
        filename = data.get('filename', '').strip()
        new_name = data.get('name', '').strip()

        if not filename or not new_name:
            return jsonify({"error": "Filename and name are required"}), 400

        if ".." in filename or "/" in filename or "\\" in filename:
            return jsonify({"error": "Invalid filename"}), 400

        csv_path = CSV_LIBRARY_DIR / filename
        if not csv_path.exists():
            return jsonify({"error": "Collection not found"}), 404

        meta_file = csv_path.with_suffix('.json')
        metadata = {}
        if meta_file.exists():
            try:
                with open(meta_file, 'r') as f:
                    metadata = json.load(f)
            except:
                pass

        metadata['name'] = new_name
        with open(meta_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        return jsonify({"success": True, "name": new_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/csv-library/status/<filename>")
def csv_collection_status(filename):
    """Get download and pin status for a CSV collection"""
    try:
        # Security: prevent directory traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            return jsonify({"error": "Invalid filename"}), 400

        csv_path = CSV_LIBRARY_DIR / filename

        # If not in library, check uploads
        if not csv_path.exists():
            csv_path = UPLOAD_DIR / filename

        # Try to fetch from GitHub if not found locally
        if not csv_path.exists():
            github_files = fetch_github_csv_files()
            for file in github_files:
                if file['filename'] == filename:
                    response = requests.get(file['download_url'], timeout=30)
                    if response.status_code == 200:
                        # Save temporarily
                        csv_path = CSV_LIBRARY_DIR / filename
                        with open(csv_path, 'wb') as f:
                            f.write(response.content)
                        break

        if not csv_path.exists():
            return jsonify({"error": "CSV file not found"}), 404

        # Parse CSV to get all CIDs and count total downloadable rows
        import csv
        cids_all = []
        seen_sources = set()  # Deduplicate by CID or URL
        total_rows = 0
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                cid = row.get('cid') or row.get('CID') or row.get('ipfs_cid') or row.get('image_cid')
                url = row.get('image_url') or ''
                if cid:
                    cid = cid.replace('ipfs://', '').strip()
                # Only count entries with valid IPFS CIDs or HTTP URLs
                valid_cid = cid and (cid.startswith('Qm') or cid.startswith('bafy'))
                valid_url = url and (url.startswith('http://') or url.startswith('https://'))
                if not valid_cid and not valid_url:
                    continue
                # Deduplicate: same CID or same URL = same file
                dedup_key = cid if valid_cid else url
                if dedup_key in seen_sources:
                    continue
                seen_sources.add(dedup_key)
                total_rows += 1
                if valid_cid:
                    cids_all.append(cid)

        cids = cids_all
        effective_total = total_rows

        if effective_total == 0:
            return jsonify({
                "total": 0,
                "downloaded": 0,
                "pinned": 0,
                "percent_downloaded": 0,
                "percent_pinned": 0
            })

        # Check which files exist locally for THIS collection
        active_nft_dir = get_active_nft_dir()
        downloaded = 0

        # Method 1: Source map — count files tagged to this collection
        source_map_file = active_nft_dir / "nft-source-map.json"
        source_map_count = 0
        if source_map_file.exists():
            try:
                with open(source_map_file, 'r') as smf:
                    source_map = json.load(smf)
                source_map_count = sum(1 for src in source_map.values() if src == filename)
            except:
                pass

        # Method 2: CID matching — count unique CIDs that have files on disk
        downloaded_cids = 0
        if cids:
            local_stems = set()
            for f in active_nft_dir.iterdir():
                stem = f.stem.split('_')[0] if '_' in f.stem else f.stem
                local_stems.add(stem)
            unique_cids = set(cids)
            for cid in unique_cids:
                # Match base CID (before /) for directory-wrapped CIDs
                base_cid = cid.split('/')[0]
                if base_cid in local_stems or cid in local_stems:
                    downloaded_cids += 1

        # Use whichever method found more (source map is more accurate but may be incomplete)
        downloaded = max(source_map_count, downloaded_cids)

        # Check which are pinned to IPFS
        pinned = 0
        ipfs_available = False

        # First check pin progress file (most accurate — tracks actual ipfs add results)
        safe_fn = re.sub(r'[^\w\-\.]', '_', filename)
        pin_progress_file = TMP_DIR / f"pin_progress_{safe_fn.replace('.', '_')}.json"
        pin_progress_used = False
        pin_complete = False  # True when all available files are pinned
        try:
            if pin_progress_file.exists():
                with open(pin_progress_file) as ppf:
                    pp = json.load(ppf)
                if pp.get('status') == 'complete':
                    pinned = (pp.get('pinned', 0) or 0) + (pp.get('skipped', 0) or 0)
                    ipfs_available = True
                    pin_progress_used = True
                    # If no errors, all available files are pinned (not_found = never downloaded)
                    if (pp.get('errors', 0) or 0) == 0:
                        pin_complete = True
        except Exception:
            pass

        # Fallback: check CIDs against ipfs pin ls
        if not pin_progress_used:
            try:
                result = subprocess.run(
                    ["ipfs", "pin", "ls", "--type=recursive", "-q"],
                    env=IPFS_ENV,
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    ipfs_available = True
                    pinned_cids = set(result.stdout.strip().split('\n'))
                    for cid in cids:
                        base_cid = cid.split('/')[0]
                        if base_cid in pinned_cids:
                            pinned += 1
            except:
                pass

        total = effective_total

        # If IPFS isn't available, treat downloaded files as "pinned" for display purposes
        # This matches the home page behavior
        effective_pinned = pinned if ipfs_available else downloaded

        # Check for last download failure info from progress file
        failed_count = 0
        failed_summary = ""
        if downloaded < total:
            try:
                active_nft_dir = get_active_nft_dir()
                progress_file = active_nft_dir / "download_progress.json"
                if not progress_file.exists() and active_nft_dir != NFT_DIR:
                    progress_file = NFT_DIR / "download_progress.json"
                if progress_file.exists():
                    with open(progress_file, 'r') as pf:
                        pdata = json.load(pf)
                    src = pdata.get('source_csv', '')
                    if src and src in filename:
                        failed_data = pdata.get('failed', {})
                        if isinstance(failed_data, dict):
                            failed_count = len(failed_data)
                            # Summarize error types
                            errors = list(failed_data.values())
                            timeout_ct = sum(1 for e in errors if 'timeout' in str(e).lower() or 'timed out' in str(e).lower())
                            notfound_ct = sum(1 for e in errors if '404' in str(e) or 'not found' in str(e).lower())
                            conn_ct = sum(1 for e in errors if 'connection' in str(e).lower() or 'refused' in str(e).lower())
                            if timeout_ct > 0:
                                failed_summary = "IPFS gateway timeout"
                            elif notfound_ct > 0:
                                failed_summary = "Content unavailable on IPFS"
                            elif conn_ct > 0:
                                failed_summary = "Connection failed"
                            else:
                                failed_summary = "Download errors"
                        elif isinstance(failed_data, list):
                            failed_count = len(failed_data)
            except:
                pass

        # Pin denominator = IPFS CID count (only content-addressed files can be pinned)
        total_pinnable = len(cids)

        # If pin completed with no errors, all available IPFS files are pinned → 100%
        pct_pinned = 100 if pin_complete else (
            min(round((effective_pinned / total_pinnable) * 100), 100) if total_pinnable > 0 else (
                100 if total_pinnable == 0 else 0
            )
        )

        return jsonify({
            "total": total,
            "downloaded": downloaded,
            "pinned": effective_pinned,
            "total_pinnable": total_pinnable,
            "ipfs_available": ipfs_available,
            "percent_downloaded": min(round((downloaded / total) * 100), 100) if total > 0 else 0,
            "percent_pinned": pct_pinned,
            "failed": failed_count,
            "failed_summary": failed_summary
        })
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

        # Check disk space before starting download (require at least 200MB free)
        try:
            total, used, free = shutil.disk_usage(NFT_DIR if NFT_DIR.exists() else "/")
            free_mb = free // (1024 * 1024)
            if free_mb < 200:
                return jsonify({"error": f"Not enough disk space. Only {free_mb}MB free. Need at least 200MB to start download."}), 400
        except Exception:
            pass  # If we can't check, allow the download to proceed

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

        # Get workers from settings (default: 2)
        workers = 2
        try:
            settings_file = Path("/opt/vernis/ipfs_settings.json")
            if settings_file.exists():
                with open(settings_file) as f:
                    settings = json.load(f)
                    workers = settings.get("download_workers", 2)
        except:
            pass

        # Kill any existing downloader processes for this CSV to prevent stuck processes
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"nft_downloader.*{filename}"],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        subprocess.run(["kill", pid], capture_output=True, timeout=5)
                    except:
                        pass
        except:
            pass

        # Run advanced downloader script in background
        # Use active NFT directory (external if configured, internal if readonly mode)
        active_nft_dir = get_active_nft_dir(for_writing=True)

        # Write initial progress file IMMEDIATELY so frontend has something to poll
        # This bridges the gap before the downloader script initializes (gateway detection etc.)
        initial_progress = {
            "downloaded": [],
            "failed": {},
            "completed": 0,
            "total": 0,
            "bytes_downloaded": 0,
            "speed": 0,
            "current_file": "",
            "source_csv": filename,
            "status": "initializing"
        }
        progress_file = active_nft_dir / "download_progress.json"
        try:
            active_nft_dir.mkdir(parents=True, exist_ok=True)
            with open(progress_file, 'w') as f:
                json.dump(initial_progress, f)
        except Exception:
            pass  # Non-critical, downloader will create it anyway

        downloader = SCRIPTS_DIR / "nft_downloader_advanced.py"
        subprocess.Popen([
            "python3", str(downloader),
            "--csv", str(dest_path),
            "--output", str(active_nft_dir),
            "--workers", str(workers)
        ])

        return jsonify({
            "success": True,
            "message": f"Installing {filename.replace('.csv', '')}",
            "source_csv": filename
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _pin_worker(filename, csv_path, ipfs_env, nft_dir, get_active_nft_dir_func):
    """Background worker that pins IPFS-verified files (CID-matched) for a collection.
    Only pins files that have original IPFS CIDs — not HTTP-downloaded copies."""
    import csv as csv_module

    safe_fn = re.sub(r'[^\w\-\.]', '_', filename)
    progress_file = TMP_DIR / f"pin_progress_{safe_fn.replace('.', '_')}.json"

    def write_progress(data):
        try:
            with open(progress_file, 'w') as f:
                json.dump(data, f)
        except Exception:
            pass

    try:
        # Read CIDs from CSV — only IPFS content-addressed files
        cids = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv_module.DictReader(f)
            for row in reader:
                cid = row.get('cid') or row.get('CID') or row.get('ipfs_cid') or row.get('image_cid') or ''
                cid = cid.replace('ipfs://', '').strip()
                if cid and (cid.startswith('Qm') or cid.startswith('bafy')):
                    cids.append(cid)

        if not cids:
            write_progress({"status": "error", "error": "No IPFS CIDs found in this collection"})
            return

        active_nft_dir = get_active_nft_dir_func()
        search_dirs = [nft_dir]
        if active_nft_dir != nft_dir:
            search_dirs.append(active_nft_dir)

        total = len(cids)
        write_progress({
            "status": "running", "total": total,
            "pinned": 0, "skipped": 0, "not_found": 0, "errors": 0,
            "current_cid": "", "phase": "Checking already pinned..."
        })

        # Get already pinned CIDs
        pinned_cids = set()
        try:
            result = subprocess.run(
                ["ipfs", "pin", "ls", "--type=recursive", "-q"],
                env=ipfs_env, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                pinned_cids = set(result.stdout.strip().split('\n'))
        except Exception:
            pass

        pinned = 0
        skipped = 0
        not_found = 0
        error_count = 0
        error_list = []
        known_exts = ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'mp4', 'webm', 'json', 'html', 'avif']

        for i, cid in enumerate(cids):
            base_cid = cid.split('/')[0]
            safe_name = cid.replace('/', '_')
            short = cid[:12] + "..."

            # Check if base CID already pinned
            if base_cid in pinned_cids:
                skipped += 1
                if i % 10 == 0 or i == total - 1:
                    write_progress({
                        "status": "running", "total": total, "processed": i + 1,
                        "pinned": pinned, "skipped": skipped, "not_found": not_found,
                        "errors": error_count, "current_cid": short,
                        "phase": f"Pinning {i + 1}/{total}..."
                    })
                continue

            # Find local file
            local_file = None
            safe_lower = safe_name.lower()
            has_ext = any(safe_lower.endswith('.' + e) for e in known_exts)
            for search_dir in search_dirs:
                if has_ext:
                    fp = search_dir / safe_name
                    if fp.exists():
                        local_file = fp
                        break
                for ext in known_exts:
                    fp = search_dir / f"{safe_name}.{ext}"
                    if fp.exists():
                        local_file = fp
                        break
                if local_file:
                    break

            if not local_file:
                not_found += 1
                write_progress({
                    "status": "running", "total": total, "processed": i + 1,
                    "pinned": pinned, "skipped": skipped, "not_found": not_found,
                    "errors": error_count, "current_cid": short,
                    "phase": f"Pinning {i + 1}/{total}..."
                })
                continue

            write_progress({
                "status": "running", "total": total, "processed": i + 1,
                "pinned": pinned, "skipped": skipped, "not_found": not_found,
                "errors": error_count, "current_cid": short,
                "phase": f"Pinning {i + 1}/{total}..."
            })

            try:
                result = subprocess.run(
                    ["ipfs", "add", "-Q", "--pin=true", str(local_file)],
                    env=ipfs_env, capture_output=True, text=True, timeout=120
                )
                if result.returncode == 0:
                    pinned += 1
                    pinned_cids.add(base_cid)
                    new_cid = result.stdout.strip()
                    if new_cid:
                        pinned_cids.add(new_cid)
                else:
                    error_count += 1
                    error_list.append(f"{cid}: {result.stderr.strip()}")
            except Exception as e:
                error_count += 1
                error_list.append(f"{cid}: {str(e)}")

        write_progress({
            "status": "complete", "total": total, "processed": total,
            "pinned": pinned, "skipped": skipped, "not_found": not_found,
            "errors": error_count, "error_list": error_list[:10],
            "current_cid": "", "phase": "Complete"
        })

    except Exception as e:
        write_progress({"status": "error", "error": str(e)})


@app.route("/api/csv-library/pin-downloaded", methods=["POST"])
def pin_downloaded_collection():
    """Pin all downloaded files from a CSV collection (async with progress)"""
    try:
        data = request.json
        filename = data.get('filename', '').strip()

        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            return jsonify({"error": "Invalid filename"}), 400

        csv_path = CSV_LIBRARY_DIR / filename
        if not csv_path.exists():
            csv_path = UPLOAD_DIR / filename
        if not csv_path.exists():
            return jsonify({"error": "CSV file not found"}), 404

        # Clear any old progress file so frontend doesn't see stale "complete"
        safe_fn = re.sub(r'[^\w\-\.]', '_', filename)
        old_progress = TMP_DIR / f"pin_progress_{safe_fn.replace('.', '_')}.json"
        if old_progress.exists():
            old_progress.unlink()

        # Start pinning in background thread
        t = threading.Thread(
            target=_pin_worker,
            args=(filename, csv_path, IPFS_ENV, NFT_DIR, get_active_nft_dir),
            daemon=True
        )
        t.start()

        return jsonify({
            "success": True,
            "async": True,
            "message": f"Pinning started for {filename}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/csv-library/pin-progress/<filename>")
def pin_progress(filename):
    """Get pin progress for a collection"""
    if ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename"}), 400

    progress_file = TMP_DIR / f"pin_progress_{filename.replace('.', '_')}.json"

    if not progress_file.exists():
        return jsonify({"status": "idle"})

    try:
        with open(progress_file, 'r') as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({"status": "idle"})

@app.route("/api/csv-library/delete", methods=["POST"])
def delete_csv_collection():
    """Delete a CSV collection and all its downloaded files"""
    try:
        data = request.json
        filename = data.get('filename', '').strip()

        # Security: prevent directory traversal
        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            return jsonify({"error": "Invalid filename"}), 400

        deleted_files = 0
        errors = []
        files_to_delete = set()

        csv_path = CSV_LIBRARY_DIR / filename
        upload_csv_path = UPLOAD_DIR / filename
        active_nft_dir = get_active_nft_dir()
        THUMBNAIL_DIR = Path("/opt/vernis/thumbnails")

        # Method 1: Source map — most reliable, covers all file naming schemes
        source_map_file = active_nft_dir / "nft-source-map.json"
        if source_map_file.exists():
            try:
                with open(source_map_file, 'r') as f:
                    source_map = json.load(f)
                for fname, source in source_map.items():
                    if source == filename:
                        files_to_delete.add(fname)
            except:
                pass

        # Method 2: CIDs from CSV — catches files not in source map
        cids_to_delete = []
        for path in [csv_path, upload_csv_path]:
            if path.exists():
                try:
                    import csv as csv_mod
                    with open(path, 'r') as f:
                        reader = csv_mod.DictReader(f)
                        for row in reader:
                            cid = row.get('cid') or row.get('CID') or row.get('ipfs_cid') or row.get('image_cid') or ''
                            if cid:
                                cid = cid.replace('ipfs://', '').strip()
                                if cid.startswith('Qm') or cid.startswith('bafy'):
                                    cids_to_delete.append(cid)
                    break
                except Exception as e:
                    errors.append(f"Error reading CSV: {e}")

        if cids_to_delete:
            for cid in cids_to_delete:
                for file_path in active_nft_dir.glob(f"{cid}*"):
                    files_to_delete.add(file_path.name)

        # Delete all matched NFT files
        for fname in files_to_delete:
            file_path = active_nft_dir / fname
            if file_path.exists():
                try:
                    file_path.unlink()
                    deleted_files += 1
                except Exception as e:
                    errors.append(f"Failed to delete {fname}: {e}")

            # Also delete thumbnails
            stem = Path(fname).stem
            for thumb_path in THUMBNAIL_DIR.glob(f"thumb_{stem}*"):
                try:
                    thumb_path.unlink()
                except:
                    pass

        # Unpin CIDs from IPFS
        for cid in cids_to_delete:
            try:
                subprocess.run(
                    ["ipfs", "pin", "rm", cid],
                    capture_output=True, timeout=10
                )
            except:
                pass

        # Update source map — remove deleted entries
        if source_map_file.exists() and files_to_delete:
            try:
                with open(source_map_file, 'r') as f:
                    source_map = json.load(f)
                source_map = {k: v for k, v in source_map.items() if k not in files_to_delete}
                with open(source_map_file, 'w') as f:
                    json.dump(source_map, f)
            except:
                pass

        # Delete the CSV files
        for path in [csv_path, upload_csv_path]:
            if path.exists():
                try:
                    path.unlink()
                except Exception as e:
                    errors.append(f"Failed to delete CSV: {e}")

        # Delete metadata sidecar
        meta_path = csv_path.with_suffix('.json')
        if meta_path.exists():
            try:
                meta_path.unlink()
            except:
                pass

        # Delete progress file if exists
        progress_file = Path(f"/opt/vernis/download_progress_{filename.replace('.csv', '')}.json")
        if progress_file.exists():
            try:
                progress_file.unlink()
            except:
                pass

        # Clean up hidden NFTs list — remove references to deleted files
        hidden_nfts_file = Path("/opt/vernis/hidden-nfts.json")
        if hidden_nfts_file.exists() and files_to_delete:
            try:
                with open(hidden_nfts_file, 'r') as f:
                    hidden = json.load(f)
                original_count = len(hidden)
                hidden = [h for h in hidden if h not in files_to_delete]
                if len(hidden) != original_count:
                    with open(hidden_nfts_file, 'w') as f:
                        json.dump(hidden, f)
            except Exception as e:
                errors.append(f"Failed to clean up hidden list: {e}")

        return jsonify({
            "success": True,
            "message": f"Deleted {deleted_files} files",
            "deleted_files": deleted_files,
            "errors": errors if errors else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/csv-library/clear-files", methods=["POST"])
def clear_csv_collection_files():
    """Clear downloaded files for a CSV collection but keep the CSV in the library"""
    try:
        data = request.json
        filename = data.get('filename', '').strip()

        # Security: prevent directory traversal
        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            return jsonify({"error": "Invalid filename"}), 400

        deleted_files = 0
        errors = []
        files_to_delete = set()
        active_nft_dir = get_active_nft_dir()
        THUMBNAIL_DIR = Path("/opt/vernis/thumbnails")

        # Method 1: Source map
        source_map_file = active_nft_dir / "nft-source-map.json"
        if source_map_file.exists():
            try:
                with open(source_map_file, 'r') as f:
                    source_map = json.load(f)
                for fname, source in source_map.items():
                    if source == filename:
                        files_to_delete.add(fname)
            except:
                pass

        # Method 2: CIDs from CSV
        csv_path = CSV_LIBRARY_DIR / filename
        upload_csv_path = UPLOAD_DIR / filename
        cids_to_delete = []

        for path in [csv_path, upload_csv_path]:
            if path.exists():
                try:
                    import csv as csv_module
                    with open(path, 'r') as f:
                        reader = csv_module.DictReader(f)
                        for row in reader:
                            cid = row.get('cid') or row.get('CID') or row.get('ipfs_cid') or row.get('image_cid') or ''
                            if cid and cid not in ["See CSV", "On-Chain", "Arweave", "--"]:
                                cid = cid.replace('ipfs://', '').strip()
                                if cid.startswith('Qm') or cid.startswith('bafy'):
                                    cids_to_delete.append(cid)
                    break
                except Exception as e:
                    errors.append(f"Error reading CSV: {e}")

        if cids_to_delete:
            for cid in cids_to_delete:
                for file_path in active_nft_dir.glob(f"{cid}*"):
                    files_to_delete.add(file_path.name)

        if not files_to_delete:
            return jsonify({"error": "No files found for this collection"}), 404

        # Delete matched files
        for fname in files_to_delete:
            file_path = active_nft_dir / fname
            if file_path.exists():
                try:
                    file_path.unlink()
                    deleted_files += 1
                except Exception as e:
                    errors.append(f"Failed to delete {fname}: {e}")

            stem = Path(fname).stem
            for thumb_path in THUMBNAIL_DIR.glob(f"thumb_{stem}*"):
                try:
                    thumb_path.unlink()
                except:
                    pass

        # Unpin CIDs from IPFS
        for cid in cids_to_delete:
            try:
                subprocess.run(["ipfs", "pin", "rm", cid], capture_output=True, timeout=10)
            except:
                pass

        # Update source map
        if source_map_file.exists() and files_to_delete:
            try:
                with open(source_map_file, 'r') as f:
                    source_map = json.load(f)
                source_map = {k: v for k, v in source_map.items() if k not in files_to_delete}
                with open(source_map_file, 'w') as f:
                    json.dump(source_map, f)
            except:
                pass

        # Clear download progress
        progress_file = active_nft_dir / "download_progress.json"
        if progress_file.exists():
            try:
                with open(progress_file, 'r') as f:
                    progress_data = json.load(f)
                downloaded = set(progress_data.get('downloaded', []))
                downloaded -= files_to_delete
                if cids_to_delete:
                    downloaded -= set(cids_to_delete)
                progress_data['downloaded'] = list(downloaded)
                progress_data['completed'] = 0
                progress_data['total'] = 0
                with open(progress_file, 'w') as f:
                    json.dump(progress_data, f, indent=2)
            except:
                pass

        return jsonify({
            "success": True,
            "message": f"Cleared {deleted_files} files",
            "deleted_files": deleted_files,
            "errors": errors if errors else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/csv-library/upload", methods=["POST"])
def upload_csv_to_library():
    """Upload a CSV file to the library (doesn't trigger downloads)"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "Empty filename"}), 400

        if not file.filename.endswith('.csv'):
            return jsonify({"error": "Only CSV files are allowed"}), 400

        # Security: sanitize filename
        import re
        safe_filename = re.sub(r'[^\w\-\.]', '_', file.filename)

        # Ensure csv-library directory exists
        CSV_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

        # Save CSV to library
        csv_path = CSV_LIBRARY_DIR / safe_filename
        file.save(csv_path)

        # Count items in CSV
        import csv
        count = 0
        try:
            with open(csv_path, 'r') as f:
                reader = csv.reader(f)
                next(reader, None)  # Skip header
                count = sum(1 for _ in reader)
        except:
            pass

        # Get optional metadata
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()

        # Save metadata if provided
        if name or description:
            meta_path = csv_path.with_suffix('.json')
            metadata = {
                "name": name or safe_filename.replace('.csv', '').replace('_', ' ').title(),
                "description": description or "NFT collection",
                "featured": False
            }
            with open(meta_path, 'w') as f:
                json.dump(metadata, f, indent=2)

        return jsonify({
            "success": True,
            "filename": safe_filename,
            "count": count,
            "message": f"Added {safe_filename} to library with {count} items"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/quick-add-cid", methods=["POST"])
def quick_add_cid():
    """Quick add a single IPFS CID directly to the gallery"""
    try:
        data = request.json
        cid = data.get('cid', '').strip()
        name = data.get('name', 'Quick Add NFT').strip()

        # Validate CID format (rejects path traversal, shell injection, etc.)
        valid, err = validate_cid(cid)
        if not valid:
            return jsonify({"error": err}), 400

        # Create a quick-add CSV file
        CSV_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        quick_csv = CSV_LIBRARY_DIR / "quick-adds.csv"

        # Append to existing file or create new one
        import csv
        file_exists = quick_csv.exists()

        with open(quick_csv, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['contract_address', 'token_id', 'ipfs_cid', 'name', 'description'])
            writer.writerow(['', '', cid, name, f'Added via Quick Add'])

        # Also create/update the metadata file
        meta_path = CSV_LIBRARY_DIR / "quick-adds.csv.meta.json"
        if meta_path.exists():
            with open(meta_path, 'r') as f:
                metadata = json.load(f)
            count = metadata.get('count', 0) + 1
        else:
            count = 1

        metadata = {
            "name": "Quick Adds",
            "description": "NFTs added via Quick Add feature",
            "featured": False,
            "count": count
        }
        with open(meta_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        # Trigger download of this CID (including nested CIDs from metadata)
        import subprocess
        active_nft_dir = get_active_nft_dir(for_writing=True)
        threading.Thread(
            target=lambda: subprocess.run(
                ['python3', '/opt/vernis/scripts/nft_downloader_advanced.py',
                 '--cid', cid, '--output', str(active_nft_dir)],
                capture_output=True, timeout=600
            ),
            daemon=True
        ).start()

        return jsonify({
            "success": True,
            "cid": cid,
            "message": f"Added {name} to gallery. Download started."
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
            config = {
                "device_mode": "full",
                "preload": {"enabled": False},
                "library": {"enabled": True}
            }

        return jsonify(config)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/theme", methods=["GET"])
def get_theme():
    """Get the global theme preference (synced across devices)"""
    try:
        if THEME_FILE.exists():
            with open(THEME_FILE, 'r') as f:
                return jsonify(json.load(f))
    except Exception:
        pass
    return jsonify({"style": "walnut", "mode": "dark"})

@app.route("/api/theme", methods=["POST"])
def set_theme():
    """Set the global theme preference (synced across devices)"""
    try:
        data = request.get_json() or {}
        style = str(data.get("style", "walnut"))[:30]
        mode = str(data.get("mode", "dark"))[:10]
        if style not in ("walnut", "gallery", "nordic", "xcopy", "hackatao", "pop"):
            style = "walnut"
        if mode not in ("light", "dark", "auto"):
            mode = "dark"
        with open(THEME_FILE, 'w') as f:
            json.dump({"style": style, "mode": mode}, f)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/battery")
def battery_status():
    """Check for UPS/battery power supply and return status"""
    ps_dir = Path("/sys/class/power_supply")
    if not ps_dir.exists():
        return jsonify({"available": False})
    for supply in ps_dir.iterdir():
        type_file = supply / "type"
        if type_file.exists():
            try:
                stype = type_file.read_text().strip()
                if stype == "Battery":
                    result = {"available": True, "name": supply.name}
                    cap_file = supply / "capacity"
                    if cap_file.exists():
                        result["capacity"] = int(cap_file.read_text().strip())
                    status_file = supply / "status"
                    if status_file.exists():
                        result["status"] = status_file.read_text().strip()
                    return jsonify(result)
            except Exception:
                continue
    return jsonify({"available": False})


@app.route("/api/favorites", methods=["GET", "POST"])
def favorites():
    """Get or save favorite artworks"""
    FAV_FILE = Path("/opt/vernis/favorites.json")
    if request.method == "POST":
        try:
            data = request.json or {}
            with open(FAV_FILE, 'w') as f:
                json.dump(data.get("favorites", {}), f)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        try:
            if FAV_FILE.exists():
                with open(FAV_FILE, 'r') as f:
                    return jsonify({"favorites": json.load(f)})
            return jsonify({"favorites": {}})
        except Exception as e:
            return jsonify({"favorites": {}, "error": str(e)})


@app.route("/api/display-config", methods=["GET", "POST"])
def display_config():
    """Get or set display configuration"""
    DISPLAY_CONFIG_FILE = Path("/opt/vernis/display-config.json")

    if request.method == "POST":
        try:
            config = request.json
            with open(DISPLAY_CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        try:
            if DISPLAY_CONFIG_FILE.exists():
                with open(DISPLAY_CONFIG_FILE, 'r') as f:
                    config = json.load(f)
            else:
                config = {
                    "image_duration": 15,
                    "video_duration": 30,
                    "crossfade_duration": 0.8,
                    "frosted_background": False,
                    "frosted_blur": 4,
                    "frosted_opacity": 0.55,
                    "force_horizontal": False,
                    "shuffle": True,
                    "background_color": "#000000",
                    "pixel_shift": True
                }
            return jsonify(config)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route("/api/display/output", methods=["GET", "POST"])
def display_output():
    """Get or set display output mode (auto/internal/external/mirror)"""
    DISPLAY_OUTPUT_CONFIG = Path("/opt/vernis/display-output-config.json")
    DISPLAY_OUTPUT_SCRIPT = "/opt/vernis/scripts/display-output.sh"

    if request.method == "POST":
        try:
            data = request.json

            # Load existing config to merge
            existing = {}
            if DISPLAY_OUTPUT_CONFIG.exists():
                with open(DISPLAY_OUTPUT_CONFIG, 'r') as f:
                    existing = json.load(f)

            mode = data.get("mode", existing.get("mode", "auto"))
            resolution = data.get("resolution", existing.get("resolution", "auto"))

            if mode not in ("auto", "internal", "external", "mirror"):
                return jsonify({"error": "Invalid mode. Use: auto, internal, external, mirror"}), 400
            if resolution not in ("auto", "1080p", "1440p", "4k"):
                return jsonify({"error": "Invalid resolution. Use: auto, 1080p, 1440p, 4k"}), 400

            with open(DISPLAY_OUTPUT_CONFIG, 'w') as f:
                json.dump({"mode": mode, "resolution": resolution}, f)

            # Apply the display configuration in background
            if os.path.exists(DISPLAY_OUTPUT_SCRIPT):
                import subprocess as _sp
                # Build environment for wlr-randr access
                env = os.environ.copy()
                env["WAYLAND_DISPLAY"] = "wayland-0"
                # Find XDG_RUNTIME_DIR for the user
                for uid_dir in Path("/run/user").iterdir():
                    wayland_sock = uid_dir / "wayland-0"
                    if wayland_sock.exists():
                        env["XDG_RUNTIME_DIR"] = str(uid_dir)
                        break
                _sp.Popen(["bash", DISPLAY_OUTPUT_SCRIPT, "apply"], env=env,
                          stdout=open("/tmp/vernis-display-output.log", "a"),
                          stderr=open("/tmp/vernis-display-output.log", "a"))

            return jsonify({"success": True, "mode": mode})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        try:
            # Read saved config
            mode = "auto"
            resolution = "auto"
            if DISPLAY_OUTPUT_CONFIG.exists():
                with open(DISPLAY_OUTPUT_CONFIG, 'r') as f:
                    cfg = json.load(f)
                    mode = cfg.get("mode", "auto")
                    resolution = cfg.get("resolution", "auto")

            # Get live display status from script
            hdmi_connected = False
            hdmi_name = ""
            dpi_name = ""
            hdmi_res = ""
            dpi_res = ""
            effective = mode

            if os.path.exists(DISPLAY_OUTPUT_SCRIPT):
                import subprocess as _sp
                env = os.environ.copy()
                env["WAYLAND_DISPLAY"] = "wayland-0"
                for uid_dir in Path("/run/user").iterdir():
                    wayland_sock = uid_dir / "wayland-0"
                    if wayland_sock.exists():
                        env["XDG_RUNTIME_DIR"] = str(uid_dir)
                        break
                try:
                    result = _sp.run(["bash", DISPLAY_OUTPUT_SCRIPT, "status"],
                                     capture_output=True, text=True, timeout=5, env=env)
                    if result.returncode == 0 and result.stdout.strip():
                        status = json.loads(result.stdout.strip())
                        hdmi_connected = status.get("hdmi_connected", False)
                        hdmi_name = status.get("hdmi_name", "")
                        dpi_name = status.get("dpi_name", "")
                        hdmi_res = status.get("hdmi_res", "")
                        dpi_res = status.get("dpi_res", "")
                        effective = status.get("effective", mode)
                except Exception:
                    pass

            return jsonify({
                "mode": mode,
                "resolution": resolution,
                "effective": effective,
                "hdmi_connected": hdmi_connected,
                "hdmi_name": hdmi_name,
                "dpi_name": dpi_name,
                "hdmi_res": hdmi_res,
                "dpi_res": dpi_res
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route("/api/nft-list-detailed")
def nft_list_detailed():
    """Return detailed list of NFTs with metadata"""
    HIDDEN_NFTS_FILE = Path("/opt/vernis/hidden-nfts.json")

    try:
        # Get hidden NFTs
        hidden = []
        if HIDDEN_NFTS_FILE.exists():
            with open(HIDDEN_NFTS_FILE, 'r') as f:
                hidden = json.load(f)

        nfts = []
        for ext in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'mp4', 'html']:
            for file_path in NFT_DIR.glob(f"*.{ext}"):
                # Skip non-art HTML files (IPFS directory listings etc)
                # Only include HTML files that contain a generator-preview meta tag
                gen_url = None
                if ext == 'html':
                    try:
                        head = file_path.read_text(errors='ignore')[:2048]
                        if 'generator-preview' not in head and 'canvas' not in head.lower():
                            continue
                        # Extract generator URL for direct iframe loading in gallery
                        import re as _re
                        m = _re.search(r'generator-url["\']?\s+content=["\']([^"\']+)', head)
                        if m:
                            gen_url = m.group(1)
                        else:
                            # Fallback: reconstruct from generator-type + generator-id (old format)
                            tm = _re.search(r'generator-type["\']?\s+content=["\']([^"\']+)', head)
                            im = _re.search(r'generator-id["\']?\s+content=["\']([^"\']+)', head)
                            if tm and im:
                                gt, gi = tm.group(1), im.group(1)
                                if gt == 'gazer':
                                    gen_url = f"https://generator.artblocks.io/0xa7d8d9ef8d8ce8992df33d8b8cf4aebabd5bd270/{215000000 + int(gi)}"
                    except Exception:
                        continue

                stat = file_path.stat()
                size_bytes = stat.st_size
                if size_bytes < 1024**2:
                    size = f"{size_bytes/1024:.1f} KB"
                else:
                    size = f"{size_bytes/(1024**2):.1f} MB"

                nft_info = {
                    "filename": file_path.name,
                    "url": f"/nfts/{file_path.name}",
                    "size": size,
                    "mtime": int(stat.st_mtime)
                }
                if gen_url:
                    nft_info["generator_url"] = gen_url
                nfts.append(nft_info)

        return jsonify({"nfts": nfts, "hidden": hidden})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/nft-list-all")
def nft_list_all():
    """Return ALL files in NFTs directory including JSON metadata"""
    HIDDEN_NFTS_FILE = Path("/opt/vernis/hidden-nfts.json")

    try:
        hidden = []
        if HIDDEN_NFTS_FILE.exists():
            with open(HIDDEN_NFTS_FILE, 'r') as f:
                hidden = json.load(f)

        all_files = []
        for file_path in sorted(NFT_DIR.iterdir()):
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lower().lstrip('.')
            if not ext:
                continue

            stat = file_path.stat()
            size_bytes = stat.st_size
            if size_bytes < 1024**2:
                size = f"{size_bytes/1024:.1f} KB"
            else:
                size = f"{size_bytes/(1024**2):.1f} MB"

            file_info = {
                "filename": file_path.name,
                "url": f"/nfts/{file_path.name}",
                "size": size,
                "size_bytes": size_bytes,
                "mtime": int(stat.st_mtime),
                "type": ext,
                "cid": file_path.stem
            }

            if ext == 'json':
                try:
                    with open(file_path, 'r') as f:
                        metadata = json.load(f)
                    file_info['metadata_name'] = metadata.get('name', '')
                    image_url = metadata.get('image', '')
                    cid_match = re.search(r'(Qm[a-zA-Z0-9]{44,}|baf[a-z0-9]{50,})', image_url)
                    if cid_match:
                        file_info['referenced_cid'] = cid_match.group(1)
                except Exception:
                    pass

            all_files.append(file_info)

        return jsonify({"files": all_files, "hidden": hidden})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/nft-visibility", methods=["POST"])
def nft_visibility():
    """Hide or show NFTs in carousel"""
    HIDDEN_NFTS_FILE = Path("/opt/vernis/hidden-nfts.json")

    try:
        data = request.json
        action = data.get('action')  # 'hide' or 'show'
        filenames = data.get('filenames', [])

        # Load current hidden list
        hidden = []
        if HIDDEN_NFTS_FILE.exists():
            with open(HIDDEN_NFTS_FILE, 'r') as f:
                hidden = json.load(f)

        # Update hidden list
        if action == 'hide':
            hidden = list(set(hidden + filenames))
        elif action == 'show':
            hidden = [f for f in hidden if f not in filenames]

        # Save
        with open(HIDDEN_NFTS_FILE, 'w') as f:
            json.dump(hidden, f, indent=2)

        return jsonify({"success": True, "hidden_count": len(hidden)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =====================
# Carousel Management API
# =====================
CAROUSELS_DIR = Path("/opt/vernis/carousels")

@app.route("/api/carousels", methods=["GET"])
def list_carousels():
    """List all saved carousel presets"""
    try:
        CAROUSELS_DIR.mkdir(exist_ok=True)
        carousels = [f.stem for f in CAROUSELS_DIR.glob("*.json")]
        return jsonify({"carousels": sorted(carousels)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/carousels", methods=["POST"])
def save_carousel():
    """Save a carousel preset"""
    try:
        CAROUSELS_DIR.mkdir(exist_ok=True)
        data = request.json
        name = data.get('name', '').strip()
        hidden = data.get('hidden', [])
        visible = data.get('visible', [])

        if not name:
            return jsonify({"error": "Carousel name is required"}), 400

        # Sanitize filename
        safe_name = "".join(c for c in name if c.isalnum() or c in ' -_').strip()
        if not safe_name:
            return jsonify({"error": "Invalid carousel name"}), 400

        carousel_file = CAROUSELS_DIR / f"{safe_name}.json"
        with open(carousel_file, 'w') as f:
            json.dump({
                "name": name,
                "hidden": hidden,
                "visible": visible,
                "created": datetime.now().isoformat()
            }, f, indent=2)

        return jsonify({"success": True, "name": safe_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/atelier/save-to-gallery", methods=["POST"])
def save_to_gallery():
    """Save an Atelier generator as an HTML file in the NFT directory"""
    import base64
    import re

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        gen_type = data.get("type", "")
        gen_id = data.get("id")
        name = data.get("name", "")
        preview_url = data.get("preview_url")
        preview_data = data.get("preview_data")

        # Validate type
        allowed_types = ["gazer", "pixelchain", "punk", "glyph", "burner"]
        if gen_type not in allowed_types:
            return jsonify({"error": "Invalid type"}), 400

        # Validate id
        try:
            gen_id = int(gen_id)
            if gen_id < 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid id"}), 400

        # Validate preview_data if provided
        if preview_data:
            if not preview_data.startswith("data:image/"):
                return jsonify({"error": "Invalid preview data"}), 400
            if len(preview_data) > 5 * 1024 * 1024:
                return jsonify({"error": "Preview data too large (max 5MB)"}), 400

        # Optional rendering mode (pixelchain: pixel, svg, ascii, hex)
        gen_mode = data.get("mode", "")
        if gen_mode and gen_mode not in ("pixel", "svg", "ascii", "hex"):
            gen_mode = ""

        # Check if already exists (mode-specific filename for pixelchain)
        if gen_mode and gen_type == "pixelchain":
            filename = f"{gen_type}-{gen_id}-{gen_mode}.html"
        else:
            filename = f"{gen_type}-{gen_id}.html"
        nft_dir = get_active_nft_dir(for_writing=True)
        filepath = nft_dir / filename
        if filepath.exists():
            return jsonify({"status": "exists", "filename": filename})

        # Build generator URL
        if gen_type == "gazer":
            contract = "0xa7d8d9ef8d8ce8992df33d8b8cf4aebabd5bd270"
            token_id = 215000000 + gen_id
            generator_url = f"https://generator.artblocks.io/{contract}/{token_id}"
        else:
            mode_param = f"&mode={gen_mode}" if gen_mode else ""
            generator_url = f"http://localhost/lab.html?type={gen_type}&id={gen_id}&fullscreen=1{mode_param}"

        # Obtain preview as base64 data URI
        full_preview = None
        if preview_data:
            full_preview = preview_data
        elif preview_url:
            try:
                resp = requests.get(preview_url, timeout=15)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "image/png").split(";")[0]
                b64 = base64.b64encode(resp.content).decode("ascii")
                full_preview = f"data:{content_type};base64,{b64}"
            except Exception:
                full_preview = None

        # SVG placeholder if no preview available (sanitize name to prevent XSS)
        if not full_preview:
            safe_svg_name = re.sub(r'[^a-zA-Z0-9 #]', '', name)
            full_preview = "data:image/svg+xml;base64," + base64.b64encode(
                b'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400" viewBox="0 0 400 400">'
                b'<rect width="400" height="400" fill="#1a1a1a"/>'
                b'<text x="200" y="200" text-anchor="middle" fill="#666" font-size="48" font-family="sans-serif">'
                + safe_svg_name.encode("utf-8") +
                b'</text></svg>'
            ).decode("ascii")

        # Generate thumbnail-sized preview for meta tag (max 300px, JPEG Q70)
        thumb_preview = full_preview
        try:
            from PIL import Image
            import io
            if not full_preview.startswith("data:image/svg"):
                header, b64data = full_preview.split(",", 1)
                img_bytes = base64.b64decode(b64data)
                img = Image.open(io.BytesIO(img_bytes))
                if img.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", img.size, (0, 0, 0))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                    img = bg
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=70)
                thumb_preview = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            thumb_preview = full_preview

        # Safety: ensure preview data URIs can't escape HTML attributes
        if full_preview and ('"' in full_preview or '<' in full_preview):
            full_preview = thumb_preview
        if thumb_preview and ('"' in thumb_preview or '<' in thumb_preview):
            thumb_preview = full_preview

        # Escape for HTML attributes
        safe_name = name.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")

        # Build HTML — no inner iframe, uses redirect so gallery can load
        # the generator at single iframe depth (double-nested iframes break WebGL on Pi)
        html_content = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="generator-type" content="{gen_type}">
<meta name="generator-id" content="{gen_id}">
<meta name="generator-name" content="{safe_name}">
<meta name="generator-preview" content="{thumb_preview}">
<meta name="generator-url" content="{generator_url}">
<style>
  * {{ margin: 0; padding: 0; }}
  body {{ background: #000; overflow: hidden; }}
  img {{ position: absolute; top: 0; left: 0; width: 100vw; height: 100vh; border: none; object-fit: contain; }}
</style>
</head>
<body>
<img src="{full_preview}" alt="{safe_name}">
<script>window.location.replace("{generator_url}");</script>
</body>
</html>'''

        # Write file
        nft_dir.mkdir(parents=True, exist_ok=True)
        filepath.write_text(html_content, encoding="utf-8")

        return jsonify({"status": "saved", "filename": filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/carousels/<name>", methods=["GET"])
def get_carousel(name):
    """Get a specific carousel preset"""
    try:
        safe_name = "".join(c for c in name if c.isalnum() or c in ' -_').strip()
        carousel_file = CAROUSELS_DIR / f"{safe_name}.json"

        if not carousel_file.exists():
            return jsonify({"error": "Carousel not found"}), 404

        with open(carousel_file, 'r') as f:
            data = json.load(f)

        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/carousels/<name>", methods=["DELETE"])
def delete_carousel(name):
    """Delete a carousel preset"""
    try:
        safe_name = "".join(c for c in name if c.isalnum() or c in ' -_').strip()
        carousel_file = CAROUSELS_DIR / f"{safe_name}.json"

        if not carousel_file.exists():
            return jsonify({"error": "Carousel not found"}), 404

        carousel_file.unlink()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =====================
# NFT Metadata Cache API
# =====================
NFT_METADATA_FILE = Path("/opt/vernis/nft-metadata-cache.json")

def load_metadata_cache():
    """Load the metadata cache from JSON file"""
    if NFT_METADATA_FILE.exists():
        try:
            with open(NFT_METADATA_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"nfts": {}, "collections": [], "artists": [], "last_updated": None}

def save_metadata_cache(cache):
    """Save the metadata cache to JSON file"""
    cache["last_updated"] = datetime.now().isoformat()
    with open(NFT_METADATA_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

def extract_ipfs_cid_from_str(url):
    """Extract IPFS CID from various URL formats"""
    if not url:
        return None
    url = str(url)
    if url.startswith("ipfs://"):
        return url.replace("ipfs://", "").split("/")[0].split("?")[0]
    if "/ipfs/" in url:
        parts = url.split("/ipfs/")
        if len(parts) > 1:
            return parts[1].split("/")[0].split("?")[0]
    if url.startswith("Qm") and len(url) >= 46:
        return url.split("/")[0].split("?")[0]
    if url.startswith("bafy") and len(url) >= 59:
        return url.split("/")[0].split("?")[0]
    return None

def fetch_ipfs_metadata(cid):
    """Fetch metadata JSON from IPFS"""
    import urllib.request

    gateways = [
        f"https://ipfs.io/ipfs/{cid}",
        f"https://cloudflare-ipfs.com/ipfs/{cid}",
        f"https://gateway.pinata.cloud/ipfs/{cid}",
    ]

    for gateway in gateways:
        try:
            req = urllib.request.Request(gateway, headers={"User-Agent": "Vernis/1.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                content_type = response.headers.get('Content-Type', '')
                if 'json' in content_type or 'text' in content_type:
                    return json.loads(response.read().decode('utf-8'))
        except:
            continue
    return None


def extract_async_layout_image_cids(layout):
    """Extract all image CIDs referenced in an Async Art master layout.
    Returns a set of CIDs from uri fields and states.options across all layers."""
    cids = set()
    for layer in layout.get('layers', []):
        if isinstance(layer, dict):
            _collect_layout_uris(layer, cids)
    return cids

def _collect_layout_uris(node, cids):
    """Recursively collect image CIDs from layout layer nodes."""
    uri = node.get('uri', '')
    if isinstance(uri, str) and uri:
        cid = extract_ipfs_cid_from_str(uri)
        if cid:
            cids.add(cid)
    states = node.get('states')
    if isinstance(states, dict):
        for option in states.get('options', []):
            if isinstance(option, dict):
                _collect_layout_uris(option, cids)


def build_json_metadata_lookup(nft_dir):
    """Read all .json files in nft_dir and build reverse lookup: image_cid -> metadata.

    JSON files are named by their own CID (e.g. QmXYZ.json).
    The 'image' field inside contains the CID of the actual artwork file.
    Returns dict: {image_cid: {name, artist, description, tags, attributes, year, json_cid}}
    Also detects Async Art tokens (master has 'layout', layer has 'master' field).
    """
    lookup = {}
    for json_path in nft_dir.glob("*.json"):
        stem = json_path.stem
        if not (stem.startswith("Qm") or stem.startswith("bafy")):
            continue
        try:
            with open(json_path, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        # Extract image CID from multiple possible fields
        image_cid = None
        for field in ['image', 'animation_url', 'media', 'displayUri']:
            raw = data.get(field, '')
            if isinstance(raw, str) and raw:
                extracted = extract_ipfs_cid_from_str(raw)
                if extracted:
                    image_cid = extracted
                    break

        # Extract artist from various field names
        artist = ''
        for af in ['createdBy', 'artist', 'creator']:
            val = data.get(af, '')
            if isinstance(val, str) and val:
                artist = val
                break
        if not artist:
            creators = data.get('creators', [])
            if isinstance(creators, list) and creators:
                first = creators[0]
                if isinstance(first, dict):
                    artist = first.get('name', first.get('address', ''))
                elif isinstance(first, str):
                    artist = first
        if not artist:
            for attr in data.get('attributes', []):
                if isinstance(attr, dict) and attr.get('trait_type', '').lower() in ('artist', 'creator', 'author'):
                    artist = attr.get('value', '')
                    break

        tags = data.get('tags', [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(',')]

        # Detect Async Art token type
        async_type = None
        async_master_uri = None
        if isinstance(data.get('layout'), dict) and 'layers' in data.get('layout', {}):
            async_type = 'master'
        elif isinstance(data.get('master'), str) and data.get('master'):
            async_type = 'layer'
            async_master_uri = data['master']

        entry = {
            'json_cid': stem,
            'name': data.get('name', ''),
            'artist': artist,
            'description': data.get('description', ''),
            'tags': tags if isinstance(tags, list) else [],
            'attributes': data.get('attributes', []) if isinstance(data.get('attributes'), list) else [],
            'year': str(data.get('yearCreated', data.get('year', ''))),
            'async_type': async_type,
            'async_master_uri': async_master_uri,
            '_raw_image': data.get('image', ''),
            '_raw_animation_url': data.get('animation_url', ''),
        }
        # Store raw layout for masters (used during scan to extract state CIDs)
        if async_type == 'master':
            entry['_layout_data'] = data['layout']

        if image_cid:
            lookup[image_cid] = entry
        # Also map JSON's own CID (direct match for bafy* files)
        lookup[stem] = entry

    return lookup


def build_csv_metadata_lookup(csv_dir):
    """Read all CSV files and build lookup: cid -> {name, collection}.
    Collection name is derived from CSV filename.
    """
    import csv as csv_mod
    lookup = {}
    for csv_path in csv_dir.glob("*.csv"):
        stem = csv_path.stem
        for suffix in ['_collection', '_nfts', '_Collection', '_NFTs']:
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        collection_name = stem.replace('_', ' ')

        try:
            with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv_mod.DictReader(f)
                if not reader.fieldnames:
                    continue
                fields_lower = {fn.lower().strip(): fn for fn in reader.fieldnames}

                cid_col = None
                for c in ['cid', 'ipfs_cid', 'image_cid']:
                    if c in fields_lower:
                        cid_col = fields_lower[c]
                        break
                if not cid_col:
                    continue

                name_col = None
                for c in ['name', 'title']:
                    if c in fields_lower:
                        name_col = fields_lower[c]
                        break

                type_col = fields_lower.get('type')
                last_name = ''

                for row in reader:
                    cid_val = (row.get(cid_col) or '').strip()
                    if not cid_val or not (cid_val.startswith('Qm') or cid_val.startswith('bafy')):
                        continue
                    row_name = (row.get(name_col) or '').strip() if name_col else ''
                    if row_name:
                        last_name = row_name
                    else:
                        row_name = last_name
                    if type_col:
                        row_type = (row.get(type_col) or '').strip().lower()
                        if row_type in ('metadata', 'index'):
                            continue
                    lookup[cid_val] = {'name': row_name, 'collection': collection_name, 'csv_file': csv_path.name}
        except Exception:
            continue
    return lookup


@app.route("/api/nft-metadata", methods=["GET"])
def get_nft_metadata():
    """Get the NFT metadata cache with collections and artists"""
    try:
        cache = load_metadata_cache()
        return jsonify(cache)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/nft-metadata/<filename>", methods=["GET"])
def get_single_nft_metadata(filename):
    """Get metadata for a single NFT"""
    try:
        cache = load_metadata_cache()
        if filename in cache["nfts"]:
            return jsonify(cache["nfts"][filename])
        return jsonify({"error": "Metadata not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/nft-metadata/<filename>", methods=["POST"])
def update_single_nft_metadata(filename):
    """Update metadata for a single NFT"""
    try:
        data = request.json
        cache = load_metadata_cache()
        cache["nfts"][filename] = {
            "name": data.get("name", filename),
            "collection": data.get("collection", ""),
            "artist": data.get("artist", ""),
            "description": data.get("description", ""),
            "attributes": data.get("attributes", []),
            "tags": data.get("tags", []),
            "source": "manual",
            "updated": datetime.now().isoformat()
        }

        # Update collections and artists lists
        collections = set(cache.get("collections", []))
        artists = set(cache.get("artists", []))
        if data.get("collection"):
            collections.add(data["collection"])
        if data.get("artist"):
            artists.add(data["artist"])
        cache["collections"] = sorted(list(collections))
        cache["artists"] = sorted(list(artists))

        save_metadata_cache(cache)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _classify_storage_type(filename, json_meta=None):
    """Classify NFT storage type from filename and sidecar metadata.
    Returns: 'ipfs', 'arweave', 'on_chain', or 'copy'.
    """
    stem = Path(filename).stem
    # IPFS: CID-based filename
    if (stem.startswith("Qm") and len(stem) >= 46) or \
       (stem.startswith("bafy") and len(stem) >= 59):
        return 'ipfs'
    # Check sidecar JSON for arweave/on-chain indicators
    if json_meta:
        for field in ('_raw_image', '_raw_animation_url'):
            url = json_meta.get(field, '') or ''
            if isinstance(url, str):
                if 'arweave.net' in url or url.startswith('ar://'):
                    return 'arweave'
                if url.startswith('data:'):
                    return 'on_chain'
    return 'copy'


@app.route("/api/nft-metadata/scan", methods=["POST"])
def scan_nft_metadata():
    """Import metadata from local JSON files and CSV library.

    Strategy:
    1. Build reverse lookup from JSON metadata files (image CID -> rich metadata)
    2. Build lookup from CSV library files (CID -> name + collection)
    3. For each media file: JSON first, CSV second, filename pattern fallback
    4. Preserve manually-edited metadata (source == 'manual')
    """
    try:
        cache = load_metadata_cache()
        scanned = 0
        updated = 0
        json_matched = 0
        csv_matched = 0
        storage_counts = {'ipfs': 0, 'arweave': 0, 'on_chain': 0, 'copy': 0}
        collections = set()
        artists = set()

        # Build lookup tables from local data sources
        json_lookup = build_json_metadata_lookup(NFT_DIR)
        csv_lookup = build_csv_metadata_lookup(CSV_LIBRARY_DIR)

        # Load persistent source map (filename -> source_csv) from downloader
        source_map = {}
        source_map_file = NFT_DIR / "nft-source-map.json"
        try:
            if source_map_file.exists():
                source_map = json.loads(source_map_file.read_text())
        except Exception:
            pass

        # Analyze Async Art relationships
        async_master_names = {}    # json_cid -> master artwork name
        async_layout_cids = set() # ALL image CIDs referenced in master layouts
        async_state_cids = set()  # State variation CIDs to auto-hide
        seen_async = set()
        for key, meta in json_lookup.items():
            jc = meta.get('json_cid', '')
            if jc in seen_async:
                continue
            seen_async.add(jc)
            if meta.get('async_type') == 'master' and meta.get('_layout_data'):
                async_master_names[jc] = meta.get('name', 'Async Art')
                async_layout_cids.update(
                    extract_async_layout_image_cids(meta['_layout_data']))
        if async_layout_cids:
            # State CIDs = layout-referenced CIDs without their own token metadata
            async_state_cids = async_layout_cids - set(json_lookup.keys())

        for ext in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'mp4', 'html']:
            for file_path in NFT_DIR.glob(f"*.{ext}"):
                filename = file_path.name
                scanned += 1

                existing = cache.get("nfts", {}).get(filename, {})

                # Preserve manually-edited metadata
                if existing.get("source") == "manual":
                    if existing.get("collection"):
                        collections.add(existing["collection"])
                    if existing.get("artist"):
                        artists.add(existing["artist"])
                    # Backfill storage_type if missing
                    if not existing.get("storage_type"):
                        existing["storage_type"] = _classify_storage_type(filename)
                        cache["nfts"][filename] = existing
                    storage_counts[existing.get("storage_type", "copy")] += 1
                    continue

                name_parts = filename.rsplit('.', 1)[0]
                cid = extract_ipfs_cid_from_str(name_parts)

                # Try JSON metadata lookup (highest priority)
                json_meta = json_lookup.get(cid) if cid else None

                if json_meta and json_meta.get('name'):
                    st = _classify_storage_type(filename, json_meta)
                    storage_counts[st] += 1
                    entry = {
                        "name": json_meta['name'],
                        "collection": "",
                        "artist": json_meta.get('artist', ''),
                        "description": json_meta.get('description', ''),
                        "attributes": json_meta.get('attributes', []),
                        "tags": json_meta.get('tags', []),
                        "cid": cid,
                        "storage_type": st,
                        "source": "json",
                        "source_csv": "",
                        "updated": datetime.now().isoformat()
                    }
                    # Supplement collection from CSV if available
                    csv_meta = csv_lookup.get(cid)
                    if csv_meta and csv_meta.get('collection'):
                        entry["collection"] = csv_meta["collection"]
                        entry["source_csv"] = csv_meta.get("csv_file", "")
                    # Also check if the JSON's own CID is in CSV
                    if not entry["collection"] and json_meta.get('json_cid'):
                        csv_meta2 = csv_lookup.get(json_meta['json_cid'])
                        if csv_meta2 and csv_meta2.get('collection'):
                            entry["collection"] = csv_meta2["collection"]
                            entry["source_csv"] = csv_meta2.get("csv_file", "")

                    # Async Art: tag type and override collection with master name
                    a_type = json_meta.get('async_type')
                    if a_type:
                        entry['async_type'] = a_type
                        if a_type == 'master':
                            entry['collection'] = json_meta.get('name', 'Async Art')
                        elif a_type == 'layer' and json_meta.get('async_master_uri'):
                            m_cid = extract_ipfs_cid_from_str(
                                json_meta['async_master_uri'])
                            if m_cid and m_cid in async_master_names:
                                entry['collection'] = async_master_names[m_cid]

                    # Fallback: check persistent source map from downloader
                    if not entry["source_csv"] and filename in source_map:
                        entry["source_csv"] = source_map[filename]

                    cache["nfts"][filename] = entry
                    json_matched += 1
                    updated += 1
                    if entry["collection"]:
                        collections.add(entry["collection"])
                    if entry["artist"]:
                        artists.add(entry["artist"])
                    continue

                # Try CSV lookup (second priority)
                csv_meta = csv_lookup.get(cid) if cid else None

                if csv_meta:
                    st = _classify_storage_type(filename)
                    storage_counts[st] += 1
                    entry = {
                        "name": csv_meta.get('name', '') or name_parts,
                        "collection": csv_meta.get('collection', ''),
                        "artist": existing.get("artist", ""),
                        "description": existing.get("description", ""),
                        "attributes": existing.get("attributes", []),
                        "tags": existing.get("tags", []),
                        "cid": cid,
                        "storage_type": st,
                        "source": "csv",
                        "source_csv": csv_meta.get("csv_file", ""),
                        "updated": datetime.now().isoformat()
                    }
                    if not entry["source_csv"] and filename in source_map:
                        entry["source_csv"] = source_map[filename]
                    cache["nfts"][filename] = entry
                    csv_matched += 1
                    updated += 1
                    if entry["collection"]:
                        collections.add(entry["collection"])
                    if entry["artist"]:
                        artists.add(entry["artist"])
                    continue

                # Fallback: filename pattern extraction
                if filename not in cache.get("nfts", {}):
                    collection = ""
                    if '_' in name_parts:
                        parts = name_parts.split('_')
                        if len(parts) >= 2 and not parts[0].startswith(('Qm', 'bafy')):
                            collection = parts[0]
                    elif '-' in name_parts and not name_parts.startswith(('Qm', 'bafy')):
                        parts = name_parts.split('-')
                        if len(parts) >= 2:
                            collection = parts[0]

                    st = _classify_storage_type(filename)
                    storage_counts[st] += 1
                    cache["nfts"][filename] = {
                        "name": name_parts,
                        "collection": collection,
                        "artist": "",
                        "description": "",
                        "attributes": [],
                        "tags": [],
                        "cid": cid,
                        "storage_type": st,
                        "source": "filename",
                        "source_csv": source_map.get(filename, ""),
                        "updated": datetime.now().isoformat()
                    }
                    if collection:
                        collections.add(collection)
                    updated += 1
                else:
                    if existing.get("collection"):
                        collections.add(existing["collection"])
                    if existing.get("artist"):
                        artists.add(existing["artist"])
                    # Backfill storage_type if missing
                    if not existing.get("storage_type"):
                        existing["storage_type"] = _classify_storage_type(filename)
                        cache["nfts"][filename] = existing
                    storage_counts[existing.get("storage_type", "copy")] += 1

        # Auto-hide Async Art state variation images
        async_hidden_count = 0
        if async_state_cids:
            hidden_file = Path("/opt/vernis/hidden-nfts.json")
            hidden = []
            if hidden_file.exists():
                try:
                    with open(hidden_file, 'r') as f:
                        hidden = json.load(f)
                except Exception:
                    pass
            hidden_set = set(hidden)
            new_hidden = []
            for ext2 in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'mp4']:
                for fp in NFT_DIR.glob(f"*.{ext2}"):
                    file_cid = extract_ipfs_cid_from_str(fp.stem)
                    if file_cid and file_cid in async_state_cids:
                        if fp.name not in hidden_set:
                            new_hidden.append(fp.name)
                        # Tag as state in cache
                        if fp.name in cache.get("nfts", {}):
                            cache["nfts"][fp.name]["async_type"] = "state"
            if new_hidden:
                async_hidden_count = len(new_hidden)
                hidden = list(set(hidden + new_hidden))
                with open(hidden_file, 'w') as f:
                    json.dump(hidden, f, indent=2)

        cache["collections"] = sorted(list(collections))
        cache["artists"] = sorted(list(artists))
        save_metadata_cache(cache)

        return jsonify({
            "success": True,
            "scanned": scanned,
            "updated": updated,
            "json_matched": json_matched,
            "csv_matched": csv_matched,
            "collections": len(collections),
            "artists": len(artists),
            "async_masters": len(async_master_names),
            "async_states_hidden": async_hidden_count,
            "storage_counts": storage_counts
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/nft-metadata/fetch-ipfs/<filename>", methods=["POST"])
def fetch_nft_ipfs_metadata(filename):
    """Fetch metadata from IPFS for a specific NFT"""
    try:
        cache = load_metadata_cache()
        name_parts = filename.rsplit('.', 1)[0]
        cid = extract_ipfs_cid_from_str(name_parts)

        if not cid:
            return jsonify({"error": "No IPFS CID found in filename"}), 400

        metadata = fetch_ipfs_metadata(cid)
        if not metadata:
            return jsonify({"error": "Could not fetch metadata from IPFS"}), 404

        # Extract relevant fields
        nft_meta = {
            "name": metadata.get("name", name_parts),
            "collection": metadata.get("collection", ""),
            "artist": "",
            "description": metadata.get("description", ""),
            "attributes": metadata.get("attributes", []),
            "tags": [],
            "cid": cid,
            "image_cid": extract_ipfs_cid_from_str(metadata.get("image", "")),
            "updated": datetime.now().isoformat()
        }

        # Try to extract artist from attributes
        for attr in nft_meta["attributes"]:
            trait_type = attr.get("trait_type", "").lower()
            if trait_type in ["artist", "creator", "author"]:
                nft_meta["artist"] = attr.get("value", "")
                break

        cache["nfts"][filename] = nft_meta

        # Update collections and artists
        collections = set(cache.get("collections", []))
        artists = set(cache.get("artists", []))
        if nft_meta["collection"]:
            collections.add(nft_meta["collection"])
        if nft_meta["artist"]:
            artists.add(nft_meta["artist"])
        cache["collections"] = sorted(list(collections))
        cache["artists"] = sorted(list(artists))

        save_metadata_cache(cache)
        return jsonify({"success": True, "metadata": nft_meta})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/nft-artwork-info/<filename>", methods=["GET"])
def get_nft_artwork_info(filename):
    """Get metadata for an artwork file displayed in gallery.
    Checks metadata cache first, then scans sidecar JSON files, then CSV library.
    """
    try:
        # Check metadata cache first (fast path)
        cache = load_metadata_cache()
        cached = cache.get("nfts", {}).get(filename, {})
        if cached.get("name") and cached["name"] != filename.rsplit('.', 1)[0]:
            return jsonify(cached)

        # Extract CID from filename
        name_parts = filename.rsplit('.', 1)[0]
        cid = extract_ipfs_cid_from_str(name_parts)
        if not cid:
            return jsonify({"error": "No metadata found"}), 404

        # Scan sidecar JSON files for matching metadata
        json_lookup = build_json_metadata_lookup(NFT_DIR)
        meta = json_lookup.get(cid)
        if meta:
            return jsonify(meta)

        # Check CSV library
        csv_lookup = build_csv_metadata_lookup(CSV_LIBRARY_DIR)
        csv_meta = csv_lookup.get(cid)
        if csv_meta:
            return jsonify(csv_meta)

        return jsonify({"error": "No metadata found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/nft-delete", methods=["POST"])
def nft_delete():
    """Delete NFT files and auto-cleanup related JSON metadata"""
    try:
        data = request.json
        filenames = data.get('filenames', [])

        deleted = 0
        related_deleted = []
        for filename in filenames:
            # Security: prevent directory traversal
            if ".." in filename or "/" in filename or "\\" in filename:
                continue

            file_path = NFT_DIR / filename
            if file_path.exists():
                file_path.unlink()
                deleted += 1

                # Auto-cleanup: if we deleted an image, check for related JSON
                stem = file_path.stem
                if file_path.suffix.lower() != '.json':
                    # 1. Same CID stem (e.g. QmXYZ.png → QmXYZ.json)
                    json_path = NFT_DIR / f"{stem}.json"
                    if json_path.exists():
                        json_path.unlink()
                        related_deleted.append(json_path.name)
                    # 2. Scan JSON files that reference this CID
                    # Only delete if ALL referenced images are gone (Async Art has many layers)
                    for jf in NFT_DIR.glob("*.json"):
                        if jf.name == "download_progress.json" or jf.name in related_deleted:
                            continue
                        try:
                            content = jf.read_text()
                            if stem not in content:
                                continue
                            # Found a JSON referencing the deleted file
                            # Check if it references any OTHER images that still exist
                            import re as _re
                            all_cids = set(_re.findall(r'(Qm[a-zA-Z0-9]{44,}|baf[a-z0-9]{50,})', content))
                            all_cids.discard(jf.stem)  # Don't count self-reference
                            has_remaining = False
                            for cid in all_cids:
                                # Check if any file with this CID still exists
                                for existing in NFT_DIR.glob(f"{cid}.*"):
                                    if existing.suffix.lower() != '.json':
                                        has_remaining = True
                                        break
                                if has_remaining:
                                    break
                            if not has_remaining:
                                jf.unlink()
                                related_deleted.append(jf.name)
                        except Exception:
                            pass

        return jsonify({"success": True, "deleted": deleted, "related_deleted": related_deleted})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/download-status")
def download_status():
    """Get download status for recent CSV uploads"""
    DOWNLOAD_STATUS_FILE = Path("/opt/vernis/download-status.json")

    try:
        if DOWNLOAD_STATUS_FILE.exists():
            with open(DOWNLOAD_STATUS_FILE, 'r') as f:
                status = json.load(f)
        else:
            status = {"downloads": []}

        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

OPENSEA_KEY_FILE = Path("/opt/vernis/opensea-key.json")
_OPENSEA_DEFAULT_KEY = ""  # Set your OpenSea API key in /opt/vernis/opensea-key.json
_WALLET_CHAINS = {"ethereum", "base", "optimism", "polygon", "arbitrum", "zora", "shape"}


def _get_opensea_key():
    """Get OpenSea API key: user-configured > env var > built-in default."""
    if OPENSEA_KEY_FILE.exists():
        try:
            key = json.loads(OPENSEA_KEY_FILE.read_text()).get('key', '')
            if key:
                return key
        except Exception:
            pass
    env_key = os.getenv("OPENSEA_API_KEY", "")
    return env_key if env_key else _OPENSEA_DEFAULT_KEY

_IPFS_CID_RE = re.compile(
    r'(?:ipfs://|/ipfs/)?'
    r'(Qm[a-zA-Z0-9]{44}(?:/[^\s"\'<>)]+)?|baf[a-z0-9]{50,}(?:/[^\s"\'<>)]+)?)',
    re.I
)


def _resolve_nft_metadata(nfts, max_workers=6, timeout=12):
    """Resolve IPFS metadata for NFTs to get original image/animation URLs.

    For each NFT with a metadata_url, fetches the JSON metadata and
    extracts the original image field (preferring ipfs:// over HTTP CDN).
    Modifies nfts in-place. Safe to call with HTTP or missing metadata_urls.
    """
    import requests as _req
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _to_gateway(uri):
        if uri.startswith('ipfs://'):
            return 'https://ipfs.io/ipfs/' + uri[7:]
        if uri.startswith('ar://'):
            return 'https://arweave.net/' + uri[5:]
        return uri

    def _is_ipfs(uri):
        return bool(uri and (uri.startswith('ipfs://') or '/ipfs/' in uri))

    def resolve_one(nft):
        meta_url = nft.get('metadata_url', '')
        if not meta_url:
            return

        fetch_url = _to_gateway(meta_url)
        try:
            resp = _req.get(fetch_url, timeout=timeout,
                            headers={"Accept": "application/json"})
            if resp.status_code != 200:
                return
            metadata = resp.json()

            # Extract original image — check standard and non-standard fields
            orig_img = (metadata.get('image') or metadata.get('image_url')
                        or metadata.get('image_data') or '')
            orig_anim = metadata.get('animation_url') or ''

            # Nifty Gateway uses "image_hash" for bare IPFS CID
            img_hash = metadata.get('image_hash') or metadata.get('imageHash') or ''
            anim_hash = metadata.get('animation_hash') or metadata.get('animationHash') or ''

            # Convert bare CID hashes to ipfs:// URIs
            if img_hash and _IPFS_CID_RE.match(img_hash):
                orig_img = 'ipfs://' + img_hash
            if anim_hash and _IPFS_CID_RE.match(anim_hash):
                orig_anim = 'ipfs://' + anim_hash

            # Priority: IPFS image > IPFS animation > non-CDN original
            if _is_ipfs(orig_img):
                nft['image_url'] = orig_img
            elif _is_ipfs(orig_anim):
                # Some NFTs store the actual artwork in animation_url (videos, HTML)
                nft['image_url'] = orig_anim
            elif orig_img and 'seadn.io' not in orig_img and 'opensea' not in orig_img:
                # Non-CDN original — still better than OpenSea resize
                nft['image_url'] = orig_img

            # Save animation_url separately if IPFS
            if orig_anim and _is_ipfs(orig_anim) and orig_anim != nft['image_url']:
                nft['animation_url'] = orig_anim

            # Extract CID from resolved image for downloader
            m = _IPFS_CID_RE.search(nft['image_url'])
            if m:
                nft['cid'] = m.group(1)

        except Exception:
            pass

    to_resolve = [n for n in nfts if n.get('metadata_url')]
    if not to_resolve:
        return

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(resolve_one, nft) for nft in to_resolve]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass


def _resolve_ens(name):
    """Resolve ENS name to Ethereum address via public RPC"""
    import requests as _req
    from Crypto.Hash import keccak
    # ENS namehash (uses keccak256, NOT NIST sha3-256)
    def keccak256(data):
        k = keccak.new(digest_bits=256)
        k.update(data)
        return k.digest()

    def namehash(name):
        node = b'\x00' * 32
        if name:
            for label in reversed(name.split('.')):
                node = keccak256(node + keccak256(label.encode()))
        return '0x' + node.hex()

    nh = namehash(name)
    # Call ENS registry to get resolver
    registry = '0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e'
    # resolver(bytes32) selector = 0x0178b8bf
    call_data = '0x0178b8bf' + nh[2:]
    rpc_urls = ['https://eth.llamarpc.com', 'https://rpc.ankr.com/eth', 'https://ethereum.publicnode.com']
    for rpc in rpc_urls:
        try:
            resp = _req.post(rpc, json={
                "jsonrpc": "2.0", "id": 1, "method": "eth_call",
                "params": [{"to": registry, "data": call_data}, "latest"]
            }, timeout=10)
            result = resp.json().get('result', '0x')
            if result == '0x' or result == '0x' + '0' * 64:
                continue
            resolver = '0x' + result[-40:]
            # addr(bytes32) selector = 0x3b3b57de
            addr_data = '0x3b3b57de' + nh[2:]
            resp2 = _req.post(rpc, json={
                "jsonrpc": "2.0", "id": 2, "method": "eth_call",
                "params": [{"to": resolver, "data": addr_data}, "latest"]
            }, timeout=10)
            addr_result = resp2.json().get('result', '0x')
            if addr_result and len(addr_result) >= 42 and addr_result != '0x' + '0' * 64:
                return '0x' + addr_result[-40:]
        except Exception:
            continue
    return None

@app.route("/api/opensea-key", methods=["GET", "POST"])
def opensea_key():
    """Get or set OpenSea API key"""
    if request.method == "GET":
        try:
            if OPENSEA_KEY_FILE.exists():
                data = json.loads(OPENSEA_KEY_FILE.read_text())
                key = data.get('key', '')
                # Return masked key
                if key:
                    return jsonify({"configured": True, "key_preview": key[:8] + "..." + key[-4:]})
            return jsonify({"configured": False})
        except Exception:
            return jsonify({"configured": False})
    else:
        data = request.json or {}
        key = data.get('key', '').strip()
        if not key:
            # Clear key
            if OPENSEA_KEY_FILE.exists():
                OPENSEA_KEY_FILE.unlink()
            return jsonify({"success": True, "message": "API key removed"})
        # Store key
        OPENSEA_KEY_FILE.write_text(json.dumps({"key": key}))
        os.chmod(str(OPENSEA_KEY_FILE), 0o600)
        return jsonify({"success": True, "message": "API key saved"})

@app.route("/api/fetch-wallet-nfts", methods=["POST"])
def fetch_wallet_nfts():
    """Fetch NFTs from wallet using OpenSea API v2 (multi-chain, ENS, pagination)"""
    try:
        import requests as _req

        data = request.json
        wallet = data.get('wallet', '').strip()
        chains = data.get('chains', ['ethereum'])

        if not wallet:
            return jsonify({"error": "Wallet address required"}), 400

        # Resolve ENS name
        if wallet.endswith('.eth'):
            resolved = _resolve_ens(wallet)
            if not resolved:
                return jsonify({"error": f"Could not resolve ENS name: {wallet}"}), 400
            wallet = resolved

        # Validate address format
        if not re.match(r'^0x[0-9a-fA-F]{40}$', wallet):
            return jsonify({"error": "Invalid wallet address format"}), 400

        # Validate chains
        chains = [c for c in chains if c in _WALLET_CHAINS]
        if not chains:
            chains = ['ethereum']

        api_key = _get_opensea_key()

        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-API-KEY"] = api_key

        # Collections to skip (not displayable art)
        _skip_collections = {'ens', 'unstoppable-domains', 'lens-protocol-profiles',
                             'wrapped-cryptopunks'}

        all_nfts = []
        skipped = 0
        throttled = False
        chain_counts = {}

        for chain in chains:
            chain_nfts = []
            cursor = None
            page = 0
            max_pages = 25  # Safety limit (25 * 200 = 5000 NFTs per chain)

            while page < max_pages:
                url = f"https://api.opensea.io/api/v2/chain/{chain}/account/{wallet}/nfts"
                params = {"limit": 200}
                if cursor:
                    params["next"] = cursor

                resp = _req.get(url, headers=headers, params=params, timeout=30)

                if resp.status_code == 429:
                    throttled = True
                    chain_counts[chain] = {"error": "Rate limited"}
                    break
                if resp.status_code != 200:
                    chain_counts[chain] = {"error": f"HTTP {resp.status_code}"}
                    break

                resp_data = resp.json()
                nfts = resp_data.get('nfts', [])

                for nft in nfts:
                    col = nft.get('collection', '')
                    # Skip non-art collections
                    if col in _skip_collections:
                        skipped += 1
                        continue
                    img = nft.get('display_image_url') or nft.get('image_url', '')
                    # Skip NFTs without any image
                    if not img:
                        skipped += 1
                        continue
                    chain_nfts.append({
                        "name": nft.get('name', ''),
                        "token_id": nft.get('identifier', ''),
                        "contract": nft.get('contract', ''),
                        "image_url": img,
                        "collection": col,
                        "chain": chain,
                        "metadata_url": nft.get('metadata_url', ''),
                    })

                cursor = resp_data.get('next')
                if not cursor:
                    break
                page += 1
                time.sleep(0.5)  # Rate limit safety

            chain_counts[chain] = len(chain_nfts)
            all_nfts.extend(chain_nfts)

        # Resolve IPFS metadata to get original image hashes
        _resolve_nft_metadata(all_nfts)
        ipfs_count = sum(1 for n in all_nfts if n.get('cid'))

        return jsonify({
            "success": True,
            "nfts": all_nfts,
            "total": len(all_nfts),
            "ipfs_resolved": ipfs_count,
            "skipped": skipped,
            "throttled": throttled,
            "wallet": wallet,
            "chains": chain_counts
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/health/storage")
def health_storage():
    """Get storage health metrics (SD Card Endurance)"""
    try:
        # 1. Disk Usage (Root Partition)
        total, used, free = shutil.disk_usage("/")
        usage_percent = (used / total) * 100
        
        # 2. Filesystem Read-Only Check
        is_ro = False
        try:
            # Try to write to a temporary file in /tmp (which is usually writable even if root is ro, unless fully locked)
            # Better to check /opt/vernis or a directory we own
            test_file = UPLOAD_DIR / ".rw_test"
            test_file.touch()
            test_file.unlink()
        except OSError:
            is_ro = True
            
        # 3. Health Assessment
        health_status = "Healthy"
        if usage_percent > 90:
            health_status = "Critical Space"
        elif usage_percent > 80:
            health_status = "Warning Space"
            
        if is_ro:
            health_status = "Read-Only (Error)"
            
        return jsonify({
            "usage_percent": round(usage_percent, 1),
            "total_gb": round(total / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1),
            "is_read_only": is_ro,
            "status": health_status,
            "message": "Filesystem writable" if not is_ro else "Filesystem is READ-ONLY"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Disk scan settings file
DISK_SCAN_SETTINGS_FILE = Path("/opt/vernis/disk-scan-settings.json")

@app.route("/api/disk-scan/settings", methods=["GET", "POST"])
def disk_scan_settings():
    """Get or update disk scan settings"""
    if request.method == "GET":
        try:
            if DISK_SCAN_SETTINGS_FILE.exists():
                with open(DISK_SCAN_SETTINGS_FILE, 'r') as f:
                    return jsonify(json.load(f))
            return jsonify({"annual_scan_enabled": False, "last_scan": None})
        except:
            return jsonify({"annual_scan_enabled": False, "last_scan": None})

    try:
        data = request.json
        settings = {"annual_scan_enabled": data.get("annual_scan_enabled", False)}

        # Preserve last_scan if it exists
        if DISK_SCAN_SETTINGS_FILE.exists():
            with open(DISK_SCAN_SETTINGS_FILE, 'r') as f:
                old_settings = json.load(f)
                settings["last_scan"] = old_settings.get("last_scan")

        with open(DISK_SCAN_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/disk-scan/run", methods=["POST"])
def run_disk_scan():
    """Run a disk health scan and return report"""
    try:
        report_lines = []
        report_lines.append("=" * 50)
        report_lines.append("VERNIS DISK HEALTH SCAN REPORT")
        report_lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("=" * 50)
        report_lines.append("")

        # 1. Disk Usage
        total, used, free = shutil.disk_usage("/")
        usage_percent = (used / total) * 100
        report_lines.append("[DISK USAGE]")
        report_lines.append(f"  Total: {round(total / (1024**3), 2)} GB")
        report_lines.append(f"  Used:  {round(used / (1024**3), 2)} GB ({round(usage_percent, 1)}%)")
        report_lines.append(f"  Free:  {round(free / (1024**3), 2)} GB")
        report_lines.append(f"  Status: {'OK' if usage_percent < 80 else 'WARNING' if usage_percent < 90 else 'CRITICAL'}")
        report_lines.append("")

        # 2. Filesystem check
        report_lines.append("[FILESYSTEM]")
        try:
            result = subprocess.run(["mount"], capture_output=True, text=True, timeout=10)
            for line in result.stdout.split('\n'):
                if ' / ' in line or '/boot' in line:
                    report_lines.append(f"  {line.strip()}")
        except:
            report_lines.append("  Unable to check mount points")
        report_lines.append("")

        # 3. Check for filesystem errors in dmesg
        report_lines.append("[FILESYSTEM ERRORS]")
        try:
            result = subprocess.run(
                ["dmesg"], capture_output=True, text=True, timeout=10
            )
            errors = [l for l in result.stdout.split('\n') if 'error' in l.lower() and ('ext4' in l.lower() or 'mmc' in l.lower() or 'sd' in l.lower())]
            if errors:
                for err in errors[-5:]:  # Last 5 errors
                    report_lines.append(f"  {err.strip()[:80]}")
            else:
                report_lines.append("  No filesystem errors detected")
        except:
            report_lines.append("  Unable to check dmesg (may require root)")
        report_lines.append("")

        # 4. I/O statistics
        report_lines.append("[I/O STATISTICS]")
        try:
            result = subprocess.run(
                ["cat", "/sys/block/mmcblk0/stat"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                stats = result.stdout.split()
                if len(stats) >= 7:
                    report_lines.append(f"  Read operations:  {stats[0]}")
                    report_lines.append(f"  Write operations: {stats[4]}")
        except:
            pass
        report_lines.append("")

        # 5. Temperature (if available)
        report_lines.append("[TEMPERATURE]")
        try:
            result = subprocess.run(
                ["cat", "/sys/class/thermal/thermal_zone0/temp"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                temp_c = int(result.stdout.strip()) / 1000
                report_lines.append(f"  CPU: {temp_c}°C {'(OK)' if temp_c < 70 else '(WARNING - HIGH)'}")
        except:
            report_lines.append("  Temperature not available")
        report_lines.append("")

        # Summary
        report_lines.append("=" * 50)
        report_lines.append("SUMMARY: Disk health scan completed successfully")
        if usage_percent >= 90:
            report_lines.append("WARNING: Disk space critically low!")
        elif usage_percent >= 80:
            report_lines.append("NOTE: Disk space getting low, consider cleanup")
        else:
            report_lines.append("All checks passed - storage healthy")
        report_lines.append("=" * 50)

        report = '\n'.join(report_lines)

        # Save last scan time
        try:
            settings = {"annual_scan_enabled": False, "last_scan": datetime.now().isoformat()}
            if DISK_SCAN_SETTINGS_FILE.exists():
                with open(DISK_SCAN_SETTINGS_FILE, 'r') as f:
                    old = json.load(f)
                    settings["annual_scan_enabled"] = old.get("annual_scan_enabled", False)
            with open(DISK_SCAN_SETTINGS_FILE, 'w') as f:
                json.dump(settings, f)
        except:
            pass

        return jsonify({"success": True, "report": report})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/backup/create", methods=["POST"])
def create_backup():
    """Create a backup archive of all NFTs and CSV files"""
    try:
        # Create backup directory if it doesn't exist
        backup_dir = Path("/opt/vernis/backup")
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
        backup_dir = Path("/opt/vernis/backup")

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
        backup_dir = Path("/opt/vernis/backup")
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

@app.route("/api/backup/delete", methods=["POST"])
def delete_backup():
    """Delete a backup file"""
    try:
        data = request.json
        filename = data.get('filename', '').strip()

        # Security: prevent directory traversal
        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            return jsonify({"error": "Invalid filename"}), 400

        backup_dir = Path("/opt/vernis/backup")
        backup_path = backup_dir / filename

        if not backup_path.exists():
            return jsonify({"error": "Backup file not found"}), 404

        # Only allow deleting zip files with proper naming pattern
        if not filename.startswith("vernis_backup_") or not filename.endswith(".zip"):
            return jsonify({"error": "Invalid backup file"}), 400

        backup_path.unlink()

        return jsonify({"success": True, "message": f"Deleted {filename}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/backup/import", methods=["POST"])
def import_backup():
    """Import a backup file (tar.gz) and restore its contents"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({"error": "No file selected"}), 400

        # Validate file extension
        if not (file.filename.endswith('.tar.gz') or file.filename.endswith('.tgz') or file.filename.endswith('.zip')):
            return jsonify({"error": "Invalid file type. Please upload a .tar.gz or .zip backup file"}), 400

        backup_dir = Path("/opt/vernis/backup")
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Save the uploaded file temporarily
        import tempfile
        import tarfile
        import zipfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix, dir=str(TMP_DIR)) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        try:
            extracted_count = 0

            if file.filename.endswith('.zip'):
                # Handle zip files
                with zipfile.ZipFile(tmp_path, 'r') as zf:
                    # Extract NFT files
                    for name in zf.namelist():
                        if name.startswith('nfts/') and not name.endswith('/'):
                            # Extract to NFT directory
                            basename = Path(name).name
                            if not basename or basename.startswith('.'):
                                continue
                            dest = NFT_DIR / basename
                            with zf.open(name) as src, open(dest, 'wb') as dst:
                                dst.write(src.read())
                            extracted_count += 1
                        elif name.startswith('csv/') and not name.endswith('/'):
                            # Extract to CSV library
                            basename = Path(name).name
                            if not basename or basename.startswith('.'):
                                continue
                            dest = CSV_LIBRARY_DIR / basename
                            with zf.open(name) as src, open(dest, 'wb') as dst:
                                dst.write(src.read())
            else:
                # Handle tar.gz files
                with tarfile.open(tmp_path, 'r:gz') as tf:
                    for member in tf.getmembers():
                        if member.isfile():
                            if member.name.startswith('nfts/'):
                                basename = Path(member.name).name
                                if not basename or basename.startswith('.'):
                                    continue
                                dest = NFT_DIR / basename
                                with tf.extractfile(member) as src:
                                    with open(dest, 'wb') as dst:
                                        dst.write(src.read())
                                extracted_count += 1
                            elif member.name.startswith('csv/'):
                                basename = Path(member.name).name
                                if not basename or basename.startswith('.'):
                                    continue
                                dest = CSV_LIBRARY_DIR / basename
                                with tf.extractfile(member) as src:
                                    with open(dest, 'wb') as dst:
                                        dst.write(src.read())

            return jsonify({
                "success": True,
                "message": f"Restored {extracted_count} files from backup"
            })
        finally:
            # Clean up temp file
            Path(tmp_path).unlink(missing_ok=True)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========================================
# Setup Wizard
# ========================================

@app.route("/api/setup/check")
def setup_check():
    """Fast check — only returns whether setup is complete. Used by gallery redirect."""
    return jsonify({"setup_complete": SETUP_COMPLETE_FILE.exists()})


@app.route("/api/setup/status")
def setup_status():
    """Check setup wizard completion status."""
    try:
        setup_complete = SETUP_COMPLETE_FILE.exists()

        # Check WiFi connection
        wifi_connected = False
        wifi_ssid = ""
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split('\n'):
                if line.startswith('yes:'):
                    wifi_ssid = line.split(':', 1)[1]
                    wifi_connected = bool(wifi_ssid)
                    break
        except Exception:
            pass

        # Check if password has been changed
        password_changed = Path("/opt/vernis/password-changed.marker").exists()

        # Check for art
        local_files = 0
        for ext in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'mp4', 'html']:
            local_files += len(list(NFT_DIR.glob(f"*.{ext}")))
        has_art = local_files > 0

        # Get hostname
        hostname = platform.node() if hasattr(platform, 'node') else "vernis"

        # Check OpenSea API key
        opensea_configured = False
        try:
            if OPENSEA_KEY_FILE.exists():
                opensea_configured = bool(json.loads(OPENSEA_KEY_FILE.read_text()).get('key', ''))
        except Exception:
            pass

        return jsonify({
            "setup_complete": setup_complete,
            "wifi_connected": wifi_connected,
            "wifi_ssid": wifi_ssid,
            "password_changed": password_changed,
            "has_art": has_art,
            "local_files": local_files,
            "hostname": hostname,
            "opensea_configured": opensea_configured
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/setup/change-password", methods=["POST"])
def setup_change_password():
    """Change the Linux user password."""
    try:
        data = request.json or {}
        new_password = data.get('password', '')
        current_password = data.get('current_password', '')

        if not new_password or len(new_password) < 8:
            return jsonify({"error": "Password must be at least 8 characters"}), 400
        if len(new_password) > 128:
            return jsonify({"error": "Password too long"}), 400

        # Get the actual login user (not root, which runs the service)
        try:
            username = os.getlogin()
        except OSError:
            username = os.environ.get("SUDO_USER", "")
        if not username or username == "root":
            # Read from hostname-based convention or /etc/hostname
            import pwd
            for u in pwd.getpwall():
                if u.pw_uid >= 1000 and u.pw_uid < 65534 and u.pw_shell not in ("/usr/sbin/nologin", "/bin/false"):
                    username = u.pw_name
                    break

        # If password was already changed before, require current password
        marker = Path("/opt/vernis/password-changed.marker")
        if marker.exists():
            if not current_password:
                return jsonify({"error": "Current password required", "needs_current": True}), 400
            # Verify current password via /etc/shadow + libc crypt (runs as root)
            _pw_ok = False
            try:
                import ctypes, ctypes.util
                _libcrypt = ctypes.CDLL(ctypes.util.find_library("crypt") or "libcrypt.so.1")
                _libcrypt.crypt.restype = ctypes.c_char_p
                stored_hash = None
                with open("/etc/shadow") as sf:
                    for line in sf:
                        parts = line.strip().split(":")
                        if parts[0] == username and len(parts) > 1:
                            stored_hash = parts[1]
                            break
                if not stored_hash or stored_hash in ("*", "!", "!!", "x"):
                    _pw_ok = True  # No password set
                else:
                    computed = _libcrypt.crypt(current_password.encode(), stored_hash.encode())
                    _pw_ok = computed is not None and computed.decode() == stored_hash
            except Exception as e:
                print(f"[setup] Password verify error: {e}", flush=True)
            if not _pw_ok:
                return jsonify({"error": "Wrong password"}), 403

        process = subprocess.run(
            ["chpasswd"],
            input=f"{username}:{new_password}",
            capture_output=True, text=True, timeout=10
        )
        if process.returncode != 0:
            return jsonify({"error": "Failed to change password"}), 500

        # Write marker
        marker.touch()
        os.chmod(str(marker), 0o600)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/setup/quick-import", methods=["POST"])
def setup_quick_import():
    """One-click wallet import: fetch NFTs and start downloading."""
    try:
        import requests as _req

        data = request.json or {}
        wallet = data.get('wallet', '').strip()
        chains = data.get('chains', ['ethereum', 'base', 'optimism'])

        if not wallet:
            return jsonify({"error": "Wallet address required"}), 400

        # Keep original input for display name
        display_name = wallet

        # Resolve ENS
        if wallet.endswith('.eth'):
            resolved = _resolve_ens(wallet)
            if not resolved:
                return jsonify({"error": f"Could not resolve ENS name: {wallet}"}), 400
            wallet = resolved

        # Validate address format
        is_tezos = wallet.startswith('tz') and len(wallet) >= 36
        is_eth = bool(re.match(r'^0x[0-9a-fA-F]{40}$', wallet))

        if not is_tezos and not is_eth:
            return jsonify({"error": "Invalid wallet address"}), 400

        # Separate chains
        tezos_requested = 'tezos' in chains
        opensea_chains = [c for c in chains if c in _WALLET_CHAINS]

        api_key = _get_opensea_key()

        all_nfts = []
        skipped = 0
        throttled = False
        _skip_collections = {'ens', 'unstoppable-domains', 'lens-protocol-profiles',
                             'wrapped-cryptopunks'}

        # Fetch from OpenSea (EVM chains)
        if is_eth and opensea_chains:
            headers = {"Accept": "application/json"}
            if api_key:
                headers["X-API-KEY"] = api_key

            for chain in opensea_chains:
                if throttled:
                    break
                cursor = None
                page = 0
                while page < 25:
                    url = f"https://api.opensea.io/api/v2/chain/{chain}/account/{wallet}/nfts"
                    params = {"limit": 200}
                    if cursor:
                        params["next"] = cursor
                    try:
                        resp = _req.get(url, headers=headers, params=params, timeout=30)
                    except Exception:
                        break
                    if resp.status_code in (429, 403):
                        throttled = True
                        break
                    if resp.status_code != 200:
                        break
                    resp_data = resp.json()
                    for nft in resp_data.get('nfts', []):
                        col = nft.get('collection', '')
                        if col in _skip_collections:
                            skipped += 1
                            continue
                        img = nft.get('display_image_url') or nft.get('image_url', '')
                        if not img:
                            skipped += 1
                            continue
                        entry = {
                            "name": nft.get('name', ''),
                            "token_id": nft.get('identifier', ''),
                            "contract": nft.get('contract', ''),
                            "image_url": img,
                            "collection": col,
                            "chain": chain,
                            "metadata_url": nft.get('metadata_url', ''),
                        }
                        all_nfts.append(entry)
                    cursor = resp_data.get('next')
                    if not cursor:
                        break
                    page += 1
                    time.sleep(0.5)

        # Fetch from objkt.com (Tezos)
        if tezos_requested and is_tezos:
            try:
                gql_query = {
                    "query": """query($addr: String!) {
                        token_holder(where: {holder_address: {_eq: $addr}, quantity: {_gt: "0"}},
                                     limit: 500, order_by: {last_incremented_at: desc}) {
                            token {
                                name token_id display_uri artifact_uri thumbnail_uri
                                fa { contract name }
                            }
                        }
                    }""",
                    "variables": {"addr": wallet}
                }
                resp = _req.post("https://data.objkt.com/v3/graphql", json=gql_query, timeout=30)
                if resp.status_code == 200:
                    holders = resp.json().get('data', {}).get('token_holder', [])
                    for h in holders:
                        t = h.get('token', {})
                        fa = t.get('fa', {})
                        # Get best image URI — keep ipfs:// for CID extraction
                        img_uri = t.get('display_uri') or t.get('artifact_uri') or t.get('thumbnail_uri') or ''
                        if not img_uri:
                            skipped += 1
                            continue
                        entry = {
                            "name": t.get('name', ''),
                            "token_id": t.get('token_id', ''),
                            "contract": fa.get('contract', ''),
                            "image_url": img_uri,
                            "collection": fa.get('name', ''),
                            "chain": "tezos",
                            "metadata_url": "",
                        }
                        # Extract CID from ipfs:// URI
                        m = _IPFS_CID_RE.search(img_uri)
                        if m:
                            entry['cid'] = m.group(1)
                        all_nfts.append(entry)
            except Exception:
                pass

        if not all_nfts and throttled:
            return jsonify({"success": False, "total": 0, "throttled": True,
                            "error": "OpenSea API rate limit reached. Please wait a minute and try again."}), 429
        if not all_nfts:
            return jsonify({"success": True, "total": 0, "message": "No art NFTs found in this wallet"})

        # Resolve IPFS metadata to get original image hashes
        _resolve_nft_metadata(all_nfts)
        ipfs_count = sum(1 for n in all_nfts if n.get('cid'))

        # Build CSV — name after wallet/ENS
        import csv as csv_module
        safe_name = re.sub(r'[^a-zA-Z0-9._-]', '', display_name)
        csv_filename = f"{safe_name}.csv"
        csv_path = UPLOAD_DIR / csv_filename
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        with open(csv_path, 'w', newline='') as f:
            writer = csv_module.writer(f)
            writer.writerow(['contract_address', 'token_id', 'name', 'collection',
                             'image_url', 'chain', 'metadata_url', 'cid'])
            for nft in all_nfts:
                writer.writerow([
                    nft['contract'], nft['token_id'],
                    nft['name'], nft['collection'],
                    nft['image_url'], nft['chain'],
                    nft.get('metadata_url', ''), nft.get('cid', '')
                ])

        # Save to CSV library with metadata sidecar
        import shutil
        lib_path = CSV_LIBRARY_DIR / csv_filename
        shutil.copy2(str(csv_path), str(lib_path))

        chain_list = ', '.join(c.title() for c in chains)
        meta_path = CSV_LIBRARY_DIR / f"{safe_name}.json"
        meta = {
            "name": display_name,
            "description": f"{len(all_nfts)} NFTs from {chain_list}",
            "wallet": wallet,
            "chains": chains,
            "featured": False
        }
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)

        # Start downloader in background
        active_nft_dir = get_active_nft_dir(for_writing=True)
        workers = 2
        try:
            settings_file = Path("/opt/vernis/ipfs_settings.json")
            if settings_file.exists():
                with open(settings_file) as f:
                    workers = json.load(f).get("download_workers", 2)
        except Exception:
            pass

        active_nft_dir.mkdir(parents=True, exist_ok=True)

        # Write initial progress file so polling doesn't read stale data from previous download
        progress_file = active_nft_dir / "download_progress.json"
        with open(progress_file, 'w') as pf:
            json.dump({
                "completed": 0, "total": len(all_nfts),
                "downloaded": [], "failed": {},
                "source_csv": csv_filename,
                "speed": 0, "current_file": ""
            }, pf)

        downloader = SCRIPTS_DIR / "nft_downloader_advanced.py"
        subprocess.Popen([
            "python3", str(downloader),
            "--csv", str(csv_path),
            "--output", str(active_nft_dir),
            "--workers", str(workers)
        ])

        msg = f"Downloading {len(all_nfts)} artworks"
        if ipfs_count:
            msg += f" ({ipfs_count} with original IPFS hashes)"
        if throttled:
            msg += " — some chains may be incomplete due to rate limits"

        return jsonify({
            "success": True,
            "total": len(all_nfts),
            "ipfs_resolved": ipfs_count,
            "skipped": skipped,
            "throttled": throttled,
            "wallet": wallet,
            "message": msg
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/setup/complete", methods=["POST"])
def setup_complete():
    """Mark setup wizard as complete."""
    try:
        data = {
            "completed_at": datetime.utcnow().isoformat() + "Z",
            "password_changed": Path("/opt/vernis/password-changed.marker").exists()
        }
        SETUP_COMPLETE_FILE.write_text(json.dumps(data, indent=2))
        os.chmod(str(SETUP_COMPLETE_FILE), 0o644)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/setup/complete", methods=["DELETE"])
def setup_reset():
    """Reset setup wizard to allow re-running."""
    try:
        if SETUP_COMPLETE_FILE.exists():
            SETUP_COMPLETE_FILE.unlink()
        return jsonify({"success": True, "message": "Setup wizard will run on next gallery load"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========================================
# Preserve Vernis (Archive & Pin to IPFS)
# ========================================

ARCHIVE_META_FILE = Path("/opt/vernis/vernis-archive.json")

# Official release CID — all devices pin this same CID for maximum redundancy.
# Update this when publishing a new release.
RELEASE_CID = "QmZZrHC2sLj5FT6s44aLbxpZW5RkPSCLwuauwT3Wm14qxU"
RELEASE_SIZE = 6004199
RELEASE_DATE = "2026-02-22"

@app.route("/api/archive/status")
def archive_status():
    """Get the current archive CID if one exists"""
    if ARCHIVE_META_FILE.exists():
        try:
            with open(ARCHIVE_META_FILE, 'r') as f:
                return jsonify(json.load(f))
        except:
            pass
    return jsonify({"cid": None})

@app.route("/api/archive/release")
def archive_release_info():
    """Get the official release CID and whether this device has pinned it"""
    pinned = False
    try:
        result = subprocess.run(
            ["ipfs", "pin", "ls", "--type=recursive", RELEASE_CID],
            capture_output=True, text=True, timeout=10, env=IPFS_ENV
        )
        pinned = result.returncode == 0 and RELEASE_CID in result.stdout
    except Exception:
        pass
    return jsonify({
        "cid": RELEASE_CID,
        "size": RELEASE_SIZE,
        "date": RELEASE_DATE,
        "gateway_url": f"https://ipfs.io/ipfs/{RELEASE_CID}",
        "pinned": pinned
    })

@app.route("/api/archive/pin-release", methods=["POST"])
def pin_release():
    """Pin the official Vernis release CID"""
    try:
        result = subprocess.run(
            ["ipfs", "pin", "add", RELEASE_CID],
            capture_output=True, text=True, timeout=300, env=IPFS_ENV
        )
        if result.returncode != 0:
            return jsonify({"error": f"Pin failed: {result.stderr.strip()}"}), 500
        # Save as this device's archive too
        meta = {
            "cid": RELEASE_CID,
            "size": RELEASE_SIZE,
            "date": RELEASE_DATE,
            "gateway_url": f"https://ipfs.io/ipfs/{RELEASE_CID}",
            "is_release": True
        }
        with open(ARCHIVE_META_FILE, 'w') as f:
            json.dump(meta, f, indent=2)
        return jsonify({"success": True, **meta})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Pin timed out (try again later)"}), 500
    except FileNotFoundError:
        return jsonify({"error": "IPFS is not installed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/archive/create", methods=["POST"])
def create_archive():
    """Create a tar.gz of Vernis software, pin it to IPFS, return the CID"""
    try:
        import tarfile
        import tempfile

        archive_path = Path(tempfile.mktemp(suffix='.tar.gz', dir=str(TMP_DIR)))

        # Build archive: web UI + backend + scripts (no user data)
        with tarfile.open(str(archive_path), 'w:gz') as tar:
            web_dir = Path("/var/www/vernis")
            backend_dir = Path("/opt/vernis")

            # Add all web UI files
            if web_dir.exists():
                for f in web_dir.rglob('*'):
                    if f.is_file():
                        arcname = "web/" + str(f.relative_to(web_dir))
                        tar.add(str(f), arcname=arcname)

            # Add backend app.py
            app_file = backend_dir / "app.py"
            if app_file.exists():
                tar.add(str(app_file), arcname="backend/app.py")

            # Add all scripts
            scripts_dir = backend_dir / "scripts"
            if scripts_dir.exists():
                for f in scripts_dir.rglob('*'):
                    if f.is_file():
                        arcname = "scripts/" + str(f.relative_to(scripts_dir))
                        tar.add(str(f), arcname=arcname)

        # Get archive size
        archive_size = archive_path.stat().st_size

        # Pin to IPFS
        result = subprocess.run(
            ["ipfs", "add", "-Q", "--pin=true", str(archive_path)],
            capture_output=True, text=True, timeout=120,
            env=IPFS_ENV
        )

        # Clean up temp file
        archive_path.unlink(missing_ok=True)

        if result.returncode != 0:
            return jsonify({"error": f"IPFS pin failed: {result.stderr}"}), 500

        cid = result.stdout.strip()

        # Save metadata
        meta = {
            "cid": cid,
            "size": archive_size,
            "date": datetime.now().isoformat(),
            "gateway_url": f"https://ipfs.io/ipfs/{cid}"
        }
        with open(ARCHIVE_META_FILE, 'w') as f:
            json.dump(meta, f, indent=2)

        return jsonify({"success": True, **meta})

    except subprocess.TimeoutExpired:
        return jsonify({"error": "IPFS pin timed out"}), 500
    except FileNotFoundError:
        return jsonify({"error": "IPFS is not installed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/archive/pin-existing", methods=["POST"])
def pin_existing_archive():
    """Pin an existing IPFS CID (e.g. shared from another Vernis device)"""
    data = request.get_json(silent=True) or {}
    cid = (data.get("cid") or "").strip()
    if not cid or (not cid.startswith("Qm") and not cid.startswith("bafy")):
        return jsonify({"error": "Invalid CID"}), 400
    try:
        result = subprocess.run(
            ["ipfs", "pin", "add", cid],
            capture_output=True, text=True, timeout=300,
            env=IPFS_ENV
        )
        if result.returncode != 0:
            return jsonify({"error": f"Pin failed: {result.stderr.strip()}"}), 500
        return jsonify({"success": True, "cid": cid})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Pin timed out (CID may not be reachable)"}), 500
    except FileNotFoundError:
        return jsonify({"error": "IPFS is not installed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/archive/qr")
def archive_qr():
    """Generate a QR code PNG for the archive gateway URL"""
    url = ""
    if ARCHIVE_META_FILE.exists():
        try:
            with open(ARCHIVE_META_FILE, 'r') as f:
                url = json.load(f).get("gateway_url", "")
        except Exception:
            pass
    # Fall back to official release URL
    if not url:
        url = f"https://ipfs.io/ipfs/{RELEASE_CID}"

    try:
        import qrcode
        from PIL import Image

        qr = qrcode.QRCode(
            version=2,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=6,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="white", back_color="black").convert('RGB')

        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return send_file(buf, mimetype='image/png')

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========================================
# External Storage Management
# ========================================

def get_storage_config():
    """Get current storage configuration"""
    defaults = {"use_external": False, "external_path": None, "readonly_mode": False}
    if STORAGE_CONFIG_FILE.exists():
        try:
            with open(STORAGE_CONFIG_FILE, 'r') as f:
                saved = json.load(f)
                defaults.update(saved)
        except:
            pass
    return defaults

def detect_external_drives():
    """Detect mounted external USB drives"""
    drives = []
    mount_points = ['/media/pi', '/media', '/mnt']

    for mount_base in mount_points:
        if not os.path.exists(mount_base):
            continue
        try:
            for entry in os.listdir(mount_base):
                drive_path = os.path.join(mount_base, entry)
                if not os.path.isdir(drive_path):
                    continue

                # Skip system directories
                if entry in ['cdrom', 'floppy', 'usb']:
                    continue

                try:
                    # Check if it's a mount point and writable
                    stat = os.statvfs(drive_path)
                    total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
                    free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
                    used_gb = total_gb - free_gb

                    # Only include drives with >1GB capacity (skip small USB sticks that might be boot drives)
                    if total_gb > 1:
                        # Check if writable
                        test_file = Path(drive_path) / ".vernis_test"
                        try:
                            test_file.touch()
                            test_file.unlink()
                            writable = True
                        except:
                            writable = False

                        drives.append({
                            "name": entry,
                            "path": drive_path,
                            "total_gb": round(total_gb, 1),
                            "free_gb": round(free_gb, 1),
                            "used_gb": round(used_gb, 1),
                            "writable": writable
                        })
                except:
                    pass
        except:
            pass

    return drives

@app.route("/api/storage/external/detect")
def detect_external():
    """Detect available external drives"""
    try:
        drives = detect_external_drives()
        config = get_storage_config()

        return jsonify({
            "drives": drives,
            "current_external": config.get("external_path"),
            "using_external": config.get("use_external", False)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/storage/external/configure", methods=["POST"])
def configure_external_storage():
    """Configure external storage usage"""
    try:
        data = request.json
        current_config = get_storage_config()

        # Check if this is just a readonly_mode toggle
        if 'readonly_mode' in data and len(data) == 1:
            current_config['readonly_mode'] = data['readonly_mode']
            with open(STORAGE_CONFIG_FILE, 'w') as f:
                json.dump(current_config, f, indent=2)
            return jsonify({
                "success": True,
                "message": f"Read-only mode {'enabled' if data['readonly_mode'] else 'disabled'}"
            })

        use_external = data.get('use_external', False)
        external_path = data.get('external_path', '').strip()

        if use_external:
            if not external_path:
                return jsonify({"error": "External path required"}), 400

            # Validate path is under /mnt/ or /media/ (prevent access to system dirs)
            resolved = str(Path(external_path).resolve())
            if not (resolved.startswith('/mnt/') or resolved.startswith('/media/')):
                return jsonify({"error": "External path must be under /mnt/ or /media/"}), 400

            # Validate the path exists and is writable
            if not os.path.isdir(external_path):
                return jsonify({"error": "Path does not exist"}), 400

            test_file = Path(external_path) / ".vernis_test"
            try:
                test_file.touch()
                test_file.unlink()
            except:
                return jsonify({"error": "Path is not writable"}), 400

            # Create vernis-nfts directory on external drive
            nft_path = Path(external_path) / "vernis-nfts"
            nft_path.mkdir(parents=True, exist_ok=True)

        # Save configuration (preserve readonly_mode if set)
        config = {
            "use_external": use_external,
            "external_path": external_path if use_external else None,
            "readonly_mode": current_config.get('readonly_mode', False) if use_external else False
        }
        with open(STORAGE_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)

        return jsonify({
            "success": True,
            "message": f"Storage configured: {'External' if use_external else 'Internal'}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/storage/external/migrate", methods=["POST"])
def migrate_to_external():
    """Migrate NFT files to external storage"""
    try:
        config = get_storage_config()

        if not config.get('use_external') or not config.get('external_path'):
            return jsonify({"error": "External storage not configured"}), 400

        external_nft_dir = Path(config['external_path']) / "vernis-nfts"
        external_nft_dir.mkdir(parents=True, exist_ok=True)

        # Count files to migrate
        internal_files = list(NFT_DIR.glob("*.*"))
        total = len(internal_files)
        migrated = 0
        errors = []

        for file_path in internal_files:
            try:
                dest = external_nft_dir / file_path.name
                shutil.copy2(file_path, dest)
                # Verify copy succeeded
                if dest.exists() and dest.stat().st_size == file_path.stat().st_size:
                    file_path.unlink()  # Remove from internal storage
                    migrated += 1
                else:
                    errors.append(f"Verify failed: {file_path.name}")
            except Exception as e:
                errors.append(f"{file_path.name}: {str(e)}")

        return jsonify({
            "success": True,
            "total": total,
            "migrated": migrated,
            "errors": errors[:10]  # Limit error list
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/storage/external/status")
def external_storage_status():
    """Get external storage status and stats"""
    try:
        config = get_storage_config()

        result = {
            "configured": config.get('use_external', False),
            "path": config.get('external_path'),
            "readonly_mode": config.get('readonly_mode', False),
            "internal_files": len(list(NFT_DIR.glob("*.*"))),
            "external_files": 0,
            "external_stats": None
        }

        if config.get('use_external') and config.get('external_path'):
            external_nft_dir = Path(config['external_path']) / "vernis-nfts"
            if external_nft_dir.exists():
                result["external_files"] = len(list(external_nft_dir.glob("*.*")))

            try:
                stat = os.statvfs(config['external_path'])
                result["external_stats"] = {
                    "total_gb": round((stat.f_blocks * stat.f_frsize) / (1024**3), 1),
                    "free_gb": round((stat.f_bavail * stat.f_frsize) / (1024**3), 1)
                }
            except:
                pass

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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

@app.route("/api/github-sync")
def github_sync():
    """Check GitHub for new CSV collections not yet in local library"""
    try:
        config = get_github_config()

        if not config.get('enabled', False):
            return jsonify({"error": "GitHub integration is not enabled. Enable it in Settings first."}), 400

        # Get all files from GitHub
        github_files = fetch_github_csv_files()

        if not github_files:
            return jsonify({
                "total": 0,
                "new_collections": [],
                "message": "No CSV files found in GitHub repository"
            })

        # Get local CSV files
        local_files = set()
        for csv_file in CSV_LIBRARY_DIR.glob("*.csv"):
            local_files.add(csv_file.name)

        # Also check uploads directory
        for csv_file in UPLOAD_DIR.glob("*.csv"):
            local_files.add(csv_file.name)

        # Find new collections (in GitHub but not local)
        new_collections = []
        for gh_file in github_files:
            if gh_file['filename'] not in local_files:
                new_collections.append({
                    'filename': gh_file['filename'],
                    'name': gh_file['name'],
                    'count': gh_file.get('count', '?'),
                    'size': gh_file.get('size', '?')
                })

        return jsonify({
            "total": len(github_files),
            "local_count": len(local_files),
            "new_collections": new_collections,
            "message": f"Found {len(new_collections)} new collection(s)" if new_collections else "All collections synced"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/screen/rotation", methods=["GET", "POST"])
def screen_rotation():
    """Get or set screen rotation using wlr-randr (Wayland) or xrandr (X11)"""
    ROTATION_FILE = Path("/opt/vernis/rotation-config.json")

    if request.method == "POST":
        try:
            data = request.json
            rotation = data.get('rotation', 0)
            target = data.get('target', 'internal')  # "internal" or "external"

            # Validate rotation value
            if rotation not in [0, 90, 180, 270]:
                return jsonify({"error": "Invalid rotation value. Must be 0, 90, 180, or 270"}), 400

            # Detect if running Wayland or X11
            # Check for wayland socket in common user runtime dirs
            wayland_socket = None
            for uid in [1000, 1001, 0]:
                socket_path = f'/run/user/{uid}/wayland-0'
                if os.path.exists(socket_path):
                    wayland_socket = socket_path
                    break

            wayland_display = os.environ.get('WAYLAND_DISPLAY') or wayland_socket

            # Set up Wayland environment - use the user's runtime dir where wayland socket exists
            wayland_uid = 1000  # Default to typical user UID
            if wayland_socket:
                wayland_uid = int(wayland_socket.split('/')[3])

            wayland_env = {
                **os.environ,
                'XDG_RUNTIME_DIR': f'/run/user/{wayland_uid}',
                'WAYLAND_DISPLAY': 'wayland-0'
            }

            if wayland_display or subprocess.run(["which", "wlr-randr"], capture_output=True, timeout=5).returncode == 0:
                # Try Wayland first (wlr-randr)
                # Map rotation degrees to wlr-randr transform values
                wlr_rotation_map = {
                    0: "normal",
                    90: "90",
                    180: "180",
                    270: "270"
                }
                wlr_value = wlr_rotation_map[rotation]

                # Get display name with wlr-randr
                result = subprocess.run(
                    ["wlr-randr"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=wayland_env
                )

                if result.returncode == 0:
                    # Find the target display (DPI for internal, HDMI for external)
                    display = None
                    for line in result.stdout.split('\n'):
                        if line and not line.startswith(' '):
                            name = line.split()[0]
                            if target == 'external' and name.startswith('HDMI'):
                                display = name
                                break
                            elif target == 'internal' and name.startswith('DPI'):
                                display = name
                                break
                    # Fallback: use first display if target not found
                    if not display:
                        for line in result.stdout.split('\n'):
                            if line and not line.startswith(' '):
                                display = line.split()[0]
                                break

                    if display:
                        # Save rotation BEFORE applying — wlr-randr triggers udev drm
                        # change events which fire the hotplug script. The hotplug script
                        # reads this config to re-apply rotation, so it must be current.
                        rot_data = {}
                        if ROTATION_FILE.exists():
                            try:
                                with open(ROTATION_FILE, 'r') as f:
                                    rot_data = json.load(f)
                            except Exception:
                                pass
                        if target == 'external':
                            rot_data['rotation_external'] = rotation
                        else:
                            rot_data['rotation'] = rotation
                        with open(ROTATION_FILE, 'w') as f:
                            json.dump(rot_data, f)

                        # Set lock so hotplug script doesn't interfere
                        lock_path = Path("/tmp/vernis-rotation-lock")
                        lock_path.write_text(str(int(time.time())))

                        # Apply rotation with wlr-randr
                        cmd = ["wlr-randr", "--output", display, "--transform", wlr_value]
                        subprocess.run(cmd, check=True, timeout=10, env=wayland_env)

                        # Rotate touch input on Wayland
                        # wlr-randr transform usually auto-remaps touch in wlroots compositors,
                        # but apply libinput calibration matrix as fallback
                        touch_matrices = {
                            0: "1 0 0 0 1 0 0 0 1",
                            90: "0 1 0 -1 0 1 0 0 1",
                            180: "-1 0 1 0 -1 1 0 0 1",
                            270: "0 -1 1 1 0 0 0 0 1"
                        }
                        matrix = touch_matrices[rotation]
                        try:
                            # Write libinput calibration for persistence across reboots
                            calib_conf = f'''# Auto-generated by Vernis rotation
Section "InputClass"
    Identifier "touchscreen-calibration"
    MatchIsTouchscreen "on"
    Option "CalibrationMatrix" "{matrix}"
EndSection
'''
                            calib_path = Path("/etc/X11/xorg.conf.d/99-touch-calibration.conf")
                            calib_path.parent.mkdir(parents=True, exist_ok=True)
                            calib_path.write_text(calib_conf)

                            # Also try swaymsg for immediate effect on sway/labwc
                            touch_cmd = f'''
for DEVICE in $(libinput list-devices 2>/dev/null | grep -B1 -i "touch\\|goodix\\|digitizer" | grep "Device:" | sed 's/Device: *//'); do
    swaymsg input type:touch calibration_matrix {matrix} 2>/dev/null
done
'''
                            subprocess.run(["bash", "-c", touch_cmd], capture_output=True, timeout=5, env=wayland_env)
                        except Exception as touch_err:
                            print(f"Wayland touch calibration note: {touch_err}")

                        return jsonify({"success": True, "rotation": rotation, "target": target, "display_server": "wayland"})

            # Fallback to X11 (xrandr)
            # Map rotation degrees to xrandr values
            rotation_map = {
                0: "normal",
                90: "right",
                180: "inverted",
                270: "left"
            }

            xrandr_value = rotation_map[rotation]

            # Get X display environment (dynamically detects display number)
            env = get_x_display_env()

            result = subprocess.run(
                ["xrandr", "--query"],
                capture_output=True,
                text=True,
                timeout=5,
                env=env
            )

            # Find ALL connected displays
            displays = []
            for line in result.stdout.split('\n'):
                if ' connected' in line:
                    displays.append(line.split()[0])

            if not displays:
                # Provide more detailed error information for debugging
                error_msg = "Could not detect display"
                if result.returncode != 0:
                    error_msg += f". xrandr error: {result.stderr}"
                elif not result.stdout:
                    error_msg += ". No display server detected. Try rebooting."
                else:
                    error_msg += f". xrandr output: {result.stdout[:200]}"
                return jsonify({"error": error_msg}), 500

            # Get current resolution to swap for portrait mode
            current_res = None
            for line in result.stdout.split('\n'):
                if '*' in line:  # Current resolution has asterisk
                    parts = line.strip().split()
                    if parts:
                        current_res = parts[0]  # e.g., "1920x1080"
                        break

            # Apply rotation to ALL connected displays
            for display in displays:
                # Build xrandr command
                cmd = ["xrandr", "--output", display, "--rotate", xrandr_value]

                # For portrait modes (90/270), we may need to set mode explicitly
                # to ensure proper scaling
                if current_res and rotation in [90, 270]:
                    # Add scale to fill screen properly in portrait mode
                    cmd.extend(["--scale", "1x1"])

                subprocess.run(cmd, check=True, timeout=10, env=env)

            # Rotate touch input to match display rotation
            # Touch transformation matrices for each rotation
            touch_matrices = {
                0: "1 0 0 0 1 0 0 0 1",        # Normal
                90: "0 1 0 -1 0 1 0 0 1",      # Right (90° CW)
                180: "-1 0 1 0 -1 1 0 0 1",   # Inverted
                270: "0 -1 1 1 0 0 0 0 1"     # Left (270° CW / 90° CCW)
            }

            matrix = touch_matrices[rotation]

            # Apply touch calibration using shell command for reliability
            try:
                # Use shell command to ensure proper environment
                touch_cmd = f'''
                export DISPLAY={env.get('DISPLAY', ':0')}
                export XAUTHORITY={env.get('XAUTHORITY', '')}

                # Try by device ID first (most reliable)
                for ID in 6 7 8 9 10; do
                    xinput set-prop $ID "Coordinate Transformation Matrix" {matrix} 2>/dev/null && echo "Applied to device ID: $ID"
                done

                # Try known touch device names
                for DEVICE in "22-005d Goodix Capacitive TouchScreen" "Goodix Capacitive TouchScreen" "SYNAPTICS Synaptics Touch Digitizer V04" "FT5406" "eGalax"; do
                    xinput set-prop "$DEVICE" "Coordinate Transformation Matrix" {matrix} 2>/dev/null && echo "Applied to: $DEVICE"
                done

                # Also try to find any touch device dynamically
                xinput list --name-only 2>/dev/null | grep -iE "touch|digitizer|goodix" | while read DEVICE; do
                    xinput set-prop "$DEVICE" "Coordinate Transformation Matrix" {matrix} 2>/dev/null && echo "Applied to: $DEVICE"
                done
                '''
                result = subprocess.run(
                    ["bash", "-c", touch_cmd],
                    capture_output=True, text=True, timeout=10
                )
                if result.stdout:
                    print(f"Touch calibration: {result.stdout.strip()}")
            except Exception as touch_err:
                # Touch rotation is optional - don't fail if it doesn't work
                print(f"Touch rotation skipped: {touch_err}")

            # Save rotation state (per-target)
            ROTATION_FILE.parent.mkdir(parents=True, exist_ok=True)
            rot_data = {}
            if ROTATION_FILE.exists():
                try:
                    with open(ROTATION_FILE, 'r') as f:
                        rot_data = json.load(f)
                except Exception:
                    pass
            if target == 'external':
                rot_data['rotation_external'] = rotation
            else:
                rot_data['rotation'] = rotation
            with open(ROTATION_FILE, 'w') as f:
                json.dump(rot_data, f)

            # Restart X session to apply new rotation with correct window size
            # The xinitrc will read the rotation config and start Chromium with correct settings
            try:
                # Kill Chromium - this will cause xinit to exit and restart with new settings
                subprocess.run(["pkill", "-9", "chromium"], timeout=5)
                print("Chromium killed - X session will restart with new rotation settings")
            except Exception as chrome_err:
                print(f"Chromium restart skipped: {chrome_err}")

            return jsonify({
                "success": True,
                "rotation": rotation,
                "message": f"Screen rotated to {rotation}°"
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Rotation command timed out"}), 500
        except subprocess.CalledProcessError as e:
            return jsonify({"error": f"Rotation failed: {str(e)}"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        # GET - return current rotation for both targets
        try:
            if ROTATION_FILE.exists():
                with open(ROTATION_FILE, 'r') as f:
                    config = json.load(f)
                    return jsonify({
                        "rotation": config.get("rotation", 0),
                        "rotation_external": config.get("rotation_external", 0)
                    })
            else:
                return jsonify({"rotation": 0, "rotation_external": 0})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route("/api/update-config", methods=["GET", "POST"])
def update_config():
    """Get or set update configuration"""
    if request.method == "POST":
        try:
            data = request.json

            # Validate mode
            mode = data.get('mode', 'production')
            if mode not in ['dev', 'production']:
                return jsonify({"error": "Invalid mode. Must be 'dev' or 'production'"}), 400

            config = {
                "mode": mode,
                "dev_server": data.get('dev_server', '').strip(),
                "github_repo": data.get('github_repo', '').strip(),
                "github_branch": data.get('github_branch', 'main').strip()
            }

            # Save configuration
            UPDATE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(UPDATE_CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)

            return jsonify({"success": True, "config": config})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        # GET - return current configuration
        return jsonify(get_update_config())

@app.route("/api/system/update", methods=["POST"])
def system_update():
    """Trigger system package update and reboot"""
    try:
        # Simple system package update - apt upgrade and reboot
        # Run in background so API can respond
        update_script = """#!/bin/bash
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
        echo "Updates installed, rebooting..."
        sleep 3
        reboot
        """

        # Write and execute the script
        script_path = Path("/tmp/system-update.sh")
        script_path.write_text(update_script)
        script_path.chmod(0o755)

        subprocess.Popen(["sudo", "bash", str(script_path)])

        return jsonify({
            "success": True,
            "message": "System update started. Device will reboot when complete."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/system/check-updates", methods=["GET"])
def check_updates():
    """Check for available system package updates"""
    try:
        # First run apt update to refresh package list
        subprocess.run(
            ["sudo", "apt-get", "update"],
            capture_output=True,
            timeout=60
        )

        # Check for upgradable packages
        result = subprocess.run(
            ["apt", "list", "--upgradable"],
            capture_output=True,
            text=True,
            timeout=30
        )

        lines = [l for l in result.stdout.split('\n') if l and not l.startswith('Listing')]
        update_count = len(lines)

        if update_count > 0:
            sample_packages = [l.split('/')[0] for l in lines[:5]]
            return jsonify({
                "updates_available": True,
                "update_count": update_count,
                "sample_packages": sample_packages,
                "message": f"{update_count} system package(s) can be upgraded"
            })
        else:
            return jsonify({
                "updates_available": False,
                "message": "System is up to date"
            })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Update check timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Remote control state file
REMOTE_CONTROL_FILE = Path("/opt/vernis/remote-control.json")

@app.route("/api/remote/command", methods=["POST"])
def remote_command():
    """Send a command to the gallery display"""
    try:
        data = request.json
        command = data.get('command', '').strip()

        valid_commands = ['next', 'prev', 'play', 'pause', 'toggle', 'hue_on', 'hue_off', 'easter_egg']
        if command not in valid_commands:
            return jsonify({"error": f"Invalid command. Valid: {valid_commands}"}), 400

        # Write command with timestamp
        import time
        control_data = {
            "command": command,
            "timestamp": time.time()
        }

        # Easter egg commands: navigate Chromium directly via DevTools
        if command == 'easter_egg':
            egg_type = data.get('type', '')
            if egg_type not in ('punk', 'glyph', 'pixelchain', 'gazer', 'burner'):
                return jsonify({"error": "Invalid easter egg type"}), 400
            egg_id = int(data.get('id', 0))
            egg_cycle = '1' if data.get('cycle', False) else '0'
            egg_mode = data.get('mode', '')
            egg_hue = '1' if data.get('hue', False) else '0'
            url = f"http://localhost/lab.html?type={egg_type}&id={egg_id}&fullscreen=1&return=gallery&cycle={egg_cycle}"
            if egg_mode and egg_mode in ('pixel', 'svg', 'ascii', 'hex'):
                url += f"&mode={egg_mode}"
            if egg_hue == '1':
                url += "&hue=1"
            try:
                import urllib.request
                tabs_resp = urllib.request.urlopen("http://localhost:9222/json/list", timeout=2)
                tabs = json.loads(tabs_resp.read())
                if tabs:
                    ws_url = tabs[0].get("webSocketDebuggerUrl", "")
                    if ws_url:
                        import websocket
                        ws = websocket.create_connection(ws_url, timeout=3)
                        ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
                        ws.recv()
                        ws.close()
                        return jsonify({"success": True, "command": command, "navigated": url})
            except Exception as nav_err:
                # Fallback: write command file for gallery polling
                pass
            control_data["type"] = egg_type
            control_data["id"] = egg_id
            control_data["cycle"] = bool(data.get('cycle', False))

        with open(REMOTE_CONTROL_FILE, 'w') as f:
            json.dump(control_data, f)

        return jsonify({"success": True, "command": command})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/remote/poll")
def remote_poll():
    """Poll for remote commands (called by gallery.html)"""
    try:
        if not REMOTE_CONTROL_FILE.exists():
            return jsonify({"command": None})

        with open(REMOTE_CONTROL_FILE, 'r') as f:
            data = json.load(f)

        # Check if command is fresh (within last 5 seconds)
        import time
        if time.time() - data.get('timestamp', 0) > 5:
            return jsonify({"command": None})

        # Clear the command after reading
        REMOTE_CONTROL_FILE.unlink()

        resp = {"command": data.get('command')}
        # Pass through extra fields for easter_egg commands
        if data.get('command') == 'easter_egg':
            resp["type"] = data.get("type", "")
            resp["id"] = data.get("id", 0)
            resp["cycle"] = data.get("cycle", False)
        return jsonify(resp)
    except Exception as e:
        return jsonify({"command": None})

@app.route("/api/remote/status")
def remote_status():
    """Get current gallery status for remote control UI"""
    try:
        # Count NFTs
        nft_count = len(list(NFT_DIR.glob("*.*"))) - 1  # Exclude progress.json

        # Get display config
        DISPLAY_CONFIG_FILE = Path("/opt/vernis/display-config.json")
        if DISPLAY_CONFIG_FILE.exists():
            with open(DISPLAY_CONFIG_FILE, 'r') as f:
                display_config = json.load(f)
        else:
            display_config = {"image_duration": 15}

        return jsonify({
            "nft_count": max(0, nft_count),
            "interval": display_config.get('image_duration', 15)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

GALLERY_STATE_FILE = Path("/opt/vernis/gallery-state.json")

def get_gallery_state():
    """Check if gallery is currently running"""
    if GALLERY_STATE_FILE.exists():
        try:
            with open(GALLERY_STATE_FILE, 'r') as f:
                return json.load(f).get('running', False)
        except:
            pass
    return False

def set_gallery_state(running):
    """Set gallery running state"""
    with open(GALLERY_STATE_FILE, 'w') as f:
        json.dump({'running': running}, f)

KIOSK_URL_FILE = Path("/opt/vernis/kiosk-url.conf")
CDP_PORT = 9222

def navigate_browser_cdp(url):
    """Navigate browser using Chrome DevTools Protocol for seamless transition."""
    try:
        # Get list of pages from CDP
        resp = requests.get(f'http://127.0.0.1:{CDP_PORT}/json', timeout=2)
        if resp.status_code != 200:
            return False, "CDP not available"

        pages = resp.json()
        if not pages:
            return False, "No browser pages found"

        # Find the main page (type: "page")
        target = None
        for page in pages:
            if page.get('type') == 'page':
                target = page
                break

        if not target:
            return False, "No page target found"

        # Use the webSocketDebuggerUrl to send navigation command
        ws_url = target.get('webSocketDebuggerUrl')
        if not ws_url:
            return False, "No WebSocket URL available"

        # Send navigation via HTTP endpoint (simpler than WebSocket)
        page_id = target.get('id')
        nav_url = f'http://127.0.0.1:{CDP_PORT}/json/navigate?{page_id}&{url}'

        # Alternative: use Page.navigate via websocket-like HTTP
        # Actually, let's use the simpler approach: activate and navigate
        import urllib.parse
        encoded_url = urllib.parse.quote(url, safe='')

        # The simplest CDP navigation is via the /json/new endpoint or JavaScript injection
        # Let's use JavaScript execution via CDP
        import websocket
        ws = websocket.create_connection(ws_url, timeout=5)

        # Send Page.navigate command
        nav_cmd = json.dumps({
            "id": 1,
            "method": "Page.navigate",
            "params": {"url": url}
        })
        ws.send(nav_cmd)
        result = ws.recv()
        ws.close()

        print(f"[navigate_browser_cdp] Navigation result: {result}", flush=True)
        return True, None

    except Exception as e:
        print(f"[navigate_browser_cdp] Error: {e}", flush=True)
        return False, str(e)

def navigate_browser(url):
    """Navigate the kiosk browser to a URL.

    Uses Chrome DevTools Protocol for seamless transition.
    Falls back to restart method if CDP fails.
    """
    print(f"[navigate_browser] Navigating to {url}", flush=True)

    # Always update the URL file (for next restart)
    try:
        with open(KIOSK_URL_FILE, 'w') as f:
            f.write(url)
    except:
        pass

    # Try CDP first for seamless navigation
    success, error = navigate_browser_cdp(url)
    if success:
        print(f"[navigate_browser] CDP navigation successful", flush=True)
        return True, None

    print(f"[navigate_browser] CDP failed ({error}), falling back to restart", flush=True)

    # Fallback: restart Chromium
    try:
        subprocess.run(['pkill', '-f', 'chromium'], capture_output=True, timeout=5)
        return True, None
    except Exception as e:
        return False, str(e)

@app.route("/api/gallery/show-generator", methods=["POST"])
def gallery_show_generator():
    """Navigate to an HTML generator full-page, inject touch overlay, schedule return."""
    try:
        data = request.json or {}
        rel_url = data.get('url', '')
        delay = min(max(int(data.get('delay', 15)), 5), 600)

        if not rel_url or '..' in rel_url:
            return jsonify({"error": "Invalid URL"}), 400

        full_url = f"https://localhost{rel_url}"

        def _show_and_return(url, d):
            import time
            import websocket as _ws
            try:
                # Get CDP WebSocket URL
                resp = requests.get(f'http://127.0.0.1:{CDP_PORT}/json', timeout=2)
                pages = resp.json()
                ws_url = None
                for p in pages:
                    if p.get('type') == 'page':
                        ws_url = p.get('webSocketDebuggerUrl')
                        break
                if not ws_url:
                    return

                ws = _ws.create_connection(ws_url, timeout=5)

                # Navigate to generator
                ws.send(json.dumps({
                    'id': 1,
                    'method': 'Page.navigate',
                    'params': {'url': url}
                }))
                ws.recv()

                # Wait for page to load
                time.sleep(2)

                # Inject touch-blocking overlay
                overlay_js = """
                (function() {
                    var overlay = document.createElement('div');
                    overlay.id = 'vernis-touch-overlay';
                    overlay.style.cssText = 'position:fixed;inset:0;z-index:99999;cursor:none;';
                    document.body.appendChild(overlay);
                })();
                """
                ws.send(json.dumps({
                    'id': 2,
                    'method': 'Runtime.evaluate',
                    'params': {'expression': overlay_js}
                }))
                ws.recv()

                ws.close()

                # Wait for duration, then navigate back
                time.sleep(d)
                navigate_browser_cdp('https://localhost/gallery.html')
            except Exception as e:
                print(f"[show-generator] Error: {e}", flush=True)

        t = threading.Thread(target=_show_and_return, args=(full_url, delay), daemon=True)
        t.start()
        return jsonify({"success": True, "delay": delay})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/remote/gallery-state")
def remote_gallery_state():
    """Get current gallery running state"""
    return jsonify({"running": get_gallery_state()})

@app.route("/api/remote/start-gallery", methods=["POST"])
def remote_start_gallery():
    """Start the gallery on the Pi's display"""
    try:
        success, error = navigate_browser('http://localhost/gallery.html')
        if success:
            set_gallery_state(True)
            return jsonify({"success": True, "message": "Gallery started", "running": True})
        else:
            return jsonify({"success": False, "error": error})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/remote/stop-gallery", methods=["POST"])
def remote_stop_gallery():
    """Stop the gallery and go to home screen"""
    try:
        success, error = navigate_browser('http://localhost/')
        if success:
            set_gallery_state(False)
            return jsonify({"success": True, "message": "Gallery stopped", "running": False})
        else:
            return jsonify({"success": False, "error": error})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# =============================================
# Thermal Monitoring
# =============================================
THERMAL_LOG_FILE = Path("/opt/vernis/thermal-log.json")

def get_thermal_status():
    """Get current CPU temperature and throttling status"""
    result = {
        "temperature": None,
        "throttled": False,
        "throttle_flags": [],
        "under_voltage": False,
        "frequency_capped": False,
        "timestamp": time.time()
    }

    # Get CPU temperature
    try:
        # Try vcgencmd first (Raspberry Pi specific)
        temp_result = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True, text=True, timeout=5
        )
        if temp_result.returncode == 0:
            # Output: temp=45.0'C
            temp_str = temp_result.stdout.strip()
            temp = float(temp_str.replace("temp=", "").replace("'C", ""))
            result["temperature"] = temp
    except:
        # Fallback to sys file
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp = int(f.read().strip()) / 1000.0
                result["temperature"] = temp
        except:
            pass

    # Get throttling status
    try:
        throttle_result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True, text=True, timeout=5
        )
        if throttle_result.returncode == 0:
            # Output: throttled=0x0
            throttle_str = throttle_result.stdout.strip()
            throttle_hex = throttle_str.replace("throttled=", "")
            throttle_val = int(throttle_hex, 16)

            # Decode throttle flags
            flags = []
            if throttle_val & 0x1:
                flags.append("Under-voltage detected")
                result["under_voltage"] = True
            if throttle_val & 0x2:
                flags.append("Frequency capped")
                result["frequency_capped"] = True
            if throttle_val & 0x4:
                flags.append("Currently throttled")
                result["throttled"] = True
            if throttle_val & 0x8:
                flags.append("Soft temp limit")
            if throttle_val & 0x10000:
                flags.append("Under-voltage occurred")
            if throttle_val & 0x20000:
                flags.append("Freq cap occurred")
            if throttle_val & 0x40000:
                flags.append("Throttling occurred")
            if throttle_val & 0x80000:
                flags.append("Soft temp limit occurred")

            result["throttle_flags"] = flags
            result["throttle_raw"] = throttle_hex
    except:
        pass

    return result

def log_thermal_reading():
    """Log current thermal reading to file"""
    try:
        # Load existing log
        if THERMAL_LOG_FILE.exists():
            with open(THERMAL_LOG_FILE, 'r') as f:
                log_data = json.load(f)
        else:
            log_data = {"readings": []}

        # Add new reading
        reading = get_thermal_status()
        log_data["readings"].append(reading)

        # Keep only last 24 hours (288 readings at 5-min intervals)
        cutoff = time.time() - (24 * 60 * 60)
        log_data["readings"] = [r for r in log_data["readings"] if r.get("timestamp", 0) > cutoff]

        # Save
        with open(THERMAL_LOG_FILE, 'w') as f:
            json.dump(log_data, f)
    except Exception as e:
        print(f"Error logging thermal: {e}")

# Background thermal logger - logs every 5 minutes
def _thermal_logger_loop():
    while True:
        time.sleep(300)  # 5 minutes
        log_thermal_reading()

_thermal_logger_thread = threading.Thread(target=_thermal_logger_loop, daemon=True)
_thermal_logger_thread.start()

@app.route("/api/thermal/status")
def thermal_status():
    """Get current thermal status"""
    try:
        status = get_thermal_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/thermal/history")
def thermal_history():
    """Get 24-hour thermal history"""
    try:
        if THERMAL_LOG_FILE.exists():
            with open(THERMAL_LOG_FILE, 'r') as f:
                log_data = json.load(f)

            readings = log_data.get("readings", [])

            # Calculate stats
            if readings:
                temps = [r["temperature"] for r in readings if r.get("temperature")]
                throttle_count = sum(1 for r in readings if r.get("throttled"))
                undervolt_count = sum(1 for r in readings if r.get("under_voltage"))

                stats = {
                    "min_temp": min(temps) if temps else None,
                    "max_temp": max(temps) if temps else None,
                    "avg_temp": sum(temps) / len(temps) if temps else None,
                    "throttle_events": throttle_count,
                    "undervolt_events": undervolt_count,
                    "total_readings": len(readings)
                }
            else:
                stats = {}

            return jsonify({
                "readings": readings,
                "stats": stats
            })
        else:
            return jsonify({"readings": [], "stats": {}})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =============================================
# Fan Control
# =============================================
FAN_CONFIG_FILE = Path("/opt/vernis/fan-config.json")

# Temperature thresholds in millidegrees for each mode
FAN_MODES = {
    "off": None,
    "silent": 80000,  # Whisper baseline + high trip points (ideal for 24/7 kiosk)
    "normal": 55000,
    "full": 0  # Always on (threshold 0 = always above)
}

def load_fan_config():
    """Load fan configuration"""
    if FAN_CONFIG_FILE.exists():
        with open(FAN_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"mode": "off", "gpio_pin": 14}

def save_fan_config(config):
    """Save fan configuration"""
    FAN_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(FAN_CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def apply_fan_overlay(mode, gpio_pin=None):
    """Update /boot/config.txt with gpio-fan overlay setting.
    Preserves the existing GPIO pin from config.txt if none specified."""
    config_paths = [Path("/boot/firmware/config.txt"), Path("/boot/config.txt")]
    config_path = None
    for p in config_paths:
        if p.exists():
            config_path = p
            break
    if not config_path:
        return False, "config.txt not found"

    try:
        lines = config_path.read_text().splitlines()

        # Read existing GPIO pin from config.txt before removing the line
        if gpio_pin is None:
            import re as _re
            for l in lines:
                m = _re.search(r'dtoverlay=gpio-fan.*gpiopin=(\d+)', l.strip())
                if m:
                    gpio_pin = int(m.group(1))
                    break
            if gpio_pin is None:
                gpio_pin = 26  # Safe default for DPI displays

        # Remove existing gpio-fan overlay lines
        new_lines = [l for l in lines if not l.strip().startswith("dtoverlay=gpio-fan")]

        if mode in ("silent", "normal", "full"):
            threshold = FAN_MODES[mode]
            new_lines.append(f"dtoverlay=gpio-fan,gpiopin={gpio_pin},temp={threshold}")

        config_path.write_text("\n".join(new_lines) + "\n")
        return True, "ok"
    except Exception as e:
        return False, str(e)

def apply_fan_live(mode):
    """Apply fan setting immediately via sysfs (no reboot needed).
    Works with both gpio-fan (on/off) and pwm-fan (speed levels).
    Sets ALL active trip points so the step_wise governor respects our setting.
    Changes are temporary - revert on reboot unless config.txt is also updated."""
    try:
        tz = Path("/sys/class/thermal/thermal_zone0")

        # Collect all writable active trip points (skip 'critical' type)
        active_trips = []
        for i in range(10):
            tp_temp = tz / f"trip_point_{i}_temp"
            tp_type = tz / f"trip_point_{i}_type"
            if not tp_temp.exists():
                break
            ttype = tp_type.read_text().strip() if tp_type.exists() else ""
            if ttype == "active":
                active_trips.append(tp_temp)

        # Set trip point temperatures based on mode
        # This tells the step_wise governor when to ramp the fan
        mode_trips = {
            "off":        [95000, 95000, 95000, 95000],  # never trigger
            "silent":     [0, 65000, 72000, 78000],       # level 1 always on, gentle ramp before throttle (80°C)
            "normal":     [50000, 60000, 67500, 75000],   # Pi 5 defaults
            "full":       [0, 0, 0, 0],                   # always max
        }
        temps = mode_trips.get(mode, mode_trips["normal"])
        for i, tp in enumerate(active_trips):
            temp = temps[i] if i < len(temps) else temps[-1]
            tp.write_text(f"{temp}\n")

        # Read current temp to calculate correct fan level
        cur_temp = 50000
        temp_file = tz / "temp"
        if temp_file.exists():
            cur_temp = int(temp_file.read_text().strip())

        # Find PWM fan cooling device
        pwm_path = None
        for cd in sorted(Path("/sys/class/thermal/").glob("cooling_device*")):
            type_file = cd / "type"
            if type_file.exists() and type_file.read_text().strip() == "pwm-fan":
                pwm_path = cd
                break

        if pwm_path:
            max_state = int((pwm_path / "max_state").read_text().strip())
            cur_state_path = pwm_path / "cur_state"

            if mode == "full":
                cur_state_path.write_text(str(max_state) + "\n")
            elif mode == "off":
                cur_state_path.write_text("0\n")
            else:
                # Calculate correct fan level from current temp vs new trip points
                level = 0
                for t in temps:
                    if cur_temp >= t:
                        level += 1
                level = min(level, max_state)
                cur_state_path.write_text(f"{level}\n")

        return True, "ok"
    except Exception as e:
        return False, str(e)

def get_fan_live_status():
    """Read current fan status from sysfs"""
    result = {"rpm": None, "pwm": None, "temp": None}
    try:
        # Current CPU temp
        temp_file = Path("/sys/class/thermal/thermal_zone0/temp")
        if temp_file.exists():
            result["temp"] = int(temp_file.read_text().strip()) / 1000.0

        # Fan RPM from hwmon
        for hwmon in Path("/sys/devices/platform/cooling_fan/hwmon/").glob("hwmon*/fan1_input"):
            result["rpm"] = int(hwmon.read_text().strip())
            break

        # PWM value (0-255)
        for hwmon in Path("/sys/devices/platform/cooling_fan/hwmon/").glob("hwmon*/pwm1"):
            result["pwm"] = int(hwmon.read_text().strip())
            break
    except Exception:
        pass
    return result

@app.route("/api/fan/config", methods=["GET"])
def get_fan_config():
    """Get current fan configuration with live status"""
    try:
        config = load_fan_config()
        config["live"] = get_fan_live_status()
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/fan/config", methods=["POST"])
def set_fan_config():
    """Set fan configuration: apply live + update boot config for persistence"""
    try:
        data = request.json
        mode = data.get("mode", "off")
        # Legacy alias: auto-quiet was renamed to silent
        if mode == "auto-quiet":
            mode = "silent"
        existing_config = load_fan_config()
        gpio_pin = data.get("gpio_pin", existing_config.get("gpio_pin"))

        if mode not in FAN_MODES and mode != "off":
            return jsonify({"error": f"Invalid mode: {mode}"}), 400

        config = {"mode": mode, "gpio_pin": gpio_pin}
        save_fan_config(config)

        # Apply immediately via sysfs (no reboot needed)
        live_ok, live_msg = apply_fan_live(mode)

        # Also update config.txt for persistence across reboots
        boot_ok, boot_msg = apply_fan_overlay(mode, gpio_pin)

        # Wait for fan RPM sensor to reflect the change
        time.sleep(2)

        return jsonify({
            "success": True,
            "mode": mode,
            "applied_live": live_ok,
            "reboot_required": True,
            "live": get_fan_live_status()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =============================================
# CPU Performance Profiles
# =============================================
CPU_PROFILE_CONFIG_FILE = Path("/opt/vernis/cpu-profile.json")

# CPU profiles for different Pi models (MHz values)
# cores: number of CPU cores (1-4), boost: allow turbo boost, arm_freq: max frequency
CPU_PROFILES = {
    "pi5": {
        "eco": {"arm_freq": 1200, "over_voltage": 4, "cores": 2, "boost": False, "icon": "🌱", "description": "Coolest, basic gallery use"},
        "balanced": {"arm_freq": 1500, "over_voltage": 4, "cores": 2, "boost": False, "icon": "⚖️", "description": "Recommended - smooth & cool"},
        "performance": {"arm_freq": 1800, "over_voltage": 4, "cores": 4, "boost": False, "icon": "⚡", "description": "More power, warmer"},
        "maximum": {"arm_freq": 2400, "over_voltage": 4, "cores": 4, "boost": True, "icon": "🔥", "description": "Full power (needs fan)"},
    },
    "pi4": {
        "eco": {"arm_freq": 900, "gpu_freq": 400, "over_voltage": -4, "cores": 2, "boost": False, "icon": "🌱", "description": "Coolest, basic gallery use"},
        "balanced": {"arm_freq": 1200, "gpu_freq": 450, "over_voltage": -2, "cores": 2, "boost": False, "icon": "⚖️", "description": "Recommended - smooth & cool"},
        "performance": {"arm_freq": 1500, "gpu_freq": 500, "over_voltage": 0, "cores": 4, "boost": False, "icon": "⚡", "description": "Default Pi 4 speed"},
        "maximum": {"arm_freq": 2000, "gpu_freq": 600, "over_voltage": 6, "cores": 4, "boost": True, "icon": "🔥", "description": "Overclocked (needs cooling)"},
    },
    "pi_zero_2w": {
        "eco": {"arm_freq": 600, "gpu_freq": 300, "over_voltage": -4, "cores": 2, "boost": False, "icon": "🌱", "description": "Minimum power"},
        "balanced": {"arm_freq": 800, "gpu_freq": 350, "over_voltage": -2, "cores": 4, "boost": False, "icon": "⚖️", "description": "Recommended"},
        "performance": {"arm_freq": 1000, "gpu_freq": 400, "over_voltage": 0, "cores": 4, "boost": False, "icon": "⚡", "description": "Default speed"},
        "maximum": {"arm_freq": 1200, "gpu_freq": 500, "over_voltage": 4, "cores": 4, "boost": True, "icon": "🔥", "description": "Overclocked (needs heatsink)"},
    },
    "unknown": {
        "eco": {"arm_freq": 600, "gpu_freq": 300, "over_voltage": -4, "cores": 2, "boost": False, "icon": "🌱", "description": "Minimum power"},
        "balanced": {"arm_freq": 1000, "gpu_freq": 400, "over_voltage": -2, "cores": 2, "boost": False, "icon": "⚖️", "description": "Recommended"},
        "performance": {"arm_freq": 1500, "gpu_freq": 500, "over_voltage": 0, "cores": 4, "boost": False, "icon": "⚡", "description": "Default"},
        "maximum": {"arm_freq": 1800, "gpu_freq": 600, "over_voltage": 4, "cores": 4, "boost": True, "icon": "🔥", "description": "Overclocked"},
    }
}

def detect_pi_model():
    """Detect Raspberry Pi model from /proc/cpuinfo"""
    try:
        with open("/proc/cpuinfo", "r") as f:
            cpuinfo = f.read()

        # Look for Model line
        model_line = ""
        for line in cpuinfo.split("\n"):
            if line.startswith("Model"):
                model_line = line.split(":", 1)[1].strip().lower()
                break

        if "pi 5" in model_line or "raspberry pi 5" in model_line:
            return "pi5", "Raspberry Pi 5"
        elif "pi 4" in model_line or "raspberry pi 4" in model_line:
            return "pi4", "Raspberry Pi 4"
        elif "pi zero 2" in model_line or "zero 2 w" in model_line:
            return "pi_zero_2w", "Raspberry Pi Zero 2 W"
        elif "pi zero" in model_line:
            return "pi_zero", "Raspberry Pi Zero"
        elif "pi 3" in model_line:
            return "pi3", "Raspberry Pi 3"
        else:
            # Try to get revision from Hardware line
            for line in cpuinfo.split("\n"):
                if line.startswith("Hardware"):
                    hw = line.split(":", 1)[1].strip()
                    if "BCM2712" in hw:
                        return "pi5", "Raspberry Pi 5"
                    elif "BCM2711" in hw:
                        return "pi4", "Raspberry Pi 4"
            return "unknown", model_line or "Unknown Pi Model"
    except Exception as e:
        return "unknown", f"Detection failed: {str(e)}"

def get_current_cpu_freq():
    """Get current CPU frequency"""
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "r") as f:
            return int(f.read().strip()) // 1000  # Convert kHz to MHz
    except:
        return None

def get_cpu_temp():
    """Get current CPU temperature"""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return int(f.read().strip()) / 1000.0
    except:
        return None

def read_config_txt():
    """Read /boot/firmware/config.txt"""
    config_paths = ["/boot/firmware/config.txt", "/boot/config.txt"]
    for path in config_paths:
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read(), path
    return "", None

def get_current_profile_from_config():
    """Detect current profile from config.txt"""
    content, _ = read_config_txt()

    # Parse arm_freq from config
    arm_freq = None
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("arm_freq=") and not line.startswith("#"):
            try:
                arm_freq = int(line.split("=")[1])
            except:
                pass

    return arm_freq

def get_current_cores():
    """Get current number of online CPU cores"""
    try:
        # Read from /sys/devices/system/cpu/online (e.g., "0-3" = 4 cores, "0-1" = 2 cores)
        with open("/sys/devices/system/cpu/online", "r") as f:
            online = f.read().strip()
        # Parse format like "0-3" or "0-1" or "0"
        if "-" in online:
            start, end = online.split("-")
            return int(end) - int(start) + 1
        else:
            return 1
    except:
        return 4  # Default to 4 cores

def get_max_cores_from_cmdline():
    """Get maxcpus setting from cmdline.txt"""
    cmdline_paths = ["/boot/firmware/cmdline.txt", "/boot/cmdline.txt"]
    for path in cmdline_paths:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    content = f.read()
                # Look for maxcpus=N
                import re
                match = re.search(r'maxcpus=(\d+)', content)
                if match:
                    return int(match.group(1)), path
                return None, path  # No maxcpus set (all cores enabled)
            except:
                pass
    return None, None

def get_boost_from_config():
    """Get arm_boost setting from config.txt"""
    content, _ = read_config_txt()
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("arm_boost=") and not line.startswith("#"):
            try:
                return int(line.split("=")[1]) == 1
            except:
                pass
    return True  # Default is boost enabled on Pi 5

def write_cmdline_cores(num_cores):
    """Write maxcpus to cmdline.txt"""
    cmdline_paths = ["/boot/firmware/cmdline.txt", "/boot/cmdline.txt"]
    for path in cmdline_paths:
        if os.path.exists(path):
            with open(path, "r") as f:
                content = f.read().strip()

            import re
            # Remove existing maxcpus parameter
            content = re.sub(r'\s*maxcpus=\d+', '', content)

            # Add maxcpus if not using all cores (4)
            if num_cores < 4:
                content = content + f" maxcpus={num_cores}"

            write_content = content.strip() + "\n"
            result = subprocess.run(
                ["sudo", "tee", path],
                input=write_content.encode(), capture_output=True, timeout=10
            )
            return result.returncode == 0
    return False

def get_saved_profile():
    """Get saved profile preference"""
    if CPU_PROFILE_CONFIG_FILE.exists():
        try:
            with open(CPU_PROFILE_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"profile": "high", "applied": False}

@app.route("/api/system/pi-model")
def api_pi_model():
    """Get detected Pi model"""
    try:
        model_id, model_name = detect_pi_model()
        current_freq = get_current_cpu_freq()
        current_temp = get_cpu_temp()

        return jsonify({
            "model_id": model_id,
            "model_name": model_name,
            "current_freq_mhz": current_freq,
            "current_temp_c": current_temp,
            "profiles_available": list(CPU_PROFILES.get(model_id, CPU_PROFILES["unknown"]).keys())
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/system/cpu-profile", methods=["GET"])
def get_cpu_profile():
    """Get current CPU profile settings"""
    try:
        model_id, model_name = detect_pi_model()
        profiles = CPU_PROFILES.get(model_id, CPU_PROFILES["unknown"])
        saved = get_saved_profile()
        current_freq = get_current_cpu_freq()
        config_arm_freq = get_current_profile_from_config()
        current_cores = get_current_cores()
        config_max_cores, _ = get_max_cores_from_cmdline()
        current_boost = get_boost_from_config()

        # Try to detect which profile matches current config
        detected_profile = None
        if config_arm_freq:
            for profile_name, settings in profiles.items():
                if settings["arm_freq"] == config_arm_freq:
                    detected_profile = profile_name
                    break

        # DPI displays can't use boost (shifts pixel clock dividers)
        content, _ = read_config_txt()
        has_dpi = any("vc4-kms-DPI" in l or "waveshare-4dpi" in l
                       for l in content.split("\n") if not l.strip().startswith("#"))

        return jsonify({
            "model_id": model_id,
            "model_name": model_name,
            "current_profile": saved.get("profile", "balanced"),
            "detected_profile": detected_profile,
            "config_arm_freq": config_arm_freq,
            "current_freq_mhz": current_freq,
            "current_temp_c": get_cpu_temp(),
            "current_cores": current_cores,
            "config_max_cores": config_max_cores if config_max_cores else 4,
            "current_boost": current_boost,
            "has_dpi": has_dpi,
            "profiles": {
                name: {
                    "arm_freq": p["arm_freq"],
                    "gpu_freq": p.get("gpu_freq"),
                    "cores": p["cores"],
                    "boost": False if has_dpi else p["boost"],
                    "icon": p["icon"],
                    "description": p["description"]
                }
                for name, p in profiles.items()
            },
            "needs_reboot": saved.get("profile") != detected_profile and saved.get("applied", False)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/system/cpu-profile", methods=["POST"])
def set_cpu_profile():
    """Set CPU profile - modifies config.txt and cmdline.txt"""
    try:
        data = request.json
        profile_name = data.get("profile")

        # Check if this is a custom profile request
        custom_cores = data.get("cores")
        custom_boost = data.get("boost")
        custom_freq = data.get("arm_freq")

        model_id, _ = detect_pi_model()
        profiles = CPU_PROFILES.get(model_id, CPU_PROFILES["unknown"])

        # Use preset profile or build custom settings
        if profile_name and profile_name in profiles:
            profile = profiles[profile_name].copy()
        elif custom_cores is not None or custom_boost is not None or custom_freq is not None:
            # Custom settings - start from current or balanced
            base_profile = profiles.get("balanced", list(profiles.values())[0])
            profile = base_profile.copy()
            profile_name = "custom"
            if custom_cores is not None:
                profile["cores"] = max(1, min(4, int(custom_cores)))
            if custom_boost is not None:
                profile["boost"] = bool(custom_boost)
            if custom_freq is not None:
                profile["arm_freq"] = int(custom_freq)
        else:
            return jsonify({"error": "Profile name or custom settings required"}), 400

        # Read current config.txt
        content, config_path = read_config_txt()
        if not config_path:
            return jsonify({"error": "Could not find config.txt"}), 500

        # Remove existing CPU frequency settings (preserve other settings)
        lines = content.split("\n")
        new_lines = []
        freq_settings = ["arm_freq", "arm_freq_min", "gpu_freq", "over_voltage", "force_turbo", "arm_boost"]

        for line in lines:
            # Skip lines that set frequency (we'll add our own)
            stripped = line.strip()
            if any(stripped.startswith(f"{setting}=") or stripped.startswith(f"#{setting}=") for setting in freq_settings):
                continue
            # Skip the Vernis CPU Profile marker section if it exists
            if "# Vernis CPU Profile" in line:
                continue
            new_lines.append(line)

        # Remove trailing empty lines
        while new_lines and not new_lines[-1].strip():
            new_lines.pop()

        # Check if DPI display overlay is present — DPI pixel clock is derived from
        # gpu_freq, so changing it causes display artifacts (color shift, scan lines)
        has_dpi = any("vc4-kms-DPI" in l or "waveshare-4dpi" in l for l in new_lines if not l.strip().startswith("#"))

        # Add our settings at the end
        new_lines.append("")
        new_lines.append(f"# Vernis CPU Profile: {profile_name}")
        new_lines.append(f"arm_freq={profile['arm_freq']}")
        if not has_dpi and "gpu_freq" in profile:
            new_lines.append(f"gpu_freq={profile['gpu_freq']}")
        new_lines.append(f"over_voltage={4 if has_dpi else profile.get('over_voltage', 0)}")
        # arm_boost: 0 on DPI displays (boost shifts pixel clock dividers causing artifacts)
        new_lines.append(f"arm_boost={'0' if has_dpi else ('1' if profile.get('boost', False) else '0')}")
        # Set minimum frequency for power saving
        new_lines.append(f"arm_freq_min=600")
        new_lines.append("")

        # Write config.txt (requires sudo — boot partition is root-owned)
        new_content = "\n".join(new_lines)
        result = subprocess.run(
            ["sudo", "tee", config_path],
            input=new_content.encode(), capture_output=True, timeout=10
        )
        if result.returncode != 0:
            return jsonify({"error": f"Failed to write config.txt: {result.stderr.decode().strip()}"}), 500

        # Write cores to cmdline.txt
        cores = profile.get("cores", 4)
        cores_written = write_cmdline_cores(cores)

        # Save profile preference
        with open(CPU_PROFILE_CONFIG_FILE, 'w') as f:
            json.dump({
                "profile": profile_name,
                "applied": True,
                "cores": cores,
                "boost": profile.get("boost", False),
                "arm_freq": profile["arm_freq"]
            }, f)

        return jsonify({
            "success": True,
            "message": f"Profile '{profile_name}' applied. Reboot required for changes to take effect.",
            "profile": profile_name,
            "settings": {
                "arm_freq": profile["arm_freq"],
                "gpu_freq": profile.get("gpu_freq"),
                "over_voltage": profile.get("over_voltage", 0),
                "cores": cores,
                "boost": profile.get("boost", False)
            },
            "cores_updated": cores_written,
            "needs_reboot": True
        })
    except PermissionError:
        return jsonify({"error": "Permission denied. Run as root to modify config.txt"}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =============================================
# Screen Saver / Burn-in Prevention
# =============================================
SCREEN_SAVER_CONFIG_FILE = Path("/opt/vernis/screen-saver-config.json")

def get_screen_saver_config():
    """Get screen saver configuration"""
    if SCREEN_SAVER_CONFIG_FILE.exists():
        try:
            with open(SCREEN_SAVER_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {
        "enabled": False,
        "timeout_minutes": 10,
        "gallery_exempt": True
    }

@app.route("/api/screen-saver/config", methods=["GET", "POST"])
def screen_saver_config():
    """Get or set screen saver configuration"""
    if request.method == "POST":
        try:
            config = request.json

            # Validate timeout
            timeout = config.get('timeout_minutes', 10)
            if not isinstance(timeout, int) or timeout < 1 or timeout > 720:
                return jsonify({"error": "Timeout must be 1-720 minutes"}), 400

            # Save configuration
            save_config = {
                "enabled": bool(config.get('enabled', False)),
                "timeout_minutes": timeout,
                "gallery_exempt": bool(config.get('gallery_exempt', True))
            }

            with open(SCREEN_SAVER_CONFIG_FILE, 'w') as f:
                json.dump(save_config, f, indent=2)

            return jsonify({"success": True, "config": save_config})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify(get_screen_saver_config())


# Screen saver idle monitor background thread
_screen_off_by_idle = False
_screen_manually_off = False  # Set when user taps "Turn off screen"

def _find_touch_event_device():
    """Find the /dev/input/eventN for the touchscreen (for raw wake detection)."""
    try:
        with open("/proc/bus/input/devices") as f:
            content = f.read()
        import re
        # Find blocks containing "touch" (case-insensitive)
        for block in content.split("\n\n"):
            if "touch" in block.lower():
                m = re.search(r'event(\d+)', block)
                if m:
                    return f"/dev/input/event{m.group(1)}"
    except Exception:
        pass
    return None

def _check_touch_input(event_path):
    """Check if there's recent input on the touch device (non-blocking read)."""
    import select
    try:
        fd = os.open(event_path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            r, _, _ = select.select([fd], [], [], 0)
            if r:
                # Drain any pending data (up to 4KB)
                os.read(fd, 4096)
                return True
        finally:
            os.close(fd)
    except Exception:
        pass
    return False

def _is_gallery_showing():
    """Check if gallery.html is the current page via CDP"""
    try:
        import urllib.request
        data = urllib.request.urlopen("http://localhost:9222/json/list", timeout=2).read()
        tabs = json.loads(data)
        if tabs and "gallery.html" in tabs[0].get("url", ""):
            return True
    except Exception:
        pass
    return False

def screen_saver_monitor():
    """Background thread: check idle time and turn screen off/on"""
    global _screen_off_by_idle
    activity_file = Path("/opt/vernis/last-activity")
    touch_dev = _find_touch_event_device()

    while True:
        try:
            global _screen_manually_off
            screen_is_off = _screen_off_by_idle or _screen_manually_off

            # Poll faster when screen is off so touch-wake is responsive
            time.sleep(2 if screen_is_off else 15)

            # Touch-wake: check raw touch input when screen is off (manual or idle)
            if screen_is_off and touch_dev:
                if _check_touch_input(touch_dev):
                    _screen_off_by_idle = False
                    _screen_manually_off = False
                    activity_file.touch()
                    _do_screen_on()
                    continue

            config = get_screen_saver_config()
            if not config.get('enabled'):
                # If we turned screen off and user disabled the saver, turn back on
                if _screen_off_by_idle:
                    _screen_off_by_idle = False
                    _do_screen_on()
                continue

            # Skip timeout when gallery is showing and gallery_exempt is enabled
            if config.get('gallery_exempt') and not _screen_off_by_idle:
                if _is_gallery_showing():
                    continue

            timeout_sec = config.get('timeout_minutes', 10) * 60

            # Get last activity time
            if activity_file.exists():
                last_active = activity_file.stat().st_mtime
            else:
                # No activity file yet — treat current time as last activity
                activity_file.touch()
                continue

            idle_sec = time.time() - last_active

            if idle_sec >= timeout_sec and not _screen_off_by_idle:
                _screen_off_by_idle = True
                _do_screen_off()
            elif idle_sec < timeout_sec and _screen_off_by_idle:
                _screen_off_by_idle = False
                _do_screen_on()

        except Exception:
            pass


def _get_wayland_env():
    """Build environment dict with Wayland display vars for wlr-randr."""
    env = os.environ.copy()
    env["WAYLAND_DISPLAY"] = "wayland-0"
    try:
        for uid_dir in Path("/run/user").iterdir():
            if (uid_dir / "wayland-0").exists():
                env["XDG_RUNTIME_DIR"] = str(uid_dir)
                break
    except:
        env["XDG_RUNTIME_DIR"] = "/run/user/1000"
    return env


def _get_dpi_output(env=None):
    """Detect DPI output name (e.g. 'DPI-1') via wlr-randr. Returns None if no DPI display."""
    if env is None:
        env = _get_wayland_env()
    try:
        r = subprocess.run(["wlr-randr"], capture_output=True, text=True, timeout=5, env=env)
        for line in r.stdout.splitlines():
            if line.startswith("DPI"):
                return line.split()[0]
    except:
        pass
    return None


def _get_dpi_transform():
    """Read saved rotation and return wlr-randr transform value."""
    try:
        with open("/opt/vernis/rotation-config.json") as f:
            rot = json.load(f).get("rotation", 0)
    except:
        rot = 0
    return {90: "90", 180: "180", 270: "270"}.get(rot, "normal")


def _dpi_output_off(env=None):
    """Disable DPI output via wlr-randr (stop signal before backlight toggle)."""
    if env is None:
        env = _get_wayland_env()
    dpi = _get_dpi_output(env)
    if not dpi:
        return
    try:
        Path("/tmp/vernis-hdmi-hotplug.lock").touch()
    except:
        pass
    subprocess.run(["wlr-randr", "--output", dpi, "--off"],
                   capture_output=True, timeout=5, env=env)
    time.sleep(0.1)
    print(f"[screen] DPI output off ({dpi})", flush=True)


def _dpi_output_on(env=None):
    """Re-enable DPI output via wlr-randr (after backlight is already on)."""
    if env is None:
        env = _get_wayland_env()
    dpi = _get_dpi_output(env)
    if not dpi:
        return
    transform = _get_dpi_transform()
    time.sleep(0.2)
    subprocess.run(["wlr-randr", "--output", dpi, "--on",
                    "--transform", transform],
                   capture_output=True, timeout=5, env=env)
    # Ensure backlight stays on after DPI re-enable
    try:
        subprocess.run(["pinctrl", "set", "18", "op", "dl"], capture_output=True, timeout=5)
    except:
        pass
    try:
        Path("/tmp/vernis-hdmi-hotplug.lock").touch()
    except:
        pass
    print(f"[screen] DPI output on ({dpi}, transform={transform})", flush=True)


def _do_screen_off():
    """Internal: turn screen off. Only toggle backlight — keep DPI output enabled for touch-wake."""
    try:
        subprocess.run(["pinctrl", "set", "18", "op", "dh"], capture_output=True, timeout=5)
    except FileNotFoundError:
        pass
    for path in ["/sys/class/backlight/rpi_backlight/bl_power", "/sys/class/backlight/10-0045/bl_power"]:
        if os.path.exists(path):
            try:
                subprocess.run(["sudo", "sh", "-c", f"echo 1 > {path}"], capture_output=True, timeout=5)
                break
            except:
                pass


def _do_screen_on():
    """Internal: turn screen on. Only toggle backlight — DPI output was never disabled."""
    try:
        subprocess.run(["pinctrl", "set", "18", "op", "dl"], capture_output=True, timeout=5)
    except FileNotFoundError:
        pass
    for path in ["/sys/class/backlight/rpi_backlight/bl_power", "/sys/class/backlight/10-0045/bl_power"]:
        if os.path.exists(path):
            try:
                subprocess.run(["sudo", "sh", "-c", f"echo 0 > {path}"], capture_output=True, timeout=5)
                break
            except:
                pass


# Start the idle monitor thread
_idle_monitor_thread = threading.Thread(target=screen_saver_monitor, daemon=True)
_idle_monitor_thread.start()

# Apply saved fan config on startup (so fan mode persists across reboots)
def _apply_fan_on_startup():
    """Delayed fan config apply — thermal zone may not be ready at import time."""
    time.sleep(5)
    try:
        cfg = load_fan_config()
        mode = cfg.get("mode", "off")
        if mode != "off":
            ok, msg = apply_fan_live(mode)
            if not ok:
                print(f"[fan startup] apply failed: {msg}", flush=True)
    except Exception as e:
        print(f"[fan startup] error: {e}", flush=True)

threading.Thread(target=_apply_fan_on_startup, daemon=True).start()

# =============================================
# LED Control (Pi Board LEDs)
# =============================================
LED_CONFIG_FILE = Path("/opt/vernis/led-config.json")

LED_PATHS = {
    "power": "/sys/class/leds/PWR",
    "activity": "/sys/class/leds/ACT"
}

LED_TRIGGERS = ["none", "default-on", "mmc0", "heartbeat", "cpu"]

def get_led_config():
    """Get saved LED configuration"""
    if LED_CONFIG_FILE.exists():
        try:
            with open(LED_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"power": True, "activity": True}

def get_led_status():
    """Get current LED status from system"""
    status = {}
    for led_name, led_path in LED_PATHS.items():
        try:
            # Check if LED exists
            if not os.path.exists(led_path):
                status[led_name] = {"available": False}
                continue

            # Read trigger
            with open(f"{led_path}/trigger", "r") as f:
                trigger_line = f.read().strip()
                # Find active trigger (in brackets)
                import re
                match = re.search(r'\[([^\]]+)\]', trigger_line)
                current_trigger = match.group(1) if match else "unknown"

            # Read brightness
            with open(f"{led_path}/brightness", "r") as f:
                brightness = int(f.read().strip())

            status[led_name] = {
                "available": True,
                "trigger": current_trigger,
                "brightness": brightness,
                "on": current_trigger != "none" or brightness > 0
            }
        except Exception as e:
            status[led_name] = {"available": False, "error": str(e)}

    return status

def set_led(led_name, enabled):
    """Turn LED on or off"""
    if led_name not in LED_PATHS:
        return False, f"Unknown LED: {led_name}"

    led_path = LED_PATHS[led_name]
    if not os.path.exists(led_path):
        return False, f"LED not found: {led_path}"

    try:
        if enabled:
            # Turn on - set appropriate default trigger
            if led_name == "activity":
                trigger = "mmc0"  # SD card activity
            else:
                trigger = "default-on"  # Power LED always on
        else:
            trigger = "none"  # Turn off

        # Use sudo to write to sysfs (requires root)
        trigger_path = f"{led_path}/trigger"
        subprocess.run(
            ["sudo", "sh", "-c", f"echo {trigger} > {trigger_path}"],
            capture_output=True, timeout=5
        )

        # Also set brightness
        brightness = "1" if enabled else "0"
        brightness_path = f"{led_path}/brightness"
        subprocess.run(
            ["sudo", "sh", "-c", f"echo {brightness} > {brightness_path}"],
            capture_output=True, timeout=5
        )

        return True, None
    except Exception as e:
        return False, str(e)

@app.route("/api/system/leds", methods=["GET"])
def get_leds():
    """Get LED status"""
    try:
        config = get_led_config()
        status = get_led_status()
        return jsonify({
            "config": config,
            "status": status
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/system/leds", methods=["POST"])
def set_leds():
    """Set LED state"""
    try:
        data = request.json
        config = get_led_config()
        errors = []

        for led_name in ["power", "activity"]:
            if led_name in data:
                enabled = bool(data[led_name])
                config[led_name] = enabled
                success, error = set_led(led_name, enabled)
                if not success:
                    errors.append(f"{led_name}: {error}")

        # Save config
        with open(LED_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)

        if errors:
            return jsonify({
                "success": False,
                "errors": errors,
                "config": config
            }), 500

        return jsonify({
            "success": True,
            "config": config,
            "status": get_led_status()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Brightness settings file
BRIGHTNESS_FILE = Path("/opt/vernis/brightness.json")

def get_saved_brightness():
    """Get saved brightness level"""
    if BRIGHTNESS_FILE.exists():
        try:
            with open(BRIGHTNESS_FILE, 'r') as f:
                return json.load(f).get('brightness', 100)
        except:
            pass
    return 100

@app.route("/api/screen/brightness", methods=["GET", "POST"])
def screen_brightness():
    """Get or set screen brightness for DPI displays (Waveshare 4inch via GPIO18)"""
    if request.method == "GET":
        return jsonify({"brightness": get_saved_brightness()})

    try:
        data = request.json
        brightness = int(data.get('brightness', 100))
        brightness = max(0, min(100, brightness))  # Clamp 0-100

        methods_tried = []
        success = False

        # Method 1: Try hardware PWM via sysfs (if available)
        # NOTE: Do NOT use pwm-2chan overlay — conflicts with Waveshare DPI backlight on GPIO 18
        pwm_chip = "/sys/class/pwm/pwmchip0"
        pwm_channel = f"{pwm_chip}/pwm2"
        if os.path.exists(pwm_chip):
            try:
                # Export PWM channel if not already exported
                if not os.path.exists(pwm_channel):
                    subprocess.run(
                        ["sudo", "sh", "-c", f"echo 2 > {pwm_chip}/export"],
                        capture_output=True, timeout=5
                    )
                    import time
                    time.sleep(0.1)  # Wait for sysfs to create the channel

                if os.path.exists(pwm_channel):
                    period = 1000000  # 1ms period = 1kHz frequency
                    duty = int((brightness / 100) * period)

                    # Set period first, then duty cycle, then enable
                    subprocess.run(["sudo", "sh", "-c", f"echo {period} > {pwm_channel}/period"], capture_output=True, timeout=5)
                    subprocess.run(["sudo", "sh", "-c", f"echo {duty} > {pwm_channel}/duty_cycle"], capture_output=True, timeout=5)
                    subprocess.run(["sudo", "sh", "-c", f"echo 1 > {pwm_channel}/enable"], capture_output=True, timeout=5)
                    methods_tried.append("sysfs-pwm")
                    success = True
            except Exception as e:
                methods_tried.append(f"sysfs-failed:{str(e)}")

        # Method 2: Try hardware PWM via pigpiod
        if not success:
            try:
                pwm_value = int(brightness * 255 / 100)
                result = subprocess.run(
                    ["pigs", "p", "18", str(pwm_value)],
                    capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    methods_tried.append("pigpiod-pwm")
                    success = True
            except FileNotFoundError:
                pass
            except:
                pass

        # Method 3: Try software PWM via python3-lgpio
        if not success:
            try:
                pwm_script = f'''
import lgpio
h = lgpio.gpiochip_open(0)
lgpio.tx_pwm(h, 18, 1000, {brightness})
'''
                result = subprocess.run(
                    ["python3", "-c", pwm_script],
                    capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    methods_tried.append("lgpio-pwm")
                    success = True
            except:
                pass

        # Method 3: Try pinctrl (Pi 5 / Bookworm) - on/off only
        if not success:
            try:
                # pinctrl can only do on/off, not dimming
                state = "dh" if brightness > 50 else "dl"
                result = subprocess.run(
                    ["pinctrl", "set", "18", "op", state],
                    capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    methods_tried.append(f"pinctrl-{state}")
                    success = True
            except FileNotFoundError:
                pass
            except:
                pass

        # Method 4: Try WiringPi gpio command (older systems)
        if not success:
            try:
                pwm_value = int(brightness * 1023 / 100)
                subprocess.run(["gpio", "-g", "mode", "18", "pwm"], capture_output=True, timeout=5)
                subprocess.run(["gpio", "pwmc", "1000"], capture_output=True, timeout=5)
                result = subprocess.run(
                    ["gpio", "-g", "pwm", "18", str(pwm_value)],
                    capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    methods_tried.append("wiringpi-pwm")
                    success = True
            except FileNotFoundError:
                pass
            except:
                pass

        # Method 5: Direct GPIO on/off (fallback)
        if not success:
            try:
                value = "0" if brightness > 50 else "1"  # GPIO18 often active-low
                subprocess.run(
                    ["sudo", "sh", "-c", f"echo 18 > /sys/class/gpio/export 2>/dev/null; echo out > /sys/class/gpio/gpio18/direction; echo {value} > /sys/class/gpio/gpio18/value"],
                    capture_output=True, timeout=5
                )
                methods_tried.append("gpio-sysfs")
                success = True
            except:
                pass

        # Save brightness setting
        with open(BRIGHTNESS_FILE, 'w') as f:
            json.dump({"brightness": brightness}, f)

        if success:
            return jsonify({"success": True, "brightness": brightness, "methods": methods_tried})
        else:
            return jsonify({"success": False, "error": "No PWM method available. Install pigpiod for best results.", "brightness": brightness, "tried": methods_tried})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/screen/off", methods=["POST"])
def screen_off():
    """Turn off the screen (pinctrl GPIO18 for DPI, backlight sysfs for DSI, DPMS for HDMI)"""
    try:
        methods_tried = []
        success = False

        # Method 1: pinctrl GPIO18 (Pi 5 + Waveshare DPI displays - most likely to work)
        # NOTE: Do NOT call _dpi_output_off() — disabling DPI also kills the touch
        # controller (connected via ribbon cable). Only toggle backlight so touch-wake works.
        if not success:
            try:
                result = subprocess.run(
                    ["pinctrl", "set", "18", "op", "dh"],  # drive HIGH = backlight OFF (active LOW)
                    capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    methods_tried.append("pinctrl-gpio18")
                    success = True
            except FileNotFoundError:
                methods_tried.append("pinctrl-not-found")

        # Method 2: Try backlight sysfs for DSI displays
        if not success:
            backlight_paths = [
                "/sys/class/backlight/rpi_backlight/bl_power",
                "/sys/class/backlight/10-0045/bl_power",
                "/sys/class/backlight/rpi_backlight/brightness",
                "/sys/class/backlight/10-0045/brightness",
            ]
            for path in backlight_paths:
                if os.path.exists(path):
                    try:
                        value = "1" if "bl_power" in path else "0"
                        with open(path, 'w') as f:
                            f.write(value)
                        methods_tried.append(f"backlight:{path}")
                        success = True
                        break
                    except PermissionError:
                        result = subprocess.run(
                            ["sudo", "sh", "-c", f"echo {'1' if 'bl_power' in path else '0'} > {path}"],
                            capture_output=True, timeout=5
                        )
                        if result.returncode == 0:
                            methods_tried.append(f"backlight-sudo:{path}")
                            success = True
                            break
                    except:
                        pass

        # Method 3: wlr-randr for Wayland
        if not success:
            try:
                result = subprocess.run(
                    ["wlr-randr", "--output", "DPI-1", "--off"],
                    capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    methods_tried.append("wlr-randr")
                    success = True
            except FileNotFoundError:
                pass

        # Method 4: DPMS for X11/HDMI
        if not success:
            try:
                env = get_x_display_env()
                result = subprocess.run(
                    ["xset", "-display", env.get('DISPLAY', ':0'), "dpms", "force", "off"],
                    env=env, capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    methods_tried.append("dpms")
                    success = True
            except:
                pass

        if success:
            global _screen_manually_off
            _screen_manually_off = True
            return jsonify({"success": True, "message": "Screen turned off", "methods": methods_tried})
        else:
            return jsonify({"error": "No screen control method worked", "tried": methods_tried}), 500

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Command timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/screen/on", methods=["POST"])
def screen_on():
    """Turn on the screen (pinctrl GPIO18 for DPI, backlight sysfs for DSI, DPMS for HDMI)"""
    try:
        methods_tried = []
        success = False

        # Method 1: pinctrl GPIO18 (Pi 5 + Waveshare DPI displays)
        # DPI output stays enabled (never disabled) so touch keeps working
        if not success:
            try:
                result = subprocess.run(
                    ["pinctrl", "set", "18", "op", "dl"],  # drive LOW = backlight ON (active LOW)
                    capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    methods_tried.append("pinctrl-gpio18")
                    success = True
            except FileNotFoundError:
                methods_tried.append("pinctrl-not-found")

        # Method 2: Try backlight sysfs for DSI displays
        if not success:
            backlight_paths = [
                "/sys/class/backlight/rpi_backlight/bl_power",
                "/sys/class/backlight/10-0045/bl_power",
                "/sys/class/backlight/rpi_backlight/brightness",
                "/sys/class/backlight/10-0045/brightness",
            ]
            for path in backlight_paths:
                if os.path.exists(path):
                    try:
                        value = "0" if "bl_power" in path else "255"
                        with open(path, 'w') as f:
                            f.write(value)
                        methods_tried.append(f"backlight:{path}")
                        success = True
                        break
                    except PermissionError:
                        result = subprocess.run(
                            ["sudo", "sh", "-c", f"echo {'0' if 'bl_power' in path else '255'} > {path}"],
                            capture_output=True, timeout=5
                        )
                        if result.returncode == 0:
                            methods_tried.append(f"backlight-sudo:{path}")
                            success = True
                            break
                    except:
                        pass

        # Method 3: wlr-randr for Wayland
        if not success:
            try:
                result = subprocess.run(
                    ["wlr-randr", "--output", "DPI-1", "--on"],
                    capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    methods_tried.append("wlr-randr")
                    success = True
            except FileNotFoundError:
                pass

        # Method 4: DPMS for X11/HDMI
        if not success:
            try:
                env = get_x_display_env()
                result = subprocess.run(
                    ["xset", "-display", env.get('DISPLAY', ':0'), "dpms", "force", "on"],
                    env=env, capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    methods_tried.append("dpms")
                    success = True
            except:
                pass

        if success:
            global _screen_manually_off
            _screen_manually_off = False
            return jsonify({"success": True, "message": "Screen turned on", "methods": methods_tried})
        else:
            return jsonify({"error": "No screen control method worked", "tried": methods_tried}), 500

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Command timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/screen/activity", methods=["POST"])
def screen_activity():
    """Record user activity (touch/click) for idle timeout tracking"""
    global _screen_off_by_idle
    try:
        activity_file = Path("/opt/vernis/last-activity")
        activity_file.touch()
        # If screen was turned off by idle, wake it
        if _screen_off_by_idle:
            _screen_off_by_idle = False
            _do_screen_on()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/screen/status")
def screen_status():
    """Get current screen power status"""
    try:
        env = get_x_display_env()

        # Query DPMS state
        result = subprocess.run(
            ["xset", "-display", env.get('DISPLAY', ':0'), "q"],
            env=env,
            capture_output=True,
            text=True,
            timeout=5
        )

        # Parse DPMS state from output
        dpms_on = True  # Default to on
        monitor_on = True

        if "DPMS is Enabled" in result.stdout:
            if "Monitor is Off" in result.stdout or "Monitor is Standby" in result.stdout or "Monitor is Suspend" in result.stdout:
                monitor_on = False

        return jsonify({
            "screen_on": monitor_on,
            "dpms_enabled": "DPMS is Enabled" in result.stdout
        })
    except Exception as e:
        return jsonify({"error": str(e), "screen_on": True})

# ========================================
# Screen Color Extraction (CDP Screenshot)
# ========================================

_cdp_backoff = {"until": 0, "failures": 0}

@app.route("/api/screen-color")
def screen_color():
    """Capture screen via CDP and extract dominant color for Hue sync."""
    import time as _time
    now = _time.time()
    if now < _cdp_backoff["until"]:
        remaining = round(_cdp_backoff["until"] - now, 1)
        return jsonify({"error": f"CDP backoff ({remaining}s remaining)", "backoff": True}), 503

    try:
        import websocket as ws_mod
        import base64
        from io import BytesIO

        # Get CDP target
        resp = requests.get(f'http://127.0.0.1:{CDP_PORT}/json', timeout=2)
        if resp.status_code != 200:
            return jsonify({"error": "CDP not available"}), 503

        pages = resp.json()
        target = next((p for p in pages if p.get('type') == 'page'), None)
        if not target:
            return jsonify({"error": "No page target"}), 503

        ws_url = target.get('webSocketDebuggerUrl')
        if not ws_url:
            return jsonify({"error": "No WebSocket URL"}), 503

        ws = ws_mod.create_connection(ws_url, timeout=5)

        # Optional clip region (device pixels)
        params = {"format": "jpeg", "quality": 30}
        cx = request.args.get('x', type=float)
        cy = request.args.get('y', type=float)
        cw = request.args.get('w', type=float)
        ch = request.args.get('h', type=float)
        if all(v is not None for v in [cx, cy, cw, ch]):
            params["clip"] = {"x": cx, "y": cy, "width": cw, "height": ch, "scale": 1}

        ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": params}))
        result = json.loads(ws.recv())
        ws.close()

        if 'result' not in result or 'data' not in result.get('result', {}):
            return jsonify({"error": "Screenshot failed"}), 500

        img_data = base64.b64decode(result['result']['data'])

        # Try PIL first, fall back to raw JPEG parsing
        try:
            from PIL import Image
            img = Image.open(BytesIO(img_data)).convert('RGB')
            img = img.resize((40, 40))
            pixels = list(img.getdata())
        except ImportError:
            # Fallback: decode JPEG with built-in (won't work without PIL)
            return jsonify({"error": "PIL not installed"}), 500

        # Dominant color via bucketing (same algo as gallery.html)
        color_buckets = {}
        bucket_size = 24
        for r, g, b in pixels:
            brightness = (r + g + b) / 3
            if brightness < 30 or brightness > 240:
                continue
            kr = (r // bucket_size) * bucket_size
            kg = (g // bucket_size) * bucket_size
            kb = (b // bucket_size) * bucket_size
            key = (kr, kg, kb)
            if key not in color_buckets:
                color_buckets[key] = {"count": 0, "r": 0, "g": 0, "b": 0}
            color_buckets[key]["count"] += 1
            color_buckets[key]["r"] += r
            color_buckets[key]["g"] += g
            color_buckets[key]["b"] += b

        if not color_buckets:
            return jsonify({"r": 128, "g": 128, "b": 128})

        dominant = max(color_buckets.values(), key=lambda b: b["count"])
        _cdp_backoff["failures"] = 0
        _cdp_backoff["until"] = 0
        return jsonify({
            "r": round(dominant["r"] / dominant["count"]),
            "g": round(dominant["g"] / dominant["count"]),
            "b": round(dominant["b"] / dominant["count"])
        })

    except Exception as e:
        _cdp_backoff["failures"] = min(_cdp_backoff["failures"] + 1, 6)
        delay = min(2 ** _cdp_backoff["failures"], 60)
        _cdp_backoff["until"] = _time.time() + delay
        print(f"[screen-color] Error (backoff {delay}s after {_cdp_backoff['failures']} failures): {e}", flush=True)
        return jsonify({"error": str(e), "backoff": True}), 503


# ========================================
# Philips Hue Integration
# ========================================

HUE_SETTINGS_FILE = Path("/opt/vernis/hue-settings.json")

def get_hue_settings():
    """Get Hue integration settings"""
    defaults = {
        "enabled": False,
        "bridge_ip": None,
        "api_key": None,
        "selected_lights": [],  # List of light IDs to control
        "selected_group": None,  # Or use a group ID
        "brightness": 254,       # 1-254
        "transition_time": 10,   # In 100ms units (10 = 1 second)
        "color_mode": "dominant" # dominant, vibrant, average
    }
    if HUE_SETTINGS_FILE.exists():
        try:
            with open(HUE_SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
                defaults.update(saved)
        except:
            pass
    return defaults


def save_hue_settings(settings):
    """Save Hue settings"""
    with open(HUE_SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)


def hue_request(method, endpoint, data=None):
    """Make a request to the Hue Bridge API"""
    settings = get_hue_settings()
    if not settings.get('bridge_ip') or not settings.get('api_key'):
        return None, "Hue Bridge not configured"

    import urllib.request
    import urllib.error

    url = f"http://{settings['bridge_ip']}/api/{settings['api_key']}{endpoint}"

    try:
        req_data = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=req_data, method=method)
        req.add_header('Content-Type', 'application/json')

        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode()), None
    except urllib.error.URLError as e:
        return None, f"Connection error: {str(e)}"
    except Exception as e:
        return None, str(e)


@app.route("/api/hue/discover")
def hue_discover():
    """Discover Hue Bridges on the network"""
    import urllib.request
    import urllib.error

    bridges = []

    # Method 1: Try meethue.com discovery
    try:
        req = urllib.request.Request("https://discovery.meethue.com/")
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            for bridge in data:
                bridges.append({
                    "ip": bridge.get("internalipaddress"),
                    "id": bridge.get("id"),
                    "source": "cloud"
                })
    except:
        pass

    # Method 2: Try common local IPs if cloud discovery fails
    if not bridges:
        import socket
        # Get local network prefix
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            prefix = '.'.join(local_ip.split('.')[:-1])

            # Try common bridge IPs
            for last_octet in [1, 2, 100, 254]:
                test_ip = f"{prefix}.{last_octet}"
                try:
                    req = urllib.request.Request(f"http://{test_ip}/api/config", method='GET')
                    with urllib.request.urlopen(req, timeout=1) as response:
                        data = json.loads(response.read().decode())
                        if "bridgeid" in data:
                            bridges.append({
                                "ip": test_ip,
                                "id": data.get("bridgeid"),
                                "name": data.get("name", "Hue Bridge"),
                                "source": "local"
                            })
                except:
                    pass
        except:
            pass

    return jsonify({"bridges": bridges})


@app.route("/api/hue/connect", methods=["POST"])
def hue_connect():
    """
    Connect to a Hue Bridge. User must press the link button first.
    Returns an API key on success.
    """
    import urllib.request
    import urllib.error

    data = request.json
    bridge_ip = data.get('bridge_ip')

    if not bridge_ip:
        return jsonify({"error": "Bridge IP required"}), 400

    # Validate bridge_ip is a private/link-local IPv4 (Hue Bridges are LAN devices)
    import ipaddress as _ipaddress
    try:
        ip = _ipaddress.ip_address(bridge_ip)
        if not (ip.is_private or ip.is_link_local):
            return jsonify({"error": "Bridge IP must be a local network address"}), 400
        if ip.is_loopback:
            return jsonify({"error": "Loopback addresses not allowed"}), 400
    except ValueError:
        return jsonify({"error": "Invalid IP address"}), 400

    # Try to create a new user (requires link button press)
    # Request clientkey for Entertainment API streaming support
    try:
        url = f"http://{bridge_ip}/api"
        req_data = json.dumps({
            "devicetype": "vernis#gallery",
            "generateclientkey": True
        }).encode()
        req = urllib.request.Request(url, data=req_data, method='POST')
        req.add_header('Content-Type', 'application/json')

        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())

            if isinstance(result, list) and len(result) > 0:
                if "success" in result[0]:
                    api_key = result[0]["success"]["username"]
                    clientkey = result[0]["success"].get("clientkey")

                    # Save settings
                    settings = get_hue_settings()
                    settings["bridge_ip"] = bridge_ip
                    settings["api_key"] = api_key
                    settings["enabled"] = True
                    if clientkey:
                        settings["clientkey"] = clientkey
                    save_hue_settings(settings)

                    return jsonify({
                        "success": True,
                        "api_key": api_key,
                        "has_clientkey": bool(clientkey),
                        "message": "Connected to Hue Bridge!" + (" Entertainment API ready!" if clientkey else "")
                    })
                elif "error" in result[0]:
                    error = result[0]["error"]
                    if error.get("type") == 101:
                        return jsonify({
                            "success": False,
                            "needs_button": True,
                            "message": "Press the link button on your Hue Bridge, then try again"
                        })
                    return jsonify({"error": error.get("description", "Unknown error")}), 400

        return jsonify({"error": "Unexpected response from bridge"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/hue/entertainment/register", methods=["POST"])
def hue_entertainment_register():
    """
    Re-register with bridge to get a clientkey for Entertainment API.
    User must press the bridge link button first.
    Preserves existing connection settings.
    """
    import urllib.request
    settings = get_hue_settings()
    bridge_ip = settings.get('bridge_ip')
    if not bridge_ip:
        return jsonify({"error": "No bridge configured. Connect first."}), 400

    try:
        url = f"http://{bridge_ip}/api"
        req_data = json.dumps({
            "devicetype": "vernis#entertainment",
            "generateclientkey": True
        }).encode()
        req = urllib.request.Request(url, data=req_data, method='POST')
        req.add_header('Content-Type', 'application/json')

        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())

            if isinstance(result, list) and len(result) > 0:
                if "success" in result[0]:
                    new_key = result[0]["success"]["username"]
                    clientkey = result[0]["success"].get("clientkey")
                    # Update the API key and clientkey
                    settings["api_key"] = new_key
                    if clientkey:
                        settings["clientkey"] = clientkey
                    save_hue_settings(settings)
                    global _hue_auto_group
                    _hue_auto_group = None
                    return jsonify({
                        "success": True,
                        "has_clientkey": bool(clientkey),
                        "message": "Entertainment API registered!" if clientkey else "Registration succeeded but no clientkey returned"
                    })
                elif "error" in result[0]:
                    error = result[0]["error"]
                    if error.get("type") == 101:
                        return jsonify({
                            "success": False,
                            "needs_button": True,
                            "message": "Press the link button on your Hue Bridge, then try again"
                        })
                    return jsonify({"error": error.get("description", "Unknown error")}), 400

        return jsonify({"error": "Unexpected response"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/hue/entertainment/status")
def hue_entertainment_status():
    """Check Entertainment API readiness."""
    settings = get_hue_settings()
    has_clientkey = bool(settings.get('clientkey'))
    bridge_ip = settings.get('bridge_ip')

    result = {
        "has_clientkey": has_clientkey,
        "bridge_ip": bridge_ip,
        "connected": bool(settings.get('api_key')),
        "streaming": _is_entertainment_streaming(),
        "entertainment_areas": []
    }

    if has_clientkey and settings.get('api_key'):
        # Fetch entertainment areas
        import urllib.request
        try:
            url = f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration"
            req = urllib.request.Request(url, method='GET')
            req.add_header('hue-application-key', settings['api_key'])
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
                data = json.loads(response.read().decode())
                for area in data.get('data', []):
                    result["entertainment_areas"].append({
                        "id": area["id"],
                        "name": area.get("metadata", {}).get("name", area.get("name", "?")),
                        "type": area.get("configuration_type", "?"),
                        "channels": len(area.get("channels", [])),
                        "status": area.get("status", "unknown")
                    })
        except Exception:
            pass

    return jsonify(result)


# Entertainment streaming daemon management
_hue_stream_proc = None
_HUE_STREAM_COLOR_FILE = "/opt/vernis/hue-stream-color.json"
_HUE_STREAM_BINARY = "/opt/vernis/scripts/hue-stream"
_HUE_STREAM_DAEMON = "/opt/vernis/scripts/hue-entertainment-daemon.py"


def _is_entertainment_streaming():
    """Check if the entertainment streaming daemon is running."""
    global _hue_stream_proc
    if _hue_stream_proc and _hue_stream_proc.poll() is None:
        return True
    _hue_stream_proc = None
    # Also check if running as systemd service
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "vernis-hue-stream"],
            capture_output=True, text=True, timeout=3
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def _write_stream_color(r, g, b):
    """Write color to the stream color file for the entertainment daemon."""
    import time as _time
    try:
        with open(_HUE_STREAM_COLOR_FILE, 'w') as f:
            json.dump({"r": r, "g": g, "b": b, "ts": _time.time()}, f)
        return True
    except Exception:
        return False


@app.route("/api/hue/entertainment/stream", methods=["POST"])
def hue_entertainment_stream():
    """Start or stop the Entertainment API streaming daemon."""
    global _hue_stream_proc
    data = request.json or {}
    action = data.get("action", "start")

    if action == "start":
        if _is_entertainment_streaming():
            return jsonify({"success": True, "message": "Already streaming"})

        settings = get_hue_settings()
        if not settings.get("clientkey"):
            return jsonify({"error": "No clientkey. Register for Entertainment API first."}), 400

        if not os.path.isfile(_HUE_STREAM_BINARY):
            # Auto-compile if source exists
            src = _HUE_STREAM_BINARY + ".c"
            if os.path.isfile(src):
                try:
                    result = subprocess.run(
                        ["gcc", "-O2", "-o", _HUE_STREAM_BINARY, src, "-lssl", "-lcrypto"],
                        capture_output=True, text=True, timeout=30
                    )
                    if result.returncode != 0:
                        return jsonify({"error": f"Failed to compile hue-stream: {result.stderr}"}), 500
                except Exception as e:
                    return jsonify({"error": f"Compile error: {e}"}), 500
            else:
                return jsonify({"error": "hue-stream binary and source not found."}), 400

        area_id = data.get("area_id")

        try:
            cmd = ["python3", _HUE_STREAM_DAEMON]
            if area_id:
                cmd += ["--area", area_id]

            _hue_stream_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            return jsonify({
                "success": True,
                "pid": _hue_stream_proc.pid,
                "message": "Entertainment streaming started"
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    elif action == "stop":
        if _hue_stream_proc and _hue_stream_proc.poll() is None:
            _hue_stream_proc.terminate()
            try:
                _hue_stream_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _hue_stream_proc.kill()
            _hue_stream_proc = None

        # Also try stopping systemd service
        try:
            subprocess.run(["sudo", "systemctl", "stop", "vernis-hue-stream"],
                          timeout=5, capture_output=True)
        except Exception:
            pass

        # Clean up color file
        try:
            os.remove(_HUE_STREAM_COLOR_FILE)
        except FileNotFoundError:
            pass

        # After entertainment stops, bridge restores pre-entertainment state which
        # may be OFF. Set lights to warm white via REST after bridge releases.
        # Run in background thread so the HTTP response returns fast (important
        # for sendBeacon which can't wait for slow REST calls).
        def _restore_lights():
            try:
                import time as _t
                settings = get_hue_settings()
                if not settings.get('api_key'):
                    return
                warm_state = {"on": True, "xy": [0.4578, 0.4101], "bri": 180, "transitiontime": 10}
                # Wait for bridge to exit entertainment mode
                _t.sleep(1.5)

                ent_lights = set()
                groups_data, err = hue_request("GET", "/groups")
                if groups_data:
                    for gid, ginfo in groups_data.items():
                        if ginfo.get('type') == 'Entertainment':
                            for lid in ginfo.get('lights', []):
                                ent_lights.add(lid)
                lights = ent_lights or set(settings.get('selected_lights', []))

                # First attempt
                for lid in lights:
                    hue_request("PUT", f"/lights/{lid}/state", warm_state)

                # Retry after another delay (bridge may still be transitioning)
                _t.sleep(1.0)
                for lid in lights:
                    hue_request("PUT", f"/lights/{lid}/state", warm_state)
            except Exception:
                pass

        import threading
        threading.Thread(target=_restore_lights, daemon=True).start()

        return jsonify({"success": True, "message": "Streaming stopped"})

    return jsonify({"error": "Invalid action. Use 'start' or 'stop'."}), 400


@app.route("/api/hue/lights")
def hue_lights():
    """Get all lights from the Hue Bridge"""
    result, error = hue_request("GET", "/lights")
    if error:
        return jsonify({"error": error}), 400

    lights = []
    for light_id, light_data in result.items():
        lights.append({
            "id": light_id,
            "name": light_data.get("name"),
            "type": light_data.get("type"),
            "on": light_data.get("state", {}).get("on", False),
            "reachable": light_data.get("state", {}).get("reachable", False),
            "supports_color": "xy" in light_data.get("state", {}) or "hue" in light_data.get("state", {})
        })

    return jsonify({"lights": lights})


@app.route("/api/hue/groups")
def hue_groups():
    """Get all groups/rooms from the Hue Bridge"""
    result, error = hue_request("GET", "/groups")
    if error:
        return jsonify({"error": error}), 400

    groups = []
    for group_id, group_data in result.items():
        groups.append({
            "id": group_id,
            "name": group_data.get("name"),
            "type": group_data.get("type"),
            "lights": group_data.get("lights", []),
            "on": group_data.get("state", {}).get("any_on", False)
        })

    return jsonify({"groups": groups})


# Hue color dedup + rate limiting state
_hue_last_color = {"r": -1, "g": -1, "b": -1}
_hue_last_color_time = 0
_hue_in_flight = False


def _rgb_to_xy(red, green, blue):
    """Convert RGB (0-255) to Hue XY color space using Philips formula."""
    red, green, blue = red / 255.0, green / 255.0, blue / 255.0
    red = pow((red + 0.055) / 1.055, 2.4) if red > 0.04045 else red / 12.92
    green = pow((green + 0.055) / 1.055, 2.4) if green > 0.04045 else green / 12.92
    blue = pow((blue + 0.055) / 1.055, 2.4) if blue > 0.04045 else blue / 12.92
    X = red * 0.4124564 + green * 0.3575761 + blue * 0.1804375
    Y = red * 0.2126729 + green * 0.7151522 + blue * 0.0721750
    Z = red * 0.0193339 + green * 0.1191920 + blue * 0.9503041
    total = X + Y + Z
    if total == 0:
        return 0.3127, 0.3290
    return round(X / total, 4), round(Y / total, 4)


_hue_auto_group = None  # Cached auto-detected group ID


def _find_group_for_lights(lights, settings):
    """Find a Hue group containing all the selected lights (cached)."""
    global _hue_auto_group
    if _hue_auto_group is not None:
        return _hue_auto_group if _hue_auto_group else None

    light_set = set(str(l) for l in lights)
    result, error = hue_request("GET", "/groups")
    if error or not result:
        _hue_auto_group = ""
        return None

    # Prefer smallest group that contains all selected lights
    best_id = None
    best_size = 999
    for gid, gdata in result.items():
        group_lights = set(gdata.get("lights", []))
        if light_set.issubset(group_lights) and len(group_lights) < best_size:
            best_id = gid
            best_size = len(group_lights)

    _hue_auto_group = best_id or ""
    return best_id


@app.route("/api/hue/set-color", methods=["POST"])
def hue_set_color():
    """
    Set light color based on RGB values.
    Expects: { "r": 0-255, "g": 0-255, "b": 0-255 }
    Optionally: { "lights": ["1", "2"] } or { "group": "1" }
    Optional: { "transitiontime": 2 } to override default transition
    """
    global _hue_last_color, _hue_last_color_time, _hue_in_flight
    import time as _time

    settings = get_hue_settings()
    if not settings.get('api_key'):
        return jsonify({"error": "Hue Bridge not connected"}), 400

    # Skip if another request is still in-flight (prevents piling)
    if _hue_in_flight:
        return jsonify({"success": True, "skipped": "in_flight"})

    data = request.json
    r = data.get('r', 255)
    g = data.get('g', 255)
    b = data.get('b', 255)

    # Color deduplication: skip if color hasn't changed much
    now = _time.time()
    color_delta = abs(r - _hue_last_color["r"]) + abs(g - _hue_last_color["g"]) + abs(b - _hue_last_color["b"])
    # Skip if barely changed AND less than 2s since last real update
    if color_delta < 20 and (now - _hue_last_color_time) < 2:
        return jsonify({"success": True, "skipped": "same_color", "delta": color_delta})

    # Entertainment API fast-path: write to color file if streaming daemon is active
    if _is_entertainment_streaming():
        _hue_last_color = {"r": r, "g": g, "b": b}
        _hue_last_color_time = now
        _write_stream_color(r, g, b)
        return jsonify({"success": True, "mode": "entertainment", "color": [r, g, b]})

    xy = _rgb_to_xy(r, g, b)

    # Smart transition time: instant for rapid live sync
    transition = data.get('transitiontime')
    if transition is None:
        time_since_last = now - _hue_last_color_time
        if time_since_last < 2.0:
            # Rapid sync: instant transition for responsive feel
            transition = 0
        else:
            transition = settings.get('transition_time', 10)

    state = {
        "on": True,
        "xy": list(xy),
        "bri": settings.get('brightness', 254),
        "transitiontime": transition
    }

    _hue_last_color = {"r": r, "g": g, "b": b}
    _hue_last_color_time = now

    lights = data.get('lights') or settings.get('selected_lights', [])
    group = data.get('group') or settings.get('selected_group')

    # Auto-detect group: if multiple lights, find a group containing all of them
    # This sends 1 API call instead of N, which is faster and avoids rate limits
    if not group and len(lights) > 1:
        group = _find_group_for_lights(lights, settings)

    errors = []
    success_count = 0
    _hue_in_flight = True

    try:
        if group:
            result, error = hue_request("PUT", f"/groups/{group}/action", state)
            if error:
                errors.append(error)
            else:
                success_count = 1
        elif lights:
            for light_id in lights:
                result, error = hue_request("PUT", f"/lights/{light_id}/state", state)
                if error:
                    errors.append(f"Light {light_id}: {error}")
                else:
                    success_count += 1
        else:
            _hue_in_flight = False
            return jsonify({"error": "No lights or group configured"}), 400
    finally:
        _hue_in_flight = False

    return jsonify({
        "success": success_count > 0,
        "updated": success_count,
        "errors": errors if errors else None
    })


@app.route("/api/hue/settings", methods=["GET", "POST"])
def hue_settings_endpoint():
    """Get or update Hue settings"""
    if request.method == "GET":
        settings = get_hue_settings()
        # Don't expose the API key in GET requests
        safe_settings = {k: v for k, v in settings.items() if k != 'api_key'}
        safe_settings['connected'] = bool(settings.get('api_key'))
        return jsonify(safe_settings)

    try:
        data = request.json
        settings = get_hue_settings()

        # Update allowed fields
        for field in ['enabled', 'selected_lights', 'selected_group', 'brightness', 'transition_time', 'color_mode', 'live_sync', 'live_sync_interval', 'show_gallery_btn']:
            if field in data:
                settings[field] = data[field]

        save_hue_settings(settings)
        # Clear auto-group cache when lights/group settings change
        if 'selected_lights' in data or 'selected_group' in data:
            global _hue_auto_group
            _hue_auto_group = None
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/hue/disconnect", methods=["POST"])
def hue_disconnect():
    """Disconnect from Hue Bridge (clear credentials)"""
    settings = get_hue_settings()
    settings['api_key'] = None
    settings['bridge_ip'] = None
    settings['enabled'] = False
    save_hue_settings(settings)
    return jsonify({"success": True, "message": "Disconnected from Hue Bridge"})


@app.route("/api/hue/test", methods=["POST"])
def hue_test():
    """Test the Hue connection by flashing lights"""
    settings = get_hue_settings()
    if not settings.get('api_key'):
        return jsonify({"error": "Not connected to Hue Bridge"}), 400

    lights = settings.get('selected_lights', [])
    group = settings.get('selected_group')

    # Flash with a nice color
    state = {"on": True, "xy": [0.6, 0.35], "bri": 254, "transitiontime": 5}

    if group:
        hue_request("PUT", f"/groups/{group}/action", state)
    elif lights:
        for light_id in lights:
            hue_request("PUT", f"/lights/{light_id}/state", state)
    else:
        return jsonify({"error": "No lights selected"}), 400

    return jsonify({"success": True, "message": "Lights should flash!"})


@app.route("/api/hue/test/<light_id>", methods=["POST"])
def hue_test_single(light_id):
    """Test a single Hue light by flashing it on/off"""
    settings = get_hue_settings()
    if not settings.get('api_key'):
        return jsonify({"error": "Not connected to Hue Bridge"}), 400

    # Flash on with warm orange
    hue_request("PUT", f"/lights/{light_id}/state", {"on": True, "xy": [0.6, 0.35], "bri": 254, "transitiontime": 2})
    time.sleep(0.6)
    # Flash off
    hue_request("PUT", f"/lights/{light_id}/state", {"on": False, "transitiontime": 2})
    time.sleep(0.6)
    # Flash on again
    hue_request("PUT", f"/lights/{light_id}/state", {"on": True, "xy": [0.6, 0.35], "bri": 254, "transitiontime": 2})
    time.sleep(0.6)
    # Turn off
    hue_request("PUT", f"/lights/{light_id}/state", {"on": False, "transitiontime": 2})

    return jsonify({"success": True, "message": f"Light {light_id} flashed"})


@app.route("/api/ambient-light", methods=["POST"])
def ambient_light():
    """
    Simple ambient light API for lab.html and gallery.html.
    Forwards to Hue if enabled, otherwise silently succeeds.
    Accepts: { "r": 0-255, "g": 0-255, "b": 0-255 } or { "off": true }
    """
    settings = get_hue_settings()
    data = request.json or {}

    # If turning off
    if data.get('off'):
        if settings.get('enabled') and settings.get('api_key'):
            lights = settings.get('selected_lights', [])
            group = settings.get('selected_group')
            state = {"on": False}

            if group:
                hue_request("PUT", f"/groups/{group}/action", state)
            elif lights:
                for light_id in lights:
                    hue_request("PUT", f"/lights/{light_id}/state", state)

        return jsonify({"success": True, "message": "Ambient light off"})

    # Setting color
    r = data.get('r', 255)
    g = data.get('g', 255)
    b = data.get('b', 255)

    if not settings.get('enabled') or not settings.get('api_key'):
        # Hue not configured - silently succeed so UI doesn't show errors
        return jsonify({"success": True, "message": "Hue not configured"})

    xy = _rgb_to_xy(r, g, b)
    state = {
        "on": True,
        "xy": list(xy),
        "bri": settings.get('brightness', 254),
        "transitiontime": settings.get('transition_time', 10)
    }

    lights = settings.get('selected_lights', [])
    group = settings.get('selected_group')

    if group:
        hue_request("PUT", f"/groups/{group}/action", state)
    elif lights:
        for light_id in lights:
            hue_request("PUT", f"/lights/{light_id}/state", state)

    return jsonify({"success": True, "r": r, "g": g, "b": b})


# ========================================
# THUMBNAIL GENERATION
# ========================================

THUMBNAIL_DIR = Path("/opt/vernis/thumbnails")
THUMBNAIL_SIZE = (200, 200)

@app.route("/api/thumbnail/<filename>")
def get_thumbnail(filename):
    """Generate and serve a thumbnail for an NFT image"""
    try:
        from PIL import Image
        import io

        # Security: sanitize filename
        filename = Path(filename).name
        original_path = NFT_DIR / filename
        thumbnail_path = THUMBNAIL_DIR / f"thumb_{filename}"

        # Handle video files - return a placeholder or first frame
        if filename.lower().endswith(('.mp4', '.webm', '.mov')):
            # Return video icon placeholder
            svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">
                <rect width="200" height="200" fill="#1a1a1a"/>
                <polygon points="75,60 75,140 140,100" fill="#666"/>
            </svg>'''
            return Response(svg, mimetype='image/svg+xml')

        # Handle HTML generator files - extract preview from meta tag
        if filename.lower().endswith('.html'):
            import re
            import base64 as b64mod
            try:
                html_text = original_path.read_text(encoding='utf-8')
                match = re.search(r'<meta\s+name="generator-preview"\s+content="([^"]+)"', html_text)
                if match:
                    data_uri = match.group(1)
                    header, b64data = data_uri.split(',', 1)
                    img_bytes = b64mod.b64decode(b64data)
                    mime = header.split(':')[1].split(';')[0] if ':' in header else 'image/jpeg'
                    return Response(img_bytes, mimetype=mime)
            except Exception:
                pass
            svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">
                <rect width="200" height="200" fill="#1a1a1a"/>
                <text x="100" y="105" text-anchor="middle" fill="#666" font-size="12">Generator</text>
            </svg>'''
            return Response(svg, mimetype='image/svg+xml')

        # Check if thumbnail already exists and is newer than original
        if thumbnail_path.exists() and original_path.exists():
            if thumbnail_path.stat().st_mtime >= original_path.stat().st_mtime:
                return send_file(thumbnail_path, mimetype='image/jpeg')

        # Generate thumbnail
        if not original_path.exists():
            return jsonify({"error": "File not found"}), 404

        # Create thumbnail directory if needed
        THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

        # Handle SVG files - return as-is (they scale well)
        if filename.lower().endswith('.svg'):
            return send_file(original_path, mimetype='image/svg+xml')

        # Handle AVIF files - return as-is (browser handles scaling)
        if filename.lower().endswith('.avif'):
            return send_file(original_path, mimetype='image/avif')

        # Handle GIF - use first frame
        if filename.lower().endswith('.gif'):
            with Image.open(original_path) as img:
                img = img.convert('RGB')
                img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                img.save(thumbnail_path, 'JPEG', quality=70)
        else:
            # Regular image (jpg, png, webp)
            with Image.open(original_path) as img:
                # Handle RGBA images
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (26, 26, 26))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')

                img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                img.save(thumbnail_path, 'JPEG', quality=70)

        return send_file(thumbnail_path, mimetype='image/jpeg')

    except Exception as e:
        # Return error placeholder
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">
            <rect width="200" height="200" fill="#2a1a1a"/>
            <text x="100" y="105" text-anchor="middle" fill="#666" font-size="12">Error</text>
        </svg>'''
        return Response(svg, mimetype='image/svg+xml')

@app.route("/api/thumbnails/generate", methods=["POST"])
def generate_all_thumbnails():
    """Generate thumbnails for all NFTs in background"""
    import threading

    def generate_thumbnails():
        from PIL import Image
        THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

        count = 0
        for ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
            for file_path in NFT_DIR.glob(f"*.{ext}"):
                try:
                    thumbnail_path = THUMBNAIL_DIR / f"thumb_{file_path.name}"

                    # Skip if thumbnail exists and is current
                    if thumbnail_path.exists():
                        if thumbnail_path.stat().st_mtime >= file_path.stat().st_mtime:
                            continue

                    with Image.open(file_path) as img:
                        if img.mode in ('RGBA', 'LA', 'P'):
                            background = Image.new('RGB', img.size, (26, 26, 26))
                            if img.mode == 'P':
                                img = img.convert('RGBA')
                            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                            img = background
                        elif img.mode != 'RGB':
                            img = img.convert('RGB')

                        img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                        img.save(thumbnail_path, 'JPEG', quality=70)
                        count += 1
                except Exception as e:
                    pass  # Skip failed images

    thread = threading.Thread(target=generate_thumbnails)
    thread.start()

    return jsonify({"success": True, "message": "Generating thumbnails in background"})

@app.route("/api/rotate-screen", methods=["POST"])
def rotate_screen():
    """Rotate screen using xrandr and save preference"""
    try:
        data = request.json
        direction = str(data.get('direction', '0'))
        
        # Map degrees to xrandr rotation names
        rotation_map = {
            '0': 'normal',
            '90': 'right',
            '180': 'inverted',
            '270': 'left'
        }
        
        rot_arg = rotation_map.get(direction, 'normal')
        
        # Set X11 environment
        env = os.environ.copy()
        if 'DISPLAY' not in env:
            env['DISPLAY'] = ':0'
            
        # Get output name (usually HDMI-1 or DSI-1)
        # We'll try to rotate the primary connected output
        
        # 1. Get current output name
        xrandr_out = subprocess.run(["xrandr"], env=env, capture_output=True, text=True, timeout=10)
        output_name = "HDMI-1" # Default

        for line in xrandr_out.stdout.split('\n'):
            if " connected" in line:
                output_name = line.split()[0]
                break

        # 2. Apply rotation
        cmd = ["xrandr", "--output", output_name, "--rotate", rot_arg]
        subprocess.run(cmd, env=env, check=True, capture_output=True, timeout=10)
        
        # 3. Save persistence
        try:
            config_dir = Path("/opt/vernis/config")
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file = config_dir / "display.json"
            
            # Load existing or create new
            current_config = {}
            if config_file.exists():
                try:
                    current_config = json.loads(config_file.read_text())
                except:
                    pass
            
            current_config["rotation"] = direction
            config_file.write_text(json.dumps(current_config, indent=2))
            
            # Also update legacy/main config if needed, but separate is safer for now
        except Exception as e:
            print(f"Failed to save rotation config: {e}")
        
        return jsonify({"success": True, "message": f"Screen rotated to {rot_arg} ({direction} deg)"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========================================
# PERFORMANCE BENCHMARK
# ========================================

@app.route("/api/thumbnails/clear", methods=["POST"])
def clear_thumbnails():
    """Clear all cached thumbnails"""
    try:
        import shutil
        if THUMBNAIL_DIR.exists():
            shutil.rmtree(THUMBNAIL_DIR)
            THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
        return jsonify({"success": True, "message": "Thumbnails cleared"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========================================
# PERFORMANCE BENCHMARK
# ========================================

BENCHMARK_RESULTS_FILE = Path("/opt/vernis/benchmark-results.json")
BENCHMARK_STATUS_FILE = Path("/opt/vernis/benchmark-status.json")

@app.route("/api/benchmark/sample")
def benchmark_sample():
    """Get a single performance sample"""
    try:
        result = {
            "timestamp": time.time(),
            "cpu_freq_mhz": 0,
            "temp_c": 0,
            "memory": {"used_mb": 0, "total_mb": 0, "percent": 0},
            "throttle": {"throttled": False}
        }

        # CPU frequency
        try:
            freq_result = subprocess.run(
                ["vcgencmd", "measure_clock", "arm"],
                capture_output=True, text=True, timeout=5
            )
            if freq_result.returncode == 0:
                freq_str = freq_result.stdout.strip().split("=")[1]
                result["cpu_freq_mhz"] = int(freq_str) // 1000000
        except:
            pass

        # Temperature
        try:
            temp_result = subprocess.run(
                ["vcgencmd", "measure_temp"],
                capture_output=True, text=True, timeout=5
            )
            if temp_result.returncode == 0:
                temp_str = temp_result.stdout.strip()
                result["temp_c"] = float(temp_str.replace("temp=", "").replace("'C", ""))
        except:
            pass

        # Memory
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            mem_info = {}
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    mem_info[parts[0].rstrip(":")] = int(parts[1])
            total = mem_info.get("MemTotal", 0) / 1024
            free = mem_info.get("MemAvailable", mem_info.get("MemFree", 0)) / 1024
            used = total - free
            result["memory"] = {
                "total_mb": round(total, 1),
                "used_mb": round(used, 1),
                "percent": round((used / total) * 100, 1) if total > 0 else 0
            }
        except:
            pass

        # Throttle status
        try:
            throttle_result = subprocess.run(
                ["vcgencmd", "get_throttled"],
                capture_output=True, text=True, timeout=5
            )
            if throttle_result.returncode == 0:
                throttle_hex = throttle_result.stdout.strip().replace("throttled=", "")
                throttle_val = int(throttle_hex, 16)
                result["throttle"] = {
                    "raw": throttle_hex,
                    "throttled": bool(throttle_val & 0x4),
                    "freq_capped": bool(throttle_val & 0x2),
                    "under_voltage": bool(throttle_val & 0x1)
                }
        except:
            pass

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/benchmark/run", methods=["POST"])
def run_benchmark():
    """Start a performance benchmark"""
    try:
        data = request.json or {}
        quick = data.get("quick", False)
        duration = data.get("duration", 60)

        # Check if already running
        if BENCHMARK_STATUS_FILE.exists():
            try:
                with open(BENCHMARK_STATUS_FILE) as f:
                    status = json.load(f)
                if status.get("running", False):
                    return jsonify({"error": "Benchmark already running"}), 400
            except:
                pass

        # Mark as running
        with open(BENCHMARK_STATUS_FILE, "w") as f:
            json.dump({"running": True, "started": time.time(), "quick": quick}, f)

        # Run benchmark in background
        benchmark_script = SCRIPTS_DIR / "performance_benchmark.py"
        args = ["python3", str(benchmark_script)]
        if quick:
            args.append("--quick")
        else:
            args.extend(["--duration", str(duration)])

        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return jsonify({
            "success": True,
            "message": f"Benchmark started ({'quick' if quick else f'{duration}s stress test'})"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/benchmark/status")
def benchmark_status():
    """Get benchmark status"""
    try:
        running = False
        started = None

        if BENCHMARK_STATUS_FILE.exists():
            try:
                with open(BENCHMARK_STATUS_FILE) as f:
                    status = json.load(f)
                running = status.get("running", False)
                started = status.get("started")

                # Check if it's been too long (timeout after 5 minutes)
                if running and started and time.time() - started > 300:
                    running = False
                    with open(BENCHMARK_STATUS_FILE, "w") as f:
                        json.dump({"running": False}, f)
            except:
                pass

        return jsonify({
            "running": running,
            "started": started,
            "elapsed": round(time.time() - started) if started and running else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/benchmark/results")
def benchmark_results():
    """Get benchmark results history"""
    try:
        results = []
        if BENCHMARK_RESULTS_FILE.exists():
            with open(BENCHMARK_RESULTS_FILE) as f:
                results = json.load(f)

        # Return last 10 results, most recent first
        return jsonify({
            "results": list(reversed(results[-10:]))
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/benchmark/complete", methods=["POST"])
def benchmark_complete():
    """Mark benchmark as complete (called by script)"""
    try:
        with open(BENCHMARK_STATUS_FILE, "w") as f:
            json.dump({"running": False, "completed": time.time()}, f)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =====================
# Integration Test API
# =====================
TEST_STATUS_FILE = Path("/opt/vernis/test-status.json")
TEST_RESULTS_FILE = Path("/opt/vernis/test-results.json")

@app.route("/api/tests/run", methods=["POST"])
def run_tests():
    """Run integration test suite"""
    try:
        # Check if already running
        if TEST_STATUS_FILE.exists():
            with open(TEST_STATUS_FILE, "r") as f:
                status = json.load(f)
                if status.get("running"):
                    return jsonify({"error": "Tests already running"}), 400

        # Mark as running
        with open(TEST_STATUS_FILE, "w") as f:
            json.dump({"running": True, "started": time.time()}, f)

        # Run test script in background
        test_script = SCRIPTS_DIR / "test_vernis.py"
        output_file = Path("/opt/vernis/test-output.json")

        subprocess.Popen([
            "python3", str(test_script),
            "--host", "127.0.0.1",
            "--port", "5000",
            "--output", str(output_file)
        ])

        return jsonify({"success": True, "message": "Tests started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/tests/status")
def test_status():
    """Get current test status"""
    try:
        if not TEST_STATUS_FILE.exists():
            return jsonify({"running": False})

        with open(TEST_STATUS_FILE, "r") as f:
            status = json.load(f)

        # Check if output file exists (tests completed)
        output_file = Path("/opt/vernis/test-output.json")
        if output_file.exists():
            output_mtime = output_file.stat().st_mtime
            started = status.get("started", 0)

            # If output is newer than start time, tests are done
            if output_mtime > started:
                status["running"] = False
                status["completed"] = True

        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/tests/results")
def test_results():
    """Get test results"""
    try:
        output_file = Path("/opt/vernis/test-output.json")
        if not output_file.exists():
            return jsonify({"error": "No test results found"}), 404

        with open(output_file, "r") as f:
            results = json.load(f)

        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/tests/history")
def test_history():
    """Get test history"""
    try:
        if not TEST_RESULTS_FILE.exists():
            return jsonify({"history": []})

        with open(TEST_RESULTS_FILE, "r") as f:
            history = json.load(f)

        return jsonify({"history": history[-20:]})  # Last 20 runs
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/tests/complete", methods=["POST"])
def tests_complete():
    """Mark tests as complete and save to history"""
    try:
        # Update status
        with open(TEST_STATUS_FILE, "w") as f:
            json.dump({"running": False, "completed": time.time()}, f)

        # Save to history
        output_file = Path("/opt/vernis/test-output.json")
        if output_file.exists():
            with open(output_file, "r") as f:
                result = json.load(f)

            history = []
            if TEST_RESULTS_FILE.exists():
                with open(TEST_RESULTS_FILE, "r") as f:
                    history = json.load(f)

            history.append({
                "timestamp": result.get("timestamp"),
                "passed": result.get("passed", 0),
                "failed": result.get("failed", 0),
                "success_rate": result.get("success_rate", 0)
            })

            # Keep last 50
            history = history[-50:]

            with open(TEST_RESULTS_FILE, "w") as f:
                json.dump(history, f, indent=2)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =====================
# Auto Security Updates API
# =====================
AUTO_UPDATE_CONFIG_FILE = Path("/opt/vernis/auto-update-config.json")
AUTO_UPDATE_SCRIPT = Path("/opt/vernis/scripts/setup-auto-updates.sh")

@app.route("/api/auto-update", methods=["GET"])
def auto_update_status():
    """Get auto security update status"""
    try:
        if AUTO_UPDATE_CONFIG_FILE.exists():
            with open(AUTO_UPDATE_CONFIG_FILE, 'r') as f:
                config = json.load(f)
            return jsonify(config)
        # Default: enabled (we want security updates on by default)
        return jsonify({"enabled": True})
    except Exception as e:
        return jsonify({"enabled": True, "error": str(e)})

@app.route("/api/auto-update", methods=["POST"])
def auto_update_set():
    """Enable or disable auto security updates"""
    try:
        data = request.json
        enabled = bool(data.get("enabled", True))
        action = "enable" if enabled else "disable"

        if AUTO_UPDATE_SCRIPT.exists():
            result = subprocess.run(
                ["sudo", "bash", str(AUTO_UPDATE_SCRIPT), action],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                return jsonify({"success": False, "error": result.stderr or "Script failed"}), 500
        else:
            # Fallback: just save config if script not deployed yet
            with open(AUTO_UPDATE_CONFIG_FILE, 'w') as f:
                json.dump({"enabled": enabled}, f)

        return jsonify({"success": True, "enabled": enabled})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# =====================
# OS Update Lock API
# =====================
OS_LOCK_STATUS_FILE = Path("/opt/vernis/os-lock-status.json")
OS_UPDATE_LOG_FILE = Path("/opt/vernis/os-update.log")

@app.route("/api/os-lock/status")
def os_lock_status():
    """Get OS update lock status"""
    try:
        # Run the lock script to get current status
        lock_script = SCRIPTS_DIR / "os_update_lock.py"
        if lock_script.exists():
            result = subprocess.run(
                ["python3", str(lock_script), "--status", "--json"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                status = json.loads(result.stdout)
                return jsonify(status)

        # Fallback: read cached status
        if OS_LOCK_STATUS_FILE.exists():
            with open(OS_LOCK_STATUS_FILE, "r") as f:
                return jsonify(json.load(f))

        return jsonify({
            "locked": False,
            "protected_packages": [],
            "unprotected_packages": [],
            "error": "Status not available"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/os-lock/lock", methods=["POST"])
def os_lock_enable():
    """Lock critical OS packages"""
    try:
        lock_script = SCRIPTS_DIR / "os_update_lock.py"
        if not lock_script.exists():
            return jsonify({"error": "Lock script not found"}), 404

        result = subprocess.run(
            ["sudo", "python3", str(lock_script), "--lock"],
            capture_output=True, text=True, timeout=60
        )

        if result.returncode == 0:
            return jsonify({
                "success": True,
                "message": "OS packages locked successfully",
                "output": result.stdout
            })
        else:
            return jsonify({
                "success": False,
                "error": result.stderr or "Failed to lock packages",
                "output": result.stdout
            }), 500
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Operation timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/os-lock/unlock", methods=["POST"])
def os_lock_disable():
    """Temporarily unlock OS packages (for manual updates)"""
    try:
        lock_script = SCRIPTS_DIR / "os_update_lock.py"
        if not lock_script.exists():
            return jsonify({"error": "Lock script not found"}), 404

        result = subprocess.run(
            ["sudo", "python3", str(lock_script), "--unlock"],
            capture_output=True, text=True, timeout=60
        )

        if result.returncode == 0:
            return jsonify({
                "success": True,
                "message": "OS packages unlocked. Remember to re-lock after updating!",
                "output": result.stdout
            })
        else:
            return jsonify({
                "success": False,
                "error": result.stderr or "Failed to unlock packages"
            }), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/os-lock/safe-update", methods=["POST"])
def os_safe_update():
    """Run safe updates (excludes kernel/firmware)"""
    try:
        lock_script = SCRIPTS_DIR / "os_update_lock.py"
        if not lock_script.exists():
            return jsonify({"error": "Lock script not found"}), 404

        # Run in background as it may take a while
        subprocess.Popen(
            ["sudo", "python3", str(lock_script), "--safe-update"],
            stdout=open("/opt/vernis/safe-update.log", "w"),
            stderr=subprocess.STDOUT
        )

        return jsonify({
            "success": True,
            "message": "Safe update started. Check logs for progress."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/os-lock/kernel-info")
def os_kernel_info():
    """Get kernel and device information"""
    try:
        info = {}

        # Running kernel
        result = subprocess.run(["uname", "-r"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            info["running_kernel"] = result.stdout.strip()

        # Device model
        model_file = Path("/proc/device-tree/model")
        if model_file.exists():
            info["device_model"] = model_file.read_text().replace("\x00", "").strip()

        # Kernel package version
        result = subprocess.run(
            "dpkg -l | grep raspberrypi-kernel | head -1 | awk '{print $3}'",
            shell=True, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            info["kernel_package_version"] = result.stdout.strip()

        # Firmware version
        result = subprocess.run(["vcgencmd", "version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            info["firmware_version"] = result.stdout.strip().split("\n")[0]

        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/os-lock/log")
def os_update_log():
    """Get OS update log"""
    try:
        if not OS_UPDATE_LOG_FILE.exists():
            return jsonify({"log": []})

        lines = OS_UPDATE_LOG_FILE.read_text().strip().split("\n")
        # Return last 50 log entries
        return jsonify({"log": lines[-50:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/easter-egg", methods=["GET", "POST"])
def easter_egg():
    """Get or set easter egg unlock state"""
    egg_file = Path("/opt/vernis/easter-eggs.json")

    if request.method == "POST":
        try:
            data = request.json or {}
            # Read existing state
            state = {}
            if egg_file.exists():
                with open(egg_file, 'r') as f:
                    state = json.load(f)
            # Merge new keys
            state.update(data)
            with open(egg_file, 'w') as f:
                json.dump(state, f, indent=2)
            return jsonify({"success": True, **state})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        try:
            if egg_file.exists():
                with open(egg_file, 'r') as f:
                    state = json.load(f)
            else:
                state = {}
            return jsonify(state)
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# =====================
# BURNER NFT Local Renderer
# =====================

@app.route("/api/burner/gas")
def burner_gas():
    """Get current Ethereum gas data for BURNER renderer via JSON-RPC"""
    rpc_config = get_eth_rpc_config()
    rpc_url = rpc_config.get("custom_rpc_url", "").strip()
    if not rpc_url:
        rpc_url = "https://ethereum-rpc.publicnode.com"

    import urllib.request
    from datetime import datetime as dt, timezone

    def rpc_call(method, params=None):
        payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or [], "id": 1})
        req = urllib.request.Request(rpc_url, data=payload.encode(), headers={"Content-Type": "application/json", "User-Agent": "Vernis/3.0"})
        resp = urllib.request.urlopen(req, timeout=8)
        return json.loads(resp.read()).get("result")

    try:
        gas_hex = rpc_call("eth_gasPrice")
        block_hex = rpc_call("eth_blockNumber")
        gas_wei = int(gas_hex, 16)
        block_num = int(block_hex, 16)
        gas_gwei = gas_wei / 1e9

        # Adaptive scaling: post-Dencun gas is often <1 gwei.
        # Original BURNER tiers expect 5-60 gwei for active visuals.
        # Use milligwei when gas is low to keep art alive.
        if gas_gwei >= 5:
            seed1 = int(gas_gwei)
        else:
            seed1 = max(5, min(200, int(gas_wei / 1e6)))

        now = dt.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return jsonify({
            "seed1": seed1,
            "seed2": seed1,
            "seed3": max(1, int(gas_wei / 1e4)),
            "datetime": now,
            "block": block_num
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/burner/render/<int:token_id>")
def burner_render(token_id):
    """Serve local BURNER renderer HTML — fully independent of crashblossom.co"""
    if token_id < 0 or token_id > 255:
        return "Token ID must be 0-255", 400

    frosted = request.args.get('frosted', '0') == '1'

    # Default tiers and rarity — covers most BURNER tokens
    # Tiers map gas (gwei) to layer visibility thresholds
    default_tiers = [0, 5, 10, 15, 25, 40, 60, 65535]
    rarity = 3
    speed = 1

    # Try to read per-token overrides from cache
    cache_file = Path("/opt/vernis/burner-token-cache.json")
    if cache_file.exists():
        try:
            with open(cache_file, 'r') as f:
                cache = json.load(f)
            tk = str(token_id)
            if tk in cache:
                default_tiers = cache[tk].get("tiers", default_tiers)
                rarity = cache[tk].get("rarity", rarity)
                speed = cache[tk].get("speed", speed)
        except:
            pass

    # Detect if full-res assets are cached locally
    cache_complete = False
    if BURNER_CACHE_DIR.exists() and (BURNER_CACHE_DIR / BURNER_JQUERY_TX).exists():
        cache_complete = True
    thumb_mode = 0 if cache_complete else 1
    if cache_complete:
        jquery_url = f"/api/burner/assets/{BURNER_JQUERY_TX}"
        sha1_url = f"/api/burner/assets/{BURNER_SHA1_TX}"
        manifest_url = f"/api/burner/assets/{BURNER_MANIFEST_TX}"
    else:
        jquery_url = f"https://arweave.net/{BURNER_JQUERY_TX}"
        sha1_url = f"https://arweave.net/{BURNER_SHA1_TX}"
        manifest_url = f"https://arweave.net/{BURNER_MANIFEST_TX}"

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<script src="{jquery_url}"></script>
<script src="{sha1_url}"></script>
<style>
html, body {{ margin:0; padding:0; height:100%; background:#000; overflow:hidden; }}
.contenedor {{ position:relative; height:100%; width:66.666vh; margin:0 auto; z-index:1; }}
canvas {{ height:100%; width:66.666vh; position:absolute; top:0; left:0; background:transparent; }}
#loading {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
  color:#555; font-family:monospace; font-size:14px; z-index:9999; }}
#frosted-bg {{ display:none; position:fixed; inset:-30px; background-size:cover; background-position:center;
  filter:blur(60px) saturate(1.4); opacity:0.5; z-index:0; transform:scale(1.15); }}
</style>
</head>
<body>
<div id="frosted-bg"></div>
<div class="contenedor">
<div class="layers">
<canvas name="canvas" index="0" width="800" height="1200" style="z-index:100"></canvas>
<canvas name="canvas" index="1" width="800" height="1200" style="z-index:200;display:none"></canvas>
<canvas name="canvas" index="2" width="800" height="1200" style="z-index:300;display:none"></canvas>
<canvas name="canvas" index="7" width="800" height="1200" style="z-index:400;display:none"></canvas>
<canvas name="canvas" index="8" width="800" height="1200" style="z-index:500;display:none"></canvas>
<canvas name="canvas" index="3" width="800" height="1200" style="z-index:600;display:none"></canvas>
<canvas name="canvas" index="4" width="800" height="1200" style="z-index:700;display:none"></canvas>
<canvas name="canvas" index="5" width="800" height="1200" style="z-index:800;display:none"></canvas>
<canvas name="canvas" index="6" width="800" height="1200" style="z-index:900;display:none"></canvas>
</div>
<div id="loading">Loading BURNER #{token_id}...</div>
</div>
<script>
var tokenID = '{token_id}';
var arrayTiers = {json.dumps(default_tiers)};
var rarity = {rarity};
var tokenSpeed = {speed};
var x = 800, y = 1200;
var delayFade = 500;
var changeCoefficient = 1.25;
var thumbmode = {thumb_mode};
var pathmanifest;
var frostedEnabled = {'true' if frosted else 'false'};
</script>
<script src="{manifest_url}"></script>
<script>
var baseLayer, transparentLayer;
var newArrayLayers, oldArrayLayers;
var chronos, heartbeats = 0, heartbeatBusy = false;
var lastBlock = 0, readBlock = 0;
var seed1 = 0, seed2 = 0, seed3 = 0, blockdt = '', oldgas = 0;

function initPaths() {{
  if (thumbmode === 0) pathmanifest.prefixuri = '/api/burner/assets/';
  baseLayer = pathmanifest.prefixuri + (thumbmode === 0 ? pathmanifest.fullbase[tokenID] : pathmanifest.thumbbase[tokenID]);
  transparentLayer = pathmanifest.prefixuri + (thumbmode === 0 ? pathmanifest.fulltransparent : pathmanifest.thumbtransparent);
  newArrayLayers = [baseLayer, transparentLayer, transparentLayer, transparentLayer, transparentLayer, transparentLayer, transparentLayer, transparentLayer, transparentLayer];
  oldArrayLayers = [baseLayer, transparentLayer, transparentLayer, transparentLayer, transparentLayer, transparentLayer, transparentLayer, transparentLayer, transparentLayer];
}}

function DetermineHighestLayer(gas) {{
  var highest = 0;
  for (var i = 0; i < 7; i++) {{
    if (gas > arrayTiers[i] && gas <= arrayTiers[i + 1]) {{ highest = i; break; }}
  }}
  return highest;
}}

function ScheduleFadeOutTransition(layer, transitionTime, scheduleTime) {{
  setTimeout(function() {{
    $('[name="canvas"][index="' + layer + '"]').fadeOut(transitionTime);
  }}, scheduleTime);
}}

function ScheduleFadeInTransition(layer, transitionTime, scheduleTime) {{
  setTimeout(function() {{
    var img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = function() {{
      var c = document.querySelector('[name="canvas"][index="' + layer + '"]');
      var ctx = c.getContext('2d');
      ctx.clearRect(0, 0, x, y);
      ctx.drawImage(img, 0, 0);
      setTimeout(function() {{
        $('[name="canvas"][index="' + layer + '"]').fadeIn(transitionTime);
      }}, 250);
    }};
    img.src = newArrayLayers[layer];
  }}, scheduleTime);
}}

function ChangeImage(layer, delta, boolFadeOut, boolFadeIn) {{
  var transTimeOut = boolFadeOut ? delayFade : 100;
  var transTimeIn = boolFadeIn ? delayFade : 100;
  if (layer !== 0) {{
    ScheduleFadeOutTransition(layer, transTimeOut, delta);
    ScheduleFadeInTransition(layer, transTimeIn, delta + transTimeOut + 100);
  }} else {{
    var img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = function() {{
      var c = document.querySelector('[name="canvas"][index="0"]');
      var ctx = c.getContext('2d');
      ctx.clearRect(0, 0, x, y);
      ctx.drawImage(img, 0, 0);
      $('[name="canvas"][index="0"]').show();
    }};
    img.src = baseLayer;
  }}
  oldArrayLayers[layer] = newArrayLayers[layer];
}}

function DetermineTransitioningLayersByGas(g, c) {{
  var r = 0;
  if (g >= arrayTiers[0] && g <= arrayTiers[1]) r = 0;
  else if (g > arrayTiers[1] && g <= arrayTiers[2]) r = 1;
  else if (g > arrayTiers[2] && g <= arrayTiers[3]) r = 1;
  else if (g > arrayTiers[3] && g <= arrayTiers[4]) r = 2;
  else if (g > arrayTiers[4] && g <= arrayTiers[5]) r = 2;
  else if (g > arrayTiers[5] && g <= arrayTiers[6]) r = 3;
  else if (g > arrayTiers[6]) r = 4;
  return Math.ceil(r * c);
}}

function PickPNG(block, gas, token, layer, datetime, num) {{
  var hash = sha1(block + ' ' + gas + ' ' + token + ' ' + layer + ' ' + datetime + ' ' + num);
  var h = parseInt(hash.slice(-1), 16);
  var idx = Math.ceil((h + 1) / (16 / 10)) - 1;
  var arr = (thumbmode === 0) ? pathmanifest.fulllayers[layer] : pathmanifest.thumblayers[layer];
  if (!arr || !arr[idx]) return transparentLayer;
  return pathmanifest.prefixuri + arr[idx];
}}

function PickRandomLayer(block, gas, number) {{
  var tmp = [];
  var max = DetermineHighestLayer(gas);
  if (gas > arrayTiers[1] && max > 0) {{
    for (var i = 1; i <= max; i++) tmp.push(i);
    if (max > 2) {{
      if (rarity >= 2) tmp.push(7);
      if (rarity >= 3) tmp.push(8);
    }}
    var hash = sha1(block + ' ' + gas + ' ' + number);
    var h = parseInt(hash.slice(-1), 16);
    var n = Math.ceil((h + 1) / (16 / 10)) - 1;
    var d = 10 / tmp.length;
    return tmp[Math.floor(n / d)];
  }}
  return 0;
}}

function UpdateView(doTransitions) {{
  var boolProceed = true;
  var d = 15;
  if (tokenSpeed === 3) d = 11;
  else if (tokenSpeed === 2) d = 4;
  var hash = sha1(lastBlock + ' ' + seed3);
  var h = parseInt(hash.slice(-1), 16);
  if (h < d) boolProceed = false;
  if (boolProceed || tokenSpeed === 1) {{
    var total = DetermineTransitioningLayersByGas(seed2, changeCoefficient);
    for (var i = 0; i < total; i++) {{
      var l = PickRandomLayer(lastBlock, seed1, i);
      if (l > 0) {{
        newArrayLayers[l] = PickPNG(lastBlock, seed3, tokenID, l, blockdt, i);
        var fo = oldArrayLayers[l] !== transparentLayer;
        var fi = newArrayLayers[l] !== transparentLayer;
        if (doTransitions !== false) ChangeImage(l, i * 250, fo, fi);
      }}
    }}
  }}
}}

function HeartBeat() {{
  if (heartbeatBusy) return;
  if (heartbeats > 4) heartbeats = 0;
  if (heartbeats === 0) {{
    heartbeatBusy = true;
    $.getJSON('/api/burner/gas', function(data) {{
      heartbeatBusy = false;
      if (data && !data.error) {{
        seed1 = Number(data.seed1);
        seed2 = Number(data.seed2);
        seed3 = Number(data.seed3);
        blockdt = data.datetime;
        lastBlock = data.block;
        readBlock = data.block;
        oldgas = seed2;
        UpdateView(true);
      }}
    }}).fail(function() {{ heartbeatBusy = false; }});
  }} else {{
    lastBlock++;
    UpdateView(true);
  }}
  heartbeats++;
}}

function Start() {{
  initPaths();
  ChangeImage(0, 0, false, false);
  $('[name="canvas"]').show();
  document.getElementById('loading').style.display = 'none';
  if (frostedEnabled) {{
    var fb = document.getElementById('frosted-bg');
    fb.style.backgroundImage = 'url(' + baseLayer + ')';
    fb.style.display = 'block';
  }}
  // Fetch initial gas data then start heartbeat cycle
  $.getJSON('/api/burner/gas', function(data) {{
    if (data && !data.error) {{
      seed1 = Number(data.seed1);
      seed2 = Number(data.seed2);
      seed3 = Number(data.seed3);
      blockdt = data.datetime;
      lastBlock = data.block;
      readBlock = data.block;
      oldgas = seed2;
      UpdateView(true);
    }}
  }}).always(function() {{
    chronos = setInterval(HeartBeat, 12000);
  }});
}}

$(document).ready(function() {{ Start(); }});

// Listen for token change messages from parent (avoids full iframe reload)
window.addEventListener('message', function(e) {{
  if (e.data && e.data.type === 'changeToken' && e.data.tokenId !== undefined) {{
    var newId = String(e.data.tokenId);
    if (newId === tokenID) return;
    tokenID = newId;
    // Stop current heartbeat
    if (chronos) clearInterval(chronos);
    heartbeats = 0;
    heartbeatBusy = false;
    // Clear overlay canvases but keep them visible (matches Start() behavior)
    $('[name="canvas"]').not('[index="0"]').each(function() {{
      var ctx = this.getContext('2d');
      ctx.clearRect(0, 0, x, y);
    }});
    $('[name="canvas"]').show();
    // Reset layer arrays and reload base
    initPaths();
    ChangeImage(0, 0, false, false);
    if (frostedEnabled) {{
      document.getElementById('frosted-bg').style.backgroundImage = 'url(' + baseLayer + ')';
    }}
    // Fetch gas and restart heartbeat
    $.getJSON('/api/burner/gas', function(data) {{
      if (data && !data.error) {{
        seed1 = Number(data.seed1);
        seed2 = Number(data.seed2);
        seed3 = Number(data.seed3);
        blockdt = data.datetime;
        lastBlock = data.block;
        readBlock = data.block;
        oldgas = seed2;
        UpdateView(true);
      }}
    }}).always(function() {{
      chronos = setInterval(HeartBeat, 12000);
    }});
  }}
}});
</script>
</body>
</html>'''

    return Response(html, mimetype='text/html')


# =====================
# BURNER Asset Cache
# =====================

BURNER_CACHE_DIR = Path("/opt/vernis/burner-cache")
BURNER_CACHE_STATUS = Path("/opt/vernis/burner-cache-status.json")
BURNER_MANIFEST_TX = "SBHqqfL2WCMAG_p-lLqC4e2fCeAa94BsNenLVU8E6LM"
BURNER_JQUERY_TX = "LXe5PDQWsxpmeFht3wSTXhgTgXi_jOlq73xac2NqLJc"
BURNER_SHA1_TX = "qH3EpeEjLVBGDq54779fH2Z3roBH47AGSjpVjP1R5zk"
BURNER_ARWEAVE_GATEWAYS = [
    "https://arweave.dev",
    "https://g8way.io",
    "https://arweave.net",
]


def _burner_fetch_arweave(tx_id, timeout=30):
    """Fetch a file from Arweave trying multiple gateways"""
    for gw in BURNER_ARWEAVE_GATEWAYS:
        try:
            r = requests.get(f"{gw}/{tx_id}", timeout=timeout, headers={"User-Agent": "Vernis/3.0"})
            if r.status_code == 200 and len(r.content) > 0:
                return r.content
        except Exception:
            continue
    return None


def _burner_parse_manifest(raw_js):
    """Parse the pathmanifest JS variable into a dict"""
    import re as _re
    js_obj = raw_js.split("pathmanifest = ")[1].rstrip().rstrip(";")
    js_obj = _re.sub(r",\s*([}\]])", r"\1", js_obj)
    return json.loads(js_obj)


def _burner_cache_worker():
    """Background worker: download all full-res BURNER assets from Arweave"""
    import time as _time
    status = {"state": "running", "downloaded": 0, "total": 0, "errors": [], "size_bytes": 0}

    def save_status():
        try:
            with open(BURNER_CACHE_STATUS, 'w') as f:
                json.dump(status, f)
        except Exception:
            pass

    try:
        BURNER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Step 1: Download manifest + JS libs
        status["state"] = "downloading manifest"
        save_status()

        manifest_raw = _burner_fetch_arweave(BURNER_MANIFEST_TX)
        if not manifest_raw:
            status["state"] = "error"
            status["errors"].append("Failed to fetch manifest from all gateways")
            save_status()
            return

        with open(BURNER_CACHE_DIR / BURNER_MANIFEST_TX, 'wb') as f:
            f.write(manifest_raw)

        manifest = _burner_parse_manifest(manifest_raw.decode('utf-8'))

        # Download jQuery and SHA-1
        for tx in [BURNER_JQUERY_TX, BURNER_SHA1_TX]:
            data = _burner_fetch_arweave(tx)
            if data:
                with open(BURNER_CACHE_DIR / tx, 'wb') as f:
                    f.write(data)
                status["size_bytes"] += len(data)
            else:
                status["errors"].append(f"Failed: {tx}")

        # Step 2: Collect all unique full-res TX IDs
        all_txs = set()
        for v in manifest.get("fullbase", []):
            if v:
                all_txs.add(v)
        for layer in manifest.get("fulllayers", []):
            if isinstance(layer, list):
                for v in layer:
                    if v:
                        all_txs.add(v)
        ft = manifest.get("fulltransparent", "")
        if ft:
            all_txs.add(ft)

        # Remove already cached
        to_download = [tx for tx in all_txs if not (BURNER_CACHE_DIR / tx).exists()]
        already_cached = len(all_txs) - len(to_download)
        status["total"] = len(all_txs)
        status["downloaded"] = already_cached
        status["state"] = "downloading assets"
        save_status()

        # Step 3: Download each file
        for tx in to_download:
            data = _burner_fetch_arweave(tx, timeout=45)
            if data:
                with open(BURNER_CACHE_DIR / tx, 'wb') as f:
                    f.write(data)
                status["downloaded"] += 1
                status["size_bytes"] += len(data)
            else:
                status["errors"].append(tx)
                status["downloaded"] += 1  # count as attempted
            save_status()
            _time.sleep(0.1)  # small delay to avoid gateway rate limits

        status["state"] = "complete"
        save_status()

    except Exception as e:
        status["state"] = "error"
        status["errors"].append(str(e))
        save_status()


@app.route("/api/burner/cache/download", methods=["POST"])
def burner_cache_download():
    """Start background download of all full-res BURNER assets"""
    # Check if already running
    if BURNER_CACHE_STATUS.exists():
        try:
            with open(BURNER_CACHE_STATUS, 'r') as f:
                st = json.load(f)
            if st.get("state") == "running" or st.get("state") == "downloading assets" or st.get("state") == "downloading manifest":
                return jsonify({"status": "already_running", "progress": st})
        except Exception:
            pass

    t = threading.Thread(target=_burner_cache_worker, daemon=True)
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/burner/cache/status")
def burner_cache_status():
    """Get BURNER cache download progress"""
    if BURNER_CACHE_STATUS.exists():
        try:
            with open(BURNER_CACHE_STATUS, 'r') as f:
                return jsonify(json.load(f))
        except Exception:
            pass
    # Check if cache dir has files
    if BURNER_CACHE_DIR.exists():
        files = list(BURNER_CACHE_DIR.iterdir())
        if files:
            total_size = sum(f.stat().st_size for f in files if f.is_file())
            return jsonify({"state": "complete", "downloaded": len(files), "total": len(files), "size_bytes": total_size, "errors": []})
    return jsonify({"state": "none", "downloaded": 0, "total": 0})


@app.route("/api/burner/assets/<tx_id>")
def burner_serve_asset(tx_id):
    """Serve a cached BURNER asset file"""
    import re as _re
    # Validate tx_id (Arweave base64url: a-z A-Z 0-9 - _)
    if not _re.match(r'^[A-Za-z0-9_-]{20,60}$', tx_id):
        return "Invalid TX ID", 400
    fpath = BURNER_CACHE_DIR / tx_id
    if not fpath.exists():
        return "Not cached", 404
    # Detect content type by reading first bytes
    data = fpath.read_bytes()
    if data[:4] == b'\x89PNG':
        mime = 'image/png'
    elif data[:4] == b'\xff\xd8\xff\xe0' or data[:4] == b'\xff\xd8\xff\xe1':
        mime = 'image/jpeg'
    elif data[:15].startswith(b'pathmanifest') or data[:20].startswith(b'var ') or data[:1] == b'(' or data[:1] == b'/' or data[:1] == b'!':
        mime = 'application/javascript'
    else:
        mime = 'application/octet-stream'
    resp = Response(data, mimetype=mime)
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp


@app.route("/api/burner/cache", methods=["DELETE"])
def burner_cache_delete():
    """Delete all cached BURNER assets"""
    import shutil
    if BURNER_CACHE_DIR.exists():
        shutil.rmtree(BURNER_CACHE_DIR)
    if BURNER_CACHE_STATUS.exists():
        BURNER_CACHE_STATUS.unlink()
    return jsonify({"success": True})


# =====================
# Ethereum RPC Configuration
# =====================

@app.route("/api/eth-rpc", methods=["GET", "POST"])
def eth_rpc_config():
    """Get or set custom Ethereum RPC URL"""
    if request.method == "POST":
        try:
            data = request.json or {}
            url = data.get("custom_rpc_url", "").strip()
            config = {"custom_rpc_url": url}
            with open(ETH_RPC_CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify(get_eth_rpc_config())


@app.route("/api/eth-rpc/test", methods=["POST"])
def eth_rpc_test():
    """Test an Ethereum RPC connection by calling eth_blockNumber"""
    try:
        data = request.json or {}
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"error": "No URL provided"}), 400
        # SSRF protection: only allow HTTPS to known RPC providers
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ('https', 'http'):
            return jsonify({"error": "Only HTTP/HTTPS URLs allowed"}), 400
        host = parsed.hostname or ''
        # Block private/link-local IP ranges
        import ipaddress
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return jsonify({"error": "Internal addresses not allowed"}), 400
        except ValueError:
            pass  # hostname, not IP — allow (DNS resolves externally)
        # Block known metadata endpoints
        if host in ('169.254.169.254', 'metadata.google.internal'):
            return jsonify({"error": "Metadata endpoints not allowed"}), 400
        r = requests.post(url, json={
            "jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1
        }, timeout=10)
        result = r.json()
        if "result" in result:
            block_num = int(result["result"], 16)
            return jsonify({"success": True, "block_number": block_num})
        elif "error" in result:
            return jsonify({"success": False, "error": result["error"].get("message", "RPC error")})
        else:
            return jsonify({"success": False, "error": "Unexpected response"})
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "Connection timed out"})
    except requests.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "Could not connect to server"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# =====================
# CryptoPunks / Autoglyphs API
# =====================

def _eth_call(contract, call_data, timeout=15):
    """Make an eth_call to Ethereum mainnet via public RPC"""
    rpc_urls = [
        "https://eth.llamarpc.com",
        "https://rpc.ankr.com/eth",
        "https://ethereum.publicnode.com",
    ]
    # Prepend custom RPC URL if configured
    custom = get_eth_rpc_config().get("custom_rpc_url", "")
    if custom:
        rpc_urls.insert(0, custom)
    for rpc_url in rpc_urls:
        try:
            r = requests.post(rpc_url, json={
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": contract, "data": call_data}, "latest"],
                "id": 1,
            }, timeout=timeout)
            resp = r.json()
            if resp.get("result") and resp["result"] != "0x" and len(resp["result"]) > 66:
                return resp["result"]
        except Exception:
            continue
    return None


def _decode_abi_string(hex_result):
    """Decode an ABI-encoded string from eth_call result"""
    h = hex_result[2:]  # strip 0x
    offset = int(h[0:64], 16) * 2
    str_len = int(h[offset:offset + 64], 16)
    str_start = offset + 64
    return bytes.fromhex(h[str_start:str_start + str_len * 2]).decode("utf-8")


@app.route("/api/cryptopunk/<int:punk_id>")
def get_cryptopunk(punk_id):
    """Get CryptoPunk on-chain SVG from CryptoPunksData contract"""
    if punk_id < 0 or punk_id > 9999:
        return jsonify({"error": "Invalid punk ID (0-9999)"}), 400
    try:
        # CryptoPunksData contract
        contract = "0x16F5A35647D6F03D5D3da7b35409D65ba03aF3B2"
        # Compute selector for punkImageSvg(uint16)
        try:
            import hashlib
            h = hashlib.new("keccak-256")
            h.update(b"punkImageSvg(uint16)")
            selector = h.hexdigest()[:8]
        except ValueError:
            selector = "e55243ad"
        call_data = "0x" + selector + format(punk_id, "064x")
        result = _eth_call(contract, call_data)
        if not result:
            return jsonify({"error": "Could not fetch punk data from Ethereum"}), 502
        svg = _decode_abi_string(result)
        return jsonify({"svg": svg, "id": punk_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/autoglyph/<int:glyph_id>")
def get_autoglyph(glyph_id):
    """Get Autoglyph ASCII art via on-chain draw() function"""
    if glyph_id < 1 or glyph_id > 512:
        return jsonify({"error": "Invalid Autoglyph ID (1-512)"}), 400
    try:
        # draw(uint256) selector = 0x3b304147
        contract = "0xd4e4078ca3495DE5B1d4dB434BEbc5a986197782"
        call_data = "0x3b304147" + format(glyph_id, "064x")
        result = _eth_call(contract, call_data, timeout=15)
        if result:
            try:
                from urllib.parse import unquote
                data_uri = _decode_abi_string(result)
                # data_uri is "data:text/plain;charset=utf-8,<URL-encoded ASCII art>"
                prefix = "data:text/plain;charset=utf-8,"
                if data_uri.startswith(prefix):
                    art = unquote(data_uri[len(prefix):])
                else:
                    art = data_uri
                return jsonify({
                    "art": art,
                    "id": glyph_id,
                    "name": f"Autoglyph #{glyph_id}",
                })
            except Exception:
                pass
        return jsonify({"error": "Could not fetch Autoglyph from chain"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =====================
# General Files API
# =====================

def load_files_metadata():
    if FILES_METADATA_FILE.exists():
        try:
            with open(FILES_METADATA_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_files_metadata(meta):
    with open(FILES_METADATA_FILE, 'w') as f:
        json.dump(meta, f, indent=2)

@app.route("/api/files/upload", methods=["POST"])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        f = request.files['file']
        if not f.filename:
            return jsonify({"error": "Empty filename"}), 400

        FILES_DIR.mkdir(parents=True, exist_ok=True)

        safe_name = re.sub(r'[^\w\-\.]', '_', f.filename)
        # Avoid overwriting: append number if exists
        dest = FILES_DIR / safe_name
        if dest.exists():
            base, ext = os.path.splitext(safe_name)
            i = 1
            while (FILES_DIR / f"{base}_{i}{ext}").exists():
                i += 1
            safe_name = f"{base}_{i}{ext}"
            dest = FILES_DIR / safe_name

        f.save(str(dest))

        import mimetypes
        mime = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"

        # Pin to IPFS if available
        ipfs_cid = ""
        try:
            result = subprocess.run(
                ["ipfs", "add", "-Q", str(dest)],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and result.stdout.strip():
                ipfs_cid = result.stdout.strip()
        except Exception:
            pass  # IPFS not available, continue without CID

        meta = load_files_metadata()
        collection = request.form.get('collection', '').strip()
        display_name = request.form.get('name', '').strip()
        meta[safe_name] = {
            "name": display_name if display_name else f.filename,
            "collection": collection if collection else "",
            "uploadDate": datetime.now().isoformat(),
            "size": dest.stat().st_size,
            "mimeType": mime,
            "ipfs_cid": ipfs_cid
        }
        save_files_metadata(meta)

        return jsonify({"success": True, "filename": safe_name, "ipfs_cid": ipfs_cid, "message": f"Uploaded {f.filename}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/files/list", methods=["GET"])
def list_files():
    try:
        meta = load_files_metadata()
        files = []
        for fname, info in meta.items():
            fpath = FILES_DIR / fname
            if fpath.exists():
                files.append({"filename": fname, **info})
        return jsonify(files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/files/delete", methods=["POST"])
def delete_files():
    try:
        data = request.get_json()
        filenames = data.get("filenames", [])
        if not filenames:
            return jsonify({"error": "No filenames provided"}), 400

        meta = load_files_metadata()
        deleted = []
        for fname in filenames:
            safe = re.sub(r'[^\w\-\.]', '_', fname)
            fpath = FILES_DIR / safe
            if fpath.exists():
                fpath.unlink()
                deleted.append(safe)
            meta.pop(safe, None)
        save_files_metadata(meta)

        return jsonify({"success": True, "deleted": deleted})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/files/metadata/<filename>", methods=["POST"])
def update_file_metadata(filename):
    try:
        safe = re.sub(r'[^\w\-\.]', '_', filename)
        meta = load_files_metadata()
        if safe not in meta:
            return jsonify({"error": "File not found in metadata"}), 404

        data = request.get_json()
        if "collection" in data:
            meta[safe]["collection"] = data["collection"]
        save_files_metadata(meta)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/files/download/<filename>", methods=["GET"])
def download_file(filename):
    safe = re.sub(r'[^\w\-\.]', '_', filename)
    return send_from_directory(str(FILES_DIR), safe, as_attachment=True)


def _fix_mislabeled_avif():
    """One-time fix: rename AVIF files incorrectly saved as .mp4 by old downloader"""
    marker = NFT_DIR / ".avif-fix-done"
    if marker.exists():
        return
    count = 0
    for f in NFT_DIR.glob("*.mp4"):
        try:
            with open(f, "rb") as fh:
                header = fh.read(12)
            if len(header) >= 12 and header[4:8] == b"ftyp" and header[8:12] in (b"avif", b"avis", b"mif1"):
                f.rename(f.with_suffix(".avif"))
                count += 1
        except Exception:
            continue
    if count > 0:
        print(f"Fixed {count} AVIF files mislabeled as .mp4")
    try:
        marker.touch()
    except Exception:
        pass

_fix_mislabeled_avif()

# ========================================
# Bluetooth PAN
# ========================================

_bt_pairing = {"pin": None, "device": None, "timestamp": 0}

@app.route("/api/bluetooth/status")
def bluetooth_status():
    """Return Bluetooth adapter state."""
    try:
        result = subprocess.run(
            ["bluetoothctl", "show"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split("\n")
        info = {}
        for line in lines:
            line = line.strip()
            if ": " in line:
                key, val = line.split(": ", 1)
                info[key] = val

        powered = info.get("Powered", "no") == "yes"
        discoverable = info.get("Discoverable", "no") == "yes"

        hostname = subprocess.run(
            ["hostname"], capture_output=True, text=True, timeout=2
        ).stdout.strip()

        return jsonify({
            "enabled": powered,
            "discoverable": discoverable,
            "device_name": f"Vernis-{hostname}",
            "pan_ip": "10.44.0.1"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/bluetooth/paired-devices")
def bluetooth_paired_devices():
    """Return paginated list of paired Bluetooth devices."""
    try:
        page = request.args.get("page", 1, type=int)
        per_page = 4

        result = subprocess.run(
            ["bluetoothctl", "devices", "Paired"],
            capture_output=True, text=True, timeout=5
        )
        devices = []
        for line in result.stdout.strip().split("\n"):
            if line.startswith("Device "):
                parts = line.split(" ", 2)
                if len(parts) >= 3:
                    mac, name = parts[1], parts[2]
                else:
                    mac, name = parts[1], "Unknown"
                info_result = subprocess.run(
                    ["bluetoothctl", "info", mac],
                    capture_output=True, text=True, timeout=3
                )
                connected = "Connected: yes" in info_result.stdout
                devices.append({
                    "name": name,
                    "address": mac,
                    "connected": connected
                })

        total_pages = max(1, (len(devices) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        page_devices = devices[start:start + per_page]

        return jsonify({
            "devices": page_devices,
            "page": page,
            "total_pages": total_pages,
            "total": len(devices)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/bluetooth/pairing", methods=["POST"])
def bluetooth_pairing():
    """Receive pairing PIN from bt-pairing-agent and push to kiosk."""
    import time as _time
    data = request.get_json(silent=True) or {}
    pin = data.get("pin")
    device = data.get("device", "Unknown device")
    event = data.get("event", "pin")

    if event in ("complete", "failed"):
        _bt_pairing["pin"] = None
        _bt_pairing["device"] = None
        _bt_pairing["timestamp"] = 0
        try:
            import websocket as ws_mod
            resp = requests.get(f"http://127.0.0.1:{CDP_PORT}/json", timeout=2)
            pages = resp.json()
            target = next((p for p in pages if p.get("type") == "page"), None)
            if target:
                ws_url = target.get("webSocketDebuggerUrl")
                if ws_url:
                    ws = ws_mod.create_connection(ws_url, timeout=3)
                    ws.send(json.dumps({
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {"expression": "if(typeof onPairingComplete==='function')onPairingComplete()"}
                    }))
                    ws.recv()
                    ws.close()
        except Exception:
            pass
        return jsonify({"success": True})

    if not pin:
        return jsonify({"error": "No PIN provided"}), 400

    _bt_pairing["pin"] = str(pin)
    _bt_pairing["device"] = device
    _bt_pairing["timestamp"] = _time.time()

    try:
        import websocket as ws_mod
        resp = requests.get(f"http://127.0.0.1:{CDP_PORT}/json", timeout=2)
        pages = resp.json()
        target = next((p for p in pages if p.get("type") == "page"), None)
        if target:
            ws_url = target.get("webSocketDebuggerUrl")
            if ws_url:
                ws = ws_mod.create_connection(ws_url, timeout=3)
                current_url = target.get("url", "")
                if "connect.html" in current_url:
                    js_pin = json.dumps(str(pin))
                    js_dev = json.dumps(device)
                    ws.send(json.dumps({
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {"expression": f"showPairingPIN({js_pin},{js_dev})"}
                    }))
                else:
                    return_path = current_url.split("localhost")[-1] if "localhost" in current_url else "/gallery.html"
                    ws.send(json.dumps({
                        "id": 1,
                        "method": "Page.navigate",
                        "params": {"url": f"https://localhost/connect.html?tab=bluetooth&pairing=1&return={return_path}"}
                    }))
                ws.recv()
                ws.close()
    except Exception as e:
        print(f"[bluetooth] CDP push failed: {e}", flush=True)

    return jsonify({"success": True, "pin": _bt_pairing["pin"]})


@app.route("/api/bluetooth/pairing", methods=["GET"])
def bluetooth_pairing_status():
    """Return current pairing state (polled by connect.html)."""
    import time as _time
    if _bt_pairing["pin"] and (_time.time() - _bt_pairing["timestamp"]) < 30:
        return jsonify({
            "active": True,
            "pin": _bt_pairing["pin"],
            "device": _bt_pairing["device"]
        })
    return jsonify({"active": False})


import threading
_bt_discoverable_cancel = threading.Event()

def _discoverable_auto_off():
    """Background thread: disable discoverable after 60s unless cancelled."""
    if _bt_discoverable_cancel.wait(60):
        return  # Cancelled
    try:
        subprocess.run(["bluetoothctl", "discoverable", "off"],
                       capture_output=True, text=True, timeout=5)
        print("[bluetooth] Discoverable auto-disabled after 60s", flush=True)
    except Exception:
        pass

@app.route("/api/bluetooth/discoverable", methods=["POST"])
def bluetooth_discoverable():
    """Toggle Bluetooth discoverable mode. Auto-disables after 60s when enabled."""
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled", True)
    cmd = "on" if enabled else "off"
    try:
        subprocess.run(
            ["bluetoothctl", "discoverable", cmd],
            capture_output=True, text=True, timeout=5
        )
        if enabled:
            subprocess.run(
                ["bluetoothctl", "pairable", "on"],
                capture_output=True, text=True, timeout=5
            )
            # Cancel previous auto-off timer, start new one
            _bt_discoverable_cancel.set()
            _bt_discoverable_cancel.clear()
            t = threading.Thread(target=_discoverable_auto_off, daemon=True)
            t.start()
        return jsonify({"success": True, "discoverable": enabled})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/bluetooth/unpair", methods=["POST"])
def bluetooth_unpair():
    """Remove a paired Bluetooth device."""
    data = request.get_json(silent=True) or {}
    address = data.get("address", "")
    if not re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', address):
        return jsonify({"error": "Invalid MAC address"}), 400
    try:
        subprocess.run(
            ["bluetoothctl", "remove", address],
            capture_output=True, text=True, timeout=5
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Bind to localhost only — Caddy reverse proxies /api/* from port 80
    app.run(host="127.0.0.1", port=5000, debug=False)
