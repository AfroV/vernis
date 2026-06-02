# Download Failure UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-card expand UI on library collection cards that surfaces *why* files failed to download, visually separates likely-to-succeed errors from less-likely ones, and offers a single "Retry all failed" button that retries every failed file regardless of group.

**Architecture:** A new helper classifies raw error strings into `likely`/`unlikely` buckets with human labels. A new endpoint packages that classification plus summary counts into a compact response. Library cards with `failed_count > 0` render a chevron that, when tapped, fetches the report and reveals an inline expand area inside the card with counts, top reasons, a full-width retry button, and a secondary "View details" reveal for the raw per-file list. The existing `/api/retry-failed` endpoint is reused for retries.

**Tech Stack:** Python 3 + Flask (backend); plain HTML/CSS/JS (frontend). No new dependencies. No pytest suite — verification is manual (curl + UI).

**Known limitation (documented, not solved here):** The backend persists download progress in a single global file (`/opt/vernis/nfts/download_progress.json`). Failure data is only available for the *most recent* download — installing a new collection overwrites the progress file. The new endpoint returns `failed_count: 0` whenever the global progress file's `source_csv` doesn't match the requested collection. Historical failure persistence across multiple installs is a separate future project.

---

## File Structure

- `backend/app.py`:
  - Insert `_classify_download_error(err_string)` helper near the existing download/progress endpoints
  - Insert `GET /api/collection/<path:filename>/failure-report` endpoint
  - Extend the `/api/csv-library` collection response with a `failed_count` field
- `library.html`:
  - Add CSS block for `.card-failure-expand` and its sub-classes
  - Add JS helpers: `toggleFailureExpand`, `fetchFailureReport`, `renderFailureExpand`, `toggleDetailsList`, `retryFailedDownloads`, `formatReasonsLine`
  - Modify card render template to emit a chevron and expand container when `col.failed_count > 0`

No new files, no new Python deps, no new JS deps.

---

## Task 1: Add `_classify_download_error` helper

**Files:** Modify `backend/app.py` — insert helper directly before the existing `@app.route("/api/retry-failed"` decorator (around line 826 — find with Grep).

- [ ] Step 1: Find with Grep: `@app.route("/api/retry-failed", methods=["POST"])`. Directly BEFORE that decorator, insert:

```python
def _classify_download_error(err_string):
    """Return (bucket, human_label) where bucket is 'likely' or 'unlikely'.

    All failures are retryable in the UI — this classification is only a
    visual hint to help users set expectations about whether a retry will help.
    """
    s = (err_string or "").lower()

    # Unlikely to succeed on retry: content gone or malformed
    if "404" in s: return ("unlikely", "missing on gateway")
    if "410" in s: return ("unlikely", "deliberately removed")
    if "451" in s: return ("unlikely", "legal takedown")
    if "400" in s: return ("unlikely", "bad CID")

    # Likely to succeed on retry: transient server/network issues
    if "429" in s: return ("likely", "rate limited")
    if "403" in s: return ("likely", "access blocked")
    if "timeout" in s or "timed out" in s: return ("likely", "timed out")
    if "connection" in s or "unreachable" in s or "dns" in s or "name resolution" in s:
        return ("likely", "gateway offline")
    if any(code in s for code in ("500", "502", "503", "504")):
        return ("likely", "gateway error")

    # Default: treat as likely
    return ("likely", err_string or "unknown error")
```

- [ ] Step 2: Verify syntax
  Run: `python3 -c "import ast; ast.parse(open('/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/backend/app.py').read())"`
  Expected: no output.

- [ ] Step 3: Manual spot-check the helper via Python REPL. Paste the function body from Step 1, then run:

```python
fn = _classify_download_error
assert fn("HTTP 404") == ("unlikely", "missing on gateway")
assert fn("HTTP 429") == ("likely", "rate limited")
assert fn("Connection timeout") == ("likely", "timed out")
assert fn("NameResolutionError") == ("likely", "gateway offline")
assert fn("HTTP 503") == ("likely", "gateway error")
assert fn("HTTP 400") == ("unlikely", "bad CID")
assert fn("") == ("likely", "unknown error")
assert fn("weird unexpected error") == ("likely", "weird unexpected error")
print("all asserts pass")
```
Expected: `all asserts pass`.

