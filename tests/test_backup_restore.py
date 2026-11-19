"""Backup and restore: art on an external drive is backed up, collection CSVs
come back on restore, and big backups are uploaded as a raw stream instead of
hitting the 500 MB multipart limit."""
import importlib
import io
import json
import zipfile
from collections import namedtuple

import pytest

LAN = {"REMOTE_ADDR": "10.0.0.42"}


@pytest.fixture
def bapp(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    for name, rel in [
        ("SECURITY_CONFIG_FILE", "security.json"), ("SESSIONS_FILE", "sessions.json"),
        ("FAILURES_FILE", "failures.json"), ("AUDIT_LOG_PATH", "audit.log"),
        ("STORAGE_CONFIG_FILE", "storage-config.json"),
    ]:
        monkeypatch.setattr(app, name, tmp_path / rel)
    for name, rel in [
        ("NFT_DIR", "nfts"), ("CSV_LIBRARY_DIR", "csv-library"),
        ("UPLOAD_DIR", "uploads"), ("BACKUP_DIR", "backup"),
    ]:
        d = tmp_path / rel
        d.mkdir()
        monkeypatch.setattr(app, name, d)
    return app


def _use_external(app, path, readonly=False):
    app.STORAGE_CONFIG_FILE.write_text(json.dumps(
        {"use_external": True, "external_path": str(path), "readonly_mode": readonly}))


def _backup_names(app, client):
    r = client.post("/api/backup/create", environ_base=LAN)
    assert r.status_code == 200, r.get_json()
    with zipfile.ZipFile(app.BACKUP_DIR / r.get_json()["filename"]) as zf:
        return set(zf.namelist())


def test_backup_includes_external_and_internal_art(bapp, tmp_path):
    ext = tmp_path / "ssd"
    (ext / "vernis-nfts").mkdir(parents=True)
    (ext / "vernis-nfts" / "QmExternal.png").write_bytes(b"ext")
    (bapp.NFT_DIR / "QmInternal.png").write_bytes(b"int")
    (bapp.CSV_LIBRARY_DIR / "punks.csv").write_text("cid\n")
    _use_external(bapp, ext, readonly=True)

    names = _backup_names(bapp, bapp.app.test_client())

    assert {"nfts/QmExternal.png", "nfts/QmInternal.png", "csv-library/punks.csv"} <= names


def test_backup_refuses_when_device_lacks_space(bapp, monkeypatch):
    (bapp.NFT_DIR / "QmA.png").write_bytes(b"x" * 1000)
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(bapp.shutil, "disk_usage", lambda p: Usage(10**9, 10**9, 1000))

    r = bapp.app.test_client().post("/api/backup/create", environ_base=LAN)

    assert r.status_code == 507
    assert "free space" in r.get_json()["error"]
    assert not list(bapp.BACKUP_DIR.iterdir())  # no partial zip left behind


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _restore_raw(app, data, name="vernis_backup_x.zip"):
    return app.app.test_client().post(
        "/api/backup/import", data=data, environ_base=LAN,
        headers={"Content-Type": "application/octet-stream", "X-Backup-Filename": name})


def test_restore_brings_back_art_and_collection_csvs(bapp):
    r = _restore_raw(bapp, _zip({
        "nfts/QmA.png": b"art",
        "csv-library/punks.csv": "cid\nQmA\n",
        "uploads/mine.csv": "cid\n",
    }))

    assert r.status_code == 200, r.get_json()
    assert (bapp.NFT_DIR / "QmA.png").read_bytes() == b"art"
    assert (bapp.CSV_LIBRARY_DIR / "punks.csv").read_text() == "cid\nQmA\n"
    assert (bapp.UPLOAD_DIR / "mine.csv").exists()
    assert r.get_json()["restored_csv"] == 2


def test_restore_round_trip(bapp):
    (bapp.NFT_DIR / "QmA.png").write_bytes(b"art")
    (bapp.CSV_LIBRARY_DIR / "punks.csv").write_text("cid\n")
    client = bapp.app.test_client()
    fn = client.post("/api/backup/create", environ_base=LAN).get_json()["filename"]
    data = (bapp.BACKUP_DIR / fn).read_bytes()
    (bapp.NFT_DIR / "QmA.png").unlink()
    (bapp.CSV_LIBRARY_DIR / "punks.csv").unlink()

    r = _restore_raw(bapp, data, fn)

    assert r.status_code == 200, r.get_json()
    assert (bapp.NFT_DIR / "QmA.png").exists()
    assert (bapp.CSV_LIBRARY_DIR / "punks.csv").exists()


def test_raw_restore_is_not_capped_by_upload_limit(bapp):
    bapp.app.config["MAX_CONTENT_LENGTH"] = 1024  # stand-in for the 500 MB cap
    r = _restore_raw(bapp, _zip({"nfts/QmBig.mp4": b"v" * 50_000}))

    assert r.status_code == 200, r.get_json()
    assert (bapp.NFT_DIR / "QmBig.mp4").stat().st_size == 50_000


def test_restore_goes_to_external_library(bapp, tmp_path):
    ext = tmp_path / "ssd"
    ext.mkdir()
    _use_external(bapp, ext)
    (ext / "vernis-nfts").mkdir()
    (ext / "vernis-nfts" / "keep.png").write_bytes(b"k")  # marks drive as usable

    r = _restore_raw(bapp, _zip({"nfts/QmA.png": b"art"}))

    assert r.status_code == 200, r.get_json()
    assert (ext / "vernis-nfts" / "QmA.png").exists()
    assert not list(ext.glob(".vernis-restore-*"))  # upload temp file removed


def test_restore_ignores_paths_outside_known_folders(bapp, tmp_path):
    r = _restore_raw(bapp, _zip({
        "nfts/../../evil.png": b"x",
        "uploads/script.sh": b"x",
        "other/QmA.png": b"x",
        "nfts/QmOk.png": b"ok",
    }))

    assert r.status_code == 200
    assert (bapp.NFT_DIR / "evil.png").exists()  # flattened to its base name
    assert not (tmp_path / "evil.png").exists()
    assert not (bapp.UPLOAD_DIR / "script.sh").exists()
    assert r.get_json()["restored_art"] == 2


def test_restore_rejects_non_backup(bapp):
    r = _restore_raw(bapp, b"not a zip")
    assert r.status_code == 400


# ---- streamed backup -----------------------------------------------------

import tarfile


def _library(app):
    (app.NFT_DIR / "QmA.png").write_bytes(b"a" * 1000)
    (app.NFT_DIR / "QmB.mp4").write_bytes(bytes(range(256)) * 40)
    (app.NFT_DIR / "nft-source-map.json").write_text("{}")
    (app.CSV_LIBRARY_DIR / "punks.csv").write_text("cid\nQmA\n")


def test_stream_is_a_valid_tar_of_the_library(bapp):
    _library(bapp)
    client = bapp.app.test_client()

    r = client.get("/api/backup/stream", environ_base=LAN)

    assert r.status_code == 200
    assert r.headers["Accept-Ranges"] == "bytes"
    assert int(r.headers["Content-Length"]) == len(r.data)
    assert "attachment" in r.headers["Content-Disposition"]
    with tarfile.open(fileobj=io.BytesIO(r.data)) as tf:
        names = tf.getnames()
        assert tf.extractfile("nfts/QmB.mp4").read() == bytes(range(256)) * 40
    assert names[-1] == "vernis-backup.json"
    assert set(names) == {"nfts/QmA.png", "nfts/QmB.mp4", "nfts/nft-source-map.json",
                          "csv-library/punks.csv", "vernis-backup.json"}
    info = client.get("/api/backup/stream/info", environ_base=LAN).get_json()
    assert info == {"artworks": 3, "collection_files": 1, "bytes": len(r.data)}


def test_stream_resumes_from_any_offset(bapp):
    _library(bapp)
    client = bapp.app.test_client()
    full = client.get("/api/backup/stream", environ_base=LAN)
    etag = full.headers["ETag"]

    for cut in (1, 511, 512, 700, 3000, len(full.data) - 1):
        r = client.get("/api/backup/stream", environ_base=LAN,
                       headers={"Range": f"bytes={cut}-", "If-Range": etag})
        assert r.status_code == 206
        assert full.data[:cut] + r.data == full.data
        assert r.headers["Content-Range"] == f"bytes {cut}-{len(full.data) - 1}/{len(full.data)}"


def test_stream_restarts_when_library_changed(bapp):
    _library(bapp)
    client = bapp.app.test_client()
    etag = client.get("/api/backup/stream", environ_base=LAN).headers["ETag"]
    (bapp.NFT_DIR / "QmNew.png").write_bytes(b"new")

    r = client.get("/api/backup/stream", environ_base=LAN,
                   headers={"Range": "bytes=100-", "If-Range": etag})

    assert r.status_code == 200  # whole archive again, not a mismatched tail
    assert r.headers["ETag"] != etag


def test_stream_handles_external_drive_and_long_names(bapp, tmp_path):
    ext = tmp_path / "ssd"
    (ext / "vernis-nfts").mkdir(parents=True)
    long = "bafy" + "k" * 150 + "_Ünïcode name.png"
    (ext / "vernis-nfts" / long).write_bytes(b"x")
    _use_external(bapp, ext)

    data = bapp.app.test_client().get("/api/backup/stream", environ_base=LAN).data

    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        assert f"nfts/{long}" in tf.getnames()


def test_streamed_backup_restores_on_an_empty_device(bapp):
    _library(bapp)
    client = bapp.app.test_client()
    data = client.get("/api/backup/stream", environ_base=LAN).data
    for d in (bapp.NFT_DIR, bapp.CSV_LIBRARY_DIR):
        for p in d.iterdir():
            p.unlink()

    r = _restore_raw(bapp, data, "vernis-backup-afrom-2026-11-17.tar")

    assert r.status_code == 200, r.get_json()
    assert (bapp.NFT_DIR / "QmB.mp4").read_bytes() == bytes(range(256)) * 40
    assert (bapp.CSV_LIBRARY_DIR / "punks.csv").exists()
    assert not list(bapp.NFT_DIR.parent.glob(".vernis-restore-*"))

    again = _restore_raw(bapp, data, "vernis-backup-afrom-2026-11-17.tar").get_json()
    assert again["unchanged"] == 4 and again["restored_art"] == 0


@pytest.mark.parametrize("cut", [1500, 2600, -1700])
def test_incomplete_download_is_reported(bapp, cut):
    _library(bapp)
    data = bapp.app.test_client().get("/api/backup/stream", environ_base=LAN).data

    r = _restore_raw(bapp, data[:cut], "b.tar")

    assert r.status_code == 400
    assert "incomplete" in r.get_json()["error"]
    assert not list(bapp.NFT_DIR.glob(".*.restore"))  # no half-written file left


def test_import_check_reports_space(bapp, monkeypatch):
    client = bapp.app.test_client()
    ok = client.get("/api/backup/import/check?size=1000&name=b.tar", environ_base=LAN).get_json()
    assert ok["ok"] is True

    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(bapp.shutil, "disk_usage", lambda p: Usage(10**9, 10**9, 10**6))
    bad = client.get("/api/backup/import/check?size=1000&name=b.tar", environ_base=LAN).get_json()
    assert bad["ok"] is False and "free space" in bad["error"]
    assert "remove" not in bad["error"].lower()
