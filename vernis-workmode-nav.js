/* Vernis Work Mode — show the "Work" menu entries (and the kiosk button)
 * only when Work Mode is turned on in Settings. Hidden by default in the
 * markup so a page never flashes a link the owner didn't opt into. */
(function () {
  'use strict';
  function show(on) {
    // Lets pages make room, e.g. the kiosk start screen fits a 4th button.
    document.documentElement.classList.toggle('workmode-on', !!on);
    document.querySelectorAll('.workmode-nav').forEach(function (el) {
      el.style.display = on ? '' : 'none';
    });
  }
  fetch('/api/workmode/config', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (c) { show(!!c.enabled); })
    .catch(function () {});
  window.vernisWorkmodeNav = show;
})();
