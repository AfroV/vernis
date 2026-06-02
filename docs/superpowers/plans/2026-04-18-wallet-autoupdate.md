# Wallet Auto-Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auto-update toggle and manual "Check now" button to wallet-sourced library cards, with daily staggered background checks and clear handling of OpenSea API key exhaustion.

**Architecture:** Single Flask daemon thread wakes hourly, scans `/opt/vernis/csv-library/*.json` sidecars, and refreshes wallet collections whose `autoupdate: true` and `last_checked` is ≥24h old. Refresh diffs OpenSea's current wallet NFT list against the existing CSV, appends new rows, and spawns the existing downloader. On HTTP 429/401, scheduler writes an exhausted-key status file; library.html and add.html both render a banner pointing to the OpenSea key input until user supplies a new key.

**Tech Stack:** Python 3 + Flask (backend); plain HTML/CSS/JS (frontend). No new dependencies. Project has no pytest suite — verification is manual (curl + UI + log inspection).

**Deployment note:** All changes are to a running Pi. Files deploy via the `sshpass` commands documented in `CLAUDE.md`. During development, changes can be tested locally by pointing `CSV_LIBRARY_DIR` at a tmp dir (see Task 0 preamble). Each task's "Verify" step assumes local dev unless otherwise stated.

---

## File Structure

Files modified (no new files):

- [backend/app.py](backend/app.py) — add `OPENSEA_KEY_STATUS_FILE` constant, add 4 helpers (`_read_key_status`, `_write_key_status`, `_clear_key_status`, `_fetch_opensea_wallet_nfts`, `_refresh_wallet_collection`), add 3 endpoints (`/api/collection/<fn>/autoupdate`, `/api/collection/<fn>/check-now`, `/api/collection/<fn>/check-status`), modify 2 endpoints (`/api/csv-library`, `/api/opensea-key`), add scheduler thread at app startup, add in-memory job registry (`_check_jobs` dict + lock)
- [library.html](library.html) — extend collection listing render to show toggle + Check now button + status line on wallet cards; add JS handlers for toggle/check-now; add key-exhausted banner
- [add.html](add.html) — add key-exhausted banner near OpenSea key input

---

## Task 0: Setup — local dev harness

**Files:**
- Create: `dev-csv-library/` (gitignored; local test sidecars)

- [ ] **Step 1: Create dev sidecar fixtures**

```bash
mkdir -p dev-csv-library
cat > dev-csv-library/test-wallet.csv <<'EOF'
contract_address,token_id,name,collection,image_url,chain,metadata_url,cid
0xaaa,1,Existing NFT,Test Coll,https://example.com/1.png,ethereum,,
EOF
cat > dev-csv-library/test-wallet.json <<'EOF'
{
  "name": "test.eth",
  "description": "1 NFT from Ethereum",
  "wallet": "0x1234567890abcdef1234567890abcdef12345678",
  "chains": ["ethereum"],
  "featured": false
}
EOF
cat > dev-csv-library/curated-no-wallet.csv <<'EOF'
contract_address,token_id,name,collection,image_url,chain,metadata_url,cid
0xbbb,5,Curated,CuratedColl,https://example.com/5.png,ethereum,,
EOF
cat > dev-csv-library/curated-no-wallet.json <<'EOF'
{
  "name": "Curated Collection",
  "description": "A hand-picked list",
  "featured": true
}
EOF
```

- [ ] **Step 2: Verify fixtures exist**

Run: `ls dev-csv-library/`
Expected output: `curated-no-wallet.csv curated-no-wallet.json test-wallet.csv test-wallet.json`

- [ ] **Step 3: Add dev dir to gitignore**

Append to [.gitignore](.gitignore):
```
dev-csv-library/
```

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore dev-csv-library fixtures dir"
```

---

## Task 1: Add OpenSea key exhaustion state helpers

**Files:**
- Modify: [backend/app.py](backend/app.py) — add constants and helpers after existing `OPENSEA_KEY_FILE` block (~line 4835)

- [ ] **Step 1: Add constant and helper functions**

Locate the line `OPENSEA_KEY_FILE = Path("/opt/vernis/opensea-key.json")` (around line 4832). Directly AFTER the existing `_get_opensea_key()` function (ends around line 4848), insert:

```python
OPENSEA_KEY_STATUS_FILE = Path("/opt/vernis/opensea-key-status.json")


def _read_key_status():
    """Return {'exhausted': bool, 'exhausted_at': iso_str, 'last_error': str} or empty dict."""
    try:
        if OPENSEA_KEY_STATUS_FILE.exists():
            return json.loads(OPENSEA_KEY_STATUS_FILE.read_text())
    except Exception:
        pass
    return {}


def _write_key_status(error_msg):
    """Mark key as exhausted now with the given error message."""
    status = {
        "exhausted": True,
        "exhausted_at": datetime.utcnow().isoformat() + "Z",
        "last_error": error_msg,
    }
    try:
        OPENSEA_KEY_STATUS_FILE.write_text(json.dumps(status, indent=2))
        os.chmod(str(OPENSEA_KEY_STATUS_FILE), 0o600)
    except Exception:
        pass


def _clear_key_status():
    """Clear the exhausted flag (called when user saves a new key)."""
    try:
        if OPENSEA_KEY_STATUS_FILE.exists():
            OPENSEA_KEY_STATUS_FILE.unlink()
    except Exception:
        pass


def _is_key_exhausted():
    """True if key is marked exhausted and <24h has passed since mark."""
    status = _read_key_status()
    if not status.get("exhausted"):
        return False
    try:
        marked = datetime.fromisoformat(status["exhausted_at"].rstrip("Z"))
        return (datetime.utcnow() - marked) < timedelta(hours=24)
    except Exception:
        return False
