# Docker Remote Rendering — Re-insertion Guide

Removed from v1 release to reduce attack surface. Follow these steps to re-enable.

## 1. Install script (install-vernis.sh)

Add after the HDMI hotplug step (Step 10.5), before Step 11:

```bash
# Step 10.7: Setup stream receiver (remote rendering via Docker)
echo "Setting up stream receiver service..."
sudo tee /etc/systemd/system/vernis-stream.service > /dev/null << STREAM_EOF
[Unit]
Description=Vernis Stream Receiver
After=network-online.target vernis-api.service
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
ExecStart=/usr/bin/python3 /opt/vernis/scripts/stream-receiver.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=vernis-stream

[Install]
WantedBy=multi-user.target
STREAM_EOF
sudo systemctl daemon-reload
sudo systemctl enable vernis-stream
echo "Stream receiver service enabled"
```

Also add the RTSP firewall rule in Step 13 (firewall section):
```bash
sudo ufw allow 8554/tcp comment "RTSP Stream"
```

Copy `stream-receiver.py` to `/opt/vernis/scripts/`.

## 2. Backend (app.py)

Insert this block after the HTTPS/Caddy section, before the `/api/diagnostics` endpoint:

```python
# ========================================
# Stream Receiver (external GPU rendering)
# ========================================
STREAM_STATUS_FILE = "/opt/vernis/stream-status.json"
STREAM_RECEIVER_SCRIPT = "/opt/vernis/scripts/stream-receiver.py"

@app.route("/api/stream/status")
def stream_status():
    """Get stream receiver status."""
    try:
        with open(STREAM_STATUS_FILE) as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"enabled": False, "active": False, "url": ""})

@app.route("/api/stream/toggle", methods=["POST"])
def stream_toggle():
    """Enable or disable the stream receiver."""
    data = request.get_json(force=True)
    enable = data.get("enable", False)

    if enable:
        subprocess.run(["systemctl", "start", "vernis-stream"], capture_output=True, timeout=15)
        import time as _time
        _time.sleep(5)
        try:
            with open(STREAM_STATUS_FILE) as f:
                return jsonify(json.load(f))
        except Exception:
            return jsonify({"enabled": True, "active": False, "url": ""})
    else:
        subprocess.run(["systemctl", "stop", "vernis-stream"], capture_output=True, timeout=15)
        return jsonify({"enabled": False, "active": False, "url": ""})


@app.route("/api/stream/test", methods=["POST"])
def stream_test():
    """Send a 10-second test pattern through the RTSP pipeline."""
    try:
        with open(STREAM_STATUS_FILE) as f:
            status = json.load(f)
        if not status.get("enabled"):
            return jsonify({"error": "Stream receiver not enabled"}), 400
    except Exception:
        return jsonify({"error": "Stream receiver not enabled"}), 400

    subprocess.run(["pkill", "-f", "testsrc2.*rtsp"], capture_output=True, timeout=5)

    subprocess.Popen(
        ["ffmpeg", "-re", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30",
         "-t", "15", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
         "-f", "rtsp", "-rtsp_transport", "tcp", "rtsp://localhost:8554/live"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return jsonify({"ok": True, "duration": 15})


RENDERER_FILE = "/opt/vernis/stream-renderer.json"
PAIRING_FILE = "/opt/vernis/stream-pairing.json"
RTSP_AUTH_FILE = "/opt/vernis/stream-rtsp-auth.json"

def _stream_get_local_ip():
    """Get this Pi's LAN IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def _stream_load_renderer():
    """Load renderer info from file. Returns dict or None."""
    try:
        with open(RENDERER_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

@app.route("/api/stream/pairing/start", methods=["POST"])
def stream_pairing_start():
    """Open a time-limited pairing window for renderer registration."""
    duration = 120
    expires = time.time() + duration
    with open(PAIRING_FILE, "w") as f:
        json.dump({"active": True, "expires": expires}, f)
    return jsonify({"ok": True, "expires_in": duration})

@app.route("/api/stream/pairing/status")
def stream_pairing_status():
    """Check if pairing window is active."""
    try:
        with open(PAIRING_FILE) as f:
            data = json.load(f)
        if data.get("active") and data.get("expires", 0) > time.time():
            remaining = int(data["expires"] - time.time())
            return jsonify({"active": True, "remaining": remaining})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return jsonify({"active": False})

@app.route("/api/stream/register-renderer", methods=["POST"])
def stream_register_renderer():
    """Register a remote render server (requires active pairing window)."""
    try:
        with open(PAIRING_FILE) as f:
            pairing = json.load(f)
        if not pairing.get("active") or pairing.get("expires", 0) < time.time():
            return jsonify({"error": "Pairing not active"}), 403
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({"error": "Pairing not active"}), 403

    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    port = data.get("port", 8555)
    api_key = data.get("apiKey", "").strip()
    if not ip:
        return jsonify({"error": "ip required"}), 400
    if not api_key:
        return jsonify({"error": "apiKey required"}), 400
    info = {"ip": ip, "port": int(port), "apiKey": api_key}
    with open(RENDERER_FILE, "w") as f:
        json.dump(info, f)
    try:
        os.chmod(RENDERER_FILE, 0o600)
    except Exception:
        pass
    try:
        os.remove(PAIRING_FILE)
    except FileNotFoundError:
        pass

    resp = {"ok": True, "ip": ip, "port": int(port)}
    try:
        with open(RTSP_AUTH_FILE) as f:
            rtsp_auth = json.load(f)
        resp["rtspUser"] = rtsp_auth.get("user", "")
        resp["rtspPass"] = rtsp_auth.get("pass", "")
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return jsonify(resp)

@app.route("/api/stream/unregister-renderer", methods=["POST"])
def stream_unregister_renderer():
    """Unregister the remote render server."""
    try:
        os.remove(RENDERER_FILE)
    except FileNotFoundError:
        pass
    return jsonify({"ok": True})

@app.route("/api/stream/renderer", methods=["GET"])
def stream_get_renderer():
    """Get registered remote render server info (no API key exposed)."""
    renderer = _stream_load_renderer()
    if not renderer:
        return jsonify({}), 404
    return jsonify({"ip": renderer["ip"], "port": renderer.get("port", 8555)})

@app.route("/api/stream/remote/start", methods=["POST"])
def stream_remote_start():
    """Proxy start-stream request to renderer (API key stays server-side)."""
    renderer = _stream_load_renderer()
    if not renderer:
        return jsonify({"error": "No renderer registered"}), 404

    data = request.get_json(force=True)
    url = data.get("url", "")
    if not url:
        return jsonify({"error": "url required"}), 400

    pi_ip = _stream_get_local_ip()
    payload = json.dumps({
        "url": url,
        "piIp": pi_ip,
        "width": data.get("width", 720),
        "height": data.get("height", 720),
        "fps": data.get("fps", 30),
        "bitrate": data.get("bitrate", "4M"),
    }).encode()

    renderer_url = f"http://{renderer['ip']}:{renderer.get('port', 8555)}/start"
    api_key = renderer.get("apiKey", "")

    try:
        import urllib.request
        req = urllib.request.Request(
            renderer_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        return jsonify(result)
    except urllib.error.URLError as e:
        return jsonify({"error": f"Cannot reach renderer: {e}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stream/remote/stop", methods=["POST"])
def stream_remote_stop():
    """Proxy stop-stream request to renderer."""
    renderer = _stream_load_renderer()
    if not renderer:
        return jsonify({"error": "No renderer registered"}), 404

    renderer_url = f"http://{renderer['ip']}:{renderer.get('port', 8555)}/stop"
    api_key = renderer.get("apiKey", "")

    try:
        import urllib.request
        req = urllib.request.Request(
            renderer_url,
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route("/api/stream/remote/status")
def stream_remote_status():
    """Proxy status check to renderer."""
    renderer = _stream_load_renderer()
    if not renderer:
        return jsonify({"available": False}), 404

    renderer_url = f"http://{renderer['ip']}:{renderer.get('port', 8555)}/status"
    api_key = renderer.get("apiKey", "")

    try:
        import urllib.request
        req = urllib.request.Request(
            renderer_url,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
        return jsonify(result)
    except Exception:
        return jsonify({"available": False}), 502
```

