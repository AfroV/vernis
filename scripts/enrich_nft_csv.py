#!/usr/bin/env python3
"""
NFT CSV Enricher
Adds IPFS CIDs to CSV files that only have contract addresses and token IDs

Usage:
    python enrich_nft_csv.py input.csv [--output output.csv]

Examples:
    python enrich_nft_csv.py hackatao_collection.csv
    python enrich_nft_csv.py my_nfts.csv --output my_nfts_with_cids.csv

The script uses the Reservoir API (free, no auth needed) to fetch metadata
and extract IPFS CIDs from image URLs.
"""

import argparse
import csv
import json
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from pathlib import Path

# Rate limiting settings
RATE_LIMIT_DELAY = 0.25  # seconds between requests
BATCH_SIZE = 50  # tokens per batch request

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

def fetch_token_batch(tokens_list):
    """
    Fetch metadata for multiple tokens in a single request using Reservoir API
    tokens_list: list of (contract, token_id) tuples
    """
    # Build the tokens query parameter
    tokens_param = "&".join([f"tokens={c}:{t}" for c, t in tokens_list])
    url = f"https://api.reservoir.tools/tokens/v7?{tokens_param}&includeAttributes=false&includeTopBid=false"

    try:
        req = Request(url, headers={
            "User-Agent": "Vernis NFT Enricher/1.0",
            "Accept": "application/json"
        })
        with urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get("tokens", [])
    except Exception as e:
        print(f"  Error fetching batch: {e}", file=sys.stderr)
        return []

def fetch_single_token(contract, token_id):
    """Fetch a single token's metadata from Reservoir API"""
    url = f"https://api.reservoir.tools/tokens/v7?tokens={contract}:{token_id}"

    try:
        req = Request(url, headers={
            "User-Agent": "Vernis NFT Enricher/1.0",
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

def enrich_csv(input_file, output_file=None, verbose=False):
    """
    Read a CSV with contract_address and token_id columns,
    fetch IPFS CIDs, and save an enriched version.
    """
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_file}", file=sys.stderr)
        return False

    if output_file is None:
        output_file = str(input_path.with_stem(input_path.stem + "_enriched"))

    # Read input CSV
    rows = []
    fieldnames = None

    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not rows:
        print("No rows found in CSV", file=sys.stderr)
        return False

    # Find contract and token_id columns (case-insensitive)
    contract_col = None
    token_col = None

    for col in fieldnames:
        col_lower = col.lower()
        if col_lower in ['contract_address', 'contract', 'address']:
            contract_col = col
        elif col_lower in ['token_id', 'tokenid', 'id', 'token']:
            token_col = col

    if not contract_col:
        print("Error: No contract_address column found", file=sys.stderr)
        return False
    if not token_col:
        print("Error: No token_id column found", file=sys.stderr)
        return False

    print(f"Found {len(rows)} tokens to enrich")
    print(f"Using columns: {contract_col}, {token_col}")

    # Check if CID column already exists
    cid_col = None
    for col in fieldnames:
        if col.lower() in ['cid', 'ipfs_cid', 'image_cid']:
            cid_col = col
            break

    # Add new columns if needed
    new_fieldnames = list(fieldnames)
    if 'cid' not in [f.lower() for f in fieldnames]:
        new_fieldnames.append('cid')
        cid_col = 'cid'
    if 'name' not in [f.lower() for f in fieldnames]:
        new_fieldnames.append('name')
    if 'image_url' not in [f.lower() for f in fieldnames]:
        new_fieldnames.append('image_url')

    # Process in batches
    enriched_count = 0
    failed_count = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        batch_tokens = [(row[contract_col], row[token_col]) for row in batch]

        print(f"Processing batch {i // BATCH_SIZE + 1}/{(len(rows) + BATCH_SIZE - 1) // BATCH_SIZE}...")

        # Fetch batch
        results = fetch_token_batch(batch_tokens)

        # Map results by contract:tokenId
        results_map = {}
        for item in results:
            token = item.get("token", {})
            key = f"{token.get('contract', '').lower()}:{token.get('tokenId', '')}"
            results_map[key] = token

        # Enrich rows
        for row in batch:
            key = f"{row[contract_col].lower()}:{row[token_col]}"
            token_data = results_map.get(key)

            if token_data:
                image = token_data.get("image", "") or token_data.get("imageSmall", "")
                media = token_data.get("media", "")

                # Extract CID
                cid = extract_ipfs_cid(image) or extract_ipfs_cid(media)

                if cid:
                    row[cid_col] = cid
                    enriched_count += 1
                    if verbose:
                        print(f"  + {token_data.get('name', row[token_col])}: {cid[:20]}...")
                else:
                    # Store the HTTP URL as fallback
                    row['image_url'] = image or media
                    if verbose:
                        print(f"  ~ {token_data.get('name', row[token_col])}: No IPFS CID (HTTP fallback)")

                row['name'] = token_data.get('name', '')
            else:
                failed_count += 1
                if verbose:
                    print(f"  ! Failed to fetch: {row[contract_col]}:{row[token_col]}")

        time.sleep(RATE_LIMIT_DELAY)

    # Write enriched CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nResults:")
    print(f"  Enriched with CIDs: {enriched_count}")
    print(f"  Failed to fetch: {failed_count}")
    print(f"  Output saved to: {output_file}")

    return True

def main():
    parser = argparse.ArgumentParser(
        description="Enrich NFT CSV with IPFS CIDs using Reservoir API"
    )
    parser.add_argument(
        "input",
        help="Input CSV file with contract_address and token_id columns"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output CSV file (default: input_enriched.csv)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed progress"
    )

    args = parser.parse_args()

    success = enrich_csv(
        input_file=args.input,
        output_file=args.output,
        verbose=args.verbose
    )

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
