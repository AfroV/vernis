/* Vernis Mode Pill — subtle status indicator on the kiosk home page.
 *
 * Shows only on the kiosk itself (NOT on phones / remote browsers).
 * Hidden in Mode A. Subtle, dimmed, bottom of the page.
 */
(function () {
  'use strict';

  var COPY = {
    B: '🔒 Protected',
    C: '🔒 Restricted',
  };

  function init() {
    fetch('/api/security/config')
      .then(function (r) { return r.json(); })
      .then(function (cfg) {
        if (!cfg.kiosk) return;       // only on the device itself
        if (cfg.mode === 'A') return; // hidden in Open
        var label = COPY[cfg.mode];
        if (!label) return;
        var pill = document.createElement('div');
        pill.className = 'vmp-pill';
        pill.textContent = label;
        document.body.appendChild(pill);
      })
      .catch(function () {});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
