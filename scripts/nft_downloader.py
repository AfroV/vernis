#!/usr/bin/env python3
"""
Vernis v3 - NFT Downloader
Downloads NFT media from contract addresses and token IDs
Supports CSV batch mode or single NFT mode
"""
import argparse
import csv
import sys
import os
import shutil
from pathlib import Path
import requests
import json
import time

def download_nft(contract, token_id, output_dir):
    """Download a single NFT"""
    try:
        # Try OpenSea API first (example - adjust for your needs)
        url = f"https://api.opensea.io/api/v1/asset/{contract}/{token_id}/"
        headers = {
            "Accept": "application/json",
            "User-Agent": "Vernis/3.0"
        }

        print(f"Fetching metadata for {contract} #{token_id}...")
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code != 200:
            print(f"  Error: API returned {response.status_code}")
            return False

        data = response.json()

        # Get image URL
        image_url = data.get('image_url') or data.get('image_original_url')
        if not image_url:
            print(f"  No image URL found")
            return False

        # Download image
        print(f"Vernis NFT Downloader: {image_url}")
        img_response = requests.get(image_url, timeout=60)

        if img_response.status_code != 200:
            print(f"  Error downloading image: {img_response.status_code}")
            return False

        # Determine file extension
        content_type = img_response.headers.get('content-type', '')
        ext = '.jpg'
        if 'png' in content_type:
            ext = '.png'
        elif 'gif' in content_type:
            ext = '.gif'
        elif 'webp' in content_type:
            ext = '.webp'
        elif 'mp4' in content_type or 'video' in content_type:
            ext = '.mp4'

        # Save file
        filename = f"{contract}_{token_id}{ext}"
        filepath = Path(output_dir) / filename

        with open(filepath, 'wb') as f:
            f.write(img_response.content)

        print(f"  Saved: {filename}")
        return True

    except Exception as e:
        print(f"  Error: {e}")
        return False

def process_csv(csv_path, output_dir):
    """Process CSV file with contract addresses and token IDs"""
    success = 0
    failed = 0

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Check disk space before each download (stop if less than 100MB free)
            try:
                total, used, free = shutil.disk_usage(output_dir)
                free_mb = free // (1024 * 1024)
                if free_mb < 100:
                    print(f"\nStopping: Disk space low ({free_mb}MB free). Need at least 100MB.")
                    break
            except Exception:
                pass

            contract = row.get('contract_address', '').strip()
            token_id = row.get('token_id', '').strip()

            if not contract or not token_id:
                continue

            if download_nft(contract, token_id, output_dir):
                success += 1
            else:
                failed += 1

            # Rate limiting
            time.sleep(1)

    print(f"\nComplete: {success} downloaded, {failed} failed")

def main():
    parser = argparse.ArgumentParser(description='Vernis NFT Downloader')
    print("Vernis NFT Downloader starting...")
    parser.add_argument('--csv', help='CSV file with contract_address,token_id columns')
    parser.add_argument('--contract', help='Single contract address')
    parser.add_argument('--token', help='Single token ID')
    parser.add_argument('--output', default='/opt/vernis/nfts', help='Output directory')

    args = parser.parse_args()

    # Create output directory
    Path(args.output).mkdir(parents=True, exist_ok=True)

    if args.csv:
        print(f"Processing CSV: {args.csv}")
        process_csv(args.csv, args.output)
    elif args.contract and args.token:
        print(f"Downloading single NFT: {args.contract} #{args.token}")
        download_nft(args.contract, args.token, args.output)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()
