#!/usr/bin/env python3
"""
Vernis CSV Library Fixer
========================
Normalizes all CSV files in csv-library/ to the standard Vernis format:
  contract_address,token_id,name,collection,image_url,metadata_url,opensea_url

Fixes:
- Merges Metadata CIDs into metadata_url column (preserves metadata context)
- Normalizes column names to standard Vernis format
- Handles sparse/merged rows (X.csv forward-fill)
- Converts raw CID dumps (Async.csv) to proper CSV
- Handles multi-line descriptions (Hackatao)
- Adds collection names from filename or data

Usage:
  python3 tools/fix-csv-library.py                    # Fix all, write to csv-library-fixed/
  python3 tools/fix-csv-library.py --dry-run           # Preview without writing
  python3 tools/fix-csv-library.py --in-place          # Overwrite originals (backup first)
  python3 tools/fix-csv-library.py --file Banksta.csv  # Fix a single file
"""

import argparse
import csv
import os
import re
import shutil
import sys

# Standard Vernis CSV header
VERNIS_HEADER = ["contract_address", "token_id", "name", "collection", "image_url", "metadata_url", "opensea_url"]

# CID patterns
CID_RE = re.compile(r'^(Qm[a-zA-Z0-9]{44}|baf[a-z0-9]{50,})$')

# Suffixes that identify non-image rows in name,cid format files
META_SUFFIXES = [" - Metadata", " - Metadata 2"]
SKIP_SUFFIXES = [" - IPFS", " - Index"]  # Not useful for display or metadata


def ipfs_url(cid):
    """Convert raw CID to ipfs:// URL."""
    if not cid:
        return ""
    return f"ipfs://{cid}"


def get_meta_base(name):
    """If name is a metadata row, return the base group name. Otherwise None."""
    for suffix in META_SUFFIXES:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return None


def is_skip_row(name):
    """Check if a row is an IPFS/index row that should be skipped entirely."""
    for suffix in SKIP_SUFFIXES:
        if name.endswith(suffix):
            return True
    return False


def detect_format(filepath):
    """Detect the CSV format by reading the first line."""
    with open(filepath, encoding="utf-8", errors="replace") as f:
        first_line = f.readline().strip()

    # Async.csv: raw CID dump (no commas, has " — CID:")
    if "— CID:" in first_line or ("— Size:" in first_line):
        return "async_dump"

    parts = [p.strip() for p in first_line.split(",")]
    header_set = set(p.lower() for p in parts)

    if header_set == set(h.lower() for h in VERNIS_HEADER):
        return "good"

    if "contract_address" in header_set and "ipfs_cid" in header_set:
        return "hackatao"

    if "contract_address" in header_set and "collectionname" in header_set:
        return "whale_vault"

    if header_set == {"title", "platform", "type", "cid"}:
        return "xcopy"

    if header_set == {"token", "name", "type", "cid"}:
        return "grifters"

    if header_set == {"token", "name", "cid"}:
        return "token_name_cid"

    if header_set == {"name", "cid"}:
        return "name_cid"

    return "unknown"


def collection_from_filename(filepath):
    """Derive collection name from the CSV filename."""
    basename = os.path.splitext(os.path.basename(filepath))[0]
    # Clean up common suffixes
    for suffix in ["_nfts", "_collection", "_OLD"]:
        basename = basename.replace(suffix, "")
    return basename


def fix_good(filepath, collection):
    """Already in correct format — pass through."""
    rows = []
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({h: row.get(h, "") for h in VERNIS_HEADER})
    return rows