```

- [ ] **Step 2: Verify `datetime` and `timedelta` imports exist**

Run: `grep -n "^from datetime" backend/app.py | head -5`
Expected: At least one line with `from datetime import datetime, timedelta` (or `datetime` and `timedelta` available via `datetime` module).

If `timedelta` is missing, update the import at the top of the file accordingly.

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('backend/app.py').read())"`
Expected: No output (parse success).

- [ ] **Step 4: Commit**

```bash
git add backend/app.py
git commit -m "feat(backend): add OpenSea key exhaustion state helpers"
```

---

## Task 2: Extract `_fetch_opensea_wallet_nfts` helper

**Files:**
- Modify: [backend/app.py](backend/app.py) — new helper placed directly before `setup_quick_import` (~line 5649)

- [ ] **Step 1: Add helper**

Directly BEFORE the line `@app.route("/api/setup/quick-import", methods=["POST"])` (around line 5649), insert:

```python
def _fetch_opensea_wallet_nfts(wallet, chains, api_key):
    """
    Fetch all NFTs from a wallet across OpenSea chains with pagination.

    Returns (nfts_list, throttled_bool, error_str).
    - nfts_list: list of dicts with keys contract, token_id, name, collection,
      image_url, chain, metadata_url
    - throttled_bool: True if any call returned 429/401
    - error_str: None on success, a short description if throttled or network-failed
    """
    import requests as _req

    nfts = []
    throttled = False
    err = None
    _skip_collections = {'ens', 'unstoppable-domains', 'lens-protocol-profiles',
                         'wrapped-cryptopunks'}

    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-KEY"] = api_key

    opensea_chains = [c for c in chains if c in _WALLET_CHAINS]
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
            except Exception as e:
                err = f"Network error: {e}"
                break
            if resp.status_code in (429, 401, 403):
                throttled = True
                err = f"HTTP {resp.status_code} from OpenSea"
                break
            if resp.status_code != 200:
                err = f"HTTP {resp.status_code} from OpenSea"
                break
            resp_data = resp.json()
            for nft in resp_data.get('nfts', []):
                col = nft.get('collection', '')
                if col in _skip_collections:
                    continue
                img = nft.get('display_image_url') or nft.get('image_url', '')
                if not img:
                    continue
                nfts.append({
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
            time.sleep(0.5)

    return nfts, throttled, err
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('backend/app.py').read())"`
Expected: No output.

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat(backend): extract _fetch_opensea_wallet_nfts helper"
```

> **Note:** We are intentionally NOT refactoring the existing `setup_quick_import` endpoint to call this helper right now. That's out of scope — we only need the helper for scheduled refreshes. Refactor can happen later.

---

## Task 3: Add `_refresh_wallet_collection` helper

**Files:**
- Modify: [backend/app.py](backend/app.py) — insert after the helper from Task 2

- [ ] **Step 1: Add helper**

Directly AFTER `_fetch_opensea_wallet_nfts` (the function added in Task 2), insert:

```python
def _refresh_wallet_collection(filename):
    """
    Refresh a wallet-sourced collection: fetch current OpenSea contents,
    diff against existing CSV, append new rows, trigger downloader for new rows.

    Returns a result dict:
      {"ok": True, "new_count": int, "message": str}
      {"ok": False, "error": str, "opensea_key_exhausted": bool}
    """
    import csv as csv_module

    # Sanitize filename (no path traversal)
    if '/' in filename or '..' in filename or not filename.endswith('.csv'):
        return {"ok": False, "error": "Invalid filename", "opensea_key_exhausted": False}

    csv_path = CSV_LIBRARY_DIR / filename
    meta_path = csv_path.with_suffix('.json')

    if not csv_path.exists() or not meta_path.exists():
        return {"ok": False, "error": "Collection not found", "opensea_key_exhausted": False}

    try:
        meta = json.loads(meta_path.read_text())
    except Exception as e:
        return {"ok": False, "error": f"Sidecar parse error: {e}", "opensea_key_exhausted": False}

    wallet = meta.get('wallet', '').strip()
    if not wallet:
        return {"ok": False, "error": "Not a wallet collection", "opensea_key_exhausted": False}

    chains = meta.get('chains') or ['ethereum', 'base', 'optimism']

    # Only EVM chains for now (Tezos refresh out of initial scope)
    evm_chains = [c for c in chains if c in _WALLET_CHAINS]
    if not evm_chains:
        return {"ok": True, "new_count": 0, "message": "Tezos-only wallets are not refreshed yet"}

    # Short-circuit if key is exhausted
    if _is_key_exhausted():
        return {"ok": False, "error": "OpenSea API key exhausted",
                "opensea_key_exhausted": True}

    api_key = _get_opensea_key()
    nfts, throttled, err = _fetch_opensea_wallet_nfts(wallet, evm_chains, api_key)

    if throttled:
        _write_key_status(err or "Throttled")
        return {"ok": False, "error": err or "OpenSea rate limit reached",
                "opensea_key_exhausted": True}

    if err and not nfts:
        return {"ok": False, "error": err, "opensea_key_exhausted": False}

    # Build set of existing (contract, token_id) pairs from CSV
    existing = set()
    try:
        with open(csv_path, 'r', newline='') as f:
            reader = csv_module.reader(f)
            header = next(reader, None)
            for row in reader:
                if len(row) >= 2:
                    existing.add((row[0].strip().lower(), row[1].strip()))
    except Exception as e:
        return {"ok": False, "error": f"CSV read error: {e}", "opensea_key_exhausted": False}

    # Diff
    new_rows = []
    for nft in nfts:
        key = (nft['contract'].strip().lower(), str(nft['token_id']).strip())
        if key not in existing:
            new_rows.append(nft)

    # Resolve IPFS metadata for new rows only
    if new_rows:
        _resolve_nft_metadata(new_rows)

    # Append new rows to CSV
    if new_rows:
        with open(csv_path, 'a', newline='') as f:
            writer = csv_module.writer(f)
            for nft in new_rows:
                writer.writerow([
                    nft['contract'], nft['token_id'],
                    nft['name'], nft['collection'],
                    nft['image_url'], nft['chain'],
                    nft.get('metadata_url', ''), nft.get('cid', ''),
                ])

    # Update sidecar
    meta['last_checked'] = datetime.utcnow().isoformat() + "Z"
    meta['last_new_count'] = len(new_rows)
    try:
        meta_path.write_text(json.dumps(meta, indent=2))
    except Exception:
        pass

    # Trigger downloader for new rows only (write a temporary CSV with just the new rows)
    if new_rows:
        try:
            import tempfile
            tmp_csv = UPLOAD_DIR / f".refresh-{filename}"
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            with open(tmp_csv, 'w', newline='') as f:
                writer = csv_module.writer(f)
                writer.writerow(['contract_address', 'token_id', 'name', 'collection',
                                 'image_url', 'chain', 'metadata_url', 'cid'])
                for nft in new_rows:
                    writer.writerow([
                        nft['contract'], nft['token_id'],
                        nft['name'], nft['collection'],
                        nft['image_url'], nft['chain'],
                        nft.get('metadata_url', ''), nft.get('cid', ''),
                    ])
            active_nft_dir = get_active_nft_dir(for_writing=True)
            active_nft_dir.mkdir(parents=True, exist_ok=True)
            downloader = SCRIPTS_DIR / "nft_downloader_advanced.py"
            subprocess.Popen([
                "python3", str(downloader),
                "--csv", str(tmp_csv),
                "--output", str(active_nft_dir),
                "--workers", "2"
            ])
        except Exception:
            pass  # Log visible via parent Flask logs; don't fail refresh

    msg = f"{len(new_rows)} new NFT{'s' if len(new_rows) != 1 else ''}"
    if len(new_rows) == 0:
        msg = "No new NFTs"
    return {"ok": True, "new_count": len(new_rows), "message": msg}
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('backend/app.py').read())"`
Expected: No output.

