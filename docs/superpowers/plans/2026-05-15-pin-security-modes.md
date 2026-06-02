# Vernis Security: PIN, Modes & Recovery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a three-mode (Open/Protected/Locked) PIN access-control system to Vernis, fix the reverse-proxy auth leak as a prerequisite, and provide robust recovery paths.

**Architecture:** A new `_enforce_security` Flask before-request hook classifies each path into read/control/delete/security/bootstrap and applies mode-dependent gates. Sessions are bcrypt-PIN-derived 30-day tokens stored server-side and surfaced to browsers as `X-Vernis-PIN-Session`. Recovery uses a separately-stored owner-password hash, accessed via SSH or a 5-second logo long-press gesture.

**Tech Stack:** Python 3 + Flask + Werkzeug ProxyFix, bcrypt (new), pytest (new), Caddy (config change), vanilla JS frontend using DOM methods (no innerHTML to avoid XSS risk), CSS conic-gradient animations.

**Reference spec:** [docs/superpowers/specs/2026-05-15-pin-security-modes-design.md](../specs/2026-05-15-pin-security-modes-design.md)

**Note on commits:** The user prefers to handle git operations personally. An executing agent should treat each "Commit" step as a checkpoint to surface the diff to the user and ask before running `git add` / `git commit`.

---

## Phase 1 — Reverse-proxy fix (prerequisite)

This phase activates dormant security and makes per-IP rate-limiting correct. It must land first because subsequent phases depend on `request.remote_addr` returning real client IPs.

### Task 1: Update Caddyfile to pass real client IPs

**Files:**
- Modify: `config/Caddyfile` (entire file)

- [ ] **Step 1: Replace `config/Caddyfile` with new content**

Replace the file contents with:

```caddyfile
# Vernis v3 - Caddy Web Server Configuration
# Serves web UI and proxies API requests to Flask

{
    # Global options
    auto_https off
    admin off

    # Trust only Caddy itself (local) so that X-Forwarded-For from outside
    # callers cannot spoof their source IP through the reverse proxy.
    servers {
        trusted_proxies static private_ranges
    }
}

# Main Vernis site
http://vernis.local {
    root * /var/www/vernis
    file_server

    reverse_proxy /api/* localhost:5000 {
        header_up X-Forwarded-For {client_ip}
        header_up X-Real-IP {client_ip}
    }

    reverse_proxy /nfts/* localhost:5000 {
        header_up X-Forwarded-For {client_ip}
        header_up X-Real-IP {client_ip}
    }

    encode gzip
    header /assets/* Cache-Control "public, max-age=31536000"
    header {
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy no-referrer-when-downgrade
    }

    log {
        output file /var/log/caddy/vernis.log
        format json
    }
}

# Also respond to direct IP access
http://:80 {
    root * /var/www/vernis
    file_server
    reverse_proxy /api/* localhost:5000 {
        header_up X-Forwarded-For {client_ip}
        header_up X-Real-IP {client_ip}
    }
    reverse_proxy /nfts/* localhost:5000 {
        header_up X-Forwarded-For {client_ip}
        header_up X-Real-IP {client_ip}
    }
    encode gzip
}
```

- [ ] **Step 2: Validate Caddyfile syntax locally (optional if Caddy not installed on dev machine)**

Run: `caddy validate --config config/Caddyfile`
Expected: `Valid configuration`. If Caddy is not installed locally, skip — the Pi will catch syntax errors at restart.

- [ ] **Step 3: Commit**

```bash
git add config/Caddyfile
git commit -m "config: pass real client IP through Caddy reverse_proxy

Adds trusted_proxies and X-Forwarded-For so Flask can see actual
client IPs. Prerequisite for PIN security."
```

### Task 2: Mirror Caddyfile changes in install-vernis.sh

**Files:**
- Modify: `scripts/install-vernis.sh:147-163` (Caddyfile heredoc)

- [ ] **Step 1: Locate the heredoc**

Run: `grep -n "sudo tee /etc/caddy/Caddyfile" scripts/install-vernis.sh`
Expected: one match around line 147.

- [ ] **Step 2: Replace the heredoc with new content matching the updated Caddyfile**

Find the existing block:

```bash
sudo tee /etc/caddy/Caddyfile > /dev/null << 'EOF'
...current content...
EOF
```

Replace with:

```bash
sudo tee /etc/caddy/Caddyfile > /dev/null << 'EOF'
{
    auto_https off
    admin off
    servers {
        trusted_proxies static private_ranges
    }
}

http://vernis.local {
    root * /var/www/vernis
    file_server
    reverse_proxy /api/* localhost:5000 {
        header_up X-Forwarded-For {client_ip}
        header_up X-Real-IP {client_ip}
    }
    reverse_proxy /nfts/* localhost:5000 {
        header_up X-Forwarded-For {client_ip}
        header_up X-Real-IP {client_ip}
    }
    reverse_proxy /nfts-ext/* localhost:5000 {
        header_up X-Forwarded-For {client_ip}
        header_up X-Real-IP {client_ip}
    }
    encode gzip
    header /assets/* Cache-Control "public, max-age=31536000"
    header {
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy no-referrer-when-downgrade
    }
    log {
        output file /var/log/caddy/vernis.log
        format json
    }
}

http://:80 {
    root * /var/www/vernis
    file_server
    reverse_proxy /api/* localhost:5000 {
        header_up X-Forwarded-For {client_ip}
        header_up X-Real-IP {client_ip}
    }
    reverse_proxy /nfts/* localhost:5000 {
        header_up X-Forwarded-For {client_ip}
        header_up X-Real-IP {client_ip}
    }
    reverse_proxy /nfts-ext/* localhost:5000 {
        header_up X-Forwarded-For {client_ip}
        header_up X-Real-IP {client_ip}
    }
    encode gzip
}
EOF
```

- [ ] **Step 3: Verify shell syntax**

