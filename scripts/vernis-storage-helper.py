#!/usr/bin/python3
"""Vernis storage helper (runs as root).

install-storage-helper.sh installs this root-owned as
/usr/local/sbin/vernis-storage, adds a udev rule for USB drives, and one sudo
rule letting vernis-api run the `prepare`, `prepare-backups` and `ipfs-move` commands.

  vernis-storage mount <kernel name>     udev, on plug-in: mount under /media/vernis
  vernis-storage unmount <kernel name>   udev, on removal
  vernis-storage prepare <mountpoint>    make <mountpoint>/vernis-nfts writable for vernis-api
  vernis-storage prepare-backups <mp>    the same for <mountpoint>/vernis-backups
  vernis-storage ipfs-move <mountpoint>  move the IPFS store onto that drive
  vernis-storage ipfs-move internal      move it back to the SD card / boot drive

Why mount at all: Raspberry Pi OS only automounts USB drives from a desktop
file manager, and the kiosk session doesn't run one, so a plugged-in drive
never showed up in Settings > External Drive.

Exit 0 = done (ipfs-move: started), 2 = refused or failed.
"""
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

MEDIA_ROOT = "/media/vernis"
# Root-owned: vernis-api reads it but can't plant a symlink there
STATUS_DIR = "/run/vernis-storage"
STATUS_FILE = STATUS_DIR + "/ipfs-move-status.json"
# Filesystems that keep Unix owners and permissions. The IPFS store needs
# them; art files work on any format (exFAT/NTFS/FAT get owner via options).
POSIX_FS = {"ext4", "ext3", "ext2", "btrfs", "xfs", "f2fs"}
SAFE_OPTS = "nosuid,nodev,noexec,noatime"


def log(msg):
    print(f"[vernis-storage] {msg}", flush=True)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def owner():
    """The account vernis-api runs as (it owns the library and IPFS store)."""
    user = run(["systemctl", "show", "-p", "User", "--value", "vernis-api"]).stdout.strip()
    if not user or user == "root":
        return None
    try:
        return pwd.getpwnam(user)
    except KeyError:
        return None


def mounts():
    """[(device, mountpoint, fstype)] from the kernel's mount table."""
    out = []
    with open("/proc/self/mounts") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 3:
                mp = parts[1].replace("\\040", " ")
                out.append((parts[0], mp, parts[2]))
    return out


def blkid(dev):
    """{TYPE, UUID, LABEL, ...} for /dev/<dev>."""
    r = run(["blkid", "-o", "export", f"/dev/{dev}"])
    info = {}
    for line in r.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k] = v
    return info


def boot_disks():
    """Disks holding / or /boot: never automount their other partitions
    (a Pi that boots from a USB SSD has its system on a USB device)."""
    disks = set()
    for dev, mp, _ in mounts():
        if mp in ("/", "/boot", "/boot/firmware") and dev.startswith("/dev/"):
            name = os.path.basename(os.path.realpath(dev))
            parent = run(["lsblk", "-no", "PKNAME", f"/dev/{name}"]).stdout.strip()
            disks.add(parent or name)
    return disks


def valid_kernel_name(dev):
    return bool(re.fullmatch(r"(sd[a-z]+|nvme\d+n\d+)(p?\d+)?", dev))


def cmd_mount(dev):
    if not valid_kernel_name(dev):
        return 2
    parent = run(["lsblk", "-no", "PKNAME", f"/dev/{dev}"]).stdout.strip() or dev
    if parent in boot_disks() or dev in boot_disks():
        log(f"{dev}: on the boot disk, not mounting")
        return 0
    if any(os.path.realpath(d) == f"/dev/{dev}" for d, _, _ in mounts()):
        log(f"{dev}: already mounted")
        return 0
    info = blkid(dev)
    fstype, uuid = info.get("TYPE", ""), info.get("UUID", "")
    if not fstype or fstype in ("swap", "crypto_LUKS", "LVM2_member", "linux_raid_member"):
        log(f"{dev}: no mountable filesystem ({fstype or 'none'})")
        return 0
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", info.get("LABEL", "")).strip("-.") or "USB-drive"
    # Label plus part of the UUID: readable, and the same path every time this
    # drive is plugged in, which is what Settings stores.
    mountpoint = os.path.join(MEDIA_ROOT, f"{label}-{(uuid or dev).replace('-', '')[:8]}")
    os.makedirs(mountpoint, exist_ok=True)

    user = owner()
    opts = SAFE_OPTS
    if fstype in ("vfat", "exfat", "ntfs", "ntfs3") and user:
        opts += f",uid={user.pw_uid},gid={user.pw_gid},umask=022"
    attempts = [[fstype]]
    if fstype == "ntfs":
        attempts = [["ntfs3"], ["ntfs-3g"]]
    for (fs,) in attempts:
        r = run(["mount", "-t", fs, "-o", opts, f"/dev/{dev}", mountpoint], timeout=120)
        if r.returncode == 0:
            break
    else:
        log(f"{dev}: mount failed: {r.stderr.strip()[:200]}")
        try:
            os.rmdir(mountpoint)
        except OSError:
            pass
        return 2
    log(f"{dev}: mounted {fstype} at {mountpoint}")
    return 0