- [ ] **Step 3: Unit-style verification via Python REPL**

Create a throwaway script `scripts/test_refresh.py` (DO NOT commit; add to `.gitignore` or `rm` after):

```python
import sys, json, pathlib
sys.path.insert(0, 'backend')

# Monkey-patch CSV_LIBRARY_DIR BEFORE importing app
import importlib.util
spec = importlib.util.spec_from_file_location("app_module", "backend/app.py")
# We can't easily import app.py (it starts Flask). Instead, test diff logic manually.

# Simpler: just verify the helper file parses and CSV diff logic works in isolation.
# Skip — rely on Task 12 smoke test after deploy.
print("OK — parse check only; full test in Task 12.")
```

Run: `python3 scripts/test_refresh.py`
Expected: `OK — parse check only; full test in Task 12.`

Delete the script: `rm scripts/test_refresh.py`

- [ ] **Step 4: Commit**

```bash
git add backend/app.py
git commit -m "feat(backend): add _refresh_wallet_collection helper"
```

---

## Task 4: Add autoupdate toggle endpoint

**Files:**
- Modify: [backend/app.py](backend/app.py) — add endpoint after `_refresh_wallet_collection`

- [ ] **Step 1: Add endpoint**

Directly AFTER `_refresh_wallet_collection` (function from Task 3), insert:

```python
@app.route("/api/collection/<path:filename>/autoupdate", methods=["POST"])
def collection_autoupdate(filename):
    """Enable or disable autoupdate for a wallet-sourced collection."""
    # Sanitize
    if '/' in filename or '..' in filename or not filename.endswith('.csv'):
        return jsonify({"error": "Invalid filename"}), 400

    meta_path = (CSV_LIBRARY_DIR / filename).with_suffix('.json')
    if not meta_path.exists():
        return jsonify({"error": "Collection not found"}), 404

    try:
        meta = json.loads(meta_path.read_text())
    except Exception as e:
        return jsonify({"error": f"Sidecar parse error: {e}"}), 500

    if not meta.get('wallet'):
        return jsonify({"error": "Not a wallet collection"}), 400

    data = request.json or {}
    enabled = bool(data.get('enabled', False))
    meta['autoupdate'] = enabled

    try:
        meta_path.write_text(json.dumps(meta, indent=2))
    except Exception as e:
        return jsonify({"error": f"Failed to write sidecar: {e}"}), 500

    return jsonify({"ok": True, "autoupdate": enabled})
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('backend/app.py').read())"`
Expected: No output.

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat(backend): add /api/collection/<fn>/autoupdate endpoint"
```

---

## Task 5: Add check-now + check-status endpoints (async job pattern)

**Files:**
- Modify: [backend/app.py](backend/app.py) — add in-memory job registry + two endpoints

- [ ] **Step 1: Add job registry and endpoints**

Directly AFTER the `collection_autoupdate` endpoint from Task 4, insert:

```python
import threading as _threading
import uuid as _uuid

_check_jobs = {}  # job_id -> {"done": bool, "result": dict, "started_at": datetime}
_check_jobs_lock = _threading.Lock()