Run: `bash -n scripts/install-vernis.sh`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add scripts/install-vernis.sh
git commit -m "install: mirror Caddyfile changes for fresh installs"
```

### Task 3: Wrap Flask app with ProxyFix

**Files:**
- Modify: `backend/app.py` (after `app = Flask(...)` line)
- Create: `tests/conftest.py`
- Create: `tests/__init__.py`
- Create: `tests/test_proxy_fix.py`

- [ ] **Step 1: Set up pytest scaffolding**

Create `tests/__init__.py` as an empty file.

Create `tests/conftest.py`:

```python
"""Pytest configuration for Vernis backend tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
```

- [ ] **Step 2: Write failing test**

Create `tests/test_proxy_fix.py`:

```python
"""ProxyFix: Flask must read real client IP from X-Forwarded-For."""
import importlib


def test_proxy_fix_reads_forwarded_for():
    import app
    importlib.reload(app)
    client = app.app.test_client()
    captured = {}

    @app.app.route("/__test_remote_pf")
    def _capture():
        from flask import request
        captured["remote"] = request.remote_addr
        return "ok"

    client.get(
        "/__test_remote_pf",
        headers={"X-Forwarded-For": "10.0.0.99"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert captured["remote"] == "10.0.0.99"


def test_proxy_fix_only_trusts_one_hop():
    import app
    importlib.reload(app)
    client = app.app.test_client()
    captured = {}

    @app.app.route("/__test_remote_pf2")
    def _capture():
        from flask import request
        captured["remote"] = request.remote_addr
        return "ok"

    # Client claims to be 1.2.3.4 — should be ignored; only right-most
    # value (10.0.0.99 from Caddy) is honored.
    client.get(
        "/__test_remote_pf2",
        headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.99"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert captured["remote"] == "10.0.0.99"
```

- [ ] **Step 3: Install pytest (one-time) and run to verify failure**

Run: `pip3 install pytest --break-system-packages` then `python3 -m pytest tests/test_proxy_fix.py -v`
Expected: FAIL — `captured["remote"]` equals `"127.0.0.1"` (ProxyFix not yet wired).

- [ ] **Step 4: Wire ProxyFix**

In `backend/app.py`, find the line `app = Flask(__name__, ...)` (near the top). Immediately after it, add:

```python
from werkzeug.middleware.proxy_fix import ProxyFix

# Trust exactly one proxy hop (Caddy at localhost). Higher values would
# allow a client to spoof its IP via X-Forwarded-For.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
```

- [ ] **Step 5: Run test to verify pass**

Run: `python3 -m pytest tests/test_proxy_fix.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app.py tests/test_proxy_fix.py tests/conftest.py tests/__init__.py
git commit -m "backend: wrap Flask with ProxyFix(x_for=1)

Flask now reads real client IPs from X-Forwarded-For (set by Caddy).
Spoofing blocked because x_for=1 trusts only one proxy hop."
```

---

## Phase 2 — Security skeleton

Storage layout, helpers, no enforcement changes yet — Mode A behavior unchanged.

### Task 4: Add bcrypt dependency to install script

**Files:**
- Modify: `scripts/install-vernis.sh` (pip install line around line 31)

- [ ] **Step 1: Update pip install line**

Find `sudo pip3 install qrcode pillow requests pycryptodome websocket-client --break-system-packages` in `scripts/install-vernis.sh` and replace with:

```bash
sudo pip3 install qrcode pillow requests pycryptodome websocket-client bcrypt --break-system-packages
```

- [ ] **Step 2: Install bcrypt locally for testing**

Run: `pip3 install bcrypt --break-system-packages`
Expected: `Successfully installed bcrypt-...`

- [ ] **Step 3: Commit**

```bash
git add scripts/install-vernis.sh
git commit -m "install: add bcrypt dependency"
```

### Task 5: Add security constants to app.py

**Files:**
- Modify: `backend/app.py` (after existing `_AUTH_BLOCK_DURATION` constant)

- [ ] **Step 1: Add constants block**

In `backend/app.py`, after `_AUTH_BLOCK_DURATION = 900`, insert:

```python
# ========================================
# Security: PIN, Modes, Recovery
# ========================================
SECURITY_CONFIG_FILE = Path("/opt/vernis/security.json")
SESSIONS_FILE = Path("/opt/vernis/security-sessions.json")
FAILURES_FILE = Path("/opt/vernis/security-failures.json")
AUDIT_LOG_PATH = Path("/opt/vernis/audit.log")

PIN_LENGTH = 6
PIN_BCRYPT_COST = 12
SESSION_TTL_DAYS = 30
RECOVERY_TTL_MINUTES = 10
# (max_failures_for_this_tier, cooldown_seconds)
PER_IP_COOLDOWN_SCHEDULE = [(3, 0), (5, 30), (8, 60), (12, 300), (None, 900)]
GLOBAL_LOCKOUT_THRESHOLD = 30
GLOBAL_LOCKOUT_WINDOW_HOURS = 24
AUDIT_LOG_MAX_BYTES = 10 * 1024 * 1024
AUDIT_LOG_ROTATE_COUNT = 1
LONG_PRESS_DURATION_MS = 5000
```

- [ ] **Step 2: Verify imports**

Run: `python3 -c "import sys; sys.path.insert(0, 'backend'); import app; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "backend: add security constants"
```

### Task 6: Implement load_security_config and save_security_config

**Files:**
- Modify: `backend/app.py`
- Create: `tests/test_security_config.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_security_config.py`:

```python
"""Tests for security.json load/save."""
import importlib, os, pytest


@pytest.fixture
def fresh_app(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    monkeypatch.setattr(app, "SECURITY_CONFIG_FILE", tmp_path / "security.json")
    return app


def test_load_returns_default_when_missing(fresh_app):
    cfg = fresh_app.load_security_config()
    assert cfg["mode"] == "A"
    assert cfg["pin_hash"] is None
    assert cfg["recovery_logo_enabled"] is True
    assert cfg["version"] == 1


def test_save_then_load_roundtrip(fresh_app):
    cfg = {
        "version": 1,
        "mode": "B",
        "pin_hash": "$2b$12$abc",
        "owner_pwd_hash": "$2b$12$xyz",
        "recovery_logo_enabled": False,
        "created_at": "2026-05-15T00:00:00Z",
    }
    fresh_app.save_security_config(cfg)
    loaded = fresh_app.load_security_config()
    assert loaded == cfg


def test_load_corrupt_file_falls_back_to_default(fresh_app):
    fresh_app.SECURITY_CONFIG_FILE.write_text("{not valid")
    cfg = fresh_app.load_security_config()
    assert cfg["mode"] == "A"
    assert cfg["pin_hash"] is None


def test_save_atomic_write_uses_replace(fresh_app, monkeypatch):
    calls = []
    real_replace = os.replace
    def spy(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)
    monkeypatch.setattr(os, "replace", spy)
    fresh_app.save_security_config(fresh_app._security_config_defaults())
    assert len(calls) == 1
    assert calls[0][1] == str(fresh_app.SECURITY_CONFIG_FILE)
    assert ".tmp" in calls[0][0]
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_config.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'load_security_config'`.

- [ ] **Step 3: Implement helpers**

In `backend/app.py`, after the constants block, add:

```python
def _security_config_defaults():
    return {
        "version": 1,
        "mode": "A",
        "pin_hash": None,
        "owner_pwd_hash": None,
        "recovery_logo_enabled": True,
        "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def load_security_config():
    """Read security.json. On missing/corrupt file, return safe defaults."""
    try:
        if not SECURITY_CONFIG_FILE.exists():
            return _security_config_defaults()
        with open(SECURITY_CONFIG_FILE, "r") as f:
            cfg = json.load(f)
        defaults = _security_config_defaults()
        for k, v in defaults.items():
            cfg.setdefault(k, v)
        return cfg
    except (json.JSONDecodeError, OSError) as e:
        print(f"[security] config load failed ({e}); using defaults", flush=True)
        return _security_config_defaults()


def save_security_config(cfg):
    """Atomic write of security.json with 0600 perms."""
    SECURITY_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SECURITY_CONFIG_FILE.with_suffix(SECURITY_CONFIG_FILE.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, SECURITY_CONFIG_FILE)
```

Verify `from datetime import datetime` is imported at the top of the file; add it if missing.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_security_config.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_config.py
git commit -m "backend: load/save security.json with atomic write + safe defaults"
```

### Task 7: PIN and owner-password hash helpers

**Files:**
- Modify: `backend/app.py`
- Create: `tests/test_security_hash.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_security_hash.py`:

```python
"""bcrypt PIN/owner-password helpers."""
import importlib, pytest


@pytest.fixture
def fresh_app():
    import app
    importlib.reload(app)
    return app


def test_hash_pin_returns_bcrypt_hash(fresh_app):
    h = fresh_app.hash_pin("123456")
    assert h.startswith("$2b$") or h.startswith("$2a$")
    assert len(h) >= 60


def test_verify_pin_accepts_correct(fresh_app):
    h = fresh_app.hash_pin("482919")
    assert fresh_app.verify_pin("482919", h) is True


def test_verify_pin_rejects_wrong(fresh_app):
    h = fresh_app.hash_pin("482919")
    assert fresh_app.verify_pin("000000", h) is False


def test_verify_pin_rejects_empty(fresh_app):
    h = fresh_app.hash_pin("482919")
    assert fresh_app.verify_pin("", h) is False
    assert fresh_app.verify_pin(None, h) is False


def test_hash_pin_rejects_bad_shape(fresh_app):
    with pytest.raises(ValueError):
        fresh_app.hash_pin("abc")
    with pytest.raises(ValueError):
        fresh_app.hash_pin("12345")


def test_owner_password_roundtrip(fresh_app):
    h = fresh_app.hash_owner_password("<device-password>")
    assert fresh_app.verify_owner_password("<device-password>", h) is True
    assert fresh_app.verify_owner_password("wrong", h) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_hash.py -v`
Expected: FAIL — helpers not defined.

- [ ] **Step 3: Implement helpers**

In `backend/app.py`, add:

```python
import bcrypt as _bcrypt


def hash_pin(pin):
    if not isinstance(pin, str) or len(pin) != PIN_LENGTH or not pin.isdigit():
        raise ValueError(f"PIN must be {PIN_LENGTH} digits")
    return _bcrypt.hashpw(pin.encode("utf-8"),
                          _bcrypt.gensalt(rounds=PIN_BCRYPT_COST)).decode("utf-8")


def verify_pin(pin, hash_str):
    if not pin or not hash_str:
        return False
    try:
        return _bcrypt.checkpw(pin.encode("utf-8"), hash_str.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_owner_password(pwd):
    if not isinstance(pwd, str) or not pwd:
        raise ValueError("owner password must be a non-empty string")
    return _bcrypt.hashpw(pwd.encode("utf-8"),
                          _bcrypt.gensalt(rounds=PIN_BCRYPT_COST)).decode("utf-8")


def verify_owner_password(pwd, hash_str):
    if not pwd or not hash_str:
        return False
    try:
        return _bcrypt.checkpw(pwd.encode("utf-8"), hash_str.encode("utf-8"))
    except (ValueError, TypeError):
        return False
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_security_hash.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_hash.py
git commit -m "backend: bcrypt helpers for PIN and owner-password"
```

### Task 8: Session management

**Files:**
- Modify: `backend/app.py`
- Create: `tests/test_security_sessions.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_security_sessions.py`:

```python
"""Session token issue/validate/revoke."""
import importlib, json, time, pytest


@pytest.fixture
def fresh_app(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    monkeypatch.setattr(app, "SESSIONS_FILE", tmp_path / "sessions.json")
    return app


def test_issue_returns_token_and_expiry(fresh_app):
    s = fresh_app.issue_session("10.0.0.42", "iOS")
    assert "token" in s and len(s["token"]) >= 32
    assert s["expires_at"] > time.time()


def test_validate_accepts_recent(fresh_app):
    s = fresh_app.issue_session("10.0.0.42", "iOS")
    ok, _ = fresh_app.validate_session(s["token"])
    assert ok is True


def test_validate_rejects_unknown(fresh_app):
    ok, reason = fresh_app.validate_session("bogus")
    assert ok is False and reason == "invalid"


def test_validate_rejects_expired(fresh_app):
    s = fresh_app.issue_session("10.0.0.42", "iOS")
    data = json.loads(fresh_app.SESSIONS_FILE.read_text())
    data[s["token"]]["expires_at"] = time.time() - 60
    fresh_app.SESSIONS_FILE.write_text(json.dumps(data))
    ok, reason = fresh_app.validate_session(s["token"])
    assert ok is False and reason == "expired"


def test_revoke_session(fresh_app):
    s = fresh_app.issue_session("10.0.0.42", "iOS")
    fresh_app.revoke_session(s["token"])
    ok, _ = fresh_app.validate_session(s["token"])
    assert ok is False


def test_revoke_all(fresh_app):
    fresh_app.issue_session("10.0.0.42", "iOS")
    fresh_app.issue_session("10.0.0.51", "Chrome")
    fresh_app.revoke_all_sessions()
    assert fresh_app.list_sessions() == []


def test_list_sessions_omits_raw_tokens(fresh_app):
    fresh_app.issue_session("10.0.0.42", "iOS")
    items = fresh_app.list_sessions()
    assert len(items) == 1
    assert "token" not in items[0]
    assert "token_id" in items[0]
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_sessions.py -v`
Expected: FAIL — helpers not defined.

- [ ] **Step 3: Implement helpers**

In `backend/app.py`, add `import secrets` at the top of the file if missing, then:

```python
def _load_sessions():
    try:
        if not SESSIONS_FILE.exists():
            return {}
        with open(SESSIONS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_sessions(sessions):
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SESSIONS_FILE.with_suffix(SESSIONS_FILE.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(sessions, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, SESSIONS_FILE)


def issue_session(ip, ua):
    token = secrets.token_urlsafe(32)
    now = time.time()
    expires_at = now + (SESSION_TTL_DAYS * 86400)
    sessions = _load_sessions()
    sessions[token] = {
        "created_at": now,
        "expires_at": expires_at,
        "ip": ip or "",
        "ua": (ua or "")[:200],
    }
    _save_sessions(sessions)
    return {"token": token, "expires_at": expires_at}


def validate_session(token):
    if not token:
        return False, "invalid"
    sessions = _load_sessions()
    entry = sessions.get(token)
    if entry is None:
        return False, "invalid"
    if entry.get("expires_at", 0) < time.time():
        sessions.pop(token, None)
        _save_sessions(sessions)
        return False, "expired"
    return True, "ok"


def revoke_session(token):
    sessions = _load_sessions()
    if sessions.pop(token, None) is not None:
        _save_sessions(sessions)


def revoke_all_sessions():
    _save_sessions({})


def list_sessions():
    sessions = _load_sessions()
    now = time.time()
    out = []
    cleaned = {}
    for token, entry in sessions.items():
        if entry.get("expires_at", 0) >= now:
            cleaned[token] = entry
            out.append({
                "token_id": token[:8],
                "ip": entry.get("ip", ""),
                "ua": entry.get("ua", ""),
                "created_at": entry.get("created_at", 0),
                "expires_at": entry.get("expires_at", 0),
            })
    if cleaned != sessions:
        _save_sessions(cleaned)
    return out
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_security_sessions.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_sessions.py
git commit -m "backend: session token issue/validate/revoke"
```

### Task 9: Audit log writer

**Files:**
- Modify: `backend/app.py`
- Create: `tests/test_security_audit.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_security_audit.py`:

```python
"""Audit log writer."""
import importlib, json, pytest


@pytest.fixture
def fresh_app(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    monkeypatch.setattr(app, "AUDIT_LOG_PATH", tmp_path / "audit.log")
    return app


def test_append_writes_jsonl(fresh_app):
    fresh_app.append_audit("login", result="ok", ip="10.0.0.42")
    lines = fresh_app.AUDIT_LOG_PATH.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["action"] == "login"
    assert rec["result"] == "ok"
    assert rec["ip"] == "10.0.0.42"


def test_never_logs_pin_or_password_or_token(fresh_app):
    fresh_app.append_audit("login", result="fail", ip="x",
                           pin="123456", password="<device-password>", token="abc")
    text = fresh_app.AUDIT_LOG_PATH.read_text()
    assert "123456" not in text
    assert "<device-password>" not in text
    assert "abc" not in text


def test_rotates_at_threshold(fresh_app, monkeypatch):
    monkeypatch.setattr(fresh_app, "AUDIT_LOG_MAX_BYTES", 200)
    for i in range(50):
        fresh_app.append_audit("noise", what=f"x{i}")
    rotated = fresh_app.AUDIT_LOG_PATH.with_suffix(".log.1")
    assert rotated.exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_audit.py -v`
Expected: FAIL — `append_audit` not defined.

- [ ] **Step 3: Implement**

In `backend/app.py`, add:

```python
_AUDIT_SENSITIVE_KEYS = {"pin", "new_pin", "current_pin", "password",
                         "owner_password", "token", "session", "hash"}


def _strip_sensitive(kwargs):
    return {k: v for k, v in kwargs.items() if k not in _AUDIT_SENSITIVE_KEYS}


def append_audit(action, what=None, ip=None, result="ok", **extra):
    try:
        rotate_audit_if_needed()
        rec = {
            "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ip": ip or "",
            "action": action,
            "result": result,
        }
        if what is not None:
            rec["what"] = what
        rec.update(_strip_sensitive(extra))
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(rec) + "\n")
        os.chmod(AUDIT_LOG_PATH, 0o640)
    except Exception as e:
        print(f"[audit] write failed: {e}", flush=True)


def rotate_audit_if_needed():
    try:
        if not AUDIT_LOG_PATH.exists():
            return
        if AUDIT_LOG_PATH.stat().st_size < AUDIT_LOG_MAX_BYTES:
            return
        rotated = AUDIT_LOG_PATH.with_suffix(".log.1")
        if rotated.exists():
            rotated.unlink()
        AUDIT_LOG_PATH.rename(rotated)
    except OSError as e:
        print(f"[audit] rotation failed: {e}", flush=True)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_security_audit.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_audit.py
git commit -m "backend: audit log with rotation and sensitive-key stripping"
```

### Task 10: Failure counter + rate limit

**Files:**
- Modify: `backend/app.py`
- Create: `tests/test_security_failures.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_security_failures.py`:

```python
"""Per-IP cooldown schedule and global lockout."""
import importlib, pytest


@pytest.fixture
def fresh_app(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    monkeypatch.setattr(app, "FAILURES_FILE", tmp_path / "failures.json")
    return app


def test_first_three_no_cooldown(fresh_app):
    for _ in range(3):
        r = fresh_app.record_failure("10.0.0.42")
        assert r["per_ip_cooldown"] == 0


def test_fourth_triggers_30s(fresh_app):
    for _ in range(3):
        fresh_app.record_failure("10.0.0.42")
    r = fresh_app.record_failure("10.0.0.42")
    assert r["per_ip_cooldown"] == 30


def test_sixth_triggers_60s(fresh_app):
    for _ in range(5):
        fresh_app.record_failure("10.0.0.42")
    r = fresh_app.record_failure("10.0.0.42")
    assert r["per_ip_cooldown"] == 60


def test_ninth_triggers_300s(fresh_app):
    for _ in range(8):
        fresh_app.record_failure("10.0.0.42")
    r = fresh_app.record_failure("10.0.0.42")
    assert r["per_ip_cooldown"] == 300


def test_thirteenth_caps_900s(fresh_app):
    for _ in range(12):
        fresh_app.record_failure("10.0.0.42")
    r = fresh_app.record_failure("10.0.0.42")
    assert r["per_ip_cooldown"] == 900


def test_clear_failures_resets_one_ip(fresh_app):
    for _ in range(5):
        fresh_app.record_failure("10.0.0.42")
    fresh_app.record_failure("10.0.0.99")
    fresh_app.clear_failures("10.0.0.42")
    assert fresh_app.cooldown_remaining("10.0.0.42") == 0


def test_global_lockout_threshold(fresh_app, monkeypatch):
    monkeypatch.setattr(fresh_app, "GLOBAL_LOCKOUT_THRESHOLD", 5)
    last = None
    for i in range(5):
        last = fresh_app.record_failure(f"10.0.0.{i}")
    assert last["hard_locked"] is True


def test_clear_all_failures_unlocks(fresh_app, monkeypatch):
    monkeypatch.setattr(fresh_app, "GLOBAL_LOCKOUT_THRESHOLD", 3)
    for i in range(3):
        fresh_app.record_failure(f"10.0.0.{i}")
    fresh_app.clear_all_failures()
    r = fresh_app.record_failure("10.0.0.99")
    assert r["hard_locked"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_failures.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `backend/app.py`, add:

```python
def _load_failures():
    try:
        if not FAILURES_FILE.exists():
            return {"by_ip": {}, "global": [], "hard_locked_at": None}
        with open(FAILURES_FILE, "r") as f:
            data = json.load(f)
        data.setdefault("by_ip", {})
        data.setdefault("global", [])
        data.setdefault("hard_locked_at", None)
        return data
    except (json.JSONDecodeError, OSError):
        return {"by_ip": {}, "global": [], "hard_locked_at": None}


def _save_failures(data):
    FAILURES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FAILURES_FILE.with_suffix(FAILURES_FILE.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, FAILURES_FILE)


def _purge_old(timestamps, window_seconds):
    cutoff = time.time() - window_seconds
    return [t for t in timestamps if t >= cutoff]


def _cooldown_for_count(count):
    for max_n, secs in PER_IP_COOLDOWN_SCHEDULE:
        if max_n is None or count <= max_n:
            return secs
    return PER_IP_COOLDOWN_SCHEDULE[-1][1]


def record_failure(ip):
    now = time.time()
    data = _load_failures()
    window = GLOBAL_LOCKOUT_WINDOW_HOURS * 3600

    by_ip = data["by_ip"]
    arr = _purge_old(by_ip.get(ip, []), window)
    arr.append(now)
    by_ip[ip] = arr

    glob = _purge_old(data["global"], window)
    glob.append(now)
    data["global"] = glob

    hard_locked = len(glob) >= GLOBAL_LOCKOUT_THRESHOLD
    if hard_locked:
        data["hard_locked_at"] = now

    _save_failures(data)
    return {"per_ip_cooldown": _cooldown_for_count(len(arr)),
            "hard_locked": hard_locked}


def cooldown_remaining(ip):
    data = _load_failures()
    window = GLOBAL_LOCKOUT_WINDOW_HOURS * 3600
    arr = _purge_old(data["by_ip"].get(ip, []), window)
    if not arr:
        return 0
    cooldown = _cooldown_for_count(len(arr))
    if cooldown == 0:
        return 0
    elapsed = time.time() - arr[-1]
    return max(0, int(cooldown - elapsed))


def clear_failures(ip):
    data = _load_failures()
    if ip in data["by_ip"]:
        del data["by_ip"][ip]
        _save_failures(data)


def clear_all_failures():
    _save_failures({"by_ip": {}, "global": [], "hard_locked_at": None})


def is_hard_locked():
    data = _load_failures()
    return data.get("hard_locked_at") is not None
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_security_failures.py -v`
Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_failures.py
git commit -m "backend: per-IP cooldown + global hard lockout"
```

---

## Phase 3 — Endpoint classifier and enforcement

### Task 11: Endpoint classifier

**Files:**
- Modify: `backend/app.py`
- Create: `tests/test_security_classify.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_security_classify.py`:

```python
"""Endpoint classification."""
import importlib, pytest


@pytest.fixture
def fresh_app():
    import app
    importlib.reload(app)
    return app


@pytest.mark.parametrize("path,method,expected", [
    ("/api/version", "GET", "read"),
    ("/api/nft-list", "GET", "read"),
    ("/api/qrcode", "GET", "read"),
    ("/api/screen-color", "GET", "read"),
    ("/api/download-progress", "GET", "read"),
    ("/api/security/config", "GET", "security"),
    ("/api/security/login", "POST", "security"),
    ("/api/security/recover", "POST", "security"),
    ("/api/nft-delete", "POST", "delete"),
    ("/api/csv-library/delete", "POST", "delete"),
    ("/api/csv-library/clear-files", "POST", "delete"),
    ("/api/carousels/MyList", "DELETE", "delete"),
    ("/api/backup/delete", "POST", "delete"),
    ("/api/files/delete", "POST", "delete"),
    ("/api/setup/complete", "DELETE", "delete"),
    ("/api/thumbnails/clear", "POST", "delete"),
    ("/api/clear-cache", "POST", "delete"),
    ("/api/ipfs/gc", "POST", "delete"),
    ("/api/burner/cache", "DELETE", "delete"),
    ("/api/hue/disconnect", "POST", "delete"),
    ("/api/storage/external/migrate", "POST", "delete"),
    ("/api/https", "DELETE", "delete"),
    ("/api/security/pin", "DELETE", "delete"),
    ("/api/setup/change-password", "POST", "delete"),
    ("/api/theme", "POST", "control"),
    ("/api/display-config", "POST", "control"),
    ("/api/hue/set-color", "POST", "control"),
    ("/api/csv-library/install", "POST", "control"),
    ("/api/carousels", "POST", "control"),
    ("/api/remote/command", "POST", "control"),
    ("/api/screen/brightness", "POST", "control"),
])
def test_classify(fresh_app, path, method, expected):
    assert fresh_app.classify_endpoint(path, method) == expected


def test_bootstrap_when_no_config_file(fresh_app, tmp_path, monkeypatch):
    monkeypatch.setattr(fresh_app, "SECURITY_CONFIG_FILE", tmp_path / "missing.json")
    assert fresh_app.classify_endpoint("/api/setup/quick-import", "POST") == "bootstrap"


def test_setup_normal_once_config_exists(fresh_app, tmp_path, monkeypatch):
    f = tmp_path / "security.json"
    f.write_text('{"version":1,"mode":"A","pin_hash":null,"owner_pwd_hash":null,'
                 '"recovery_logo_enabled":true,"created_at":""}')
    monkeypatch.setattr(fresh_app, "SECURITY_CONFIG_FILE", f)
    assert fresh_app.classify_endpoint("/api/setup/change-password", "POST") == "delete"
    assert fresh_app.classify_endpoint("/api/setup/complete", "DELETE") == "delete"
    assert fresh_app.classify_endpoint("/api/setup/quick-import", "POST") == "control"
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_classify.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement classifier**

In `backend/app.py`, add:

```python
_DELETE_EXACT = frozenset([
    "/api/nft-delete",
    "/api/csv-library/delete",
    "/api/csv-library/clear-files",
    "/api/backup/delete",
    "/api/files/delete",
    "/api/thumbnails/clear",
    "/api/clear-cache",
    "/api/ipfs/gc",
    "/api/hue/disconnect",
    "/api/storage/external/migrate",
    "/api/setup/change-password",
])
_DELETE_METHOD_PATHS = frozenset([
    ("DELETE", "/api/carousels"),
    ("DELETE", "/api/setup/complete"),
    ("DELETE", "/api/burner/cache"),
    ("DELETE", "/api/https"),
    ("DELETE", "/api/security/pin"),
])

_SECURITY_PREFIX = "/api/security/"

_READ_EXTRA = frozenset([
    "/api/screen-color",
    "/api/diagnostics",
    "/api/burner/render",
    "/api/burner/assets",
    "/api/cryptopunk",
    "/api/autoglyph",
])


def classify_endpoint(path, method):
    """Return 'read' | 'control' | 'delete' | 'security' | 'bootstrap'."""
    path = path.rstrip("/") or "/"

    if path.startswith(_SECURITY_PREFIX):
        if (method, path) in _DELETE_METHOD_PATHS:
            return "delete"
        return "security"

    if path in _DELETE_EXACT:
        return "delete"
    for m, prefix in _DELETE_METHOD_PATHS:
        if method == m and (path == prefix or path.startswith(prefix + "/")):
            return "delete"

    if path.startswith("/api/setup/") and not SECURITY_CONFIG_FILE.exists():
        return "bootstrap"

    if method == "GET":
        return "read"
    if path in _READ_EXTRA:
        return "read"
    if path in _AUTH_EXEMPT_PATHS:
        return "read"

    return "control"
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_security_classify.py -v`
Expected: all parametrized cases PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_classify.py
git commit -m "backend: endpoint classifier"
```

### Task 12: Replace `_enforce_auth` with `_enforce_security`

**Files:**
- Modify: `backend/app.py` (the `@app.before_request` around line 160)
- Create: `tests/test_security_enforce.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_security_enforce.py`:

```python
"""Integration tests for the new before_request hook."""
import importlib, pytest


@pytest.fixture
def fresh_app(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    monkeypatch.setattr(app, "SECURITY_CONFIG_FILE", tmp_path / "security.json")
    monkeypatch.setattr(app, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(app, "FAILURES_FILE", tmp_path / "failures.json")
    monkeypatch.setattr(app, "AUDIT_LOG_PATH", tmp_path / "audit.log")
    return app


def _set_mode(app_mod, mode, has_pin=True):
    cfg = app_mod._security_config_defaults()
    cfg["mode"] = mode
    if has_pin:
        cfg["pin_hash"] = app_mod.hash_pin("123456")
    app_mod.save_security_config(cfg)


def test_mode_a_allows_delete_without_pin(fresh_app):
    _set_mode(fresh_app, "A", has_pin=False)
    client = fresh_app.app.test_client()
    r = client.post("/api/nft-delete", json={"filenames": []},
                    environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code not in (401, 403, 429)


def test_mode_b_blocks_delete_without_session(fresh_app):
    _set_mode(fresh_app, "B")
    client = fresh_app.app.test_client()
    r = client.post("/api/nft-delete", json={"filenames": []},
                    environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 401
    assert r.get_json().get("error") == "pin_required"


def test_mode_b_allows_control(fresh_app):
    _set_mode(fresh_app, "B")
    client = fresh_app.app.test_client()
    r = client.post("/api/theme", json={"style": "walnut"},
                    environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code not in (401, 403, 429)


def test_mode_c_blocks_control(fresh_app):
    _set_mode(fresh_app, "C")
    client = fresh_app.app.test_client()
    r = client.post("/api/theme", json={"style": "walnut"},
                    environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 401


def test_mode_c_allows_localhost(fresh_app):
    _set_mode(fresh_app, "C")
    client = fresh_app.app.test_client()
    r = client.post("/api/theme", json={"style": "walnut"},
                    environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code not in (401, 403, 429)


def test_session_unlocks_delete_in_b(fresh_app):
    _set_mode(fresh_app, "B")
    s = fresh_app.issue_session("10.0.0.42", "test")
    client = fresh_app.app.test_client()
    r = client.post("/api/nft-delete", json={"filenames": []},
                    headers={"X-Vernis-PIN-Session": s["token"]},
                    environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code not in (401, 403, 429)


def test_get_always_allowed(fresh_app):
    _set_mode(fresh_app, "C")
    client = fresh_app.app.test_client()
    r = client.get("/api/version",
                   environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_enforce.py -v`
Expected: FAIL.

- [ ] **Step 3: Replace `_enforce_auth`**

In `backend/app.py`, find the `@app.before_request` decorator and the `_enforce_auth` function. Replace the whole function with:

```python
@app.before_request
def _enforce_security():
    """Mode-based access control. See spec §5.2."""
    if request.remote_addr in ("127.0.0.1", "::1"):
        return None

    cls = classify_endpoint(request.path, request.method)
    if cls in ("read", "bootstrap"):
        return None
    if cls == "security":
        return None

    cfg = load_security_config()
    mode = cfg.get("mode", "A")
    if mode == "A":
        return None
    if mode == "B" and cls == "control":
        return None

    token = (request.headers.get("X-Vernis-PIN-Session")
             or request.args.get("pin_session", ""))
    ok, _ = validate_session(token)
    if ok:
        return None
    return jsonify({"error": "pin_required"}), 401
```

The old `_enforce_auth` function should be removed. Keep `require_auth` for now — it's referenced from `/api/auth-token`.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_security_enforce.py -v && python3 -m pytest tests/ -v`
Expected: all PASS across all test files.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_enforce.py
git commit -m "backend: enforce three-mode security on every request"
```

---

## Phase 4 — Auth endpoints

### Task 13: GET /api/security/config

**Files:**
- Modify: `backend/app.py`
- Create: `tests/test_security_endpoints.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_security_endpoints.py`:

```python
"""Integration tests for /api/security/* endpoints."""
import importlib, pytest


@pytest.fixture
def fresh_app(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    monkeypatch.setattr(app, "SECURITY_CONFIG_FILE", tmp_path / "security.json")
    monkeypatch.setattr(app, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(app, "FAILURES_FILE", tmp_path / "failures.json")
    monkeypatch.setattr(app, "AUDIT_LOG_PATH", tmp_path / "audit.log")
    return app


def _set_pin(fresh_app, pin):
    cfg = fresh_app._security_config_defaults()
    cfg["pin_hash"] = fresh_app.hash_pin(pin)
    fresh_app.save_security_config(cfg)


def _set_owner_password(fresh_app, pwd):
    cfg = fresh_app.load_security_config()
    cfg["owner_pwd_hash"] = fresh_app.hash_owner_password(pwd)
    fresh_app.save_security_config(cfg)


def test_config_defaults_for_fresh(fresh_app):
    client = fresh_app.app.test_client()
    r = client.get("/api/security/config",
                   environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["mode"] == "A"
    assert d["has_pin"] is False
    assert d["recovery_logo_enabled"] is True
    assert d["hard_locked"] is False
    assert d["kiosk"] is False


def test_config_kiosk_flag_for_localhost(fresh_app):
    client = fresh_app.app.test_client()
    r = client.get("/api/security/config",
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.get_json()["kiosk"] is True


def test_config_locked_until_during_cooldown(fresh_app):
    client = fresh_app.app.test_client()
    for _ in range(4):
        fresh_app.record_failure("10.0.0.42")
    r = client.get("/api/security/config",
                   environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    d = r.get_json()
    assert d["locked_until"] is not None
    assert d["locked_until"] > 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_endpoints.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Implement endpoint**

In `backend/app.py`, add:

```python
@app.route("/api/security/config", methods=["GET"])
def security_config():
    cfg = load_security_config()
    is_kiosk = request.remote_addr in ("127.0.0.1", "::1")
    remaining = cooldown_remaining(request.remote_addr or "")
    locked_until = (time.time() + remaining) if remaining > 0 else None
    return jsonify({
        "mode": cfg.get("mode", "A"),
        "has_pin": bool(cfg.get("pin_hash")),
        "recovery_logo_enabled": bool(cfg.get("recovery_logo_enabled", True)),
        "locked_until": locked_until,
        "hard_locked": is_hard_locked(),
        "kiosk": is_kiosk,
    })
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_security_endpoints.py -v -k config`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_endpoints.py
git commit -m "backend: GET /api/security/config"
```

### Task 14: POST /api/security/login

**Files:**
- Modify: `backend/app.py`
- Modify: `tests/test_security_endpoints.py`

- [ ] **Step 1: Append tests**

Append to `tests/test_security_endpoints.py`:

```python
def test_login_correct_pin(fresh_app):
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/login", json={"pin": "123456"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    d = r.get_json()
    assert "token" in d and len(d["token"]) >= 32


def test_login_wrong_pin(fresh_app):
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/login", json={"pin": "999999"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 401


def test_login_invalid_shape(fresh_app):
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/login", json={"pin": "abc"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 422


def test_login_429_after_cooldown(fresh_app):
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    for _ in range(4):
        c.post("/api/security/login", json={"pin": "000000"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    r = c.post("/api/security/login", json={"pin": "123456"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_login_423_global_lockout(fresh_app, monkeypatch):
    monkeypatch.setattr(fresh_app, "GLOBAL_LOCKOUT_THRESHOLD", 3)
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    for i in range(3):
        c.post("/api/security/login", json={"pin": "000000"},
               environ_overrides={"REMOTE_ADDR": f"10.0.0.{i}"})
    r = c.post("/api/security/login", json={"pin": "123456"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.99"})
    assert r.status_code == 423


def test_login_success_clears_failures(fresh_app):
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    for _ in range(2):
        c.post("/api/security/login", json={"pin": "000000"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    r = c.post("/api/security/login", json={"pin": "123456"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    assert fresh_app.cooldown_remaining("10.0.0.42") == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_endpoints.py -v -k login`
Expected: FAIL.

- [ ] **Step 3: Implement endpoint**

In `backend/app.py`, add:

```python
@app.route("/api/security/login", methods=["POST"])
def security_login():
    ip = request.remote_addr or ""
    if is_hard_locked():
        append_audit("login_blocked", ip=ip, result="hard_locked")
        return jsonify({"error": "hard_locked"}), 423

    remaining = cooldown_remaining(ip)
    if remaining > 0:
        return (jsonify({"error": "cooldown", "retry_after": remaining}),
                429, {"Retry-After": str(remaining)})

    data = request.get_json(silent=True) or {}
    pin = data.get("pin", "")
    if not isinstance(pin, str) or len(pin) != PIN_LENGTH or not pin.isdigit():
        return jsonify({"error": "invalid_pin_shape"}), 422

    cfg = load_security_config()
    pin_hash = cfg.get("pin_hash")
    if not pin_hash or not verify_pin(pin, pin_hash):
        result = record_failure(ip)
        append_audit("login", ip=ip, result="fail")
        if result["hard_locked"]:
            return jsonify({"error": "hard_locked"}), 423
        return jsonify({"error": "invalid_pin"}), 401

    clear_failures(ip)
    sess = issue_session(ip, request.headers.get("User-Agent", "")[:200])
    append_audit("login", ip=ip, result="ok")
    return jsonify(sess)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_security_endpoints.py -v -k login`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_endpoints.py
git commit -m "backend: POST /api/security/login"
```

### Task 15: POST /api/security/logout

**Files:**
- Modify: `backend/app.py`
- Modify: `tests/test_security_endpoints.py`

- [ ] **Step 1: Append test**

```python
def test_logout_revokes_session(fresh_app):
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    s = fresh_app.issue_session("10.0.0.42", "t")
    r = c.post("/api/security/logout",
               headers={"X-Vernis-PIN-Session": s["token"]},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    ok, _ = fresh_app.validate_session(s["token"])
    assert ok is False
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_endpoints.py::test_logout_revokes_session -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `backend/app.py`, add:

```python
@app.route("/api/security/logout", methods=["POST"])
def security_logout():
    token = request.headers.get("X-Vernis-PIN-Session", "")
    if token:
        revoke_session(token)
    append_audit("logout", ip=request.remote_addr or "", result="ok")
    return jsonify({"ok": True})
```

- [ ] **Step 4: Run test**

Run: `python3 -m pytest tests/test_security_endpoints.py::test_logout_revokes_session -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_endpoints.py
git commit -m "backend: POST /api/security/logout"
```

### Task 16: POST /api/security/recover (initial setup + recovery)

**Files:**
- Modify: `backend/app.py`
- Modify: `tests/test_security_endpoints.py`

- [ ] **Step 1: Append tests**

```python
def test_recover_sets_initial_pin(fresh_app):
    _set_owner_password(fresh_app, "<device-password>")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/recover",
               json={"owner_password": "<device-password>", "new_pin": "482919"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and "token" in d
    assert fresh_app.load_security_config()["pin_hash"] is not None


def test_recover_rejects_wrong_password(fresh_app):
    _set_owner_password(fresh_app, "<device-password>")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/recover",
               json={"owner_password": "wrong", "new_pin": "482919"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 401


def test_recover_no_new_pin_drops_to_a(fresh_app):
    _set_owner_password(fresh_app, "<device-password>")
    cfg = fresh_app.load_security_config()
    cfg["pin_hash"] = fresh_app.hash_pin("123456")
    cfg["mode"] = "C"
    fresh_app.save_security_config(cfg)
    c = fresh_app.app.test_client()
    r = c.post("/api/security/recover",
               json={"owner_password": "<device-password>"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    cfg2 = fresh_app.load_security_config()
    assert cfg2["pin_hash"] is None
    assert cfg2["mode"] == "A"


def test_recover_with_new_pin_keeps_mode(fresh_app):
    _set_owner_password(fresh_app, "<device-password>")
    cfg = fresh_app.load_security_config()
    cfg["pin_hash"] = fresh_app.hash_pin("123456")
    cfg["mode"] = "B"
    fresh_app.save_security_config(cfg)
    c = fresh_app.app.test_client()
    r = c.post("/api/security/recover",
               json={"owner_password": "<device-password>", "new_pin": "777777"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    cfg2 = fresh_app.load_security_config()
    assert fresh_app.verify_pin("777777", cfg2["pin_hash"]) is True
    assert cfg2["mode"] == "B"


def test_recover_revokes_other_sessions(fresh_app):
    _set_owner_password(fresh_app, "<device-password>")
    s = fresh_app.issue_session("10.0.0.50", "old")
    c = fresh_app.app.test_client()
    c.post("/api/security/recover",
           json={"owner_password": "<device-password>", "new_pin": "111111"},
           environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    ok, _ = fresh_app.validate_session(s["token"])
    assert ok is False
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_endpoints.py -v -k recover`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `backend/app.py`, add:

```python
@app.route("/api/security/recover", methods=["POST"])
def security_recover():
    ip = request.remote_addr or ""
    remaining = cooldown_remaining(ip)
    if remaining > 0:
        return (jsonify({"error": "cooldown", "retry_after": remaining}),
                429, {"Retry-After": str(remaining)})

    data = request.get_json(silent=True) or {}
    pwd = data.get("owner_password", "")
    new_pin = data.get("new_pin")

    cfg = load_security_config()
    owner_hash = cfg.get("owner_pwd_hash")
    if not owner_hash or not verify_owner_password(pwd, owner_hash):
        result = record_failure(ip)
        append_audit("recovery", ip=ip, result="fail")
        if result["hard_locked"]:
            return jsonify({"error": "hard_locked"}), 423
        return jsonify({"error": "invalid_owner_password"}), 401

    if new_pin is not None:
        if not isinstance(new_pin, str) or len(new_pin) != PIN_LENGTH or not new_pin.isdigit():
            return jsonify({"error": "invalid_pin_shape"}), 422
        action_audit = "recovery_pin_set" if cfg.get("pin_hash") is None else "recovery_pin_reset"
        cfg["pin_hash"] = hash_pin(new_pin)
    else:
        cfg["pin_hash"] = None
        cfg["mode"] = "A"
        action_audit = "recovery_to_open"

    save_security_config(cfg)
    revoke_all_sessions()
    clear_failures(ip)

    resp = {"ok": True}
    if new_pin is not None:
        sess = issue_session(ip, request.headers.get("User-Agent", "")[:200])
        resp.update(sess)

    append_audit(action_audit, ip=ip, result="ok")
    return jsonify(resp)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_security_endpoints.py -v -k recover`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_endpoints.py
git commit -m "backend: POST /api/security/recover for initial setup and recovery"
```

### Task 17: POST and DELETE /api/security/pin

**Files:**
- Modify: `backend/app.py`
- Modify: `tests/test_security_endpoints.py`

- [ ] **Step 1: Append tests**

```python
def test_change_pin_with_session(fresh_app):
    _set_pin(fresh_app, "123456")
    s = fresh_app.issue_session("10.0.0.42", "t")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/pin",
               json={"current_pin": "123456", "new_pin": "999999"},
               headers={"X-Vernis-PIN-Session": s["token"]},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    cfg = fresh_app.load_security_config()
    assert fresh_app.verify_pin("999999", cfg["pin_hash"]) is True


def test_change_pin_wrong_current(fresh_app):
    _set_pin(fresh_app, "123456")
    s = fresh_app.issue_session("10.0.0.42", "t")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/pin",
               json={"current_pin": "000000", "new_pin": "999999"},
               headers={"X-Vernis-PIN-Session": s["token"]},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 401


def test_change_pin_requires_session(fresh_app):
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/pin",
               json={"current_pin": "123456", "new_pin": "999999"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 401


def test_delete_pin_drops_to_a(fresh_app):
    _set_pin(fresh_app, "123456")
    cfg = fresh_app.load_security_config()
    cfg["mode"] = "B"
    fresh_app.save_security_config(cfg)
    s = fresh_app.issue_session("10.0.0.42", "t")
    c = fresh_app.app.test_client()
    r = c.delete("/api/security/pin", json={"current_pin": "123456"},
                 headers={"X-Vernis-PIN-Session": s["token"]},
                 environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    cfg2 = fresh_app.load_security_config()
    assert cfg2["pin_hash"] is None
    assert cfg2["mode"] == "A"
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_endpoints.py -v -k "change_pin or delete_pin"`
Expected: FAIL.

- [ ] **Step 3: Implement endpoints**

In `backend/app.py`, add:

```python
def _require_session_or_401():
    token = request.headers.get("X-Vernis-PIN-Session", "")
    ok, _ = validate_session(token)
    if ok:
        return None
    return jsonify({"error": "pin_required"}), 401


@app.route("/api/security/pin", methods=["POST"])
def security_pin_change():
    err = _require_session_or_401()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    current = data.get("current_pin", "")
    new = data.get("new_pin", "")
    if any(not isinstance(p, str) or len(p) != PIN_LENGTH or not p.isdigit()
           for p in (current, new)):
        return jsonify({"error": "invalid_pin_shape"}), 422

    cfg = load_security_config()
    if not cfg.get("pin_hash") or not verify_pin(current, cfg["pin_hash"]):
        append_audit("pin_change", ip=request.remote_addr or "", result="fail")
        return jsonify({"error": "invalid_pin"}), 401

    cfg["pin_hash"] = hash_pin(new)
    save_security_config(cfg)
    current_token = request.headers.get("X-Vernis-PIN-Session", "")
    sessions = _load_sessions()
    kept = {current_token: sessions[current_token]} if current_token in sessions else {}
    _save_sessions(kept)
    append_audit("pin_changed", ip=request.remote_addr or "", result="ok")
    return jsonify({"ok": True})


@app.route("/api/security/pin", methods=["DELETE"])
def security_pin_remove():
    err = _require_session_or_401()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    current = data.get("current_pin", "")
    if not isinstance(current, str) or len(current) != PIN_LENGTH or not current.isdigit():
        return jsonify({"error": "invalid_pin_shape"}), 422

    cfg = load_security_config()
    if not cfg.get("pin_hash") or not verify_pin(current, cfg["pin_hash"]):
        append_audit("pin_remove", ip=request.remote_addr or "", result="fail")
        return jsonify({"error": "invalid_pin"}), 401

    cfg["pin_hash"] = None
    cfg["mode"] = "A"
    save_security_config(cfg)
    revoke_all_sessions()
    append_audit("pin_removed", ip=request.remote_addr or "", result="ok")
    return jsonify({"ok": True, "mode": "A"})
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_security_endpoints.py -v -k "change_pin or delete_pin"`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_endpoints.py
git commit -m "backend: POST and DELETE /api/security/pin"
```

### Task 18: POST /api/security/mode

**Files:**
- Modify: `backend/app.py`
- Modify: `tests/test_security_endpoints.py`

- [ ] **Step 1: Append tests**

```python
def test_mode_switch_to_b_with_session(fresh_app):
    _set_pin(fresh_app, "123456")
    s = fresh_app.issue_session("10.0.0.42", "t")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/mode", json={"mode": "B"},
               headers={"X-Vernis-PIN-Session": s["token"]},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    assert fresh_app.load_security_config()["mode"] == "B"


def test_mode_switch_b_without_pin(fresh_app):
    c = fresh_app.app.test_client()
    r = c.post("/api/security/mode", json={"mode": "C"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 400
    assert r.get_json()["error"] == "set_pin_first"


def test_mode_switch_revokes_sessions(fresh_app):
    _set_pin(fresh_app, "123456")
    cfg = fresh_app.load_security_config()
    cfg["mode"] = "B"
    fresh_app.save_security_config(cfg)
    s = fresh_app.issue_session("10.0.0.42", "t")
    s2 = fresh_app.issue_session("10.0.0.99", "other")
    c = fresh_app.app.test_client()
    c.post("/api/security/mode", json={"mode": "A"},
           headers={"X-Vernis-PIN-Session": s["token"]},
           environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    ok1, _ = fresh_app.validate_session(s["token"])
    ok2, _ = fresh_app.validate_session(s2["token"])
    assert ok1 is False and ok2 is False


def test_mode_switch_invalid_mode(fresh_app):
    _set_pin(fresh_app, "123456")
    s = fresh_app.issue_session("10.0.0.42", "t")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/mode", json={"mode": "Z"},
               headers={"X-Vernis-PIN-Session": s["token"]},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_endpoints.py -v -k mode_switch`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `backend/app.py`, add:

```python
@app.route("/api/security/mode", methods=["POST"])
def security_mode():
    data = request.get_json(silent=True) or {}
    new_mode = data.get("mode", "")
    if new_mode not in ("A", "B", "C"):
        return jsonify({"error": "invalid_mode"}), 422

    cfg = load_security_config()
    has_pin = bool(cfg.get("pin_hash"))

    if has_pin:
        err = _require_session_or_401()
        if err:
            return err
    elif new_mode in ("B", "C"):
        return jsonify({"error": "set_pin_first"}), 400

    old_mode = cfg.get("mode", "A")
    if old_mode == new_mode:
        return jsonify({"mode": new_mode})

    cfg["mode"] = new_mode
    save_security_config(cfg)
    revoke_all_sessions()
    append_audit("mode_change", ip=request.remote_addr or "",
                 result="ok", **{"from": old_mode, "to": new_mode})
    return jsonify({"mode": new_mode})
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_security_endpoints.py -v -k mode_switch`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_endpoints.py
git commit -m "backend: POST /api/security/mode"
```

### Task 19: Sessions list/revoke and audit tail

**Files:**
- Modify: `backend/app.py`
- Modify: `tests/test_security_endpoints.py`

- [ ] **Step 1: Append tests**

```python
def test_list_sessions_requires_session(fresh_app):
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    r = c.get("/api/security/sessions",
              environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 401


def test_list_sessions_returns_metadata(fresh_app):
    _set_pin(fresh_app, "123456")
    s = fresh_app.issue_session("10.0.0.42", "iOS")
    c = fresh_app.app.test_client()
    r = c.get("/api/security/sessions",
              headers={"X-Vernis-PIN-Session": s["token"]},
              environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    items = r.get_json()
    assert any(it["ip"] == "10.0.0.42" for it in items)
    assert all("token" not in it for it in items)


def test_revoke_single_session(fresh_app):
    _set_pin(fresh_app, "123456")
    s = fresh_app.issue_session("10.0.0.42", "t")
    other = fresh_app.issue_session("10.0.0.99", "other")
    c = fresh_app.app.test_client()
    r = c.delete(f"/api/security/sessions/{other['token'][:8]}",
                 headers={"X-Vernis-PIN-Session": s["token"]},
                 environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    ok, _ = fresh_app.validate_session(other["token"])
    assert ok is False
    ok2, _ = fresh_app.validate_session(s["token"])
    assert ok2 is True


def test_audit_mode_a_requires_localhost(fresh_app):
    c = fresh_app.app.test_client()
    r = c.get("/api/security/audit",
              environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 401


def test_audit_mode_b_requires_session(fresh_app):
    _set_pin(fresh_app, "123456")
    cfg = fresh_app.load_security_config()
    cfg["mode"] = "B"
    fresh_app.save_security_config(cfg)
    s = fresh_app.issue_session("10.0.0.42", "t")
    fresh_app.append_audit("login", ip="10.0.0.42", result="ok")
    c = fresh_app.app.test_client()
    r = c.get("/api/security/audit",
              headers={"X-Vernis-PIN-Session": s["token"]},
              environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    lines = r.get_json()
    assert any(l["action"] == "login" for l in lines)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_security_endpoints.py -v -k "sessions or audit"`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `backend/app.py`, add:

```python
@app.route("/api/security/sessions", methods=["GET"])
def security_sessions_list():
    if request.remote_addr not in ("127.0.0.1", "::1"):
        err = _require_session_or_401()
        if err:
            return err
    return jsonify(list_sessions())


@app.route("/api/security/sessions/<token_id>", methods=["DELETE"])
def security_sessions_revoke(token_id):
    if request.remote_addr not in ("127.0.0.1", "::1"):
        err = _require_session_or_401()
        if err:
            return err
    sessions = _load_sessions()
    target = next((t for t in sessions if t[:8] == token_id), None)
    if target:
        sessions.pop(target, None)
        _save_sessions(sessions)
        append_audit("session_revoked", ip=request.remote_addr or "",
                     result="ok", token_id=token_id)
    return jsonify({"ok": True})


@app.route("/api/security/audit", methods=["GET"])
def security_audit_tail():
    cfg = load_security_config()
    is_kiosk = request.remote_addr in ("127.0.0.1", "::1")
    if cfg.get("mode") == "A":
        if not is_kiosk:
            return jsonify({"error": "pin_required"}), 401
    else:
        if not is_kiosk:
            err = _require_session_or_401()
            if err:
                return err

    limit = int(request.args.get("limit", 100))
    limit = max(1, min(limit, 500))
    if not AUDIT_LOG_PATH.exists():
        return jsonify([])
    with open(AUDIT_LOG_PATH, "r") as f:
        lines = f.readlines()[-limit:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return jsonify(out)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_security_endpoints.py -v -k "sessions or audit"`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_security_endpoints.py
git commit -m "backend: session list/revoke and audit tail endpoints"
```

### Task 20: Sync owner_pwd_hash on change-password

**Files:**
- Modify: `backend/app.py` (existing `/api/setup/change-password` route around line 6195)
- Create: `tests/test_change_password_sync.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_change_password_sync.py`:

```python
"""Verify /api/setup/change-password also updates owner_pwd_hash."""
import importlib, pytest


@pytest.fixture
def fresh_app(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    monkeypatch.setattr(app, "SECURITY_CONFIG_FILE", tmp_path / "security.json")
    return app


def test_sync_updates_hash(fresh_app):
    cfg = fresh_app.load_security_config()
    cfg["owner_pwd_hash"] = fresh_app.hash_owner_password("old")
    fresh_app.save_security_config(cfg)
    fresh_app.sync_owner_password_hash("new")
    cfg2 = fresh_app.load_security_config()
    assert fresh_app.verify_owner_password("new", cfg2["owner_pwd_hash"]) is True
    assert fresh_app.verify_owner_password("old", cfg2["owner_pwd_hash"]) is False


def test_sync_noop_when_file_absent(fresh_app, tmp_path, monkeypatch):
    monkeypatch.setattr(fresh_app, "SECURITY_CONFIG_FILE", tmp_path / "missing.json")
    fresh_app.sync_owner_password_hash("x")  # must not raise
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_change_password_sync.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement and wire**

In `backend/app.py`, add the helper:

```python
def sync_owner_password_hash(new_password):
    """Re-hash a newly-set device password into security.json owner_pwd_hash.
    Safe to call even if security.json doesn't exist (bootstrap case)."""
    try:
        if not SECURITY_CONFIG_FILE.exists():
            return
        cfg = load_security_config()
        cfg["owner_pwd_hash"] = hash_owner_password(new_password)
        save_security_config(cfg)
        append_audit("owner_password_changed", result="ok")
    except Exception as e:
        print(f"[security] sync_owner_password_hash failed: {e}", flush=True)
```

In the existing `setup_change_password` route (find via `grep -n "setup_change_password" backend/app.py`), locate the line that runs `chpasswd` via `subprocess.run`. Immediately after the success check `if process.returncode != 0: return jsonify({"error": "Failed to change password"}), 500`, before `marker.touch()`, insert:

```python
        # Keep recovery hash in sync with the new device password.
        sync_owner_password_hash(new_password)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_change_password_sync.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_change_password_sync.py
git commit -m "backend: sync owner_pwd_hash when device password changes via UI"
```

---

## Phase 5 — Frontend lock guard, PIN prompt, settings UI

All frontend JS uses `document.createElement` + `textContent` (no `innerHTML`) so user-controlled values like IPs and user-agent strings cannot inject markup.

### Task 21: Create vernis-lock-guard.js

**Files:**
- Create: `vernis-lock-guard.js`

- [ ] **Step 1: Write the script**

Create `vernis-lock-guard.js`:

```javascript
/* Vernis Lock Guard — gates page contents in Mode C.
 *
 * On DOMContentLoaded, fetches /api/security/config. If mode==='C' and
 * the caller is not the kiosk and lacks a valid session, hides the body
 * and renders a PIN overlay. On successful login, stores session token
 * in localStorage and reveals the page.
 *
 * Pages including this script: settings, library, manage, lab, add.
 * Home (index.html) does NOT include it — the gallery is always viewable.
 */
