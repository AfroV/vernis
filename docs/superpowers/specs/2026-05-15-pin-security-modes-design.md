# Vernis Security: PIN, Modes & Recovery — Design

**Date:** 2026-05-15
**Status:** Design approved; pending implementation plan
**Owner:** sharthan@25time.no

---

## 1. Context and problem

Vernis runs on a Raspberry Pi behind Caddy. The Flask backend at `backend/app.py` has an auth-token system intended to gate destructive endpoints from non-localhost callers. A grep through the source reveals two facts that change everything:

1. **The auth-token system is defeated by the reverse-proxy.** Caddy reverse-proxies `/api/*` to `localhost:5000` ([config/Caddyfile:17](../../config/Caddyfile)). Flask has no `ProxyFix` middleware. Every request — phone, PC, or kiosk — appears to Flask as `127.0.0.1`. The check at [backend/app.py:124](../../backend/app.py) short-circuits everything and effectively disables auth.
2. **The kiosk has no other software gate.** Anyone with network reach (WiFi, BT-PAN) to the Pi's HTTP port can currently delete NFTs, libraries, carousels, and uploaded files via `/api/nft-delete`, `/api/csv-library/delete`, `DELETE /api/carousels/<name>`, `/api/files/delete`, `/api/backup/delete`, etc., with no credential.

The owner wants a tiered access model for homes where multiple people interact with the device:

- **A — Open:** everyone can do everything (frictionless default).
- **B — Protected:** everyone can browse and control the device; **deleting** files/libraries/carousels requires a PIN.
- **C — Locked:** the kiosk home stays viewable (gallery + connect QR), but control pages and any write APIs require a PIN.

The PIN must be brute-force-resistant, persist in the browser so the owner doesn't re-enter it constantly, and have a recovery path for the inevitable "I forgot the PIN" scenario.

## 2. Goals and non-goals

**Goals**
- Three mutually-exclusive modes (A/B/C) selectable from Settings.
- 6-digit numeric PIN, bcrypt-hashed server-side.
- Per-browser session token, 30-day TTL, stored in `localStorage`.
- Two recovery paths: SSH reset script, and 5-second logo long-press → device-password modal.
- Brute-force protection: per-IP escalating cooldowns plus a global 24h lockout.
- Audit log of destructive actions.
- Fix the reverse-proxy auth leak as part of this work.
- Kiosk on the wall stays unlocked (localhost is trusted).

**Non-goals**
- 2FA / TOTP, email/SMS-based recovery, PIN rotation policies, per-page granular permissions, per-user accounts. Deferred unless future evidence demands them.

## 3. Three-mode model

| Surface | Mode A — Open | Mode B — Protected | Mode C — Locked |
|---|---|---|---|
| Read APIs (GETs, viewing, status, progress) | ✅ | ✅ | ✅ |
| Control APIs (theme, hue, screen, download, install, remote-trigger) | ✅ | ✅ | 🔒 PIN |
| Delete APIs (nft-delete, csv-library/delete, carousels DELETE, backups, files/delete, etc.) | ✅ | 🔒 PIN | 🔒 PIN |
| Home page `index.html` + gallery fullscreen + connect QR | ✅ | ✅ | ✅ |
| Settings / Library / Manage / Lab / Add pages | ✅ | ✅ | 🔒 PIN overlay |
| Logo long-press recovery gesture | ✅ | ✅ | ✅ |
| Kiosk on the wall (requests from `127.0.0.1`) | ✅ always trusted | ✅ always trusted | ✅ always trusted |

**Boot default: Mode A.** First-run users see no friction.

**Trust the kiosk:** localhost requests are always allowed regardless of mode. The Pi running its own browser on its own screen is the most-trusted client in the system. Remote-triggered navigations (PC → Lab → kiosk shows Gazer) work because the kiosk's resulting GET arrives at Flask as `127.0.0.1`.

## 4. Reverse-proxy fix (prerequisite)

Two changes that activate dormant security and make rate-limiting per-IP correct.

### 4.1 Caddy

