"""Verify /api/setup/change-password also updates owner_pwd_hash."""
import importlib

import pytest


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