(function () {
  'use strict';

  var SESSION_KEY = 'vernis-pin-session';
  var EXP_KEY = 'vernis-pin-session-expires';

  function getStoredSession() {
    var token = localStorage.getItem(SESSION_KEY);
    var expires = parseFloat(localStorage.getItem(EXP_KEY) || '0');
    if (!token || expires < Date.now() / 1000) {
      localStorage.removeItem(SESSION_KEY);
      localStorage.removeItem(EXP_KEY);
      return null;
    }
    return token;
  }

  function storeSession(token, expiresAt) {
    localStorage.setItem(SESSION_KEY, token);
    localStorage.setItem(EXP_KEY, String(expiresAt));
  }

  function clearSession() {
    localStorage.removeItem(SESSION_KEY);
    localStorage.removeItem(EXP_KEY);
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === 'text') node.textContent = attrs[k];
        else if (k === 'style') node.style.cssText = attrs[k];
        else if (k === 'class') node.className = attrs[k];
        else node.setAttribute(k, attrs[k]);
      });
    }
    if (children) {
      children.forEach(function (c) { node.appendChild(c); });
    }
    return node;
  }

  function fetchConfig() {
    return fetch('/api/security/config').then(function (r) { return r.json(); });
  }

  function hideBody() { document.body.style.visibility = 'hidden'; }
  function revealBody() { document.body.style.visibility = ''; }

  var INPUT_STYLE =
    'font-size:24px;letter-spacing:8px;text-align:center;width:100%;' +
    'padding:12px;border-radius:12px;border:1px solid var(--border-light);' +
    'background:var(--bg-tertiary);color:var(--text-primary);margin-bottom:16px;';
  var STATUS_STYLE = 'margin-top:12px;font-size:13px;color:var(--text-muted);';
  var SUBMIT_STYLE = 'background:var(--accent-primary);color:#fff;';

  function buildOverlay() {
    var logo = el('div', { class: 'kiosk-logo', id: 'vlg-logo',
      style: 'font-size:36px;margin-bottom:12px;', text: 'VERNIS' });
    var msg = el('div', { class: 'vernis-confirm-message', id: 'vlg-msg',
      text: 'Enter PIN to continue' });
    var pinInput = el('input', { type: 'password', inputmode: 'numeric',
      pattern: '\\d{6}', maxlength: '6', autocomplete: 'off',
      id: 'vlg-pin', style: INPUT_STYLE });
    var cancelBtn = el('button', { class: 'vernis-confirm-btn vernis-confirm-cancel',
      id: 'vlg-cancel', text: 'Cancel' });
    var submitBtn = el('button', { class: 'vernis-confirm-btn',
      id: 'vlg-submit', style: SUBMIT_STYLE, text: 'Unlock' });
    var actions = el('div', { class: 'vernis-confirm-actions' }, [cancelBtn, submitBtn]);
    var status = el('div', { id: 'vlg-status', style: STATUS_STYLE });
    var modal = el('div', { class: 'vernis-confirm-modal', role: 'dialog',
      'aria-label': 'PIN entry' }, [logo, msg, pinInput, actions, status]);
    var overlay = el('div', { class: 'vernis-confirm-overlay active',
      style: 'z-index:99999;' }, [modal]);
    return { overlay: overlay, pin: pinInput, submit: submitBtn,
      cancel: cancelBtn, status: status, logo: logo };
  }

  function submitPin(pin) {
    return fetch('/api/security/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin: pin })
    }).then(function (r) {
      return r.json().then(function (d) { return { status: r.status, data: d }; });
    });
  }

  function showOverlay() {
    var parts = buildOverlay();
    document.body.appendChild(parts.overlay);
    revealBody();
    document.body.style.overflow = 'hidden';
    parts.pin.focus();

    function setStatus(t) { parts.status.textContent = t || ''; }

    function tryLogin() {
      var value = parts.pin.value.trim();
      if (!/^\d{6}$/.test(value)) {
        setStatus('Enter exactly 6 digits.');
        return;
      }
      parts.submit.disabled = true;
      setStatus('Checking…');
      submitPin(value).then(function (res) {
        if (res.status === 200 && res.data.token) {
          storeSession(res.data.token, res.data.expires_at);
          parts.overlay.remove();
          document.body.style.overflow = '';
        } else if (res.status === 429) {
          setStatus('Too many tries. Try again in ' + res.data.retry_after + ' s.');
        } else if (res.status === 423) {
          setStatus('Device locked. Use SSH reset or hold the logo 5 s.');
        } else {
          setStatus('Wrong PIN.');
          parts.pin.value = '';
        }
      }).catch(function () { setStatus('Network error.'); })
        .finally(function () { parts.submit.disabled = false; });
    }

    parts.submit.addEventListener('click', tryLogin);
    parts.pin.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') tryLogin();
    });
    parts.cancel.addEventListener('click', function () {
      window.location.href = '/index.html';
    });

    if (window.VernisLogoLongPress) {
      window.VernisLogoLongPress.attach(parts.logo);
    }
  }

  function init() {
    hideBody();
    fetchConfig().then(function (cfg) {
      if (cfg.kiosk || cfg.mode !== 'C') {
        revealBody();
        return;
      }
      if (getStoredSession()) {
        revealBody();
        return;
      }
      showOverlay();
    }).catch(function () { revealBody(); });
  }

  window.VernisLockGuard = {
    getSession: getStoredSession,
    clearSession: clearSession,
    storeSession: storeSession,
    authHeaders: function () {
      var t = getStoredSession();
      return t ? { 'X-Vernis-PIN-Session': t } : {};
    },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
```

- [ ] **Step 2: Verify JS syntax**

Run: `node -c vernis-lock-guard.js` (skip if node not installed; manual browser load will validate later)
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add vernis-lock-guard.js
git commit -m "frontend: lock guard — Mode C PIN overlay for control pages"
```

### Task 22: Create vernis-pin-prompt.js

**Files:**
- Create: `vernis-pin-prompt.js`

- [ ] **Step 1: Write the script**

Create `vernis-pin-prompt.js`:

```javascript
/* Vernis PIN Prompt — wraps an API call that may return 401 in Mode B/C.
 * Shows a PIN modal, stores the new session, retries the call.
 *
 * Usage:
 *   VernisPinPrompt.withPin(function (headers) {
 *     return fetch('/api/nft-delete', {
 *       method: 'POST',
 *       headers: Object.assign({'Content-Type':'application/json'}, headers),
 *       body: JSON.stringify({ filenames: ['a.jpg'] })
 *     });
 *   }).then(handleResponse);
 */
(function () {
  'use strict';

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'style') node.style.cssText = attrs[k];
      else if (k === 'class') node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    if (children) children.forEach(function (c) { node.appendChild(c); });
    return node;
  }

  function authHeaders() {
    if (window.VernisLockGuard) return window.VernisLockGuard.authHeaders();
    var t = localStorage.getItem('vernis-pin-session');
    return t ? { 'X-Vernis-PIN-Session': t } : {};
  }

  var INPUT_STYLE =
    'font-size:24px;letter-spacing:8px;text-align:center;width:100%;' +
    'padding:12px;border-radius:12px;border:1px solid var(--border-light);' +
    'background:var(--bg-tertiary);color:var(--text-primary);margin-bottom:16px;';
  var STATUS_STYLE = 'margin-top:12px;font-size:13px;color:var(--text-muted);';
  var SUBMIT_STYLE = 'background:var(--accent-primary);color:#fff;';

  function buildPrompt() {
    var msg = el('div', { class: 'vernis-confirm-message',
      text: 'Enter PIN to continue' });
    var pin = el('input', { type: 'password', inputmode: 'numeric',
      pattern: '\\d{6}', maxlength: '6', autocomplete: 'off',
      id: 'vpp-pin', style: INPUT_STYLE });
    var cancel = el('button', { class: 'vernis-confirm-btn vernis-confirm-cancel',
      id: 'vpp-cancel', text: 'Cancel' });
    var submit = el('button', { class: 'vernis-confirm-btn',
      id: 'vpp-submit', style: SUBMIT_STYLE, text: 'Unlock' });
    var actions = el('div', { class: 'vernis-confirm-actions' }, [cancel, submit]);
    var status = el('div', { id: 'vpp-status', style: STATUS_STYLE });
    var modal = el('div', { class: 'vernis-confirm-modal', role: 'dialog',
      'aria-label': 'PIN required' }, [msg, pin, actions, status]);
    var overlay = el('div', { class: 'vernis-confirm-overlay active',
      style: 'z-index:99999;' }, [modal]);
    return { overlay: overlay, pin: pin, submit: submit, cancel: cancel, status: status };
  }

  function promptForPin() {
    return new Promise(function (resolve, reject) {
      var parts = buildPrompt();
      document.body.appendChild(parts.overlay);
      parts.pin.focus();

      function done(ok) {
        parts.overlay.remove();
        if (ok) resolve(); else reject(new Error('pin_cancelled'));
      }

      function tryLogin() {
        var value = parts.pin.value.trim();
        if (!/^\d{6}$/.test(value)) {
          parts.status.textContent = 'Enter 6 digits.';
          return;
        }
        parts.submit.disabled = true;
        parts.status.textContent = 'Checking…';
        fetch('/api/security/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin: value })
        }).then(function (r) {
          return r.json().then(function (d) { return { status: r.status, data: d }; });
        }).then(function (res) {
          if (res.status === 200 && res.data.token) {
            if (window.VernisLockGuard) {
              window.VernisLockGuard.storeSession(res.data.token, res.data.expires_at);
            } else {
              localStorage.setItem('vernis-pin-session', res.data.token);
              localStorage.setItem('vernis-pin-session-expires', String(res.data.expires_at));
            }
            done(true);
          } else if (res.status === 429) {
            parts.status.textContent = 'Try again in ' + res.data.retry_after + ' s.';
            parts.submit.disabled = false;
          } else if (res.status === 423) {
            parts.status.textContent = 'Device locked. Use SSH reset.';
            parts.submit.disabled = false;
          } else {
            parts.status.textContent = 'Wrong PIN.';
            parts.pin.value = '';
            parts.submit.disabled = false;
          }
        }).catch(function () {
          parts.status.textContent = 'Network error.';
          parts.submit.disabled = false;
        });
      }

      parts.submit.addEventListener('click', tryLogin);
      parts.pin.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') tryLogin();
      });
      parts.cancel.addEventListener('click', function () { done(false); });
    });
  }

  function withPin(callFn) {
    return callFn(authHeaders()).then(function (r) {
      if (r.status !== 401) return r;
      return r.clone().json().then(function (d) {
        if (d && d.error === 'pin_required') {
          return promptForPin().then(function () { return callFn(authHeaders()); });
        }
        return r;
      }).catch(function () { return r; });
    });
  }

  window.VernisPinPrompt = { withPin: withPin, promptForPin: promptForPin };
})();
```

- [ ] **Step 2: Verify syntax**

Run: `node -c vernis-pin-prompt.js`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add vernis-pin-prompt.js
git commit -m "frontend: pin-prompt — inline PIN entry for delete actions"
```

### Task 23: Wire lock-guard and pin-prompt into HTML pages

**Files:**
- Modify: `settings.html`, `library.html`, `manage.html`, `lab.html`, `add.html`
- Modify: `manage.html:1684` and `manage.html:2174` (the two `/api/nft-delete` calls)
- Modify: `library.html:3682` (the `/api/csv-library/delete` call)

- [ ] **Step 1: Add lock-guard script to control pages**

In each of `settings.html`, `library.html`, `manage.html`, `lab.html`, `add.html`, locate the first `<script>` tag inside `<head>` (or near the top of `<body>`). Immediately before it, insert:

```html
<script src="/vernis-lock-guard.js"></script>
```

Then in `manage.html` and `library.html` only, add immediately after the lock-guard line:

```html
<script src="/vernis-pin-prompt.js"></script>
```

- [ ] **Step 2: Wrap the `/api/nft-delete` call in manage.html around line 1684**

Find:

```javascript
const response = await fetch('/api/nft-delete', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    filenames: Array.from(selectedNFTs)
  })
});
```

Replace with:

```javascript
const response = await VernisPinPrompt.withPin(function (authHeaders) {
  return fetch('/api/nft-delete', {
    method: 'POST',
    headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders),
    body: JSON.stringify({ filenames: Array.from(selectedNFTs) })
  });
});
```

- [ ] **Step 3: Wrap the second `/api/nft-delete` call in manage.html around line 2174**

The second call uses `fetch('/api/nft-delete', ...)` similarly. Wrap it the same way.

- [ ] **Step 4: Wrap the `/api/csv-library/delete` call in library.html around line 3682**

Find the `fetch('/api/csv-library/delete', { ... })` invocation and wrap with `VernisPinPrompt.withPin(...)` the same way as Step 2.

- [ ] **Step 5: Smoke test**

Manual:
1. With Flask + Caddy running, fresh device (Mode A), open `http://localhost/manage.html` — page loads normally.
2. Set up PIN via `curl -X POST http://localhost/api/security/recover -H 'Content-Type: application/json' -d '{"owner_password":"<device-pwd>","new_pin":"482919"}'`.
3. Switch to Mode C via `curl -X POST http://localhost/api/security/mode -H 'Content-Type: application/json' -H "X-Vernis-PIN-Session: <token>" -d '{"mode":"C"}'`.
4. Reload manage.html in a private window — PIN overlay should appear.
5. Enter the PIN — page reveals.

