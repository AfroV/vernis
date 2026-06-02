/* Vernis Lock Guard — Mode C page gate.
 *
 * On DOMContentLoaded, queries /api/security/config. If Mode C is on
 * and this is a remote (non-kiosk) client without a valid session,
 * hides body content and opens the shared full-screen PIN modal
 * (vernis-pin-modal.js). Reveals page on successful PIN entry.
 *
 * Loaded by: settings.html, library.html, manage.html, lab.html, add.html.
 * Home (index.html / gallery.html) does NOT include it.
 */
(function () {
  'use strict';

  var SESSION_KEY = 'vernis-pin-session';
  var SESSION_EXP_KEY = 'vernis-pin-session-expires';
  var SESSION_PERM_KEY = 'vernis-pin-session-permanent';

  function getStoredSession() {
    var token = localStorage.getItem(SESSION_KEY);
    if (!token) return null;
    var permanent = localStorage.getItem(SESSION_PERM_KEY) === '1';
    if (permanent) return token;  // never expires client-side
    var expires = parseFloat(localStorage.getItem(SESSION_EXP_KEY) || '0');
    if (expires < Date.now() / 1000) {
      clearSession();
      return null;
    }
    return token;
  }

  function storeSession(d) {
    if (!d || !d.token) return;
    localStorage.setItem(SESSION_KEY, d.token);
    localStorage.setItem(SESSION_EXP_KEY,
      d.expires_at == null ? '' : String(d.expires_at));
    localStorage.setItem(SESSION_PERM_KEY, d.permanent ? '1' : '0');
  }

  function clearSession() {
    localStorage.removeItem(SESSION_KEY);
    localStorage.removeItem(SESSION_EXP_KEY);
    localStorage.removeItem(SESSION_PERM_KEY);
  }

  function hideBody() { document.body.style.visibility = 'hidden'; }
  function revealBody() { document.body.style.visibility = ''; }

  function init() {
    hideBody();
    fetch('/api/security/config').then(function (r) { return r.json(); })
      .then(function (cfg) {
        if (cfg.kiosk || cfg.mode !== 'C') { revealBody(); return; }
        if (getStoredSession()) { revealBody(); return; }
        if (!window.VernisPinModal) {
          // Pin-modal script missing — fail open rather than brick page.
          revealBody();
          return;
        }
        window.VernisPinModal.open({
          title: 'Enter PIN to continue',
          subtitle: document.title || 'Vernis',
          onSuccess: function (d) {
            storeSession(d);
            revealBody();
          },
          onCancel: function () {
            window.location.href = '/index.html';
          },
        });
      })
      .catch(function () { revealBody(); });  // fail open on backend issue
  }

  window.VernisLockGuard = {
    getSession: getStoredSession,
    clearSession: clearSession,
    storeSession: storeSession,
    authHeaders: function () {
      var t = getStoredSession();
      return t ? { 'X-Vernis-PIN-Session': t } : {};
    },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
