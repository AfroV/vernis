# connect.html — Full Source

This is the complete source for `connect.html`. Copy this entire HTML block to create the file.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Vernis • Connect</title>
  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <link rel="stylesheet" href="vernis-themes.css">
  <script>
    (function () {
      var theme = localStorage.getItem('vernis-theme-style') || 'walnut';
      var mode = localStorage.getItem('vernis-theme-mode') || 'dark';
      document.documentElement.setAttribute('data-theme', theme);
      document.documentElement.setAttribute('data-mode', mode);
    })();
  </script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      min-height: 100vh;
      background: var(--bg-primary, #0f0d0d);
      color: var(--text-primary, #e5e5e5);
      font-family: 'Inter', -apple-system, system-ui, sans-serif;
      display: flex; justify-content: center; align-items: flex-start;
      padding: 24px 16px;
      -webkit-user-select: none; user-select: none;
      -webkit-tap-highlight-color: transparent;
      overflow: hidden;
    }

    .connect-container { width: 100%; max-width: 420px; }

    /* Logo */
    .logo-section { text-align: center; margin-bottom: 28px; }
    .logo-mark {
      width: 56px; height: 56px;
      background: radial-gradient(circle at 35% 35%, var(--accent-primary, #d4af37), var(--accent-secondary, #8b6914));
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      margin: 0 auto 12px;
      box-shadow: 0 4px 20px rgba(212,175,55,0.25);
    }
    .logo-mark span {
      font-size: 26px; font-weight: 700; color: var(--bg-primary, #0f0d0d);
      font-family: 'Playfair Display', Georgia, serif;
    }
    .logo-title {
      font-size: 22px; font-weight: 600; letter-spacing: 3px; text-transform: uppercase;
      color: var(--text-primary, #e5e5e5);
    }
    .logo-sub { font-size: 12px; color: var(--text-muted, #888); margin-top: 4px; letter-spacing: 1px; }

    /* Panel */
    .panel {
      background: var(--bg-secondary, rgba(30,28,28,0.85));
      border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
      border-radius: 16px; overflow: hidden;
      backdrop-filter: blur(15px);
      box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    }

    /* Tabs */
    .tabs { display: flex; border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06)); }
    .tab {
      flex: 1; padding: 16px 12px; text-align: center; cursor: pointer;
      font-size: 14px; font-weight: 500; color: var(--text-muted, #777);
      border: none; border-bottom: 2px solid transparent;
      background: none; transition: all 0.3s ease;
      display: flex; align-items: center; justify-content: center; gap: 8px;
    }
    .tab:hover { color: var(--text-secondary, #bbb); }
    .tab.active { color: var(--accent-primary, #d4af37); border-bottom-color: var(--accent-primary, #d4af37); }
    .tab svg { width: 18px; height: 18px; }

    .tab-content { display: none; padding: 28px 24px; min-height: 320px; }
    .tab-content.active { display: block; }

    /* WiFi Tab */
    .qr-area {
      width: 180px; height: 180px; background: #fff; border-radius: 12px;
      margin: 0 auto 20px; display: flex; align-items: center; justify-content: center;
      overflow: hidden;
    }
    .qr-area img { width: 100%; height: 100%; object-fit: contain; }
    .ip-display { text-align: center; margin-bottom: 16px; }
    .ip-label { font-size: 11px; color: var(--text-muted, #666); text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 6px; }
    .ip-value {
      font-size: 20px; font-weight: 600; color: var(--accent-primary, #d4af37);
      font-family: 'SF Mono', 'Fira Code', monospace; letter-spacing: 1px;
    }
    .wifi-status {
      display: flex; align-items: center; justify-content: center; gap: 8px;
      padding: 10px 16px; border-radius: 10px; font-size: 13px;
    }
    .wifi-status.connected {
      background: rgba(50,215,75,0.08); border: 1px solid rgba(50,215,75,0.15); color: #32d74b;
    }
    .wifi-status.disconnected {
      background: rgba(255,200,50,0.08); border: 1px solid rgba(255,200,50,0.15); color: #ffc832;
    }
    .status-dot {
      width: 8px; height: 8px; border-radius: 50%;
      animation: pulse 2s ease infinite;
    }
    .status-dot.green { background: #32d74b; }
    .status-dot.yellow { background: #ffc832; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

    .wifi-hint {
      text-align: center; margin-top: 16px; font-size: 11px;
      color: var(--text-muted, #555); padding: 0 8px;
    }

    /* Bluetooth Tab */
    .bt-icon-large {
      width: 72px; height: 72px;
      background: rgba(55,120,250,0.1); border: 1px solid rgba(55,120,250,0.2);
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      margin: 0 auto 20px;
    }
    .bt-icon-large svg { width: 32px; height: 32px; color: #3778fa; }
    .device-name { text-align: center; margin-bottom: 24px; }
    .device-name .label { font-size: 11px; color: var(--text-muted, #666); text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 6px; }
    .device-name .name { font-size: 20px; font-weight: 600; color: var(--text-primary, #e5e5e5); }

    .bt-steps { list-style: none; margin-bottom: 24px; }
    .bt-steps li {
      display: flex; align-items: flex-start; gap: 12px;
      padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.04);
      font-size: 13px; color: var(--text-secondary, #aaa); line-height: 1.5;
    }
    .bt-steps li:last-child { border-bottom: none; }
    .step-num {
      width: 24px; height: 24px; background: rgba(55,120,250,0.12); border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 12px; font-weight: 600; color: #3778fa; flex-shrink: 0; margin-top: 1px;
    }

    .bt-actions {
      display: flex; gap: 12px; margin-bottom: 16px; align-items: center; justify-content: center;
    }
    .bt-btn {
      padding: 10px 20px; border-radius: 10px; font-size: 13px; font-weight: 500;
      cursor: pointer; border: none; transition: all 0.2s;
    }
    .bt-btn-primary {
      background: rgba(55,120,250,0.15); color: #3778fa;
      border: 1px solid rgba(55,120,250,0.25);
    }
    .bt-btn-primary:hover { background: rgba(55,120,250,0.25); }
    .bt-btn-primary:disabled { opacity: 0.4; cursor: default; }
    .bt-link {
      color: var(--text-muted, #888); font-size: 13px; text-decoration: none;
      padding: 10px 0; cursor: pointer; background: none; border: none;
    }
    .bt-link:hover { color: var(--text-secondary, #bbb); }

    .bt-status {
      display: flex; align-items: center; justify-content: center; gap: 8px;
      padding: 10px 16px; border-radius: 10px; font-size: 13px;
      background: rgba(55,120,250,0.08); border: 1px solid rgba(55,120,250,0.15); color: #3778fa;
    }

    /* PIN display */
    .pin-overlay { text-align: center; padding: 20px 0; display: none; }
    .pin-overlay.active { display: block; }
    .pin-label { font-size: 13px; color: var(--text-muted, #888); margin-bottom: 12px; }
    .pin-code {
      font-size: 48px; font-weight: 700; letter-spacing: 12px;
      color: var(--accent-primary, #d4af37);
      font-family: 'SF Mono', 'Fira Code', monospace;
      text-shadow: 0 0 30px rgba(212,175,55,0.3); margin-bottom: 12px;
    }
    .pin-device { font-size: 12px; color: var(--text-muted, #666); }
    .pin-spinner {
      width: 24px; height: 24px;
      border: 2px solid rgba(212,175,55,0.2); border-top-color: var(--accent-primary, #d4af37);
      border-radius: 50%; margin: 16px auto 0;
      animation: spin 1s linear infinite;
    }
    .pin-timer { text-align: center; font-size: 12px; color: var(--text-muted, #555); margin-top: 16px; }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* Paired devices sub-view */
    .paired-view { display: none; }
    .paired-view.active { display: block; }
    .paired-header {
      display: flex; align-items: center; gap: 12px; margin-bottom: 20px;
    }
    .paired-back {
      width: 44px; height: 44px; border-radius: 10px;
      background: var(--bg-secondary, rgba(30,28,28,0.85));
      border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
      color: var(--text-primary, #e5e5e5); cursor: pointer;
      display: flex; align-items: center; justify-content: center;
    }
    .paired-back svg { width: 20px; height: 20px; }
    .paired-title { font-size: 18px; font-weight: 600; color: var(--text-primary, #e5e5e5); }

    .device-list { display: flex; flex-direction: column; gap: 8px; min-height: 240px; }
    .device-row {
      display: flex; align-items: center; padding: 14px 16px;
      background: var(--bg-secondary, rgba(30,28,28,0.85));
      border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
      border-radius: 12px; gap: 12px;
    }
    .device-row-name { flex: 1; font-size: 14px; color: var(--text-primary, #e5e5e5); }
    .device-row-badge {
      font-size: 11px; padding: 4px 10px; border-radius: 6px; font-weight: 500;
    }
    .device-row-badge.connected { background: rgba(50,215,75,0.1); color: #32d74b; }
    .device-row-badge.disconnected { background: rgba(255,255,255,0.05); color: var(--text-muted, #666); }
    .device-row-unpair {
      width: 36px; height: 36px; border-radius: 8px;
      background: rgba(255,69,58,0.08); border: 1px solid rgba(255,69,58,0.15);
      color: #ff453a; cursor: pointer; display: flex; align-items: center; justify-content: center;
      font-size: 16px; font-weight: 600;
    }
    .device-row-unpair:hover { background: rgba(255,69,58,0.15); }

    .page-nav {
      display: flex; justify-content: center; gap: 12px; margin-top: 16px; align-items: center;
    }
    .page-btn {
      width: 44px; height: 44px; border-radius: 10px;
      background: var(--bg-secondary, rgba(30,28,28,0.85));
      border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
      color: var(--text-primary, #e5e5e5); cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      font-size: 18px;
    }
    .page-btn:disabled { opacity: 0.3; cursor: default; }
    .page-info { font-size: 13px; color: var(--text-muted, #888); }

    .empty-state {
      text-align: center; padding: 40px 20px; color: var(--text-muted, #666);
    }
    .empty-state p { font-size: 14px; margin-bottom: 8px; }
    .empty-state .hint { font-size: 12px; }

    /* Continue link (remote only) */
    .continue-link {
      display: block; text-align: center; margin-top: 20px;
      color: var(--accent-primary, #d4af37); font-size: 14px; text-decoration: none;
    }
    .continue-link:hover { opacity: 0.8; }
    .hide { display: none; }
  </style>
</head>
<body>
  <!-- Main connect view -->
  <div class="connect-container" id="main-view">
    <div class="logo-section">
      <div class="logo-mark"><span>V</span></div>
      <div class="logo-title">Vernis</div>
      <div class="logo-sub">Connect to your frame</div>
    </div>
    <div class="panel">
      <div class="tabs">
        <button class="tab active" id="tab-wifi" onclick="switchTab('wifi')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>
          WiFi
        </button>
        <button class="tab" id="tab-bt" onclick="switchTab('bt')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/><path d="M12 2l3.5 3.5L12 9l3.5 3.5L12 16l3.5 3.5L12 23"/><path d="M12 2L8.5 5.5 12 9 8.5 12.5 12 16l-3.5 3.5L12 23"/></svg>
          Bluetooth
        </button>
      </div>

      <!-- WiFi content -->
      <div class="tab-content active" id="content-wifi">
        <div class="qr-area" id="qr-area">
          <span style="color:#999;font-size:13px;">Loading...</span>
        </div>
        <div class="ip-display">
          <div class="ip-label">Device Address</div>
          <div class="ip-value" id="device-ip">...</div>
        </div>
        <div class="wifi-status connected" id="wifi-status">
          <div class="status-dot green"></div>
          <span id="wifi-ssid">Checking...</span>
        </div>
        <div class="wifi-hint">Scan QR code or visit the address above from your phone or PC</div>
      </div>

      <!-- Bluetooth content -->
      <div class="tab-content" id="content-bt">
        <div id="bt-normal">
          <div class="bt-icon-large">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/><path d="M12 2l3.5 3.5L12 9l3.5 3.5L12 16l3.5 3.5L12 23"/><path d="M12 2L8.5 5.5 12 9 8.5 12.5 12 16l-3.5 3.5L12 23"/></svg>
          </div>
          <div class="device-name">
            <div class="label">Device Name</div>
            <div class="name" id="bt-device-name">...</div>
          </div>
          <ol class="bt-steps" id="bt-steps"></ol>
          <div class="bt-actions">
            <button class="bt-link" id="paired-link" onclick="showPairedDevices()">Paired Devices (<span id="paired-count">0</span>)</button>
            <button class="bt-btn bt-btn-primary" id="pair-btn" onclick="startPairing()">Pair New Device</button>
          </div>
          <div class="bt-status" id="bt-status">
            <span id="bt-status-text">Checking Bluetooth...</span>
          </div>
        </div>
        <div class="pin-overlay" id="pin-overlay">
          <div class="pin-label">Confirm this PIN on your device</div>
          <div class="pin-code" id="pin-code"></div>
          <div class="pin-device" id="pin-device"></div>
          <div class="pin-spinner"></div>
          <div class="pin-timer" id="pin-timer"></div>
        </div>
      </div>
    </div>

    <a href="welcome.html" class="continue-link" id="continue-link">Continue to setup &rarr;</a>
  </div>

  <!-- Paired devices sub-view -->
  <div class="connect-container paired-view" id="paired-view">
    <div class="paired-header">
      <button class="paired-back" onclick="hidePairedDevices()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5"/><path d="M12 19l-7-7 7-7"/></svg>
      </button>
      <div class="paired-title">Paired Devices</div>
    </div>
    <div class="device-list" id="device-list"></div>
    <div class="page-nav" id="page-nav">
      <button class="page-btn" id="page-up" onclick="changePage(-1)">&#9650;</button>
      <span class="page-info" id="page-info">1 / 1</span>
      <button class="page-btn" id="page-down" onclick="changePage(1)">&#9660;</button>
    </div>
  </div>

  <script>
    // === State ===
    var _btDeviceName = '';
    var _pairedPage = 1;
    var _pairedTotalPages = 1;
    var _pinTimer = null;
    var _pairingTimer = null;
    var _discoverableTimer = null;
    var _pollInterval = null;
    var _returnUrl = '';

    // === Utilities ===
    function escHTML(s) {
      var d = document.createElement('div');
      d.textContent = s;
      return d.textContent;
    }

    function isKiosk() {
      var h = location.hostname;
      return h === 'localhost' || h === '127.0.0.1';
    }

    // === Tab switching ===
    function switchTab(tab) {
      document.getElementById('tab-wifi').className = tab === 'wifi' ? 'tab active' : 'tab';
      document.getElementById('tab-bt').className = tab === 'bt' ? 'tab active' : 'tab';
      document.getElementById('content-wifi').className = tab === 'wifi' ? 'tab-content active' : 'tab-content';
      document.getElementById('content-bt').className = tab === 'bt' ? 'tab-content active' : 'tab-content';
    }

    // === WiFi tab ===
    function loadWiFiInfo() {
      // QR code
      var theme = localStorage.getItem('vernis-theme-style') || 'walnut';
      var qrArea = document.getElementById('qr-area');
      var img = document.createElement('img');
      img.src = '/api/qrcode?theme=' + encodeURIComponent(theme);
      img.alt = 'QR Code';
      img.onerror = function() { qrArea.textContent = 'QR unavailable'; };
      qrArea.textContent = '';
      qrArea.appendChild(img);

      // IP address
      document.getElementById('device-ip').textContent = location.hostname;

      // WiFi status
      fetch('/api/wifi-status').then(function(r) { return r.json(); }).then(function(d) {
        var statusEl = document.getElementById('wifi-status');
        var ssidEl = document.getElementById('wifi-ssid');
        var dotEl = statusEl.querySelector('.status-dot');
        if (d.connected && d.ssid) {
          statusEl.className = 'wifi-status connected';
          dotEl.className = 'status-dot green';
          ssidEl.textContent = 'Connected to ' + d.ssid;
        } else {
          statusEl.className = 'wifi-status disconnected';
          dotEl.className = 'status-dot yellow';
          ssidEl.textContent = 'Not connected';
        }
      }).catch(function() {
        document.getElementById('wifi-ssid').textContent = 'Status unavailable';
      });
    }

    // === Bluetooth tab ===
    function loadBTStatus() {
      fetch('/api/bluetooth/status').then(function(r) { return r.json(); }).then(function(d) {
        _btDeviceName = d.device_name || 'Vernis';
        document.getElementById('bt-device-name').textContent = _btDeviceName;
        buildBTSteps(_btDeviceName);

        var statusText = document.getElementById('bt-status-text');
        if (!d.enabled) {
          statusText.textContent = 'Bluetooth is off';
        } else if (d.discoverable) {
          statusText.textContent = 'Discoverable — waiting for pairing...';
        } else {
          statusText.textContent = 'Bluetooth ready';
        }
      }).catch(function() {
        document.getElementById('bt-status-text').textContent = 'Bluetooth unavailable';
      });

      // Load paired count
      fetch('/api/bluetooth/paired-devices?page=1').then(function(r) { return r.json(); }).then(function(d) {
        document.getElementById('paired-count').textContent = d.total || 0;
      }).catch(function() {});
    }

    function buildBTSteps(deviceName) {
      var steps = [
        'Open <strong>Bluetooth settings</strong> on your phone or laptop',
        'Pair with <strong>' + escHTML(deviceName) + '</strong>',
        'Confirm the PIN shown on this screen',
        'Connect to the <strong>PAN network</strong>, then visit <strong style="color:#3778fa;">https://10.44.0.1</strong>'
      ];
      var ol = document.getElementById('bt-steps');
      ol.textContent = '';
      for (var i = 0; i < steps.length; i++) {
        var li = document.createElement('li');
        var numDiv = document.createElement('div');
        numDiv.className = 'step-num';
        numDiv.textContent = String(i + 1);
        var textDiv = document.createElement('div');
        // Steps contain safe static HTML with only the device name escaped
        textDiv.insertAdjacentHTML('beforeend', steps[i]);
        li.appendChild(numDiv);
        li.appendChild(textDiv);
        ol.appendChild(li);
      }
    }

    // === Pairing ===
    function startPairing() {
      var btn = document.getElementById('pair-btn');
      btn.disabled = true;
      btn.textContent = 'Discoverable...';

      fetch('/api/bluetooth/discoverable', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: true })
      }).then(function(r) { return r.json(); }).then(function() {
        document.getElementById('bt-status-text').textContent = 'Discoverable — waiting for pairing...';

        // Auto-disable after 60s (client-side UI update; backend also auto-disables)
        clearTimeout(_discoverableTimer);
        _discoverableTimer = setTimeout(function() {
          btn.disabled = false;
          btn.textContent = 'Pair New Device';
          document.getElementById('bt-status-text').textContent = 'Discoverable timed out';
          loadBTStatus();
        }, 60000);
      }).catch(function() {
        btn.disabled = false;
        btn.textContent = 'Pair New Device';
      });

      // Start polling for pairing PIN
      startPINPolling();
    }

    function startPINPolling() {
      clearInterval(_pollInterval);
      _pollInterval = setInterval(function() {
        fetch('/api/bluetooth/pairing').then(function(r) { return r.json(); }).then(function(d) {
          if (d.active && d.pin) {
            showPairingPIN(d.pin, d.device);
          }
        }).catch(function() {});
      }, 2000);
    }

    // Called by CDP injection or polling
    function showPairingPIN(pin, device) {
      clearInterval(_pollInterval);

      // Format PIN with space in middle: "847293" -> "847 293"
      var formatted = pin.length === 6 ? pin.slice(0, 3) + ' ' + pin.slice(3) : pin;

      document.getElementById('pin-code').textContent = formatted;
      document.getElementById('pin-device').textContent = 'Pairing with ' + escHTML(device || 'device');

      // Show PIN overlay, hide normal BT content
      document.getElementById('bt-normal').style.display = 'none';
      document.getElementById('pin-overlay').className = 'pin-overlay active';

      // Switch to BT tab
      switchTab('bt');

      // 30-second countdown
      var remaining = 30;
      document.getElementById('pin-timer').textContent = 'PIN expires in ' + remaining + ' seconds';
      clearInterval(_pinTimer);
      _pinTimer = setInterval(function() {
        remaining--;
        document.getElementById('pin-timer').textContent = 'PIN expires in ' + remaining + ' seconds';
        if (remaining <= 0) {
          hidePairingPIN();
        }
      }, 1000);
    }

    function hidePairingPIN() {
      clearInterval(_pinTimer);
      document.getElementById('bt-normal').style.display = '';
      document.getElementById('pin-overlay').className = 'pin-overlay';
      document.getElementById('pair-btn').disabled = false;
      document.getElementById('pair-btn').textContent = 'Pair New Device';
      loadBTStatus();
    }

    // Called by CDP after pairing completes
    function onPairingComplete() {
      hidePairingPIN();
      clearTimeout(_discoverableTimer);
      clearInterval(_pollInterval);

      // Navigate back to return URL if specified
      if (_returnUrl) {
        location.href = _returnUrl;
      }
    }

    // === Paired devices list ===
    function showPairedDevices() {
      _pairedPage = 1;
      document.getElementById('main-view').style.display = 'none';
      document.getElementById('paired-view').className = 'connect-container paired-view active';
      loadPairedDevices();
    }

    function hidePairedDevices() {
      document.getElementById('paired-view').className = 'connect-container paired-view';
      document.getElementById('main-view').style.display = '';
      loadBTStatus(); // refresh paired count
    }

    function loadPairedDevices() {
      fetch('/api/bluetooth/paired-devices?page=' + _pairedPage).then(function(r) { return r.json(); }).then(function(d) {
        _pairedTotalPages = d.total_pages || 1;
        renderDeviceList(d.devices || []);
        document.getElementById('page-info').textContent = _pairedPage + ' / ' + _pairedTotalPages;
        document.getElementById('page-up').disabled = _pairedPage <= 1;
        document.getElementById('page-down').disabled = _pairedPage >= _pairedTotalPages;
      }).catch(function() {
        var list = document.getElementById('device-list');
        list.textContent = '';
        var p = document.createElement('p');
        p.style.cssText = 'text-align:center;color:#666;padding:40px;';
        p.textContent = 'Failed to load devices';
        list.appendChild(p);
      });
    }

    function renderDeviceList(devices) {
      var list = document.getElementById('device-list');
      list.textContent = '';

      if (devices.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        var p = document.createElement('p');
        p.textContent = 'No paired devices';
        var hint = document.createElement('p');
        hint.className = 'hint';
        hint.textContent = 'Use "Pair New Device" to connect a phone or laptop';
        empty.appendChild(p);
        empty.appendChild(hint);
        list.appendChild(empty);
        return;
      }

      for (var i = 0; i < devices.length; i++) {
        var dev = devices[i];
        var row = document.createElement('div');
        row.className = 'device-row';

        var nameEl = document.createElement('div');
        nameEl.className = 'device-row-name';
        nameEl.textContent = dev.name || 'Unknown';

        var badge = document.createElement('div');
        badge.className = 'device-row-badge ' + (dev.connected ? 'connected' : 'disconnected');
        badge.textContent = dev.connected ? 'Connected' : 'Disconnected';

        var unpairBtn = document.createElement('button');
        unpairBtn.className = 'device-row-unpair';
        unpairBtn.textContent = '\u2715';
        unpairBtn.setAttribute('data-address', dev.address);
        unpairBtn.onclick = function() {
          var addr = this.getAttribute('data-address');
          unpairDevice(addr);
        };

        row.appendChild(nameEl);
        row.appendChild(badge);
        row.appendChild(unpairBtn);
        list.appendChild(row);
      }
    }

    function changePage(delta) {
      var newPage = _pairedPage + delta;
      if (newPage < 1 || newPage > _pairedTotalPages) return;
      _pairedPage = newPage;
      loadPairedDevices();
    }

    function unpairDevice(address) {
      fetch('/api/bluetooth/unpair', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address: address })
      }).then(function() {
        loadPairedDevices();
      }).catch(function() {});
    }

    // === Init ===
    (function init() {
      // Parse URL params
      var params = new URLSearchParams(location.search);
      if (params.get('tab') === 'bluetooth') switchTab('bt');
      if (params.get('return')) _returnUrl = params.get('return');

      // Hide continue link on kiosk
      if (isKiosk()) {
        document.getElementById('continue-link').className = 'continue-link hide';
      }

      // Load data
      loadWiFiInfo();
      loadBTStatus();

      // If navigated here for pairing, start PIN polling
      if (params.get('pairing') === '1') {
        startPINPolling();
        // Also check immediately for PIN
        fetch('/api/bluetooth/pairing').then(function(r) { return r.json(); }).then(function(d) {
          if (d.active && d.pin) {
            showPairingPIN(d.pin, d.device);
          }
        }).catch(function() {});
      }

      // Periodic refresh
      setInterval(function() {
        if (document.getElementById('pin-overlay').className.indexOf('active') === -1) {
          loadBTStatus();
        }
      }, 15000);
    })();
  </script>
</body>
</html>
```