- [ ] **Step 6: Commit**

```bash
git add settings.html library.html manage.html lab.html add.html
git commit -m "frontend: include lock-guard/pin-prompt + wrap delete calls"
```

### Task 24: Add Security section to settings.html

**Files:**
- Modify: `settings.html` (insert new section, add JS init)
- Modify: `vernis-themes.css` (add mode-selector and sessions-list styles)

- [ ] **Step 1: Locate insertion point**

Run: `grep -n 'section-https\|section-archive' settings.html`
Expected: locations around lines 5057 and 5109. Insert the new Security section between them.

- [ ] **Step 2: Insert the section markup**

In `settings.html`, after the closing `</section>` of `section-https`, insert:

```html
        <section class="settings-section" id="section-security">
            <h2>Security</h2>
            <p class="section-description">Control who can change settings, delete files, and manage your library.</p>

            <div class="setting-row">
                <label>Access Level</label>
                <div class="mode-selector" id="security-mode-selector">
                    <button class="mode-option" data-mode="A">Open</button>
                    <button class="mode-option" data-mode="B">Protected</button>
                    <button class="mode-option" data-mode="C">Locked</button>
                </div>
                <p class="setting-hint" id="security-mode-hint"></p>
            </div>

            <div class="setting-row" id="security-pin-row">
                <label>PIN</label>
                <button class="btn btn-primary" id="security-set-pin-btn">Set PIN</button>
                <button class="btn btn-secondary" id="security-change-pin-btn" style="display:none;">Change PIN</button>
                <button class="btn btn-danger" id="security-remove-pin-btn" style="display:none;">Remove PIN</button>
            </div>

            <div class="setting-row">
                <label>Recovery</label>
                <label class="toggle-switch">
                    <input type="checkbox" id="security-recovery-logo-toggle" />
                    <span class="toggle-slider"></span>
                </label>
                <p class="setting-hint">Allow PIN reset by holding the VERNIS logo 5 seconds and entering the device password.</p>
            </div>

            <div class="setting-row">
                <label>Active Sessions</label>
                <ul id="security-sessions-list"></ul>
            </div>

            <div class="setting-row">
                <button class="btn btn-secondary" id="security-audit-btn">View audit log</button>
            </div>
        </section>
```

