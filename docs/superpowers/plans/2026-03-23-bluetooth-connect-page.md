# Bluetooth Connect Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Bluetooth PAN connectivity and a new `connect.html` page as the central hub for WiFi and Bluetooth connections to the Vernis Pi.

**Architecture:** New `connect.html` with tabbed panel (WiFi | Bluetooth) and a paginated paired-devices sub-view. Backend gets 5 new `/api/bluetooth/*` endpoints that shell out to `bluetoothctl`. A custom Python D-Bus agent handles pairing with PIN display on the kiosk screen via CDP. The setup script configures systemd services for the BT PAN bridge.

**Tech Stack:** Flask, bluetoothctl, BlueZ D-Bus API (Python dbus), CDP (Chrome DevTools Protocol), systemd services

**Spec:** `docs/superpowers/specs/2026-03-23-bluetooth-connect-page-design.md`

**XSS Note:** All user-facing strings (device names, MAC addresses) from Bluetooth must be escaped via `escHTML()` (textContent-based) before rendering. The `innerHTML` usage in paired devices list uses this helper. This matches the existing pattern in `manage.html`.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `connect.html` | Create | Tabbed panel page — WiFi tab (QR + IP + status), Bluetooth tab (device name + instructions + status + pair button), paired devices sub-view (paginated list) |
| `backend/app.py` | Modify | Add 5 Bluetooth API endpoints (`/api/bluetooth/status`, `/paired-devices`, `/pairing`, `/discoverable`, `/unpair`) |
| `scripts/bt-pairing-agent.py` | Create | Custom BlueZ D-Bus agent for DisplayYesNo pairing — relays PIN to backend |
| `scripts/setup-bluetooth-pan.sh` | Modify | Update bt-agent.service to use custom Python agent, remove discoverable-on-boot |
| `index.html` | Modify | Add "More connection options" link to existing QR connect overlay |

---

### Task 1: Backend Bluetooth API endpoints

**Files:**
- Modify: `backend/app.py`

- [ ] **Step 1: Add `/api/bluetooth/status` endpoint**

Add after the screen-color section (around line 8215). This endpoint returns adapter state by parsing `bluetoothctl show` output:

