/**
 * System findings banner: shared by flows2 and core2.
 * Requires: CoreAPI.getSystemFindings() (single API that runs all system checks).
 * Renders each flagged check as a line item; expand/collapse; dismiss / ignore for today.
 */
(function () {
  'use strict';

  function todayDateKey() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function hideSystemFindingsBanner() {
    var banner = document.getElementById('system-findings-banner');
    if (banner) banner.style.display = 'none';
  }

  /**
   * Fetch system findings (one API call) and render banner. Call on DOMContentLoaded and optionally after navigation.
   */
  async function loadSystemFindingsBanner() {
    var banner = document.getElementById('system-findings-banner');
    var listEl = document.getElementById('system-findings-list');
    if (!banner || !listEl) return;
    if (sessionStorage.getItem('corechecks_ignore_date') === todayDateKey()) {
      return;
    }
    if (sessionStorage.getItem('corechecks_banner_dismissed') === '1') {
      return;
    }
    /* To show the banner again after Dismiss/Ignore for today: clear sessionStorage keys corechecks_banner_dismissed and corechecks_ignore_date for this origin. */

    var findings = [];
    try {
      var api = window.CoreAPI;
      if (!api || typeof api.getSystemFindings !== 'function') {
        console.warn('System findings banner: CoreAPI.getSystemFindings not available.');
        return;
      }
      var data = await api.getSystemFindings();
      findings = (data && Array.isArray(data.findings)) ? data.findings : [];
    } catch (e) {
      console.warn('System findings banner: failed to load findings', e);
      return;
    }

    if (findings.length === 0) {
      hideSystemFindingsBanner();
      return;
    }

    var sourcemapUrl = '/core/sourcemap?show=check-needed';
    var hasWastageModal = !!document.getElementById('record-wastage-modal');
    listEl.innerHTML = findings.map(function (f, index) {
      var text = (f && f.text != null) ? String(f.text) : '';
      var checkId = (f && f.check_id != null) ? String(f.check_id) : '';
      var detailsId = 'system-finding-details-' + index;
      var triggerHtml = formatTriggerDetails(checkId, f.data);
      var hasDetails = triggerHtml.length > 0;
      var summaryClass = 'system-findings-item__summary' + (hasDetails ? '' : ' system-findings-item__summary--no-details');
      var ariaExpanded = hasDetails ? ' aria-expanded="false" aria-controls="' + detailsId + '"' : '';
      var chevron = hasDetails
        ? '<svg class="system-findings-item__chevron" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>'
        : '';
      var detailsBlock = hasDetails
        ? '<div id="' + detailsId + '" class="system-findings-item__details" hidden><p class="system-findings-item__details-title">What triggered this</p><div class="system-findings-item__details-body">' + triggerHtml + '</div></div>'
        : '';
      var actionBlock = '';
      if (checkId === 'expired_materials') {
        var expiredIds = [];
        if (f.data && Array.isArray(f.data.expired_raw_materials)) {
          f.data.expired_raw_materials.forEach(function (x) {
            if (x && x.id) expiredIds.push(String(x.id));
          });
        }
        var expiredIdsAttr = expiredIds.length ? " data-expired-ids='" + String(JSON.stringify(expiredIds)).replace(/'/g, "&#39;") + "'" : '';
        var menuItems = '<a href="' + sourcemapUrl + '" class="system-findings-item__menu-item" data-action="review-sourcemap">Review in Sourcemap</a>';
        if (hasWastageModal && expiredIds.length > 0) {
          menuItems += '<button type="button" class="system-findings-item__menu-item" data-action="dispose">Dispose of material</button>';
        }
        actionBlock =
          '<div class="system-findings-item__action-dropdown"' + expiredIdsAttr + '>' +
            '<button type="button" class="system-findings-item__action-trigger btn btn-secondary btn-sm" aria-haspopup="true" aria-expanded="false">' +
              'Select action' +
              '<svg class="system-findings-item__action-chevron" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>' +
            '</button>' +
            '<div class="system-findings-item__action-menu" role="menu" hidden>' +
              menuItems +
            '</div>' +
          '</div>';
      }
      return (
        '<li class="system-findings-item" data-index="' + index + '">' +
          '<div class="system-findings-item__row">' +
            '<button type="button" class="' + summaryClass + '"' + ariaExpanded + '>' +
              chevron +
              '<span class="system-findings-item__text">' + escapeHtml(text) + '</span>' +
            '</button>' +
            (actionBlock ? actionBlock : '') +
          '</div>' +
          detailsBlock +
        '</li>'
      );
    }).join('');
    banner.style.display = 'block';
  }

  function onFindingActionClick(ev) {
    var menuItem = ev.target && ev.target.closest && ev.target.closest('.system-findings-item__menu-item');
    if (menuItem) {
      var action = menuItem.getAttribute('data-action');
      closeAllFindingDropdowns();
      if (action === 'dispose') {
        ev.preventDefault();
        ev.stopPropagation();
        var findingItem = menuItem.closest('.system-findings-item');
        if (findingItem) {
          var dropdownEl = findingItem.querySelector('.system-findings-item__action-dropdown');
          var idsJson = dropdownEl ? dropdownEl.getAttribute('data-expired-ids') : null;
          if (idsJson) {
            try {
              var ids = JSON.parse(idsJson);
              if (typeof window.openRecordWastageModalForExpired === 'function') {
                window.openRecordWastageModalForExpired(ids);
              }
            } catch (e) { /* ignore */ }
          }
        }
      }
      return;
    }
    var trigger = ev.target && ev.target.closest && ev.target.closest('.system-findings-item__action-trigger');
    if (trigger && trigger.parentNode && trigger.parentNode.classList.contains('system-findings-item__action-dropdown')) {
      ev.preventDefault();
      ev.stopPropagation();
      var menu = trigger.parentNode.querySelector('.system-findings-item__action-menu');
      var isOpen = menu && !menu.hidden;
      closeAllFindingDropdowns();
      if (menu && !isOpen) {
        menu.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
      }
    }
  }

  function closeAllFindingDropdowns() {
    var list = document.getElementById('system-findings-list');
    if (!list) return;
    list.querySelectorAll('.system-findings-item__action-menu').forEach(function (menu) {
      menu.hidden = true;
    });
    list.querySelectorAll('.system-findings-item__action-trigger').forEach(function (btn) {
      btn.setAttribute('aria-expanded', 'false');
    });
  }

  function formatTriggerDetails(checkId, data) {
    if (!data || typeof data !== 'object') return '';
    var parts = [];
    if (checkId === 'expired_materials') {
      var expired = data.expired_raw_materials;
      if (Array.isArray(expired) && expired.length > 0) {
        parts.push('<p class="system-findings-item__detail-section"><strong>Expired raw material(s):</strong> ' +
          expired.map(function (x) { return escapeHtml(x && x.name ? x.name : x.id || '—'); }).join(', ') + '</p>');
      }
      var impacted = data.impacted_items;
      if (Array.isArray(impacted) && impacted.length > 0) {
        parts.push('<p class="system-findings-item__detail-section"><strong>Impacted item(s):</strong> ' +
          impacted.map(function (x) { return escapeHtml(x && x.name ? x.name : x.id || '—'); }).join(', ') + '</p>');
      }
    } else if (checkId === 'untracked_items') {
      var untracked = data.untracked_items;
      if (Array.isArray(untracked) && untracked.length > 0) {
        parts.push('<p class="system-findings-item__detail-section"><strong>Untracked item(s):</strong> ' +
          untracked.map(function (x) { return escapeHtml(x && x.name ? x.name : x.id || '—'); }).join(', ') + '</p>');
      }
    } else if (data && Object.keys(data).length > 0) {
      parts.push('<pre class="system-findings-item__detail-raw">' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>');
    }
    return parts.join('');
  }

  function onFindingSummaryClick(ev) {
    var btn = ev.target && ev.target.closest && ev.target.closest('.system-findings-item__summary');
    if (!btn || btn.getAttribute('aria-controls') == null) return;
    var detailsId = btn.getAttribute('aria-controls');
    var details = document.getElementById(detailsId);
    if (!details) return;
    var expanded = btn.getAttribute('aria-expanded') !== 'true';
    btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    details.hidden = !expanded;
  }

  function escapeHtml(text) {
    if (text == null) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function bindBanner() {
    var banner = document.getElementById('system-findings-banner');
    var listEl = document.getElementById('system-findings-list');
    var toggleBtn = document.getElementById('system-findings-banner-toggle');
    var body = document.getElementById('system-findings-banner-body');
    var dismissBtn = document.getElementById('system-findings-banner-dismiss');
    var ignoreBtn = document.getElementById('system-findings-banner-ignore-today');

    if (listEl) {
      listEl.addEventListener('click', onFindingSummaryClick);
      listEl.addEventListener('click', onFindingActionClick);
    }
    document.addEventListener('click', function (ev) {
      if (ev.target && !ev.target.closest('.system-findings-item__action-dropdown')) {
        closeAllFindingDropdowns();
      }
    });
    if (toggleBtn && body) {
      toggleBtn.addEventListener('click', function () {
        var expanded = toggleBtn.getAttribute('aria-expanded') !== 'true';
        toggleBtn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        body.hidden = !expanded;
      });
    }
    if (dismissBtn) {
      dismissBtn.addEventListener('click', function () {
        sessionStorage.setItem('corechecks_banner_dismissed', '1');
        hideSystemFindingsBanner();
      });
    }
    if (ignoreBtn) {
      ignoreBtn.addEventListener('click', function () {
        sessionStorage.setItem('corechecks_ignore_date', todayDateKey());
        hideSystemFindingsBanner();
      });
    }
  }

  window.loadSystemFindingsBanner = loadSystemFindingsBanner;
  window.hideSystemFindingsBanner = hideSystemFindingsBanner;

  function init() {
    var banner = document.getElementById('system-findings-banner');
    if (!banner) {
      console.warn('System findings banner element not found (ensure shared/system-findings-banner.html is included).');
      return;
    }
    bindBanner();
    loadSystemFindingsBanner();
  }

  function runWhenReady() {
    if (document.getElementById('system-findings-banner')) {
      init();
      return;
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        init();
        if (!document.getElementById('system-findings-banner')) {
          setTimeout(init, 50);
        }
      });
    } else {
      setTimeout(init, 0);
    }
  }
  runWhenReady();
})();