Also add to `_AUTH_EXEMPT_PATHS`:
```python
'/api/stream/renderer', '/api/stream/remote/status',
```

## 3. Settings HTML (settings.html)

Insert this card inside the Lab/Streaming settings section (after the Entertainment Streaming card):

```html
<div class="settings-card">
  <h3>Remote Rendering</h3>
  <p style="margin-bottom: 16px; color: var(--text-secondary); font-size: 14px;">
    Use a powerful computer to render generative art and stream it here.
    Automatically falls back to local rendering when disconnected.
  </p>
  <div class="toggle-group">
    <div class="toggle-label">
      <div>Enable Remote Rendering</div>
      <div class="small">Starts RTSP server to receive external streams</div>
    </div>
    <div class="toggle" id="toggle-stream-receiver" onclick="toggleStreamReceiver(this)"></div>
  </div>
  <div id="stream-info" style="display: none; margin-top: 16px;">
    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 14px;">
      <div id="stream-status-dot" style="width: 10px; height: 10px; border-radius: 50%; background: #f59e0b; flex-shrink: 0;"></div>
      <div id="stream-status-text" style="font-size: 14px; font-weight: 600;">Waiting for stream...</div>
    </div>
    <div style="padding: 14px; background: rgba(255,255,255,0.04); border-radius: 8px; border: 1px solid var(--border-light, #333); margin-bottom: 12px;">
      <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 6px;">RTSP Address</div>
      <div style="display: flex; align-items: center; gap: 8px;">
        <code id="stream-url" style="font-size: 13px; background: rgba(0,0,0,0.3); padding: 6px 10px; border-radius: 4px; flex: 1; word-break: break-all;"></code>
        <button class="btn btn-secondary" style="padding: 8px 14px; font-size: 12px;" onclick="copyToClipboard(document.getElementById('stream-url').textContent)">Copy</button>
      </div>
    </div>
    <div style="padding: 14px; background: rgba(255,255,255,0.04); border-radius: 8px; border: 1px solid var(--border-light, #333); margin-bottom: 14px;">
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
        <div>
          <div style="font-size: 13px; font-weight: 600;">Pair Renderer</div>
          <div style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;" id="pairing-hint">Opens a 2-minute window for a Docker renderer to connect</div>
        </div>
        <button class="btn btn-secondary" id="pairing-btn" style="padding: 10px 18px; font-size: 13px; white-space: nowrap;" onclick="startPairing()">Pair</button>
      </div>
      <div id="pairing-status" style="display: none; margin-top: 10px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <div id="pairing-dot" style="width: 8px; height: 8px; border-radius: 50%; background: #f59e0b; animation: pulse 1.5s infinite;"></div>
          <span id="pairing-text" style="font-size: 13px; color: #f59e0b;">Waiting for renderer...</span>
          <span id="pairing-timer" style="font-size: 12px; color: var(--text-secondary); margin-left: auto;"></span>
        </div>
      </div>
    </div>
    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 14px;">
      <button class="btn btn-secondary" id="stream-test-btn" style="padding: 10px 18px; font-size: 13px; display: flex; align-items: center; gap: 6px;" onclick="sendTestStream()">
        <span style="font-size: 16px;">&#9654;</span> Test Stream
      </button>
      <span id="stream-test-status" style="font-size: 13px; color: var(--text-secondary);"></span>
    </div>
    <details style="padding: 14px; background: rgba(255,255,255,0.04); border-radius: 8px; border: 1px solid var(--border-light, #333);">
      <summary style="cursor: pointer; font-size: 13px; font-weight: 600; color: var(--text-primary); user-select: none;">Computer Setup Guide</summary>
      <div style="margin-top: 12px;">
        <div style="font-size: 12px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px;">Docker Container (Recommended)</div>
        <p style="font-size: 12px; color: var(--text-secondary); margin: 0 0 6px 0;">Runs fully headless in a container. No screen recording needed.</p>
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
          <code id="stream-cmd-docker" style="font-size: 11px; background: rgba(0,0,0,0.3); padding: 6px 10px; border-radius: 4px; flex: 1; word-break: break-all;"></code>
          <button class="btn btn-secondary" style="padding: 6px 12px; font-size: 11px;" onclick="copyToClipboard(document.getElementById('stream-cmd-docker').textContent)">Copy</button>
        </div>
        <p style="font-size: 11px; color: var(--text-secondary); margin: 0 0 14px 0;">
          Requires <a href="https://www.docker.com/products/docker-desktop/" target="_blank" style="color: var(--accent);">Docker Desktop</a>. Build first: <code style="font-size: 10px; background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 3px;">docker build -t vernis-renderer extras/docker-renderer/</code>
        </p>
        <div style="border-top: 1px solid var(--border-light, #333); margin: 12px 0; padding-top: 12px;">
          <div style="font-size: 12px; font-weight: 600; margin-bottom: 8px;">Manual ffmpeg</div>
        </div>
        <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;">macOS</div>
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
          <code id="stream-cmd-mac" style="font-size: 11px; background: rgba(0,0,0,0.3); padding: 6px 10px; border-radius: 4px; flex: 1; word-break: break-all;"></code>
          <button class="btn btn-secondary" style="padding: 6px 12px; font-size: 11px;" onclick="copyToClipboard(document.getElementById('stream-cmd-mac').textContent)">Copy</button>
        </div>
        <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;">Linux</div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <code id="stream-cmd-linux" style="font-size: 11px; background: rgba(0,0,0,0.3); padding: 6px 10px; border-radius: 4px; flex: 1; word-break: break-all;"></code>
          <button class="btn btn-secondary" style="padding: 6px 12px; font-size: 11px;" onclick="copyToClipboard(document.getElementById('stream-cmd-linux').textContent)">Copy</button>
        </div>
      </div>
    </details>
  </div>
</div>
```

