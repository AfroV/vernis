#!/usr/bin/env python3
"""
Vernis Stream Receiver

Receives RTSP video stream from an external renderer (computer with GPU),
displays it fullscreen on the Pi via mpv. Falls back to local Chromium
rendering when the stream disconnects.

Architecture:
  - mediamtx (RTSP server) runs on Pi, accepts incoming streams
  - Computer pushes stream: ffmpeg ... -f rtsp rtsp://pi-ip:8554/live
  - This script monitors for active streams and switches display
  - Chromium stays running underneath; mpv overlays on top when streaming

Usage:
  python3 stream-receiver.py          # Run in foreground
  python3 stream-receiver.py --stop   # Stop receiver and clean up
"""

import subprocess, time, json, os, signal, sys, tarfile, urllib.request, shutil

MEDIAMTX_DIR = "/opt/vernis/mediamtx"
MEDIAMTX_BIN = os.path.join(MEDIAMTX_DIR, "mediamtx")
MEDIAMTX_CONF = os.path.join(MEDIAMTX_DIR, "mediamtx.yml")
MEDIAMTX_API = "http://localhost:9997"
STREAM_PATH = "live"
STATUS_FILE = "/opt/vernis/stream-status.json"
RTSP_AUTH_FILE = "/opt/vernis/stream-rtsp-auth.json"
PID_FILE = "/tmp/vernis-stream-receiver.pid"

mpv_proc = None
mediamtx_proc = None
running = True


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def write_status(enabled, active, url=""):
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump({"enabled": enabled, "active": active, "url": url}, f)
    except Exception:
        pass


def install_mediamtx():
    """Download mediamtx binary if not present."""
    if os.path.exists(MEDIAMTX_BIN):
        log("mediamtx already installed")
        return True

    os.makedirs(MEDIAMTX_DIR, exist_ok=True)

    arch = subprocess.check_output(["uname", "-m"]).decode().strip()
    if arch == "aarch64":
        arch_str = "linux_arm64v8"
    elif arch.startswith("arm"):
        arch_str = "linux_armv7"
    else:
        arch_str = "linux_amd64"

    version = "1.11.1"
    url = f"https://github.com/bluenviron/mediamtx/releases/download/v{version}/mediamtx_v{version}_{arch_str}.tar.gz"

    log(f"Downloading mediamtx v{version} for {arch_str}...")
    tar_path = os.path.join(MEDIAMTX_DIR, "mediamtx.tar.gz")

    try:
        urllib.request.urlretrieve(url, tar_path)
        with tarfile.open(tar_path) as tf:
            tf.extractall(MEDIAMTX_DIR, filter='data')
        os.remove(tar_path)
        os.chmod(MEDIAMTX_BIN, 0o755)
        log("mediamtx installed successfully")
        return True
    except Exception as e:
        log(f"Failed to install mediamtx: {e}")
        return False


def generate_rtsp_auth():
    """Generate random RTSP publish/read credentials and save to file."""
    import secrets
    auth = {"user": "vernis", "pass": secrets.token_urlsafe(24)}
    with open(RTSP_AUTH_FILE, "w") as f:
        json.dump(auth, f)
    try:
        os.chmod(RTSP_AUTH_FILE, 0o600)
    except Exception:
        pass
    log(f"RTSP auth generated (user: {auth['user']})")
    return auth


def load_rtsp_auth():
    """Load existing RTSP auth or generate new."""
    try:
        with open(RTSP_AUTH_FILE) as f:
            auth = json.load(f)
        if auth.get("user") and auth.get("pass"):
            return auth
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return generate_rtsp_auth()


def write_mediamtx_config(rtsp_auth):
    """Write mediamtx config with publish/read authentication."""
    config = f"""# Vernis Stream Receiver - mediamtx config
logLevel: warn
api: yes
apiAddress: :9997
rtsp: yes
rtspAddress: :8554
rtmp: no
hls: no
webrtc: no
srt: no

paths:
  live:
    source: publisher
    publishUser: {rtsp_auth['user']}
    publishPass: {rtsp_auth['pass']}
    readUser: {rtsp_auth['user']}
    readPass: {rtsp_auth['pass']}
"""
    with open(MEDIAMTX_CONF, "w") as f:
        f.write(config)


def start_mediamtx(rtsp_auth):
    """Start the mediamtx RTSP server."""
    global mediamtx_proc

    write_mediamtx_config(rtsp_auth)

    log("Starting mediamtx RTSP server on port 8554...")
    mediamtx_log = open("/tmp/mediamtx.log", "w")
    mediamtx_proc = subprocess.Popen(
        [MEDIAMTX_BIN, MEDIAMTX_CONF],
        cwd=MEDIAMTX_DIR,
        stdout=mediamtx_log,
        stderr=subprocess.STDOUT,
    )
    time.sleep(2)

    if mediamtx_proc.poll() is not None:
        log("mediamtx failed to start!")
        return False

    log("mediamtx running")
    return True


def check_stream_active():
    """Check if a stream is being pushed to mediamtx."""
    try:
        req = urllib.request.urlopen(f"{MEDIAMTX_API}/v3/paths/list", timeout=2)
        data = json.loads(req.read())
        for item in data.get("items", []):
            if item.get("readyTime"):
                return True
        return False
    except Exception:
        return False


