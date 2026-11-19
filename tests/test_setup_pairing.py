"""Setup pairing: the first device password can only be set by someone who
can see the frame's screen (QR link or 6-digit code), by the frame itself, or
with the current password. Anyone else on the Wi-Fi gets nothing."""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

PHONE = {"REMOTE_ADDR": "10.0.0.42"}
INTRUDER = {"REMOTE_ADDR": "10.0.0.66"}
KIOSK = {"REMOTE_ADDR": "127.0.0.1"}


@pytest.fixture
def papp(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    for name, fn in [("SECURITY_CONFIG_FILE", "security.json"), ("SESSIONS_FILE", "sessions.json"),
                     ("FAILURES_FILE", "failures.json"), ("AUDIT_LOG_PATH", "audit.log"),
                     ("SETUP_COMPLETE_FILE", "setup-complete.json"),
                     ("PASSWORD_MARKER_FILE", "password-changed.marker")]:
        monkeypatch.setattr(app, name, tmp_path / fn)
    monkeypatch.setattr(app, "get_primary_ip", lambda: "10.0.0.7")
    calls = []

    def fake_device_password(action, password):
        calls.append((action, password))
        return password == "old-password" if action == "check" else True
    monkeypatch.setattr(app, "_device_password", fake_device_password)
    app._test_calls = calls
    return app


def _pairing(client):
    return client.get("/api/setup/pairing", environ_overrides=KIOSK).get_json()


def _set_pw(client, env, session="", **body):
    return client.post("/api/setup/change-password", json={"password": "new-password-1", **body},
                       headers={"X-Vernis-Setup-Session": session}, environ_overrides=env)


def test_only_the_frame_can_read_the_code(papp):
    c = papp.app.test_client()
    assert c.get("/api/setup/pairing", environ_overrides=PHONE).status_code == 403
    d = _pairing(c)
    assert d["active"] is True
    assert len(d["code"]) == 6 and d["code"].isdigit()
    assert d["url"].startswith("http://10.0.0.7/welcome.html?pair=")


def test_no_pairing_once_setup_is_finished(papp):
    papp.SETUP_COMPLETE_FILE.write_text("{}")
    assert _pairing(papp.app.test_client()) == {"active": False}


def test_intruder_cannot_set_first_password(papp):
    r = _set_pw(papp.app.test_client(), INTRUDER)
    assert r.status_code == 400
    assert r.get_json()["needs_pairing"] is True
    assert ("set", "new-password-1") not in papp._test_calls
    assert not papp.PASSWORD_MARKER_FILE.exists()


def test_code_pairs_once_then_sets_password(papp):
    c = papp.app.test_client()
    code = _pairing(c)["code"]
    r = c.post("/api/setup/pair", json={"code": code[:3] + " " + code[3:]}, environ_overrides=PHONE)
    session = r.get_json()["session"]
    # The code is single-use: it rotates as soon as it worked
    assert c.post("/api/setup/pair", json={"code": code}, environ_overrides=INTRUDER).status_code == 403

    r = _set_pw(c, PHONE, session=session)
    assert r.get_json() == {"success": True}
    assert ("set", "new-password-1") in papp._test_calls
    assert papp.PASSWORD_MARKER_FILE.exists()
    # The session is used up, and later changes need the current password
    r = _set_pw(c, PHONE, session=session)
    assert r.status_code == 400 and r.get_json()["needs_current"] is True
    assert "needs_pairing" not in r.get_json()


def test_qr_link_token_pairs(papp):
    c = papp.app.test_client()
    token = _pairing(c)["url"].split("pair=")[1]
    r = c.post("/api/setup/pair", json={"token": token}, environ_overrides=PHONE)
    assert r.get_json()["success"] is True
    assert c.post("/api/setup/pair", json={"token": token}, environ_overrides=PHONE).status_code == 403


def test_wrong_codes_rotate_the_code_and_lock_out(papp):
    c = papp.app.test_client()
    code = _pairing(c)["code"]
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    for _ in range(3):
        assert c.post("/api/setup/pair", json={"code": wrong}, environ_overrides=INTRUDER).status_code == 403
    assert _pairing(c)["code"] != code  # rotated after 3 misses
    for _ in range(10):
        r = c.post("/api/setup/pair", json={"code": wrong}, environ_overrides=INTRUDER)
    assert r.status_code == 429


def test_frame_itself_may_set_first_password(papp):
    assert _set_pw(papp.app.test_client(), KIOSK).get_json() == {"success": True}


def test_current_password_fallback(papp):
    c = papp.app.test_client()
    assert _set_pw(c, PHONE, current_password="guess").status_code == 403
    assert _set_pw(c, PHONE, current_password="old-password").get_json() == {"success": True}


def test_gallery_shows_code_only_when_a_phone_asks(papp):
    c = papp.app.test_client()
    assert _pairing(c)["requested"] is False
    c.post("/api/setup/pairing/request", environ_overrides=PHONE)
    assert _pairing(c)["requested"] is True


def test_helper_refuses_without_sudo():
    helper = Path(__file__).resolve().parent.parent / "scripts" / "vernis-device-password.py"
    r = subprocess.run([sys.executable, str(helper), "set"], input="x" * 10 + "\n",
                       capture_output=True, text=True)
    assert r.returncode == 2


def test_only_the_frame_gets_the_qr(papp):
    c = papp.app.test_client()
    assert c.get("/api/setup/pairing/qr", environ_overrides=PHONE).status_code == 403
    r = c.get("/api/setup/pairing/qr", environ_overrides=KIOSK)
    assert r.status_code == 200 and r.mimetype == "image/png"