In `config/Caddyfile` (and the heredoc in `scripts/install-vernis.sh`):

```caddyfile
servers {
  trusted_proxies static private_ranges
}

# inside each site block:
reverse_proxy /api/* localhost:5000 {
  header_up X-Forwarded-For {client_ip}
  header_up X-Real-IP {client_ip}
}
```

Caddy overrides any client-supplied `X-Forwarded-For` when `trusted_proxies` is set, blocking spoofing from outside.

### 4.2 Flask

In `backend/app.py`, near the top:

```python
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
```

`x_for=1` tells Werkzeug to trust exactly one proxy hop (Caddy). Higher values would let a malicious client spoof their IP.

### 4.3 Effects

- `request.remote_addr` returns real client IPs.
- The existing localhost short-circuit at line 124 now actually identifies the kiosk.
- The per-IP failure counter (existing `_auth_failures`) now buckets attackers separately.
- `/api/auth-token` actually 403s non-localhost callers — phones can no longer fetch the token. The HTML pages' fallback `.catch(function(){})` leaves `_vernisToken` empty silently. No real workflow breaks because phone-side destructive calls now use PIN sessions instead.

## 5. Architecture

### 5.1 Storage layout

```
/opt/vernis/
├── security.json              # config + hashes (chmod 0600)
├── security-sessions.json     # active session tokens (chmod 0600)
├── security-failures.json     # rate-limit snapshot (chmod 0600)
├── audit.log                  # JSON Lines, rotated at 10 MB (chmod 0640)
└── (existing files unchanged)
```

`security.json` schema:

```json
{
  "version": 1,
  "mode": "A",
  "pin_hash": null,
  "owner_pwd_hash": "<bcrypt hash of Linux user password>",
  "recovery_logo_enabled": true,
  "created_at": "2026-05-15T00:00:00Z"
}
```

`security-sessions.json` schema:

```json
{
  "Xc7K...": { "created_at": 1763000000, "expires_at": 1765592000, "ip": "10.0.0.42", "ua": "iOS/Safari" }
}
```

`security-failures.json` schema:

```json
{
  "by_ip": { "10.0.0.99": [1762000000, 1762000060, ...] },
  "global": [1762000000, ...],
  "hard_locked_at": null
}
```

Sensitive values (PINs, passwords, session tokens) are **never** logged.

### 5.2 Backend additions (`backend/app.py`)

New imports: `bcrypt`, `werkzeug.middleware.proxy_fix.ProxyFix`.

New constants block near existing security constants:

```python
PIN_LENGTH = 6
PIN_BCRYPT_COST = 12
SESSION_TTL_DAYS = 30
RECOVERY_TTL_MINUTES = 10
PER_IP_COOLDOWN_SCHEDULE = [(3, 0), (5, 30), (8, 60), (12, 300), (None, 900)]
GLOBAL_LOCKOUT_THRESHOLD = 30
GLOBAL_LOCKOUT_WINDOW_HOURS = 24
AUDIT_LOG_MAX_BYTES = 10 * 1024 * 1024
AUDIT_LOG_ROTATE_COUNT = 1
LONG_PRESS_DURATION_MS = 5000
```

New helpers:

```python
def load_security_config() -> dict: ...
def save_security_config(cfg: dict) -> None: ...        # atomic write via tmp + os.replace
def hash_pin(pin: str) -> str: ...                      # bcrypt cost 12
def verify_pin(pin: str, hash_: str) -> bool: ...
def hash_owner_password(pwd: str) -> str: ...
def verify_owner_password(pwd: str) -> bool: ...
def issue_session(ip: str, ua: str) -> dict: ...        # returns {token, expires_at}
def validate_session(token: str) -> tuple[bool, str]: ...
def revoke_all_sessions() -> None: ...
def revoke_session(token: str) -> None: ...
def list_sessions() -> list[dict]: ...                  # no tokens, just metadata
def classify_endpoint(path: str, method: str) -> str: ...   # 'read' | 'control' | 'delete' | 'security' | 'bootstrap'
def record_failure(ip: str) -> dict: ...                # returns {locked_until, hard_locked}
def clear_failures(ip: str) -> None: ...
def cooldown_remaining(ip: str) -> int: ...
def append_audit(action: str, what: object = None, ip: str = None, result: str = 'ok', **extra) -> None: ...
def rotate_audit_if_needed() -> None: ...
```

