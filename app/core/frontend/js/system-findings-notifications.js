(function () {
  'use strict';

  function todayDateKey() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function ignoreKey(checkId) {
    return 'corechecks_finding_ignore_date_' + String(checkId);
  }

  function dismissedKey(checkId) {
    return 'corechecks_finding_dismissed_' + String(checkId);
  }

  function isIgnoredToday(checkId, todayKey) {
    return sessionStorage.getItem(ignoreKey(checkId)) === todayKey;
  }

  function isDismissed(checkId) {
    return sessionStorage.getItem(dismissedKey(checkId)) === '1';
  }

  function expandAllDetails() {
    var details = document.querySelectorAll('#system-findings-list .system-findings-item__details[hidden]');
    details.forEach(function (el) {
      el.removeAttribute('hidden');
      el.hidden = false;
    });
  }

  function removeExistingCardActions() {
    var actions = document.querySelectorAll('#system-findings-list .system-findings-item__card-actions');
    actions.forEach(function (el) {
      el.remove();
    });
  }

  function ensureEmptyState(visibleCount) {
    var body = document.getElementById('system-findings-banner-body');
    if (!body) return;

    var emptyEl = document.getElementById('system-findings-notifications-empty');

    if (visibleCount === 0) {
      if (!emptyEl) {
        emptyEl = document.createElement('div');
        emptyEl.id = 'system-findings-notifications-empty';
        emptyEl.textContent = 'No system notifications right now.';
        emptyEl.style.padding = '24px 0';
        emptyEl.style.textAlign = 'center';
        emptyEl.style.color = 'var(--text-secondary, #6b7280)';
        emptyEl.style.fontSize = '0.9375rem';
        body.appendChild(emptyEl);
      }
    } else if (emptyEl) {
      emptyEl.remove();
    }
  }

  async function renderCards() {
    var listEl = document.getElementById('system-findings-list');
    var bannerBody = document.getElementById('system-findings-banner-body');
    var banner = document.getElementById('system-findings-banner');

    if (!listEl || !bannerBody || !banner) return;

    // Always show the list portion (we hide the global header via CSS).
    bannerBody.hidden = false;
    bannerBody.removeAttribute('hidden');
    banner.style.display = 'block';

    removeExistingCardActions();

    var todayKey = todayDateKey();

    // Filter items according to per-check dismiss/ignore-for-today session keys.
    var items = Array.from(listEl.querySelectorAll('.system-findings-item'));
    items.forEach(function (item) {
      var checkId = item.getAttribute('data-check-id') || '';
      if (!checkId) return;

      if (isDismissed(checkId) || isIgnoredToday(checkId, todayKey)) {
        item.remove();
      }
    });

    expandAllDetails();

    // Inject per-card ignore/dismiss actions.
    items = Array.from(listEl.querySelectorAll('.system-findings-item'));
    items.forEach(function (item) {
      var checkId = item.getAttribute('data-check-id') || '';
      if (!checkId) return;

      var alreadyInjected = item.querySelector('.system-findings-item__card-actions');
      if (alreadyInjected) return;

      var actions = document.createElement('div');
      actions.className = 'system-findings-item__card-actions';

      var ignoreBtn = document.createElement('button');
      ignoreBtn.type = 'button';
      ignoreBtn.className = 'system-findings-item__card-action system-findings-item__card-action--ignore';
      ignoreBtn.textContent = 'Ignore for today';
      ignoreBtn.setAttribute('aria-label', 'Ignore this finding for today');
      ignoreBtn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        sessionStorage.setItem(ignoreKey(checkId), todayKey);
        renderCards();
      });

      var dismissBtn = document.createElement('button');
      dismissBtn.type = 'button';
      dismissBtn.className = 'system-findings-item__card-action';
      dismissBtn.textContent = 'Dismiss';
      dismissBtn.setAttribute('aria-label', 'Dismiss this finding');
      dismissBtn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        sessionStorage.setItem(dismissedKey(checkId), '1');
        renderCards();
      });

      actions.appendChild(ignoreBtn);
      actions.appendChild(dismissBtn);

      // Place actions after the details block so they read as part of the same card.
      item.appendChild(actions);
    });

    var visibleCount = listEl.querySelectorAll('.system-findings-item').length;
    ensureEmptyState(visibleCount);
    if (window.SystemFindingsNotifications && typeof window.SystemFindingsNotifications.updateBadge === 'function') {
      window.SystemFindingsNotifications.updateBadge(visibleCount);
    }
  }

  async function waitForInitialList() {
    var listEl = document.getElementById('system-findings-list');
    if (!listEl) return;

    var attempts = 0;
    while (attempts < 80) {
      if (listEl.querySelector('.system-findings-item')) return;
      attempts += 1;
      await new Promise(function (r) { return setTimeout(r, 50); });
    }
  }

  // Bind once.
  function init() {
    waitForInitialList().then(function () {
      renderCards();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

