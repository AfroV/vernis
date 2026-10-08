"""Tests for Preview Mode — temporary artist previews.

The property that matters most here is the negative one: a preview must never
leave anything behind in the library. Several tests assert on what did NOT
happen (no NFT_DIR write, no metadata-cache entry) rather than on return values.
"""
import importlib
import io
import json

import pytest


@pytest.fixture
def prev_app(tmp_path, monkeypatch):
    import app
    importlib.reload(app)

    monkeypatch.setattr(app, "PREVIEW_DIR", tmp_path / "preview")
    monkeypatch.setattr(app, "PREVIEW_CONFIG_FILE", tmp_path / "preview-config.json")
    monkeypatch.setattr(app, "SECURITY_CONFIG_FILE", tmp_path / "security.json")
    monkeypatch.setattr(app, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(app, "FAILURES_FILE", tmp_path / "failures.json")
    monkeypatch.setattr(app, "AUDIT_LOG_PATH", tmp_path / "audit.log")

    # Keep the library dirs pointed at the sandbox so an accidental write
    # would be visible to the tests rather than hitting the real paths.
    nft_dir = tmp_path / "nfts"
    nft_dir.mkdir()
    monkeypatch.setattr(app, "NFT_DIR", nft_dir)
    monkeypatch.setattr(app, "METADATA_CACHE_FILE", tmp_path / "nft-metadata-cache.json",
                        raising=False)

    # Never drive a real browser from a test.
    monkeypatch.setattr(app, "navigate_browser_cdp", lambda url: (True, None))
    app._preview_state.update(
        {"files": [], "index": 0, "last_seen": 0.0, "return_url": None, "showing": False}
    )
    return app


def _enable(a, ttl=1800):
    a.save_preview_config({"enabled": True, "ttl_seconds": ttl})


def _png():
    # 1x1 PNG — smallest thing that survives a real file write.
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _upload(client, name="art.png", data=None):
    return client.post(
        "/api/preview/upload",
        data={"file": (io.BytesIO(data or _png()), name)},
        content_type="multipart/form-data",
        environ_overrides={"REMOTE_ADDR": "10.0.0.42"},
    )


# ============================================================
# Feature toggle
# ============================================================
def test_disabled_by_default(prev_app):
    client = prev_app.app.test_client()
    assert client.get("/api/preview/config").get_json()["enabled"] is False


def test_upload_rejected_while_disabled(prev_app):
    client = prev_app.app.test_client()
    r = _upload(client)
    assert r.status_code == 403


def test_show_rejected_while_disabled(prev_app):
    client = prev_app.app.test_client()
    r = client.post("/api/preview/show", json={"index": 0},
                    environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 403


def test_disabling_ends_a_live_session(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app)
    _upload(client)
    client.post("/api/preview/show", json={"index": 0},
                environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert prev_app._preview_state["showing"] is True

    client.post("/api/preview/config", json={"enabled": False},
                environ_overrides={"REMOTE_ADDR": "10.0.0.42"})

    assert prev_app._preview_state["files"] == []
    assert list(prev_app.PREVIEW_DIR.iterdir()) == []


# ============================================================
# Upload behaviour
# ============================================================
def test_upload_stores_file_and_keeps_original_name(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app)
    r = _upload(client, "My Artwork.png")
    assert r.status_code == 200
    files = r.get_json()["files"]
    assert len(files) == 1
    assert files[0]["name"] == "My Artwork.png"
    # Stored name is randomized hex + ext, never the caller's string.
    assert files[0]["stored"].endswith(".png")
    assert "My" not in files[0]["stored"]
    assert (prev_app.PREVIEW_DIR / files[0]["stored"]).exists()


def test_upload_rejects_unsupported_type(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app)
    r = _upload(client, "payload.svg")
    assert r.status_code == 400
    assert "Unsupported" in r.get_json()["error"]


def test_traversal_filename_cannot_escape(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app)
    r = _upload(client, "../../../../etc/passwd.png")
    assert r.status_code == 200
    stored = r.get_json()["files"][0]["stored"]
    assert "/" not in stored and ".." not in stored
    assert (prev_app.PREVIEW_DIR / stored).exists()


def test_session_file_count_capped(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app)
    for _ in range(prev_app.PREVIEW_MAX_FILES):
        assert _upload(client).status_code == 200
    r = _upload(client)
    assert r.status_code == 400
    assert "Maximum" in r.get_json()["error"]


def test_session_size_capped(prev_app, monkeypatch):
    client = prev_app.app.test_client()
    _enable(prev_app)
    monkeypatch.setattr(prev_app, "PREVIEW_MAX_SESSION_BYTES", 512)
    r = _upload(client, "big.png", data=b"\x89PNG\r\n\x1a\n" + b"x" * 4096)
    assert r.status_code == 413
    assert "limit" in r.get_json()["error"].lower()
    # The oversized file must not survive the rejection.
    assert list(prev_app.PREVIEW_DIR.iterdir()) == []


# ============================================================
# The core guarantee: nothing reaches the library
# ============================================================
def test_preview_never_touches_the_library(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app)
    _upload(client, "secret-unreleased.png")
    client.post("/api/preview/show", json={"index": 0},
                environ_overrides={"REMOTE_ADDR": "10.0.0.42"})

    assert list(prev_app.NFT_DIR.iterdir()) == [], "preview leaked into NFT_DIR"
    cache = prev_app.PREVIEW_CONFIG_FILE.parent / "nft-metadata-cache.json"
    assert not cache.exists(), "preview created a metadata-cache entry"


def test_end_wipes_everything(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app)
    _upload(client)
    _upload(client)
    assert len(list(prev_app.PREVIEW_DIR.iterdir())) == 2

    r = client.post("/api/preview/end", environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    assert list(prev_app.PREVIEW_DIR.iterdir()) == []
    assert prev_app._preview_state["files"] == []
    assert prev_app._preview_state["showing"] is False


def test_end_works_even_when_disabled(prev_app):
    """Turning the toggle off must never strand files that are already there."""
    client = prev_app.app.test_client()
    _enable(prev_app)
    _upload(client)
    prev_app.save_preview_config({"enabled": False})
    r = client.post("/api/preview/end", environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 200
    assert list(prev_app.PREVIEW_DIR.iterdir()) == []


# ============================================================
# Idle expiry
# ============================================================
def test_status_heartbeat_extends_session(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app, ttl=100)
    _upload(client)
    prev_app._preview_state["last_seen"] = prev_app.time.time() - 50

    before = client.get("/api/preview/status").get_json()["expires_in"]
    after = client.get("/api/preview/status?heartbeat=1").get_json()["expires_in"]
    assert before < 60
    assert after > 95, "heartbeat=1 should reset the idle clock"


def test_display_poll_does_not_extend_session(prev_app):
    """preview-display.html polls without heartbeat, so a forgotten display
    alone cannot keep an abandoned session alive."""
    client = prev_app.app.test_client()
    _enable(prev_app, ttl=100)
    _upload(client)
    prev_app._preview_state["last_seen"] = prev_app.time.time() - 50

    client.get("/api/preview/status")
    assert client.get("/api/preview/status").get_json()["expires_in"] < 60


def test_expired_session_is_wiped(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app, ttl=30)
    _upload(client)
    client.post("/api/preview/show", json={"index": 0},
                environ_overrides={"REMOTE_ADDR": "10.0.0.42"})

    # Simulate the artist walking away, then run one sweep iteration's worth
    # of logic directly rather than waiting on the background thread.
    prev_app._preview_state["last_seen"] = prev_app.time.time() - 31
    prev_app._preview_reset(restore_display=True)

    assert list(prev_app.PREVIEW_DIR.iterdir()) == []
    assert prev_app._preview_state["files"] == []


# ============================================================
# File serving
# ============================================================
def test_file_serves_known_name(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app)
    stored = _upload(client).get_json()["files"][0]["stored"]
    r = client.get("/api/preview/file/" + stored)
    assert r.status_code == 200
    assert r.data == _png()


def test_file_rejects_unknown_name(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app)
    _upload(client)
    assert client.get("/api/preview/file/deadbeefdeadbeef.png").status_code == 404


def test_file_rejects_traversal(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app)
    _upload(client)
    r = client.get("/api/preview/file/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)


# ============================================================
# Show / navigation
# ============================================================
def test_show_clamps_index(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app)
    _upload(client)
    _upload(client)
    r = client.post("/api/preview/show", json={"index": 99},
                    environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.get_json()["index"] == 1


def test_show_requires_an_upload(prev_app):
    client = prev_app.app.test_client()
    _enable(prev_app)
    r = client.post("/api/preview/show", json={"index": 0},
                    environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert r.status_code == 400


def test_only_first_show_navigates(prev_app, monkeypatch):
    """Later prev/next are picked up by the display's own poll — re-navigating
    would flash the screen black between images."""
    calls = []
    monkeypatch.setattr(prev_app, "navigate_browser_cdp",
                        lambda url: (calls.append(url), (True, None))[1])
    client = prev_app.app.test_client()
    _enable(prev_app)
    _upload(client)
    _upload(client)
    for i in (0, 1, 0):
        client.post("/api/preview/show", json={"index": i},
                    environ_overrides={"REMOTE_ADDR": "10.0.0.42"})
    assert len(calls) == 1
    assert calls[0].endswith("/preview-display.html")


# ============================================================
# Mode C gating (reuses the existing before_request classifier)
# ============================================================
def test_control_endpoints_classified_as_control(prev_app):
    for path in ("/api/preview/upload", "/api/preview/show", "/api/preview/end"):
        assert prev_app.classify_endpoint(path, "POST") == "control"


def test_status_is_readable_without_a_pin(prev_app):
    assert prev_app.classify_endpoint("/api/preview/status", "GET") == "read"


def test_mode_c_blocks_upload_without_session(prev_app):
    cfg = prev_app._security_config_defaults()
    cfg["mode"] = "C"
    prev_app.save_security_config(cfg)
    _enable(prev_app)
    client = prev_app.app.test_client()
    r = _upload(client)
    assert r.status_code == 401
    assert r.get_json()["error"] == "pin_required"


def test_kiosk_localhost_always_allowed(prev_app):
    cfg = prev_app._security_config_defaults()
    cfg["mode"] = "C"
    prev_app.save_security_config(cfg)
    _enable(prev_app)
    client = prev_app.app.test_client()
    r = client.post(
        "/api/preview/upload",
        data={"file": (io.BytesIO(_png()), "a.png")},
        content_type="multipart/form-data",
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert r.status_code == 200


# ============================================================
# Size-limit enforcement (regression: mp4 uploads)
#
# The limits were originally enforced too late — after the client had
# committed to sending and after the bytes had already been written to
# tmpfs. On a Pi that tmpfs is RAM, and the caller got either a raw
# Werkzeug exception string or an aborted connection.
# ============================================================
def test_oversized_file_never_lands_on_disk(prev_app, monkeypatch):
    """A file over the per-file cap must be refused without being written in
    full — /tmp is tmpfs, so an oversized write is a RAM spike on a 416 MB Pi."""
    monkeypatch.setattr(prev_app, "PREVIEW_MAX_FILE_BYTES", 4096)
    client = prev_app.app.test_client()
    _enable(prev_app)

    r = _upload(client, "big.mp4", data=b"\x00" * (256 * 1024))
    assert r.status_code == 413
    assert list(prev_app.PREVIEW_DIR.iterdir()) == [], "oversized file was written to disk"


def test_over_max_content_length_gives_actionable_json(prev_app):
    """Werkzeug's RequestEntityTooLarge must not surface as a 500 carrying a
    raw exception string — that is what the artist ends up reading."""
    client = prev_app.app.test_client()
    _enable(prev_app)
    original = prev_app.app.config['MAX_CONTENT_LENGTH']
    prev_app.app.config['MAX_CONTENT_LENGTH'] = 2048
    try:
        r = _upload(client, "huge.mp4", data=b"\x00" * (64 * 1024))
        assert r.status_code == 413
        msg = r.get_json()["error"]
        assert "Request Entity Too Large" not in msg, "raw Werkzeug text leaked to the user"
        assert "too large" in msg.lower()
    finally:
        prev_app.app.config['MAX_CONTENT_LENGTH'] = original


def test_declared_size_rejected_before_body_is_read(prev_app, monkeypatch):
    """An over-cap Content-Length is refused up front, so we never spend the
    transfer only to reject it at the end."""
    monkeypatch.setattr(prev_app, "PREVIEW_MAX_SESSION_BYTES", 4096)
    client = prev_app.app.test_client()
    _enable(prev_app)
    r = _upload(client, "big.mp4", data=b"\x00" * (256 * 1024))
    assert r.status_code == 413
    assert list(prev_app.PREVIEW_DIR.iterdir()) == []


def test_config_publishes_limits_to_the_client(prev_app):
    """preview.html checks size before uploading; it must read the real limits
    from the server rather than hard-coding a copy that can drift."""
    d = prev_app.app.test_client().get("/api/preview/config").get_json()
    assert d["max_file_bytes"] == prev_app.PREVIEW_MAX_FILE_BYTES
    assert d["max_files"] == prev_app.PREVIEW_MAX_FILES
    assert d["max_session_bytes"] == prev_app.PREVIEW_MAX_SESSION_BYTES
