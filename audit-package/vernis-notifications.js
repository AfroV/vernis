/**
 * Vernis v3 - Premium Notification System
 * Replaces standard alert() with glassmorphic toast notifications
 */

function _escNotif(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

const VernisNotifications = {
    container: null,

    init() {
        if (this.container) return;

        this.container = document.createElement('div');
        this.container.id = 'vernis-notifications-container';
        this.container.style.cssText = `
            position: fixed;
            bottom: 30px;
            right: 30px;
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 12px;
            pointer-events: none;
        `;
        document.body.appendChild(this.container);
    },

    show(message, type = 'info', duration = 5000) {
        this.init();

        const toast = document.createElement('div');
        toast.className = `vernis-toast vernis-toast-${type}`;

        const icon = type === 'success' ? '✓' : (type === 'error' ? '✕' : 'ℹ');

        toast.innerHTML = `
            <div class="vernis-toast-icon">${icon}</div>
            <div class="vernis-toast-content">${_escNotif(message)}</div>
            <div class="vernis-toast-close">✕</div>
        `;

        // Style is handled in vernis-themes.css, but we'll add basic behavior here
        toast.style.pointerEvents = 'auto';

        this.container.appendChild(toast);

        // Auto-hide
        const timeout = setTimeout(() => this.hide(toast), duration);

        toast.querySelector('.vernis-toast-close').onclick = () => {
            clearTimeout(timeout);
            this.hide(toast);
        };
    },

    hide(toast) {
        toast.classList.add('vernis-toast-hiding');
        setTimeout(() => toast.remove(), 400);
    },

    confirm(message) {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'vernis-confirm-overlay';
            overlay.innerHTML = `
                <div class="vernis-confirm-modal">
                    <div class="vernis-confirm-message">${_escNotif(message)}</div>
                    <div class="vernis-confirm-actions">
                        <button class="vernis-confirm-btn vernis-confirm-cancel">Cancel</button>
                        <button class="vernis-confirm-btn vernis-confirm-ok">Confirm</button>
                    </div>
                </div>
            `;

            document.body.appendChild(overlay);

            // Force reflow for animation
            overlay.offsetHeight;
            overlay.classList.add('active');

            const cleanup = (result) => {
                overlay.classList.remove('active');
                setTimeout(() => overlay.remove(), 400);
                resolve(result);
            };

            overlay.querySelector('.vernis-confirm-cancel').onclick = () => cleanup(false);
            overlay.querySelector('.vernis-confirm-ok').onclick = () => cleanup(true);
            overlay.onclick = (e) => { if (e.target === overlay) cleanup(false); };
        });
    },

    prompt(message, defaultValue) {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'vernis-confirm-overlay';

            const modal = document.createElement('div');
            modal.className = 'vernis-confirm-modal';

            const msg = document.createElement('div');
            msg.className = 'vernis-confirm-message';
            msg.textContent = message;

            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'vernis-prompt-input';
            input.value = defaultValue || '';
            input.autocomplete = 'off';
            input.spellcheck = false;

            const actions = document.createElement('div');
            actions.className = 'vernis-confirm-actions';

            const cancelBtn = document.createElement('button');
            cancelBtn.className = 'vernis-confirm-btn vernis-confirm-cancel';
            cancelBtn.textContent = 'Cancel';

            const okBtn = document.createElement('button');
            okBtn.className = 'vernis-confirm-btn vernis-confirm-ok';
            okBtn.textContent = 'Save';

            actions.appendChild(cancelBtn);
            actions.appendChild(okBtn);
            modal.appendChild(msg);
            modal.appendChild(input);
            modal.appendChild(actions);
            overlay.appendChild(modal);
            document.body.appendChild(overlay);

            overlay.offsetHeight;
            overlay.classList.add('active');
            input.focus();
            input.select();

            const cleanup = (result) => {
                overlay.classList.remove('active');
                setTimeout(() => overlay.remove(), 400);
                resolve(result);
            };

            cancelBtn.onclick = () => cleanup(null);
            okBtn.onclick = () => cleanup(input.value);
            overlay.onclick = (e) => { if (e.target === overlay) cleanup(null); };
            input.onkeydown = (e) => {
                if (e.key === 'Enter') cleanup(input.value);
                if (e.key === 'Escape') cleanup(null);
            };
        });
    }
};

// Override window.alert
window.vernisAlert = (message, type = 'info') => {
    VernisNotifications.show(message, type);
};

// Premium confirmation
window.vernisConfirm = (message) => VernisNotifications.confirm(message);

// Premium prompt (text input)
window.vernisPrompt = (message, defaultValue) => VernisNotifications.prompt(message, defaultValue);

// Loading toast — stays visible until dismissed
window.showLoading = (msg) => {
    VernisNotifications.init();
    const toast = document.createElement('div');
    toast.className = 'vernis-toast vernis-toast-info';
    toast.innerHTML = `
        <div class="vernis-toast-icon" style="animation: vernis-spin 1s linear infinite;">⟳</div>
        <div class="vernis-toast-content">${_escNotif(msg)}</div>
    `;
    toast.style.pointerEvents = 'auto';
    VernisNotifications.container.appendChild(toast);
    return () => VernisNotifications.hide(toast);
};

// Map types for easier usage
window.showSuccess = (msg) => window.vernisAlert(msg, 'success');
window.showError = (msg) => window.vernisAlert(msg, 'error');
window.showInfo = (msg) => window.vernisAlert(msg, 'info');

// Clipboard copy with fallback for HTTP (non-secure context)
window.copyToClipboard = (text) => {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => showSuccess('Copied!')).catch(() => _fallbackCopy(text));
    } else {
        _fallbackCopy(text);
    }
};
function _fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); showSuccess('Copied!'); }
    catch(e) { showError('Copy failed'); }
    ta.remove();
}