- [ ] **Step 3: Add the JavaScript using safe DOM construction**

Near the bottom of `settings.html`, inside the existing settings `<script>` block (before the closing `</script>`), append:

```javascript
(function setupSecuritySection() {
  var modeSelector = document.getElementById('security-mode-selector');
  if (!modeSelector) return;
  var modeHint = document.getElementById('security-mode-hint');
  var setBtn = document.getElementById('security-set-pin-btn');
  var changeBtn = document.getElementById('security-change-pin-btn');
  var removeBtn = document.getElementById('security-remove-pin-btn');
  var recoveryToggle = document.getElementById('security-recovery-logo-toggle');
  var sessionsList = document.getElementById('security-sessions-list');

  var MODE_DESCRIPTIONS = {
    A: 'Open — anyone with the link can use the device fully.',
    B: 'Protected — everyone can browse and control; delete requires PIN.',
    C: 'Locked — PIN required to open Settings, Library, Manage, Lab, Add.'
  };

  function authHeaders() {
    return window.VernisLockGuard ? window.VernisLockGuard.authHeaders() : {};
  }

  function refresh() {
    fetch('/api/security/config').then(function (r) { return r.json(); }).then(function (cfg) {
      Array.prototype.forEach.call(modeSelector.querySelectorAll('.mode-option'), function (b) {
        b.classList.toggle('active', b.dataset.mode === cfg.mode);
      });
      modeHint.textContent = MODE_DESCRIPTIONS[cfg.mode] || '';
      setBtn.style.display = cfg.has_pin ? 'none' : '';
      changeBtn.style.display = cfg.has_pin ? '' : 'none';
      removeBtn.style.display = cfg.has_pin ? '' : 'none';
      recoveryToggle.checked = !!cfg.recovery_logo_enabled;
      refreshSessions();
    });
  }

  function refreshSessions() {
    fetch('/api/security/sessions', { headers: authHeaders() })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (items) {
        // Clear list using DOM methods (not innerHTML).
        while (sessionsList.firstChild) sessionsList.removeChild(sessionsList.firstChild);
        items.forEach(function (s) {
          var li = document.createElement('li');
          var when = new Date(s.created_at * 1000).toLocaleString();
          var label = document.createElement('span');
          // textContent is safe — IP and UA come from request headers but
          // we render as text, never as HTML.
          label.textContent = (s.ua || 'browser') + ' · ' + s.ip + ' · ' + when;
          var revoke = document.createElement('button');
          revoke.className = 'btn btn-secondary';
          revoke.dataset.revoke = s.token_id;
          revoke.textContent = 'Revoke';
          li.appendChild(label);
          li.appendChild(revoke);
          sessionsList.appendChild(li);
        });
      });
  }

  modeSelector.addEventListener('click', function (e) {
    var btn = e.target.closest('.mode-option');
    if (!btn) return;
    var newMode = btn.dataset.mode;
    fetch('/api/security/mode', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
      body: JSON.stringify({ mode: newMode })
    }).then(function (r) {
      if (r.status === 400) {
        return r.json().then(function (d) {
          if (d.error === 'set_pin_first') promptSetPin();
        });
      }
      if (r.status === 401) showError('Enter PIN to change mode.');
      refresh();
    });
  });

  function promptSetPin() {
    var ownerPwd = prompt('Enter your device password to set a PIN:');
    if (!ownerPwd) return;
    var pin = prompt('Choose a 6-digit PIN:');
    if (!/^\d{6}$/.test(pin || '')) {
      showError('PIN must be 6 digits.');
      return;
    }
    fetch('/api/security/recover', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ owner_password: ownerPwd, new_pin: pin })
    }).then(function (r) {
      if (r.ok) {
        return r.json().then(function (d) {
          if (d.token && window.VernisLockGuard) {
            window.VernisLockGuard.storeSession(d.token, d.expires_at);
          }
          showSuccess('PIN set.');
          refresh();
        });
      }
      showError('Could not set PIN. Check device password.');
    });
  }

  function promptChangePin() {
    var cur = prompt('Current PIN:');
    var nxt = prompt('New 6-digit PIN:');
    if (!/^\d{6}$/.test(cur || '') || !/^\d{6}$/.test(nxt || '')) return;
    fetch('/api/security/pin', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
      body: JSON.stringify({ current_pin: cur, new_pin: nxt })
    }).then(function (r) {
      if (r.ok) showSuccess('PIN changed.');
      else showError('Wrong current PIN.');
      refresh();
    });
  }

  function promptRemovePin() {
    var cur = prompt('Current PIN to remove:');
    if (!/^\d{6}$/.test(cur || '')) return;
    fetch('/api/security/pin', {
      method: 'DELETE',
      headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
      body: JSON.stringify({ current_pin: cur })
    }).then(function (r) {
      if (r.ok) showSuccess('PIN removed.');
      else showError('Wrong PIN.');
      refresh();
    });
  }

  setBtn.addEventListener('click', promptSetPin);
  changeBtn.addEventListener('click', promptChangePin);
  removeBtn.addEventListener('click', promptRemovePin);

  sessionsList.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-revoke]');
    if (!btn) return;
    fetch('/api/security/sessions/' + encodeURIComponent(btn.dataset.revoke), {
      method: 'DELETE',
      headers: authHeaders()
    }).then(refreshSessions);
  });

  refresh();
})();
```

