#!/usr/bin/env python3
"""
Hue Entertainment API streaming daemon for Vernis.

Manages a DTLS streaming connection to the Hue Bridge via the
hue-stream helper binary. Colors are received via a simple JSON
file that the Flask backend writes to.

The daemon:
1. Reads /opt/vernis/hue-settings.json for credentials
2. Watches /opt/vernis/hue-stream-color.json for color updates
3. Pipes colors to the hue-stream binary via stdin
4. Handles restarts and cleanup

Usage:
    python3 hue-entertainment-daemon.py [--area <area_id>]
"""

import json
import os
import signal
import subprocess
import sys
import time

SETTINGS_FILE = "/opt/vernis/hue-settings.json"
COLOR_FILE = "/opt/vernis/hue-stream-color.json"
STREAM_BINARY = "/opt/vernis/scripts/hue-stream"
POLL_INTERVAL = 0.04  # 25 Hz polling

running = True


def handle_signal(sig, frame):
    global running
    running = False


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except Exception as e:
        log(f"Error loading settings: {e}")
        return {}


def read_color():
    """Read the current target color from the color file."""
    try:
        with open(COLOR_FILE) as f:
            data = json.load(f)
        return data.get("r", 0), data.get("g", 0), data.get("b", 0), data.get("ts", 0)
    except (FileNotFoundError, json.JSONDecodeError):
        return None, None, None, 0


def _hue_api_get(bridge_ip, api_key, path):
    """Make a GET request to the Hue Bridge CLIP v2 API."""
    import urllib.request
    import ssl
    url = f"https://{bridge_ip}/clip/v2/resource/{path}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("hue-application-key", api_key)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
        return json.loads(response.read().decode())


def find_entertainment_area(settings, preferred_area=None):
    """Find the best entertainment area to use."""
    bridge_ip = settings.get("bridge_ip")
    api_key = settings.get("api_key")
    if not bridge_ip or not api_key:
        return None, 0

    try:
        data = _hue_api_get(bridge_ip, api_key, "entertainment_configuration")
        areas = data.get("data", [])
        if not areas:
            return None, 0

        # Prefer the specified area
        if preferred_area:
            for area in areas:
                if area["id"] == preferred_area:
                    return area["id"], len(area.get("channels", []))

        # Prefer "monitor" type areas (designed for screen sync)
        for area in areas:
            if area.get("configuration_type") == "monitor":
                return area["id"], len(area.get("channels", []))

        # Fall back to first area
        area = areas[0]
        return area["id"], len(area.get("channels", []))

    except Exception as e:
        log(f"Error finding entertainment areas: {e}")
        return None, 0


def is_entertainment_active(bridge_ip, api_key, area_id):
    """Check if the entertainment area is still in streaming state on the bridge."""
    try:
        data = _hue_api_get(bridge_ip, api_key, f"entertainment_configuration/{area_id}")
        items = data.get("data", [])
        if items:
            status = items[0].get("status", "inactive")
            return status == "active"
    except Exception as e:
        log(f"Could not check entertainment status: {e}")
    return False


def main():
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Parse args
    preferred_area = None
    if "--area" in sys.argv:
        idx = sys.argv.index("--area")
        if idx + 1 < len(sys.argv):
            preferred_area = sys.argv[idx + 1]

    log("Hue Entertainment daemon starting...")

    # Check for stream binary
    if not os.path.isfile(STREAM_BINARY):
        log(f"Error: {STREAM_BINARY} not found. Compile with:")
        log(f"  gcc -O2 -o {STREAM_BINARY} /opt/vernis/scripts/hue-stream.c -lssl -lcrypto")
        sys.exit(1)

    # Load settings
    settings = load_settings()
    bridge_ip = settings.get("bridge_ip")
    api_key = settings.get("api_key")
    clientkey = settings.get("clientkey")

    if not bridge_ip or not api_key:
        log("Error: Hue Bridge not connected. Run connect first.")
        sys.exit(1)

    if not clientkey:
        log("Error: No clientkey found. Register for Entertainment API first.")
        log("  curl -X POST http://localhost:5000/api/hue/entertainment/register")
        log("  (press bridge button first)")
        sys.exit(1)

    # Find entertainment area
    area_id, num_channels = find_entertainment_area(settings, preferred_area)
    if not area_id:
        log("Error: No entertainment areas found on bridge.")
        log("Create one in the Philips Hue app first.")
        sys.exit(1)

    log(f"Using entertainment area: {area_id} ({num_channels} channels)")
    log(f"Bridge: {bridge_ip}")

    # Start the streaming process
    proc = None
    last_color_ts = 0
    last_r, last_g, last_b = 0, 0, 0
    restart_count = 0

    while running:
        if proc is None or proc.poll() is not None:
            if proc is not None:
                log(f"Stream process exited with code {proc.returncode}")

                # Check if bridge still has entertainment active
                # If not, user likely stopped from Philips app — respect that
                if not is_entertainment_active(bridge_ip, api_key, area_id):
                    log("Entertainment area no longer active on bridge (stopped externally). Exiting.")
                    break

                # Also stop if color file was removed (Vernis stop endpoint)
                if not os.path.isfile(COLOR_FILE):
                    log("Color file removed. Exiting.")
                    break

                restart_count += 1
                if restart_count > 5:
                    log("Too many restarts, waiting 30s...")
                    time.sleep(30)
                    restart_count = 0

            log("Starting hue-stream process...")
            try:
                proc = subprocess.Popen(
                    [STREAM_BINARY, bridge_ip, api_key, clientkey,
                     area_id, str(num_channels)],
                    stdin=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1  # line-buffered
                )
                log(f"Stream process started (PID {proc.pid})")
                time.sleep(1)  # Let it handshake

                # Check if it's still running
                if proc.poll() is not None:
                    stderr = proc.stderr.read()
                    log(f"Stream process died immediately: {stderr}")
                    proc = None
                    time.sleep(5)
                    continue
                else:
                    restart_count = 0

            except Exception as e:
                log(f"Failed to start stream process: {e}")
                proc = None
                time.sleep(5)
                continue

        # Read color file
        r, g, b, ts = read_color()
        if r is not None and ts > last_color_ts:
            last_color_ts = ts
            last_r, last_g, last_b = r, g, b

            # Send to stream process
            try:
                proc.stdin.write(f"{r} {g} {b}\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError):
                log("Pipe broken, restarting stream...")
                proc = None
                continue

        time.sleep(POLL_INTERVAL)

    # Cleanup
    log("Shutting down...")
    if proc and proc.poll() is None:
        try:
            proc.stdin.write("QUIT\n")
            proc.stdin.flush()
            proc.wait(timeout=5)
        except Exception:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()

    log("Done.")


if __name__ == "__main__":
    main()
