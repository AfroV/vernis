#!/usr/bin/env python3
"""
Vernis Remote Renderer — Secure Docker Server

Runs inside a Docker container with Xvfb. Receives render requests from Pi
backend (authenticated with API key), launches Chromium on the virtual display,
and streams via RTSP back to the Pi.

Security:
  - All endpoints require Authorization: Bearer <key>
  - URL allowlist prevents arbitrary page rendering
  - Designed to be called only by the Pi backend (proxy pattern)
"""

import http.server
import json
import subprocess
import os
import signal
import sys
import socket
import time
import urllib.error
from urllib.parse import urlparse

PORT = 8555
API_KEY = os.environ.get("VERNIS_API_KEY", "")

# Chromium/ffmpeg processes
chrome_proc = None
ffmpeg_proc = None

# RTSP auth (received from Pi during registration)
rtsp_user = ""
rtsp_pass = ""

# URL allowlist — only these domains can be rendered
ALLOWED_DOMAINS = [
    "generator.artblocks.io",
    "artblocks.io",
    "media.artblocks.io",
    "api.artblocks.io",
    "token.artblocks.io",
    "ipfs.io",
    "gateway.pinata.cloud",
    "cloudflare-ipfs.com",
    "dweb.link",
    "w3s.link",
    "nftstorage.link",
]


def get_local_ip():
    """Get this machine's LAN IP (or Docker host IP override)."""
    override = os.environ.get("RENDERER_IP", "")
    if override:
        return override
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_allowed_domains():
    """Build full allowlist including env var extras."""
    domains = list(ALLOWED_DOMAINS)
    extra = os.environ.get("VERNIS_EXTRA_DOMAINS", "")
    for d in extra.split(","):
        d = d.strip()
        if d:
            domains.append(d)
    return domains


def validate_api_key(handler):
    """Check Authorization header."""
    auth = handler.headers.get("Authorization", "")
    import hmac
    return hmac.compare_digest(auth.encode(), f"Bearer {API_KEY}".encode())


