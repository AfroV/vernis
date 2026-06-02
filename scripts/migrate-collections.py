#!/usr/bin/env python3
"""Vernis — one-shot collection migration.

Backfills two pieces of metadata that older code didn't write:

  (1) Sidecar `wallet`/`chains` for wallet-sourced collections imported
      before the wallet-tool fix. Without this, the Auto-sync toggle in
      Library and the Settings → Wallets list never show the entry.
      Both `0x…` filenames and ENS names (`vitalik.eth`) are detected;
      ENS names are resolved via public RPC (same path the backend uses).

  (2) nft-source-map.json entries for files already on disk. The
      downloader used to only flush this map at end-of-run, so any
      interrupted install left an empty map for its collection and
      "Remove files" / source-map-driven features couldn't see them.

The script is idempotent. Running it multiple times produces the same
result; it only adds entries, never removes. Safe to wire to a button
in Settings or to a systemd hook.

Usage:
    sudo python3 /opt/vernis/scripts/migrate-collections.py
    sudo python3 /opt/vernis/scripts/migrate-collections.py --dry-run
    sudo python3 /opt/vernis/scripts/migrate-collections.py --json   # machine-readable summary

Exit codes:
    0  success (including "nothing to do")
    1  failure
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Iterable

CSV_LIBRARY = Path("/opt/vernis/csv-library")
NFT_DIRS = [Path("/opt/vernis/nfts")]  # external/ext dirs picked up below
ETH_ADDR_RE = re.compile(r"^(0x[0-9a-fA-F]{40})")
ENS_RE = re.compile(r"^([a-z0-9-]+\.eth)$", re.IGNORECASE)
MEDIA_EXTS = (".gif", ".png", ".jpg", ".jpeg", ".mp4", ".glb",
              ".html", ".bin", ".webp", ".svg", ".avif", ".json", ".txt")


def _find_external_nft_dirs() -> list[Path]:
    cfg = Path("/opt/vernis/storage-config.json")
    if not cfg.exists():
        return []
    try:
        data = json.loads(cfg.read_text())
        if data.get("use_external") and data.get("external_path"):
            return [Path(data["external_path"])]
    except Exception:
        pass
    return []


_ENS_CACHE: dict[str, str | None] = {}


def _resolve_ens(name: str) -> str | None:
    """Resolve an ENS name to an Ethereum address via public RPC.
    Returns lowercase 0x-prefixed address, or None on failure.
    Mirrors the backend's _resolve_ens so this script needs no Flask running."""
    if name in _ENS_CACHE:
        return _ENS_CACHE[name]
    try:
        import requests
        from Crypto.Hash import keccak
    except ImportError:
        _ENS_CACHE[name] = None
        return None

    def kk(data: bytes) -> bytes:
        h = keccak.new(digest_bits=256)
        h.update(data)
        return h.digest()

    def namehash(n: str) -> str:
        node = b"\x00" * 32
        if n:
            for label in reversed(n.split(".")):
                node = kk(node + kk(label.encode()))
        return "0x" + node.hex()

    nh = namehash(name)
    registry = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"
    rpc_urls = ("https://eth.llamarpc.com", "https://rpc.ankr.com/eth", "https://ethereum.publicnode.com")
    zero32 = "0x" + "0" * 64
    for rpc in rpc_urls:
        try:
            r = requests.post(rpc, json={
                "jsonrpc": "2.0", "id": 1, "method": "eth_call",
                "params": [{"to": registry, "data": "0x0178b8bf" + nh[2:]}, "latest"],
            }, timeout=10).json().get("result", "0x")
            if r in ("0x", zero32):
                continue
            resolver = "0x" + r[-40:]
            r2 = requests.post(rpc, json={
                "jsonrpc": "2.0", "id": 2, "method": "eth_call",
                "params": [{"to": resolver, "data": "0x3b3b57de" + nh[2:]}, "latest"],
            }, timeout=10).json().get("result", "0x")
            if r2 and len(r2) >= 42 and r2 != zero32:
                addr = "0x" + r2[-40:].lower()
                _ENS_CACHE[name] = addr
                return addr
        except Exception:
            continue
    _ENS_CACHE[name] = None
    return None


def _detect_wallet_from_filename(stem: str) -> tuple[str, list[str]] | None:
    """If the CSV filename obviously names a wallet, return (address, chains).
    Auto-detected only — never guesses, never overrides."""
    m = ETH_ADDR_RE.match(stem)
    if m:
        return (m.group(1).lower(), ["ethereum"])
    # ENS name → resolve via public RPC (same path the backend uses).
    if ENS_RE.match(stem):
        resolved = _resolve_ens(stem.lower())
        if resolved:
            return (resolved, ["ethereum"])
    return None


def _backfill_sidecars(dry_run: bool) -> dict:
    """Pass 1: add wallet/chains to orphan sidecars where the wallet
    address is unambiguously detectable from the filename."""
    patched: list[str] = []
    skipped_ambiguous: list[str] = []
    if not CSV_LIBRARY.exists():
        return {"patched": [], "skipped_ambiguous": []}

    for csv_path in sorted(CSV_LIBRARY.glob("*.csv")):
        stem = csv_path.stem
        meta_path = csv_path.with_suffix(".json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
            except Exception:
                meta = {}
        else:
            meta = {}

        if meta.get("wallet"):
            continue  # already wallet-tagged, leave alone

        detected = _detect_wallet_from_filename(stem)
        if detected is None:
            # Possibly a wallet-import that we can't auto-detect (ENS, custom name)
            # OR a plain CSV upload. We don't touch it — false-tagging a CSV as a
            # wallet would silently change UI behaviour.
            if ENS_RE.match(stem):
                skipped_ambiguous.append(stem)
            continue

        wallet_addr, chains = detected
        meta["wallet"] = wallet_addr
        meta.setdefault("chains", chains)
        meta.setdefault("name", stem)
        meta.setdefault("description", "NFTs from wallet")
        meta.setdefault("featured", False)
        if not dry_run:
            tmp = meta_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(meta, indent=2))
            tmp.replace(meta_path)
        patched.append(csv_path.name)

    return {"patched": patched, "skipped_ambiguous": skipped_ambiguous}