## 4. Settings JS (settings.html)

Add this JavaScript in the `<script>` section (before the Performance Profile section):

```javascript
// ========================================
// Remote Rendering
// ========================================
var streamPollInterval = null;

function populateStreamCommands(url) {
  document.getElementById("stream-url").textContent = url;
  var ip = url.replace(/^rtsp:\/\//, '').replace(/:.*$/, '');
  document.getElementById("stream-cmd-docker").textContent =
    'docker run --rm -e PI_IP=' + ip + ' -p 8555:8555 vernis-renderer';
  document.getElementById("stream-cmd-mac").textContent =
    'ffmpeg -f avfoundation -framerate 30 -capture_cursor 0 -pixel_format uyvy422 -i "1:none" -vf scale=1920:1080 -c:v libx264 -preset ultrafast -tune zerolatency -b:v 8M -pix_fmt yuv420p -f rtsp -rtsp_transport tcp ' + url;
  document.getElementById("stream-cmd-linux").textContent =
    'ffmpeg -f x11grab -framerate 30 -video_size 1920x1080 -i :0.0 -c:v libx264 -preset ultrafast -tune zerolatency -b:v 8M -pix_fmt yuv420p -f rtsp -rtsp_transport tcp ' + url;
}

function toggleStreamReceiver(toggle) {
  var enabling = !toggle.classList.contains("active");
  toggle.classList.toggle("active");
  var infoDiv = document.getElementById("stream-info");
  if (enabling) {
    infoDiv.style.display = "block";
    document.getElementById("stream-status-text").textContent = "Starting...";
    document.getElementById("stream-status-text").style.color = "var(--text-secondary)";
    document.getElementById("stream-status-dot").style.background = "#666";
  }
  fetch("/api/stream/toggle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enable: enabling }),
  })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (enabling && data.url) {
        populateStreamCommands(data.url);
        updateStreamStatus(data);
        if (streamPollInterval) clearInterval(streamPollInterval);
        streamPollInterval = setInterval(pollStreamStatus, 3000);
      } else {
        infoDiv.style.display = "none";
        if (streamPollInterval) { clearInterval(streamPollInterval); streamPollInterval = null; }
      }
    })
    .catch(function () {
      toggle.classList.remove("active");
      infoDiv.style.display = "none";
      showError("Failed to toggle remote rendering");
    });
}

function updateStreamStatus(data) {
  var el = document.getElementById("stream-status-text");
  var dot = document.getElementById("stream-status-dot");
  if (data.active) {
    el.textContent = "Stream active"; el.style.color = "#4ade80";
    dot.style.background = "#4ade80"; dot.style.boxShadow = "0 0 8px #4ade80";
  } else if (data.enabled) {
    el.textContent = "Waiting for stream..."; el.style.color = "#f59e0b";
    dot.style.background = "#f59e0b"; dot.style.boxShadow = "none";
  } else {
    el.textContent = "Disabled"; el.style.color = "var(--text-secondary)";
    dot.style.background = "#666"; dot.style.boxShadow = "none";
  }
}

function sendTestStream() { /* ... see full code in extras/docker-renderer/server.py context ... */ }
function pollStreamStatus() { /* ... */ }
function startPairing() { /* ... */ }
function pollPairingStatus() { /* ... */ }

// Check initial stream state on page load
fetch("/api/stream/status").then(r => r.json()).then(data => {
  if (data.enabled) {
    document.getElementById("toggle-stream-receiver").classList.add("active");
    document.getElementById("stream-info").style.display = "block";
    if (data.url) populateStreamCommands(data.url);
    updateStreamStatus(data);
    streamPollInterval = setInterval(pollStreamStatus, 3000);
  }
}).catch(() => {});
```