---

## Task 2: Add `/api/collection/<filename>/failure-report` endpoint

**Files:** Modify `backend/app.py` — insert new endpoint directly after `_classify_download_error` from Task 1.

- [ ] Step 1: Insert:

```python
@app.route("/api/collection/<path:filename>/failure-report", methods=["GET"])
def collection_failure_report(filename):
    """Return classified failure breakdown for a collection.

    Data source is the global download_progress.json. Only returns meaningful
    data when its 'source_csv' matches the requested filename.
    """
    if "/" in filename or ".." in filename or not filename.endswith(".csv"):
        return jsonify({"error": "Invalid filename"}), 400

    include_details = request.args.get("details", "").strip() in ("1", "true", "yes")

    empty = {
        "filename": filename,
        "completed": 0,
        "total": 0,
        "in_progress": False,
        "failed_count": 0,
        "likely": {"count": 0, "top_reasons": []},
        "unlikely": {"count": 0, "top_reasons": []},
    }

    try:
        active_nft_dir = get_active_nft_dir()
    except Exception:
        return jsonify(empty)

    progress_file = active_nft_dir / "download_progress.json"
    if not progress_file.exists() and active_nft_dir != NFT_DIR:
        progress_file = NFT_DIR / "download_progress.json"

    if not progress_file.exists():
        return jsonify(empty)

    try:
        pdata = json.loads(progress_file.read_text())
    except Exception:
        return jsonify(empty)

    if pdata.get("source_csv", "") != filename:
        return jsonify(empty)

    failed_raw = pdata.get("failed", {})
    if isinstance(failed_raw, list):
        failed_items = [(item, "unknown") for item in failed_raw]
    elif isinstance(failed_raw, dict):
        failed_items = [(k, str(v) if v is not None else "unknown") for k, v in failed_raw.items()]
    else:
        failed_items = []

    likely_items = []
    unlikely_items = []
    likely_reason_counts = {}
    unlikely_reason_counts = {}

    for name, err in failed_items:
        bucket, reason = _classify_download_error(err)
        if bucket == "likely":
            likely_items.append({"name": name, "err": err, "bucket": "likely", "reason": reason})
            likely_reason_counts[reason] = likely_reason_counts.get(reason, 0) + 1
        else:
            unlikely_items.append({"name": name, "err": err, "bucket": "unlikely", "reason": reason})
            unlikely_reason_counts[reason] = unlikely_reason_counts.get(reason, 0) + 1

    def top_reasons(counts, limit=2):
        return sorted(counts.items(), key=lambda kv: -kv[1])[:limit]

    try:
        file_age = time.time() - progress_file.stat().st_mtime
    except Exception:
        file_age = 1e9
    try:
        proc_check = subprocess.run(["pgrep", "-f", "nft_downloader"], capture_output=True)
        process_alive = proc_check.returncode == 0
    except Exception:
        process_alive = False
    in_progress = (file_age < 30 or process_alive)

    result = {
        "filename": filename,
        "completed": pdata.get("completed", 0),
        "total": pdata.get("total", 0),
        "in_progress": in_progress,
        "failed_count": len(failed_items),
        "likely": {
            "count": len(likely_items),
            "top_reasons": top_reasons(likely_reason_counts),
        },
        "unlikely": {
            "count": len(unlikely_items),
            "top_reasons": top_reasons(unlikely_reason_counts),
        },
    }

    if include_details:
        result["details"] = likely_items + unlikely_items

    return jsonify(result)
```

- [ ] Step 2: Verify syntax
  Run: `python3 -c "import ast; ast.parse(open('/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/backend/app.py').read())"`
  Expected: no output.

- [ ] Step 3: Verify endpoint registered
  Run: `grep -n "failure-report" "/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/backend/app.py"`
  Expected: one match on the `@app.route` line.

---

## Task 3: Extend `/api/csv-library` with `failed_count`

**Files:** Modify `backend/app.py` — `csv_library()`'s `collections.append({...})` block.

- [ ] Step 1: Find: `grep -n '"last_new_count": metadata' "/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/backend/app.py"`
  Expected: one match inside the `collections.append({...})` block from the autoupdate feature.

