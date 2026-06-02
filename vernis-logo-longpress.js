/* Vernis Logo Long-Press — 5-second hold opens PIN recovery.
 * Auto-attaches to .kiosk-logo on the current page.
 */
(function () {
  'use strict';

  var DURATION_MS = 5000;
  var STARTUP_DELAY_MS = 1000;

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'style') node.style.cssText = attrs[k];
      else if (k === 'class') node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    if (children) children.forEach(function (c) { node.appendChild(c); });
    return node;
  }

  var SVG_NS = 'http://www.w3.org/2000/svg';
  // Circumference of a circle with r=46 → 2 * π * 46 ≈ 289.03
  var RING_CIRCUMFERENCE = 289.03;

  function buildRing(host) {
    // Don't wrap the logo — wrapping breaks the parent flex layout and
    // shifts the logo to upper-left. Instead, establish a positioning
    // context on the logo itself and append the ring as a child.
    if (getComputedStyle(host).position === 'static') {
      host.style.position = 'relative';
    }
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('class', 'vlp-ring');
    svg.setAttribute('viewBox', '0 0 100 100');
    svg.setAttribute('aria-hidden', 'true');
    var circle = document.createElementNS(SVG_NS, 'circle');
    circle.setAttribute('cx', '50');
    circle.setAttribute('cy', '50');
    circle.setAttribute('r', '46');
    circle.setAttribute('fill', 'none');
    circle.setAttribute('stroke', 'currentColor');
    circle.setAttribute('stroke-width', '2');
    circle.setAttribute('stroke-linecap', 'round');
    circle.setAttribute('transform', 'rotate(-90 50 50)');
    circle.setAttribute('stroke-dasharray', String(RING_CIRCUMFERENCE));
    circle.setAttribute('stroke-dashoffset', String(RING_CIRCUMFERENCE));
    svg.appendChild(circle);
    host.appendChild(svg);
    return { svg: svg, circle: circle };
  }

  function attach(logoEl) {
    if (!logoEl || logoEl.dataset.vlpAttached) return;
    logoEl.dataset.vlpAttached = '1';
    var ringParts = buildRing(logoEl);
    var ring = ringParts.svg;
    var ringCircle = ringParts.circle;
    var startTs = 0;
    var raf = 0;
    var ringActive = false;
    var pendingReset = false;

    function tick() {
      var elapsed = Date.now() - startTs;
      if (elapsed >= STARTUP_DELAY_MS && !ringActive) {
        ring.classList.add('active');
        ringActive = true;
      }
      if (ringActive) {
        var progress = Math.min(1,
          (elapsed - STARTUP_DELAY_MS) / (DURATION_MS - STARTUP_DELAY_MS));
        ringCircle.setAttribute('stroke-dashoffset',
          String(RING_CIRCUMFERENCE * (1 - progress)));
        if (elapsed >= DURATION_MS) {
          // 5-second hold reached. Don't open the recovery screen yet —
          // the user's finger is still on the screen. Wait for pointerup
          // so the touch can't leak into whatever opens next.
          pendingReset = true;
          cancelAnimationFrame(raf);
          ring.classList.add('ready');
          return;
        }
      }
      raf = requestAnimationFrame(tick);
    }

    function start(ev) {
      if (ev.cancelable) ev.preventDefault();
      pendingReset = false;
      startTs = Date.now();
      raf = requestAnimationFrame(tick);
      // Capture the pointer so finger drift off the logo doesn't cancel
      // the hold (real touchscreens jitter — pointerleave would fire).
      try { logoEl.setPointerCapture(ev.pointerId); } catch (_) {}
    }

    function cancel() {
      cancelAnimationFrame(raf);
      ring.classList.remove('active');
      ring.classList.remove('ready');
      ringCircle.setAttribute('stroke-dashoffset', String(RING_CIRCUMFERENCE));
      ringActive = false;
      startTs = 0;
      if (pendingReset) {
        pendingReset = false;
        // Small delay so any synthetic mouse-click after touchend
        // doesn't land on the next screen.
        setTimeout(openRecoveryModal, 150);
      }
    }

    logoEl.addEventListener('pointerdown', start);
    logoEl.addEventListener('pointerup', cancel);
    logoEl.addEventListener('pointercancel', cancel);
  }

  var INPUT_STYLE_PWD =
    'width:100%;padding:12px;border-radius:12px;border:1px solid var(--border-light);' +
    'background:var(--bg-tertiary);color:var(--text-primary);margin-bottom:12px;';
  var INPUT_STYLE_PIN =
    'width:100%;padding:12px;border-radius:12px;border:1px solid var(--border-light);' +
    'background:var(--bg-tertiary);color:var(--text-primary);margin-bottom:16px;' +
    'font-size:24px;letter-spacing:8px;text-align:center;';
  var STATUS_STYLE = 'margin-top:12px;font-size:13px;color:var(--text-muted);';
  var SUBMIT_STYLE = 'background:var(--accent-primary);color:#fff;';
  var LABEL_STYLE =
    'display:block;text-align:left;font-size:13px;' +
    'color:var(--text-muted);margin-bottom:6px;';

  function buildModal() {
    var msg = el('div', { class: 'vernis-confirm-message',
      text: 'Reset PIN — enter device password' });
    var pwd = el('input', { type: 'password', id: 'vlp-pwd',
      autocomplete: 'off', style: INPUT_STYLE_PWD });
    var label = el('label', { style: LABEL_STYLE,
      text: 'New PIN (leave empty to clear PIN entirely)' });
    var newpin = el('input', { type: 'password', inputmode: 'numeric',
      pattern: '\\d{6}', maxlength: '6', id: 'vlp-newpin',
      style: INPUT_STYLE_PIN });
    var cancel = el('button', { class: 'vernis-confirm-btn vernis-confirm-cancel',
      id: 'vlp-cancel', text: 'Cancel' });
    var submit = el('button', { class: 'vernis-confirm-btn',
      id: 'vlp-submit', style: SUBMIT_STYLE, text: 'Reset' });
    var actions = el('div', { class: 'vernis-confirm-actions' },
      [cancel, submit]);
    var status = el('div', { id: 'vlp-status', style: STATUS_STYLE });
    var modal = el('div', { class: 'vernis-confirm-modal' },
      [msg, pwd, label, newpin, actions, status]);
    var overlay = el('div', { class: 'vernis-confirm-overlay active',
      style: 'z-index:99999;' }, [modal]);
    return { overlay: overlay, pwd: pwd, newpin: newpin,
      submit: submit, cancel: cancel, status: status };
  }

  function openRecoveryModal() {
    var parts = buildModal();
    document.body.appendChild(parts.overlay);
    parts.pwd.focus();

    function trySubmit() {
      var payload = { owner_password: parts.pwd.value };
      if (parts.newpin.value) {
        if (!/^\d{6}$/.test(parts.newpin.value)) {
          parts.status.textContent = 'PIN must be 6 digits.';
          return;
        }
        payload.new_pin = parts.newpin.value;
      }
      parts.submit.disabled = true;
      parts.status.textContent = 'Resetting…';
      fetch('/api/security/recover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).then(function (r) {
        return r.json().then(function (d) { return { status: r.status, data: d }; });
      }).then(function (res) {
        if (res.status === 200) {
          if (res.data.token && window.VernisLockGuard) {
            window.VernisLockGuard.storeSession(res.data.token, res.data.expires_at);
          }
          parts.overlay.remove();
          window.location.reload();
        } else if (res.status === 429) {
          parts.status.textContent = 'Try again in ' + res.data.retry_after + ' s.';
          parts.submit.disabled = false;
        } else {
          parts.status.textContent = 'Wrong password.';
          parts.submit.disabled = false;
        }
      }).catch(function () {
        parts.status.textContent = 'Network error.';
        parts.submit.disabled = false;
      });
    }

    parts.submit.addEventListener('click', trySubmit);
    parts.cancel.addEventListener('click', function () { parts.overlay.remove(); });
  }

  window.VernisLogoLongPress = { attach: attach, openRecoveryModal: openRecoveryModal };

  function autoAttach() {
    var logo = document.querySelector('.kiosk-logo');
    if (logo) attach(logo);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoAttach);
  } else {
    autoAttach();
  }
})();