def validate_url(url):
    """Check URL against allowlist. Returns (ok, error_message)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL"

    if parsed.scheme not in ("http", "https"):
        return False, "Only HTTP/HTTPS URLs allowed"

    host = parsed.hostname
    if not host:
        return False, "Invalid URL: no hostname"

    for domain in get_allowed_domains():
        if host == domain or host.endswith("." + domain):
            return True, ""

    return False, f"Domain '{host}' not in allowlist"


def stop_stream():
    """Stop Chromium and ffmpeg."""
    global chrome_proc, ffmpeg_proc
    for proc, name in [(ffmpeg_proc, "ffmpeg"), (chrome_proc, "Chromium")]:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            print(f"  Stopped {name}")
    chrome_proc = None
    ffmpeg_proc = None


def start_stream(url, pi_ip, width=720, height=720, fps=20, bitrate="4M", rtsp_port=8554):
    """Start Chromium + ffmpeg streaming to the Pi via RTSP."""
    global chrome_proc, ffmpeg_proc

    stop_stream()

    # Use authenticated RTSP URL if credentials available
    if rtsp_user and rtsp_pass:
        rtsp_url = f"rtsp://{rtsp_user}:{rtsp_pass}@{pi_ip}:{rtsp_port}/live"
    else:
        rtsp_url = f"rtsp://{pi_ip}:{rtsp_port}/live"

    print(f"  Starting stream: {url}")
    print(f"  Resolution: {width}x{height} @ {fps}fps, Target: {rtsp_url}")

    # Detect GPU: if /dev/dri exists, a real GPU is available (e.g. --gpus all)
    has_gpu = os.path.exists("/dev/dri")

    chrome_args = [
        "chromium",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        f"--window-size={width},{height}",
        "--kiosk",
        "--autoplay-policy=no-user-gesture-required",
        "--disable-features=RendererCodeIntegrity",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    if has_gpu:
        # Real GPU available — use hardware acceleration
        chrome_args += [
            "--use-gl=angle",
            "--use-angle=gl",
            "--enable-gpu-rasterization",
            "--ignore-gpu-blocklist",
        ]
        print(f"  GPU detected — using hardware acceleration")
    else:
        # No GPU — fall back to SwiftShader (CPU-based GL)
        chrome_args += [
            "--disable-software-rasterizer",
            "--use-gl=angle",
            "--use-angle=swiftshader",
        ]
        print(f"  No GPU — using SwiftShader (software rendering)")

    # Block access to private/internal IPs to prevent SSRF via page navigations
    chrome_args += [
        "--host-resolver-rules=MAP 10.0.0.0/8 ~NOTFOUND, MAP 172.16.0.0/12 ~NOTFOUND, MAP 192.168.0.0/16 ~NOTFOUND, MAP 169.254.0.0/16 ~NOTFOUND, MAP 127.0.0.0/8 ~NOTFOUND",
        "--disable-webrtc",
    ]

    chrome_args.append(url)

    # Launch Chromium on the Xvfb virtual display (DISPLAY=:99 set by entrypoint)
    chrome_proc = subprocess.Popen(
        chrome_args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for Chromium to render
    import time
    time.sleep(4)

    if chrome_proc.poll() is not None:
        return {"error": "Chromium failed to start"}

    # Hide cursor off-screen
    subprocess.run(["xdotool", "mousemove", "--screen", "0", "9999", "9999"],
                   capture_output=True)

    # Capture virtual framebuffer with ffmpeg
    ffmpeg_log = open("/tmp/vernis-ffmpeg.log", "w")
    ffmpeg_proc = subprocess.Popen(
        [
            "ffmpeg",
            "-f", "x11grab",
            "-framerate", str(fps),
            "-video_size", f"{width}x{height}",
            "-i", ":99.0",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-b:v", bitrate,
            "-pix_fmt", "yuv420p",
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            rtsp_url,
        ],
        stdout=ffmpeg_log,
        stderr=ffmpeg_log,
    )

    return {
        "ok": True,
        "url": url,
        "resolution": f"{width}x{height}",
        "rtsp": rtsp_url,
    }


class RendererHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Quiet default logging

    def _json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path == "/":
            # Public — no auth required, no sensitive info
            self._json(200, {"name": "Vernis Remote Renderer", "version": "1.0"})
            return

        if not validate_api_key(self):
            self._json(401, {"error": "Unauthorized"})
            return

        if self.path == "/status":
            streaming = ffmpeg_proc is not None and ffmpeg_proc.poll() is None
            self._json(200, {
                "available": True,
                "streaming": streaming,
            })
        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self):
        if not validate_api_key(self):
            self._json(401, {"error": "Unauthorized"})
            return

        if self.path == "/start":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}

            url = body.get("url", "")
            pi_ip = body.get("piIp", "")

            if not url or not pi_ip:
                self._json(400, {"error": "url and piIp required"})
                return

            # Validate URL against allowlist
            ok, err = validate_url(url)
            if not ok:
                print(f"  BLOCKED: {url} — {err}")
                self._json(403, {"error": err})
                return

            result = start_stream(
                url=url,
                pi_ip=pi_ip,
                width=body.get("width", 720),
                height=body.get("height", 720),
                fps=body.get("fps", 30),
                bitrate=body.get("bitrate", "4M"),
            )
            code = 200 if "ok" in result else 500
            self._json(code, result)

        elif self.path == "/stop":
            stop_stream()
            self._json(200, {"ok": True})

        else:
            self._json(404, {"error": "Not found"})


def register_with_pi(pi_ip, local_ip, port, api_key):
    """Register this renderer with the Pi. Returns True on success, 'pairing' if waiting."""
    global rtsp_user, rtsp_pass
    import urllib.request
    url = f"http://{pi_ip}/api/stream/register-renderer"
    data = json.dumps({"ip": local_ip, "port": port, "apiKey": api_key}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        if resp.status == 200:
            result = json.loads(resp.read())
            # Store RTSP auth credentials from Pi
            rtsp_user = result.get("rtspUser", "")
            rtsp_pass = result.get("rtspPass", "")
            print(f"  Registered with Pi at {pi_ip}")
            if rtsp_user:
                print(f"  RTSP auth received")
            return True
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return "pairing"
        print(f"  Warning: Could not register with Pi ({e})")
    except Exception as e:
        print(f"  Warning: Could not register with Pi ({e})")
    return False


def unregister_from_pi(pi_ip):
    """Unregister from a Pi."""
    import urllib.request
    url = f"http://{pi_ip}/api/stream/unregister-renderer"
    req = urllib.request.Request(url, method="POST")
    try:
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def main():
    if not API_KEY:
        print("ERROR: VERNIS_API_KEY not set")
        sys.exit(1)

    port = int(os.environ.get("VERNIS_PORT", PORT))
    local_ip = get_local_ip()

    # Parse Pi IPs from environment
    pi_ips_str = os.environ.get("PI_IP", "")
    pi_ips = [ip.strip() for ip in pi_ips_str.split(",") if ip.strip()]

    def shutdown(sig, frame):
        print("\nShutting down...")
        stop_stream()
        for pip in pi_ips:
            unregister_from_pi(pip)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    server = http.server.HTTPServer(("0.0.0.0", port), RendererHandler)
    print(f"  Listening on http://{local_ip}:{port}")
    print(f"  Allowed domains: {', '.join(get_allowed_domains())}")
    print("")

    if pi_ips:
        for pip in pi_ips:
            result = register_with_pi(pip, local_ip, port, API_KEY)
            if result == "pairing":
                print(f"  Waiting for pairing on {pip}...")
                print(f"  Open Settings on the Pi and tap 'Pair Renderer'")
                while result == "pairing":
                    time.sleep(5)
                    result = register_with_pi(pip, local_ip, port, API_KEY)
            elif not result:
                print(f"  Will retry registration with {pip} in background")
    else:
        print("  No PI_IP set — waiting for manual registration")

    print(f"  Ready for stream requests...")
    print("")
    server.serve_forever()


if __name__ == "__main__":
    main()