- [ ] Step 2: Replace the entire append block (current shape shown below):

Current:
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

Replace with:
```python
            failed_count_for_card = 0
            try:
                _pf = NFT_DIR / "download_progress.json"
                if _pf.exists():
                    _pdata = json.loads(_pf.read_text())
                    if _pdata.get("source_csv", "") == csv_file.name:
                        _failed = _pdata.get("failed", {})
                        if isinstance(_failed, list):
                            failed_count_for_card = len(_failed)
                        elif isinstance(_failed, dict):
                            failed_count_for_card = len(_failed)
            except Exception:
                pass

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
                "failed_count": failed_count_for_card,
            })
```

- [ ] Step 3: Verify syntax
  Run: `python3 -c "import ast; ast.parse(open('/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/backend/app.py').read())"`
  Expected: no output.

---

## Task 4: library.html — CSS for the expand UI

**Files:** Modify `library.html` — add new rules inside existing `<style>` block.

- [ ] Step 1: Find insertion point
  Run: `grep -n "card-autoupdate-status" "/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/library.html"`
  Expected: matches in CSS + JS. Pick the line where the `.card-autoupdate-status { ... }` rule's closing `}` is.

- [ ] Step 2: Directly AFTER that closing `}`, insert:

```css
    .card-failure-expand {
      margin-top: 8px;
      padding: 10px;
      background: rgba(255, 255, 255, 0.04);
      border-radius: 6px;
      font-size: 12px;
      line-height: 1.4;
      display: none;
    }
    .card-failure-expand.open { display: block; }
    .card-failure-header {
      font-size: 11px;
      color: rgba(255, 255, 255, 0.55);
      margin-bottom: 8px;
    }
    .card-failure-row {
      display: flex;
      align-items: baseline;
      gap: 8px;
      margin: 6px 0;
    }
    .card-failure-row .icon {
      width: 16px;
      display: inline-block;
      text-align: center;
      flex-shrink: 0;
    }
    .card-failure-row .meta { flex: 1; }
    .card-failure-row .count { font-weight: 600; }
    .card-failure-row .reasons {
      display: block;
      font-size: 11px;
      color: rgba(255, 255, 255, 0.55);
      margin-top: 2px;
    }
    .card-failure-row-likely .icon { color: #3b82f6; }
    .card-failure-row-likely .count { color: #3b82f6; }
    .card-failure-row-unlikely .icon { color: #888; }
    .card-failure-row-unlikely .count { color: #aaa; }
    .card-failure-row-unlikely .meta { opacity: 0.85; }
    .card-failure-actions {
      display: flex;
      gap: 8px;
      margin-top: 10px;
      align-items: center;
    }
    .card-failure-retry {
      flex: 1;
      min-height: 44px;
      background: #3b82f6;
      color: #fff;
      border: none;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }
    .card-failure-retry:disabled {
      background: #3b82f680;
      cursor: not-allowed;
    }
    .card-failure-retry:hover:not(:disabled) { background: #2563eb; }
    .card-failure-details-toggle {
      background: transparent;
      border: none;
      color: rgba(255, 255, 255, 0.55);
      font-size: 11px;
      cursor: pointer;
      padding: 10px 6px;
      min-height: 44px;
    }
    .card-failure-details-toggle:hover { color: rgba(255, 255, 255, 0.85); }
    .card-failure-details-list {
      max-height: 200px;
      overflow-y: auto;
      margin-top: 8px;
      padding: 6px;
      background: rgba(0, 0, 0, 0.3);
      border-radius: 4px;
      font-family: monospace;
      font-size: 10px;
      display: none;
    }
    .card-failure-details-list.open { display: block; }
    .card-failure-details-list .row {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      padding: 2px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }
    .card-failure-details-list .row:last-child { border-bottom: none; }
    .card-failure-details-list .name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .card-failure-details-list .err {
      color: rgba(255, 255, 255, 0.55);
      flex-shrink: 0;
    }
    .card-failure-chevron {
      display: inline-block;
      cursor: pointer;
      padding: 4px 6px;
      margin-left: 8px;
      color: #f59e0b;
      font-weight: 600;
      user-select: none;
    }
    .card-failure-chevron:hover { color: #fbbf24; }
```