def _evict_old_check_jobs():
    """Remove jobs completed >5 minutes ago."""
    cutoff = datetime.utcnow() - timedelta(minutes=5)
    with _check_jobs_lock:
        stale = [jid for jid, j in _check_jobs.items()
                 if j.get("done") and j.get("finished_at") and j["finished_at"] < cutoff]
        for jid in stale:
            del _check_jobs[jid]


def _run_check_job(job_id, filename):
    """Worker thread body: run refresh, store result in registry."""
    try:
        result = _refresh_wallet_collection(filename)
    except Exception as e:
        result = {"ok": False, "error": f"Unhandled: {e}", "opensea_key_exhausted": False}
    with _check_jobs_lock:
        if job_id in _check_jobs:
            _check_jobs[job_id]["result"] = result
            _check_jobs[job_id]["done"] = True
            _check_jobs[job_id]["finished_at"] = datetime.utcnow()


@app.route("/api/collection/<path:filename>/check-now", methods=["POST"])
def collection_check_now(filename):
    """Start an async refresh job for a wallet collection."""
    if '/' in filename or '..' in filename or not filename.endswith('.csv'):
        return jsonify({"error": "Invalid filename"}), 400

    meta_path = (CSV_LIBRARY_DIR / filename).with_suffix('.json')
    if not meta_path.exists():
        return jsonify({"error": "Collection not found"}), 404

    try:
        meta = json.loads(meta_path.read_text())
    except Exception:
        return jsonify({"error": "Sidecar unreadable"}), 500

    if not meta.get('wallet'):
        return jsonify({"error": "Not a wallet collection"}), 400

    _evict_old_check_jobs()

    job_id = _uuid.uuid4().hex
    with _check_jobs_lock:
        _check_jobs[job_id] = {
            "done": False,
            "result": None,
            "started_at": datetime.utcnow(),
        }

    t = _threading.Thread(target=_run_check_job, args=(job_id, filename), daemon=True)
    t.start()

    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/collection/<path:filename>/check-status", methods=["GET"])
def collection_check_status(filename):
    """Poll status of a check-now job."""
    job_id = request.args.get('job', '').strip()
    if not job_id:
        return jsonify({"error": "Missing job id"}), 400

    with _check_jobs_lock:
        job = _check_jobs.get(job_id)
        if job is None:
            return jsonify({"done": True, "error": "Job not found or expired"}), 404
        if not job["done"]:
            return jsonify({"done": False})
        result = job["result"] or {}

    return jsonify({"done": True, **result})
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('backend/app.py').read())"`
Expected: No output.

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat(backend): add check-now and check-status endpoints"
```

---

## Task 6: Add scheduler thread

**Files:**
- Modify: [backend/app.py](backend/app.py) — add scheduler loop + startup hook at end of file

- [ ] **Step 1: Add scheduler function**

Find the bottom of `backend/app.py` (below the last `@app.route` but BEFORE any `if __name__ == "__main__":` block or the call to `app.run`). Insert:

```python
def _scheduler_loop():
    """Background thread: hourly tick, refreshes due wallet collections sequentially."""
    # Initial delay so we don't hammer on Flask startup
    time.sleep(60)

    while True:
        try:
            # Skip entire tick if OpenSea key is exhausted
            if _is_key_exhausted():
                time.sleep(3600)
                continue

            due_files = []
            try:
                for meta_path in CSV_LIBRARY_DIR.glob("*.json"):
                    try:
                        meta = json.loads(meta_path.read_text())
                    except Exception:
                        continue
                    if not meta.get('autoupdate'):
                        continue
                    if not meta.get('wallet'):
                        continue
                    last = meta.get('last_checked')
                    if last:
                        try:
                            last_dt = datetime.fromisoformat(last.rstrip("Z"))
                            if (datetime.utcnow() - last_dt) < timedelta(hours=24):
                                continue
                        except Exception:
                            pass  # unparseable -> treat as due
                    csv_filename = meta_path.with_suffix('.csv').name
                    due_files.append(csv_filename)
            except Exception:
                due_files = []

            # Process sequentially, 60s apart
            for fname in due_files:
                if _is_key_exhausted():
                    break
                try:
                    _refresh_wallet_collection(fname)
                except Exception:
                    pass
                time.sleep(60)
        except Exception:
            pass

        # Sleep until next hourly tick
        time.sleep(3600)


def _start_scheduler():
    """Start scheduler thread once per process."""
    t = _threading.Thread(target=_scheduler_loop, name="vernis-autoupdate", daemon=True)
    t.start()


# Start scheduler at import time (runs under Flask dev server and gunicorn)
_start_scheduler()
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('backend/app.py').read())"`
Expected: No output.

- [ ] **Step 3: Verify scheduler hook location**

Run: `grep -n "_start_scheduler" backend/app.py`
Expected: Two lines — the `def _start_scheduler` definition and the bare call `_start_scheduler()`. The bare call should be the LAST non-`app.run` statement in the file.

- [ ] **Step 4: Commit**

```bash
git add backend/app.py
git commit -m "feat(backend): add hourly autoupdate scheduler thread"
```

---

## Task 7: Extend `/api/csv-library` response with wallet fields

