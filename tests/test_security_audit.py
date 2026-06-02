"""Audit log writer."""
import importlib
import json

import pytest


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
    fresh_app.append_audit(
        "login", result="fail", ip="x",
        pin="123456", password="test-password", token="abc",
    )
    text = fresh_app.AUDIT_LOG_PATH.read_text()
    assert "123456" not in text
    assert "test-password" not in text
    assert "abc" not in text


def test_rotates_at_threshold(fresh_app, monkeypatch):
    monkeypatch.setattr(fresh_app, "AUDIT_LOG_MAX_BYTES", 200)
    for i in range(50):
        fresh_app.append_audit("noise", what=f"x{i}")
    rotated = fresh_app.AUDIT_LOG_PATH.with_suffix(".log.1")
    assert rotated.exists()
