# Wallet Auto-Update — Design Spec

**Date:** 2026-04-17
**Status:** Draft — awaiting user review

## Goal

Let users toggle automatic daily checks on wallet-sourced library cards. When enabled, Vernis queries OpenSea for the wallet's current NFTs, diffs against what's already downloaded, and pulls any new ones. Users can also trigger an immediate check from the card.

## Scope

**In scope:**
- Auto-update toggle on library cards that represent a wallet (ENS or 0x address)
- Per-card "Check now" button
- Daily scheduled checks, staggered across enabled wallets
- Clear handling of OpenSea API key exhaustion with a user-facing recovery path

**Out of scope:**
- Per-card custom intervals (daily default is fixed; no per-card override)
- Key pools / automatic rotation (single key model; user rotates manually when exhausted)
- Non-wallet cards (CSV uploads, contract imports, curated library)
- Tezos wallets (initial version; existing code already handles via objkt.com but scheduler focuses on the common case)

## Detection: what qualifies as a wallet card?

A library card is a wallet card **if and only if** its sidecar JSON (`<name>.json` next to `<name>.csv` in `CSV_LIBRARY_DIR`) contains a non-empty `wallet` field.

The existing one-click wallet import at [backend/app.py:5821](backend/app.py#L5821) already writes this field. No migration or backfill needed — cards added before this feature simply won't have the toggle, which is correct.

## UI — library.html

On each wallet card:

- **Auto-update toggle** — small toggle switch (reuse existing `.toggle` CSS from settings.html); positioned in card footer area
- **"Check now" button** — icon-only refresh arrow next to the toggle; visible on all wallet cards regardless of toggle state
- **Status line** — small muted text under toggle when enabled: `Last checked: 2h ago` (derived from sidecar `last_checked`)

Interactions:

- Toggle change → `POST /api/collection/<filename>/autoupdate` with `{enabled: true|false}` → backend writes `autoupdate` field into sidecar; UI updates status line
- Check now tap → `POST /api/collection/<filename>/check-now` → card shows inline spinner; on response, toast: `"3 new NFTs downloading"`, `"No new NFTs"`, or error message
- If backend returns `opensea_key_exhausted: true` in any response, library renders a top-of-page banner (see Section: Key Exhaustion)

Non-wallet cards render unchanged.

## Backend scheduler

**Thread model:** Single daemon thread started at Flask boot (during app init, not on first request). Survives until process dies. On systemd restart, it re-starts naturally.

**Tick interval:** Every 1 hour the thread wakes, scans sidecars, and enqueues due checks. Hourly granularity is cheap and gives natural staggering across a 24h window.

**Due logic:** A card is due if `autoupdate == true` and `now - last_checked >= 24h`. Missing `last_checked` is treated as due (first run).

**Processing:** Queue is drained sequentially within the tick — one wallet at a time, ~60s sleep between wallets. This spreads API load and keeps the scheduler thread lightweight. If the queue is long (>10 wallets), the remaining items naturally roll to the next hourly tick.

**Refresh core — `_refresh_wallet_collection(filename)` helper:**

1. Read sidecar to get `wallet` address and `chains` list
2. Read existing CSV to build a set of `(contract_address, token_id)` tuples already present
3. Call OpenSea v2 for the wallet (reuse logic from `/api/import-wallet`)
4. Diff fetched NFTs against existing set → new rows only
5. Append new rows to CSV; update sidecar with `last_checked: <iso timestamp>` and `last_new_count: <int>`
6. If new rows exist, trigger the existing downloader in a background thread for just those rows

Extract this helper from the existing [backend/app.py:5651](backend/app.py#L5651) `/api/import-wallet` endpoint so both that endpoint and the scheduler call the same code. Keep the existing endpoint's behaviour unchanged for first-time imports.

**State persistence:** `last_checked` lives in the sidecar JSON — no separate state file. Scheduler is stateless across restarts and picks up naturally from sidecar timestamps.

## API endpoints (new)

- `POST /api/collection/<filename>/autoupdate` — body `{enabled: bool}` → writes `autoupdate` field into sidecar; returns `{ok: true, autoupdate: <bool>}`. 404 if sidecar missing or has no `wallet` field.
- `POST /api/collection/<filename>/check-now` — runs `_refresh_wallet_collection` in a background thread and returns immediately with `{ok: true, job_id: <uuid>}`. Frontend polls `GET /api/collection/<filename>/check-status?job=<uuid>` every 2s until it returns `{done: true, new_count: <int>, message: "..."}` or `{done: true, error: "...", opensea_key_exhausted: <bool>}`. Job state kept in an in-memory dict keyed by job_id, evicted 5 min after completion.

Filename validation: must match existing sidecars in `CSV_LIBRARY_DIR`; reject path traversal.

## OpenSea key exhaustion

**State file:** `/opt/vernis/opensea-key-status.json`

```json
{
  "exhausted": true,
  "exhausted_at": "2026-04-17T14:23:00Z",
  "last_error": "HTTP 429 from OpenSea"
}
```

**When triggered:** Any OpenSea call (from scheduler or manual Check now) returning HTTP 429 or 401 sets this file. The scheduler halts further wallet checks for the rest of the hour.

**Scheduler behaviour while exhausted:**
- On each tick, read the status file. If `exhausted == true` and `now - exhausted_at < 24h`, skip the tick entirely (OpenSea resets daily).
- After 24h, clear the flag and resume.

**User recovery path:**
- `GET /api/opensea-key` already returns key info — extend its response with `exhausted: bool` and `exhausted_at` from the status file
- library.html and add.html both poll this on load; if exhausted, show a top-of-page banner:
  > **OpenSea API limit reached.** Get a free key at [opensea.io/settings/developer](https://opensea.io/settings/developer) and paste it below.
- Banner on add.html scrolls to / highlights the existing OpenSea key input field
- When user saves a new key via `POST /api/opensea-key`, backend clears the exhausted flag immediately and the banner disappears

**Shipped default key:** Unchanged — Vernis still ships with the hardcoded default key at [backend/app.py:4833](backend/app.py#L4833). When that gets exhausted, the same flow applies (user sets their own personal key).

## Files changed

- [backend/app.py](backend/app.py):
  - Extract `_refresh_wallet_collection(filename)` helper from `/api/import-wallet`
  - Add `POST /api/collection/<filename>/autoupdate`
  - Add `POST /api/collection/<filename>/check-now`
  - Add scheduler thread (started at app init)
  - Add `OPENSEA_KEY_STATUS_FILE` helpers (read/write/clear)
  - Extend `GET /api/opensea-key` response with `exhausted` field
- [library.html](library.html):
  - Render toggle + Check now button on wallet cards (cards with sidecar `wallet` field)
  - Wire toggle and Check now handlers
  - Render exhausted-key banner when detected
- [add.html](add.html):
  - Render same exhausted-key banner near the OpenSea key input

No new files, no new Python dependencies.

## Edge cases & error handling

- **Wallet with 0 NFTs currently** (previously had some): CSV is not truncated — autoupdate only *adds*, never removes. This matches user expectation (owned art stays on the frame even if transferred).
- **Sidecar corrupted / missing:** Autoupdate endpoints return 404; scheduler skips silently.
- **Flask restart mid-check:** Worst case is one wallet's check is abandoned; next tick picks it up via `last_checked` staleness.
- **Multiple identical ticks after long downtime:** Scheduler processes one wallet per ~60s, so a 24h gap on 10 wallets takes ~10 min to catch up — acceptable.
- **User disables toggle during a check:** In-flight check completes normally; next tick sees `autoupdate: false` and skips.
- **ENS re-resolution:** Sidecar already stores the resolved 0x address. No re-resolution needed.

## Testing

- Unit: `_refresh_wallet_collection` diff logic (mock OpenSea response + existing CSV)
- Integration: toggle endpoint round-trip (write → read sidecar)
- Manual: enable toggle on a real wallet card, confirm scheduler fires within 24h, confirm new NFT appears in CSV and downloads
- Manual: simulate 429 (temporarily set a bad key) → confirm banner appears on library + add pages
- Manual: save new key → confirm banner disappears and scheduler resumes
