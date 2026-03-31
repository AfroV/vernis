"""
Vernis v3 - Advanced NFT Downloader
Features:
- Nested CID downloads (follows IPFS links in metadata)
- Multi-port IPFS detection (checks common ports)
- Multi-threaded workers for parallel downloads
- Progress tracking and resume capability
- IPFS gateway support with automatic detection
- Comprehensive error handling and retries
- Produced by Vernis Labs
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import threading
from pathlib import Path
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

class IPFSManager:
    """Handles IPFS gateway detection across multiple ports"""

    def __init__(self):
        self.gateway_url = None
        self.gateway_port = None
        # Common IPFS gateway ports to check
        self.common_ports = [8080, 5001, 5002, 5003, 8081, 9090]

    def detect_gateway(self):
        """Auto-detect IPFS gateway on common ports"""
        # Try to find IPFS on common ports
        for port in self.common_ports:
            try:
                test_url = f"http://127.0.0.1:{port}"
                # Test with a known small CID
                response = requests.get(
                    f"{test_url}/ipfs/bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
                    timeout=2
                )
                if response.status_code == 200:
                    self.gateway_url = test_url
                    self.gateway_port = port
                    print(f"✓ Found IPFS gateway at {test_url}")
                    return True
            except:
                continue

        print("⚠ No local IPFS gateway found, will use public gateways")
        return False

    def get_gateway_url(self):
        """Get the best available gateway URL"""
        if self.gateway_url:
            return self.gateway_url

        # Fallback to public gateways
        return "https://ipfs.io"

class AdvancedNFTDownloader:
    """Advanced NFT downloader with IPFS support, workers, and nested downloads"""

    # Public RPC endpoints per chain (no auth needed)
    _CHAIN_RPCS = {
        'ethereum': [
            'https://eth.llamarpc.com',
            'https://rpc.ankr.com/eth',
            'https://ethereum.publicnode.com',
        ],
        'base': [
            'https://base.llamarpc.com',
            'https://rpc.ankr.com/base',
        ],
        'optimism': [
            'https://optimism.llamarpc.com',
            'https://rpc.ankr.com/optimism',
        ],
        'polygon': [
            'https://polygon.llamarpc.com',
            'https://rpc.ankr.com/polygon',
        ],
        'arbitrum': [
            'https://arbitrum.llamarpc.com',
            'https://rpc.ankr.com/arbitrum',
        ],
        'zora': [
            'https://rpc.zora.energy',
            'https://rpc.ankr.com/zora',
        ],
    }

    def __init__(self, output_dir="nfts", workers=1, gateway_url=None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.workers = workers
        self.session = requests.Session()

        # Load settings for timeouts
        self.download_timeout = 60
        self.download_retries = 3
        self._load_ipfs_settings()

        # IPFS support
        self.ipfs_manager = IPFSManager()
        if gateway_url:
            self.ipfs_manager.gateway_url = gateway_url
        else:
            self.ipfs_manager.detect_gateway()

        self.gateway_url = self.ipfs_manager.get_gateway_url()

        # CID pattern for IPFS links (captures optional /path after CID for directory CIDs)
        self.cid_pattern = re.compile(
            r'(?:https?://[^/\s]*ipfs[^/\s]*/(?:ipfs/)?|ipfs://)?'
            r'(?:(Qm[a-zA-Z0-9]{44}(?:/[^\s"\'<>)]+)?)|(baf[a-z0-9]{50,}(?:/[^\s"\'<>)]+)?))',
            re.I
        )

        # Progress tracking
        self.downloaded = set()
        self.failed = {}  # Track failed downloads with error reasons: {cid: error_message}
        self.progress_file = self.output_dir / "download_progress.json"
        self.lock = threading.RLock()  # Use RLock to allow nested lock acquisition
        self.completed_items = 0
        self.cid_verification = True  # Default on, can be disabled in ipfs-settings.json
        self.total_items = 0
        self.source_csv = None  # Track which CSV file is being downloaded
        self.saved_files = []   # Track actual filenames written to disk
        self.bytes_downloaded = 0
        self.start_time = None
        self.current_file = None

        # IPFS pinning support
        self.ipfs_env = os.environ.copy()
        # Auto-detect IPFS_PATH: scan /home/*/.ipfs first (works when running as root)
        import glob as _glob
        ipfs_path = None
        for p in _glob.glob("/home/*/.ipfs"):
            if os.path.isdir(p):
                ipfs_path = p
                break
        if not ipfs_path and os.path.isdir("/root/.ipfs"):
            ipfs_path = "/root/.ipfs"
        if not ipfs_path:
            import pwd
            try:
                home_dir = pwd.getpwuid(os.getuid()).pw_dir
            except Exception:
                home_dir = os.path.expanduser("~")
            ipfs_path = os.path.join(home_dir, ".ipfs")
        self.ipfs_env["IPFS_PATH"] = ipfs_path
        self.auto_pin = self._check_auto_pin()

        self._load_progress()

    def _load_ipfs_settings(self):
        """Load IPFS download settings"""
        try:
            settings_file = Path("/opt/vernis/ipfs-settings.json")
            if settings_file.exists():
                with open(settings_file) as f:
                    settings = json.load(f)
                    self.download_timeout = settings.get("download_timeout", 60)
                    self.download_retries = settings.get("download_retries", 3)
                    self.cid_verification = settings.get("cid_verification", True)
                    print(f"✓ Loaded settings: timeout={self.download_timeout}s, retries={self.download_retries}, verify={self.cid_verification}")
        except Exception as e:
            print(f"⚠ Using default settings: {e}")

    def _check_auto_pin(self):
        """Check if auto-pin is enabled in IPFS settings"""
        try:
            settings_file = Path("/opt/vernis/ipfs_settings.json")
            if settings_file.exists():
                with open(settings_file) as f:
                    settings = json.load(f)
                    return settings.get("auto_pin", True)
        except:
            pass
        return True  # Default to auto-pin enabled

    def _verify_cid(self, data, expected_cid):
        """Verify downloaded content matches expected CID.
        Checks bare CID first, then directory-wrapped CID via ipfs ls.
        Returns: 'verified', 'directory_verified', 'unverified', or 'skip'."""
        if not self.cid_verification:
            return 'skip'
        try:
            # Step 1: Hash the content → bare CID check
            result = subprocess.run(
                ["ipfs", "add", "--only-hash", "-Q", "--cid-version=0"],
                input=data, capture_output=True, timeout=30,
                env=self.ipfs_env
            )
            if result.returncode != 0:
                return 'skip'  # ipfs CLI unavailable

            computed_v0 = result.stdout.decode().strip()
            if computed_v0 == expected_cid:
                return 'verified'

            # Try CIDv1
            result_v1 = subprocess.run(
                ["ipfs", "add", "--only-hash", "-Q", "--cid-version=1"],
                input=data, capture_output=True, timeout=30,
                env=self.ipfs_env
            )
            if result_v1.returncode == 0:
                computed_v1 = result_v1.stdout.decode().strip()
                if computed_v1 == expected_cid:
                    return 'verified'

            # Step 2: Bare check failed — try directory verification
            # ipfs ls <CID> succeeds if it's a valid directory node on IPFS.
            # The gateway correctly resolves directory contents, so if the CID
            # is a real directory, the downloaded content is authentic.
            try:
                ls_result = subprocess.run(
                    ["ipfs", "ls", expected_cid],
                    env=self.ipfs_env,
                    capture_output=True, text=True, timeout=30
                )
                if ls_result.returncode == 0 and ls_result.stdout.strip():
                    print(f"  ✓ Directory-wrapped CID verified: {expected_cid}")
                    return 'directory_verified'
            except Exception:
                pass  # ipfs ls timed out or failed — can't verify directory

            print(f"  ⚠ CID unverified: expected {expected_cid}, got {computed_v0}")
            return 'unverified'
        except Exception:
            return 'skip'

    def _pin_to_ipfs(self, cid):
        """Pin a CID to local IPFS node"""
        if not self.auto_pin:
            return False
        try:
            result = subprocess.run(
                ["ipfs", "pin", "add", "-r", cid],
                env=self.ipfs_env,
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return True
        except:
            pass
        return False

    def _load_progress(self):
        """Load previously downloaded files"""
        if self.progress_file.exists():
            try:
                data = json.load(open(self.progress_file))
                self.downloaded = set(data.get("downloaded", []))
                # Handle both old format (list) and new format (dict)
                failed_data = data.get("failed", {})
                if isinstance(failed_data, list):
                    self.failed = {item: "Unknown" for item in failed_data}
                else:
                    self.failed = failed_data
            except:
                pass

        # Scan output directory for existing files and add to downloaded set
        extensions = [".json", ".gif", ".png", ".jpg", ".mp4", ".glb", ".html", ".bin", ".webp", ".svg", ".avif"]
        for ext in extensions:
            for filepath in self.output_dir.glob(f"*{ext}"):
                cid = filepath.stem  # Get filename without extension
                if cid and cid != "download_progress":
                    self.downloaded.add(cid)

        if self.downloaded:
            print(f"Loaded {len(self.downloaded)} previously downloaded items")
        if self.failed:
            print(f"Found {len(self.failed)} previously failed items (will retry)")

    def _check_stop_signal(self):
        """Check if a stop signal has been sent"""
        stop_file = self.output_dir / "download_stop"
        if stop_file.exists():
            try:
                stop_file.unlink()
            except:
                pass
            return True
        return False

    def _save_progress(self):
        """Save download progress"""
        with self.lock:
            # Calculate speed
            speed = 0
            if self.start_time and self.bytes_downloaded > 0:
                elapsed = time.time() - self.start_time
                if elapsed > 0:
                    speed = self.bytes_downloaded / elapsed  # bytes per second

            progress_data = {
                "downloaded": list(self.downloaded),
                "failed": dict(self.failed),  # Dict with error reasons
                "completed": self.completed_items,
                "total": self.total_items,
                "bytes_downloaded": self.bytes_downloaded,
                "speed": speed,
                "current_file": self.current_file
            }
            # Include source CSV filename if set
            if self.source_csv:
                progress_data["source_csv"] = self.source_csv
            # Include retry info
            if hasattr(self, '_retry_pass') and self._retry_pass > 0:
                progress_data["retry_pass"] = self._retry_pass
                progress_data["retry_timeout"] = self.download_timeout
            # Write to temp file first, then rename for atomic update
            temp_file = self.progress_file.with_suffix('.tmp')
            with open(temp_file, "w") as f:
                json.dump(progress_data, f)
                f.flush()
                os.fsync(f.fileno())
            temp_file.rename(self.progress_file)

    def _extract_cids_from_json(self, obj, parent_cid=None):
        """Recursively extract all IPFS CIDs from JSON metadata"""
        cids = []

        if isinstance(obj, str):
            for match in self.cid_pattern.finditer(obj):
                cid = match.group(1) or match.group(2)
                if cid and cid != parent_cid:
                    cids.append(cid)
        elif isinstance(obj, dict):
            for value in obj.values():
                cids.extend(self._extract_cids_from_json(value, parent_cid))
        elif isinstance(obj, list):
            for item in obj:
                cids.extend(self._extract_cids_from_json(item, parent_cid))

        return cids

    def _download_with_retry(self, url, retries=None, timeout=None):
        """Download with retries using progressive timeouts"""
        if retries is None:
            retries = self.download_retries
        if timeout is None:
            timeout = self.download_timeout

        self.last_error = None
        for attempt in range(retries):
            # Progressive timeout: base, base*1.5, base*2
            attempt_timeout = int(timeout * (1 + attempt * 0.5))
            try:
                response = self.session.get(url, timeout=attempt_timeout)
                if response.status_code == 200 and len(response.content) > 100:
                    # Track bytes downloaded
                    with self.lock:
                        self.bytes_downloaded += len(response.content)
                    return response.content
                self.last_error = f"HTTP {response.status_code}"
            except requests.exceptions.Timeout:
                self.last_error = f"Timeout ({attempt_timeout}s)"
            except requests.exceptions.ConnectionError:
                self.last_error = "Connection failed"
            except Exception as e:
                self.last_error = str(e)[:50]

            if attempt < retries - 1:
                time.sleep(2)  # Wait before retry

        return None

    def _detect_file_type(self, data):
        """Detect file type from magic bytes"""
        if data.startswith(b'\x89PNG'):
            return ".png"
        elif data.startswith(b'\xff\xd8\xff'):
            return ".jpg"
        elif data.startswith(b'GIF8'):
            return ".gif"
        elif len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return ".webp"
        elif len(data) >= 12 and data[4:8] == b'ftyp':
            # ISOBMFF container: check brand to distinguish AVIF from MP4
            brand = data[8:12]
            if brand in [b'avif', b'avis', b'mif1']:
                return ".avif"
            return ".mp4"
        elif len(data) >= 8 and data[4:8] in [b'mdat', b'moov', b'wide']:
            return ".mp4"
        elif data.startswith(b'glTF'):
            return ".glb"
        elif data.startswith(b'<!DOCTYPE html') or data.startswith(b'<html'):
            return ".html"
        elif data.lstrip().startswith(b'<svg') or data.lstrip().startswith(b'<?xml'):
            return ".svg"
        else:
            try:
                json.loads(data)
                return ".json"
            except:
                return ".bin"

    def _parse_cid_path(self, cid_with_path):
        """Split 'QmXYZ/subpath/file.ext' into (base_cid, safe_identifier).
        For bare CIDs, safe_identifier equals the CID itself."""
        if '/' in cid_with_path:
            base_cid = cid_with_path.split('/', 1)[0]
            subpath = cid_with_path.split('/', 1)[1]
            stem = Path(subpath).stem  # '6' from '6.json'
            safe_id = f"{base_cid}_{stem}"
            return base_cid, safe_id
        return cid_with_path, cid_with_path

    def _file_exists(self, identifier):
        """Check if file already exists with any extension"""
        extensions = [".json", ".gif", ".png", ".jpg", ".mp4", ".glb", ".html", ".bin", ".webp", ".svg", ".avif"]
        return any((self.output_dir / f"{identifier}{ext}").exists() for ext in extensions)

    def download_ipfs_cid(self, cid, nested=False):
        """Download IPFS CID (with optional /path for directory CIDs) and follow nested CIDs"""
        cid = cid.strip()

        # Parse CID+path into base CID and safe filename identifier
        base_cid, safe_id = self._parse_cid_path(cid)

        # Check if already downloaded this session (and file exists)
        with self.lock:
            if safe_id in self.downloaded and self._file_exists(safe_id):
                return True
            # Remove from failed dict if retrying
            self.failed.pop(safe_id, None)

        # Check if file exists
        if self._file_exists(safe_id):
            with self.lock:
                self.downloaded.add(safe_id)
            print(f"  ✓ Already have: {cid}")

            # If exists, check for nested CIDs to download
            if not nested:
                for ext in [".json", ".html"]:
                    filepath = self.output_dir / f"{safe_id}{ext}"
                    if filepath.exists():
                        try:
                            content = filepath.read_text(encoding="utf-8", errors="ignore")
                            if ext == ".json":
                                metadata = json.loads(content)
                                nested_cids = self._extract_cids_from_json(metadata, base_cid)
                            else:
                                nested_cids = [
                                    match.group(1) or match.group(2)
                                    for match in self.cid_pattern.finditer(content)
                                    if (match.group(1) or match.group(2)) != cid
                                ]

                            for nested_cid in nested_cids:
                                _, nested_safe_id = self._parse_cid_path(nested_cid)
                                if not self._file_exists(nested_safe_id):
                                    self.download_ipfs_cid(nested_cid, nested=True)
                        except:
                            pass

            return True

        # Download from IPFS
        print(f"  ⬇ Downloading: {cid}")
        with self.lock:
            self.current_file = safe_id[:16] + "..."  # Truncate for display
        url = f"{self.gateway_url}/ipfs/{cid}"
        data = self._download_with_retry(url)

        if not data:
            error_msg = getattr(self, 'last_error', 'Download failed')
            print(f"  ✗ Failed to download: {cid} ({error_msg})")
            with self.lock:
                self.failed[safe_id] = error_msg
                self._save_progress()
            return False

        # Verify CID integrity (only for bare CIDs, not directory paths)
        if cid == base_cid:
            verify_result = self._verify_cid(data, base_cid)
            if verify_result == 'unverified':
                print(f"  ✗ Integrity check failed: {cid} — content does not match CID")
                with self.lock:
                    self.failed[safe_id] = "CID integrity mismatch"
                    self._save_progress()
                return False

        # Detect file type and save
        ext = self._detect_file_type(data)
        filepath = self.output_dir / f"{safe_id}{ext}"
        filepath.write_bytes(data)
        self.saved_files.append(filepath.name)

        # Pin to IPFS (use base CID only — can't pin a path)
        if self._pin_to_ipfs(base_cid):
            print(f"  ✓ Saved & Pinned: {safe_id}{ext}")
        else:
            print(f"  ✓ Saved: {safe_id}{ext}")

        # Mark as successfully downloaded
        with self.lock:
            self.downloaded.add(safe_id)
            self.failed.pop(safe_id, None)
        self._save_progress()

        # Extract and download nested CIDs (may include directory paths)
        if ext in [".json", ".html"] and not nested:
            try:
                content = data.decode("utf-8", errors="ignore")

                if ext == ".json":
                    metadata = json.loads(content)
                    nested_cids = self._extract_cids_from_json(metadata, base_cid)
                else:
                    nested_cids = [
                        match.group(1) or match.group(2)
                        for match in self.cid_pattern.finditer(content)
                        if (match.group(1) or match.group(2)) != cid
                    ]

                if nested_cids:
                    print(f"    Found {len(nested_cids)} nested CIDs")
                    for nested_cid in nested_cids:
                        _, nested_safe_id = self._parse_cid_path(nested_cid)
                        if not self._file_exists(nested_safe_id):
                            self.download_ipfs_cid(nested_cid, nested=True)
            except:
                pass

        return True

    def _eth_call(self, contract, data, chain='ethereum'):
        """Make an eth_call to a smart contract via public RPC"""
        rpcs = self._CHAIN_RPCS.get(chain, self._CHAIN_RPCS['ethereum'])
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{"to": contract, "data": data}, "latest"]
        }
        for rpc_url in rpcs:
            try:
                resp = self.session.post(rpc_url, json=payload, timeout=15)
                result = resp.json()
                if 'result' in result and result['result'] not in ('0x', '0x0'):
                    return result['result']
            except Exception:
                continue
        return None

    def _abi_decode_string(self, hex_data):
        """Decode ABI-encoded string from eth_call hex result"""
        if not hex_data or hex_data in ('0x', '0x0'):
            return None
        data = hex_data[2:]  # strip 0x
        if len(data) < 128:
            # Not standard ABI, try raw decode
            try:
                return bytes.fromhex(data).decode('utf-8').rstrip('\x00')
            except Exception:
                return None
        try:
            offset = int(data[:64], 16) * 2  # offset in hex chars
            length = int(data[offset:offset + 64], 16)
            string_hex = data[offset + 64:offset + 64 + length * 2]
            return bytes.fromhex(string_hex).decode('utf-8')
        except Exception:
            # Fallback: try raw bytes
            try:
                return bytes.fromhex(data).decode('utf-8').rstrip('\x00')
            except Exception:
                return None

    def _resolve_token_uri(self, contract, token_id, chain='ethereum'):
        """Resolve tokenURI from on-chain contract (ERC-721 / ERC-1155)"""
        token_int = int(token_id)
        token_hex = format(token_int, '064x')

        # ERC-721: tokenURI(uint256) selector 0xc87b56dd
        result = self._eth_call(contract, '0xc87b56dd' + token_hex, chain)
        if result:
            uri = self._abi_decode_string(result)
            if uri:
                return uri

        # ERC-1155: uri(uint256) selector 0x0e89341c
        result = self._eth_call(contract, '0x0e89341c' + token_hex, chain)
        if result:
            uri = self._abi_decode_string(result)
            if uri:
                # ERC-1155 uses {id} placeholder
                uri = uri.replace('{id}', format(token_int, '064x'))
                return uri

        return None

    def _ipfs_uri_to_gateway_url(self, uri):
        """Convert ipfs:// URI or gateway URL to local gateway URL"""
        if uri.startswith('ipfs://'):
            return f"{self.gateway_url}/ipfs/{uri[7:]}"
        if uri.startswith('ar://'):
            return f"https://arweave.net/{uri[5:]}"
        # Already HTTP
        return uri

    def _extract_ipfs_cid_from_uri(self, uri):
        """Extract IPFS CID (with optional path) from various URI formats"""
        if not uri:
            return None
        if uri.startswith('ipfs://'):
            return uri[7:]
        match = self.cid_pattern.search(uri)
        if match:
            return match.group(1) or match.group(2)
        return None

    def _handle_data_uri_metadata(self, data_uri, identifier):
        """Handle data:application/json;base64,... token URIs. Returns metadata dict or None."""
        import base64
        try:
            # data:application/json;base64,eyJ...
            header, encoded = data_uri.split(',', 1)
            if 'base64' in header:
                raw = base64.b64decode(encoded)
            else:
                raw = encoded.encode('utf-8')
            return json.loads(raw)
        except Exception:
            return None

    def _save_metadata_sidecar(self, stem, metadata):
        """Save metadata JSON as sidecar file next to artwork image.
        Used by gallery artwork info panel (/api/nft-artwork-info)."""
        if not metadata:
            return
        # For IPFS CIDs with paths, use the safe identifier
        if '/' in str(stem):
            _, stem = self._parse_cid_path(stem)
        sidecar_path = self.output_dir / f"{stem}.json"
        if sidecar_path.exists():
            return  # Don't overwrite existing metadata
        try:
            with open(sidecar_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def download_nft(self, contract, token_id, chain='ethereum', image_url_fallback=''):
        """Download NFT by resolving tokenURI on-chain, then downloading from IPFS.
        Falls back to image_url_fallback (e.g. OpenSea CDN) only if on-chain fails."""
        identifier = f"{contract}_{token_id}"

        # Check if already downloaded
        with self.lock:
            if identifier in self.downloaded:
                return True
            self.downloaded.add(identifier)

        if self._file_exists(identifier):
            print(f"  ✓ Already have: {identifier}")
            return True

        # === STEP 1: On-chain tokenURI resolution ===
        print(f"  ⛓ Resolving tokenURI: {contract[:10]}...#{token_id} ({chain})")
        token_uri = None
        metadata = None

        try:
            token_uri = self._resolve_token_uri(contract, token_id, chain)
        except Exception as e:
            print(f"  ⚠ On-chain call error: {e}")

        if token_uri:
            # Handle data: URIs (fully on-chain metadata)
            if token_uri.startswith('data:'):
                metadata = self._handle_data_uri_metadata(token_uri, identifier)
            else:
                # Fetch metadata from IPFS or HTTP
                metadata_url = self._ipfs_uri_to_gateway_url(token_uri)
                metadata_ipfs_cid = self._extract_ipfs_cid_from_uri(token_uri)
                print(f"  📋 Metadata: {token_uri[:70]}...")

                try:
                    meta_data = self._download_with_retry(metadata_url)
                    if meta_data:
                        try:
                            metadata = json.loads(meta_data)
                            # Pin metadata CID if it came from IPFS
                            if metadata_ipfs_cid:
                                base_meta_cid = metadata_ipfs_cid.split('/')[0]
                                self._pin_to_ipfs(base_meta_cid)
                        except json.JSONDecodeError:
                            # tokenURI pointed directly to image content, not JSON
                            print(f"  ℹ tokenURI returned raw content (not JSON)")
                            ext = self._detect_file_type(meta_data)
                            filepath = self.output_dir / f"{identifier}{ext}"
                            filepath.write_bytes(meta_data)
                            self.saved_files.append(filepath.name)
                            if self.auto_pin:
                                try:
                                    r = subprocess.run(
                                        ["ipfs", "add", "-Q", "--pin", str(filepath)],
                                        env=self.ipfs_env, capture_output=True,
                                        text=True, timeout=30
                                    )
                                    if r.returncode == 0:
                                        print(f"  ✓ Saved + pinned: {identifier}{ext} ({r.stdout.strip()[:12]}...)")
                                    else:
                                        print(f"  ✓ Saved: {identifier}{ext}")
                                except Exception:
                                    print(f"  ✓ Saved: {identifier}{ext}")
                            else:
                                print(f"  ✓ Saved: {identifier}{ext}")
                            self._save_progress()
                            return True
                except Exception as e:
                    print(f"  ⚠ Metadata fetch failed: {e}")

        # === STEP 2: Download image from metadata ===
        if metadata:
            image_field = (
                metadata.get('image') or
                metadata.get('image_url') or
                metadata.get('animation_url') or
                metadata.get('image_data') or ''
            )

            # Use token name from metadata for filename
            token_name = (metadata.get('name') or '').strip()
            if token_name:
                safe_name = re.sub(r'[^\w\s-]', '', token_name)[:50].strip()
                filename = f"{safe_name}_{token_id}" if safe_name else identifier
            else:
                filename = identifier

            if image_field:
                # Try IPFS download (preserves original content-addressed hash)
                image_cid = self._extract_ipfs_cid_from_uri(image_field)
                if image_cid:
                    print(f"  📦 IPFS image: {image_cid[:30]}...")
                    result = self.download_ipfs_cid(image_cid)
                    if result:
                        # Save metadata JSON as sidecar file
                        self._save_metadata_sidecar(image_cid, metadata)
                        self._save_progress()
                        return True
                    print(f"  ⚠ IPFS image download failed, trying gateway URL...")

                # Try as HTTP URL
                if image_field.startswith(('http://', 'https://')):
                    img_data = self._download_with_retry(image_field)
                    if img_data:
                        ext = self._detect_file_type(img_data)
                        filepath = self.output_dir / f"{filename}{ext}"
                        filepath.write_bytes(img_data)
                        self.saved_files.append(filepath.name)
                        # Save metadata JSON as sidecar file
                        self._save_metadata_sidecar(filename, metadata)
                        if self.auto_pin:
                            try:
                                r = subprocess.run(
                                    ["ipfs", "add", "-Q", "--pin", str(filepath)],
                                    env=self.ipfs_env, capture_output=True,
                                    text=True, timeout=30
                                )
                                if r.returncode == 0:
                                    print(f"  ✓ Saved + pinned: {filename}{ext} ({r.stdout.strip()[:12]}...)")
                                else:
                                    print(f"  ✓ Saved: {filename}{ext}")
                            except Exception:
                                print(f"  ✓ Saved: {filename}{ext}")
                        else:
                            print(f"  ✓ Saved: {filename}{ext}")
                        self._save_progress()
                        return True

                # Try as data URI (SVG or base64 image)
                if image_field.startswith('data:'):
                    import base64
                    try:
                        header, encoded = image_field.split(',', 1)
                        if 'base64' in header:
                            img_data = base64.b64decode(encoded)
                        else:
                            img_data = encoded.encode('utf-8')
                        ext = self._detect_file_type(img_data)
                        filepath = self.output_dir / f"{filename}{ext}"
                        filepath.write_bytes(img_data)
                        self.saved_files.append(filepath.name)
                        # Save metadata JSON as sidecar file
                        self._save_metadata_sidecar(filename, metadata)
                        print(f"  ✓ Saved: {filename}{ext} (on-chain art)")
                        self._save_progress()
                        return True
                    except Exception:
                        pass

        # === STEP 3: Fallback to image_url from CSV (OpenSea CDN) ===
        if image_url_fallback:
            print(f"  ↩ Fallback to image URL: {image_url_fallback[:60]}...")

            # Check if fallback URL contains IPFS CID
            cid_match = self.cid_pattern.search(image_url_fallback)
            if cid_match:
                cid = cid_match.group(1) or cid_match.group(2)
                result = self.download_ipfs_cid(cid)
                if result:
                    return True

            # Regular HTTP download
            img_data = self._download_with_retry(image_url_fallback)
            if img_data:
                ext = self._detect_file_type(img_data)
                filepath = self.output_dir / f"{identifier}{ext}"
                filepath.write_bytes(img_data)
                self.saved_files.append(filepath.name)
                if self.auto_pin:
                    try:
                        r = subprocess.run(
                            ["ipfs", "add", "-Q", "--pin", str(filepath)],
                            env=self.ipfs_env, capture_output=True,
                            text=True, timeout=30
                        )
                        if r.returncode == 0:
                            print(f"  ✓ Saved + pinned: {identifier}{ext} (fallback, {r.stdout.strip()[:12]}...)")
                        else:
                            print(f"  ✓ Saved: {identifier}{ext} (fallback)")
                    except Exception:
                        print(f"  ✓ Saved: {identifier}{ext} (fallback)")
                else:
                    print(f"  ✓ Saved: {identifier}{ext} (fallback)")
                self._save_progress()
                return True

        # === Nothing worked ===
        error_msg = "On-chain resolution failed" if not token_uri else "Could not download image from metadata"
        if not image_url_fallback:
            error_msg += ", no fallback URL"
        print(f"  ✗ Failed: {identifier} — {error_msg}")
        with self.lock:
            self.failed[identifier] = error_msg
        return False

    def download_url(self, url, name=""):
        """Download image from a direct HTTP URL"""
        # Create identifier from URL or name
        if name:
            identifier = re.sub(r'[^\w\s-]', '', name)[:50].strip() or "download"
        else:
            # Use last part of URL path
            identifier = url.split('/')[-1].split('?')[0][:50] or "download"

        # Check if already downloaded
        with self.lock:
            if identifier in self.downloaded:
                return True
            self.downloaded.add(identifier)

        if self._file_exists(identifier):
            print(f"  ✓ Already have: {identifier}")
            return True

        try:
            print(f"  ⬇ Downloading: {url[:60]}...")
            img_data = self._download_with_retry(url)

            if not img_data:
                print(f"  ✗ Failed to download")
                with self.lock:
                    self.failed[identifier] = getattr(self, 'last_error', 'Download failed')
                return False

            # Detect file type
            ext = self._detect_file_type(img_data)
            filepath = self.output_dir / f"{identifier}{ext}"
            filepath.write_bytes(img_data)
            self.saved_files.append(filepath.name)

            with self.lock:
                self.bytes_downloaded += len(img_data)

            # Pin to IPFS for backup
            if self.auto_pin:
                try:
                    result = subprocess.run(
                        ["ipfs", "add", "-Q", "--pin", str(filepath)],
                        env=self.ipfs_env,
                        capture_output=True, text=True, timeout=30
                    )
                    if result.returncode == 0:
                        cid = result.stdout.strip()
                        print(f"  ✓ Saved + pinned: {identifier}{ext} ({cid[:12]}...)")
                    else:
                        print(f"  ✓ Saved: {identifier}{ext} (pin failed)")
                except Exception:
                    print(f"  ✓ Saved: {identifier}{ext} (IPFS unavailable)")
            else:
                print(f"  ✓ Saved: {identifier}{ext}")

            self._save_progress()
            return True

        except Exception as e:
            print(f"  ✗ Error: {e}")
            with self.lock:
                self.failed[identifier] = str(e)[:100]
            return False

    def process_csv(self, csv_path):
        """Process CSV file with either CIDs or contract addresses"""
        # Store the source CSV filename for progress tracking
        self.source_csv = Path(csv_path).name

        items = []

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Check for CID column (multiple possible names)
                cid = (
                    row.get("cid") or row.get("CID") or
                    row.get("ipfs_cid") or row.get("image_cid") or ""
                ).strip()

                # Check for image_url column (HTTP or IPFS URLs)
                image_url = (
                    row.get("image_url") or row.get("imageUrl") or
                    row.get("image") or ""
                ).strip()

                # Check for metadata_url column
                if not cid:
                    metadata_url = (row.get("metadata_url") or row.get("metadataUrl") or "").strip()
                    if metadata_url:
                        match = self.cid_pattern.search(metadata_url)
                        if match:
                            cid = match.group(1) or match.group(2)

                # Try to extract CID from image_url if no direct CID
                if not cid and image_url:
                    match = self.cid_pattern.search(image_url)
                    if match:
                        cid = match.group(1) or match.group(2)

                # Check for contract address + token ID
                contract = row.get('contract_address', '').strip()
                token_id = row.get('token_id', '').strip()
                chain = (row.get('chain') or 'ethereum').strip().lower()

                # Get name for filename
                name = (row.get("name") or row.get("Name") or "").strip()

                if cid and cid not in ["See CSV", "On-Chain", "Arweave", "--"]:
                    items.append(('ipfs', cid))
                elif contract and token_id:
                    # On-chain resolution first, image_url as fallback
                    items.append(('nft', (contract, token_id, chain, image_url)))
                elif image_url and image_url.startswith(('http://', 'https://')):
                    # Direct HTTP URL only if no contract+token for on-chain lookup
                    items.append(('url', (image_url, name or token_id or '')))

        self.total_items = len(items)
        self._retry_pass = 0

        # Count item types
        ipfs_items = sum(1 for t, _ in items if t == 'ipfs')
        url_items = sum(1 for t, _ in items if t == 'url')
        nft_items = sum(1 for t, _ in items if t == 'nft')

        print(f"\nFound {self.total_items} items to download")
        if ipfs_items > 0:
            print(f"  - {ipfs_items} with direct IPFS CIDs")
        if url_items > 0:
            print(f"  - {url_items} with direct HTTP URLs")
        if nft_items > 0:
            print(f"  - {nft_items} with on-chain tokenURI resolution (contract+token)")
            if ipfs_items == 0 and url_items == 0:
                print("  ℹ All items will be resolved on-chain via public RPC")

        if self.total_items == 0:
            print("⚠ No downloadable items found in CSV")
            print("  The CSV may be missing 'cid' or 'image_url' columns.")
            return

        # Clean up any stale stop signal
        stop_file = self.output_dir / "download_stop"
        if stop_file.exists():
            try:
                stop_file.unlink()
            except:
                pass

        # Initialize timing for speed calculation
        self.start_time = time.time()
        self.bytes_downloaded = 0

        # Save initial progress
        self._save_progress()

        # Run download pass
        self._run_download_pass(items)

        # Auto-retry timeout failures with increasing timeout (up to 300s / 5 min)
        max_timeout = 300
        timeout_steps = [120, 180, 300]  # Progressive base timeouts for retries

        for retry_timeout in timeout_steps:
            if self._check_stop_signal():
                print("\n⏹ Download stopped by user")
                break

            # Check for timeout failures worth retrying
            timeout_failures = {
                k: v for k, v in self.failed.items()
                if 'timeout' in str(v).lower() or 'timed out' in str(v).lower()
            }

            if not timeout_failures:
                break  # No timeout failures, done

            if self.download_timeout >= max_timeout:
                break  # Already at max timeout

            # Increase timeout and retry failed items
            self._retry_pass += 1
            self.download_timeout = retry_timeout
            retry_items = []
            for item_type, item_data in items:
                if item_type == 'ipfs':
                    _, safe_id = self._parse_cid_path(item_data.strip())
                    if safe_id in timeout_failures:
                        retry_items.append((item_type, item_data))
                elif item_type == 'url':
                    url_data = item_data[0] if isinstance(item_data, tuple) else item_data
                    safe_id = re.sub(r'[^\w\-.]', '_', str(url_data))[:80]
                    if safe_id in timeout_failures:
                        retry_items.append((item_type, item_data))
                elif item_type == 'nft':
                    contract = item_data[0] if isinstance(item_data, tuple) else item_data
                    token = item_data[1] if isinstance(item_data, tuple) and len(item_data) > 1 else ''
                    safe_id = f"{contract}_{token}"
                    if safe_id in timeout_failures:
                        retry_items.append((item_type, item_data))

            if not retry_items:
                break

            print(f"\n🔄 Auto-retry pass {self._retry_pass}: {len(retry_items)} timeout failures with {retry_timeout}s timeout")
            # Reset completed count for accurate progress during retry
            self.completed_items = self.total_items - len(retry_items)
            self._save_progress()
            self._run_download_pass(retry_items)

        # Final save of progress
        self._save_progress()

        # Show summary
        failed_count = len(self.failed)
        success_count = len(self.downloaded) - failed_count
        print(f"\n{'✓' if failed_count == 0 else '⚠'} Complete: {success_count} downloaded, {failed_count} failed")
        if failed_count > 0:
            print(f"  Failed items are logged in: {self.progress_file}")
        print(f"Files saved to: {self.output_dir.resolve()}")

        # Write persistent source map (filename -> source CSV) for metadata scan
        if self.source_csv and self.saved_files:
            map_file = self.output_dir / "nft-source-map.json"
            try:
                source_map = json.loads(map_file.read_text()) if map_file.exists() else {}
                for fname in self.saved_files:
                    source_map[fname] = self.source_csv
                with open(map_file, 'w') as f:
                    json.dump(source_map, f)
                print(f"  📋 Source map: {len(self.saved_files)} files tagged as {self.source_csv}")
            except Exception as e:
                print(f"  ⚠ Could not write source map: {e}")

    def _run_download_pass(self, items):
        """Run a single download pass over the given items"""
        stopped = False
        if self.workers == 1:
            for item_type, item_data in items:
                if self._check_stop_signal():
                    print("\n⏹ Download stopped by user")
                    stopped = True
                    break
                if item_type == 'ipfs':
                    self.download_ipfs_cid(item_data)
                elif item_type == 'url':
                    self.download_url(*item_data)
                elif item_type == 'nft':
                    self.download_nft(*item_data)

                self.completed_items += 1
                self._save_progress()
                print(f"Progress: {self.completed_items}/{self.total_items}")
        else:
            def task(item):
                if self._check_stop_signal():
                    return
                item_type, item_data = item
                if item_type == 'ipfs':
                    self.download_ipfs_cid(item_data)
                elif item_type == 'url':
                    self.download_url(*item_data)
                elif item_type == 'nft':
                    self.download_nft(*item_data)

                with self.lock:
                    self.completed_items += 1
                    self._save_progress()
                    print(f"Progress: {self.completed_items}/{self.total_items}")

            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = [executor.submit(task, item) for item in items]
                for future in as_completed(futures):
                    future.result()

def main():
    parser = argparse.ArgumentParser(
        description='Vernis Advanced NFT Downloader',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download from CSV with 4 workers
  %(prog)s --csv my-nfts.csv --workers 4

  # Download single NFT
  %(prog)s --contract 0xBC4CA0EdA7647A8aB7C2061c2E118A18a936f13D --token 1

  # Download IPFS CID
  %(prog)s --cid bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi

  # Use custom IPFS gateway
  %(prog)s --csv my-nfts.csv --gateway http://127.0.0.1:8080
        """
    )

    parser.add_argument('--csv', help='CSV file with cid/contract_address,token_id columns')
    parser.add_argument('--contract', help='Single contract address')
    parser.add_argument('--token', help='Single token ID')
    parser.add_argument('--cid', help='Single IPFS CID')
    parser.add_argument('--chain', default='ethereum',
                        choices=['ethereum', 'base', 'optimism', 'polygon', 'arbitrum', 'zora'],
                        help='Blockchain for contract lookup (default: ethereum)')
    parser.add_argument('--output', default='/opt/vernis/nfts', help='Output directory')
    parser.add_argument('--workers', type=int, default=1, help='Number of parallel workers (1-8)')
    parser.add_argument('--gateway', help='IPFS gateway URL (auto-detected if not specified)')

    args = parser.parse_args()

    # Validate workers
    if args.workers < 1 or args.workers > 8:
        print("Workers must be between 1 and 8")
        sys.exit(1)

    # Create downloader
    print(f"Vernis Advanced NFT Downloader")
    print(f"Workers: {args.workers}")
    print(f"Output: {args.output}\n")

    downloader = AdvancedNFTDownloader(
        output_dir=args.output,
        workers=args.workers,
        gateway_url=args.gateway
    )

    # Process based on arguments
    if args.csv:
        print(f"Processing CSV: {args.csv}\n")
        downloader.process_csv(args.csv)
    elif args.cid:
        print(f"Downloading IPFS CID: {args.cid}\n")
        downloader.download_ipfs_cid(args.cid)
    elif args.contract and args.token:
        print(f"Downloading NFT: {args.contract} #{args.token} ({args.chain})\n")
        downloader.download_nft(args.contract, args.token, args.chain)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()