New `before_request` handler `_enforce_security` replaces `_enforce_auth`:

```
if request.remote_addr in ('127.0.0.1', '::1'): allow         # kiosk
cls = classify_endpoint(request.path, request.method)
if cls == 'read': allow
if cls == 'bootstrap' and not security.json exists: allow
if cls == 'security': route handles its own auth
cfg = load_security_config()
if cfg.mode == 'A': allow
if cls == 'control' and cfg.mode == 'B': allow
require valid PIN session token (header or query param)
```

### 5.3 New endpoints (`/api/security/*`)

| Method | Path | Auth | Body | Returns |
|---|---|---|---|---|
| GET | `/api/security/config` | open | — | `{mode, has_pin, recovery_logo_enabled, locked_until, hard_locked, kiosk}` |
| POST | `/api/security/mode` | PIN session required if PIN exists; open if no PIN exists | `{mode}` | `{mode}` |
| POST | `/api/security/pin` | PIN session (and `current_pin` in body) | `{current_pin, new_pin}` | `{ok: true}` |
| DELETE | `/api/security/pin` | PIN session (and `current_pin` in body) | `{current_pin}` | `{ok: true, mode: "A"}` |
| POST | `/api/security/login` | open, rate-limited | `{pin}` | `{token, expires_at}` or 401/429/423 |
| POST | `/api/security/logout` | session | — | `{ok: true}` |
| POST | `/api/security/recover` | open, rate-limited (used for **initial PIN setup** AND **recovery**) | `{owner_password, new_pin?}` | `{ok: true, token?, expires_at?}` |
| GET | `/api/security/sessions` | PIN session or localhost | — | list of `{token_id, ip, ua, created_at, expires_at}` (no raw token) |
| DELETE | `/api/security/sessions/<token_id>` | PIN session or localhost | — | `{ok: true}` |
| GET | `/api/security/audit` | PIN session in B/C; localhost-only in A | `?limit=` | recent JSONL entries |

`POST /api/security/login` includes `Retry-After` in 429 responses. `423 Locked` is returned when global lockout is active.

**Important — initial PIN setup uses `/api/security/recover`:**

`POST /api/security/pin` requires the current PIN, which doesn't exist for a brand-new device. Setting the first PIN therefore uses the same endpoint as forgotten-PIN recovery — both flows authenticate via the **owner password**, both can set a new PIN, and both rate-limit through the same per-IP counter. This is intentional:

- It prevents a hostile-takeover scenario where a guest on Mode A's open WiFi calls `POST /api/security/pin` to set their own PIN and lock the owner out.
- The owner password is the single "I own this device" credential — used for initial PIN setup, lockout-recovery, and forgotten-PIN recovery.
- When `/api/security/recover` succeeds and a `new_pin` is provided, the backend issues a session token in the response so the owner doesn't have to log in again immediately after setup.

The "Set PIN" button in Settings opens a modal asking for the device password + new PIN; the "Change PIN" button (shown when a PIN already exists) asks for current PIN + new PIN and uses `POST /api/security/pin`.

### 5.4 Frontend components

**Shared scripts (loaded from HTML pages):**

| File | Loaded by | Purpose |
|---|---|---|
| `vernis-lock-guard.js` | settings, library, manage, lab, add | On DOMContentLoaded: GET `/api/security/config`; if `mode==='C' && !kiosk && !valid session` → hide `#page-content` (or `body > main`), render PIN overlay using `.vernis-confirm-overlay` styles. Reveal page on success. |
| `vernis-pin-prompt.js` | library, manage | Helper `withPin(fn)` — wraps an API call. On 401 `pin_required`, opens PIN modal, retries on success. Used to wrap the existing delete handlers. |
| `vernis-logo-longpress.js` | index, lock-overlay | Binds `pointerdown`/`pointerup`/`pointercancel` on `.kiosk-logo`. Tracks elapsed time. Draws conic-gradient ring via SVG/`<canvas>` over the logo. At 5000 ms opens recovery modal. Cancels and fades on release. |