def cmd_unmount(dev):
    if not valid_kernel_name(dev):
        return 2
    for d, mp, _ in mounts():
        if d == f"/dev/{dev}" and mp.startswith(MEDIA_ROOT + "/"):
            run(["umount", "-l", mp], timeout=60)
            try:
                os.rmdir(mp)
            except OSError:
                pass
            log(f"{dev}: unmounted {mp}")
    return 0


def drive_mount(path):
    """(mountpoint, fstype) when `path` is exactly a mounted drive under
    /media or /mnt, else None. Arguments come from vernis-api, so nothing
    else is accepted."""
    path = os.path.realpath(path)
    if not re.match(r"^/(media|mnt)/", path):
        return None
    for _, mp, fs in mounts():
        if mp == path:
            return mp, fs
    return None


def owned_dir(path, user):
    """Create directory `path` (or reuse a real one) and give it to `user`,
    never following a symlink: vernis-api's account can write in some of
    these places, and must not be able to aim a root chown elsewhere."""
    try:
        os.mkdir(path, 0o755)
    except FileExistsError:
        pass
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)  # fails on a symlink
    try:
        os.fchown(fd, user.pw_uid, user.pw_gid)
    finally:
        os.close(fd)


def cmd_prepare(path, folder="vernis-nfts"):
    """Make <drive>/<folder> writable for vernis-api's account."""
    found = drive_mount(path)
    user = owner()
    if not found or not user:
        return 2
    target = os.path.join(found[0], folder)
    if found[1] in POSIX_FS:
        try:
            owned_dir(target, user)
        except OSError as e:
            log(f"prepare {target}: {e}")
            return 2
    elif not os.path.islink(target):
        os.makedirs(target, exist_ok=True)  # FAT/exFAT/NTFS: owner comes from mount options
    return 0


# ---- IPFS store move -------------------------------------------------------

def write_status(**kw):
    """Status for Settings, in a root-owned folder vernis-api can read but
    not write (a file in /opt/vernis could be swapped for a symlink)."""
    kw["updated"] = int(time.time())
    os.makedirs(STATUS_DIR, mode=0o755, exist_ok=True)
    st = os.lstat(STATUS_DIR)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0:
        raise RuntimeError(f"{STATUS_DIR} is not a root-owned folder")
    fd, tmp = tempfile.mkstemp(dir=STATUS_DIR)
    with os.fdopen(fd, "w") as f:
        json.dump(kw, f)
    os.chmod(tmp, 0o644)
    os.replace(tmp, STATUS_FILE)


def dir_stats(path):
    files = size = 0
    for root, _, names in os.walk(path):
        for n in names:
            try:
                size += os.lstat(os.path.join(root, n)).st_size
                files += 1
            except OSError:
                pass
    return files, size


def as_user(user, cmd, **kw):
    """Run `cmd` as vernis-api's account, not root: copying the store only
    needs that account's own rights, so planted links can't reach root's."""
    return run(["runuser", "-u", user.pw_name, "--", *cmd], **kw)


def ipfs_online(user, timeout=90):
    """True once the restarted daemon answers on its API."""
    env = {"IPFS_PATH": os.path.join(user.pw_dir, ".ipfs"), "PATH": "/usr/local/bin:/usr/bin:/bin"}
    end = time.time() + timeout
    while time.time() < end:
        if as_user(user, ["ipfs", "swarm", "peers"], env=env, timeout=15).returncode == 0:
            return True
        time.sleep(3)
    return False


def store_location(link, uid):
    """The IPFS store's real folder, accepted only in the two shapes Vernis
    makes: ~/.ipfs as a real folder, or ~/.ipfs linking to
    <mounted drive>/vernis-ipfs. Anything else (a link to /etc, say) is
    refused, since this runs as root on a path vernis-api's account controls."""
    if os.path.islink(link):
        target = os.readlink(link)
        found = drive_mount(os.path.dirname(target))
        if (found and os.path.basename(target) == "vernis-ipfs"
                and os.path.join(found[0], "vernis-ipfs") == target
                and os.path.isdir(target) and not os.path.islink(target)):
            return target
        return None
    st = os.lstat(link) if os.path.lexists(link) else None
    if st and stat.S_ISDIR(st.st_mode) and st.st_uid == uid:
        return link
    return None


def copy_tree(user, src, dst):
    if shutil.which("rsync"):
        r = as_user(user, ["rsync", "-a", src.rstrip("/") + "/", dst.rstrip("/") + "/"])
    else:
        r = as_user(user, ["cp", "-a", src.rstrip("/") + "/.", dst])
    if r.returncode != 0:
        raise RuntimeError(f"copy failed: {r.stderr.strip()[:200]}")


