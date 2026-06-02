/**
 * Vernis Virtual Keyboard
 * On-screen keyboard for touchscreen kiosk mode
 */

(function() {
  // Overlay keyboard disabled — WiFi password entry now uses dedicated wifi-keyboard.html page
  // Keep this file for the screen saver activity tracker below
  var _skipKeyboardUI = true;
  var disableKeyboard = localStorage.getItem('vernis-disable-keyboard') === 'true';
  if (disableKeyboard) _skipKeyboardUI = true;

  // Note: innerHTML usage below is safe — all key labels are hardcoded string
  // literals from the layouts object, never user-supplied data.

  const layouts = {
    lower: [
      ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
      ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
      ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
      ['⇧', 'z', 'x', 'c', 'v', 'b', 'n', 'm', '⌫'],
      ['?123', 'ÆØÅ', '@', ' ', '.', '↵']
    ],
    upper: [
      ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
      ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
      ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L'],
      ['⇧', 'Z', 'X', 'C', 'V', 'B', 'N', 'M', '⌫'],
      ['?123', 'ÆØÅ', '@', ' ', '.', '↵']
    ],
    symbols: [
      ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')'],
      ['-', '_', '=', '+', '[', ']', '{', '}', '|', '\\'],
      ['~', '`', ':', ';', '"', "'", '<', '>', '?', '/'],
      ['ABC', ',', '.', ' ', '⌫', '↵']
    ],
    intl: [
      ['æ', 'ø', 'å', 'ä', 'ö', 'ü', 'ß', 'ñ', 'ç', 'é'],
      ['Æ', 'Ø', 'Å', 'Ä', 'Ö', 'Ü', 'è', 'ê', 'ë', 'î'],
      ['ô', 'û', 'ù', 'ï', 'á', 'í', 'ó', 'ú', 'ý', 'ð'],
      ['ABC', ',', '.', ' ', '⌫', '↵']
    ]
  };

  const styles = `
    .vk-overlay {
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      z-index: 10001;
      background: rgba(0,0,0,0.5);
      backdrop-filter: blur(10px);
      padding: 10px;
      animation: vk-slide-up 0.2s ease;
      overflow: hidden;
      box-sizing: border-box;
    }
    @keyframes vk-slide-up {
      from { transform: translateY(100%); }
      to { transform: translateY(0); }
    }
    .vk-container {
      max-width: 100%;
      margin: 0 auto;
      background: var(--bg-secondary, #1a1a1a);
      border-radius: 16px;
      padding: 12px;
      border: 1px solid var(--border-light, #333);
      position: relative;
      overflow: hidden;
      box-sizing: border-box;
    }
    .vk-preview {
      background: var(--bg-primary, #111);
      border: 1px solid var(--border-light, #333);
      border-radius: 8px;
      padding: 16px 18px;
      margin-bottom: 10px;
      color: var(--text-primary, #fff);
      font-size: 26px;
      font-family: monospace;
      min-height: 40px;
      white-space: pre;
      overflow-x: auto;
      overflow-y: hidden;
      letter-spacing: 0.5px;
    }
    .vk-preview-label {
      font-size: 11px;
      color: var(--text-secondary, #888);
      margin-bottom: 4px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .vk-close-top {
      position: absolute;
      top: 6px;
      right: 6px;
      width: 48px;
      height: 48px;
      border: none;
      background: var(--accent-secondary, var(--accent-primary, #6366f1));
      color: white;
      border-radius: 50%;
      font-size: 24px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
      z-index: 1;
    }
    .vk-rows {
      display: flex;
      flex-direction: column;
      gap: 4px;
      overflow: hidden;
    }
    .vk-row {
      display: flex;
      justify-content: center;
      gap: 3px;
      overflow: hidden;
    }
    .vk-key {
      min-width: 0;
      height: 42px;
      flex: 1 1 0%;
      border: none;
      background: var(--bg-tertiary, #2a2a2a);
      color: var(--text-primary, #fff);
      border-radius: 7px;
      font-size: 17px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.1s;
      user-select: none;
      -webkit-tap-highlight-color: transparent;
    }
    .vk-key:active {
      background: var(--accent-primary, #6366f1);
    }
    .vk-key.vk-space {
      flex: 3;
      max-width: none;
      border: 1px solid var(--border-light, #444);
      background: var(--bg-primary, #111);
    }
    .vk-key.vk-special {
      min-width: 0;
      flex: 1.3;
      font-size: 14px;
      background: var(--bg-primary, #111);
    }
    .vk-key.vk-shift.active {
      background: var(--accent-primary, #6366f1);
    }
    .vk-fab {
      position: fixed;
      bottom: 100px;
      right: 16px;
      width: 56px;
      height: 56px;
      border-radius: 50%;
      border: none;
      background: var(--accent-primary, #6366f1);
      color: var(--text-on-accent, white);
      font-size: 24px;
      cursor: pointer;
      z-index: 10001;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      display: flex;
      align-items: center;
      justify-content: center;
      transition: transform 0.2s, box-shadow 0.2s;
    }
    .vk-fab:hover {
      transform: scale(1.1);
      box-shadow: 0 6px 16px rgba(0,0,0,0.4);
    }
    .vk-fab:active {
      transform: scale(0.95);
    }
    @media (max-width: 720px) {
      .vk-fab {
        bottom: 100px;
        right: 16px;
        width: 48px;
        height: 48px;
        font-size: 20px;
      }
      .vk-overlay {
        padding: 4px;
      }
      .vk-container {
        padding: 6px;
        border-radius: 12px;
      }
      .vk-rows {
        gap: 3px;
      }
      .vk-row {
        gap: 3px;
      }
      .vk-key {
        min-width: 0;
        height: 38px;
        font-size: 16px;
        border-radius: 6px;
      }
      .vk-key.vk-special {
        min-width: 0;
        flex: 1.3;
        font-size: 13px;
      }
      .vk-key.vk-space {
        flex: 2.5;
      }
      .vk-preview {
        padding: 10px 12px;
        font-size: 18px;
        margin-bottom: 6px;
        min-height: 24px;
      }
      .vk-preview-label {
        font-size: 10px;
        margin-bottom: 2px;
      }
      .vk-close-top {
        width: 44px;
        height: 44px;
        font-size: 22px;
        top: 4px;
        right: 4px;
      }
    }
    @media (max-width: 480px) {
      .vk-fab {
        bottom: 120px;
        right: 16px;
        width: 44px;
        height: 44px;
        font-size: 18px;
      }
      .vk-overlay {
        padding: 3px;
      }
      .vk-container {
        padding: 5px;
        border-radius: 10px;
      }
      .vk-rows {
        gap: 2px;
      }
      .vk-row {
        gap: 2px;
      }
      .vk-key {
        min-width: 0;
        height: 34px;
        font-size: 14px;
        border-radius: 5px;
      }
      .vk-key.vk-special {
        min-width: 0;
        font-size: 11px;
      }
      .vk-close-top {
        width: 40px;
        height: 40px;
        font-size: 20px;
        top: 2px;
        right: 2px;
      }
    }
  `;

  function initKeyboard() {
    try {
      const styleEl = document.createElement('style');
      styleEl.textContent = styles;
      document.head.appendChild(styleEl);

      const keyboardHTML = `
        <div id="vernis-keyboard" class="vk-overlay" style="display:none;">
          <div class="vk-container">
            <button class="vk-close-top" id="vk-close-btn">&times;</button>
            <div class="vk-preview-label" id="vk-preview-label">Typing:</div>
            <div class="vk-preview" id="vk-preview"></div>
            <div class="vk-rows" id="vk-rows"></div>
          </div>
        </div>
        <button id="vk-fab" class="vk-fab">⌨</button>
      `;

      document.body.insertAdjacentHTML('beforeend', keyboardHTML);

      // Only show FAB on settings page (WiFi password entry)
      var _page = location.pathname.split('/').pop().replace('.html', '') || 'index';
      var _fabPages = ['settings'];
      if (_fabPages.indexOf(_page) === -1) {
        document.getElementById('vk-fab').style.display = 'none';
      }

      let currentInput = null;
      let currentLayout = 'lower';
      let isShift = false;
      let cursorPos = 0; // Manual cursor tracking — selectionStart unreliable on touch

      const fab = document.getElementById('vk-fab');
      const overlay = document.getElementById('vernis-keyboard');
      const closeBtn = document.getElementById('vk-close-btn');

      window.VernisKeyboard = {
        open(input) {
          currentInput = input;
          currentLayout = 'lower';
          isShift = false;
          cursorPos = input ? input.value.length : 0; // Start cursor at end
          this.render();
          overlay.style.display = 'block';
          fab.style.display = 'none';
          this.updatePreview();
          // Scroll input into view above keyboard
          setTimeout(function() {
            if (input && input.scrollIntoView) {
              input.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
          }, 300);
        },

        close() {
          overlay.style.display = 'none';
          // Only restore FAB on settings page
          if (_fabPages.indexOf(_page) !== -1) {
            fab.style.display = 'flex';
          }
        },

        render() {
          var rows = document.getElementById('vk-rows');
          var layout = layouts[currentLayout];

          // Build keyboard rows from hardcoded layout data (no user input — safe)
          rows.innerHTML = layout.map(function(row) {
            return '<div class="vk-row">' + row.map(function(key) {
              var classes = 'vk-key';
              var display = key;

              if (key === ' ') {
                classes += ' vk-space';
                display = '\u2423'; // open box symbol — visible space marker
              }
              if (key === '⇧' || key === '?123' || key === 'ABC' || key === 'ÆØÅ' || key === '⌫' || key === '↵') {
                classes += ' vk-special';
              }
              if (key === '⇧' && isShift) classes += ' vk-shift active';

              return '<button class="' + classes + '" data-key="' + key + '" type="button">' + display + '</button>';
            }).join('') + '</div>';
          }).join('');

          var _lastTouchTime = 0;
          rows.querySelectorAll('.vk-key').forEach(function(btn) {
            btn.addEventListener('touchstart', function(e) {
              e.preventDefault();
              _lastTouchTime = Date.now();
              if (currentInput) currentInput.focus();
              window.VernisKeyboard.handleKey(btn.dataset.key);
            }, { passive: false });
            btn.addEventListener('click', function(e) {
              e.preventDefault();
              if (Date.now() - _lastTouchTime < 400) return;
              window.VernisKeyboard.handleKey(btn.dataset.key);
            });
          });
        },

        updatePreview() {
          var preview = document.getElementById('vk-preview');
          if (!preview || !currentInput) return;
          var val = currentInput.value;
          // Show spaces as visible middle-dot so user can see them
          var display = val.replace(/ /g, '\u00B7');
          preview.textContent = display || '';
          // Auto-scroll preview to end
          preview.scrollLeft = preview.scrollWidth;
        },

        handleKey(key) {
          if (!currentInput) return;

          var value = currentInput.value;

          // Clamp cursorPos to valid range
          if (cursorPos > value.length) cursorPos = value.length;
          if (cursorPos < 0) cursorPos = 0;

          switch(key) {
            case '⇧':
              isShift = !isShift;
              currentLayout = isShift ? 'upper' : 'lower';
              this.render();
              return; // No input change — skip preview/event
            case '?123':
              currentLayout = 'symbols';
              this.render();
              return;
            case 'ABC':
              currentLayout = isShift ? 'upper' : 'lower';
              this.render();
              return;
            case 'ÆØÅ':
              currentLayout = 'intl';
              this.render();
              return;
            case '⌫':
              if (cursorPos > 0) {
                currentInput.value = value.slice(0, cursorPos - 1) + value.slice(cursorPos);
                cursorPos--;
              }
              break;
            case '↵':
              this.close();
              currentInput.dispatchEvent(new Event('change', { bubbles: true }));
              return;
            default:
              currentInput.value = value.slice(0, cursorPos) + key + value.slice(cursorPos);
              cursorPos += key.length;
              if (isShift && currentLayout === 'upper') {
                isShift = false;
                currentLayout = 'lower';
                this.render();
              }
          }

          // Try to sync browser cursor (best-effort, not relied upon)
          try {
            currentInput.setSelectionRange(cursorPos, cursorPos);
          } catch(e) {}

          this.updatePreview();
          currentInput.dispatchEvent(new Event('input', { bubbles: true }));
        }
      };

      fab.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        var input = currentInput || document.querySelector('input[type="text"], input[type="password"], textarea');
        if (input) {
          input.focus();
          currentInput = input;
          VernisKeyboard.open(input);
        }
      });

      closeBtn.addEventListener('click', function(e) {
        e.preventDefault();
        VernisKeyboard.close();
      });

      // Close keyboard before navigating away (back button, link clicks)
      window.addEventListener('pagehide', function() {
        VernisKeyboard.close();
      });
      // Intercept nav link clicks — close keyboard first, then navigate
      document.addEventListener('click', function(e) {
        var link = e.target.closest('a[href]');
        if (link && overlay.style.display !== 'none') {
          e.preventDefault();
          VernisKeyboard.close();
          setTimeout(function() { window.location.href = link.href; }, 150);
        }
      });

      // Auto-open keyboard on input focus in kiosk mode
      var _autoOpen = (location.hostname === 'localhost' || location.hostname === '127.0.0.1');
      function _bindInput(input) {
        if (input._vkBound) return;
        input._vkBound = true;
        input.addEventListener('focus', function() {
          currentInput = input;
          cursorPos = input.value.length; // Sync cursor on focus
          if (_autoOpen) VernisKeyboard.open(input);
        });
        // Touchstart backup — focus doesn't always fire on kiosk touch
        if (_autoOpen) {
          input.addEventListener('touchstart', function() {
            currentInput = input;
            setTimeout(function() { VernisKeyboard.open(input); }, 100);
          }, { passive: true });
        }
      }
      document.querySelectorAll('input[type="text"], input[type="password"], input[type="search"], input[type="email"], textarea').forEach(_bindInput);
      // Also watch for dynamically added inputs
      new MutationObserver(function(mutations) {
        mutations.forEach(function(m) {
          m.addedNodes.forEach(function(n) {
            if (n.nodeType !== 1) return;
            if (n.matches && n.matches('input[type="text"], input[type="password"], input[type="search"], input[type="email"], textarea')) _bindInput(n);
            if (n.querySelectorAll) n.querySelectorAll('input[type="text"], input[type="password"], input[type="search"], input[type="email"], textarea').forEach(_bindInput);
          });
        });
      }).observe(document.body, { childList: true, subtree: true });

    } catch(e) {
      console.error('[VernisKeyboard] Error:', e);
    }
  }

  if (!_skipKeyboardUI) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initKeyboard);
    } else {
      initKeyboard();
    }
  }

  // Screen saver activity tracker - reports touch/click for idle timeout
  // Gallery and lab have their own touchstart-only reporters, so skip here
  // to avoid resetting the idle timer on page load or synthetic clicks.
  var _activityPage = location.pathname.split('/').pop().replace('.html', '') || 'index';
  if (_activityPage !== 'gallery' && _activityPage !== 'lab') {
    var _lastActivityReport = 0;
    function _reportActivity() {
      var now = Date.now();
      if (now - _lastActivityReport < 30000) return;
      _lastActivityReport = now;
      fetch('/api/screen/activity', { method: 'POST' }).catch(function(){});
    }
    document.addEventListener('touchstart', _reportActivity, { passive: true });
    document.addEventListener('click', _reportActivity);
    _reportActivity();
  }
})();