**Settings UI (`settings.html` → new `<section id="section-security">`):**

```
[ Security ]
  Access Level
    ( ) Open       Anyone with the link can use the device fully.
    (●) Protected  Everyone can browse and control; delete requires PIN.
    ( ) Locked     PIN required to open Settings/Library/Manage/Lab/Add.

  PIN
    [ Set PIN ]    (or Change PIN / Remove PIN depending on state)

  Recovery
    [✓] Allow physical reset (hold logo 5s + device password)

  Active sessions
    iOS/Safari · 10.0.0.42 · 3 days ago · [Revoke]
    Chrome/Mac · 10.0.0.51 · 28 days ago · [Revoke]

  [ View audit log ]
```

**Logo long-press visual (new keyframes in `vernis-themes.css`):**

- Conic-gradient ring uses `var(--accent-primary)` to match the existing `.kiosk-logo` gradient.
- Logo pulses `transform: scale(1.0 → 1.02 → 1.0)` over each 1s during press.
- Ring fills 0 → 360deg over 5s.
- On 5s completion: brief flash, then `.vernis-confirm-overlay` opens with the device-password prompt.
- On release before 5s: ring fades to 0 in 200 ms, no modal.

### 5.5 Endpoint classification

Concrete categorization of all routes in `backend/app.py`.

**DELETE class (PIN required in Modes B and C):**

```
POST   /api/nft-delete
POST   /api/csv-library/delete
POST   /api/csv-library/clear-files
DELETE /api/carousels/<name>
POST   /api/backup/delete
POST   /api/files/delete
DELETE /api/setup/complete
POST   /api/thumbnails/clear
POST   /api/clear-cache
POST   /api/ipfs/gc
DELETE /api/burner/cache
POST   /api/hue/disconnect
POST   /api/storage/external/migrate
DELETE /api/https
DELETE /api/security/pin
POST   /api/setup/change-password    # see §5.6 for additional behavior
```

### 5.6 `/api/setup/change-password` keeps `owner_pwd_hash` in sync

The existing endpoint at [backend/app.py:6195](../../backend/app.py) changes the Linux user password via `chpasswd`. To prevent `owner_pwd_hash` from going stale (which would break logo long-press recovery after a password change), the endpoint gains one additional step:

```
1. Verify current password via libcrypt + /etc/shadow (existing).
2. chpasswd to set new Linux password (existing).
3. NEW: hash the new password with bcrypt cost 12 and write to
   security.json -> owner_pwd_hash, atomically.
4. NEW: append_audit("owner_password_changed", result="ok").
5. Touch marker file (existing).
```

This means **the user never has to think about `owner_pwd_hash`** when changing the device password through the UI. The manual `scripts/update-owner-password.sh` exists only as a fallback for users who change their password via `passwd` directly over SSH (bypassing the Vernis endpoint). A note in `CLAUDE.md` and the in-app Help section flags this:

> If you change your device password from the Settings page, the recovery hash updates automatically. If you change it via `passwd` over SSH, run `sudo /opt/vernis/scripts/update-owner-password.sh` so logo-long-press recovery keeps working.

If `security.json` happens not to exist when `chpasswd` succeeds (first-run edge case before security is initialized), the step is a no-op — the install path is responsible for initializing the file later, and it reads from `chpasswd`'s effect anyway.

**CONTROL class (PIN required in Mode C only):**

All other `POST` / `PUT` / `DELETE` routes not in DELETE or READ classes, including:

