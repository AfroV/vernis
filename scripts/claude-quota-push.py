#!/usr/bin/env python3
"""Vernis Work Mode — send the owner's Claude plan usage to their Vernis frame.

Runs on the owner's Mac. It asks Claude Code itself for the numbers with
`claude -p /usage` — Claude Code's own command, which sends nothing to the
model and costs nothing — and sends only the percentages and reset times to
the frame. This script never reads the Claude login.

Installed (by /api/workmode/installer.sh) as a Claude Code Stop hook, so it
runs after every reply in Claude Code, the desktop app's Code tab included.

  claude-quota-push.py --hook            from the hook: debounced, quiet
  claude-quota-push.py --once            fetch and send now
  claude-quota-push.py --once --dry-run  fetch and print, send nothing

Uses only the standard library plus macOS `curl`.
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

DIR = os.path.expanduser("~/Library/Application Support/vernis-quota")
CONFIG = os.path.join(DIR, "config.json")
STAMP = os.path.join(DIR, "last-run")
LOCK = os.path.join(DIR, "run.lock")
CHILD_ENV = "VERNIS_QUOTA_CHILD"   # set for our own `claude -p`, so its hook does nothing
MIN_GAP = 45                       # seconds between runs; a busy session ends many turns
UA = "vernis-quota-push/2.0"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
LINE = re.compile(
    r"^\s*Current (session|week)(?: \(([^)]*)\))?:\s*(\d+(?:\.\d+)?)%\s*used"
    r"(?:\s*·\s*resets\s+(.+?))?\s*$", re.I | re.M)
RESET = re.compile(
    r"^(?:([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?\s+at\s+)?"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:\(([^)]+)\))?\s*$", re.I)


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def load_config():
    with open(CONFIG) as f:
        return json.load(f)


def window_name(kind, scope):
    if kind.lower() == "session":
        return "five_hour"
    scope = (scope or "").strip().lower()
    if scope in ("", "all models"):
        return "seven_day"
    # "Sonnet only" -> seven_day_sonnet (the frame accepts [a-z0-9] suffixes)
    word = re.sub(r"[^a-z0-9]", "", scope.split()[0])[:24]
    return "seven_day_" + word if word else None


def parse_reset(text, now=None):
    """'Nov 18 at 5:20am (Europe/Oslo)' -> ISO 8601, or None if unreadable."""
    m = RESET.match((text or "").strip())
    if not m:
        return None
    mon, day, year, hour, minute, ampm, tzname = m.groups()
    tz = None
    if tzname and ZoneInfo:
        try:
            tz = ZoneInfo(tzname.strip())
        except Exception:
            tz = None
    now = now or datetime.now(tz)
    hour, minute = int(hour), int(minute or 0)
    if ampm:
        hour = hour % 12 + (12 if ampm.lower() == "pm" else 0)
    if hour > 23 or minute > 59:
        return None
    try:
        if mon:
            month = MONTHS.get(mon[:3].lower())
            if not month:
                return None
            dt = now.replace(year=int(year) if year else now.year, month=month, day=int(day),
                             hour=hour, minute=minute, second=0, microsecond=0)
            if not year and dt < now - timedelta(days=2):
                dt = dt.replace(year=dt.year + 1)      # "Jan 2" seen in late December
        else:
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if dt < now - timedelta(hours=1):
                dt += timedelta(days=1)
    except ValueError:
        return None
    return dt.isoformat()


def parse_usage(text):
    windows = {}
    for kind, scope, pct, reset in LINE.findall(text):
        name = window_name(kind, scope)
        if not name or name in windows:
            continue
        windows[name] = {"utilization": max(0.0, min(100.0, float(pct))),
                         "resets_at": parse_reset(reset) if reset else None}
    return windows


def fetch_usage(cfg):
    claude = cfg.get("claude") or "claude"
    env = dict(os.environ, **{CHILD_ENV: "1"})
    r = subprocess.run([claude, "-p", "/usage", "--strict-mcp-config", "--no-chrome"],
                       capture_output=True, text=True, timeout=90, cwd=DIR, env=env)
    windows = parse_usage(r.stdout)
    if not windows:
        hint = (r.stdout or r.stderr).strip().splitlines()[:2]
        raise RuntimeError("no usage in Claude Code's answer: " + " / ".join(hint)[:200])
    return windows


def push(cfg, windows):
    fd, path = tempfile.mkstemp(suffix=".json", dir=DIR)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(windows, f)
        hdr = "Authorization: Bearer %s\nContent-Type: application/json\n" % cfg["push_token"]
        r = subprocess.run(
            ["curl", "-sS", "--max-time", "15", "-A", UA, "-H", "@-", "-w", "\n%{http_code}",
             "--data-binary", "@" + path, cfg["url"].rstrip("/") + "/api/workmode/usage"],
            input=hdr, capture_output=True, text=True, timeout=30)   # token on stdin, not in `ps`
    finally:
        os.unlink(path)
    if r.returncode != 0:
        raise RuntimeError("network error: " + r.stderr.strip()[:200])
    text, _, code = r.stdout.rpartition("\n")
    if code == "403":
        raise RuntimeError("the frame refused the push token — Work Mode is off, or the token "
                           "was renewed. Re-run the install command from Settings → Work Mode.")
    if code != "200":
        raise RuntimeError(f"the frame answered HTTP {code}: {text[:120]}")


def summary(windows):
    return ", ".join(f"{n} {w['utilization']:.0f}% used" for n, w in windows.items())


def run(dry=False):
    cfg = load_config()
    windows = fetch_usage(cfg)
    if dry:
        log("dry run: " + summary(windows))
        print(json.dumps(windows, indent=2))
        return
    push(cfg, windows)
    log("sent: " + summary(windows))


def hook():
    """Called after every Claude Code reply. Must never slow Claude Code down or
    loop: our own `claude -p /usage` ends a turn too, and fires this hook."""
    if os.environ.get(CHILD_ENV):
        return 0
    try:
        sys.stdin.read()            # the hook's JSON; not needed
    except Exception:
        pass
    os.makedirs(DIR, exist_ok=True)
    with open(LOCK, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0                # another run is already busy
        try:
            if time.time() - os.path.getmtime(STAMP) < MIN_GAP:
                return 0
        except OSError:
            pass
        open(STAMP, "w").close()
        with open(os.path.join(DIR, "push.log"), "a") as out:
            sys.stdout = out
            try:
                run()
            except Exception as e:
                log(f"could not update the frame: {e}")
    return 0


def main(argv):
    if "--hook" in argv:
        return hook()
    if "--once" not in argv:
        print(__doc__)
        return 1
    try:
        run(dry="--dry-run" in argv)
    except Exception as e:
        log(f"could not update the frame: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