def remove_tree(path):
    """rmtree refuses a symlink and removes nothing outside `path`."""
    if os.path.lexists(path):
        if os.path.islink(path):
            os.unlink(path)
        else:
            shutil.rmtree(path, ignore_errors=True)


def cmd_ipfs_move_run(target):
    """The move itself, in its own systemd unit so restarting vernis-api or
    ipfs can't kill it half-way. The old copy is kept until the node has
    started from the new one; any failure puts everything back."""
    user = owner()
    if not user:
        write_status(state="error", error="Vernis service user not found")
        return 2
    link = os.path.join(user.pw_dir, ".ipfs")
    current = store_location(link, user.pw_uid)
    if current is None:
        write_status(state="error", error="The IPFS store isn't where Vernis keeps it; fix it over SSH")
        return 2
    if target == "internal":
        dest = link
        if current == link:
            write_status(state="done", location="internal")
            return 0
    else:
        found = drive_mount(target)
        if not found or found[1] not in POSIX_FS:
            write_status(state="error", error="That drive can't hold the IPFS store (needs ext4, btrfs, xfs or f2fs)")
            return 2
        dest = os.path.join(found[0], "vernis-ipfs")
        if dest == current:
            write_status(state="done", location=found[0])
            return 0

    files, size = dir_stats(current)
    free = shutil.disk_usage(user.pw_dir if target == "internal" else found[0]).free
    if size + 512 * 1024**2 > free:
        write_status(state="error", error=f"Not enough free space: the IPFS store is "
                     f"{size / 1e9:.1f} GB and the drive has {free / 1e9:.1f} GB free")
        return 2

    staging = dest + ".moving"
    backup = link + ".before-move"
    if os.path.lexists(backup):
        write_status(state="error", error=f"{backup} is in the way; remove it over SSH first")
        return 2
    write_status(state="copying", files=files, bytes=size, target=target)
    run(["systemctl", "stop", "ipfs"], timeout=120)
    swapped = False
    try:
        remove_tree(staging)
        owned_dir(staging, user)
        copy_tree(user, current, staging)
        if dir_stats(staging) != (files, size):
            raise RuntimeError("the copy doesn't match the original")
        os.rename(link, backup)  # the symlink, or the real store folder
        swapped = True
        if target == "internal":
            os.rename(staging, link)
        else:
            remove_tree(dest)
            os.rename(staging, dest)
            os.symlink(dest, link)
            os.lchown(link, user.pw_uid, user.pw_gid)
        write_status(state="starting", target=target)
        run(["systemctl", "start", "ipfs"], timeout=120)
        if not ipfs_online(user):
            raise RuntimeError("the IPFS node did not start from the new location")
    except Exception as e:
        log(f"ipfs-move failed: {e}; rolling back")
        run(["systemctl", "stop", "ipfs"], timeout=120)
        if swapped:
            if target == "internal":
                remove_tree(link)          # the new real folder
            elif os.path.islink(link):
                os.unlink(link)
                remove_tree(dest)          # the unused copy on the drive
            os.rename(backup, link)
        remove_tree(staging)
        run(["systemctl", "start", "ipfs"], timeout=120)
        write_status(state="error", error=f"Move failed, nothing changed: {e}")
        return 2

    # Started fine from the new copy: the old one (validated above) is a duplicate.
    if target == "internal":
        os.unlink(backup)                  # the old symlink
        remove_tree(current)               # <drive>/vernis-ipfs
    else:
        remove_tree(backup)                # the old real folder
    write_status(state="done", location="internal" if target == "internal" else found[0])
    log(f"IPFS store now at {os.path.realpath(link)}")
    return 0


def cmd_ipfs_move(target):
    if target != "internal" and not drive_mount(target):
        return 2
    write_status(state="queued", target=target)
    r = run(["systemd-run", "--no-block", "--collect", "--unit", "vernis-ipfs-move",
             os.path.realpath(sys.argv[0]), "ipfs-move-run", target])
    if r.returncode != 0:
        write_status(state="error", error=f"could not start: {r.stderr.strip()[:200]}")
        return 2
    return 0


def main():
    if os.geteuid() != 0 or len(sys.argv) != 3:
        return 2
    cmd, arg = sys.argv[1], sys.argv[2]
    handlers = {"mount": cmd_mount, "unmount": cmd_unmount, "prepare": cmd_prepare,
                "prepare-backups": lambda p: cmd_prepare(p, "vernis-backups"),
                "ipfs-move": cmd_ipfs_move, "ipfs-move-run": cmd_ipfs_move_run}
    if cmd not in handlers:
        return 2
    # ipfs-move-run is only ever started by ipfs-move through systemd-run,
    # never through the sudo rule (which names the other commands only).
    return handlers[cmd](arg)


if __name__ == "__main__":
    sys.exit(main())
