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
import re
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

    def __init__(self, output_dir="nfts", workers=1, gateway_url=None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.workers = workers
        self.session = requests.Session()

        # IPFS support
        self.ipfs_manager = IPFSManager()
        if gateway_url:
            self.ipfs_manager.gateway_url = gateway_url
        else:
            self.ipfs_manager.detect_gateway()

        self.gateway_url = self.ipfs_manager.get_gateway_url()

        # CID pattern for IPFS links
        self.cid_pattern = re.compile(
            r'(?:https?://[^/\s]*ipfs[^/\s]*/(?:ipfs/)?|ipfs://)?'
            r'(?:(Qm[a-zA-Z0-9]{44})|(baf[a-z0-9]{50,}))',
            re.I
        )

        # Progress tracking
        self.downloaded = set()
        self.progress_file = self.output_dir / "download_progress.json"
        self.lock = threading.Lock()
        self.completed_items = 0
        self.total_items = 0

        self._load_progress()

    def _load_progress(self):
        """Load previously downloaded files"""
        if self.progress_file.exists():
            try:
                data = json.load(open(self.progress_file))
                self.downloaded = set(data.get("downloaded", []))
                print(f"Loaded {len(self.downloaded)} previously downloaded items")
            except:
                pass

    def _save_progress(self):
        """Save download progress"""
        with self.lock:
            json.dump(
                {
                    "downloaded": list(self.downloaded),
                    "completed": self.completed_items,
                    "total": self.total_items
                },
                open(self.progress_file, "w"),
                indent=2
            )

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

    def _download_with_retry(self, url, retries=5, timeout=30):
        """Download with retries"""
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=timeout)
                if response.status_code == 200 and len(response.content) > 100:
                    return response.content
            except:
                pass

            if attempt < retries - 1:
                time.sleep(2)  # Wait before retry

        return None

    def _detect_file_type(self, data):
        """Detect file type from content"""
        if data.startswith(b'<!DOCTYPE html'):
            return ".html"
        elif data.startswith(b'\x89PNG'):
            return ".png"
        elif data.startswith(b'\xff\xd8\xff'):
            return ".jpg"
        elif data.startswith(b'GIF8'):
            return ".gif"
        elif len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return ".webp"
        elif len(data) >= 8 and data[4:8] in [b'ftyp', b'mdat', b'moov', b'wide']:
            return ".mp4"
        elif data.startswith(b'glTF'):
            return ".glb"
        else:
            try:
                json.loads(data)
                return ".json"
            except:
                return ".bin"

    def _file_exists(self, identifier):
        """Check if file already exists with any extension"""
        extensions = [".json", ".gif", ".png", ".jpg", ".mp4", ".glb", ".html", ".bin", ".webp"]
        return any((self.output_dir / f"{identifier}{ext}").exists() for ext in extensions)

    def download_ipfs_cid(self, cid, nested=False):
        """Download IPFS CID and optionally follow nested CIDs"""
        cid = cid.strip()

        # Check if already downloaded this session
        with self.lock:
            if cid in self.downloaded:
                return True
            self.downloaded.add(cid)

        # Check if file exists
        if self._file_exists(cid):
            print(f"  ✓ Already have: {cid}")

            # If exists, check for nested CIDs to download
            if not nested:
                for ext in [".json", ".html"]:
                    filepath = self.output_dir / f"{cid}{ext}"
                    if filepath.exists():
                        try:
                            content = filepath.read_text(encoding="utf-8", errors="ignore")
                            if ext == ".json":
                                metadata = json.loads(content)
                                nested_cids = self._extract_cids_from_json(metadata, cid)
                            else:
                                nested_cids = [
                                    match.group(1) or match.group(2)
                                    for match in self.cid_pattern.finditer(content)
                                    if (match.group(1) or match.group(2)) != cid
                                ]

                            for nested_cid in nested_cids:
                                if not self._file_exists(nested_cid):
                                    self.download_ipfs_cid(nested_cid, nested=True)
                        except:
                            pass

            return True

        # Download from IPFS
        print(f"  ⬇ Downloading CID: {cid}")
        url = f"{self.gateway_url}/ipfs/{cid}"
        data = self._download_with_retry(url)

        if not data:
            print(f"  ✗ Failed to download: {cid}")
            return False

        # Detect file type and save
        ext = self._detect_file_type(data)
        filepath = self.output_dir / f"{cid}{ext}"
        filepath.write_bytes(data)

        print(f"  ✓ Saved: {cid}{ext}")
        self._save_progress()

        # Extract and download nested CIDs
        if ext in [".json", ".html"] and not nested:
            try:
                content = data.decode("utf-8", errors="ignore")

                if ext == ".json":
                    metadata = json.loads(content)
                    nested_cids = self._extract_cids_from_json(metadata, cid)
                else:
                    nested_cids = [
                        match.group(1) or match.group(2)
                        for match in self.cid_pattern.finditer(content)
                        if (match.group(1) or match.group(2)) != cid
                    ]

                if nested_cids:
                    print(f"    Found {len(nested_cids)} nested CIDs")
                    for nested_cid in nested_cids:
                        if not self._file_exists(nested_cid):
                            self.download_ipfs_cid(nested_cid, nested=True)
            except:
                pass

        return True

    def download_nft(self, contract, token_id):
        """Download NFT from contract address and token ID"""
        identifier = f"{contract}_{token_id}"

        # Check if already downloaded
        with self.lock:
            if identifier in self.downloaded:
                return True
            self.downloaded.add(identifier)

        if self._file_exists(identifier):
            print(f"  ✓ Already have: {identifier}")
            return True

        try:
            # Try OpenSea API
            url = f"https://api.opensea.io/api/v1/asset/{contract}/{token_id}/"
            headers = {
                "Accept": "application/json",
                "User-Agent": "Vernis/3.0"
            }

            print(f"Fetching metadata for {contract} #{token_id}...")
            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code != 200:
                print(f"  ✗ API error: {response.status_code}")
                return False

            data = response.json()

            # Get image URL
            image_url = data.get('image_url') or data.get('image_original_url')
            if not image_url:
                print(f"  ✗ No image URL found")
                return False

            # Check if it's an IPFS URL
            cid_match = self.cid_pattern.search(image_url)
            if cid_match:
                # It's IPFS - download via IPFS gateway
                cid = cid_match.group(1) or cid_match.group(2)
                return self.download_ipfs_cid(cid)

            # Regular HTTP download
            print(f"  ⬇ Downloading: {image_url}")
            img_data = self._download_with_retry(image_url, timeout=60)

            if not img_data:
                print(f"  ✗ Failed to download image")
                return False

            # Detect file type
            ext = self._detect_file_type(img_data)
            filepath = self.output_dir / f"{identifier}{ext}"
            filepath.write_bytes(img_data)

            print(f"  ✓ Saved: {identifier}{ext}")
            self._save_progress()
            return True

        except Exception as e:
            print(f"  ✗ Error: {e}")
            return False

    def process_csv(self, csv_path):
        """Process CSV file with either CIDs or contract addresses"""
        items = []

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Check for CID column
                cid = (row.get("cid") or row.get("CID") or "").strip()

                # Check for metadata_url column
                if not cid:
                    metadata_url = (row.get("metadata_url") or row.get("metadataUrl") or "").strip()
                    if metadata_url:
                        match = self.cid_pattern.search(metadata_url)
                        if match:
                            cid = match.group(1) or match.group(2)

                # Check for contract address + token ID
                contract = row.get('contract_address', '').strip()
                token_id = row.get('token_id', '').strip()

                if cid and cid not in ["See CSV", "On-Chain", "Arweave", "--"]:
                    items.append(('ipfs', cid))
                elif contract and token_id:
                    items.append(('nft', (contract, token_id)))

        self.total_items = len(items)
        print(f"\nFound {self.total_items} items to download")

        # Save initial progress
        self._save_progress()

        # Download with workers
        if self.workers == 1:
            # Single-threaded
            for item_type, item_data in items:
                if item_type == 'ipfs':
                    self.download_ipfs_cid(item_data)
                else:
                    self.download_nft(*item_data)

                self.completed_items += 1
                self._save_progress()
                print(f"Progress: {self.completed_items}/{self.total_items}")
        else:
            # Multi-threaded
            def task(item):
                item_type, item_data = item
                if item_type == 'ipfs':
                    self.download_ipfs_cid(item_data)
                else:
                    self.download_nft(*item_data)

                with self.lock:
                    self.completed_items += 1
                    self._save_progress()
                    print(f"Progress: {self.completed_items}/{self.total_items}")

            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = [executor.submit(task, item) for item in items]
                for future in as_completed(futures):
                    future.result()

        print(f"\n✓ Complete: Downloaded {len(self.downloaded)} items")
        print(f"Files saved to: {self.output_dir.resolve()}")

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
        print(f"Downloading NFT: {args.contract} #{args.token}\n")
        downloader.download_nft(args.contract, args.token)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()
