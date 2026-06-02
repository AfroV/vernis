"""Tests for security.json load/save."""
import importlib
import os

import pytest


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