def fix_async_dump(filepath, collection):
    """Parse raw CID dump: 'QmXXX — CID: QmXXX — Size: NNN'"""
    seen = set()
    rows = []
    with open(filepath, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Extract CID — try multiple patterns
            # Format: "QmXXX — CID: QmXXX — Size: NNN" or just bare CID
            match = re.search(r'(Qm[a-zA-Z0-9]{44}|baf[a-z0-9]{50,})', line)
            if match:
                cid = match.group(1)
                if cid not in seen:
                    seen.add(cid)
                    rows.append({
                        "contract_address": "",
                        "token_id": "",
                        "name": cid[:20] + "...",
                        "collection": collection,
                        "image_url": ipfs_url(cid),
                        "metadata_url": "",
                        "opensea_url": "",
                    })
    return rows


def fix_name_cid(filepath, collection):
    """Fix name,cid format (Banksta, DOOM Party, Rabble).
    Two-pass: first collect metadata CIDs by group, then merge into image rows."""
    all_rows = []
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            cid = (row.get("cid") or "").strip()
            if not cid or not CID_RE.match(cid):
                continue
            all_rows.append((name, cid))

    # Pass 1: collect metadata CIDs by base group name
    # e.g. "Head - Metadata" → base "Head", "Banksta - Metadata" → base "Banksta"
    meta_by_group = {}
    for name, cid in all_rows:
        base = get_meta_base(name)
        if base is not None:
            meta_by_group[base] = cid

    # Pass 2: build output rows for image entries, attaching metadata CID
    rows = []
    for name, cid in all_rows:
        if get_meta_base(name) is not None:
            continue  # This is a metadata row, already captured above
        if is_skip_row(name):
            continue

        # Find matching metadata: try exact prefix match
        # e.g. image "Head - Human" matches meta group "Head"
        metadata_cid = ""
        for base, meta_cid in meta_by_group.items():
            if name == base or name.startswith(base + " - "):
                metadata_cid = meta_cid
                break

        rows.append({
            "contract_address": "",
            "token_id": "",
            "name": name,
            "collection": collection,
            "image_url": ipfs_url(cid),
            "metadata_url": ipfs_url(metadata_cid),
            "opensea_url": "",
        })
    return rows


def fix_grifters(filepath, collection):
    """Fix token,name,type,cid format — merge Image + Metadata by token."""
    # Group by token_id: collect image and metadata CIDs
    tokens = {}  # token_id → {name, image_cid, metadata_cid}
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            token = (row.get("token") or "").strip()
            name = (row.get("name") or "").strip()
            row_type = (row.get("type") or "").strip()
            cid = (row.get("cid") or "").strip()

            if not cid or not CID_RE.match(cid):
                continue

            if token not in tokens:
                tokens[token] = {"name": name, "image_cid": "", "metadata_cid": ""}

            if row_type == "Image":
                tokens[token]["image_cid"] = cid
            elif row_type == "Metadata":
                tokens[token]["metadata_cid"] = cid

    rows = []
    for token, data in tokens.items():
        if not data["image_cid"]:
            continue
        rows.append({
            "contract_address": "",
            "token_id": token,
            "name": data["name"],
            "collection": collection,
            "image_url": ipfs_url(data["image_cid"]),
            "metadata_url": ipfs_url(data["metadata_cid"]),
            "opensea_url": "",
        })
    return rows


def fix_token_name_cid(filepath, collection):
    """Fix token,name,cid format (MAX PAIN AND FRENS).
    The ALL row is contract-level metadata — stored as collection metadata on each row."""
    rows = []
    contract_meta_cid = ""
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            token = (row.get("token") or "").strip()
            name = (row.get("name") or "").strip()
            cid = (row.get("cid") or "").strip()

            if not cid or not CID_RE.match(cid):
                continue
            if token == "ALL":
                contract_meta_cid = cid
                continue
            if is_skip_row(name):
                continue
            if get_meta_base(name) is not None:
                continue

            rows.append({
                "contract_address": "",
                "token_id": token,
                "name": name,
                "collection": collection,
                "image_url": ipfs_url(cid),
                "metadata_url": ipfs_url(contract_meta_cid),
                "opensea_url": "",
            })
    return rows


def fix_xcopy(filepath, collection):
    """Fix title,platform,type,cid format with sparse/merged rows (X.csv).
    Two-pass: forward-fill titles, then merge Image + Metadata by artwork."""
    # Pass 1: read all rows with forward-filled titles
    all_rows = []
    current_title = ""
    current_platform = ""

    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = (row.get("title") or "").strip()
            platform = (row.get("platform") or "").strip()
            row_type = (row.get("type") or "").strip()
            cid = (row.get("cid") or "").strip()

            if title:
                current_title = title
            if platform:
                current_platform = platform

            if not cid or not CID_RE.match(cid):
                continue

            all_rows.append({
                "title": current_title,
                "platform": current_platform,
                "type": row_type,
                "cid": cid,
            })

    # Pass 2: group by title, merge Image + Metadata
    artworks = {}  # title → {platform, image_cid, metadata_cid}
    for r in all_rows:
        key = r["title"]
        if key not in artworks:
            artworks[key] = {"platform": r["platform"], "image_cid": "", "metadata_cid": ""}
        if r["type"] == "Image":
            artworks[key]["image_cid"] = r["cid"]
        elif r["type"] == "Metadata":
            artworks[key]["metadata_cid"] = r["cid"]

    rows = []
    for title, data in artworks.items():
        if not data["image_cid"]:
            continue
        plat = data["platform"]
        rows.append({
            "contract_address": "",
            "token_id": "",
            "name": title,
            "collection": f"XCOPY - {plat}" if plat else collection,
            "image_url": ipfs_url(data["image_cid"]),
            "metadata_url": ipfs_url(data["metadata_cid"]),
            "opensea_url": "",
        })
    return rows


def fix_hackatao(filepath, collection):
    """Fix contract_address,token_id,ipfs_cid,name,description format with multi-line descriptions."""
    rows = []
    # Use Python's csv module which handles multi-line quoted fields correctly
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            contract = (row.get("contract_address") or "").strip()
            token_id = (row.get("token_id") or "").strip()
            cid = (row.get("ipfs_cid") or "").strip()
            name = (row.get("name") or "").strip()

            if not cid or not CID_RE.match(cid):
                continue

            rows.append({
                "contract_address": contract,
                "token_id": token_id,
                "name": name,
                "collection": collection,
                "image_url": ipfs_url(cid),
                "metadata_url": "",
                "opensea_url": "",
            })
    return rows


def fix_whale_vault(filepath, collection):
    """Fix contract_address,token_id,CollectionName format (no image data)."""
    rows = []
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            contract = (row.get("contract_address") or "").strip()
            token_id = (row.get("token_id") or "").strip()
            coll_name = (row.get("CollectionName") or "").strip()

            if not contract or not token_id:
                continue

            rows.append({
                "contract_address": contract,
                "token_id": token_id.strip('"'),
                "name": "",
                "collection": coll_name or collection,
                "image_url": "",
                "metadata_url": "",
                "opensea_url": "",
            })
    return rows


# Map format names to fix functions
FIXERS = {
    "good": fix_good,
    "async_dump": fix_async_dump,
    "name_cid": fix_name_cid,
    "grifters": fix_grifters,
    "token_name_cid": fix_token_name_cid,
    "xcopy": fix_xcopy,
    "hackatao": fix_hackatao,
    "whale_vault": fix_whale_vault,
}


def write_csv(rows, output_path):
    """Write rows to a proper Vernis CSV file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=VERNIS_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def process_file(filepath, output_dir, dry_run=False, in_place=False):
    """Process a single CSV file."""
    basename = os.path.basename(filepath)
    fmt = detect_format(filepath)
    collection = collection_from_filename(filepath)

    if fmt == "unknown":
        print(f"  SKIP  {basename} — unknown format, needs manual review")
        return None

    if fmt == "good":
        print(f"  OK    {basename} — already in Vernis format")
        if not in_place:
            # Copy as-is to output dir
            if not dry_run:
                out_path = os.path.join(output_dir, basename)
                os.makedirs(output_dir, exist_ok=True)
                shutil.copy2(filepath, out_path)
        return "ok"

    fixer = FIXERS.get(fmt)
    if not fixer:
        print(f"  SKIP  {basename} — no fixer for format '{fmt}'")
        return None

    try:
        rows = fixer(filepath, collection)
    except Exception as e:
        print(f"  ERROR {basename} — {e}")
        return None

    if dry_run:
        print(f"  FIX   {basename} — {fmt} → {len(rows)} image rows (dry run)")
        return "fixed"

    if in_place:
        out_path = filepath
    else:
        out_path = os.path.join(output_dir, basename)

    write_csv(rows, out_path)
    print(f"  FIX   {basename} — {fmt} → {len(rows)} image rows → {out_path}")
    return "fixed"


def main():
    parser = argparse.ArgumentParser(
        description="Normalize CSV files in csv-library/ to standard Vernis format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 tools/fix-csv-library.py                     # Fix all → csv-library-fixed/
  python3 tools/fix-csv-library.py --dry-run            # Preview changes
  python3 tools/fix-csv-library.py --in-place           # Overwrite originals
  python3 tools/fix-csv-library.py --file Banksta.csv   # Fix single file
        """,
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument("--in-place", action="store_true", help="Overwrite original files")
    parser.add_argument("--file", help="Process a single file (name only, looked up in csv-library/)")
    parser.add_argument("--csv-dir", default=None, help="Path to csv-library/ directory")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: csv-library-fixed/)")

    args = parser.parse_args()

    # Find csv-library relative to this script or cwd
    if args.csv_dir:
        csv_dir = args.csv_dir
    else:
        # Try relative to script location first, then cwd
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_dir = os.path.dirname(script_dir)
        csv_dir = os.path.join(project_dir, "csv-library")
        if not os.path.isdir(csv_dir):
            csv_dir = os.path.join(os.getcwd(), "csv-library")

    if not os.path.isdir(csv_dir):
        print(f"Error: csv-library directory not found at {csv_dir}")
        print("Use --csv-dir to specify the path")
        sys.exit(1)

    output_dir = args.output_dir or os.path.join(os.path.dirname(csv_dir), "csv-library-fixed")

    print(f"CSV Library Fixer")
    print(f"  Source:  {csv_dir}")
    if not args.in_place:
        print(f"  Output:  {output_dir}")
    if args.dry_run:
        print(f"  Mode:    DRY RUN")
    elif args.in_place:
        print(f"  Mode:    IN-PLACE (overwriting originals)")
    print()

    # Collect files to process
    if args.file:
        filepath = os.path.join(csv_dir, args.file)
        if not os.path.isfile(filepath):
            print(f"Error: {filepath} not found")
            sys.exit(1)
        files = [filepath]
    else:
        files = sorted(
            os.path.join(csv_dir, f)
            for f in os.listdir(csv_dir)
            if f.endswith(".csv")
        )

    stats = {"ok": 0, "fixed": 0, "skipped": 0, "errors": 0}

    for filepath in files:
        result = process_file(filepath, output_dir, dry_run=args.dry_run, in_place=args.in_place)
        if result == "ok":
            stats["ok"] += 1
        elif result == "fixed":
            stats["fixed"] += 1
        else:
            stats["skipped"] += 1

    print()
    print(f"Done: {stats['ok']} already good, {stats['fixed']} fixed, {stats['skipped']} skipped")


if __name__ == "__main__":
    main()