- [ ] Step 3: Verify
  Run HTML parse sanity + grep:
  `python3 -c "from html.parser import HTMLParser; HTMLParser().feed(open('/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/library.html').read())"` — no output.
  `grep -c "card-failure-" "/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/library.html"` — ≥ 20.

---

## Task 5: library.html — JS helpers

**Files:** Modify `library.html` — add JS functions inside the existing `<script>` block. The file already uses `innerHTML` + `escHTML()` extensively (established project pattern); we follow that pattern. All user-supplied strings that flow into markup are escaped via `escHTML()`.

- [ ] Step 1: Find insertion point
  `grep -n "function checkExhaustedBanner" "/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/library.html"` — one match. Insert new JS directly AFTER that function's closing `}`.

- [ ] Step 2: Write the JS helpers in a separate file so I can paste them verbatim. Create `/tmp/failure-ux-helpers.js` with the content below, then copy its contents into `library.html` at the insertion point.

See `docs/superpowers/plans/2026-04-18-download-failure-ux.helpers.js` (sibling file — created in the next step; it contains the JS code block to paste).

- [ ] Step 3: Verify
  `python3 -c "from html.parser import HTMLParser; HTMLParser().feed(open('/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/library.html').read())"` — no output.
  `grep -c "toggleFailureExpand\|retryFailedDownloads\|fetchFailureReport\|renderFailureExpand" "/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/library.html"` — ≥ 8.

---

## Task 6: library.html — card template: chevron + expand container

**Files:** Modify `library.html` — the card render template inside `filteredCollections.map(...)`.

- [ ] Step 1: Find
  `grep -n "col.wallet ?" "/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/library.html"` — at least one match (wallet block added in autoupdate feature).

- [ ] Step 2: Add the expand container after the wallet block. Find the block starting with:

```javascript
      ${col.wallet ? `
      <div class="card-autoupdate">
```

Find its closing `` ` : ''}``. DIRECTLY AFTER that closing, insert:

```javascript
      ${(col.failed_count && col.failed_count > 0) ? `
      <div class="card-failure-expand" data-filename="${sf}"></div>
      ` : ''}
```

- [ ] Step 3: Add a chevron inside the `.card-progress-text` div.
  Run: `grep -n 'card-progress-text"></div>' "/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/library.html"` — one match inside the card template.

Replace that self-closing empty div with:

```javascript
      <div class="card-progress-text">
        ${(col.failed_count && col.failed_count > 0) ? `<span class="card-failure-chevron" onclick="event.stopPropagation(); toggleFailureExpand('${sf}', this.closest('.card'))">▾ ${col.failed_count} failed</span>` : ''}
      </div>
```

- [ ] Step 4: Verify
  `python3 -c "from html.parser import HTMLParser; HTMLParser().feed(open('/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/library.html').read())"` — no output.
  `grep -n "toggleFailureExpand" "/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/library.html"` — ≥ 2 (function def + onclick).

---

## Task 7: Local static sanity check

**Files:** None modified — verification only.

- [ ] Step 1: Python + HTML parse both pass:
```
python3 -c "import ast; ast.parse(open('/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/backend/app.py').read())"
python3 -c "from html.parser import HTMLParser; HTMLParser().feed(open('/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/library.html').read())"
```
Expected: no output from either.

- [ ] Step 2: Verify new symbols are wired:
```
grep -c "_classify_download_error\|failure-report\|card-failure-\|toggleFailureExpand\|fetchFailureReport\|retryFailedDownloads\|renderFailureExpand\|formatReasonsLine" "/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/backend/app.py" "/Users/sharthansimoons/My Drive/3dPrinter/artboxv3/library.html"
```
Expected: both files ≥ 5.

---

## Task 8: Deploy to afrom + real-world smoke test (user-gated)

**Files:** None — deploy + verify. Requires 10.0.0.39 reachable.

- [ ] Step 1: Reach check
  `curl -s --max-time 5 -o /dev/null -w "%{http_code}\n" http://10.0.0.39/api/csv-library` — `200`.

- [ ] Step 2: Deploy backend (from project root):
```
cat backend/app.py | sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrom@10.0.0.39 "cat > /tmp/app.py && echo '<device-password>' | sudo -S mv /tmp/app.py /opt/vernis/ && echo '<device-password>' | sudo -S systemctl restart vernis-api && sleep 3 && systemctl is-active vernis-api"
```
Expected: `active`.

