"""Tests for the HomeView export — square JPEGs an iPhone Shortcut posts to a
shared iCloud album (docs/homeview-integration.md).

What matters most: the feature does nothing while off, only ever exports what
the gallery would show, never crops the artwork, and remembers what was sent
so the owner's shared album doesn't fill up with duplicates.
"""
import importlib
import io
import json
import shutil
import time

import pytest
from PIL import Image

LAN = {"REMOTE_ADDR": "10.0.0.42"}


@pytest.fixture
def hv_app(tmp_path, monkeypatch):
    import app
    importlib.reload(app)

    monkeypatch.setattr(app, "HOMEVIEW_CONFIG_FILE", tmp_path / "homeview-config.json")
    monkeypatch.setattr(app, "HOMEVIEW_STATE_FILE", tmp_path / "homeview-state.json")
    monkeypatch.setattr(app, "HOMEVIEW_EXPORT_DIR", tmp_path / "homeview-export")
    monkeypatch.setattr(app, "HIDDEN_NFTS_FILE", tmp_path / "hidden-nfts.json")
    monkeypatch.setattr(app, "FAVORITES_FILE", tmp_path / "favorites.json")
    monkeypatch.setattr(app, "NFT_METADATA_FILE", tmp_path / "nft-metadata-cache.json")
    monkeypatch.setattr(app, "SECURITY_CONFIG_FILE", tmp_path / "security.json")
    monkeypatch.setattr(app, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(app, "FAILURES_FILE", tmp_path / "failures.json")
    monkeypatch.setattr(app, "AUDIT_LOG_PATH", tmp_path / "audit.log")
    monkeypatch.setattr(app, "get_storage_config", lambda: {})

    nft_dir = tmp_path / "nfts"
    nft_dir.mkdir()
    monkeypatch.setattr(app, "NFT_DIR", nft_dir)

    # Rendering is exercised through the image endpoint; a background thread
    # would race the assertions.
    monkeypatch.setattr(app, "_homeview_start_prerender", lambda ids: None)
    return app


def _enable(a, **extra):
    a.save_homeview_config({"enabled": True, **extra})


def _art(a, name, size=(800, 200), color=(255, 0, 0), mode="RGB"):
    path = a.NFT_DIR / name
    Image.new(mode, size, color).save(path)
    return path


def _hide(a, names):
    a.HIDDEN_NFTS_FILE.write_text(json.dumps(names))


def _status(client):
    return client.get("/api/homeview/status", environ_overrides=LAN).get_json()


def _batch(client, **body):
    return client.post("/api/homeview/batch", json=body, environ_overrides=LAN)


def _send(client):
    """A complete send: make a batch and download it, as the Shortcut does."""
    b = _batch(client).get_json()
    if b["batch"]:
        for item in _manifest(client, b["batch"]).get_json()["items"]:
            _jpeg(client.get(f"/api/homeview/image/{item['id']}.jpg", environ_overrides=LAN))
    return b


def _manifest(client, batch_id, **kw):
    return client.get(f"/api/homeview/manifest?batch={batch_id}", environ_overrides=LAN, **kw)


def _id_of(a, name):
    return a._homeview_id(name)


def _jpeg(resp):
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    assert resp.mimetype == "image/jpeg"
    return Image.open(io.BytesIO(resp.data)).convert("RGB")


# ============================================================
# Feature flag
# ============================================================
def test_disabled_by_default(hv_app):
    client = hv_app.app.test_client()
    assert client.get("/api/homeview/config").get_json()["enabled"] is False


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/homeview/status"),
    ("POST", "/api/homeview/batch"),
    ("GET", "/api/homeview/manifest?batch=abc"),
    ("GET", "/api/homeview/image/0123456789abcdef.jpg"),
    ("POST", "/api/homeview/removed/clear"),
])
def test_endpoints_refuse_while_disabled(hv_app, method, path):
    _art(hv_app, "a.png")
    client = hv_app.app.test_client()
    r = client.open(path, method=method, json={} if method == "POST" else None,
                    environ_overrides=LAN)
    assert r.status_code == 403