def _candidates_for_row(row: dict) -> Iterable[str]:
    """Identifiers the downloader could have used as the filename stem
    for a given CSV row."""
    cid_raw = (row.get("cid") or row.get("CID") or "").replace("ipfs://", "").strip()
    cid = cid_raw.split("/", 1)[0]
    if cid.startswith("Qm") or cid.startswith("bafy"):
        yield cid
    contract = (row.get("contract_address") or row.get("contract") or "").strip().lower()
    token = (row.get("token_id") or "").strip()
    if contract and token:
        yield f"{contract}_{token}"


def _build_file_index(nft_dir: Path) -> dict[str, list[Path]]:
    """Listdir the NFT directory ONCE and build a prefix index.

    Result: for any identifier `ident`, `index.get(ident, [])` returns every
    file whose stem is exactly `ident` or starts with `ident_…`. Files with
    non-media extensions are skipped.

    This replaces the previous per-row glob() loop, which scanned the whole
    directory once per (identifier × extension) pair — pathological on dirs
    with thousands of files.
    """
    index: dict[str, list[Path]] = {}
    if not nft_dir.exists():
        return index
    for entry in nft_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in MEDIA_EXTS:
            continue
        stem = entry.stem
        # Exact-match key
        index.setdefault(stem, []).append(entry)
        # Underscore-boundary prefixes (e.g. for stem "0xabc_1234_thumb",
        # also index under "0xabc" and "0xabc_1234")
        parts = stem.split("_")
        for i in range(1, len(parts)):
            prefix = "_".join(parts[:i])
            index.setdefault(prefix, []).append(entry)
    return index


def _match_files_for_identifier(index: dict[str, list[Path]], ident: str) -> Iterable[Path]:
    """Files matching `ident` (bare `ident.ext`) or suffixed `ident_*.ext`.

    Downloader convention: if a bare-name file exists for `ident`, do NOT
    also match suffixed variants — the bare file is authoritative."""
    candidates = index.get(ident)
    if not candidates:
        return
    bare = [p for p in candidates if p.stem == ident]
    if bare:
        yield from bare
        return
    yield from candidates


def _backfill_source_map(dry_run: bool) -> dict:
    """Pass 2: for each NFT dir, scan every CSV in the library and tag
    files that match the CSV's rows."""
    nft_dirs = NFT_DIRS + _find_external_nft_dirs()
    per_dir_results = []
    total_added = 0

    for nft_dir in nft_dirs:
        if not nft_dir.exists():
            continue
        map_file = nft_dir / "nft-source-map.json"
        try:
            source_map = json.loads(map_file.read_text()) if map_file.exists() else {}
        except Exception:
            source_map = {}

        file_index = _build_file_index(nft_dir)

        added_in_dir = 0
        if not CSV_LIBRARY.exists():
            continue
        for csv_path in sorted(CSV_LIBRARY.glob("*.csv")):
            csv_name = csv_path.name
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        for ident in _candidates_for_row(row):
                            for match in _match_files_for_identifier(file_index, ident):
                                if source_map.get(match.name) != csv_name:
                                    source_map[match.name] = csv_name
                                    added_in_dir += 1
            except Exception as e:
                print(f"  ⚠ skipping {csv_name}: {e}", flush=True)

        if not dry_run and added_in_dir > 0:
            tmp = map_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(source_map))
            tmp.replace(map_file)

        per_dir_results.append({
            "dir": str(nft_dir),
            "added": added_in_dir,
            "total_entries_now": len(source_map),
        })
        total_added += added_in_dir

    return {"dirs": per_dir_results, "total_added": total_added}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="don't write any files")
    ap.add_argument("--json", action="store_true", help="machine-readable summary on stdout")
    args = ap.parse_args()

    try:
        sidecars = _backfill_sidecars(args.dry_run)
        source_map = _backfill_source_map(args.dry_run)
    except Exception as e:
        msg = {"ok": False, "error": str(e)}
        print(json.dumps(msg) if args.json else f"ERROR: {e}", flush=True)
        return 1

    result = {
        "ok": True,
        "dry_run": args.dry_run,
        "sidecars": sidecars,
        "source_map": source_map,
    }

    if args.json:
        print(json.dumps(result))
        return 0

    # Human-readable summary
    print("Vernis collection migration")
    print("=" * 40)
    if args.dry_run:
        print("(dry run — no files changed)")
    print()
    print(f"Sidecars patched (wallet field added):  {len(sidecars['patched'])}")
    for f in sidecars["patched"]:
        print(f"  + {f}")
    if sidecars["skipped_ambiguous"]:
        print(f"Sidecars skipped (ENS or unclear):    {len(sidecars['skipped_ambiguous'])}")
        for f in sidecars["skipped_ambiguous"]:
            print(f"  ? {f}  (edit the .json by hand or re-import)")
    print()
    print(f"Source-map entries added:  {source_map['total_added']}")
    for d in source_map["dirs"]:
        print(f"  {d['dir']}: +{d['added']} (total {d['total_entries_now']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
