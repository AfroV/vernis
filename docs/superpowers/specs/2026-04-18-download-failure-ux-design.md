# Download Failure UX — Design Spec

**Date:** 2026-04-18
**Status:** Draft — awaiting user review

## Goal

When a collection card ends up partial (some files downloaded, others failed), surface *what failed and why* directly inside the card. All failures are retryable — IPFS gateways come and go, so even "404 missing" might resolve later — but the UI sets expectations by visually grouping errors into *likely to succeed* and *less likely to succeed*. Collapse the common dead-end question *"why isn't this at 100% and what can I do about it?"* into an inline answer and a single-tap retry.

## Scope

**In scope:**
- In-card expand UI on any collection card whose progress file records `failed_count > 0`
- Visual classification of failure reasons into two groups: *likely to succeed on retry* and *less likely to succeed*
- Summary counts + top error types per group
- Secondary "View details" reveal for the full per-file list (behind a second tap)
- Single "Retry all failed" button that retries **every** failed file regardless of group — IPFS gateway availability is volatile enough that even 404s can come back
- New backend endpoint that packages the classification into one response

**Out of scope:**
- Per-file retry buttons (rejected during brainstorming — cumbersome on 4" touchscreen)
- Auto-retry on a schedule (the existing downloader already retries during the active run; scheduled re-retries would be a separate feature)
- Cross-card aggregated failures view (e.g. a global "Downloads" page)
- Persisted expand state across full page reloads (collapse on refresh is fine)
- Removing failed rows from the CSV (preserves history; user can still manually delete the collection if they want)

## Detection: when does the expand UI appear?

A card renders the expand chevron when its progress data (served by `/api/csv-library/status/<filename>` or the new failure-report endpoint) reports `failed_count > 0`. This applies to any card type — curated CSV, wallet-imported CSV, contract import — not just wallet cards.

Chevron placement: end of the existing `.card-progress-text` line, replacing/augmenting the current "X/Y" text with `"12 of 20 · ▾ details"`.

Expand state: in-memory only. On page reload, all cards collapse back to their default. Keeps the implementation simple and matches the existing library behaviour where the card state is always derived fresh from the API.

## UI — expanded card contents

When the chevron is tapped, the card's body grows downward (other cards in the grid reflow) to show:

```
htmlnft.eth — 12 of 20 downloaded
──────────────────────────────────
⚠ 5 likely to succeed on retry
   gateway offline (3), rate limited (2)
✗ 3 less likely (may need time or a new gateway)
   missing on gateway (2), bad CID (1)

[  Retry all 8 failed  ]          [ View details ▾ ]
```

**Elements:**
- **Header line**: `{collection name} — {completed} of {total} downloaded`
- **Likely-to-succeed group** (blue `#3b82f6` accent): count + top 2 error categories (human names like "gateway offline", not raw "HTTP 503"). These are transient network/server errors that often clear up.
- **Less-likely group** (grey `#888`, de-emphasised): count + top 2 error categories. Shown with a small note like *"may need time or a new gateway"* so the user understands why these are grouped differently but still retryable.
- **Retry button**: full-width touch target (≥44px tall). Label shows total failure count across **both** groups. Tapping calls `POST /api/retry-failed` with the collection filename; shows a spinner until the retry batch kicks off; then toast: *"Retrying 8 files"*. The download progress bar resumes in place. Every failed file is included in the retry — no filtering by group.
- **View details link**: secondary text button. Tapping reveals a scrollable (`max-height: 200px`) plain list of each failure: `filename  HTTP 404`. No per-row retry buttons. Intended for the curious user and for diagnostic copy-paste, not the default path.

If `failed_count === 0` the card renders unchanged (no chevron, no expand markup). If a download is still in progress and some have already failed, the expand still works and shows *"downloading... {X} failed so far"*. Retry button is disabled while an active download is running — the existing downloader retries these internally first.

## Backend — error classification

New helper in [backend/app.py](backend/app.py):

```python
def _classify_download_error(err_string):
    """Return (bucket, human_label) where bucket is 'likely' or 'unlikely'.

    All failures are retryable — bucket is only a visual hint for the UI
    to set user expectations.
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

    # Default: treat as likely (err on side of giving user hope)
    return ("likely", err_string or "unknown error")
```

The matching is deliberately substring-based on the raw error string the downloader writes. The downloader currently writes things like `"HTTP 404"`, `"HTTP 429"`, `"Connection timeout"`, `"NameResolutionError: ..."`. Substring match handles all of them without requiring downloader changes.

New endpoint:

```
GET /api/collection/<filename>/failure-report[?details=1]
```

Response:

```json
{
  "filename": "htmlnft.eth.csv",
  "completed": 12,
  "total": 20,
  "in_progress": false,
  "failed_count": 8,
  "likely": {
    "count": 5,
    "top_reasons": [["gateway offline", 3], ["rate limited", 2]]
  },
  "unlikely": {
    "count": 3,
    "top_reasons": [["missing on gateway", 2], ["bad CID", 1]]
  },
  "details": [
    {"name": "Qm123...", "err": "HTTP 404", "bucket": "unlikely", "reason": "missing on gateway"},
    ...
  ]
}
```

`details` only included when `?details=1` query param is present, to keep the common fetch small.

`in_progress` is `true` when a downloader process is currently running for this collection — used by the frontend to disable the Retry button and re-label counts as "{X} failed so far".

**Retry wiring:** The UI calls the existing `POST /api/retry-failed` endpoint at [backend/app.py:826](backend/app.py#L826). That endpoint already reads the failed dict, builds a retry CSV, and spawns the downloader. No new retry endpoint.

## Files changed

- [backend/app.py](backend/app.py):
  - Add `_classify_download_error(err_string)` helper (~25 lines)
  - Add `GET /api/collection/<filename>/failure-report` endpoint (~40 lines)
  - Total: ~65 lines of Python
- [library.html](library.html):
  - Extend the collection-card render template to include the expand chevron + container when `col.failed_count > 0`
  - Add JS handlers: `toggleFailureExpand(filename, cardEl)`, `fetchFailureReport(filename, cardEl, withDetails=false)`, `retryFailedDownloads(filename, cardEl)`
  - Add CSS for `.card-failure-expand`, `.card-failure-row-likely`, `.card-failure-row-unlikely`, `.card-failure-details-list`
  - Total: ~180 lines of HTML/CSS/JS
- No new files, no new Python deps

## Edge cases

- **Card never downloaded**: no progress file → `failed_count` undefined → no expand UI. Matches current behaviour.
- **All files failed**: `completed: 0, total: 20, failed_count: 20`. Expand UI works normally — only one of the two groups may be populated, which is fine.
- **Retry triggers mid-active-download**: the existing `/api/retry-failed` endpoint handles this (it spawns a new downloader process). The progress file gets updated by whichever process writes last. Acceptable race.
- **Progress file corrupted**: endpoint returns `{"error": "...", "failed_count": 0}`; card doesn't show expand. Same as "no data" fallback.
- **User closes the expand then retry is still running**: retry continues server-side; next expand reopen shows updated counts.
- **`failed` dict has non-string values**: defensive — `_classify_download_error` coerces to string first.

## Testing

- **Manual unit**: feed `_classify_download_error` the 10 common error strings that appear in production progress files and verify bucket + label. Throwaway script.
- **Manual integration**: on afrom, hit `GET /api/collection/htmlnft.eth.csv/failure-report` and confirm response structure.
- **Manual UI**: open `http://10.0.0.39/library.html`, tap an existing partial card, confirm expand opens, retry button triggers downloader (verify via journalctl).
- **No automated tests** — this project has no pytest suite; matching existing project practice.