def test_disabling_deletes_exported_images_but_remembers_what_was_sent(hv_app):
    _art(hv_app, "a.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    _batch(client)
    _jpeg(client.get(f"/api/homeview/image/{_id_of(hv_app, 'a.png')}.jpg",
                     environ_overrides=LAN))
    assert any(hv_app.HOMEVIEW_EXPORT_DIR.iterdir())

    client.post("/api/homeview/config", json={"enabled": False}, environ_overrides=LAN)

    for _ in range(50):  # the wipe runs in the background
        if not hv_app.HOMEVIEW_EXPORT_DIR.exists():
            break
        time.sleep(0.05)
    assert not hv_app.HOMEVIEW_EXPORT_DIR.exists()
    # Re-enabling must not re-send everything into the album.
    _enable(hv_app)
    assert _status(client)["not_sent"] == 0


def test_config_rejects_unknown_source(hv_app):
    client = hv_app.app.test_client()
    client.post("/api/homeview/config", json={"enabled": True, "source": "../../etc"},
                environ_overrides=LAN)
    assert client.get("/api/homeview/config").get_json()["source"] == "gallery"


# ============================================================
# Selection — the same art the gallery shows
# ============================================================
def test_hidden_art_is_not_offered(hv_app):
    _art(hv_app, "a.png")
    _art(hv_app, "b.png")
    _hide(hv_app, ["b.png"])
    _enable(hv_app)
    assert _status(hv_app.app.test_client())["not_sent"] == 1


def test_favorites_source_offers_only_favorites(hv_app):
    _art(hv_app, "a.png")
    _art(hv_app, "b.png")
    hv_app.FAVORITES_FILE.write_text(json.dumps({"b.png": 1700000000}))
    _enable(hv_app, source="favorites")
    client = hv_app.app.test_client()
    batch = _batch(client).get_json()
    items = _manifest(client, batch["batch"]).get_json()["items"]
    assert [i["id"] for i in items] == [_id_of(hv_app, "b.png")]


def test_html_without_preview_image_and_non_art_files_are_skipped(hv_app):
    _art(hv_app, "a.png")
    (hv_app.NFT_DIR / "index.html").write_text("<html><body>dir listing</body></html>")
    (hv_app.NFT_DIR / "nft-source-map.json").write_text("{}")
    _enable(hv_app)
    assert _status(hv_app.app.test_client())["not_sent"] == 1


# ============================================================
# Batches — Vernis remembers what was sent
# ============================================================
def test_batch_marks_items_sent(hv_app):
    _art(hv_app, "a.png")
    _art(hv_app, "b.png")
    _enable(hv_app)
    client = hv_app.app.test_client()

    first = _send(client)
    assert first["count"] == 2
    assert _status(client)["not_sent"] == 0

    second = _send(client)
    assert second["count"] == 0
    assert second["batch"] is None


def test_new_art_after_a_send_is_the_only_thing_in_the_next_batch(hv_app):
    _art(hv_app, "a.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    _send(client)
    _art(hv_app, "new.png")

    batch = _send(client)
    items = _manifest(client, batch["batch"]).get_json()["items"]
    assert [i["id"] for i in items] == [_id_of(hv_app, "new.png")]


def test_resend_returns_the_last_batch_again(hv_app):
    _art(hv_app, "a.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    first = _batch(client).get_json()

    again = _batch(client, resend=True).get_json()

    assert again["batch"] == first["batch"]
    assert again["count"] == 1


def test_batch_is_capped_and_the_rest_waits(hv_app, monkeypatch):
    monkeypatch.setattr(hv_app, "HOMEVIEW_BATCH_MAX", 2)
    for n in "abc":
        _art(hv_app, f"{n}.png")
    _enable(hv_app)
    client = hv_app.app.test_client()

    assert _send(client)["count"] == 2
    assert _status(client)["not_sent"] == 1


def test_manifest_lists_absolute_image_urls_and_titles(hv_app):
    _art(hv_app, "a.png")
    hv_app.NFT_METADATA_FILE.write_text(json.dumps(
        {"nfts": {"a.png": {"name": "Sunrise", "artist": "XCOPY"}}}))
    _enable(hv_app)
    client = hv_app.app.test_client()
    batch = _batch(client).get_json()

    r = _manifest(client, batch["batch"], headers={"Host": "afrom.local"})

    item = r.get_json()["items"][0]
    assert item["url"] == f"http://afrom.local/api/homeview/image/{_id_of(hv_app, 'a.png')}.jpg"
    assert item["title"] == "Sunrise"
    assert item["artist"] == "XCOPY"


def test_manifest_url_follows_https_from_the_proxy(hv_app):
    _art(hv_app, "a.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    batch = _batch(client).get_json()

    r = _manifest(client, batch["batch"],
                  headers={"Host": "afrom.local", "X-Forwarded-Proto": "https"})

    assert r.get_json()["items"][0]["url"].startswith("https://afrom.local/")


def test_unknown_batch_is_404(hv_app):
    _art(hv_app, "a.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    _batch(client)
    assert _manifest(client, "not-a-batch").status_code == 404


# ============================================================
# Removed art — the album can't be cleaned automatically, so tell the owner
# ============================================================
def test_sent_art_that_is_hidden_later_is_reported_removed(hv_app):
    _art(hv_app, "a.png")
    _art(hv_app, "b.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    _send(client)

    _hide(hv_app, ["b.png"])

    assert _status(client)["removed"] == ["b.png"]


def test_clearing_removed_forgets_them(hv_app):
    _art(hv_app, "a.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    _send(client)
    _hide(hv_app, ["a.png"])

    client.post("/api/homeview/removed/clear", json={}, environ_overrides=LAN)

    assert _status(client)["removed"] == []
    # Showing it again makes it new, so it can go back into the album.
    _hide(hv_app, [])
    assert _status(client)["not_sent"] == 1


# ============================================================
# Rendering — square, high resolution, never cropped
# ============================================================
def _render(hv_app, name):
    _enable(hv_app)
    client = hv_app.app.test_client()
    _batch(client)
    return _jpeg(client.get(f"/api/homeview/image/{_id_of(hv_app, name)}.jpg",
                            environ_overrides=LAN))


def test_image_is_square_at_export_size(hv_app):
    _art(hv_app, "a.png", size=(800, 200))
    img = _render(hv_app, "a.png")
    assert img.size == (hv_app.HOMEVIEW_SIZE, hv_app.HOMEVIEW_SIZE)


def test_wide_art_is_padded_not_cropped(hv_app):
    _art(hv_app, "a.png", size=(800, 200), color=(255, 0, 0))
    img = _render(hv_app, "a.png")
    s = hv_app.HOMEVIEW_SIZE
    # Full width is art (nothing cut off the sides) ...
    assert img.getpixel((2, s // 2))[0] > 200
    assert img.getpixel((s - 3, s // 2))[0] > 200
    # ... and the space above and below is padding.
    assert img.getpixel((s // 2, 10)) == pytest.approx((0, 0, 0), abs=8)
    assert img.getpixel((s // 2, s - 10)) == pytest.approx((0, 0, 0), abs=8)


def test_small_pixel_art_stays_crisp(hv_app):
    path = hv_app.NFT_DIR / "punk.png"
    small = Image.new("RGB", (8, 8))
    for x in range(8):
        for y in range(8):
            small.putpixel((x, y), (255, 255, 255) if (x + y) % 2 else (0, 0, 0))
    small.save(path)

    img = _render(hv_app, "punk.png")

    # Sample the middle of each source pixel: a blurring resampler would
    # leave greys there, a crisp one leaves pure black and white.
    cell = hv_app.HOMEVIEW_SIZE // 8
    for x in range(8):
        for y in range(8):
            v = img.getpixel((x * cell + cell // 2, y * cell + cell // 2))[0]
            assert v < 30 or v > 225


def test_transparency_is_flattened_onto_the_pad_colour(hv_app):
    _art(hv_app, "a.png", size=(100, 100), color=(255, 0, 0, 0), mode="RGBA")
    img = _render(hv_app, "a.png")
    assert img.getpixel((hv_app.HOMEVIEW_SIZE // 2,) * 2) == pytest.approx((0, 0, 0), abs=8)


def test_html_art_uses_its_preview_image(hv_app):
    import base64
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (0, 0, 255)).save(buf, "PNG")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    (hv_app.NFT_DIR / "gen.html").write_text(
        f'<html><head><meta name="generator-preview" content="{uri}"></head></html>')

    img = _render(hv_app, "gen.html")

    assert img.getpixel((hv_app.HOMEVIEW_SIZE // 2,) * 2)[2] > 200


def test_html_preview_must_be_a_raster_image(hv_app):
    import base64
    uri = "data:text/html;base64," + base64.b64encode(b"<script>x</script>").decode()
    (hv_app.NFT_DIR / "gen.html").write_text(
        f'<html><head><meta name="generator-preview" content="{uri}"></head></html>')
    _enable(hv_app)
    assert _status(hv_app.app.test_client())["not_sent"] == 0


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_video_exports_a_frame(hv_app, tmp_path):
    import subprocess
    src = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=green:s=320x180:d=2", "-pix_fmt", "yuv420p", "-y", str(src)],
                   check=True)
    shutil.copy(src, hv_app.NFT_DIR / "clip.mp4")

    img = _render(hv_app, "clip.mp4")

    s = hv_app.HOMEVIEW_SIZE
    assert img.size == (s, s)
    assert img.getpixel((s // 2, s // 2))[1] > 100


def test_image_for_art_hidden_after_sending_is_404(hv_app):
    _art(hv_app, "a.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    _batch(client)
    _hide(hv_app, ["a.png"])
    r = client.get(f"/api/homeview/image/{_id_of(hv_app, 'a.png')}.jpg", environ_overrides=LAN)
    assert r.status_code == 404


def test_only_the_last_batch_can_be_fetched(hv_app):
    # Bounds disk use and stops a LAN client from making the Pi render the
    # whole collection by walking IDs.
    _art(hv_app, "a.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    r = client.get(f"/api/homeview/image/{_id_of(hv_app, 'a.png')}.jpg", environ_overrides=LAN)
    assert r.status_code == 404


def test_a_new_batch_deletes_the_previous_exports(hv_app):
    _art(hv_app, "a.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    _batch(client)
    _jpeg(client.get(f"/api/homeview/image/{_id_of(hv_app, 'a.png')}.jpg", environ_overrides=LAN))
    _art(hv_app, "b.png")

    _batch(client)

    assert not (hv_app.HOMEVIEW_EXPORT_DIR / f"{_id_of(hv_app, 'a.png')}.jpg").exists()


def test_image_id_is_not_a_path(hv_app):
    _enable(hv_app)
    client = hv_app.app.test_client()
    r = client.get("/api/homeview/image/..%2F..%2Fsecurity.jpg", environ_overrides=LAN)
    assert r.status_code == 404


# ============================================================
# Security modes
# ============================================================
def _mode_c(a):
    cfg = a._security_config_defaults()
    cfg["mode"] = "C"
    cfg["pin_hash"] = a.hash_pin("123456")
    a.save_security_config(cfg)


def test_mode_c_needs_a_pin_to_send(hv_app):
    _art(hv_app, "a.png")
    _enable(hv_app)
    _mode_c(hv_app)
    r = _batch(hv_app.app.test_client())
    assert r.status_code == 401


def test_mode_c_lets_the_shortcut_read_without_a_pin(hv_app):
    _art(hv_app, "a.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    batch = _batch(client).get_json()
    _mode_c(hv_app)

    assert _manifest(client, batch["batch"]).status_code == 200
    r = client.get(f"/api/homeview/image/{_id_of(hv_app, 'a.png')}.jpg", environ_overrides=LAN)
    assert r.status_code == 200


# ============================================================
# Review fixes
# ============================================================
def test_dotfiles_uppercase_and_folders_are_not_art(hv_app):
    # Same rule as the gallery's glob("*.png"): macOS ._ resource forks on a
    # NAS/exFAT drive, upper-case extensions and folders are not offered.
    _art(hv_app, "a.png")
    (hv_app.NFT_DIR / "._a.png").write_bytes(b"\x00\x05\x16\x07junk")
    _art(hv_app, "B.PNG")
    (hv_app.NFT_DIR / "dir.png").mkdir()
    _enable(hv_app)
    assert _status(hv_app.app.test_client())["not_sent"] == 1


def test_offline_external_storage_does_not_count_as_removed(hv_app, monkeypatch, tmp_path):
    ext = tmp_path / "ext"
    (ext / "vernis-nfts").mkdir(parents=True)
    Image.new("RGB", (800, 200)).save(ext / "vernis-nfts" / "e.png")
    monkeypatch.setattr(hv_app, "get_storage_config",
                        lambda: {"use_external": True, "external_path": str(ext)})
    monkeypatch.setattr(hv_app, "external_storage_available", lambda p: True)
    _enable(hv_app)
    client = hv_app.app.test_client()
    _batch(client)

    monkeypatch.setattr(hv_app, "external_storage_available", lambda p: False)

    s = _status(client)
    assert s["removed"] == []
    assert s["storage_offline"] is True
    # ... and "Done, I've deleted them" must not forget pieces that are only
    # out of reach, or they'd be posted again as duplicates.
    assert client.post("/api/homeview/removed/clear", json={},
                       environ_overrides=LAN).status_code == 409


def test_pieces_the_shortcut_never_fetched_go_in_the_next_batch(hv_app):
    # First run: the owner taps Send before installing the Shortcut, installs
    # it, then taps Send again (not "Send last batch again").
    _art(hv_app, "a.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    _batch(client)
    _art(hv_app, "b.png")

    batch = _batch(client).get_json()

    items = _manifest(client, batch["batch"]).get_json()["items"]
    assert sorted(i["id"] for i in items) == sorted([_id_of(hv_app, "a.png"), _id_of(hv_app, "b.png")])


def test_fetched_pieces_are_not_sent_again(hv_app):
    _art(hv_app, "a.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    _batch(client)
    _jpeg(client.get(f"/api/homeview/image/{_id_of(hv_app, 'a.png')}.jpg", environ_overrides=LAN))

    assert _batch(client).get_json()["count"] == 0


def test_prune_survives_a_leftover_folder(hv_app):
    _art(hv_app, "a.png")
    _enable(hv_app)
    client = hv_app.app.test_client()
    _batch(client)
    _jpeg(client.get(f"/api/homeview/image/{_id_of(hv_app, 'a.png')}.jpg", environ_overrides=LAN))
    (hv_app.HOMEVIEW_EXPORT_DIR / "tmpabc123").mkdir()
    (hv_app.HOMEVIEW_EXPORT_DIR / "zz-old.jpg").write_bytes(b"x")
    _art(hv_app, "b.png")

    _batch(client)

    assert not (hv_app.HOMEVIEW_EXPORT_DIR / "zz-old.jpg").exists()


def test_exif_rotation_is_applied(hv_app):
    # A portrait photo stored landscape with Orientation=6 (rotate 90°).
    img = Image.new("RGB", (800, 200), (255, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6
    img.save(hv_app.NFT_DIR / "a.jpg", exif=exif)

    out = _render(hv_app, "a.jpg")

    s = hv_app.HOMEVIEW_SIZE
    # Upright it is tall: art in the middle column, padding left and right.
    assert out.getpixel((s // 2, 5))[0] > 200
    assert out.getpixel((5, s // 2)) == pytest.approx((0, 0, 0), abs=8)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_oversized_images_are_decoded_outside_the_api_process(hv_app, monkeypatch):
    monkeypatch.setattr(hv_app, "HOMEVIEW_MAX_INPROCESS_PIXELS", 1000)
    _art(hv_app, "big.png", size=(800, 200), color=(255, 0, 0))
    opened = []
    real_square = hv_app._homeview_square
    monkeypatch.setattr(hv_app, "_homeview_square",
                        lambda img: opened.append(img.size) or real_square(img))

    out = _render(hv_app, "big.png")

    assert out.getpixel((2, hv_app.HOMEVIEW_SIZE // 2))[0] > 200
    # Pillow only ever saw ffmpeg's already-scaled frame, never the original.
    assert opened and opened[0] != (800, 200)


def test_config_with_a_non_object_body_is_rejected_cleanly(hv_app):
    client = hv_app.app.test_client()
    r = client.post("/api/homeview/config", json=[1, 2], environ_overrides=LAN)
    assert r.status_code == 400
