"""USB drives, restore from a drive, re-pinning restored art, and moving the
IPFS store (backend side and the root storage helper)."""
import importlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

LAN = {"REMOTE_ADDR": "10.0.0.42"}
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sapp(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    for name, rel in [
        ("SECURITY_CONFIG_FILE", "security.json"), ("SESSIONS_FILE", "sessions.json"),
        ("FAILURES_FILE", "failures.json"), ("AUDIT_LOG_PATH", "audit.log"),
        ("STORAGE_CONFIG_FILE", "storage-config.json"),
        ("IPFS_MOVE_STATUS_FILE", "ipfs-move-status.json"),
    ]:
        monkeypatch.setattr(app, name, tmp_path / rel)
    for name, rel in [("NFT_DIR", "nfts"), ("CSV_LIBRARY_DIR", "csv-library"),
                      ("UPLOAD_DIR", "uploads"), ("BACKUP_DIR", "backup")]:
        d = tmp_path / rel
        d.mkdir()
        monkeypatch.setattr(app, name, d)
    drive = tmp_path / "media" / "vernis" / "Archive-1a2b3c4d"
    drive.mkdir(parents=True)
    mounts = tmp_path / "mounts"
    mounts.write_text(
        "/dev/mmcblk0p2 / ext4 rw 0 0\n"
        "tmpfs /run tmpfs rw 0 0\n"
        f"/dev/sda1 {drive} ext4 rw,nosuid 0 0\n".replace(str(tmp_path), "/TMP"))
    # The parser itself is covered below; here the table maps /TMP to tmp_path
    def fake_mounts():
        out = []
        for line in mounts.read_text().splitlines():
            dev, mp, fs = line.split()[:3]
            mp = mp.replace("/TMP", str(tmp_path))
            if fs not in app._PSEUDO_FS and "/media/" in mp:
                out.append((dev, mp, fs))
        return out
    monkeypatch.setattr(app, "_drive_mounts", fake_mounts)
    app._test_drive = drive
    return app


def test_drive_mounts_parses_mount_table(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    table = tmp_path / "mounts"
    table.write_text("/dev/mmcblk0p2 / ext4 rw 0 0\n"
                     "/dev/sda1 /media/vernis/My\\040Drive-1234abcd exfat rw 0 0\n"
                     "tmpfs /mnt/ram tmpfs rw 0 0\n"
                     "//nas/art /mnt/nas cifs rw 0 0\n"
                     "/dev/sdb1 /media ext4 rw 0 0\n")
    monkeypatch.setattr(app, "MOUNTS_FILE", str(table))
    assert app._drive_mounts() == [
        ("/dev/sda1", "/media/vernis/My Drive-1234abcd", "exfat"),
        ("//nas/art", "/mnt/nas", "cifs"),
    ]


def test_detect_reports_real_drives_only(sapp):
    drives = sapp.detect_external_drives()
    assert [d["path"] for d in drives] == [str(sapp._test_drive)]
    assert drives[0]["can_hold_ipfs"] is True
    assert drives[0]["fstype"] == "ext4"


def _backup_tar(app, files):
    nft = app.NFT_DIR
    for name, data in files.items():
        (nft / name).write_bytes(data)
    data = app.app.test_client().get("/api/backup/stream", environ_base=LAN).data
    for name in files:
        (nft / name).unlink()
    return data


def _wait_restore(client):
    for _ in range(200):
        s = client.get("/api/backup/restore-status", environ_base=LAN).get_json()
        if s.get("state") != "running":
            return s
        time.sleep(0.02)
    raise AssertionError("restore did not finish")


def test_restore_from_usb_drive(sapp):
    cid = "Qm" + "a" * 44
    data = _backup_tar(sapp, {f"{cid}.png": b"art"})
    (sapp._test_drive / "backups").mkdir()
    (sapp._test_drive / "backups" / "vernis-backup-afrom-2026-11-17.tar").write_bytes(data)
    (sapp._test_drive / "holiday.tar").write_bytes(b"not ours")
    client = sapp.app.test_client()

    listed = client.get("/api/backup/local", environ_base=LAN).get_json()["backups"]
    assert [b["name"] for b in listed] == ["vernis-backup-afrom-2026-11-17.tar"]

    r = client.post("/api/backup/local/restore", json={"path": listed[0]["path"]}, environ_base=LAN)
    assert r.status_code == 200, r.get_json()
    s = _wait_restore(client)
    assert s["state"] == "done", s
    assert s["restored_art"] == 1
    assert (sapp.NFT_DIR / f"{cid}.png").read_bytes() == b"art"


def test_local_restore_only_accepts_listed_backups(sapp, tmp_path):
    secret = tmp_path / "vernis-backup-evil.tar"
    secret.write_bytes(b"x")
    r = sapp.app.test_client().post("/api/backup/local/restore", json={"path": str(secret)},
                                    environ_base=LAN)
    assert r.status_code == 404


def test_repin_uses_original_cid_offline(sapp, monkeypatch, tmp_path):
    cid = "Qm" + "b" * 44
    f = tmp_path / f"{cid}.png"
    f.write_bytes(b"art")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "--only-hash" in cmd:
            out = cid if "--cid-version=0" in cmd else "bafyother"
            return SimpleNamespace(returncode=0, stdout=out + "\n", stderr="")
        return SimpleNamespace(returncode=0, stdout=cid + "\n", stderr="")
    monkeypatch.setattr(sapp.subprocess, "run", fake_run)

    assert sapp._repin_file(f) is True
    assert calls[-1][:4] == ["ipfs", "add", "-Q", "--pin"]
    assert "--cid-version=0" in calls[-1]
    assert not any(c[:3] == ["ipfs", "pin", "add"] for c in calls)


def test_repin_falls_back_to_network_pin(sapp, monkeypatch, tmp_path):
    cid = "bafy" + "c" * 55
    f = tmp_path / f"{cid}.mp4"
    f.write_bytes(b"v")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="somethingelse\n", stderr="")
    monkeypatch.setattr(sapp.subprocess, "run", fake_run)

    assert sapp._repin_file(f) is True
    assert calls[-1] == ["ipfs", "pin", "add", cid]


def test_repin_skips_files_not_named_by_cid(sapp, tmp_path):
    f = tmp_path / "nft-source-map.json"
    f.write_text("{}")
    assert sapp._repin_file(f) is False


def test_ipfs_location_reports_external_store(sapp, monkeypatch, tmp_path):
    store = sapp._test_drive / "vernis-ipfs"
    store.mkdir()
    link = tmp_path / "home" / ".ipfs"
    link.parent.mkdir()
    link.symlink_to(store)
    monkeypatch.setitem(sapp.IPFS_ENV, "IPFS_PATH", str(link))
    d = sapp.app.test_client().get("/api/ipfs/location", environ_base=LAN).get_json()
    assert d["external"] is True and d["drive"] == str(sapp._test_drive)


def test_ipfs_move_refuses_non_posix_drive(sapp, monkeypatch):
    monkeypatch.setattr(sapp, "detect_external_drives", lambda: [
        {"path": "/media/vernis/Stick-1", "fstype": "exfat", "can_hold_ipfs": False}])
    r = sapp.app.test_client().post("/api/ipfs/location", json={"target": "/media/vernis/Stick-1"},
                                    environ_base=LAN)
    assert r.status_code == 400 and "ext4" in r.get_json()["error"]


def test_limit_ceiling_follows_the_ipfs_drive(sapp, monkeypatch, tmp_path):
    monkeypatch.setitem(sapp.IPFS_ENV, "IPFS_PATH", str(tmp_path))
    Usage = __import__("collections").namedtuple("Usage", "total used free")
    monkeypatch.setattr(sapp.shutil, "disk_usage", lambda p: Usage(16 * 10**12, 0, 16 * 10**12))
    monkeypatch.setattr(sapp.os, "stat", lambda p, *a, **k: SimpleNamespace(st_dev=1 if p == "/" else 2))
    # 16 TB drive, not the system drive: 85% of it, far above the old 4096 cap
    assert sapp._ipfs_limit_ceiling_gb() == int(16 * 10**12 / 1024**3 * 0.85)


# ---- root storage helper ---------------------------------------------------

@pytest.fixture
def helper(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("vstore", ROOT / "scripts" / "vernis-storage-helper.py")
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    home = tmp_path / "home"
    (home / ".ipfs" / "blocks").mkdir(parents=True)
    (home / ".ipfs" / "config").write_text("{}")
    (home / ".ipfs" / "blocks" / "CIQA.data").write_bytes(b"block" * 100)
    drive = tmp_path / "drive"
    drive.mkdir()
    user = SimpleNamespace(pw_name=os.environ.get("USER", "me"), pw_uid=os.getuid(),
                           pw_gid=os.getgid(), pw_dir=str(home))
    monkeypatch.setattr(h, "owner", lambda: user)
    statuses = []
    monkeypatch.setattr(h, "write_status", lambda **kw: statuses.append(kw))
    monkeypatch.setattr(h, "drive_mount", lambda p: (str(drive), "ext4") if p == str(drive) else None)
    systemctl, as_user_cmds = [], []

    def fake_run(cmd, **kw):
        if cmd[0] == "systemctl":
            systemctl.append(cmd[1])
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[0] == "runuser":  # run the command itself, as us
            cmd = cmd[cmd.index("--") + 1:]
            as_user_cmds.append(cmd[0])
        return subprocess.run(cmd, capture_output=True, text=True)
    monkeypatch.setattr(h, "run", fake_run)
    h._t = SimpleNamespace(home=home, drive=drive, systemctl=systemctl, as_user=as_user_cmds,
                           status=lambda: statuses[-1], tmp=tmp_path)
    return h


def test_helper_moves_store_to_drive_and_back(helper, monkeypatch):
    monkeypatch.setattr(helper, "ipfs_online", lambda u, timeout=90: True)
    t = helper._t

    assert helper.cmd_ipfs_move_run(str(t.drive)) == 0
    link = t.home / ".ipfs"
    assert link.is_symlink() and os.path.realpath(link) == str(t.drive / "vernis-ipfs")
    assert (link / "blocks" / "CIQA.data").read_bytes() == b"block" * 100
    assert not (t.home / ".ipfs.before-move").exists()
    assert t.systemctl == ["stop", "start"]
    assert t.as_user and t.as_user[0] in ("rsync", "cp")  # copied without root rights
    assert t.status()["state"] == "done"

    assert helper.cmd_ipfs_move_run("internal") == 0
    assert link.is_dir() and not link.is_symlink()
    assert (link / "config").exists()
    assert not (t.drive / "vernis-ipfs").exists()


def test_helper_rolls_back_when_node_wont_start(helper, monkeypatch):
    monkeypatch.setattr(helper, "ipfs_online", lambda u, timeout=90: False)
    t = helper._t

    assert helper.cmd_ipfs_move_run(str(t.drive)) == 2
    link = t.home / ".ipfs"
    assert link.is_dir() and not link.is_symlink()
    assert (link / "blocks" / "CIQA.data").exists()
    assert not (t.drive / "vernis-ipfs").exists()
    assert t.systemctl[-1] == "start"
    assert t.status()["state"] == "error"


def test_helper_refuses_bad_names():
    spec = importlib.util.spec_from_file_location("vstore2", ROOT / "scripts" / "vernis-storage-helper.py")
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    assert h.valid_kernel_name("sda1") and h.valid_kernel_name("nvme0n1p2")
    assert not h.valid_kernel_name("../sda1") and not h.valid_kernel_name("mmcblk0p2")


def test_helper_refuses_store_linked_elsewhere(helper, monkeypatch):
    """vernis-api's account controls ~/.ipfs: pointing it at a system folder
    must not make root copy, hand over or delete that folder."""
    monkeypatch.setattr(helper, "ipfs_online", lambda u, timeout=90: True)
    t = helper._t
    victim = t.tmp / "etc"
    victim.mkdir()
    (victim / "shadow").write_text("secret")
    link = t.home / ".ipfs"
    import shutil as _sh
    _sh.rmtree(link)
    link.symlink_to(victim)

    assert helper.cmd_ipfs_move_run(str(t.drive)) == 2
    assert (victim / "shadow").read_text() == "secret"
    assert not (t.drive / "vernis-ipfs").exists()
    assert t.systemctl == []  # refused before touching anything


def test_prepare_refuses_planted_symlink(helper, monkeypatch):
    t = helper._t
    victim = t.tmp / "victim"
    victim.mkdir()
    (t.drive / "vernis-nfts").symlink_to(victim)
    chowned = []
    monkeypatch.setattr(os, "fchown", lambda fd, u, g: chowned.append(fd))

    assert helper.cmd_prepare(str(t.drive)) == 2
    assert chowned == []


def test_status_refuses_folder_not_owned_by_root(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("vstore3", ROOT / "scripts" / "vernis-storage-helper.py")
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    monkeypatch.setattr(h, "STATUS_DIR", str(tmp_path))  # owned by us, not root
    monkeypatch.setattr(h, "STATUS_FILE", str(tmp_path / "s.json"))
    with pytest.raises(RuntimeError):
        h.write_status(state="copying")
    assert not (tmp_path / "s.json").exists()


# ---- backup onto a USB drive -----------------------------------------------

def _wait_drive_backup(client):
    for _ in range(200):
        s = client.get("/api/backup/drive/status", environ_base=LAN).get_json()
        if s.get("state") != "running":
            return s
        time.sleep(0.02)
    raise AssertionError("backup did not finish")


def test_backup_to_drive_then_restore_from_it(sapp):
    cid = "Qm" + "d" * 44
    (sapp.NFT_DIR / f"{cid}.mp4").write_bytes(b"video" * 1000)
    (sapp.CSV_LIBRARY_DIR / "punks.csv").write_text("cid\n")
    client = sapp.app.test_client()

    r = client.post("/api/backup/drive", json={"path": str(sapp._test_drive)}, environ_base=LAN)
    assert r.status_code == 200, r.get_json()
    s = _wait_drive_backup(client)
    assert s["state"] == "done", s
    saved = Path(s["file"])
    assert saved.parent == sapp._test_drive / "vernis-backups"
    assert not list(saved.parent.glob(".*.part"))
    with tarfile.open(saved) as tf:
        assert f"nfts/{cid}.mp4" in tf.getnames()

    # The new Vernis sees it as a backup it can restore
    (sapp.NFT_DIR / f"{cid}.mp4").unlink()
    listed = client.get("/api/backup/local", environ_base=LAN).get_json()["backups"]
    assert [b["path"] for b in listed] == [str(saved)]
    client.post("/api/backup/local/restore", json={"path": str(saved)}, environ_base=LAN)
    assert _wait_restore(client)["state"] == "done"
    assert (sapp.NFT_DIR / f"{cid}.mp4").read_bytes() == b"video" * 1000


def test_backup_to_fat32_drive_over_4gb_is_refused(sapp, monkeypatch):
    monkeypatch.setattr(sapp, "detect_external_drives", lambda: [
        {"path": "/media/vernis/Stick-1", "name": "Stick-1", "fstype": "vfat"}])
    monkeypatch.setattr(sapp, "_backup_tar_plan", lambda: ([], 5 * 1024**3, "x", {}))
    r = sapp.app.test_client().post("/api/backup/drive", json={"path": "/media/vernis/Stick-1"},
                                    environ_base=LAN)
    assert r.status_code == 400 and "FAT32" in r.get_json()["error"]


def test_backup_to_unknown_drive_is_refused(sapp):
    r = sapp.app.test_client().post("/api/backup/drive", json={"path": "/etc"}, environ_base=LAN)
    assert r.status_code == 404