- [ ] **Step 4: Add minimal CSS for the mode selector**

Append to `vernis-themes.css`:

```css
/* Security mode selector (settings.html) */
.mode-selector {
  display: inline-flex;
  border: 1px solid var(--border-light);
  border-radius: 12px;
  overflow: hidden;
}
.mode-selector .mode-option {
  padding: 10px 18px;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border: none;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}
.mode-selector .mode-option.active {
  background: var(--accent-primary);
  color: #fff;
}

#security-sessions-list {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
}
#security-sessions-list li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-light);
  font-size: 13px;
}
```

- [ ] **Step 5: Commit**

```bash
git add settings.html vernis-themes.css
git commit -m "frontend: Security section in Settings"
```

---

## Phase 6 — Logo long-press recovery & scripts

### Task 25: Long-press logo handler with progress ring

**Files:**
- Create: `vernis-logo-longpress.js`
- Modify: `vernis-themes.css` (add keyframes)
- Modify: `index.html`, `settings.html`, `library.html`, `manage.html`, `lab.html`, `add.html` (load script)

- [ ] **Step 1: Add CSS keyframes for the ring**

Append to `vernis-themes.css`:

```css
/* Logo long-press recovery ring */
.vlp-ring-host {
  position: relative;
  display: inline-block;
}
.vlp-ring {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 110%;
  aspect-ratio: 1 / 1;
  border-radius: 50%;
  pointer-events: none;
  opacity: 0;
  transition: opacity 200ms ease;
  background: conic-gradient(var(--accent-primary) 0deg, transparent 0deg);
}
.vlp-ring.active { opacity: 0.8; }
@keyframes vlpPulse {
  0%, 100% { transform: translate(-50%, -50%) scale(1); }
  50% { transform: translate(-50%, -50%) scale(1.02); }
}
.vlp-logo-pulsing { animation: vlpPulse 1s ease-in-out infinite; }
```