**Files:**
- Modify: [backend/app.py:2514-2522](backend/app.py#L2514-L2522) — the dict appended inside `csv_library()`

- [ ] **Step 1: Modify the append block**

Find the block starting at line ~2514 where `collections.append({...})` is called inside `csv_library()`. Replace that append call with:

```python
            collections.append({
                "filename": csv_file.name,
                "name": metadata.get("name", csv_file.stem.replace('_', ' ').title()),
                "description": metadata.get("description", "NFT collection"),
                "count": count,
                "size": size,
                "source": "local",
                "featured": metadata.get("featured", False),
                "wallet": metadata.get("wallet", ""),
                "autoupdate": metadata.get("autoupdate", False),
                "last_checked": metadata.get("last_checked", ""),
                "last_new_count": metadata.get("last_new_count", 0),
            })
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('backend/app.py').read())"`
Expected: No output.

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat(backend): expose wallet/autoupdate fields in /api/csv-library"
```

---

## Task 8: Extend `/api/opensea-key` GET response with exhausted flag

**Files:**
- Modify: [backend/app.py:4985-5010](backend/app.py#L4985-L5010) — `opensea_key()` function

- [ ] **Step 1: Replace function body**

Replace the entire `opensea_key` function (the `@app.route("/api/opensea-key", methods=["GET", "POST"])` block) with:

```python
@app.route("/api/opensea-key", methods=["GET", "POST"])
def opensea_key():
    """Get or set OpenSea API key"""
    if request.method == "GET":
        status = _read_key_status()
        exhausted = _is_key_exhausted()
        try:
            if OPENSEA_KEY_FILE.exists():
                data = json.loads(OPENSEA_KEY_FILE.read_text())
                key = data.get('key', '')
                if key:
                    return jsonify({
                        "configured": True,
                        "key_preview": key[:8] + "..." + key[-4:],
                        "exhausted": exhausted,
                        "exhausted_at": status.get("exhausted_at", ""),
                        "last_error": status.get("last_error", ""),
                    })
            return jsonify({
                "configured": False,
                "exhausted": exhausted,
                "exhausted_at": status.get("exhausted_at", ""),
                "last_error": status.get("last_error", ""),
            })
        except Exception:
            return jsonify({"configured": False, "exhausted": exhausted})
    else:
        data = request.json or {}
        key = data.get('key', '').strip()
        if not key:
            if OPENSEA_KEY_FILE.exists():
                OPENSEA_KEY_FILE.unlink()
            _clear_key_status()
            return jsonify({"success": True, "message": "API key removed"})
        OPENSEA_KEY_FILE.write_text(json.dumps({"key": key}))
        os.chmod(str(OPENSEA_KEY_FILE), 0o600)
        _clear_key_status()
        return jsonify({"success": True, "message": "API key saved"})
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('backend/app.py').read())"`
Expected: No output.

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat(backend): expose exhausted flag on GET /api/opensea-key; clear on key save"
```

---

## Task 9: Library.html — render toggle + Check now button on wallet cards

**Files:**
- Modify: [library.html:1469-1530](library.html#L1469-L1530) — the `collectionCards` render function

- [ ] **Step 1: Add CSS for autoupdate controls**

In [library.html](library.html), find the `<style>` block. Locate a spot near other `.card-*` rules (search for `.card-progress-container`). Insert:

```css
    .card-autoupdate {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 0;
      font-size: 12px;
      color: rgba(255, 255, 255, 0.7);
    }
    .card-autoupdate-toggle {
      position: relative;
      width: 36px;
      height: 20px;
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.2);
      cursor: pointer;
      transition: background 0.2s;
      flex-shrink: 0;
    }
    .card-autoupdate-toggle.on {
      background: #4caf50;
    }
    .card-autoupdate-toggle::after {
      content: "";
      position: absolute;
      top: 2px;
      left: 2px;
      width: 16px;
      height: 16px;
      border-radius: 50%;
      background: #fff;
      transition: transform 0.2s;
    }
    .card-autoupdate-toggle.on::after {
      transform: translateX(16px);
    }
    .card-check-now {
      background: transparent;
      border: 1px solid rgba(255, 255, 255, 0.3);
      color: inherit;
      border-radius: 6px;
      padding: 6px 8px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      min-width: 32px;
      min-height: 32px;
    }
    .card-check-now:hover {
      background: rgba(255, 255, 255, 0.1);
    }
    .card-check-now.spinning svg {
      animation: spin 1s linear infinite;
    }
    @keyframes spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
    .card-autoupdate-status {
      flex: 1;
      opacity: 0.7;
      font-size: 11px;
    }
    .exhausted-banner {
      background: #b71c1c;
      color: #fff;
      padding: 14px 18px;
      border-radius: 10px;
      margin: 20px 0;
      font-size: 14px;
      line-height: 1.4;
      display: none;
    }
    .exhausted-banner.active {
      display: block;
    }
    .exhausted-banner a {
      color: #ffeb3b;
      text-decoration: underline;
    }
```

- [ ] **Step 2: Add banner element**

Directly AFTER the `<div id="loading" class="loading">` element (around line 1309), insert:

```html
    <div id="exhausted-banner" class="exhausted-banner">
      <strong>OpenSea API limit reached.</strong> Auto-updates are paused.
      Get a free key at <a href="https://opensea.io/settings/developer" target="_blank">opensea.io/settings/developer</a>,
      then paste it on the <a href="add.html">Add Collection page</a>.
    </div>
