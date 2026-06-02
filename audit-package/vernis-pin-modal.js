/* Vernis PIN Modal — shared full-screen PIN UI.
 *
 * Public API:
 *   VernisPinModal.open({title?, subtitle?, showTrustToggle?, onSuccess, onCancel})
 *     Existing-PIN entry (used by lock-guard for Mode C, pin-prompt for delete).
 *
 *   VernisPinModal.openSetup({onSuccess, onCancel})
 *     Initial PIN setup. Two-step: device password → new 6-digit PIN.
 *     Posts /api/security/recover.
 *
 *   VernisPinModal.openChangePin({onSuccess, onCancel})
 *     Change existing PIN. Two-step: current PIN → new PIN.
 *     Posts /api/security/pin.
 *
 *   VernisPinModal.openRemovePin({onSuccess, onCancel})
 *     Remove PIN. One step: confirm current PIN. Drops device to Mode A.
 *     Deletes /api/security/pin.
 *
 *   VernisPinModal.close()
 *
 * All DOM built with createElement + textContent — no innerHTML.
 *
 * ─────────────────────────────────────────────────────────────────────
 * Keyboard note: createAlphanumericKeyboard() is intentionally written
 * to be extractable into a shared vernis-keyboard-builder.js later.
 * The 4 layouts (lower/upper/symbols/intl) are byte-for-byte identical
 * to wifi-keyboard.html so the two implementations can be unified with
 * a one-line change in that page when the time comes.
 * ─────────────────────────────────────────────────────────────────────
 */
