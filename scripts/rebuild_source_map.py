#!/usr/bin/env python3
"""
Rebuild nft-source-map.json by walking each CSV in /opt/vernis/csv-library/
and tagging matching files on disk with their owning CSV. Run this after
the historic 'every run claims every file' bug to recover proper mappings.

If multiple CSVs reference the same CID (true cross-collection sharing),
the first CSV (alphabetically) wins.
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

EXTENSIONS = {".gif", ".png", ".jpg", ".jpeg", ".mp4", ".glb", ".html",
              ".bin", ".webp", ".svg", ".avif", ".json", ".txt"}


def collect_identifiers(csv_path):
    """Mirror the downloader's CSV parsing — return identifier strings."""
    ids = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cid = (row.get("cid") or row.get("CID") or row.get("ipfs_cid")
                       or row.get("image_cid") or "").strip()
                cid = cid.replace("ipfs://", "")
                if not cid:
                    metadata_url = (row.get("metadata_url") or "").strip()
                    if metadata_url:
                        for prefix in ("Qm", "bafy"):
                            idx = metadata_url.find(prefix)
                            if idx >= 0:
                                cid = metadata_url[idx:].split("/")[0].split("?")[0]
                                break
                if cid and (cid.startswith("Qm") or cid.startswith("bafy")):
                    ids.append(cid.split("/")[0])
                    continue
                contract = (row.get("contract_address") or "").strip()
                token_id = (row.get("token_id") or "").strip()
                if contract and token_id:
                    ids.append(f"{contract}_{token_id}")
    except Exception as e:
        print(f"  ⚠ Could not parse {csv_path.name}: {e}", file=sys.stderr)
    return ids


def main():
    nft_dir = Path("/opt/vernis/nfts")
    csv_dir = Path("/opt/vernis/csv-library")
    map_file = nft_dir / "nft-source-map.json"

    if not nft_dir.exists() or not csv_dir.exists():
        print("ERROR: NFT or CSV-library dir missing", file=sys.stderr)
        sys.exit(2)

    backup = map_file.with_suffix(".json.bak")
    if map_file.exists() and not backup.exists():
        backup.write_bytes(map_file.read_bytes())
        print(f"Backed up old source map → {backup}")

    # Scan the NFT directory ONCE. Build two indexes:
    #   exact[stem]    -> [filenames]                (filename starts as <stem>.<ext>)
    #   prefix[stem]   -> [filenames with <stem>_*]
    print(f"Scanning {nft_dir}...")
    exact = defaultdict(list)
    prefix = defaultdict(list)
    file_count = 0
    for entry in nft_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in EXTENSIONS:
            continue
        file_count += 1
        stem = entry.stem
        exact[stem].append(entry.name)
        # Prefix index by everything before the first underscore
        if "_" in stem:
            base = stem.split("_", 1)[0]
            prefix[base].append(entry.name)
    print(f"  indexed {file_count} files ({len(exact)} unique stems)")

    new_map = {}
    csvs = sorted(csv_dir.glob("*.csv"))
    print(f"Walking {len(csvs)} CSVs...")
    for csv_path in csvs:
        ids = collect_identifiers(csv_path)
        if not ids:
            continue
        tagged = 0
        for ident in ids:
            for fname in exact.get(ident, ()):
                if fname not in new_map:
                    new_map[fname] = csv_path.name
                    tagged += 1
            for fname in prefix.get(ident, ()):
                if fname not in new_map:
                    new_map[fname] = csv_path.name
                    tagged += 1
        print(f"  {csv_path.name}: {tagged} files (from {len(ids)} CSV ids)")

    map_file.write_text(json.dumps(new_map, indent=2))
    print(f"\nWrote {len(new_map)} entries → {map_file}")


if __name__ == "__main__":
    main()
