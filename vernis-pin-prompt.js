/* Vernis PIN Prompt — wraps an API call that may return 401 in Mode B/C.
 *
 * Usage:
 *   VernisPinPrompt.withPin(function (headers) {
 *     return fetch('/api/nft-delete', {
 *       method: 'POST',
 *       headers: Object.assign({'Content-Type':'application/json'}, headers),
 *       body: JSON.stringify({ filenames: ['a.jpg'] })
 *     });
 *   }).then(handleResponse);
 *
 * Delegates the PIN entry UI to vernis-pin-modal.js so all PIN screens
 * share one full-screen visual + behaviour.
 */
(function () {
  'use strict';

  function authHeaders() {
    if (window.VernisLockGuard) return window.VernisLockGuard.authHeaders();
    var t = localStorage.getItem('vernis-pin-session');
    return t ? { 'X-Vernis-PIN-Session': t } : {};
  }

  function promptForPin() {
    return new Promise(function (resolve, reject) {
      if (!window.VernisPinModal) {
        reject(new Error('pin_modal_missing'));
        return;
      }
      window.VernisPinModal.open({
        title: 'Enter PIN to continue',
        subtitle: 'Confirm to proceed',
        onSuccess: function () { resolve(); },
        onCancel:  function () { reject(new Error('pin_cancelled')); },
      });
    });
  }

  function withPin(callFn) {
    return callFn(authHeaders()).then(function (r) {
      if (r.status !== 401) return r;
      return r.clone().json().then(function (d) {
        if (d && d.error === 'pin_required') {
          return promptForPin().then(function () { return callFn(authHeaders()); });
        }
        return r;
      }).catch(function () { return r; });
    });
  }

  window.VernisPinPrompt = { withPin: withPin, promptForPin: promptForPin };
})();
