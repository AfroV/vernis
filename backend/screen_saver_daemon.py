#!/usr/bin/env python3
"""
Vernis Screen Saver Daemon
Monitors user activity and turns off the screen after idle timeout.
Works on both X11 and Wayland (Pi 5 + Waveshare DPI displays).

Idle detection:
  - Wayland: Watches /opt/vernis/last-activity timestamp (updated by frontend touch events)
  - X11: Uses xprintidle (fallback)

Screen control:
  - Calls the Flask API /api/screen/off and /api/screen/on (handles pinctrl/sysfs/DPMS)

Usage: Run as a background service
"""

import subprocess
import json
import time
import os
import sys
import glob
import urllib.request
from pathlib import Path

# Configuration files
CONFIG_FILE = Path("/opt/vernis/screen-saver-config.json")
GALLERY_STATE_FILE = Path("/opt/vernis/gallery-state.json")
ACTIVITY_FILE = Path("/opt/vernis/last-activity")

# State tracking
screen_is_off = False
last_idle_ms = 0
API_BASE = "http://127.0.0.1:5000"


def get_config():
    """Load screen saver configuration"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {
        "enabled": False,
        "timeout_minutes": 10,
        "gallery_exempt": True
    }


def is_gallery_running():
    """Check if gallery mode is currently active"""
    if GALLERY_STATE_FILE.exists():
        try:
            with open(GALLERY_STATE_FILE, 'r') as f:
                return json.load(f).get('running', False)
        except:
            pass
    return False


def get_idle_time_ms():
    """Get idle time in milliseconds.
    Primary: check last-activity file timestamp (works on Wayland + X11).
    Fallback: xprintidle (X11 only).
    """
    # Method 1: Activity file timestamp (set by frontend on any touch/click)
    if ACTIVITY_FILE.exists():
        try:
            mtime = ACTIVITY_FILE.stat().st_mtime
            idle_ms = int((time.time() - mtime) * 1000)
            return max(0, idle_ms)
        except:
            pass

    # Method 2: xprintidle (X11 fallback)
    try:
        result = subprocess.run(
            ['xprintidle'],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, 'DISPLAY': ':0'}
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except:
        pass

    return 0


def call_screen_api(action):
    """Call the Flask API to turn screen on/off"""
    try:
        url = f"{API_BASE}/api/screen/{action}"
        req = urllib.request.Request(url, method='POST', data=b'')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get('success', False)
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] API call failed ({action}): {e}")
        # Direct pinctrl fallback if API is down
        try:
            if action == 'off':
                subprocess.run(["pinctrl", "set", "18", "op", "dh"], timeout=5)
            else:
                subprocess.run(["pinctrl", "set", "18", "op", "dl"], timeout=5)
            return True
        except:
            pass
    return False


def turn_screen_off():
    global screen_is_off
    if call_screen_api('off'):
        screen_is_off = True
        print(f"[{time.strftime('%H:%M:%S')}] Screen turned OFF")
    else:
        print(f"[{time.strftime('%H:%M:%S')}] Failed to turn screen off")


def turn_screen_on():
    global screen_is_off
    if call_screen_api('on'):
        screen_is_off = False
        print(f"[{time.strftime('%H:%M:%S')}] Screen turned ON")
    else:
        print(f"[{time.strftime('%H:%M:%S')}] Failed to turn screen on")


def main():
    global screen_is_off, last_idle_ms

    print("Vernis Screen Saver Daemon started")
    print(f"Config file: {CONFIG_FILE}")
    print(f"Activity file: {ACTIVITY_FILE}")

    # Wait for Flask API to be ready
    time.sleep(10)

    check_interval = 5  # Check every 5 seconds

    while True:
        try:
            config = get_config()

            if not config.get('enabled', False):
                if screen_is_off:
                    turn_screen_on()
                time.sleep(check_interval)
                continue

            timeout_ms = config.get('timeout_minutes', 10) * 60 * 1000
            gallery_exempt = config.get('gallery_exempt', True)

            if gallery_exempt and is_gallery_running():
                if screen_is_off:
                    turn_screen_on()
                time.sleep(check_interval)
                continue

            current_idle_ms = get_idle_time_ms()

            # User became active (idle time reset)
            if current_idle_ms < last_idle_ms and screen_is_off:
                turn_screen_on()

            # Idle timeout reached
            elif current_idle_ms >= timeout_ms and not screen_is_off:
                print(f"[{time.strftime('%H:%M:%S')}] Idle timeout reached ({config.get('timeout_minutes')} min)")
                turn_screen_off()

            last_idle_ms = current_idle_ms

        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Error in main loop: {e}")

        time.sleep(check_interval)


if __name__ == "__main__":
    main()