(function () {
  'use strict';

  // ── Storage keys ────────────────────────────────────────────────────
  var SESSION_KEY = 'vernis-pin-session';
  var SESSION_EXP_KEY = 'vernis-pin-session-expires';
  var SESSION_PERM_KEY = 'vernis-pin-session-permanent';

  // ── Small helpers ───────────────────────────────────────────────────
  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'style') n.style.cssText = attrs[k];
      else if (k === 'class') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    if (children) children.forEach(function (c) { if (c) n.appendChild(c); });
    return n;
  }
  function storeSession(d) {
    if (!d || !d.token) return;
    localStorage.setItem(SESSION_KEY, d.token);
    localStorage.setItem(SESSION_EXP_KEY,
      d.expires_at == null ? '' : String(d.expires_at));
    localStorage.setItem(SESSION_PERM_KEY, d.permanent ? '1' : '0');
  }
  function fmtCountdown(seconds) {
    var s = Math.max(0, Math.round(seconds));
    var m = Math.floor(s / 60), r = s % 60;
    return m + ':' + (r < 10 ? '0' + r : r);
  }
  function nextCooldownLabel(secs) {
    if (secs < 60) return secs + '-second wait';
    if (secs < 3600) return Math.round(secs / 60) + '-minute wait';
    return secs === 3600 ? '1-hour wait' : Math.round(secs / 3600) + '-hour wait';
  }
  function authHeaders() {
    var t = localStorage.getItem(SESSION_KEY);
    return t ? { 'X-Vernis-PIN-Session': t } : {};
  }

  // ── Layouts ─────────────────────────────────────────────────────────
  // Verbatim from wifi-keyboard.html. Single source for future
  // extraction: window.VernisKeyboardLayouts.
  var LAYOUTS = {
    lower: [
      ['1','2','3','4','5','6','7','8','9','0'],
      ['q','w','e','r','t','y','u','i','o','p'],
      ['a','s','d','f','g','h','j','k','l'],
      ['⇧','z','x','c','v','b','n','m','⌫'],
      ['?123','ÆØÅ','@',' ','.','↵'],
    ],
    upper: [
      ['1','2','3','4','5','6','7','8','9','0'],
      ['Q','W','E','R','T','Y','U','I','O','P'],
      ['A','S','D','F','G','H','J','K','L'],
      ['⇧','Z','X','C','V','B','N','M','⌫'],
      ['?123','ÆØÅ','@',' ','.','↵'],
    ],
    symbols: [
      ['!','@','#','$','%','^','&','*','(',')'],
      ['-','_','=','+','[',']','{','}','|','\\'],
      ['~','`',':',';','"',"'",'<','>','?','/'],
      ['ABC',',','.',' ','⌫','↵'],
    ],
    intl: [
      ['æ','ø','å','ä','ö','ü','ß','ñ','ç','é'],
      ['Æ','Ø','Å','Ä','Ö','Ü','è','ê','ë','î'],
      ['ô','û','ù','ï','á','í','ó','ú','ý','ð'],
      ['ABC',',','.',' ','⌫','↵'],
    ],
  };
  window.VernisKeyboardLayouts = LAYOUTS;

  /**
   * createAlphanumericKeyboard(container, options) → keyboard handle
   *
   * Renders an on-screen alphanumeric keyboard into `container`.
   * Layouts and class names are stable (.vk-*) so a future extraction
   * to vernis-keyboard-builder.js is trivial.
   *
   * options:
   *   onChange(value, addedKey?) — fired on every change
   *   onSubmit(value)            — fired when ↵ pressed
   *   initialValue               — defaults to ''
   *
   * returns: { getValue(), setValue(v), destroy() }
   */
  function createAlphanumericKeyboard(container, options) {
    options = options || {};
    var value = options.initialValue || '';
    var currentLayout = 'lower';
    var isShift = false;
    var kbEl = el('div', { class: 'vk-keyboard' });
    container.appendChild(kbEl);

    function fire() {
      if (options.onChange) options.onChange(value);
    }

    function handleKey(key) {
      switch (key) {
        case '⇧':  // shift
          isShift = !isShift;
          currentLayout = isShift ? 'upper' : 'lower';
          render();
          return;
        case '?123':
          currentLayout = 'symbols';
          render();
          return;
        case 'ABC':
          currentLayout = isShift ? 'upper' : 'lower';
          render();
          return;
        case 'ÆØÅ':
          currentLayout = 'intl';
          render();
          return;
        case '⌫':  // backspace
          value = value.slice(0, -1);
          break;
        case '↵':  // enter
          if (options.onSubmit) options.onSubmit(value);
          return;
        default:
          value += key;
          if (isShift && currentLayout === 'upper') {
            isShift = false;
            currentLayout = 'lower';
            render();
          }
      }
      fire();
    }

    function render() {
      while (kbEl.firstChild) kbEl.removeChild(kbEl.firstChild);
      LAYOUTS[currentLayout].forEach(function (row) {
        var rowEl = el('div', { class: 'vk-row' });
        row.forEach(function (key) {
          var btn = el('button', {
            type: 'button',
            class: 'vk-key',
            'data-key': key,
          });
          if (key === ' ') { btn.classList.add('vk-space'); btn.textContent = '␣'; }
          else if (key === '⇧') {
            btn.classList.add('vk-special');
            if (isShift) btn.classList.add('vk-shift-active');
            btn.textContent = key;
          }
          else if (key === '⌫') { btn.classList.add('vk-backspace'); btn.textContent = key; }
          else if (key === '?123' || key === 'ABC' || key === '↵'
                   || key === 'ÆØÅ') {
            btn.classList.add('vk-special');
            btn.textContent = key;
          }
          else btn.textContent = key;

          // Touch + click with debounce so the click that follows a
          // touchend doesn't double-fire (same pattern as wifi-keyboard.html).
          var lastTouch = 0;
          btn.addEventListener('touchstart', function (e) {
            e.preventDefault();
            lastTouch = Date.now();
            handleKey(key);
          }, { passive: false });
          btn.addEventListener('click', function (e) {
            e.preventDefault();
            if (Date.now() - lastTouch < 400) return;
            handleKey(key);
          });
          rowEl.appendChild(btn);
        });
        kbEl.appendChild(rowEl);
      });
    }

    render();
    return {
      getValue: function () { return value; },
      setValue: function (v) { value = v || ''; fire(); },
      destroy: function () {
        if (kbEl.parentNode) kbEl.parentNode.removeChild(kbEl);
      },
    };
  }
  window.VernisCreateAlphanumericKeyboard = createAlphanumericKeyboard;

  // ── Numeric keypad (used by all PIN-entry steps) ───────────────────
  function createNumericKeypad(container, options) {
    options = options || {};
    var pin = options.initialValue || '';
    var disabled = false;
    var kbEl = el('div', { class: 'vpm-keypad' });
    container.appendChild(kbEl);
    var labels = ['1','2','3','4','5','6','7','8','9','⌫','0',''];
    var buttons = [];
    labels.forEach(function (label) {
      if (label === '') {
        kbEl.appendChild(el('div', { class: 'vpm-key-spacer' }));
        return;
      }
      var btn = el('button', { class: 'vpm-key', type: 'button', text: label });
      buttons.push(btn);
      kbEl.appendChild(btn);
      btn.addEventListener('click', function () {
        if (disabled) return;
        if (label === '⌫') pin = pin.slice(0, -1);
        else if (pin.length < 6) pin += label;
        if (options.onChange) options.onChange(pin);
        if (pin.length === 6 && options.onComplete) options.onComplete(pin);
      });
    });
    return {
      getValue: function () { return pin; },
      reset: function () { pin = ''; if (options.onChange) options.onChange(pin); },
      setDisabled: function (d) {
        disabled = d;
        buttons.forEach(function (b) { b.disabled = d; });
      },
    };
  }

  // ── Dots indicator (6 positions) ───────────────────────────────────
  function createDots(container) {
    var row = el('div', { class: 'vpm-dots' });
    container.appendChild(row);
    var els = [];
    for (var i = 0; i < 6; i++) {
      var d = el('span', { class: 'vpm-dot' });
      els.push(d);
      row.appendChild(d);
    }
    return {
      set: function (count) {
        els.forEach(function (el_, i) {
          el_.classList.toggle('filled', i < count);
        });
      },
    };
  }

  // ── Shared screen shell ────────────────────────────────────────────
  function buildShell(opts) {
    var back = el('button', { class: 'vpm-back', 'aria-label': 'Back',
      text: '←' });
    back.addEventListener('click', opts.onBack || function () {});
    var title = el('div', { class: 'vpm-title', text: opts.title || '' });
    var header = el('div', { class: 'vpm-header' }, [back, title]);
    var body = el('div', { class: 'vpm-body' });
    var screen = el('div', {
      class: 'vpm-screen',
      role: 'dialog',
      'aria-modal': 'true',
      'aria-label': opts.title || '',
    }, [header, body]);
    return { screen: screen, body: body, header: header, title: title, back: back };
  }

  function mount(screen) {
    closeInternal();
    document.body.appendChild(screen);
    document.documentElement.classList.add('vpm-active');
    window._vpmActiveScreen = screen;
  }
  function closeInternal() {
    var screen = window._vpmActiveScreen;
    if (screen && screen.parentNode) screen.parentNode.removeChild(screen);
    document.documentElement.classList.remove('vpm-active');
    window._vpmActiveScreen = null;
    if (window._vpmCooldownTimer) {
      clearInterval(window._vpmCooldownTimer);
      window._vpmCooldownTimer = 0;
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // Flow 1: open() — existing-PIN entry (login + Mode B delete prompt)
  // ────────────────────────────────────────────────────────────────────
  function open(opts) {
    opts = opts || {};
    var shell = buildShell({
      title: opts.title || 'Enter PIN',
      onBack: function () {
        closeInternal();
        if (opts.onCancel) opts.onCancel();
      },
    });

    var state = {
      cooldownUntil: 0,
      attemptsCount: 0,
      nextCooldown: 0,
      lastError: null,
      trustChecked: false,
      busy: false,
    };

    // Wrap PIN-entry UI in a single group so Forgot PIN can hide all of it
    // at once. Without this, the Forgot panel opens BELOW the keypad and
    // gets clipped — the user only sees the title peek out and reasonably
    // concludes "nothing happened".
    var pinGroup = el('div', { class: 'vpm-pin-group' });
    shell.body.appendChild(pinGroup);

    if (opts.subtitle) {
      pinGroup.appendChild(el('div', { class: 'vpm-subtitle',
        text: opts.subtitle }));
    }
    var dots = createDots(pinGroup);
    var status = el('div', { class: 'vpm-status' });
    pinGroup.appendChild(status);

    var keypad = createNumericKeypad(pinGroup, {
      onChange: function (pin) { dots.set(pin.length); },
      onComplete: function (pin) { submit(pin); },
    });

    var trustWrap = null;
    if (opts.showTrustToggle !== false) {
      var cb = el('input', { type: 'checkbox', id: 'vpm-trust',
        class: 'vpm-trust-checkbox' });
      cb.addEventListener('change', function () {
        state.trustChecked = cb.checked;
      });
      trustWrap = el('div', { class: 'vpm-trust' }, [
        cb,
        el('label', { class: 'vpm-trust-label', for: 'vpm-trust',
          text: 'Trust this browser until I sign out' }),
      ]);
      pinGroup.appendChild(trustWrap);
    }

    var forgotLink = el('button', { class: 'vpm-forgot-link', type: 'button',
      text: 'Forgot PIN?' });
    pinGroup.appendChild(forgotLink);
    var forgotPanel = buildForgotPanel(function backToLogin() {
      forgotPanel.classList.remove('open');
      pinGroup.style.display = '';
      keypad.setDisabled(false);
    });
    shell.body.appendChild(forgotPanel);
    forgotLink.addEventListener('click', function () {
      // Hide all PIN-entry UI so the Forgot panel takes over the modal body
      pinGroup.style.display = 'none';
      forgotPanel.classList.add('open');
    });

    function setStatus() {
      var inCooldown = state.cooldownUntil > Date.now() / 1000;
      if (inCooldown) {
        status.textContent = '⏱︎  Try again in '
          + fmtCountdown(state.cooldownUntil - Date.now() / 1000);
        status.className = 'vpm-status vpm-status-warn';
        keypad.setDisabled(true);
      } else if (state.lastError === 'invalid_pin'
                 && state.nextCooldown > 0
                 && (state.attemptsCount === 6
                     || state.attemptsCount === 10
                     || state.attemptsCount === 15)) {
        status.textContent = '⚠  Wrong PIN. Next wrong attempt will trigger a '
          + nextCooldownLabel(state.nextCooldown) + '.';
        status.className = 'vpm-status vpm-status-warn';
        keypad.setDisabled(false);
      } else if (state.lastError === 'invalid_pin') {
        status.textContent = '⚠  Wrong PIN.';
        status.className = 'vpm-status vpm-status-warn';
        keypad.setDisabled(false);
      } else if (state.lastError === 'network') {
        status.textContent = 'Network error. Try again.';
        status.className = 'vpm-status vpm-status-warn';
        keypad.setDisabled(false);
      } else {
        status.textContent = '';
        status.className = 'vpm-status';
        keypad.setDisabled(state.busy);
      }
    }

    function tickCooldown() {
      if (window._vpmCooldownTimer) clearInterval(window._vpmCooldownTimer);
      window._vpmCooldownTimer = setInterval(function () {
        if (state.cooldownUntil <= Date.now() / 1000) {
          clearInterval(window._vpmCooldownTimer);
          window._vpmCooldownTimer = 0;
        }
        setStatus();
      }, 250);
    }

    function submit(pin) {
      state.busy = true;
      setStatus();
      fetch('/api/security/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pin: pin,
          trust_until_signout: state.trustChecked,
        }),
      }).then(function (r) {
        return r.json().then(function (d) {
          return { status: r.status, data: d };
        });
      }).then(function (res) {
        state.busy = false;
        if (res.status === 200) {
          storeSession(res.data);
          closeInternal();
          if (opts.onSuccess) opts.onSuccess(res.data);
          return;
        }
        var d = res.data || {};
        state.attemptsCount = d.attempts_count || 0;
        state.nextCooldown = d.next_cooldown || 0;
        keypad.reset();
        dots.set(0);
        if (res.status === 429) {
          state.lastError = null;
          state.cooldownUntil = Date.now() / 1000 + (d.retry_after || 0);
          tickCooldown();
        } else if (res.status === 401 || res.status === 422) {
          state.lastError = 'invalid_pin';
          if (d.cooldown_remaining > 0) {
            state.cooldownUntil = Date.now() / 1000 + d.cooldown_remaining;
            tickCooldown();
          }
        }
        setStatus();
      }).catch(function () {
        state.busy = false;
        state.lastError = 'network';
        setStatus();
      });
    }

    // Bootstrap: if a cooldown is already running, surface it.
    fetch('/api/security/config').then(function (r) { return r.json(); })
      .then(function (cfg) {
        if (cfg.locked_until && cfg.locked_until > Date.now() / 1000) {
          state.cooldownUntil = cfg.locked_until;
          state.attemptsCount = cfg.attempts_count || 0;
          state.nextCooldown = cfg.next_cooldown || 0;
          tickCooldown();
        }
        setStatus();
      })
      .catch(function () { setStatus(); });

    mount(shell.screen);
  }

  function buildForgotPanel(onBack) {
    var fpTitle = el('div', { class: 'vpm-fp-title', text: 'Forgot PIN?' });
    var fpIntro = el('div', { class: 'vpm-fp-intro',
      text: 'No worries — you can reset it.' });
    var step1 = el('div', { class: 'vpm-fp-step' }, [
      el('div', { class: 'vpm-fp-num', text: '1' }),
      el('div', { class: 'vpm-fp-text',
        text: 'On your Vernis device, press and hold the VERNIS logo for '
              + '5 seconds. You’ll be asked for your device password.' }),
    ]);
    var orSep = el('div', { class: 'vpm-fp-or', text: '— or —' });
    var step2 = el('div', { class: 'vpm-fp-step' }, [
      el('div', { class: 'vpm-fp-num', text: '2' }),
      el('div', { class: 'vpm-fp-text' }, [
        document.createTextNode('If you have SSH access, run: '),
        el('code', { class: 'vpm-fp-code',
          text: 'sudo /opt/vernis/scripts/reset-pin.sh' }),
      ]),
    ]);
    var backBtn = el('button', { class: 'vpm-fp-back', type: 'button',
      text: '←  Back to PIN entry' });
    backBtn.addEventListener('click', onBack);
    return el('div', { class: 'vpm-forgot-panel' },
      [fpTitle, fpIntro, step1, orSep, step2, backBtn]);
  }

  // ────────────────────────────────────────────────────────────────────
  // Flow 2: openSetup() — initial PIN setup (password → new PIN)
  // ────────────────────────────────────────────────────────────────────
  function openSetup(opts) {
    opts = opts || {};
    var pwd = '';
    var newPin = '';
    var step = 1;

    var shell = buildShell({
      title: 'Set up your PIN',
      onBack: function () {
        if (step === 2) { step = 1; renderStep(); return; }
        closeInternal();
        if (opts.onCancel) opts.onCancel();
      },
    });

    function renderStep() {
      while (shell.body.firstChild) shell.body.removeChild(shell.body.firstChild);

      if (step === 1) {
        shell.title.textContent = 'Step 1 of 2 — Device password';
        shell.body.appendChild(el('div', { class: 'vpm-subtitle',
          text: 'Enter your Vernis device password to authorize PIN setup.' }));

        var inputWrap = el('div', { class: 'vpm-pwd-wrap' });
        var pwdInput = el('input', {
          type: 'password', class: 'vpm-pwd-input', readonly: 'readonly',
          autocomplete: 'off', placeholder: 'Device password',
        });
        inputWrap.appendChild(pwdInput);

        var nextBtn = el('button', { class: 'vpm-primary', type: 'button',
          text: 'Next' });
        nextBtn.disabled = true;
        inputWrap.appendChild(nextBtn);
        shell.body.appendChild(inputWrap);

        var errLine = el('div', { class: 'vpm-status' });
        shell.body.appendChild(errLine);

        var kb = createAlphanumericKeyboard(shell.body, {
          initialValue: pwd,
          onChange: function (v) {
            pwd = v;
            pwdInput.value = v;
            nextBtn.disabled = !v;
          },
          onSubmit: function () { if (pwd) nextBtn.click(); },
        });

        nextBtn.addEventListener('click', function () {
          if (!pwd) return;
          step = 2;
          renderStep();
        });
      } else {
        shell.title.textContent = 'Step 2 of 2 — Choose a 6-digit PIN';
        shell.body.appendChild(el('div', { class: 'vpm-subtitle',
          text: 'You’ll use this PIN to confirm protected actions.' }));

        var dots = createDots(shell.body);
        var status = el('div', { class: 'vpm-status' });
        shell.body.appendChild(status);

        var keypad = createNumericKeypad(shell.body, {
          onChange: function (pin) { newPin = pin; dots.set(pin.length); },
          onComplete: function (pin) {
            keypad.setDisabled(true);
            status.textContent = 'Setting up…';
            status.className = 'vpm-status';
            fetch('/api/security/recover', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ owner_password: pwd, new_pin: pin }),
            }).then(function (r) {
              return r.json().then(function (d) {
                return { status: r.status, data: d };
              });
            }).then(function (res) {
              if (res.status === 200) {
                storeSession(res.data);
                closeInternal();
                if (opts.onSuccess) opts.onSuccess(res.data);
                return;
              }
              if (res.status === 401) {
                // Wrong password — go back to step 1 with a message
                step = 1;
                renderStep();
                var s = shell.body.querySelector('.vpm-status');
                if (s) {
                  s.textContent = '⚠  Wrong device password. Try again.';
                  s.className = 'vpm-status vpm-status-warn';
                }
                return;
              }
              if (res.status === 429) {
                status.textContent = '⏱︎  Too many tries. Wait '
                  + (res.data.retry_after || 0) + ' seconds.';
                status.className = 'vpm-status vpm-status-warn';
                keypad.setDisabled(false);
                return;
              }
              status.textContent = 'Could not set PIN. ' + (res.data.error || '');
              status.className = 'vpm-status vpm-status-warn';
              keypad.setDisabled(false);
            }).catch(function () {
              status.textContent = 'Network error.';
              status.className = 'vpm-status vpm-status-warn';
              keypad.setDisabled(false);
            });
          },
        });
      }
    }
    renderStep();
    mount(shell.screen);
  }

  // ────────────────────────────────────────────────────────────────────
  // Flow 3: openChangePin() — current PIN → new PIN
  // ────────────────────────────────────────────────────────────────────
  function openChangePin(opts) {
    opts = opts || {};
    var currentPin = '';
    var newPin = '';
    var step = 1;

    var shell = buildShell({
      title: 'Change PIN',
      onBack: function () {
        if (step === 2) { step = 1; renderStep(); return; }
        closeInternal();
        if (opts.onCancel) opts.onCancel();
      },
    });

    function renderStep() {
      while (shell.body.firstChild) shell.body.removeChild(shell.body.firstChild);
      shell.title.textContent = step === 1
        ? 'Step 1 of 2 — Current PIN'
        : 'Step 2 of 2 — New PIN';
      shell.body.appendChild(el('div', { class: 'vpm-subtitle',
        text: step === 1
          ? 'Confirm your current PIN to continue.'
          : 'Choose a new 6-digit PIN.' }));
      var dots = createDots(shell.body);
      var status = el('div', { class: 'vpm-status' });
      shell.body.appendChild(status);
      var keypad = createNumericKeypad(shell.body, {
        onChange: function (p) { dots.set(p.length); },
        onComplete: function (p) {
          if (step === 1) {
            currentPin = p;
            step = 2;
            renderStep();
          } else {
            newPin = p;
            keypad.setDisabled(true);
            status.textContent = 'Updating…';
            status.className = 'vpm-status';
            fetch('/api/security/pin', {
              method: 'POST',
              headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
              body: JSON.stringify({ current_pin: currentPin, new_pin: newPin }),
            }).then(function (r) {
              return r.json().then(function (d) {
                return { status: r.status, data: d };
              });
            }).then(function (res) {
              if (res.status === 200) {
                closeInternal();
                if (opts.onSuccess) opts.onSuccess();
                return;
              }
              if (res.status === 401) {
                // Wrong current PIN
                step = 1;
                renderStep();
                var s = shell.body.querySelector('.vpm-status');
                if (s) {
                  s.textContent = '⚠  Wrong PIN. Try again.';
                  s.className = 'vpm-status vpm-status-warn';
                }
                return;
              }
              status.textContent = 'Could not change PIN.';
              status.className = 'vpm-status vpm-status-warn';
              keypad.setDisabled(false);
            }).catch(function () {
              status.textContent = 'Network error.';
              status.className = 'vpm-status vpm-status-warn';
              keypad.setDisabled(false);
            });
          }
        },
      });
    }
    renderStep();
    mount(shell.screen);
  }

  // ────────────────────────────────────────────────────────────────────
  // Flow 4: openRemovePin() — confirm and remove
  // ────────────────────────────────────────────────────────────────────
  function openRemovePin(opts) {
    opts = opts || {};
    var shell = buildShell({
      title: 'Remove PIN',
      onBack: function () {
        closeInternal();
        if (opts.onCancel) opts.onCancel();
      },
    });
    shell.body.appendChild(el('div', { class: 'vpm-subtitle',
      text: 'Confirm your current PIN to remove protection. The device '
            + 'will switch to Open mode.' }));
    var dots = createDots(shell.body);
    var status = el('div', { class: 'vpm-status' });
    shell.body.appendChild(status);
    var keypad = createNumericKeypad(shell.body, {
      onChange: function (p) { dots.set(p.length); },
      onComplete: function (p) {
        keypad.setDisabled(true);
        status.textContent = 'Removing…';
        status.className = 'vpm-status';
        fetch('/api/security/pin', {
          method: 'DELETE',
          headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
          body: JSON.stringify({ current_pin: p }),
        }).then(function (r) {
          return r.json().then(function (d) {
            return { status: r.status, data: d };
          });
        }).then(function (res) {
          if (res.status === 200) {
            closeInternal();
            if (opts.onSuccess) opts.onSuccess();
            return;
          }
          if (res.status === 401) {
            status.textContent = '⚠  Wrong PIN. Try again.';
            status.className = 'vpm-status vpm-status-warn';
            keypad.reset();
            dots.set(0);
            keypad.setDisabled(false);
            return;
          }
          status.textContent = 'Could not remove PIN.';
          status.className = 'vpm-status vpm-status-warn';
          keypad.setDisabled(false);
        }).catch(function () {
          status.textContent = 'Network error.';
          status.className = 'vpm-status vpm-status-warn';
          keypad.setDisabled(false);
        });
      },
    });
    mount(shell.screen);
  }

  // ────────────────────────────────────────────────────────────────────
  // Flow 5: openRecover() — owner-password recovery from kiosk long-press.
  // Step 1: device password (alphanumeric keyboard).
  // Step 2: choose a new 6-digit PIN, or tap "Clear PIN" to reset to Mode A.
  // ────────────────────────────────────────────────────────────────────
  function openRecover(opts) {
    opts = opts || {};
    var pwd = '';
    var step = 1;

    var shell = buildShell({
      title: 'Recover device',
      onBack: function () {
        if (step === 2) { step = 1; renderStep(); return; }
        closeInternal();
        if (opts.onCancel) opts.onCancel();
      },
    });

    function submitRecovery(newPin, status, keypad) {
      var payload = { owner_password: pwd };
      if (newPin) payload.new_pin = newPin;
      if (keypad) keypad.setDisabled(true);
      status.textContent = newPin ? 'Setting new PIN…' : 'Clearing PIN…';
      status.className = 'vpm-status';
      fetch('/api/security/recover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).then(function (r) {
        return r.json().then(function (d) { return { status: r.status, data: d }; });
      }).then(function (res) {
        if (res.status === 200) {
          if (res.data.token) storeSession(res.data);
          closeInternal();
          if (opts.onSuccess) opts.onSuccess(res.data);
          else window.location.reload();
          return;
        }
        if (res.status === 401) {
          step = 1;
          renderStep();
          var s = shell.body.querySelector('.vpm-status');
          if (s) {
            s.textContent = '⚠  Wrong device password. Try again.';
            s.className = 'vpm-status vpm-status-warn';
          }
          return;
        }
        if (res.status === 429) {
          status.textContent = '⏱︎  Too many tries. Wait '
            + (res.data.retry_after || 0) + ' seconds.';
          status.className = 'vpm-status vpm-status-warn';
          if (keypad) keypad.setDisabled(false);
          return;
        }
        status.textContent = 'Recovery failed. ' + (res.data.error || '');
        status.className = 'vpm-status vpm-status-warn';
        if (keypad) keypad.setDisabled(false);
      }).catch(function () {
        status.textContent = 'Network error.';
        status.className = 'vpm-status vpm-status-warn';
        if (keypad) keypad.setDisabled(false);
      });
    }

    function renderStep() {
      while (shell.body.firstChild) shell.body.removeChild(shell.body.firstChild);

      if (step === 1) {
        shell.title.textContent = 'Step 1 of 2 — Device password';
        shell.body.appendChild(el('div', { class: 'vpm-subtitle',
          text: 'Enter your Vernis device password to reset the PIN.' }));

        var inputWrap = el('div', { class: 'vpm-pwd-wrap' });
        var pwdInput = el('input', {
          type: 'password', class: 'vpm-pwd-input', readonly: 'readonly',
          autocomplete: 'off', placeholder: 'Device password',
        });
        inputWrap.appendChild(pwdInput);

        var showBtn = el('button', {
          class: 'vpm-show-toggle', type: 'button', text: 'Show',
          title: 'Show/hide password',
        });
        showBtn.addEventListener('click', function () {
          var nowVisible = pwdInput.getAttribute('type') === 'text';
          pwdInput.setAttribute('type', nowVisible ? 'password' : 'text');
          showBtn.textContent = nowVisible ? 'Show' : 'Hide';
        });
        inputWrap.appendChild(showBtn);

        var nextBtn = el('button', { class: 'vpm-primary', type: 'button',
          text: 'Next' });
        nextBtn.disabled = true;
        inputWrap.appendChild(nextBtn);
        shell.body.appendChild(inputWrap);

        var errLine = el('div', { class: 'vpm-status' });
        shell.body.appendChild(errLine);

        createAlphanumericKeyboard(shell.body, {
          initialValue: pwd,
          onChange: function (v) {
            pwd = v;
            pwdInput.value = v;
            nextBtn.disabled = !v;
            // Clear any previous error as soon as the user types
            if (errLine.textContent) {
              errLine.textContent = '';
              errLine.className = 'vpm-status';
            }
          },
          onSubmit: function () { if (pwd) nextBtn.click(); },
        });

        nextBtn.addEventListener('click', function () {
          if (!pwd || nextBtn.disabled) return;
          nextBtn.disabled = true;
          var prevLabel = nextBtn.textContent;
          nextBtn.textContent = 'Verifying…';
          errLine.textContent = '';
          errLine.className = 'vpm-status';
          fetch('/api/security/verify-owner', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ owner_password: pwd }),
          }).then(function (r) {
            return r.json().then(function (d) { return { status: r.status, data: d }; });
          }).then(function (res) {
            nextBtn.textContent = prevLabel;
            if (res.status === 200) {
              step = 2;
              renderStep();
              return;
            }
            if (res.status === 429) {
              errLine.textContent = '⏱︎  Too many tries. Wait '
                + (res.data.retry_after || 0) + ' seconds.';
              errLine.className = 'vpm-status vpm-status-warn';
              nextBtn.disabled = false;
              return;
            }
            errLine.textContent = '⚠  Wrong device password. Try again.';
            errLine.className = 'vpm-status vpm-status-warn';
            nextBtn.disabled = false;
          }).catch(function () {
            nextBtn.textContent = prevLabel;
            errLine.textContent = 'Network error. Try again.';
            errLine.className = 'vpm-status vpm-status-warn';
            nextBtn.disabled = false;
          });
        });
      } else {
        shell.title.textContent = 'Step 2 of 2 — Choose a new PIN';
        shell.body.appendChild(el('div', { class: 'vpm-subtitle',
          text: 'Enter a new 6-digit PIN, or clear the PIN to switch the device to Open mode.' }));

        var dots = createDots(shell.body);
        var status = el('div', { class: 'vpm-status' });
        shell.body.appendChild(status);

        var keypad = createNumericKeypad(shell.body, {
          onChange: function (pin) { dots.set(pin.length); },
          onComplete: function (pin) { submitRecovery(pin, status, keypad); },
        });

        var clearBtn = el('button', {
          class: 'vpm-forgot-link', type: 'button',
          text: 'Clear PIN — switch to Open mode',
        });
        clearBtn.style.marginTop = '14px';
        clearBtn.addEventListener('click', function () {
          submitRecovery('', status, keypad);
        });
        shell.body.appendChild(clearBtn);
      }
    }
    renderStep();
    mount(shell.screen);
  }

  window.VernisPinModal = {
    open: open,
    openSetup: openSetup,
    openChangePin: openChangePin,
    openRemovePin: openRemovePin,
    openRecover: openRecover,
    close: closeInternal,
  };
})();