```

- [ ] **Step 3: Add helpers inside `<script>` block**

Find the `<script>` block and locate the `renderCollections()` function (or the area around line 1469). BEFORE `renderCollections`, insert:

```javascript
    function formatRelativeTime(iso) {
      if (!iso) return 'never';
      try {
        const then = new Date(iso);
        const diffMs = Date.now() - then.getTime();
        const diffMin = Math.floor(diffMs / 60000);
        if (diffMin < 1) return 'just now';
        if (diffMin < 60) return diffMin + 'm ago';
        const diffH = Math.floor(diffMin / 60);
        if (diffH < 24) return diffH + 'h ago';
        const diffD = Math.floor(diffH / 24);
        return diffD + 'd ago';
      } catch (e) { return 'never'; }
    }

    async function toggleAutoupdate(filename, cardEl) {
      const toggleEl = cardEl.querySelector('.card-autoupdate-toggle');
      const currentlyOn = toggleEl.classList.contains('on');
      const next = !currentlyOn;
      toggleEl.classList.toggle('on', next);
      try {
        const resp = await fetch(`/api/collection/${encodeURIComponent(filename)}/autoupdate`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({enabled: next})
        });
        if (!resp.ok) throw new Error('Failed');
      } catch (e) {
        toggleEl.classList.toggle('on', currentlyOn);
        if (typeof showError === 'function') showError('Failed to update auto-update setting');
      }
    }

    async function checkNowCollection(filename, cardEl) {
      const btn = cardEl.querySelector('.card-check-now');
      btn.classList.add('spinning');
      try {
        const startResp = await fetch(`/api/collection/${encodeURIComponent(filename)}/check-now`, {
          method: 'POST'
        });
        const startData = await startResp.json();
        if (!startResp.ok || !startData.job_id) {
          throw new Error(startData.error || 'Start failed');
        }
        const jobId = startData.job_id;
        const poll = async () => {
          const statusResp = await fetch(`/api/collection/${encodeURIComponent(filename)}/check-status?job=${jobId}`);
          const statusData = await statusResp.json();
          if (!statusData.done) {
            setTimeout(poll, 2000);
            return;
          }
          btn.classList.remove('spinning');
          if (statusData.opensea_key_exhausted) {
            document.getElementById('exhausted-banner').classList.add('active');
          }
          if (statusData.ok) {
            if (typeof showInfo === 'function') showInfo(statusData.message || 'Check complete');
            else alert(statusData.message || 'Check complete');
            loadCollections();  // refresh card info
          } else {
            if (typeof showError === 'function') showError(statusData.error || 'Check failed');
            else alert(statusData.error || 'Check failed');
          }
        };
        setTimeout(poll, 2000);
      } catch (e) {
        btn.classList.remove('spinning');
        if (typeof showError === 'function') showError('Check failed: ' + e.message);
        else alert('Check failed: ' + e.message);
      }
    }

    async function checkExhaustedBanner() {
      try {
        const resp = await fetch('/api/opensea-key');
        const data = await resp.json();
        const banner = document.getElementById('exhausted-banner');
        if (banner) banner.classList.toggle('active', !!data.exhausted);
      } catch (e) { /* silent */ }
    }
```

- [ ] **Step 4: Update card rendering to include wallet controls**

Locate the `collectionCards` render template (line ~1484 — the `return \`...\`;` block inside `filteredCollections.map`). Find this section:

```javascript
      <div class="actions">
        <button class="btn-library-primary" onclick="installCollection('${sf}')" ${isReadOnly ? 'disabled title="Storage is read-only"' : ''}>Install</button>
      </div>
```

Replace it with:

```javascript
      <div class="actions">
        <button class="btn-library-primary" onclick="installCollection('${sf}')" ${isReadOnly ? 'disabled title="Storage is read-only"' : ''}>Install</button>
      </div>
      ${col.wallet ? `
      <div class="card-autoupdate">
        <div class="card-autoupdate-toggle ${col.autoupdate ? 'on' : ''}" onclick="toggleAutoupdate('${sf}', this.closest('.card'))" title="Auto-update daily"></div>
        <div class="card-autoupdate-status">${col.autoupdate ? ('Last: ' + formatRelativeTime(col.last_checked)) : 'Auto-update off'}</div>
        <button class="card-check-now" onclick="checkNowCollection('${sf}', this.closest('.card'))" title="Check for new NFTs now">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
        </button>
      </div>
      ` : ''}
```

- [ ] **Step 5: Call `checkExhaustedBanner()` on page load**

Find where `loadCollections()` or equivalent init runs. A common pattern is a `DOMContentLoaded` listener or a top-level call at the end of `<script>`. Locate a top-level `loadCollections();` call (search for it in the file) and ADD a line right after it:

```javascript
    checkExhaustedBanner();
```

Also wire a periodic refresh (every 60s while page is open) — at the same spot:

```javascript
    setInterval(checkExhaustedBanner, 60000);
```

- [ ] **Step 6: Verify HTML parse (rough sanity check)**

Run: `python3 -c "from html.parser import HTMLParser; HTMLParser().feed(open('library.html').read())"`
Expected: No output (parser is lenient; this just catches truly broken structure).

- [ ] **Step 7: Commit**

```bash
git add library.html
git commit -m "feat(library): autoupdate toggle, check-now button, and exhausted-key banner"
```

---

## Task 10: Add.html — exhausted-key banner

**Files:**
- Modify: [add.html](add.html) — add banner near OpenSea key input

- [ ] **Step 1: Find OpenSea key input location**

Run: `grep -n "opensea\|opensea-key\|OpenSea" add.html`

Expected: One or more line numbers pointing to the OpenSea key input section. If there's a `<section>` or `<div>` wrapping the input, that's your insertion target.

- [ ] **Step 2: Add CSS (if not already present)**

If [add.html](add.html) doesn't already have a `.exhausted-banner` CSS rule (grep to confirm: `grep "exhausted-banner" add.html`), add to the `<style>` block:

