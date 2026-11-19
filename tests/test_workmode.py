"""Tests for Work Mode — Claude quota pushed from the owner's Mac.

The Pi must only ever hold numbers: never the owner's Claude login, and the
push token must not leak through read endpoints that anyone on the LAN can hit.
"""
import importlib

import pytest

LAN = {"REMOTE_ADDR": "10.0.0.42"}


@pytest.fixture
def wm_app(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    monkeypatch.setattr(app, "WORKMODE_CONFIG_FILE", tmp_path / "workmode.json")
    monkeypatch.setattr(app, "WORKMODE_USAGE_FILE", tmp_path / "workmode-usage.json")
    monkeypatch.setattr(app, "SECURITY_CONFIG_FILE", tmp_path / "security.json")
    monkeypatch.setattr(app, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(app, "FAILURES_FILE", tmp_path / "failures.json")
    monkeypatch.setattr(app, "AUDIT_LOG_PATH", tmp_path / "audit.log")
    return app


def _enable(client):
    r = client.post("/api/workmode/config", json={"enabled": True}, environ_overrides=LAN)
    assert r.status_code == 200
    r = client.post("/api/workmode/push-token", json={}, environ_overrides=LAN)
    return r.get_json()["push_token"]


GOOD = {
    "five_hour": {"utilization": 13.0, "resets_at": "2026-11-17T23:00:00.304Z"},
    "seven_day": {"utilization": 7, "resets_at": "2026-11-24T05:00:00+00:00",
                  "secret_extra": "drop me"},
    "seven_day_opus": {"utilization": 2, "resets_at": "2026-11-24T05:00:00+00:00"},
    "weird": "ignored",
}


def _push(client, token, body=GOOD):
    return client.post("/api/workmode/usage", json=body,
                       headers={"Authorization": f"Bearer {token}"},
                       environ_overrides=LAN)


def test_disabled_by_default(wm_app):
    c = wm_app.app.test_client()
    r = c.get("/api/workmode/config", environ_overrides=LAN)
    assert r.get_json()["enabled"] is False


def test_get_config_never_exposes_token(wm_app):
    c = wm_app.app.test_client()
    token = _enable(c)
    assert token and len(token) >= 20
    body = c.get("/api/workmode/config", environ_overrides=LAN).get_data(as_text=True)
    assert token not in body
    assert '"enabled": true' in body.replace(":true", ": true")


def test_push_token_includes_install_command(wm_app):
    c = wm_app.app.test_client()
    token = _enable(c)
    r = c.post("/api/workmode/push-token", json={}, environ_overrides=LAN,
               base_url="http://10.0.0.49")
    d = r.get_json()
    assert d["push_token"] == token
    assert token in d["install_command"]
    assert "http://10.0.0.49/api/workmode/installer.sh" in d["install_command"]


def test_rotate_makes_new_token(wm_app):
    c = wm_app.app.test_client()
    old = _enable(c)
    new = c.post("/api/workmode/push-token", json={"rotate": True},
                 environ_overrides=LAN).get_json()["push_token"]
    assert new != old
    assert _push(c, old).status_code == 403


def test_push_stores_only_numbers(wm_app):
    c = wm_app.app.test_client()
    token = _enable(c)
    assert _push(c, token).status_code == 200
    d = c.get("/api/workmode/usage", environ_overrides=LAN).get_json()
    assert d["has_data"] is True
    assert d["windows"]["five_hour"] == {"utilization": 13.0,
                                         "resets_at": "2026-11-17T23:00:00.304Z"}
    assert "secret_extra" not in d["windows"]["seven_day"]
    assert "seven_day_opus" in d["windows"]
    assert "weird" not in d["windows"]
    assert 0 <= d["age_seconds"] < 5


def test_push_wrong_token_or_disabled_is_403(wm_app):
    c = wm_app.app.test_client()
    token = _enable(c)
    assert _push(c, "nope").status_code == 403
    assert c.post("/api/workmode/usage", json=GOOD, environ_overrides=LAN).status_code == 403
    c.post("/api/workmode/config", json={"enabled": False}, environ_overrides=LAN)
    assert _push(c, token).status_code == 403


@pytest.mark.parametrize("bad", [
    {"five_hour": {"utilization": "abc", "resets_at": "2026-11-17T23:00:00Z"}},
    {"five_hour": {"utilization": 150, "resets_at": "2026-11-17T23:00:00Z"}},
    {"five_hour": {"utilization": 10, "resets_at": "not a date"}},
    {},
])
def test_bad_push_is_400_and_keeps_old_data(wm_app, bad):
    c = wm_app.app.test_client()
    token = _enable(c)
    _push(c, token)
    assert _push(c, token, bad).status_code == 400
    d = c.get("/api/workmode/usage", environ_overrides=LAN).get_json()
    assert d["windows"]["five_hour"]["utilization"] == 13.0


def test_null_window_is_skipped_not_rejected(wm_app):
    # The API reports windows that don't apply to the plan as null.
    c = wm_app.app.test_client()
    token = _enable(c)
    body = dict(GOOD, seven_day_opus=None)
    assert _push(c, token, body).status_code == 200
    d = c.get("/api/workmode/usage", environ_overrides=LAN).get_json()
    assert "seven_day_opus" not in d["windows"]


def test_usage_empty_state(wm_app):
    c = wm_app.app.test_client()
    _enable(c)
    d = c.get("/api/workmode/usage", environ_overrides=LAN).get_json()
    assert d["has_data"] is False


def test_mode_c_push_works_without_pin_but_config_needs_it(wm_app):
    c = wm_app.app.test_client()
    token = _enable(c)
    cfg = wm_app._security_config_defaults()
    cfg["mode"] = "C"
    cfg["pin_hash"] = wm_app.hash_pin("123456")
    wm_app.save_security_config(cfg)
    assert _push(c, token).status_code == 200
    r = c.post("/api/workmode/config", json={"enabled": False}, environ_overrides=LAN)
    assert r.status_code == 401
    r = c.post("/api/workmode/push-token", json={}, environ_overrides=LAN)
    assert r.status_code == 401


def test_installer_has_url_and_no_token(wm_app):
    c = wm_app.app.test_client()
    token = _enable(c)
    r = c.get("/api/workmode/installer.sh", environ_overrides=LAN,
              base_url="http://10.0.0.49")
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert text.startswith("#!/bin/bash")
    assert "http://10.0.0.49" in text
    assert token not in text
    # Hook-based: runs Claude Code's own /usage after each reply, never reads the login
    assert "' --hook\" % (py, script)" in text
    assert "security find-generic-password" not in text
    assert "StartInterval" not in text


# --- Showing Work Mode on the frame's own screen (driven from a phone) ---

@pytest.fixture
def kiosk(wm_app, monkeypatch):
    """Fake the kiosk browser: records navigations, reports a current URL."""
    k = {"url": "http://127.0.0.1/gallery.html", "navs": []}

    def nav(url):
        k["navs"].append(url)
        k["url"] = url
        return True, None
    monkeypatch.setattr(wm_app, "navigate_browser_cdp", nav)
    monkeypatch.setattr(wm_app, "_kiosk_current_url", lambda: k["url"])
    return k


def test_show_puts_work_mode_on_the_frame(wm_app, kiosk):
    c = wm_app.app.test_client()
    _enable(c)
    r = c.post("/api/workmode/show", environ_overrides=LAN)
    assert r.status_code == 200
    assert kiosk["navs"][-1] == "http://127.0.0.1/work.html"
    assert c.get("/api/workmode/config", environ_overrides=LAN).get_json()["showing"] is True


def test_hide_returns_to_what_was_on_screen(wm_app, kiosk):
    c = wm_app.app.test_client()
    _enable(c)
    kiosk["url"] = "http://127.0.0.1/gallery.html?collection=x"
    c.post("/api/workmode/show", environ_overrides=LAN)
    r = c.post("/api/workmode/hide", environ_overrides=LAN)
    assert r.status_code == 200
    assert kiosk["navs"][-1] == "http://127.0.0.1/gallery.html?collection=x"
    assert c.get("/api/workmode/config", environ_overrides=LAN).get_json()["showing"] is False


def test_show_twice_keeps_the_original_return_page(wm_app, kiosk):
    c = wm_app.app.test_client()
    _enable(c)
    c.post("/api/workmode/show", environ_overrides=LAN)
    c.post("/api/workmode/show", environ_overrides=LAN)
    c.post("/api/workmode/hide", environ_overrides=LAN)
    assert kiosk["navs"][-1] == "http://127.0.0.1/gallery.html"


def test_return_url_must_be_local(wm_app, kiosk):
    c = wm_app.app.test_client()
    _enable(c)
    kiosk["url"] = "https://evil.example/x"
    c.post("/api/workmode/show", environ_overrides=LAN)
    c.post("/api/workmode/hide", environ_overrides=LAN)
    assert kiosk["navs"][-1].startswith("http://127.0.0.1/")


def test_show_refused_when_disabled(wm_app, kiosk):
    c = wm_app.app.test_client()
    assert c.post("/api/workmode/show", environ_overrides=LAN).status_code == 403
    assert kiosk["navs"] == []


def test_disabling_while_showing_restores_the_screen(wm_app, kiosk):
    c = wm_app.app.test_client()
    _enable(c)
    c.post("/api/workmode/show", environ_overrides=LAN)
    c.post("/api/workmode/config", json={"enabled": False}, environ_overrides=LAN)
    assert kiosk["navs"][-1] == "http://127.0.0.1/gallery.html"


def test_show_needs_pin_in_mode_c(wm_app, kiosk):
    c = wm_app.app.test_client()
    _enable(c)
    cfg = wm_app._security_config_defaults()
    cfg["mode"] = "C"
    cfg["pin_hash"] = wm_app.hash_pin("123456")
    wm_app.save_security_config(cfg)
    assert c.post("/api/workmode/show", environ_overrides=LAN).status_code == 401
    assert kiosk["navs"] == []


def test_show_reports_unreachable_display(wm_app, kiosk, monkeypatch):
    c = wm_app.app.test_client()
    _enable(c)
    monkeypatch.setattr(wm_app, "navigate_browser_cdp", lambda url: (False, "CDP not available"))
    assert c.post("/api/workmode/show", environ_overrides=LAN).status_code == 502
