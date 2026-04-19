// Minimal Settings SPA initializer.
// Settings page HTML is swapped into #page-content via HTMX, so page-specific JS must run on navigation.

function _weNormalizePathname(pathname) {
  const p = (pathname || '').trim();
  if (!p) return '/';
  return p.length > 1 ? p.replace(/\/+$/, '') : p;
}

function _isWorkflowEngineSettingsRoute() {
  const p = _weNormalizePathname(window.location.pathname);
  return p === '/workflow-engine/settings';
}

async function _weFetchJson(url) {
  const resp = await fetch(url, { method: 'GET', credentials: 'include' });
  if (!resp.ok) throw new Error('HTTP ' + resp.status);
  return await resp.json();
}

async function _initSettingsAccountFields() {
  const orgNameInput = document.getElementById('settings-org-name');
  const firstNameInput = document.getElementById('settings-first-name');
  const lastNameInput = document.getElementById('settings-last-name');
  const emailInput = document.getElementById('settings-email');
  const phoneInput = document.getElementById('settings-phone');

  if (!orgNameInput && !firstNameInput && !lastNameInput && !emailInput && !phoneInput) return;

  try {
    const data = await _weFetchJson('/auth/settings');
    if (orgNameInput) orgNameInput.value = data.org_name || '';
    if (firstNameInput) firstNameInput.value = data.first_name || '';
    if (lastNameInput) lastNameInput.value = data.last_name || '';
    if (emailInput) emailInput.value = data.email || '';
    if (phoneInput) phoneInput.value = data.phone_number || '';
  } catch (_) {
    // Non-fatal; the full page load version has richer error handling.
  }
}

async function _init2FAStatus() {
  const statusValue = document.getElementById('2fa-status-value');
  if (!statusValue) return;

  try {
    const data = await _weFetchJson('/auth/me');
    const enabled = !!(data && data.user && data.user.two_factor_enabled);
    statusValue.textContent = enabled ? 'Enabled' : 'Disabled';
    statusValue.style.color = enabled ? 'var(--azure-blue)' : 'var(--text-secondary)';

    const enableBtn = document.getElementById('enable-2fa-btn');
    const disableBtn = document.getElementById('disable-2fa-btn');
    if (enableBtn) enableBtn.style.display = enabled ? 'none' : 'block';
    if (disableBtn) disableBtn.style.display = enabled ? 'block' : 'none';

    return enabled;
  } catch (_) {
    // If session expired, the global handlers/modal take over elsewhere.
  }
  return null;
}

function _sessionTimeoutToDisplay(totalMinutes) {
  const m = Number(totalMinutes);
  if (!isFinite(m) || m <= 0) return { value: '', unit: 'minutes' };
  if (m >= 24 * 60 && m % (24 * 60) === 0) return { value: m / (24 * 60), unit: 'days' };
  if (m >= 60 && m % 60 === 0) return { value: m / 60, unit: 'hours' };
  return { value: m, unit: 'minutes' };
}

function _formatTimeoutLabel(value, unit) {
  const v = Number(value);
  const u =
    unit === 'days' ? (v === 1 ? 'day' : 'days')
    : unit === 'hours' ? (v === 1 ? 'hour' : 'hours')
    : (v === 1 ? 'minute' : 'minutes');
  return (isNaN(v) ? '—' : v) + ' ' + u;
}

async function _initSessionTimeoutAndBanner(twoFaEnabled) {
  const input = document.getElementById('session-timeout-input');
  const unitSelect = document.getElementById('session-timeout-unit');
  const display = document.getElementById('session-timeout-display');
  const banner = document.getElementById('long-session-banner');
  if (!input || !unitSelect) return;

  try {
    const data = await _weFetchJson('/auth/session-timeout');
    const timeoutMinutes = data.session_timeout_minutes ?? (24 * 60);
    const { value, unit } = _sessionTimeoutToDisplay(timeoutMinutes);
    input.value = value;
    unitSelect.value = unit;
    if (display) display.textContent = _formatTimeoutLabel(value, unit);

    // Show/hide long session banner (match existing intent: > 24h AND 2FA disabled)
    if (banner) {
      const show = timeoutMinutes > 24 * 60 && twoFaEnabled === false;
      banner.style.display = show ? 'block' : 'none';
    }
  } catch (_) {
    // Non-fatal.
  }
}