## 5. Lab HTML (lab.html)

Add the remote render button in Gazer fullscreen controls (after the Hue sun button):

```html
<button class="fullscreen-btn-control" id="gazer-fs-remote" title="Remote Render" onclick="toggleRemoteRender()">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
  </svg>
</button>
```

Add this JavaScript in the `<script>` section:

```javascript
// ===== Remote Render =====
var _remoteRendering = false;
var _rendererAvailable = false;

(function checkRemoteRenderServer() {
  fetch("/api/stream/remote/status")
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.available) {
        _rendererAvailable = true;
        _remoteRendering = d.streaming || false;
        var btn = document.getElementById("gazer-fs-remote");
        if (_remoteRendering && btn) btn.style.background = "rgba(74,222,128,0.3)";
      }
    })
    .catch(function () {});
})();

function toggleRemoteRender() {
  if (!_rendererAvailable) {
    showEasterEggToast("No render server connected.\nRun: docker run -e PI_IP=" + location.hostname + " vernis-renderer");
    return;
  }
  var btn = document.getElementById("gazer-fs-remote");
  if (_remoteRendering) {
    fetch("/api/stream/remote/stop", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function () {
        _remoteRendering = false;
        if (btn) btn.style.background = "";
        showEasterEggToast("Remote render stopped");
      })
      .catch(function () { showEasterEggToast("Cannot reach renderer"); });
  } else {
    if (!currentGazerUrl) { showEasterEggToast("No Gazer loaded"); return; }
    fetch("/api/stream/remote/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: currentGazerUrl, width: 720, height: 720 }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) {
          _remoteRendering = true;
          if (btn) btn.style.background = "rgba(74,222,128,0.3)";
          showEasterEggToast("Remote render started");
        } else {
          showEasterEggToast(d.error || "Failed to start");
        }
      })
      .catch(function () { showEasterEggToast("Cannot reach renderer"); });
  }
}
```
