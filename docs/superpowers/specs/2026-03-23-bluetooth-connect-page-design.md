# Bluetooth Connection Page — Design Spec

## Problem

Vernis Pi devices are only accessible via WiFi. When WiFi is misconfigured, unavailable, or the user hasn't set it up yet, there's no way to connect to the device for troubleshooting or setup. Users need a fallback connection method that works without network infrastructure.

## Solution

A Bluetooth PAN (Personal Area Network) connection option, exposed through a new `connect.html` page that serves as the central hub for all connection methods (WiFi and Bluetooth).

## Users

- **Setup user**: Powers on a new Pi, needs to connect from phone/laptop to configure WiFi and import wallet. May use Bluetooth if WiFi isn't available yet.
- **Troubleshooting user**: Pi is running but WiFi is broken. Needs Bluetooth to SSH in or access the web UI.
- **Multi-device user**: Controls the Pi from multiple phones/laptops. Needs to pair several devices.

## Constraints

- Pi screen is 720x720 — no scrolling on kiosk pages.
- Must follow existing Vernis visual design language (glass cards, gold accents, dark theme).
- Existing QR overlay on index.html stays as the fast path for WiFi.
- The connect page must work on both the Pi kiosk screen and remote phone/laptop browsers.
- Security: SSH + fail2ban + UFW already protect the Pi. Bluetooth adds pairing confirmation (PIN on screen) and short range (~10m).

---

## Page: connect.html

### Layout

A centered tabbed panel with two tabs: **WiFi** and **Bluetooth**. Vernis logo and "Connect to your frame" subtitle above the panel. Theme-aware (uses `vernis-themes.css`).

### WiFi Tab

- QR code (180px, generated via existing `/api/qrcode?theme={style}`)
- Device IP address in gold monospace font
- WiFi connection status indicator (green dot + SSID when connected, yellow "Not connected" when disconnected)
- Subtitle: "Scan QR code or visit the address from your phone or PC"

### Bluetooth Tab

- Large Bluetooth icon in blue circle
- Device name (e.g. "Vernis-afrol") — fetched from `/api/bluetooth/status`
- Numbered pairing instructions (4 steps):
  1. Open Bluetooth settings on your phone or laptop
  2. Pair with **Vernis-{hostname}**
  3. Confirm the PIN shown on this screen
  4. Connect to the PAN network, then visit **https://10.44.0.1**
- Status indicator: "Waiting for pairing request..." / "Pairing..." / "Connected"
- **"Paired Devices (N)"** link → navigates to paired devices list page
- **"Pair New Device"** button → enables discoverable mode on the adapter

### PIN Display State

When a Bluetooth pairing request arrives, the BT tab content is replaced with:

- Label: "Confirm this PIN on your device"
- Large PIN in gold monospace (48px, letter-spaced), e.g. **847 293**
- Device name being paired (e.g. "Pairing with iPhone 15 Pro")
- Spinner animation
- Expiry timer: "PIN expires in 30 seconds"
- Auto-returns to normal BT tab content after pairing completes or times out

### Paired Devices List (sub-view within connect.html)

A separate view state within `connect.html` (not a separate HTML file). Toggled by the "Paired Devices" link on the BT tab. Hides the tabbed panel and shows the list view. Same pattern as the WiFi network list in settings.

- **Back button** (top left) → returns to connect.html BT tab
- **Title**: "Paired Devices"
- **Page up / page down arrow buttons** (no scrolling — paginated)
- ~4 devices per page on 720px screen
- Each device row shows:
  - Device name
  - Status badge: "Connected" (green) / "Disconnected" (gray)
  - Unpair button (X icon)
- Empty state: "No paired devices" with prompt to pair

---

## Navigation

### Pi Kiosk

- **index.html**: Existing QR connect overlay stays (fast path). New "More connection options" link below the overlay navigates to `connect.html`.
- **BT pairing request received**: Backend sends event → kiosk navigates to `connect.html` BT tab → PIN displayed → pairing completes → auto-returns to previous page (gallery or index).
- **connect.html → paired devices list**: Navigates to paginated list. Back button returns to connect.html.

### Phone/Laptop (Remote)

- **connect.html**: Shows both WiFi and Bluetooth instructions. After connecting via either method, a "Continue to setup" link navigates to `welcome.html`.
- On localhost (Pi kiosk), the "Continue to setup" link is hidden (not needed).

---

## Backend

### New Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/bluetooth/status` | GET | Returns adapter state: `{enabled, discoverable, device_name, pan_ip}` |
| `/api/bluetooth/paired-devices` | GET | Returns paginated paired devices: `{devices: [{name, address, connected}], page, total_pages}`. Accepts `?page=1` query param (4 per page). |
| `/api/bluetooth/pairing` | POST | Receives PIN from bt-agent helper: `{pin, device}`. Stores in memory, pushes to kiosk via CDP JavaScript injection |
| `/api/bluetooth/discoverable` | POST | Toggle discoverable: `{enabled: true/false}`. Calls `bluetoothctl discoverable on/off` |
| `/api/bluetooth/unpair` | POST | Remove paired device: `{address}`. Calls `bluetoothctl remove {address}` |

