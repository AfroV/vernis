#!/usr/bin/env python3
"""
Known Origin IPFS CID Scraper
Scrapes IPFS CIDs from Known Origin NFT marketplace

Usage:
    python known_origin_scraper.py [--output FILE] [--limit N] [--start-id ID]

Examples:
    python known_origin_scraper.py
    python known_origin_scraper.py --output known_origin.csv --limit 100
    python known_origin_scraper.py --start-id 1000 --limit 500

Note: This scraper fetches metadata directly from Known Origin's IPFS storage.
Known Origin uses predictable token URI patterns that we can enumerate.
"""

import argparse
import csv
import json
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from concurrent.futures import ThreadPoolExecutor, as_completed

# Known Origin contract metadata base URIs
# V2: https://ipfs.io/ipfs/QmXXXXX/{tokenId}
# V3: Uses token-specific IPFS CIDs

# Known public gateways to try
IPFS_GATEWAYS = [
    "https://ipfs.io/ipfs/",
    "https://cloudflare-ipfs.com/ipfs/",
    "https://gateway.pinata.cloud/ipfs/",
    "https://dweb.link/ipfs/",
]

# Known Origin edition metadata base (V2)
KO_METADATA_BASE = "https://ipfs.io/ipfs/"

# Known collection of Known Origin CIDs (can be expanded)
KNOWN_KO_CIDS = []

def fetch_url(url, timeout=15):
    """Fetch URL with timeout and error handling"""
    headers = {
        "User-Agent": "Vernis NFT Scraper/1.0",
        "Accept": "application/json"
    }

    for gateway in IPFS_GATEWAYS:
        try:
            # If it's an IPFS URL, try different gateways
            if "ipfs" in url.lower():
                cid = extract_ipfs_cid(url)
                if cid:
                    test_url = f"{gateway}{cid}"
                    req = Request(test_url, headers=headers)
                    with urlopen(req, timeout=timeout) as response:
                        return json.loads(response.read().decode('utf-8'))

            # Try direct URL
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception:
            continue

    return None

def extract_ipfs_cid(url):
    """Extract IPFS CID from various URL formats"""
    if not url:
        return None

    url = str(url)

    # Handle ipfs:// URLs
    if url.startswith("ipfs://"):
        cid = url.replace("ipfs://", "").split("/")[0].split("?")[0]
        return cid

    # Handle gateway URLs
    if "/ipfs/" in url:
        parts = url.split("/ipfs/")
        if len(parts) > 1:
            cid = parts[1].split("/")[0].split("?")[0]
            return cid

    # Check if it's just a raw CID (starts with Qm or bafy)
    if url.startswith("Qm") and len(url) >= 46:
        return url.split("/")[0].split("?")[0]
    if url.startswith("bafy") and len(url) >= 59:
        return url.split("/")[0].split("?")[0]

    return None

def fetch_known_origin_edition(edition_id):
    """
    Fetch a specific Known Origin edition metadata.
    Known Origin editions have metadata stored on IPFS.
    """

    # Known Origin V2 token URI pattern
    # They use a base IPFS hash with edition numbers
    # Example: ipfs://QmPMc4tcBsMqLRuCQtPmPe84bpSjrC3Ky7t3JWuHXYB4aS/{edition_id}

    # Try common Known Origin metadata patterns
    patterns = [
        f"https://ipfs.io/ipfs/QmPMc4tcBsMqLRuCQtPmPe84bpSjrC3Ky7t3JWuHXYB4aS/{edition_id}",
        f"https://knownorigin.io/edition/{edition_id}",
    ]

    for pattern in patterns:
        try:
            data = fetch_url(pattern)
            if data:
                return data
        except Exception:
            continue

    return None

def fetch_from_reservoir(contract, token_id):
    """Fetch NFT metadata from Reservoir API (public, no auth needed)"""
    url = f"https://api.reservoir.tools/tokens/v7?tokens={contract}:{token_id}"

    try:
        req = Request(url, headers={
            "User-Agent": "Vernis NFT Scraper/1.0",
            "Accept": "application/json"
        })
        with urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
            tokens = data.get("tokens", [])
            if tokens:
                return tokens[0].get("token", {})
    except Exception as e:
        pass

    return None

def fetch_collection_from_reservoir(contract, limit=100, continuation=None):
    """Fetch collection tokens from Reservoir API"""
    url = f"https://api.reservoir.tools/tokens/v7?collection={contract}&limit={limit}"
    if continuation:
        url += f"&continuation={continuation}"

    try:
        req = Request(url, headers={
            "User-Agent": "Vernis NFT Scraper/1.0",
            "Accept": "application/json"
        })
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Error fetching collection: {e}", file=sys.stderr)
        return None

def scrape_known_origin(output_file="known_origin_nfts.csv", limit=None, verbose=False):
    """Main scraping function using Reservoir API"""

    # Known Origin contract addresses
    contracts = [
        "0xfbeef911dc5821886e1dda71586d90ed28174b7d",  # KO V1
        "0xabb3738f04dc2ec20f4ae4462c3d069d02ae045b",  # KO V2
    ]

    all_nfts = []

    for contract in contracts:
        print(f"Fetching from contract {contract[:10]}...")
        continuation = None
        contract_count = 0

        while True:
            data = fetch_collection_from_reservoir(contract, limit=100, continuation=continuation)

            if not data:
                break

            tokens = data.get("tokens", [])
            if not tokens:
                break

            for item in tokens:
                token = item.get("token", {})
                name = token.get("name", "")
                image = token.get("image", "") or token.get("imageSmall", "")
                media = token.get("media", "")

                # Extract IPFS CID from image or media URL
                cid = extract_ipfs_cid(image) or extract_ipfs_cid(media)

                if cid:
                    all_nfts.append({
                        "name": name or f"Token {token.get('tokenId', '')}",
                        "cid": cid,
                        "token_id": token.get("tokenId", ""),
                        "contract": contract,
                        "collection": token.get("collection", {}).get("name", "Known Origin")
                    })
                    contract_count += 1

                    if verbose:
                        print(f"  Found: {name} - {cid[:20]}...")

                if limit and len(all_nfts) >= limit:
                    break

            continuation = data.get("continuation")
            if not continuation or (limit and len(all_nfts) >= limit):
                break

            time.sleep(0.3)  # Rate limiting

        print(f"  Found {contract_count} NFTs from this contract")

        if limit and len(all_nfts) >= limit:
            all_nfts = all_nfts[:limit]
            break

    print(f"\nTotal: {len(all_nfts)} NFTs with IPFS CIDs")

    # Write to CSV
    if all_nfts:
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["name", "cid"])

            for nft in all_nfts:
                writer.writerow([nft["name"], nft["cid"]])

        print(f"Saved to {output_file}")

        # Also save detailed version
        detailed_file = output_file.replace('.csv', '_detailed.csv')
        with open(detailed_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=["name", "cid", "token_id", "contract", "collection"])
            writer.writeheader()
            writer.writerows(all_nfts)

        print(f"Detailed data saved to {detailed_file}")
    else:
        print("No NFTs found to save.")

    return all_nfts

def main():
    parser = argparse.ArgumentParser(
        description="Scrape IPFS CIDs from Known Origin NFT marketplace"
    )
    parser.add_argument(
        "--output", "-o",
        default="known_origin_nfts.csv",
        help="Output CSV file (default: known_origin_nfts.csv)"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        help="Limit number of NFTs to scrape"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed progress"
    )

    args = parser.parse_args()

    scrape_known_origin(
        output_file=args.output,
        limit=args.limit,
        verbose=args.verbose
    )

if __name__ == "__main__":
    main()