def start_mpv(rtsp_auth):
    """Launch mpv to display the RTSP stream fullscreen."""
    global mpv_proc

    if mpv_proc and mpv_proc.poll() is None:
        return  # Already running

    log("Stream detected — launching mpv fullscreen")

    # Find the desktop user's Wayland socket (UID 1000 typically)
    env = os.environ.copy()
    xdg_dir = "/run/user/1000"
    wayland_sock = "wayland-0"
    # Auto-detect: find wayland-* socket in /run/user/1000/
    for f in os.listdir(xdg_dir) if os.path.isdir(xdg_dir) else []:
        if f.startswith("wayland-") and not f.endswith(".lock"):
            wayland_sock = f
            break
    env["WAYLAND_DISPLAY"] = wayland_sock
    env["XDG_RUNTIME_DIR"] = xdg_dir

    # Authenticated RTSP URL
    rtsp_url = f"rtsp://{rtsp_auth['user']}:{rtsp_auth['pass']}@localhost:8554/{STREAM_PATH}"

    log_f = open("/tmp/mpv-stream.log", "w")
    mpv_proc = subprocess.Popen(
        [
            "mpv",
            rtsp_url,
            "--fullscreen",
            "--no-osc",
            "--profile=low-latency",
            "--untimed",
            "--no-cache",
            "--demuxer-lavf-o=rtsp_transport=tcp",
            "--vo=gpu",
            "--hwdec=auto",
            "--force-window=yes",
        ],
        env=env,
        stdout=log_f,
        stderr=log_f,
    )


def stop_mpv():
    """Stop mpv, letting Chromium show through."""
    global mpv_proc

    if mpv_proc and mpv_proc.poll() is None:
        log("Stream lost — stopping mpv, falling back to local rendering")
        mpv_proc.terminate()
        try:
            mpv_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            mpv_proc.kill()
    mpv_proc = None

    # Refocus Chromium kiosk window (close stray dialogs first)
    try:
        env = os.environ.copy()
        env["XDG_RUNTIME_DIR"] = "/run/user/1000"
        subprocess.run(
            ["wlrctl", "toplevel", "close", "title:Open File"],
            env=env, capture_output=True, timeout=3,
        )
        subprocess.run(
            ["wlrctl", "toplevel", "focus", "app_id:chromium"],
            env=env, capture_output=True, timeout=3,
        )
    except Exception:
        pass


def cleanup(signum=None, frame=None):
    """Clean shutdown."""
    global running
    running = False
    log("Shutting down stream receiver...")

    stop_mpv()

    if mediamtx_proc and mediamtx_proc.poll() is None:
        mediamtx_proc.terminate()
        try:
            mediamtx_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            mediamtx_proc.kill()

    write_status(False, False)

    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

    log("Stream receiver stopped")
    sys.exit(0)


def stop_existing():
    """Stop any running instance."""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            log(f"Sent SIGTERM to PID {pid}")
            time.sleep(1)
        except (ProcessLookupError, ValueError):
            pass
        try:
            os.remove(PID_FILE)
        except FileNotFoundError:
            pass

    # Also kill any leftover mediamtx
    subprocess.run(["pkill", "-f", "mediamtx"], capture_output=True)


def get_pi_ip():
    """Get the Pi's LAN IP address."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "pi-ip"


def main():
    if "--stop" in sys.argv:
        stop_existing()
        write_status(False, False)
        return

    # Stop any existing instance first
    stop_existing()

    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # Generate or load RTSP auth
    rtsp_auth = load_rtsp_auth()

    # Install mediamtx if needed
    if not install_mediamtx():
        log("Cannot start without mediamtx")
        write_status(False, False)
        return

    # Start RTSP server with auth
    if not start_mediamtx(rtsp_auth):
        write_status(False, False)
        return

    # Register cleanup
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    pi_ip = get_pi_ip()
    stream_url = f"rtsp://{pi_ip}:8554/{STREAM_PATH}"
    log(f"Ready — push stream to: {stream_url} (auth required)")
    write_status(True, False, stream_url)

    # Main loop: watch for streams
    stream_was_active = False
    consecutive_inactive = 0

    while running:
        try:
            active = check_stream_active()

            if active and not stream_was_active:
                # Stream just started
                consecutive_inactive = 0
                start_mpv(rtsp_auth)
                stream_was_active = True
                write_status(True, True, stream_url)
                log("Streaming active")

            elif not active and stream_was_active:
                # Stream might have dropped — wait a few checks before killing mpv
                consecutive_inactive += 1
                if consecutive_inactive >= 3:  # 6 seconds of no stream
                    stop_mpv()
                    stream_was_active = False
                    write_status(True, False, stream_url)

            elif active:
                consecutive_inactive = 0
                # Check if mpv died unexpectedly
                if mpv_proc and mpv_proc.poll() is not None:
                    log("mpv crashed, restarting...")
                    start_mpv(rtsp_auth)

            # Check if mediamtx died
            if mediamtx_proc and mediamtx_proc.poll() is not None:
                log("mediamtx died, restarting...")
                start_mediamtx()

            time.sleep(2)

        except Exception as e:
            log(f"Error in main loop: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