- All theme/display/screen/screen-saver writes
- All hue writes except disconnect
- All download/library install/upload writes
- All carousels POST, atelier save, nft-visibility, nft-metadata writes
- All backup create/import
- All system/fan/wifi/reboot/shutdown/update/os-lock writes
- All bluetooth writes
- All remote-command and gallery state writes
- All archive create/pin writes
- All setup/* writes (other than `change-password` and `complete` DELETE)

**READ class (always allowed):**

- All `GET` requests
- Streaming/serving endpoints: `/nfts/<path>`, `/nfts-ext/<path>`, `/api/thumbnail/<x>`, `/api/burner/render/<x>`, `/api/burner/assets/<x>`
- `/api/qrcode`, `/api/health`, `/api/version`, `/api/status`, all `*/status` and `*/progress` endpoints
- The existing `_AUTH_EXEMPT_PATHS` set folds into READ

**BOOTSTRAP exemption:** all `/api/setup/*` writes are allowed when `security.json` does not exist on disk (first-run wizard). The moment the file is created, classification reverts to DELETE/CONTROL.

**SECURITY class:** the `/api/security/*` routes handle their own auth and bypass the central classifier.

The classifier is implemented as three sets of paths plus pattern matching for path-parametered routes. A unit test enumerates every route in `app.py` and asserts each falls into exactly one class.

## 6. Data flows

### 6.1 First login in Mode C

1. Phone loads `/settings.html` (Caddy serves static file, no gate).
2. `vernis-lock-guard.js` calls `GET /api/security/config`.
3. Response: `{mode:"C", has_pin:true, kiosk:false, locked_until:null}`.
4. Guard hides page content and renders PIN overlay.
5. User taps 6 digits. Frontend `POST /api/security/login {pin}`.
6. Backend verifies bcrypt, issues session, audits `login ok`, returns `{token, expires_at}`.
7. Guard stores `vernis-pin-session` in `localStorage` and reveals page.
8. Subsequent state-changing requests include `X-Vernis-PIN-Session: <token>`.

### 6.2 Delete in Mode B

1. Phone on `manage.html` confirms delete via existing `vernisConfirm()`.
2. Phone `POST /api/nft-delete` without PIN header (Mode B doesn't lock the page).
3. Backend classify=delete, mode=B → 401 `{error:"pin_required"}`.
4. Frontend wrapper opens PIN modal, user types PIN.
5. `POST /api/security/login` succeeds, token stored.
6. Wrapper retries `POST /api/nft-delete` with header → 200.
7. Audit entry `delete_nft what=[...]`.

For 30 days the session token remains valid; no prompt on next delete.

### 6.3 Lab remote-trigger in Mode C (verifies trust-the-kiosk)

1. PC on `lab.html` has valid PIN session.
2. PC `POST /api/remote/command {cmd:"show-gazer",id:42}` with header.
3. Backend classify=control, mode=C → require session → ok. Audit `remote_command`.
4. Backend issues CDP navigate command to kiosk Chromium.
5. Kiosk Chromium `GET /lab.html?gazer=42&hue=1` — `remote_addr = 127.0.0.1`.
6. `_enforce_security` short-circuits localhost. Page renders.
7. `vernis-lock-guard` on the kiosk: `GET /api/security/config` returns `kiosk:true`; guard reveals page without overlay.

### 6.4 Forgotten-PIN recovery via logo long-press

1. User on kiosk (or any device showing the lock overlay) presses-and-holds `.kiosk-logo`.
2. After 1s: conic-gradient ring starts drawing. Logo pulses gently.
3. At 5s: ring fills, brief flash, `.vernis-confirm-overlay` opens: "Reset PIN — enter device password".
4. User types Pi password.
5. Modal transitions to "Set new PIN" or "Skip — leave open". User picks one.
6. `POST /api/security/recover {owner_password, new_pin?}` — `new_pin` optional.
7. Backend verifies owner password via bcrypt against `owner_pwd_hash`. Recovery attempts count toward the same per-IP cooldown as login attempts.
8. On success:
   - If `new_pin` supplied: replace `pin_hash` with hash of `new_pin`, **keep current mode**, issue a session token in the response (returned to caller).
   - If `new_pin` omitted: clear `pin_hash`, set `mode="A"`.
   - In both cases: `revoke_all_sessions()` (any other browsers must re-authenticate), audit `recovery_logo ok`.
9. Modal closes; if a session token was returned, the caller stores it in `localStorage`.

Releasing before 5s: ring fades, no modal.

### 6.5 Initial PIN setup (in Mode A, no PIN yet)

1. Owner opens Settings → Security. UI sees `has_pin: false`, shows "Set PIN" button.
2. Tap → modal asks for **device password** + **6-digit PIN** + **confirm PIN**.
3. `POST /api/security/recover {owner_password, new_pin}`.
4. Backend rate-limits per IP (same counter as login), verifies owner password, hashes and stores new PIN, issues session token, audits `pin_set`.
5. Response includes session token; phone stores it in `localStorage`. Owner can now switch modes without re-authenticating.

The same endpoint thus serves three semantically-distinct flows: initial setup, recovery from lock-out (with new PIN), recovery to Open (no new PIN). One credential (owner password) authorizes all three.

### 6.6 SSH recovery

```
$ sudo /opt/vernis/scripts/reset-pin.sh
This will wipe the PIN and unlock the device. Continue? [y/N] y
PIN cleared. Mode set to Open.
```

Script writes a clean `security.json` (preserving `owner_pwd_hash`), empties sessions and failures, sends `SIGHUP` to `vernis-api`, audits `recovery_ssh ok`.

### 6.7 Mode switch from Settings

- Switching to B or C with no PIN set: backend returns 400 `set_pin_first` and Settings UI redirects to "Set PIN" flow.
- Switching to A: `pin_hash` preserved, all sessions revoked, audit `mode_change A`.
- Switching between B and C: sessions revoked (forces re-login), audit `mode_change X`.

## 7. Brute-force protection

### 7.1 Per-IP escalation (rolling 24h)

| Failure # | Cooldown before next attempt | HTTP response |
|---|---|---|
| 1–3 | none | 401 `pin_required` |
| 4–5 | 30 s | 429 `Retry-After: 30` |
| 6–8 | 60 s | 429 `Retry-After: 60` |
| 9–12 | 300 s | 429 `Retry-After: 300` |
| 13+ | 900 s (cap) | 429 `Retry-After: 900` |

Successful login from this IP zeros the counter for this IP only. 24h since last failure also clears it. Recovery attempts (owner password) count toward the same counter from this IP.

### 7.2 Global hard lockout

Across all IPs in any rolling 24h window:

- **≥ 30 total PIN failures → device hard-locks.**
- `GET /api/security/config` returns `hard_locked:true`.
- `POST /api/security/login` returns `423 Locked`.
- Recovery (logo long-press → owner password, or SSH script) STILL works. Prevents lockout-as-attack.

### 7.3 Frontend behavior

When config response includes future `locked_until`, the overlay shows a live countdown and disables the keypad until it elapses. Submitting during cooldown is avoided client-side.

### 7.4 Persistence

- Sessions: persisted on issue, cleaned on each access (lazy expiry).
- Failures: in-memory dict + debounced snapshot to disk every ~10 s and on graceful shutdown.
- Cooldowns use `time.monotonic()`. Audit log uses wall clock.

## 8. Audit log

Path: `/opt/vernis/audit.log`. Format: JSON Lines.

```jsonl
{"ts":"2026-05-15T11:32:14Z","ip":"10.0.0.42","action":"login","result":"ok","ua":"safari/ios"}
{"ts":"2026-05-15T11:33:01Z","ip":"10.0.0.42","action":"delete_carousel","what":"Vacation","result":"ok"}
{"ts":"2026-05-15T11:55:00Z","ip":"10.0.0.99","action":"login","result":"fail","attempts":3}
{"ts":"2026-05-15T12:01:22Z","ip":"127.0.0.1","action":"mode_change","from":"A","to":"B","result":"ok"}
{"ts":"2026-05-15T12:30:00Z","ip":"10.0.0.42","action":"recovery_logo","result":"ok"}
```

Logged actions: `pin_set`, `pin_changed`, `pin_removed`, `mode_change`, `login` (ok/fail), `logout`, `lockout_per_ip`, `lockout_global`, `recovery_logo`, `recovery_ssh`, `delete_nft`, `delete_library`, `delete_carousel`, `delete_backup`, `delete_files`, `clear_cache`, `clear_thumbnails`, `ipfs_gc`, `https_disable`, `hue_disconnect`, `setup_complete_delete`.

Never logged: the PIN itself, the owner password, raw session tokens, the *value* of failed PIN attempts.

Rotation: at `AUDIT_LOG_MAX_BYTES`, current file rotates to `audit.log.1`; older logs discarded (`AUDIT_LOG_ROTATE_COUNT=1`).

## 9. Edge cases (consolidated)

| Case | Handling |
|---|---|
| Clock skew (NTP jump) | Cooldowns use `time.monotonic()`. Audit log uses wall clock (acceptable). |
| PIN change from active session | The performing session stays valid; all others revoked. |
| Two browsers logging in simultaneously | Each gets its own session token, independent. |
| Owner-password recovery before any PIN was set | This IS the initial-PIN-setup flow; see §6.5. New PIN supplied → set + issue session. New PIN omitted → no-op. |
| Hostile guest tries to set their own PIN in Mode A | Blocked. `POST /api/security/pin` requires a valid PIN session, which requires an existing PIN. Initial setup goes through `/api/security/recover` which requires the owner password. |
| User changes device password from Settings | `/api/setup/change-password` re-hashes the new password into `security.json -> owner_pwd_hash` atomically (§5.6). Logo-long-press recovery keeps working with the new password. |
| User changes device password directly via `passwd` over SSH | `owner_pwd_hash` goes stale; logo-long-press recovery still accepts the *old* password. User must run `sudo /opt/vernis/scripts/update-owner-password.sh` to re-sync. Documented in `CLAUDE.md` and the Help section. |
| Mode A with PIN hash present | Allowed; switching back to B/C reuses the stored hash. |
| Invalid PIN format | Frontend regex `\d{6}`; backend `len(pin)==6 and pin.isdigit()`. 422 on shape error. |
| Session valid in `localStorage` but server-side revoked | First API call returns 401; frontend clears `localStorage`, prompts re-login. |
| Factory reset | `security.json` wiped; boots to Mode A. |
| Bluetooth WiFi-provisioning flow on a fresh device | Bypasses PIN via bootstrap exemption while `security.json` absent. |
| Existing `/api/auth-token` plumbing in HTML pages | Continues to exist; on phones the fetch silently 403s after proxy fix and `_vernisToken` remains empty. PIN sessions take over. Old plumbing can be removed in a later cleanup pass. |
| Client spoofs `X-Forwarded-For` | Blocked by `trusted_proxies` in Caddy; Werkzeug's `ProxyFix x_for=1` only trusts the immediate hop. |
| File corruption of `security.json` | Loader catches JSON errors, falls back to defaults (Mode A, empty PIN hash, preserve `owner_pwd_hash` if recoverable from `.bak`). Logs the corruption. |

## 10. File-by-file change list

**Backend**
- `backend/app.py` — ProxyFix wrap; security helpers; new endpoints; replace `_enforce_auth` with `_enforce_security`; audit writer; bcrypt usage. Also: modify existing `/api/setup/change-password` to re-hash the new password into `owner_pwd_hash` after `chpasswd` succeeds (§5.6).
- Python deps — add `bcrypt>=4.0`.

**Config**
- `config/Caddyfile` — `trusted_proxies` block; `header_up X-Forwarded-For` on `/api/*` reverse_proxy.
- `scripts/install-vernis.sh` — mirror Caddyfile heredoc; install `bcrypt`; initialize `security.json` with `owner_pwd_hash` from the install-time password; create `audit.log`, `security-sessions.json`, `security-failures.json` with correct perms.

**Scripts**
- `scripts/reset-pin.sh` — NEW. SSH recovery.
- `scripts/update-owner-password.sh` — NEW. Re-sync `owner_pwd_hash` after `passwd` change.

**Shared frontend**
- `vernis-lock-guard.js` — NEW.
- `vernis-pin-prompt.js` — NEW.
- `vernis-logo-longpress.js` — NEW.
- `vernis-themes.css` — add long-press ring keyframes and PIN-overlay numeric-keypad styles. Reuses existing `.vernis-confirm-overlay`.

**HTML**
- `index.html` — wire long-press handler to `.kiosk-logo`; no lock guard.
- `settings.html` — new `<section id="section-security">`; include lock guard.
- `library.html`, `manage.html` — include lock guard + pin-prompt; wrap delete actions.
- `lab.html`, `add.html` — include lock guard.
- `gallery.html` — no change.

**Docs**
- `README.md` — "Security" section.
- `CLAUDE.md` — recovery script paths; owner-password sync command.
- `settings.html` Help section — short explainer.

## 11. Migration

Existing field devices (afrol, afroz, afrom, afromini):

1. Deploy Caddyfile change; reload Caddy.
2. `pip install bcrypt` into the Flask venv.
3. Deploy updated `app.py`; restart `vernis-api`.
4. Run one-time initialization: write `security.json` with `mode:"A"`, `owner_pwd_hash` from the device password documented in `CLAUDE.md`, `pin_hash:null`.
5. Touch `audit.log`, `security-sessions.json`, `security-failures.json`.

Net effect: zero behavior change for the user until they opt into Mode B or C. Proxy fix silently activates correct security boundaries.

## 12. Rollout order

1. Proxy fix + `ProxyFix` wrap alone. Deploy to afroz first; verify kiosk and phone behavior unchanged in logs.
2. Security skeleton: storage, helpers, `GET /api/security/config` only. No enforcement.
3. Enforcement: switch `_enforce_security` on. Mode A default keeps everything passing.
4. Frontend: lock guard, PIN prompt, settings section.
5. Recovery: logo long-press handler, SSH reset script.
6. Brute-force escalation and global lockout.
7. Documentation.

Each step is independently deployable and reversible.

## 13. Testing

**Unit (`tests/test_security.py`)**
- `hash_pin` / `verify_pin` roundtrip; rejects empty/wrong-length/non-numeric.
- `classify_endpoint` covers every route in `app.py` (enumerated test).
- `issue_session` / `validate_session` honor TTL; revocation removes from store.
- `record_failure` produces the exact §7.1 schedule.
- Global lockout triggers at threshold; cleared by recovery; cleared by SSH reset.
- `security.json` corruption falls back to safe defaults.
- Audit log rotates at threshold; never contains `pin`, `password`, `token` substrings (regex check).

**Integration (Flask test client)**
- Mode A: every endpoint passes without session.
- Mode B: delete-class returns 401 without session; 200 with.
- Mode C: control + delete require session; reads always pass.
- Localhost short-circuits in all modes.
- Spoofed `X-Forwarded-For` from outside is ignored.
- Per-IP rate limit triggers at correct counts; doesn't affect other IPs.
- Global lockout triggers at 30 mixed-IP failures; recovery unlocks.

**Manual on-device**
- afrol kiosk in Mode C still shows gallery + QR.
- Phone unlocks Settings via PIN overlay.
- PC triggers Gazer in Mode C → kiosk renders Lab without prompt.
- Logo press 4.9s → no modal; 5.0s → modal.
- Owner-password recovery resets PIN, clears lockout.
- Bluetooth WiFi-provisioning still completes on fresh device.
- HTTPS opt-in still works after Caddyfile change.

**Security-specific**
- `audit.log` grep for `pin|password|token` returns nothing.
- `security.json` chmod is `0600`.
- bcrypt cost-12 login latency on Pi 4/5 is 150–300 ms (acceptable). Lower cost only if unacceptable.

## 14. Out of scope

- 2FA / TOTP.
- PIN expiration / forced rotation.
- Per-page granular permissions.
- Per-session naming / labeling beyond auto IP+UA.
- Email/SMS recovery.
- Removing the legacy `_vernisToken` plumbing in HTML pages (later cleanup).