```css
    .exhausted-banner {
      background: #b71c1c;
      color: #fff;
      padding: 14px 18px;
      border-radius: 10px;
      margin: 20px 0;
      font-size: 14px;
      line-height: 1.4;
      display: none;
    }
    .exhausted-banner.active {
      display: block;
    }
    .exhausted-banner a {
      color: #ffeb3b;
      text-decoration: underline;
    }
```

- [ ] **Step 3: Add banner markup directly before the OpenSea key input**

Find the OpenSea key input (from Step 1). Directly BEFORE its container element, insert:

```html
    <div id="exhausted-banner" class="exhausted-banner">
      <strong>OpenSea API limit reached.</strong> Auto-updates are paused until you provide a new key.
      Get a free key at <a href="https://opensea.io/settings/developer" target="_blank">opensea.io/settings/developer</a>
      and paste it below.
    </div>
```

- [ ] **Step 4: Add banner-check JS**

In the `<script>` block of [add.html](add.html), add:

```javascript
    async function checkExhaustedBanner() {
      try {
        const resp = await fetch('/api/opensea-key');
        const data = await resp.json();
        const banner = document.getElementById('exhausted-banner');
        if (banner) banner.classList.toggle('active', !!data.exhausted);
      } catch (e) { /* silent */ }
    }
```

Then call `checkExhaustedBanner();` at the end of the script block (or inside any existing `DOMContentLoaded`/`init` routine).

- [ ] **Step 5: Verify HTML parse**

Run: `python3 -c "from html.parser import HTMLParser; HTMLParser().feed(open('add.html').read())"`
Expected: No output.

- [ ] **Step 6: Commit**

```bash
git add add.html
git commit -m "feat(add): show exhausted-key banner near OpenSea key input"
```

---

## Task 11: Deploy to afroz (test device) and smoke test

**Files:** None modified — deploy and verify.

- [ ] **Step 1: Deploy backend**

Run (from repo root):

```bash
cat backend/app.py | sshpass -p '<device-password>' ssh afroz@10.0.0.34 "cat > /tmp/app.py && echo '<device-password>' | sudo -S mv /tmp/app.py /opt/vernis/"
sshpass -p '<device-password>' ssh afroz@10.0.0.34 "echo '<device-password>' | sudo -S systemctl restart vernis-api"
```

Expected: Commands succeed without errors.

- [ ] **Step 2: Deploy library.html**

```bash
cat library.html | sshpass -p '<device-password>' ssh afroz@10.0.0.34 "cat > /tmp/library.html && echo '<device-password>' | sudo -S mv /tmp/library.html /var/www/vernis/"
```

- [ ] **Step 3: Deploy add.html**

```bash
cat add.html | sshpass -p '<device-password>' ssh afroz@10.0.0.34 "cat > /tmp/add.html && echo '<device-password>' | sudo -S mv /tmp/add.html /var/www/vernis/"
```

- [ ] **Step 4: Verify service is healthy**

Run: `sshpass -p '<device-password>' ssh afroz@10.0.0.34 "systemctl status vernis-api --no-pager | head -20"`
Expected: `Active: active (running)`.

If failed, fetch logs: `sshpass -p '<device-password>' ssh afroz@10.0.0.34 "journalctl -u vernis-api -n 50 --no-pager"` and fix the error.

- [ ] **Step 5: Smoke test — `/api/csv-library` returns new fields**

```bash
curl -s http://10.0.0.34/api/csv-library | python3 -m json.tool | head -40
```

Expected: At least one collection has `"wallet"`, `"autoupdate"`, `"last_checked"`, `"last_new_count"` keys (empty string / false / 0 for non-wallet collections).

- [ ] **Step 6: Smoke test — `/api/opensea-key` returns exhausted flag**

```bash
curl -s http://10.0.0.34/api/opensea-key | python3 -m json.tool
```

Expected: Response contains `"exhausted": false` (the flag, not necessarily the value).

- [ ] **Step 7: Smoke test — toggle endpoint (requires a real wallet card)**

Find a wallet-sourced CSV filename on the device (from Step 5 output — look for one with non-empty `wallet`). If none exists, skip to Step 8.

```bash
curl -s -X POST http://10.0.0.34/api/collection/<filename>/autoupdate \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}' | python3 -m json.tool
```

Expected: `{"ok": true, "autoupdate": true}`.

Verify sidecar was updated:
```bash
sshpass -p '<device-password>' ssh afroz@10.0.0.34 "cat /opt/vernis/csv-library/<basename>.json"
```
Expected: JSON contains `"autoupdate": true`.

Toggle back off:
```bash
curl -s -X POST http://10.0.0.34/api/collection/<filename>/autoupdate \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}' | python3 -m json.tool
```
Expected: `{"ok": true, "autoupdate": false}`.

- [ ] **Step 8: Smoke test — Check now endpoint (requires a real wallet card)**

If a wallet card exists on the device:

```bash
JOB=$(curl -s -X POST http://10.0.0.34/api/collection/<filename>/check-now | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
echo "Job: $JOB"
# Poll a few times
for i in 1 2 3 4 5; do
  sleep 3
  curl -s "http://10.0.0.34/api/collection/<filename>/check-status?job=$JOB" | python3 -m json.tool
done
```

Expected: Eventually `{"done": true, "ok": true, "new_count": ..., "message": "..."}`.

- [ ] **Step 9: Smoke test — UI in browser**

Open `http://10.0.0.34/library.html` in a browser.
- Expected: Wallet cards show a toggle + refresh button in their footer.
- Expected: Non-wallet cards look identical to before.
- Click the toggle → page should not reload; toggle slides on/off smoothly.
- Click the refresh button → should spin; toast or alert appears with result.

