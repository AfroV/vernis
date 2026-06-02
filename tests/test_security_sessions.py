"""Session token issue/validate/revoke."""
import importlib
import json
import time

import pytest


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


def test_permanent_session_ignores_expiry(fresh_app):
    """A session issued with permanent=True stays valid forever."""
    s = fresh_app.issue_session("10.0.0.42", "iOS", permanent=True)
    assert s["expires_at"] is None
    assert s["permanent"] is True
    # Even with an artificially-set past expiry, it stays valid
    data = json.loads(fresh_app.SESSIONS_FILE.read_text())
    data[s["token"]]["expires_at"] = time.time() - 10000
    fresh_app.SESSIONS_FILE.write_text(json.dumps(data))
    ok, _ = fresh_app.validate_session(s["token"])
    assert ok is True


def test_list_sessions_includes_permanent_flag(fresh_app):
    a = fresh_app.issue_session("10.0.0.42", "iOS")
    b = fresh_app.issue_session("10.0.0.99", "Mac", permanent=True)
    items = fresh_app.list_sessions()
    by_ip = {it["ip"]: it for it in items}
    assert by_ip["10.0.0.42"]["permanent"] is False
    assert by_ip["10.0.0.99"]["permanent"] is True
    assert by_ip["10.0.0.99"]["expires_at"] is None


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
