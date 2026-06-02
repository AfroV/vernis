"""Integration tests for /api/security/* endpoints."""
import importlib

import pytest


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


# ============================================================
# T13: GET /api/security/config
# ============================================================
def test_config_defaults_for_fresh(fresh_app):
    client = fresh_app.app.test_client()
    r = client.get("/api/security/config",
                   environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["mode"] == "A"
    assert d["has_pin"] is False
    assert d["recovery_logo_enabled"] is True
    assert d["kiosk"] is False
    # No more hard_locked field
    assert "hard_locked" not in d
    # New fields surfaced
    assert d["attempts_count"] == 0
    assert d["next_cooldown"] == 0
    assert "days_since_setup" in d


def test_config_kiosk_flag_for_localhost(fresh_app):
    client = fresh_app.app.test_client()
    r = client.get("/api/security/config",
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.get_json()["kiosk"] is True


def test_config_locked_until_during_cooldown(fresh_app):
    client = fresh_app.app.test_client()
    # 7 failures puts us into the 30 s tier
    for _ in range(7):
        fresh_app.record_failure("10.0.0.42")
    r = client.get("/api/security/config",
                   environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    d = r.get_json()
    assert d["locked_until"] is not None
    assert d["locked_until"] > 0
    assert d["attempts_count"] == 7


def test_config_next_cooldown_warns_before_tier_jump(fresh_app):
    """After 6 failures, next_cooldown should report 30 (the cooldown
    that triggers on attempt #7)."""
    client = fresh_app.app.test_client()
    for _ in range(6):
        fresh_app.record_failure("10.0.0.42")
    r = client.get("/api/security/config",
                   environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    d = r.get_json()
    assert d["next_cooldown"] == 30
    assert d["locked_until"] is None  # still free this attempt


# ============================================================
# T14: POST /api/security/login
# ============================================================
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
    """7 wrong attempts → next request returns 429 with retry hint."""
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    for _ in range(7):
        c.post("/api/security/login", json={"pin": "000000"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    r = c.post("/api/security/login", json={"pin": "123456"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    body = r.get_json()
    assert body["attempts_count"] == 7
    assert body["next_cooldown"] == 30


def test_login_401_includes_counters(fresh_app):
    """Failed login response exposes attempts_count + next_cooldown."""
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/login", json={"pin": "000000"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 401
    body = r.get_json()
    assert body["error"] == "invalid_pin"
    assert body["attempts_count"] == 1
    # 1 failure; 2nd would still be free
    assert body["next_cooldown"] == 0
    assert body["cooldown_remaining"] == 0


def test_login_no_longer_returns_423_anywhere(fresh_app):
    """The hard-lock concept is gone — no path should return 423."""
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    # Spam many failures across many IPs — must never hit 423.
    for i in range(40):
        ip = "10.0.0.{}".format(i)
        for _ in range(5):
            r = c.post("/api/security/login", json={"pin": "000000"},
                       environ_overrides={"REMOTE_ADDR": ip})
            assert r.status_code != 423


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


# ============================================================
# T15: POST /api/security/logout
# ============================================================
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


# ============================================================
# T16: POST /api/security/recover (initial setup + recovery)
# ============================================================
def test_recover_sets_initial_pin(fresh_app):
    _set_owner_password(fresh_app, "test-password")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/recover",
               json={"owner_password": "test-password", "new_pin": "482919"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and "token" in d
    assert fresh_app.load_security_config()["pin_hash"] is not None


def test_recover_rejects_wrong_password(fresh_app):
    _set_owner_password(fresh_app, "test-password")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/recover",
               json={"owner_password": "wrong", "new_pin": "482919"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 401


def test_recover_no_new_pin_drops_to_a(fresh_app):
    _set_owner_password(fresh_app, "test-password")
    cfg = fresh_app.load_security_config()
    cfg["pin_hash"] = fresh_app.hash_pin("123456")
    cfg["mode"] = "C"
    fresh_app.save_security_config(cfg)
    c = fresh_app.app.test_client()
    r = c.post("/api/security/recover",
               json={"owner_password": "test-password"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    cfg2 = fresh_app.load_security_config()
    assert cfg2["pin_hash"] is None
    assert cfg2["mode"] == "A"


def test_recover_with_new_pin_keeps_mode(fresh_app):
    _set_owner_password(fresh_app, "test-password")
    cfg = fresh_app.load_security_config()
    cfg["pin_hash"] = fresh_app.hash_pin("123456")
    cfg["mode"] = "B"
    fresh_app.save_security_config(cfg)
    c = fresh_app.app.test_client()
    r = c.post("/api/security/recover",
               json={"owner_password": "test-password", "new_pin": "777777"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    cfg2 = fresh_app.load_security_config()
    assert fresh_app.verify_pin("777777", cfg2["pin_hash"]) is True
    assert cfg2["mode"] == "B"


def test_recover_revokes_other_sessions(fresh_app):
    _set_owner_password(fresh_app, "test-password")
    s = fresh_app.issue_session("10.0.0.50", "old")
    c = fresh_app.app.test_client()
    c.post("/api/security/recover",
           json={"owner_password": "test-password", "new_pin": "111111"},
           environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    ok, _ = fresh_app.validate_session(s["token"])
    assert ok is False


# ============================================================
# T17: POST and DELETE /api/security/pin
# ============================================================
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


# ============================================================
# T18: POST /api/security/mode
# ============================================================
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


# ============================================================
# T19: GET/DELETE /api/security/sessions + GET /api/security/audit
# ============================================================
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


# ============================================================
# Permanent sessions: "Trust this browser until I sign out"
# ============================================================
def test_login_with_trust_until_signout_issues_permanent_session(fresh_app):
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/login",
               json={"pin": "123456", "trust_until_signout": True},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["permanent"] is True
    assert d["expires_at"] is None


def test_default_login_is_non_permanent(fresh_app):
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    r = c.post("/api/security/login", json={"pin": "123456"},
               environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    d = r.get_json()
    assert d["permanent"] is False
    assert d["expires_at"] is not None
    assert d["expires_at"] > 0


def test_list_sessions_surfaces_permanent_flag(fresh_app):
    _set_pin(fresh_app, "123456")
    a = fresh_app.issue_session("10.0.0.42", "iOS")
    b = fresh_app.issue_session("10.0.0.99", "Mac", permanent=True)
    c = fresh_app.app.test_client()
    r = c.get("/api/security/sessions",
              headers={"X-Vernis-PIN-Session": a["token"]},
              environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    items = r.get_json()
    perm = [s for s in items if s["permanent"]]
    non_perm = [s for s in items if not s["permanent"]]
    assert len(perm) == 1 and perm[0]["ip"] == "10.0.0.99"
    assert len(non_perm) == 1 and non_perm[0]["ip"] == "10.0.0.42"


# ============================================================
# Sign out everyone else
# ============================================================
def test_revoke_others_keeps_current_session(fresh_app):
    _set_pin(fresh_app, "123456")
    current = fresh_app.issue_session("10.0.0.42", "current")
    fresh_app.issue_session("10.0.0.99", "other-1")
    fresh_app.issue_session("10.0.0.50", "other-2", permanent=True)
    c = fresh_app.app.test_client()
    r = c.delete("/api/security/sessions/others",
                 headers={"X-Vernis-PIN-Session": current["token"]},
                 environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["removed"] == 2
    # Current session still works
    ok, _ = fresh_app.validate_session(current["token"])
    assert ok is True
    # Others are gone
    items = fresh_app.list_sessions()
    assert len(items) == 1


def test_revoke_others_requires_session(fresh_app):
    _set_pin(fresh_app, "123456")
    c = fresh_app.app.test_client()
    r = c.delete("/api/security/sessions/others",
                 environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 401