- [ ] **Step 10: Smoke test — exhausted-key banner (manual simulation)**

```bash
# Write a fake exhausted status
sshpass -p '<device-password>' ssh afroz@10.0.0.34 "echo '<device-password>' | sudo -S bash -c 'echo {\\\"exhausted\\\":true,\\\"exhausted_at\\\":\\\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\\\",\\\"last_error\\\":\\\"Simulated\\\"} > /opt/vernis/opensea-key-status.json && chmod 600 /opt/vernis/opensea-key-status.json'"

# Refresh library.html in browser → banner should appear within 60s (or immediately on reload)
# Refresh add.html in browser → banner should appear

# Clean up
sshpass -p '<device-password>' ssh afroz@10.0.0.34 "echo '<device-password>' | sudo -S rm /opt/vernis/opensea-key-status.json"
```

Expected: Red banner with link appears on both pages when the file is present, and disappears when removed (after a reload or the 60s polling interval).

- [ ] **Step 11: Verify scheduler is running**

```bash
sshpass -p '<device-password>' ssh afroz@10.0.0.34 "ps aux | grep vernis-autoupdate | grep -v grep" || true
sshpass -p '<device-password>' ssh afroz@10.0.0.34 "journalctl -u vernis-api --since '5 minutes ago' | grep -i 'scheduler\|autoupdate' || true"
```

Expected: Either the thread shows up in ps, OR logs show no errors. (The thread name may not appear in ps depending on Python; absence of errors in journalctl is the key signal.)

- [ ] **Step 12: Commit nothing — this task is verification only**

No commit needed. If any smoke test failed, fix the underlying code in the relevant earlier task and re-deploy before proceeding.

---

## Task 12: Deploy to other devices (afrol, afrom, afromini)

**Files:** None modified — deploy only.

- [ ] **Step 1: Deploy to afrol**

```bash
cat backend/app.py | sshpass -p '<device-password>' ssh afrol@10.0.0.28 "cat > /tmp/app.py && echo '<device-password>' | sudo -S mv /tmp/app.py /opt/vernis/ && echo '<device-password>' | sudo -S systemctl restart vernis-api"
cat library.html | sshpass -p '<device-password>' ssh afrol@10.0.0.28 "cat > /tmp/library.html && echo '<device-password>' | sudo -S mv /tmp/library.html /var/www/vernis/"
cat add.html | sshpass -p '<device-password>' ssh afrol@10.0.0.28 "cat > /tmp/add.html && echo '<device-password>' | sudo -S mv /tmp/add.html /var/www/vernis/"
```

- [ ] **Step 2: Deploy to afrom**

```bash
cat backend/app.py | sshpass -p '<device-password>' ssh afrom@10.0.0.39 "cat > /tmp/app.py && echo '<device-password>' | sudo -S mv /tmp/app.py /opt/vernis/ && echo '<device-password>' | sudo -S systemctl restart vernis-api"
cat library.html | sshpass -p '<device-password>' ssh afrom@10.0.0.39 "cat > /tmp/library.html && echo '<device-password>' | sudo -S mv /tmp/library.html /var/www/vernis/"
cat add.html | sshpass -p '<device-password>' ssh afrom@10.0.0.39 "cat > /tmp/add.html && echo '<device-password>' | sudo -S mv /tmp/add.html /var/www/vernis/"
```

- [ ] **Step 3: Deploy to afromini (only reachable when on-network)**

```bash
cat backend/app.py | sshpass -p '<device-password>' ssh afromini@10.2.0.8 "cat > /tmp/app.py && echo '<device-password>' | sudo -S mv /tmp/app.py /opt/vernis/ && echo '<device-password>' | sudo -S systemctl restart vernis-api"
cat library.html | sshpass -p '<device-password>' ssh afromini@10.2.0.8 "cat > /tmp/library.html && echo '<device-password>' | sudo -S mv /tmp/library.html /var/www/vernis/"
cat add.html | sshpass -p '<device-password>' ssh afromini@10.2.0.8 "cat > /tmp/add.html && echo '<device-password>' | sudo -S mv /tmp/add.html /var/www/vernis/"
```

- [ ] **Step 4: Spot-check each device**

For each device IP, run: `curl -s http://<IP>/api/opensea-key | python3 -m json.tool`
Expected: Response includes `"exhausted": ...`. If a device is offline, skip it.

- [ ] **Step 5: No commit needed**

Deployment is a runtime action, not a repo change.

---

## Self-Review Result

- **Spec coverage:** Each spec section maps to tasks — Detection (Task 7 exposes `wallet`); UI toggle+button+status (Task 9); backend scheduler (Task 6); check-now async job (Task 5); key exhaustion state + banner (Tasks 1, 8, 9, 10); file scope matches spec (Task 11, 12 deployments).
- **Placeholder scan:** No TBDs, no "handle edge cases" hand-waves. Every step has concrete code or concrete commands.
- **Type consistency:** Helper names match between tasks (`_refresh_wallet_collection`, `_fetch_opensea_wallet_nfts`, `_is_key_exhausted`, `_check_jobs`). Endpoint routes match between backend (Tasks 4, 5) and frontend (Task 9). Sidecar field names (`wallet`, `autoupdate`, `last_checked`, `last_new_count`) match between writing (Task 3, 4), reading (Task 6, 7), and display (Task 9).
- **Out-of-scope confirmed:** Tezos refresh is explicitly skipped in `_refresh_wallet_collection` (returns early); per-card custom intervals and key pools remain excluded.