### CDP Push for Pairing PIN

When `/api/bluetooth/pairing` receives a PIN:

1. Store `{pin, device, timestamp}` in a global variable
2. Use CDP (Chrome DevTools Protocol on port 9222) to execute JavaScript in the kiosk:
   - If kiosk is NOT on connect.html → navigate to `connect.html?tab=bluetooth&pairing=1`
   - If kiosk IS on connect.html → call `showPairingPIN(pin, device)` directly
3. After 30 seconds or pairing completion, clear the PIN and navigate back

### Pairing PIN Relay

The `bt-agent` tool from `bluez-tools` uses the `-c` flag for capability but does NOT support a `-p` callback script for DisplayYesNo. Instead, a custom Python agent script replaces `bt-agent` to handle pairing events via the BlueZ D-Bus API. This script:

1. Registers as a BlueZ agent with `DisplayYesNo` capability
2. On `RequestConfirmation(device, passkey)`: posts the PIN to the backend via localhost
3. On successful pairing: posts a "paired" event to clear the PIN

```bash
curl -s -X POST http://localhost:5000/api/bluetooth/pairing \
    -H "Content-Type: application/json" \
    -d "{\"pin\": \"$PIN\", \"device\": \"$DEVICE\"}"
```

The `bt-agent.service` will be updated to run this custom Python agent instead of the `bt-agent` binary. Flask binds directly on port 5000 (localhost), so the curl works regardless of Caddy.

### Navigation Return

When the kiosk navigates to `connect.html` for a pairing event, the previous URL is passed as a query parameter: `connect.html?tab=bluetooth&pairing=1&return=/gallery.html`. After pairing completes or times out, `connect.html` navigates to the `return` URL. If no return param, it uses `history.back()`.

---

## Setup Script: setup-bluetooth-pan.sh

Already written at `scripts/setup-bluetooth-pan.sh`. Needs updates before implementation:

- `bluez-tools` (bt-network for NAP server)
- `bridge-utils` (bt0 bridge interface)
- `dnsmasq` (DHCP on bt0 subnet 10.44.0.0/24)
- `bt-agent.service` — must be updated: replace `bt-agent` binary with custom Python D-Bus agent, remove `ExecStartPre discoverable on` (discoverable off by default)
- `bt-pan.service` — NAP server on bt0 bridge
- UFW rules: SSH + HTTPS on bt0 interface
- Supports multiple paired devices (DHCP pool: .10 to .50)

---

## Security

- **Pairing**: PIN confirmation on Pi screen (DisplayYesNo capability). User must be physically present.
- **Discoverable**: Off by default on boot. The `bt-agent.service` must NOT enable discoverable in `ExecStartPre` — the setup script will be updated to remove this. Discoverable is enabled temporarily via the "Pair New Device" button on the BT tab, and auto-disables after pairing completes or a 60-second timeout.
- **Network**: UFW limits bt0 to SSH (22) + HTTPS (443) only. Same fail2ban protection as WiFi.
- **Range**: Bluetooth ~10m — attacker needs physical proximity.
- **Multi-device**: Each paired device gets its own DHCP lease. Up to 40 devices supported.

---

## Files Changed

| File | Action | Responsibility |
|------|--------|----------------|
| `connect.html` | Create | Tabbed panel page (WiFi + Bluetooth + paired devices sub-view) |
| `index.html` | Modify | Add "More connection options" link to QR overlay |
| `backend/app.py` | Modify | Add Bluetooth API endpoints |
| `scripts/setup-bluetooth-pan.sh` | Modify | Update bt-agent service (custom Python agent, discoverable off by default) |
| `scripts/bt-pan-helper.sh` | Created by setup script | Bridge management |
| `scripts/bt-pairing-agent.py` | Create | Custom BlueZ D-Bus agent for DisplayYesNo pairing with PIN relay |

---

## Testing

1. **WiFi tab**: Verify QR code renders, IP displayed, status updates.
2. **Bluetooth tab**: Verify device name shows, instructions render, status indicator works.
3. **Pairing flow**: Pair phone with Pi → PIN appears on Pi screen → confirm → PAN connects → browse to 10.44.0.1.
4. **Multi-device**: Pair second device while first is connected. Both get network access.
5. **Paired devices list**: Navigate to list, verify pagination works, unpair a device.
6. **Auto-navigate**: Pi showing gallery → BT pairing request → Pi switches to connect.html with PIN → pairing done → Pi returns to gallery.
7. **Discoverable timeout**: Enable discoverable, wait 60s, verify it auto-disables.
8. **Security**: Verify unpaired device cannot connect to PAN. Verify fail2ban covers bt0.
9. **720px screen**: Verify no scrolling needed on any state of the connect page or paired devices list.

## Out of Scope

- BLE provisioning (different protocol, not needed for PAN)
- Bluetooth audio/file transfer
- Auto-discovery/mDNS over Bluetooth
- Changes to welcome.html wizard flow