- [ ] Step 3: Deploy library.html:
```
cat library.html | sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrom@10.0.0.39 "cat > /tmp/library.html && echo '<device-password>' | sudo -S mv /tmp/library.html /var/www/vernis/ && echo OK"
```
Expected: `OK`.

- [ ] Step 4: Verify csv-library returns `failed_count`:
```
curl -s http://10.0.0.39/api/csv-library | python3 -c "import sys,json; cols=json.load(sys.stdin)['collections']; print('All have failed_count:', all('failed_count' in c for c in cols))"
```
Expected: `All have failed_count: True`.

- [ ] Step 5: Verify failure-report responds. Pick a filename `FN` from the csv-library response:
```
FN="<some-collection.csv>"
curl -s "http://10.0.0.39/api/collection/$FN/failure-report" | python3 -m json.tool
```
Expected: valid JSON with all keys. `failed_count` is 0 unless this collection was the most recent download.

- [ ] Step 6: Path traversal blocked:
```
curl -s -o /dev/null -w "%{http_code}\n" "http://10.0.0.39/api/collection/..%2Fescape.csv/failure-report"
```
Expected: `400`.

- [ ] Step 7: Simulate failures and run UX end-to-end. Pick a filename `FN` present on the device:
```
FN="<your-collection.csv>"
sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrom@10.0.0.39 "echo '<device-password>' | sudo -S tee /opt/vernis/nfts/download_progress.json >/dev/null <<EOF
{\"source_csv\": \"$FN\", \"completed\": 12, \"total\": 20, \"failed\": {\"Qm123\": \"HTTP 404\", \"Qm456\": \"HTTP 404\", \"Qm789\": \"HTTP 429\", \"Qmabc\": \"Connection timeout\", \"Qmdef\": \"HTTP 400\"}, \"downloaded\": [], \"bytes_downloaded\": 0, \"speed\": 0}
EOF
echo '<device-password>' | sudo -S chown afrom:afrom /opt/vernis/nfts/download_progress.json"
```

Check endpoint:
```
curl -s "http://10.0.0.39/api/collection/$FN/failure-report" | python3 -m json.tool
```
Expected: `failed_count: 5`, `likely.count: 2`, `unlikely.count: 3`.

Reload `http://10.0.0.39/library.html`:
- Card for `$FN` shows `▾ 5 failed` in the progress-text area
- Tap chevron: reveal shows the two group rows + retry button
- Retry button label: `Retry all 5 failed`; tapping calls `/api/retry-failed` and shows toast
- Tap "View details ▾": reveals 5 raw rows

Clean up:
```
sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrom@10.0.0.39 "echo '<device-password>' | sudo -S rm /opt/vernis/nfts/download_progress.json"
```

---

## Self-Review Result

**Spec coverage:**
- Detection (chevron appears when `failed_count > 0`) — Task 3 (backend field) + Task 6 (frontend render)
- Expand contents — Task 5 (JS render) + Task 4 (CSS)
- Classification rules — Task 1
- Endpoint shape — Task 2
- Retry wiring to existing `/api/retry-failed` — Task 5 `retryFailedDownloads`
- Less-likely grey de-emphasis — Task 4 `.card-failure-row-unlikely`
- In-progress disables retry — Task 5 render sets `disabled` when `report.in_progress`
- Page reload collapses — no persistence code, matches spec
- Known limitation — documented at plan header

**Placeholder scan:** No TBDs. Every step contains concrete code or commands. Task 5's JS lives in a sibling file (created as part of the plan, see `.helpers.js` — written by Task 5 Step 2).

**Type consistency:**
- `_classify_download_error` returns `(bucket, label)` with bucket ∈ `{'likely', 'unlikely'}` — matched in Task 2, Task 4 CSS classes, Task 5 render
- `failed_count` used in Task 3 (backend) and Task 6 (template conditional)
- Endpoint path matches between Task 2 (route) and Task 5 JS fetch
- `toggleFailureExpand(filename, cardEl)` signature matches between Task 5 (definition) and Task 6 (onclick)
