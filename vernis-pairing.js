// Vernis setup pairing - the frame's own screen only.
//
// Until setup is finished, the frame shows a QR code and a 6-digit code. A
// phone that scans the QR (or types the code into the setup wizard) proves
// its owner can see this screen, which is what allows setting the first
// device password (see /api/setup/pair in app.py).
//
// <script src="vernis-pairing.js" data-mode="home"></script>    always shown
// <script src="vernis-pairing.js" data-mode="gallery"></script> only while a
//                                                               phone asks
(function () {
  if (location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') return;

  var mode = (document.currentScript && document.currentScript.dataset.mode) || 'home';
  var overlay = null;
  var shownUrl = '';
  var dismissed = false;

  // Same look as the setup wizard (welcome.html) and the active theme
  var CSS =
    '#vernis-pairing{position:fixed;inset:0;z-index:99999;display:none;align-items:center;justify-content:center;' +
    '  background:var(--bg-primary,#0a0a0a);color:var(--text-primary,#fff);font-family:var(--font-body,system-ui,sans-serif);text-align:center;}' +
    '#vernis-pairing .vp-wrap{width:min(88vmin,640px);}' +
    '#vernis-pairing .vp-logo{font-family:"Playfair Display",serif;font-size:6vmin;font-weight:900;letter-spacing:0.15em;' +
    '  background:linear-gradient(135deg,var(--accent-primary),var(--accent-secondary),var(--accent-primary));' +
    '  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}' +
    '#vernis-pairing .vp-diamond{width:1.1vmin;height:1.1vmin;margin:0.6vmin auto;background:var(--accent-primary);transform:rotate(45deg);opacity:0.6;}' +
    '#vernis-pairing .vp-line{width:26vmin;height:1px;margin:0 auto 2.4vmin;opacity:0.5;' +
    '  background:linear-gradient(90deg,transparent,var(--accent-primary),transparent);}' +
    '#vernis-pairing .vp-card{background:var(--bg-secondary,#141414);border:1px solid var(--border-light,#333);' +
    '  border-radius:2.4vmin;padding:2.8vmin 3vmin;}' +
    '#vernis-pairing .vp-title{font-family:var(--font-display,serif);font-size:4.6vmin;font-weight:800;margin-bottom:0.6vmin;}' +
    '#vernis-pairing .vp-sub{color:var(--text-secondary,#bbb);font-size:2.9vmin;margin-bottom:2vmin;}' +
    '#vernis-pairing .vp-qr{width:36vmin;height:36vmin;margin:0 auto;border-radius:1.6vmin;' +
    '  background:#fff center/contain no-repeat;image-rendering:pixelated;}' +
    '#vernis-pairing .vp-or{color:var(--text-muted,#999);font-size:2.7vmin;margin-top:2vmin;}' +
    '#vernis-pairing .vp-or b{color:var(--text-primary,#fff);}' +
    '#vernis-pairing .vp-code{font-family:var(--font-body,system-ui,sans-serif);color:var(--accent-primary,#d4af37);font-size:8.5vmin;' +
    '  font-weight:700;letter-spacing:1.2vmin;margin-top:0.4vmin;font-variant-numeric:lining-nums tabular-nums;}' +
    '#vernis-pairing .vp-hide{margin-top:2.4vmin;padding:1.4vmin 5vmin;font-size:2.7vmin;font-family:var(--font-body,sans-serif);' +
    '  border-radius:1.6vmin;cursor:pointer;background:var(--bg-tertiary,#1e1e1e);color:var(--text-primary,#fff);' +
    '  border:1px solid var(--border-light,#333);}';

  function build() {
    var style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);
    overlay = document.createElement('div');
    overlay.id = 'vernis-pairing';
    // Static markup only; the address and code are set with textContent
    overlay.innerHTML =
      '<div class="vp-wrap">' +
      '  <div class="vp-logo">VERNIS</div><div class="vp-diamond"></div><div class="vp-line"></div>' +
      '  <div class="vp-card">' +
      '    <div class="vp-title">Set up your Vernis</div>' +
      '    <div class="vp-sub">Scan with your phone camera</div>' +
      // A div, not <img>: gallery.html styles every img as hidden artwork
      '    <div class="vp-qr" id="vernis-pairing-qr" role="img" aria-label="Setup QR code"></div>' +
      '    <div class="vp-or">or open <b id="vernis-pairing-addr"></b> and enter</div>' +
      '    <div class="vp-code" id="vernis-pairing-code"></div>' +
      '  </div>' +
      '  <button class="vp-hide" id="vernis-pairing-hide">Not now</button>' +
      '</div>';
    document.body.appendChild(overlay);
    document.getElementById('vernis-pairing-hide').onclick = function () {
      dismissed = true;
      overlay.style.display = 'none';
    };
  }

  function render(d) {
    // Home: shown until dismissed; a phone asking for the code brings it back.
    // Gallery: only while a phone asks, so the art isn't covered otherwise.
    var show = d.active && (d.requested || (mode === 'home' && !dismissed));
    if (d.requested) dismissed = false;
    if (!show) {
      if (overlay) overlay.style.display = 'none';
      return;
    }
    if (!overlay) build();
    if (d.url !== shownUrl) {
      shownUrl = d.url;
      // Cache-buster: the image changes whenever the link rotates
      document.getElementById('vernis-pairing-qr').style.backgroundImage =
        'url("/api/setup/pairing/qr?v=' + encodeURIComponent(d.code) + '")';
    }
    document.getElementById('vernis-pairing-addr').textContent = d.address;
    document.getElementById('vernis-pairing-code').textContent =
      d.code.slice(0, 3) + ' ' + d.code.slice(3);
    overlay.style.display = 'flex';
  }

  function poll() {
    fetch('/api/setup/pairing')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        render(d);
        if (d.active) setTimeout(poll, 4000);  // setup finished: stop asking
      })
      .catch(function () { setTimeout(poll, 10000); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', poll);
  else poll();
})();
