# Vernis v3 — Security & Functional Testing Prompt

You are testing **Vernis**, a Raspberry Pi-based digital art frame that displays NFT/IPFS artwork. The web UI runs on `http://<device-ip>/` served by Caddy, with a Flask backend at `/api/*`.

Read `user-journeys.md` for full user flows. Split your testing into the subtasks below. Report findings ranked: **Critical / High / Medium / Low**.

---

## Subtask 1: Input Sanitization & Injection

Test all user inputs for injection attacks:

- **CID input** (`add.html`): Try path traversal (`../../etc/passwd`), shell injection (`; rm -rf /`), XSS (`<script>alert(1)</script>`) in the "Add by CID" field
- **WiFi SSID/password** (`settings.html`): Special characters, long strings, null bytes
- **CSV upload** (`add.html`): Malformed CSV, CSV with path traversal in filenames (`../../../etc/cron.d/evil`), oversized files, non-CSV extensions
- **Ethereum RPC URL** (`settings.html`): SSRF attempts (`http://169.254.169.254`, `http://localhost:5000/api/...`), javascript: URLs
- **Easter egg code input** (`library.html`): XSS in code entry, overflow strings
- **Collection/slideshow names** (`manage.html`): XSS in names, SQL-like injection
- **Search fields**: All text inputs across pages

## Subtask 2: API Endpoint Security

Test the Flask backend API directly (curl/fetch):

- **Authentication**: Are any endpoints protected? Can anyone on the network call `/api/shutdown`, `/api/reboot`, `/api/backup/export`?
- **File access**: Can `/api/nfts/../../etc/passwd` or `/nfts/../../../etc/shadow` read system files?
- **HTTPS endpoint** (`POST /api/https`): Can this be triggered remotely to modify Caddy config?
- **Display config** (`POST /api/display-config`): Arbitrary JSON injection
- **Backup import** (`POST /api/backup/import`): Zip slip attacks, hidden files (`.env`, `.ssh`), symlink traversal
- **Workers parameter**: Integer overflow, negative numbers, non-integer values
- **Rate limiting**: Are expensive endpoints (download, backup, diagnostics) rate-limited?

## Subtask 3: IPFS Pinning & Persistence

**This is critical** — artwork files must stay pinned and reachable from the public internet via IPFS:

- Install a collection from Library and verify files are **pinned** (not just cached)
- Check that pinned CIDs are reachable from a public gateway: `https://ipfs.io/ipfs/<CID>` and `https://cloudflare-ipfs.com/ipfs/<CID>`
- Verify IPFS swarm port 4001 is open and the node is discoverable
- Run `ipfs pin ls` and confirm installed artwork CIDs appear
- Test the "Preserve Vernis" archive — create archive, get CID, verify it resolves from another device
- After reboot, confirm pins survive (persistent datastore, not ephemeral)
- Check GC behavior: does garbage collection remove pinned files? It should NOT
- Verify pin count shown in UI matches actual `ipfs pin ls` count

## Subtask 4: IPFS Download Integrity

- Install a collection and verify all files download completely (no partial/corrupt files)
- Check that download progress accurately reflects actual state
- Test with a slow/interrupted connection — does it resume or retry?
- Verify downloaded files match their IPFS CID (content-addressable integrity)
- Test with directory CIDs (e.g. `QmSTci.../6.json`) if supported

## Subtask 5: Network & Exposure

- **Port scan** the device: only ports 80 (Caddy), 4001 (IPFS swarm), 5001 (IPFS API, should be localhost only), 5000 (Flask, should be localhost only) expected
- Verify Flask binds to `127.0.0.1` not `0.0.0.0`
- Verify IPFS API gateway (5001) is not exposed externally
- Test what happens when WiFi disconnects mid-download
- Check that the self-signed HTTPS setup doesn't break HTTP redirect
- Confirm no secrets (passwords, API keys) are exposed in page source, JS, or API responses

## Subtask 6: Frontend Robustness

- **Memory leaks**: Open gallery, let it run 30+ minutes, check if browser memory grows unbounded
- **Gallery exit cleanup**: Exit gallery and verify all intervals/timers are cleared (no background CPU usage)
- **Concurrent operations**: Start two installs simultaneously, trigger backup during download
- **localStorage abuse**: Fill localStorage, clear it — does the app recover gracefully?
- **Touch targets**: On a 4" screen (480x800), are all buttons at least 44px tap target?
- **Error states**: What happens when backend is down? Are errors shown clearly or does the UI just freeze?

## Subtask 7: Backup & Restore Security

- Export a backup and inspect the zip contents — no passwords, no `.env`, no private keys
- Import a crafted backup zip with: symlinks, absolute paths, files outside expected directories
- Verify backup includes: CSV collections, settings, slideshow presets, metadata cache
- Verify backup does NOT include: artwork files (too large), system files, credentials

---

## Devices for Testing

| Device | IP | Notes |
|--------|-----|-------|
| afrol | 10.0.0.28 | 4" touchscreen |
| afroz | 10.0.0.34 | Has DOOM Party pinned |
| afrom | 10.0.0.39 | Hue Entertainment API |

## Key Files

- `user-journeys.md` — Full user journey scenarios A-S with UX review
- `backend/app.py` — All API endpoints
- `settings.html` — Largest page (~220KB), most settings
- `gallery.html` — Fullscreen gallery with Hue sync, favorites, quick settings

## Expected Output

For each subtask, report:
1. What you tested
2. What you found (with steps to reproduce)
3. Severity: Critical / High / Medium / Low
4. Suggested fix (if applicable)
