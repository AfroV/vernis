"""Integration tests for the new before_request hook."""
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


def _set_mode(app_mod, mode, has_pin=True):
    cfg = app_mod._security_config_defaults()
    cfg["mode"] = mode
    if has_pin:
        cfg["pin_hash"] = app_mod.hash_pin("123456")
    app_mod.save_security_config(cfg)


def test_mode_a_allows_delete_without_pin(fresh_app):
    _set_mode(fresh_app, "A", has_pin=False)
    client = fresh_app.app.test_client()
    r = client.post(
        "/api/nft-delete",
        json={"filenames": []},
        environ_overrides={"REMOTE_ADDR": "10.0.0.42"},
    )
    assert r.status_code not in (401, 403, 429)


def test_mode_b_blocks_delete_without_session(fresh_app):
    _set_mode(fresh_app, "B")
    client = fresh_app.app.test_client()
    r = client.post(
        "/api/nft-delete",
        json={"filenames": []},
        environ_overrides={"REMOTE_ADDR": "10.0.0.42"},
    )
    assert r.status_code == 401
    assert r.get_json().get("error") == "pin_required"


def test_mode_b_allows_control(fresh_app):
    _set_mode(fresh_app, "B")
    client = fresh_app.app.test_client()
    r = client.post(
        "/api/theme",
        json={"style": "walnut"},
        environ_overrides={"REMOTE_ADDR": "10.0.0.42"},
    )
    assert r.status_code not in (401, 403, 429)


def test_mode_c_blocks_control(fresh_app):
    _set_mode(fresh_app, "C")
    client = fresh_app.app.test_client()
    r = client.post(
        "/api/theme",
        json={"style": "walnut"},
        environ_overrides={"REMOTE_ADDR": "10.0.0.42"},
    )
    assert r.status_code == 401


def test_mode_c_allows_localhost(fresh_app):
    _set_mode(fresh_app, "C")
    client = fresh_app.app.test_client()
    r = client.post(
        "/api/theme",
        json={"style": "walnut"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert r.status_code not in (401, 403, 429)


def test_session_unlocks_delete_in_b(fresh_app):
    _set_mode(fresh_app, "B")
    s = fresh_app.issue_session("10.0.0.42", "test")
    client = fresh_app.app.test_client()
    r = client.post(
        "/api/nft-delete",
        json={"filenames": []},
        headers={"X-Vernis-PIN-Session": s["token"]},
        environ_overrides={"REMOTE_ADDR": "10.0.0.42"},
    )
    assert r.status_code not in (401, 403, 429)


def test_get_always_allowed(fresh_app):
    _set_mode(fresh_app, "C")
    client = fresh_app.app.test_client()
    r = client.get(
        "/api/version",
        environ_overrides={"REMOTE_ADDR": "10.0.0.42"},
    )
    assert r.status_code == 200
