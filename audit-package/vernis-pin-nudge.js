/* Vernis PIN Nudge — gentle banner on the home page suggesting the
 * owner set a PIN once the device is past first-week honeymoon.
 *
 * Triggers when ALL true:
 *   mode === 'A' (no protection active)
 *   has_pin === false (no PIN even configured)
 *   days_since_setup >= 7
 *   not the kiosk (don't nag the wall display)
 *   not dismissed recently
 *
 * Dismissal: × or "Maybe later" → snooze 7 days. After 3 dismissals,
 * mark permanent so we never show it again.
 */
(function () {
  'use strict';

  var DISMISSED_KEY = 'vernis-pin-nudge-dismissed';      // 'true' = forever
  var COUNT_KEY     = 'vernis-pin-nudge-dismiss-count';  // int
  var LAST_KEY      = 'vernis-pin-nudge-last-shown';     // unix-seconds
  var SNOOZE_DAYS   = 7;
  var MAX_DISMISSALS = 3;

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'class') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    if (kids) kids.forEach(function (k) { if (k) n.appendChild(k); });
    return n;
  }

  function shouldShow(cfg) {
    if (cfg.kiosk) return false;
    if (cfg.mode !== 'A') return false;
    if (cfg.has_pin) return false;
    if ((cfg.days_since_setup || 0) < 7) return false;
    if (localStorage.getItem(DISMISSED_KEY) === 'true') return false;
    var last = parseFloat(localStorage.getItem(LAST_KEY) || '0');
    if (last && (Date.now() / 1000 - last) < SNOOZE_DAYS * 86400) return false;
    return true;
  }

  function snooze() {
    var count = parseInt(localStorage.getItem(COUNT_KEY) || '0', 10) + 1;
    localStorage.setItem(COUNT_KEY, String(count));
    localStorage.setItem(LAST_KEY, String(Math.floor(Date.now() / 1000)));
    if (count >= MAX_DISMISSALS) {
      localStorage.setItem(DISMISSED_KEY, 'true');
    }
  }

  function mountNudge() {
    var close = el('button', { class: 'vpn-close', 'aria-label': 'Dismiss',
      text: '×' });
    var title = el('div', { class: 'vpn-title',
      text: '💎  Protect your collection' });
    var body = el('p', { class: 'vpn-body',
      text: 'Vernis is open to anyone on your network right now. Set a PIN '
            + 'so guests can browse without being able to delete or change '
            + 'anything.' });
    var setupBtn = el('button', { class: 'btn btn-primary vpn-cta',
      text: 'Set up PIN' });
    var laterBtn = el('button', { class: 'btn vpn-later',
      text: 'Maybe later' });
    var actions = el('div', { class: 'vpn-actions' }, [setupBtn, laterBtn]);
    var card = el('div', { class: 'vpn-card', role: 'region',
      'aria-label': 'PIN suggestion' }, [close, title, body, actions]);

    function dismissAndRemove() {
      snooze();
      if (card.parentNode) card.parentNode.removeChild(card);
    }
    close.addEventListener('click', dismissAndRemove);
    laterBtn.addEventListener('click', dismissAndRemove);
    setupBtn.addEventListener('click', function () {
      // No snooze — they're acting on it
      window.location.href = '/settings.html#section-security';
    });

    // Attach near the bottom of main content. If the page has a known
    // container (cards grid on index.html) we append after it; otherwise
    // we just append to body.
    var anchor = document.querySelector('.kiosk-buttons')
      || document.querySelector('main')
      || document.body;
    anchor.appendChild(card);
  }

  function init() {
    fetch('/api/security/config')
      .then(function (r) { return r.json(); })
      .then(function (cfg) { if (shouldShow(cfg)) mountNudge(); })
      .catch(function () {});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