- [ ] **Step 2: Create vernis-logo-longpress.js using safe DOM methods**

Create `vernis-logo-longpress.js`:

```javascript
/* Vernis Logo Long-Press — 5-second hold opens PIN recovery.
 * Auto-attaches to .kiosk-logo on the current page.
 */
(function () {
  'use strict';

  var DURATION_MS = 5000;
  var STARTUP_DELAY_MS = 1000;

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'style') node.style.cssText = attrs[k];
      else if (k === 'class') node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    if (children) children.forEach(function (c) { node.appendChild(c); });
    return node;
  }

  function buildRing(host) {
    var wrap = document.createElement('span');
    wrap.className = 'vlp-ring-host';
    host.parentNode.insertBefore(wrap, host);
    wrap.appendChild(host);
    var ring = document.createElement('span');
    ring.className = 'vlp-ring';
    wrap.appendChild(ring);
    return ring;
  }

  function attach(logoEl) {
    if (!logoEl || logoEl.dataset.vlpAttached) return;
    logoEl.dataset.vlpAttached = '1';
    var ring = buildRing(logoEl);
    var startTs = 0;
    var raf = 0;
    var ringActive = false;

    function tick() {
      var elapsed = Date.now() - startTs;
      if (elapsed >= STARTUP_DELAY_MS && !ringActive) {
        ring.classList.add('active');
        logoEl.classList.add('vlp-logo-pulsing');
        ringActive = true;
      }
      if (ringActive) {
        var progress = Math.min(1,
          (elapsed - STARTUP_DELAY_MS) / (DURATION_MS - STARTUP_DELAY_MS));
        var deg = Math.round(360 * progress);
        ring.style.background =
          'conic-gradient(var(--accent-primary) ' + deg +
          'deg, transparent ' + deg + 'deg)';
        if (elapsed >= DURATION_MS) { finish(); return; }
      }
      raf = requestAnimationFrame(tick);
    }

    function start(ev) {
      if (ev.cancelable) ev.preventDefault();
      startTs = Date.now();
      raf = requestAnimationFrame(tick);
    }

    function cancel() {
      cancelAnimationFrame(raf);
      ring.classList.remove('active');
      logoEl.classList.remove('vlp-logo-pulsing');
      ring.style.background = '';
      ringActive = false;
      startTs = 0;
    }

    function finish() { cancel(); openRecoveryModal(); }

    logoEl.addEventListener('pointerdown', start);
    logoEl.addEventListener('pointerup', cancel);
    logoEl.addEventListener('pointerleave', cancel);
    logoEl.addEventListener('pointercancel', cancel);
  }

  var INPUT_STYLE_PWD =
    'width:100%;padding:12px;border-radius:12px;border:1px solid var(--border-light);' +
    'background:var(--bg-tertiary);color:var(--text-primary);margin-bottom:12px;';
  var INPUT_STYLE_PIN =
    'width:100%;padding:12px;border-radius:12px;border:1px solid var(--border-light);' +
    'background:var(--bg-tertiary);color:var(--text-primary);margin-bottom:16px;' +
    'font-size:24px;letter-spacing:8px;text-align:center;';
  var STATUS_STYLE = 'margin-top:12px;font-size:13px;color:var(--text-muted);';
  var SUBMIT_STYLE = 'background:var(--accent-primary);color:#fff;';
  var LABEL_STYLE =
    'display:block;text-align:left;font-size:13px;' +
    'color:var(--text-muted);margin-bottom:6px;';

  function buildModal() {
    var msg = el('div', { class: 'vernis-confirm-message',
      text: 'Reset PIN — enter device password' });
    var pwd = el('input', { type: 'password', id: 'vlp-pwd',
      autocomplete: 'off', style: INPUT_STYLE_PWD });
    var label = el('label', { style: LABEL_STYLE,
      text: 'New PIN (leave empty to clear PIN entirely)' });
    var newpin = el('input', { type: 'password', inputmode: 'numeric',
      pattern: '\\d{6}', maxlength: '6', id: 'vlp-newpin',
      style: INPUT_STYLE_PIN });
    var cancel = el('button', { class: 'vernis-confirm-btn vernis-confirm-cancel',
      id: 'vlp-cancel', text: 'Cancel' });
    var submit = el('button', { class: 'vernis-confirm-btn',
      id: 'vlp-submit', style: SUBMIT_STYLE, text: 'Reset' });
    var actions = el('div', { class: 'vernis-confirm-actions' },
      [cancel, submit]);
    var status = el('div', { id: 'vlp-status', style: STATUS_STYLE });
    var modal = el('div', { class: 'vernis-confirm-modal' },
      [msg, pwd, label, newpin, actions, status]);
    var overlay = el('div', { class: 'vernis-confirm-overlay active',
      style: 'z-index:99999;' }, [modal]);
    return { overlay: overlay, pwd: pwd, newpin: newpin,
      submit: submit, cancel: cancel, status: status };
  }

  function openRecoveryModal() {
    var parts = buildModal();
    document.body.appendChild(parts.overlay);
    parts.pwd.focus();

    function trySubmit() {
      var payload = { owner_password: parts.pwd.value };
      if (parts.newpin.value) {
        if (!/^\d{6}$/.test(parts.newpin.value)) {
          parts.status.textContent = 'PIN must be 6 digits.';
          return;
        }
        payload.new_pin = parts.newpin.value;
      }
      parts.submit.disabled = true;
      parts.status.textContent = 'Resetting…';
      fetch('/api/security/recover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).then(function (r) {
        return r.json().then(function (d) { return { status: r.status, data: d }; });
      }).then(function (res) {
        if (res.status === 200) {
          if (res.data.token && window.VernisLockGuard) {
            window.VernisLockGuard.storeSession(res.data.token, res.data.expires_at);
          }
          parts.overlay.remove();
          window.location.reload();
        } else if (res.status === 429) {
          parts.status.textContent = 'Try again in ' + res.data.retry_after + ' s.';
          parts.submit.disabled = false;
        } else {
          parts.status.textContent = 'Wrong password.';
          parts.submit.disabled = false;
        }
      }).catch(function () {
        parts.status.textContent = 'Network error.';
        parts.submit.disabled = false;
      });
    }

    parts.submit.addEventListener('click', trySubmit);
    parts.cancel.addEventListener('click', function () { parts.overlay.remove(); });
  }

  window.VernisLogoLongPress = { attach: attach, openRecoveryModal: openRecoveryModal };

  function autoAttach() {
    var logo = document.querySelector('.kiosk-logo');
    if (logo) attach(logo);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoAttach);
  } else {
    autoAttach();
  }
})();
```

- [ ] **Step 3: Include the script in all relevant pages**

In `index.html`, `settings.html`, `library.html`, `manage.html`, `lab.html`, `add.html`, before `</body>` (or near the other `<script>` tags), add:

```html
<script src="/vernis-logo-longpress.js"></script>
```

- [ ] **Step 4: Verify syntax**

Run: `node -c vernis-logo-longpress.js`
Expected: no output.

- [ ] **Step 5: Smoke test in browser**

Manual:
1. Open `index.html` in a browser.
2. Press-and-hold the VERNIS logo.
3. After ~1 s the ring should start drawing.
4. Hold to 5 s — recovery modal opens.
5. Release before 5 s — ring fades, no modal.

- [ ] **Step 6: Commit**

```bash
git add vernis-logo-longpress.js vernis-themes.css index.html settings.html library.html manage.html lab.html add.html
git commit -m "frontend: 5-second logo long-press opens PIN recovery"
```

### Task 26: SSH reset script

**Files:**
- Create: `scripts/reset-pin.sh`

- [ ] **Step 1: Write the script**

Create `scripts/reset-pin.sh`:

```bash
#!/bin/bash
# Vernis — emergency PIN reset.
# Wipes the PIN, drops to Mode A, revokes all sessions, preserves
# owner_pwd_hash, reloads Flask.
#
# Usage: sudo /opt/vernis/scripts/reset-pin.sh

set -e

CONFIG_FILE="/opt/vernis/security.json"
SESSIONS_FILE="/opt/vernis/security-sessions.json"
FAILURES_FILE="/opt/vernis/security-failures.json"
AUDIT_LOG="/opt/vernis/audit.log"

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root (use sudo)." >&2
    exit 1
fi

echo "This will wipe the PIN and unlock the device. Continue? [y/N]"
read -r CONFIRM
if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
    echo "Aborted."
    exit 0
fi

OWNER_HASH=""
if [ -f "$CONFIG_FILE" ]; then
    OWNER_HASH=$(python3 -c "
import json
try:
    with open('$CONFIG_FILE') as f:
        d = json.load(f)
    print(d.get('owner_pwd_hash') or '')
except Exception:
    print('')
")
fi

NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
cat > "$CONFIG_FILE" <<EOF
{
  "version": 1,
  "mode": "A",
  "pin_hash": null,
  "owner_pwd_hash": $([ -n "$OWNER_HASH" ] && echo "\"$OWNER_HASH\"" || echo "null"),
  "recovery_logo_enabled": true,
  "created_at": "$NOW"
}
EOF
chmod 0600 "$CONFIG_FILE"

echo "{}" > "$SESSIONS_FILE"
chmod 0600 "$SESSIONS_FILE"
echo '{"by_ip": {}, "global": [], "hard_locked_at": null}' > "$FAILURES_FILE"
chmod 0600 "$FAILURES_FILE"

echo "{\"ts\":\"$NOW\",\"ip\":\"localhost\",\"action\":\"recovery_ssh\",\"result\":\"ok\"}" >> "$AUDIT_LOG"

systemctl reload vernis-api 2>/dev/null || systemctl restart vernis-api

echo "PIN cleared. Mode set to Open."
```

- [ ] **Step 2: Make executable, verify syntax**

Run: `chmod +x scripts/reset-pin.sh && bash -n scripts/reset-pin.sh`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add scripts/reset-pin.sh
git commit -m "scripts: reset-pin.sh — SSH emergency PIN reset"
```

### Task 27: Owner-password sync script

**Files:**
- Create: `scripts/update-owner-password.sh`

- [ ] **Step 1: Write the script**

Create `scripts/update-owner-password.sh`:

```bash
#!/bin/bash
# Vernis — re-sync owner_pwd_hash after changing the device password
# via `passwd` (NOT through the Settings UI).
#
# Usage: sudo /opt/vernis/scripts/update-owner-password.sh

set -e

CONFIG_FILE="/opt/vernis/security.json"

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root (use sudo)." >&2
    exit 1
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "$CONFIG_FILE does not exist; nothing to update." >&2
    exit 1
fi

echo -n "Enter the new device password: "
read -rs NEW_PWD
echo

if [ -z "$NEW_PWD" ]; then
    echo "Aborted: empty password." >&2
    exit 1
fi

NEW_PWD="$NEW_PWD" python3 - <<'PYEOF'
import bcrypt, json, os
pwd = os.environ["NEW_PWD"]
path = "/opt/vernis/security.json"
with open(path) as f:
    cfg = json.load(f)
cfg["owner_pwd_hash"] = bcrypt.hashpw(
    pwd.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(cfg, f, indent=2)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
print("owner_pwd_hash updated.")
PYEOF

systemctl reload vernis-api 2>/dev/null || systemctl restart vernis-api
echo "Done."
```

- [ ] **Step 2: Make executable, verify syntax**

Run: `chmod +x scripts/update-owner-password.sh && bash -n scripts/update-owner-password.sh`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add scripts/update-owner-password.sh
git commit -m "scripts: update-owner-password.sh — re-sync recovery hash"
```

---

## Phase 7 — Install/migration & documentation

### Task 28: Initialize security.json on install

**Files:**
- Modify: `scripts/install-vernis.sh`

- [ ] **Step 1: Add init logic after `/opt/vernis` is set up**

In `scripts/install-vernis.sh`, find the line that creates `/opt/vernis` (search `grep -n 'mkdir.*opt/vernis' scripts/install-vernis.sh`). After that line, insert:

```bash
# Initialize Vernis security config if missing
SECURITY_FILE="/opt/vernis/security.json"
if [ ! -f "$SECURITY_FILE" ]; then
    NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    OWNER_HASH=$(python3 - <<PYEOF
import bcrypt, os
pwd = os.environ.get("INSTALL_USER_PASSWORD", "")
if not pwd:
    print("")
else:
    print(bcrypt.hashpw(pwd.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8"))
PYEOF
)
    sudo tee "$SECURITY_FILE" > /dev/null <<EOF
{
  "version": 1,
  "mode": "A",
  "pin_hash": null,
  "owner_pwd_hash": $([ -n "$OWNER_HASH" ] && echo "\"$OWNER_HASH\"" || echo "null"),
  "recovery_logo_enabled": true,
  "created_at": "$NOW"
}
EOF
    sudo chmod 0600 "$SECURITY_FILE"

    sudo touch /opt/vernis/audit.log
    sudo chmod 0640 /opt/vernis/audit.log

    echo "{}" | sudo tee /opt/vernis/security-sessions.json > /dev/null
    sudo chmod 0600 /opt/vernis/security-sessions.json

    echo '{"by_ip": {}, "global": [], "hard_locked_at": null}' \
        | sudo tee /opt/vernis/security-failures.json > /dev/null
    sudo chmod 0600 /opt/vernis/security-failures.json
fi
```

The operator sets `INSTALL_USER_PASSWORD` before running install, e.g.:

```bash
INSTALL_USER_PASSWORD='<device-password>' sudo -E bash install-vernis.sh
```

If unset, the install proceeds with `owner_pwd_hash` null and the operator can run `update-owner-password.sh` later.

- [ ] **Step 2: Verify shell syntax**

Run: `bash -n scripts/install-vernis.sh`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add scripts/install-vernis.sh
git commit -m "install: initialize security.json with owner_pwd_hash"
```

### Task 29: Migration helper for existing field devices

**Files:**
- Create: `scripts/migrate-security-init.sh`

- [ ] **Step 1: Write the migration script**

Create `scripts/migrate-security-init.sh`:

```bash
#!/bin/bash
# Vernis — one-time migration for already-deployed devices.
# Idempotent: safe to run multiple times.
#
# Usage:
#   INSTALL_USER_PASSWORD='<device pwd>' sudo -E bash /opt/vernis/scripts/migrate-security-init.sh

set -e

SECURITY_FILE="/opt/vernis/security.json"

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root (use sudo)." >&2
    exit 1
fi

if [ -f "$SECURITY_FILE" ]; then
    echo "security.json already exists; nothing to do."
    exit 0
fi

PWD_VAR="${INSTALL_USER_PASSWORD:-}"
if [ -z "$PWD_VAR" ]; then
    echo "Set INSTALL_USER_PASSWORD env var first." >&2
    exit 1
fi

# Ensure bcrypt is installed
pip3 show bcrypt > /dev/null 2>&1 || pip3 install bcrypt --break-system-packages

NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
OWNER_HASH=$(INSTALL_USER_PASSWORD="$PWD_VAR" python3 - <<'PYEOF'
import bcrypt, os
pwd = os.environ["INSTALL_USER_PASSWORD"]
print(bcrypt.hashpw(pwd.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8"))
PYEOF
)

cat > "$SECURITY_FILE" <<EOF
{
  "version": 1,
  "mode": "A",
  "pin_hash": null,
  "owner_pwd_hash": "$OWNER_HASH",
  "recovery_logo_enabled": true,
  "created_at": "$NOW"
}
EOF
chmod 0600 "$SECURITY_FILE"

touch /opt/vernis/audit.log; chmod 0640 /opt/vernis/audit.log
echo "{}" > /opt/vernis/security-sessions.json
chmod 0600 /opt/vernis/security-sessions.json
echo '{"by_ip": {}, "global": [], "hard_locked_at": null}' > /opt/vernis/security-failures.json
chmod 0600 /opt/vernis/security-failures.json

systemctl restart vernis-api
systemctl reload caddy

echo "Migration complete. Device runs in Mode A — no behavior change."
echo "To enable PIN: visit Settings → Security."
```

- [ ] **Step 2: Make executable, verify syntax**

Run: `chmod +x scripts/migrate-security-init.sh && bash -n scripts/migrate-security-init.sh`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate-security-init.sh
git commit -m "scripts: one-time migration for already-deployed devices"
```

### Task 30: Documentation updates

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Append Security section to README.md**

Append to `README.md`:

```markdown
## Security

Vernis has three access-control modes selectable from Settings → Security:

- **Open** — default. Anyone with the link can use the device fully.
- **Protected** — anyone can browse and control; **deleting** files/libraries/carousels requires a PIN.
- **Locked** — PIN required to open Settings/Library/Manage/Lab/Add. The home page (gallery + connect QR) stays viewable.

The PIN is 6 digits, bcrypt-hashed server-side. Your browser remembers a session for 30 days so you don't re-enter the PIN constantly.

### Setting up a PIN

1. Open Settings → Security
2. Click **Set PIN**
3. Enter your device password and choose a 6-digit PIN
4. Pick a mode (Protected or Locked) when you're ready

### Forgot your PIN?

Two recovery paths:

1. **Hold the VERNIS logo for 5 seconds** on the home page or PIN entry screen. A modal asks for your device password. Enter it, optionally set a new PIN, and you're back in.
2. **SSH into the Pi** and run `sudo /opt/vernis/scripts/reset-pin.sh` to wipe the PIN and drop back to Open mode.

### Changed your device password via `passwd`?

If you change your Linux password via `passwd` over SSH (instead of through Settings), the recovery hash goes stale. Re-sync it:

```bash
sudo /opt/vernis/scripts/update-owner-password.sh
```

Settings → Security → Change Password keeps everything in sync automatically.
```

- [ ] **Step 2: Append Security section to CLAUDE.md**

Append to `CLAUDE.md`:

```markdown
## Security — PIN, Modes, Recovery (2026-05-15)

Three modes in Settings → Security: **A — Open**, **B — Protected** (PIN gates deletes), **C — Locked** (PIN gates control + delete; home view stays open).

### Files
- `/opt/vernis/security.json` — config (mode, bcrypt PIN hash, owner password hash)
- `/opt/vernis/security-sessions.json` — active session tokens
- `/opt/vernis/security-failures.json` — per-IP and global lockout counters
- `/opt/vernis/audit.log` — JSON-lines audit log (rotates at 10 MB)

### Recovery
- **SSH:** `sudo /opt/vernis/scripts/reset-pin.sh`
- **Logo long-press:** hold `.kiosk-logo` for 5 s → enter device password.

### After changing device password via passwd
Run `sudo /opt/vernis/scripts/update-owner-password.sh` to re-sync the recovery hash.

### Reverse-proxy trust
Caddy forwards real client IPs via `X-Forwarded-For` (`trusted_proxies static private_ranges`). Flask reads them via `ProxyFix(x_for=1)`. The kiosk on the Pi is identified by `127.0.0.1` and is always trusted.
```

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: security section in README and CLAUDE.md"
```

### Task 31: Final integration pass & cleanup

**Files:**
- All test files

- [ ] **Step 1: Run the entire test suite**

Run: `python3 -m pytest tests/ -v`
Expected: every test PASS. If any fail, fix before continuing.

- [ ] **Step 2: Manual sanity check via curl**

With Flask running on localhost:

```bash
# Should report mode A, no PIN
curl localhost:5000/api/security/config

# Set up PIN (needs owner_pwd_hash already seeded by install)
curl -X POST localhost:5000/api/security/recover \
  -H 'Content-Type: application/json' \
  -d '{"owner_password":"<device-pwd>","new_pin":"482919"}'

# Expect 200 with {"ok":true,"token":"...","expires_at":...}
```

Use the returned token to switch to Mode C:

```bash
curl -X POST localhost:5000/api/security/mode \
  -H 'Content-Type: application/json' \
  -H 'X-Vernis-PIN-Session: <token>' \
  -d '{"mode":"C"}'
# Expect 200 with {"mode":"C"}
```

- [ ] **Step 3: Audit-log inspection**

Run: `grep -E "pin|password|token" /opt/vernis/audit.log`
Expected: matches only in `action` field values (`pin_set`, `pin_changed`, etc.), never raw PIN/password/token values.

- [ ] **Step 4: Performance check on Pi**

Run on a real Pi:

```bash
time curl -X POST localhost:5000/api/security/login \
  -H 'Content-Type: application/json' \
  -d '{"pin":"482919"}'
```

Expected: 150–300 ms per login on Pi 4/5. If significantly slower, lower `PIN_BCRYPT_COST` to 10 in `backend/app.py`, re-run tests.

- [ ] **Step 5: Spoofing check**

Run from a non-localhost machine simulating a malicious `X-Forwarded-For`:

```bash
curl -H 'X-Forwarded-For: 127.0.0.1' http://<pi-ip>/api/security/config
```

Expected: response shows `"kiosk": false` (Caddy strips the client-supplied header before forwarding to Flask).

- [ ] **Step 6: Commit any final adjustments**

```bash
git add tests/
git commit -m "tests: final integration adjustments"
```

---

## Spec coverage check

| Spec section | Tasks |
|---|---|
| §3 three-mode model | 11, 12 |
| §4.1 Caddy proxy fix | 1, 2 |
| §4.2 Flask ProxyFix | 3 |
| §5.1 Storage layout | 6, 8, 9, 10, 28 |
| §5.2 Backend helpers | 5–12 |
| §5.3 New endpoints | 13–19 |
| §5.4 Frontend components | 21, 22, 24, 25 |
| §5.5 Endpoint catalog | 11 |
| §5.6 change-password sync | 20 |
| §6 Data flows | covered by 12, 14, 16 (integration tests) |
| §7 Brute-force | 10, 14 |
| §8 Audit log | 9 |
| §9 Edge cases | 11 (bootstrap), 12 (localhost short-circuit), individual tests |
| §10 File-by-file | all phases |
| §11 Migration | 29 |
| §12 Rollout order | matches Phase 1→7 ordering |
| §13 Testing | unit tests in each task; performance + spoofing in 31 |
| §14 Out of scope | (correctly absent) |