```python
# ========================================
# Bluetooth PAN
# ========================================

_bt_pairing = {"pin": None, "device": None, "timestamp": 0}

@app.route("/api/bluetooth/status")
def bluetooth_status():
    """Return Bluetooth adapter state."""
    try:
        result = subprocess.run(
            ["bluetoothctl", "show"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split("\n")
        info = {}
        for line in lines:
            line = line.strip()
            if ": " in line:
                key, val = line.split(": ", 1)
                info[key] = val

        powered = info.get("Powered", "no") == "yes"
        discoverable = info.get("Discoverable", "no") == "yes"

        # Get hostname for device name
        hostname = subprocess.run(
            ["hostname"], capture_output=True, text=True, timeout=2
        ).stdout.strip()

        return jsonify({
            "enabled": powered,
            "discoverable": discoverable,
            "device_name": f"Vernis-{hostname}",
            "pan_ip": "10.44.0.1"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 2: Add `/api/bluetooth/paired-devices` endpoint**

```python
@app.route("/api/bluetooth/paired-devices")
def bluetooth_paired_devices():
    """Return paginated list of paired Bluetooth devices."""
    try:
        page = request.args.get("page", 1, type=int)
        per_page = 4

        # Get paired devices
        result = subprocess.run(
            ["bluetoothctl", "paired-devices"],
            capture_output=True, text=True, timeout=5
        )
        devices = []
        for line in result.stdout.strip().split("\n"):
            if line.startswith("Device "):
                parts = line.split(" ", 2)
                if len(parts) >= 3:
                    mac, name = parts[1], parts[2]
                else:
                    mac, name = parts[1], "Unknown"
                # Check if connected
                info_result = subprocess.run(
                    ["bluetoothctl", "info", mac],
                    capture_output=True, text=True, timeout=3
                )
                connected = "Connected: yes" in info_result.stdout
                devices.append({
                    "name": name,
                    "address": mac,
                    "connected": connected
                })

        total_pages = max(1, (len(devices) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        page_devices = devices[start:start + per_page]

        return jsonify({
            "devices": page_devices,
            "page": page,
            "total_pages": total_pages,
            "total": len(devices)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 3: Add `/api/bluetooth/pairing` POST endpoint**

This receives PIN from the pairing agent and pushes to the kiosk via CDP:

```python
@app.route("/api/bluetooth/pairing", methods=["POST"])
def bluetooth_pairing():
    """Receive pairing PIN from bt-pairing-agent and push to kiosk."""
    import time as _time
    data = request.get_json(silent=True) or {}
    pin = data.get("pin")
    device = data.get("device", "Unknown device")
    event = data.get("event", "pin")  # "pin" or "complete" or "failed"

    if event in ("complete", "failed"):
        _bt_pairing["pin"] = None
        _bt_pairing["device"] = None
        _bt_pairing["timestamp"] = 0
        # Navigate kiosk back if it's on connect.html
        try:
            import websocket as ws_mod
            resp = requests.get(f"http://127.0.0.1:{CDP_PORT}/json", timeout=2)
            pages = resp.json()
            target = next((p for p in pages if p.get("type") == "page"), None)
            if target:
                ws_url = target.get("webSocketDebuggerUrl")
                if ws_url:
                    ws = ws_mod.create_connection(ws_url, timeout=3)
                    ws.send(json.dumps({
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {"expression": "if(typeof onPairingComplete==='function')onPairingComplete()"}
                    }))
                    ws.recv()
                    ws.close()
        except Exception:
            pass
        return jsonify({"success": True})

    if not pin:
        return jsonify({"error": "No PIN provided"}), 400

    _bt_pairing["pin"] = str(pin)
    _bt_pairing["device"] = device
    _bt_pairing["timestamp"] = _time.time()

    # Push to kiosk via CDP
    try:
        import websocket as ws_mod
        resp = requests.get(f"http://127.0.0.1:{CDP_PORT}/json", timeout=2)
        pages = resp.json()
        target = next((p for p in pages if p.get("type") == "page"), None)
        if target:
            ws_url = target.get("webSocketDebuggerUrl")
            if ws_url:
                ws = ws_mod.create_connection(ws_url, timeout=3)
                current_url = target.get("url", "")
                if "connect.html" in current_url:
                    # Already on connect page — call JS function
                    js_pin = pin.replace("'", "\\'")
                    js_dev = device.replace("'", "\\'")
                    ws.send(json.dumps({
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {"expression": f"showPairingPIN('{js_pin}','{js_dev}')"}
                    }))
                else:
                    # Navigate to connect page with pairing params
                    return_path = current_url.split("localhost")[-1] if "localhost" in current_url else "/gallery.html"
                    ws.send(json.dumps({
                        "id": 1,
                        "method": "Page.navigate",
                        "params": {"url": f"https://localhost/connect.html?tab=bluetooth&pairing=1&return={return_path}"}
                    }))
                ws.recv()
                ws.close()
    except Exception as e:
        print(f"[bluetooth] CDP push failed: {e}", flush=True)

    return jsonify({"success": True, "pin": _bt_pairing["pin"]})
```

- [ ] **Step 4: Add `/api/bluetooth/pairing` GET handler for polling**

The connect.html page polls this to get the current PIN (in case CDP injection missed):

```python
@app.route("/api/bluetooth/pairing", methods=["GET"])
def bluetooth_pairing_status():
    """Return current pairing state (polled by connect.html)."""
    import time as _time
    if _bt_pairing["pin"] and (_time.time() - _bt_pairing["timestamp"]) < 30:
        return jsonify({
            "active": True,
            "pin": _bt_pairing["pin"],
            "device": _bt_pairing["device"]
        })
    return jsonify({"active": False})
```

- [ ] **Step 5: Add `/api/bluetooth/discoverable` endpoint**

```python
_bt_discoverable_timer = {"thread": None}

def _discoverable_auto_off():
    """Background thread: disable discoverable after 60s if still on."""
    import time as _time
    _time.sleep(60)
    try:
        subprocess.run(["bluetoothctl", "discoverable", "off"],
                       capture_output=True, text=True, timeout=5)
        print("[bluetooth] Discoverable auto-disabled after 60s", flush=True)
    except Exception:
        pass

@app.route("/api/bluetooth/discoverable", methods=["POST"])
def bluetooth_discoverable():
    """Toggle Bluetooth discoverable mode. Auto-disables after 60s when enabled."""
    import threading
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled", True)
    cmd = "on" if enabled else "off"
    try:
        subprocess.run(
            ["bluetoothctl", "discoverable", cmd],
            capture_output=True, text=True, timeout=5
        )
        if enabled:
            subprocess.run(
                ["bluetoothctl", "pairable", "on"],
                capture_output=True, text=True, timeout=5
            )
            # Auto-disable after 60s (security: don't stay discoverable)
            t = threading.Thread(target=_discoverable_auto_off, daemon=True)
            t.start()
            _bt_discoverable_timer["thread"] = t
        return jsonify({"success": True, "discoverable": enabled})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 6: Add `/api/bluetooth/unpair` endpoint**

```python
@app.route("/api/bluetooth/unpair", methods=["POST"])
def bluetooth_unpair():
    """Remove a paired Bluetooth device."""
    data = request.get_json(silent=True) or {}
    address = data.get("address", "")
    # Validate MAC format
    if not re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', address):
        return jsonify({"error": "Invalid MAC address"}), 400
    try:
        subprocess.run(
            ["bluetoothctl", "remove", address],
            capture_output=True, text=True, timeout=5
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 7: Commit**

```bash
git add backend/app.py
git commit -m "feat: add Bluetooth PAN API endpoints (status, pairing, discoverable, unpair)"
```

---

### Task 2: Create connect.html

**Files:**
- Create: `connect.html`

- [ ] **Step 1: Create connect.html**

The complete implementation source code is at `docs/superpowers/plans/connect-html-source.md`. Copy the entire HTML content from that file to create `connect.html`.

The file contains ~450 lines of HTML/CSS/JS implementing:
- Vernis boilerplate (theme sync IIFE, viewport meta, vernis-themes.css)
- Logo section (gold V mark + "VERNIS" + "Connect to your frame")
- Tabbed panel with WiFi and Bluetooth tabs
- WiFi tab: QR code via `/api/qrcode`, IP address, WiFi status
- Bluetooth tab: device name, 4-step instructions, status bar, "Paired Devices" link, "Pair New Device" button, PIN overlay
- Paired devices sub-view: back button, paginated list with page up/down buttons, unpair buttons
- "Continue to setup" link (hidden on localhost/kiosk)
- All device names escaped via `escHTML()` helper (textContent-based sanitization)
- 60-second discoverable timeout in `startPairing()` — calls `POST /api/bluetooth/discoverable {enabled: false}` after timeout

- [ ] **Step 2: Commit**

```bash
git add connect.html
git commit -m "feat: create connect.html with WiFi/Bluetooth tabbed panel and paired devices list"
```

---

### Task 3: Create bt-pairing-agent.py

**Files:**
- Create: `scripts/bt-pairing-agent.py`

- [ ] **Step 1: Create the custom BlueZ D-Bus pairing agent**

This replaces `bt-agent` from `bluez-tools` with a custom script that relays the PIN to the backend. Uses `python3-dbus` and `python3-gi` (GLib main loop).

Key behavior:
- Registers as BlueZ agent with `DisplayYesNo` capability at `/vernis/bt_agent`
- `RequestConfirmation(device, passkey)`: formats passkey as 6-digit PIN, posts to `http://localhost:5000/api/bluetooth/pairing`, auto-confirms
- `DisplayPasskey(device, passkey, entered)`: same PIN relay
- `Cancel()`: posts `event: "failed"` to clear PIN from kiosk
- On new paired device (via D-Bus `InterfacesAdded` signal): auto-trusts device, posts `event: "complete"`

Uses `curl` subprocess for backend notification (avoids importing requests in the agent).

```python
#!/usr/bin/env python3
"""
Vernis Bluetooth Pairing Agent
Custom BlueZ D-Bus agent with DisplayYesNo capability.
Relays pairing PIN to the Vernis backend for display on the kiosk screen.
"""

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import subprocess
import json

AGENT_INTERFACE = "org.bluez.Agent1"
AGENT_PATH = "/vernis/bt_agent"
BACKEND_URL = "http://localhost:5000/api/bluetooth/pairing"
CAPABILITY = "DisplayYesNo"


def notify_backend(pin, device, event="pin"):
    """Post pairing event to Vernis backend."""
    try:
        data = json.dumps({"pin": str(pin), "device": device, "event": event})
        subprocess.Popen([
            "curl", "-s", "-X", "POST", BACKEND_URL,
            "-H", "Content-Type: application/json",
            "-d", data
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[bt-agent] Backend notify failed: {e}", flush=True)


def device_name(path):
    """Get friendly name for a device from its D-Bus path."""
    try:
        bus = dbus.SystemBus()
        obj = bus.get_object("org.bluez", path)
        props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
        name = props.Get("org.bluez.Device1", "Name")
        return str(name)
    except Exception:
        return path.split("/")[-1] if "/" in path else "Unknown"


class Agent(dbus.service.Object):
    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Release(self):
        print("[bt-agent] Agent released", flush=True)

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        print(f"[bt-agent] AuthorizeService {device} {uuid}", flush=True)

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        name = device_name(device)
        print(f"[bt-agent] RequestPinCode from {name}", flush=True)
        return "0000"

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        name = device_name(device)
        print(f"[bt-agent] RequestPasskey from {name}", flush=True)
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_INTERFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        name = device_name(device)
        pin = f"{passkey:06d}"
        print(f"[bt-agent] DisplayPasskey {pin} for {name}", flush=True)
        notify_backend(pin, name)

    @dbus.service.method(AGENT_INTERFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        name = device_name(device)
        pin = f"{passkey:06d}"
        print(f"[bt-agent] RequestConfirmation {pin} for {name}", flush=True)
        notify_backend(pin, name)
        # Auto-confirm (PIN is shown on screen for user verification)

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        name = device_name(device)
        print(f"[bt-agent] RequestAuthorization from {name}", flush=True)

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Cancel(self):
        print("[bt-agent] Pairing cancelled", flush=True)
        notify_backend("", "", "failed")


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    agent = Agent(bus, AGENT_PATH)
    manager = dbus.Interface(
        bus.get_object("org.bluez", "/org/bluez"),
        "org.bluez.AgentManager1"
    )

    manager.RegisterAgent(AGENT_PATH, CAPABILITY)
    manager.RequestDefaultAgent(AGENT_PATH)
    print(f"[bt-agent] Registered with capability={CAPABILITY}", flush=True)

    # Trust paired devices automatically
    def interfaces_added(path, interfaces):
        if "org.bluez.Device1" in interfaces:
            props = interfaces["org.bluez.Device1"]
            if props.get("Paired"):
                try:
                    obj = bus.get_object("org.bluez", path)
                    dev = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
                    dev.Set("org.bluez.Device1", "Trusted", True)
                    name = props.get("Name", "Unknown")
                    print(f"[bt-agent] Auto-trusted {name}", flush=True)
                    notify_backend("", str(name), "complete")
                except Exception:
                    pass

    bus.add_signal_receiver(
        interfaces_added,
        dbus_interface="org.freedesktop.DBus.ObjectManager",
        signal_name="InterfacesAdded"
    )

    print("[bt-agent] Waiting for pairing requests...", flush=True)
    mainloop = GLib.MainLoop()
    try:
        mainloop.run()
    except KeyboardInterrupt:
        print("[bt-agent] Stopped", flush=True)
        manager.UnregisterAgent(AGENT_PATH)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/bt-pairing-agent.py
git commit -m "feat: add custom BlueZ D-Bus pairing agent with PIN relay to backend"
```

---

### Task 4: Update setup-bluetooth-pan.sh

**Files:**
- Modify: `scripts/setup-bluetooth-pan.sh`

- [ ] **Step 1: Update apt install to include D-Bus Python bindings**

In `scripts/setup-bluetooth-pan.sh`, update the apt install line (line 29):

```bash
# Before:
sudo apt install -y bluez bluez-tools bridge-utils dnsmasq

# After:
sudo apt install -y bluez bluez-tools bridge-utils dnsmasq python3-dbus python3-gi
```

- [ ] **Step 2: Update bt-agent.service to use custom Python agent**

Replace the bt-agent.service definition. Remove the `ExecStartPre discoverable on` line (discoverable is now controlled via the web UI only):

```bash
# Replace the entire bt-agent.service tee block with:
sudo tee /etc/systemd/system/bt-agent.service > /dev/null << EOF
[Unit]
Description=Bluetooth Pairing Agent for Vernis
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=simple
ExecStartPre=/usr/bin/bluetoothctl pairable on
ExecStart=/usr/bin/python3 /opt/vernis/scripts/bt-pairing-agent.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

- [ ] **Step 3: Remove the bt-pin-display.sh creation block**

Delete the entire block that creates `/opt/vernis/scripts/bt-pin-display.sh` — the Python agent handles PIN relay directly.

- [ ] **Step 4: Add copy of bt-pairing-agent.py to the install flow**

Add after the `sudo chmod +x /opt/vernis/scripts/bt-pan-helper.sh` line:

```bash
# Copy pairing agent script
sudo cp "$(dirname "$0")/bt-pairing-agent.py" /opt/vernis/scripts/bt-pairing-agent.py
sudo chmod +x /opt/vernis/scripts/bt-pairing-agent.py
```

- [ ] **Step 5: Commit**

```bash
git add scripts/setup-bluetooth-pan.sh
git commit -m "feat: update BT PAN setup — custom Python agent, discoverable off by default"
```

---

### Task 5: Add "More connection options" link to index.html

**Files:**
- Modify: `index.html` (around line 676)

- [ ] **Step 1: Add link to the QR connect overlay**

Find the kiosk connect overlay hint text:

```html
<div class="kiosk-connect-hint">Open this link on your phone or computer to manage your Vernis</div>
```

Add immediately after:

```html
<a href="connect.html" style="display:block;text-align:center;margin-top:16px;color:var(--accent-primary);font-size:13px;text-decoration:none;opacity:0.7;">More connection options (Bluetooth)</a>
```

- [ ] **Step 2: Commit**

```bash
git add index.html
git commit -m "feat: add 'More connection options' link to kiosk connect overlay"
```

---

### Task 6: Deploy and test on Pi

- [ ] **Step 1: Deploy all files to Pi 28 (afrol)**

Deploy `connect.html` to `/var/www/vernis/`, `app.py` to `/opt/vernis/`, `bt-pairing-agent.py` to `/opt/vernis/scripts/`, `index.html` to `/var/www/vernis/`. Restart vernis-api.

```bash
# Web files
for f in connect.html index.html; do
  cat "$f" | sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrol@10.0.0.28 "cat > /tmp/$f && echo '<device-password>' | sudo -S mv /tmp/$f /var/www/vernis/$f"
done

# Backend
cat backend/app.py | sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrol@10.0.0.28 "cat > /tmp/app.py && echo '<device-password>' | sudo -S mv /tmp/app.py /opt/vernis/app.py && echo '<device-password>' | sudo -S systemctl restart vernis-api"

# Pairing agent
cat scripts/bt-pairing-agent.py | sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrol@10.0.0.28 "cat > /tmp/bt-pairing-agent.py && echo '<device-password>' | sudo -S mv /tmp/bt-pairing-agent.py /opt/vernis/scripts/bt-pairing-agent.py && echo '<device-password>' | sudo -S chmod +x /opt/vernis/scripts/bt-pairing-agent.py"
```

- [ ] **Step 2: Run setup script on Pi**

```bash
cat scripts/setup-bluetooth-pan.sh | sshpass -p '<device-password>' ssh -o StrictHostKeyChecking=no afrol@10.0.0.28 "cat > /tmp/setup-bt.sh && bash /tmp/setup-bt.sh"
```

- [ ] **Step 3: Verify WiFi tab**

Open `https://10.0.0.28/connect.html`. Verify QR code loads, IP shows, WiFi status shows SSID.

- [ ] **Step 4: Verify Bluetooth tab**

Switch to BT tab. Verify device name "Vernis-afrol", instructions render, status shows "Bluetooth ready".

- [ ] **Step 5: Test pairing flow**

Click "Pair New Device" → pair from phone → verify PIN appears on Pi screen → confirm → PAN connects → browse `https://10.44.0.1`.

- [ ] **Step 6: Test paired devices list**

Click "Paired Devices" → verify list shows device → verify page up/down and back button.

- [ ] **Step 7: Test kiosk auto-navigate**

While Pi shows gallery, pair a new device → Pi switches to connect.html with PIN → pairing completes → Pi returns to gallery.