function _bindPasswordPolicyOnce() {
  const inp = document.getElementById('new-password');
  const warnings = document.getElementById('new-password-warnings');
  if (!inp || !warnings) return;
  if (inp.dataset.wePolicyBound === '1') return;
  inp.dataset.wePolicyBound = '1';
  if (window.PasswordPolicy && typeof window.PasswordPolicy.attach === 'function') {
    window.PasswordPolicy.attach('new-password', 'new-password-warnings', 1000);
  }
}

function _bindPasswordResetOnce() {
  const form = document.getElementById('password-reset-form');
  if (!form) return;
  if (form.dataset.weBound === '1') return;
  form.dataset.weBound = '1';

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    const currentPassword = (document.getElementById('current-password') || {}).value || '';
    const newPassword = (document.getElementById('new-password') || {}).value || '';
    const newPasswordConfirm = (document.getElementById('new-password-confirm') || {}).value || '';
    const errorDiv = document.getElementById('password-reset-error');
    const submitButton = document.getElementById('password-reset-btn');

    function showErr(msg) {
      if (!errorDiv) return;
      errorDiv.textContent = msg;
      errorDiv.style.display = 'block';
    }

    if (errorDiv) { errorDiv.style.display = 'none'; errorDiv.textContent = ''; }
    if (!currentPassword || !newPassword || !newPasswordConfirm) return showErr('All fields are required');
    if (newPassword !== newPasswordConfirm) return showErr('New passwords do not match');
    if (currentPassword === newPassword) return showErr('New password must be different from current password');

    if (submitButton) { submitButton.disabled = true; submitButton.textContent = 'Updating...'; }
    try {
      const resp = await fetch('/auth/change-password', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
          new_password_confirm: newPasswordConfirm
        })
      });

      if (resp.ok) {
        form.reset();
        if (warnings) warnings.style.display = 'none';
        return;
      }

      let data = {};
      try { data = await resp.json(); } catch (_) { data = {}; }
      showErr(data.error || 'Failed to update password. Please try again.');
    } catch (_) {
      showErr('Network error. Please try again.');
    } finally {
      if (submitButton) { submitButton.disabled = false; submitButton.textContent = 'Update Password'; }
    }
  });
}

function initWorkflowEngineSettingsSpa() {
  if (!_isWorkflowEngineSettingsRoute()) return;

  const root = document.getElementById('page-content') || document.body;
  if (root && root.dataset && root.dataset.weSettingsSpaInit === '1') {
    // Already initialized for this DOM tree; still refresh status/fields.
    _init2FAStatus().then(_initSessionTimeoutAndBanner);
    _initSettingsAccountFields();
    _bindPasswordPolicyOnce();
    _bindPasswordResetOnce();
    return;
  }
  if (root && root.dataset) root.dataset.weSettingsSpaInit = '1';

  _init2FAStatus().then(_initSessionTimeoutAndBanner);
  _initSettingsAccountFields();
  _bindPasswordPolicyOnce();
  _bindPasswordResetOnce();
}

// Full load
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initWorkflowEngineSettingsSpa);
} else {
  initWorkflowEngineSettingsSpa();
}

// SPA navigation
document.body.addEventListener('htmx:afterSwap', function (evt) {
  const target = evt && evt.detail && evt.detail.target;
  if (!target) return;
  if (target.id === 'page-content' || (target.closest && target.closest('#page-content'))) {
    initWorkflowEngineSettingsSpa();
  }
});

