#!/usr/bin/env python3
"""
Vernis — Directory-CID Artifact Cleanup
========================================
One-shot repair for NFT collections whose CSV CIDs are IPFS *directory*
CIDs (folder-wrapped tokens) rather than single-image CIDs — e.g. the
Hackatao "fixed" CSV.

When the advanced downloader is handed a directory CID it (a) saves the
gateway's auto-generated HTML directory-index page as a bogus ".html"
artwork, and (b) downloads the real image twice — once via its directory
sub-path (`<dirCID>_Name.jpg`) and once via the file's own bare content
CID (`<imageCID>.jpg`). The result is a pile of near-identical-looking
files with different hashes in manage.html.

This tool removes both kinds of junk from the nfts directory:
  1. Every ".html" file that is an IPFS directory-index page.
  2. For each set of byte-identical media files, all but one copy
     (keeping the human-readable `<cid>_Name.ext` form when present).
It also prunes the deleted names from nft-source-map.json and
download_progress.json so the Library "Remove files" action and the
downloader's resume logic stay consistent.

Defaults to DRY RUN. Nothing is deleted unless you pass --apply.

Usage:
  python3 cleanup-directory-cid-artifacts.py                 # dry run, /opt/vernis/nfts
  python3 cleanup-directory-cid-artifacts.py --dir /opt/vernis/nfts
  python3 cleanup-directory-cid-artifacts.py --apply         # actually delete
"""

import argparse
import hashlib
import json
import os
import re
import sys

# Marker present in every IPFS gateway directory-listing page.
DIR_INDEX_MARKERS = (
    b"directory of content-addressed files hosted on IPFS",
    b"Index of ",
)

MEDIA_EXTS = {".gif", ".jpg", ".jpeg", ".png", ".mp4", ".webp", ".svg", ".avif", ".glb"}

# A bare content-addressed identifier: Qm... (CIDv0) or baf... (CIDv1).
BARE_CID_RE = re.compile(r"^(Qm[A-Za-z0-9]{44}|baf[a-z0-9]{50,})$")
# A human-readable variant produced by the downloader: <cid>_SomeName
NAMED_CID_RE = re.compile(r"^(Qm[A-Za-z0-9]{44}|baf[a-z0-9]{50,})_.+")

# Bookkeeping files that live in the nfts dir but are not artworks.
SIDECAR_FILES = {"download_progress.json", "nft-source-map.json"}


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_directory_index_html(path):
    """True if the .html file is an IPFS gateway directory-listing page."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    return any(m in head for m in DIR_INDEX_MARKERS)


def pick_keeper(names):
    """Choose which file to keep from a set of byte-identical filenames.
    Prefer the human-readable `<cid>_Name.ext` form; fall back to the
    lexicographically smallest name for determinism."""
    named = sorted(n for n in names if NAMED_CID_RE.match(os.path.splitext(n)[0]))
    if named:
        return named[0]
    return sorted(names)[0]


def main():
    parser = argparse.ArgumentParser(
        description="Remove IPFS directory-index HTML pages and byte-identical "
                    "duplicate images left behind by directory-CID collections.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dir", default="/opt/vernis/nfts", help="NFT directory (default: /opt/vernis/nfts)")
    parser.add_argument("--apply", action="store_true", help="Actually delete files (default: dry run)")
    args = parser.parse_args()

    nfts_dir = args.dir
    if not os.path.isdir(nfts_dir):
        print(f"Error: {nfts_dir} is not a directory")
        sys.exit(1)

    all_files = sorted(
        f for f in os.listdir(nfts_dir)
        if os.path.isfile(os.path.join(nfts_dir, f))
    )

    # --- Phase A: IPFS directory-index HTML pages ---
    html_to_delete = []
    for fname in all_files:
        if fname.lower().endswith(".html") and is_directory_index_html(os.path.join(nfts_dir, fname)):
            html_to_delete.append(fname)

    # --- Phase B: byte-identical media duplicates ---
    by_hash = {}
    for fname in all_files:
        ext = os.path.splitext(fname)[1].lower()
        if ext not in MEDIA_EXTS:
            continue
        digest = md5_of(os.path.join(nfts_dir, fname))
        by_hash.setdefault(digest, []).append(fname)

    dup_to_delete = []  # (deleted, kept) pairs for reporting
    for digest, names in by_hash.items():
        if len(names) < 2:
            continue
        keeper = pick_keeper(names)
        for n in names:
            if n != keeper:
                dup_to_delete.append((n, keeper))

    to_delete = set(html_to_delete) | {d for d, _ in dup_to_delete}

    # --- Report ---
    mode = "APPLY (deleting)" if args.apply else "DRY RUN (no changes)"
    print(f"Directory-CID artifact cleanup — {mode}")
    print(f"  Dir: {nfts_dir}")
    print(f"  Total files: {len(all_files)}\n")

    print(f"IPFS directory-index HTML pages to remove: {len(html_to_delete)}")
    for n in html_to_delete:
        print(f"    - {n}")

    print(f"\nByte-identical duplicate copies to remove: {len(dup_to_delete)}")
    for deleted, kept in sorted(dup_to_delete):
        print(f"    - {deleted}")
        print(f"        (keeping {kept})")

    remaining = len(all_files) - len(to_delete)
    print(f"\nSummary: remove {len(to_delete)}, keep {remaining} "
          f"(of which {len(SIDECAR_FILES & set(all_files))} are bookkeeping files)")

    if not to_delete:
        print("\nNothing to clean.")
        return

    if not args.apply:
        print("\nDry run only. Re-run with --apply to delete the files above.")
        return

    # --- Apply: delete files, then prune sidecar JSON ---
    deleted_count = 0
    for fname in sorted(to_delete):
        try:
            os.remove(os.path.join(nfts_dir, fname))
            deleted_count += 1
        except OSError as e:
            print(f"  ! could not remove {fname}: {e}")

    _prune_source_map(os.path.join(nfts_dir, "nft-source-map.json"), to_delete)
    _prune_progress(os.path.join(nfts_dir, "download_progress.json"), to_delete)

    print(f"\nDone: deleted {deleted_count} files; pruned sidecar JSON.")


def _atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def _prune_source_map(path, deleted_names):
    """Remove deleted filenames (map keys are filenames)."""
    if not os.path.exists(path):
        return
    try:
        src = json.load(open(path))
    except (OSError, ValueError):
        return
    before = len(src)
    src = {k: v for k, v in src.items() if k not in deleted_names}
    _atomic_write_json(path, src)
    print(f"  nft-source-map.json: {before} -> {len(src)} entries")


def _prune_progress(path, deleted_names):
    """Remove deleted stems from the 'downloaded' list and 'failed' dict
    (progress tracks by stem / safe-id, not full filename)."""
    if not os.path.exists(path):
        return
    try:
        prog = json.load(open(path))
    except (OSError, ValueError):
        return
    deleted_stems = {os.path.splitext(n)[0] for n in deleted_names}
    dl = prog.get("downloaded", [])
    if isinstance(dl, list):
        prog["downloaded"] = [s for s in dl if s not in deleted_stems]
    failed = prog.get("failed", {})
    if isinstance(failed, dict):
        prog["failed"] = {k: v for k, v in failed.items() if k not in deleted_stems}
    _atomic_write_json(path, prog)
    print(f"  download_progress.json: pruned {len(deleted_stems)} deleted stems")


if __name__ == "__main__":
    main()
