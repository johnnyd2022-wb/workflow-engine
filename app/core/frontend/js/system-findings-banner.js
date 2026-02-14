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

    listEl.innerHTML = findings.map(function (f) {
      var text = (f && f.text != null) ? String(f.text) : '';
      return '<li>' + escapeHtml(text) + '</li>';
    }).join('');
    banner.style.display = 'block';
  }

  function escapeHtml(text) {
    if (text == null) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function bindBanner() {
    var banner = document.getElementById('system-findings-banner');
    var toggleBtn = document.getElementById('system-findings-banner-toggle');
    var body = document.getElementById('system-findings-banner-body');
    var dismissBtn = document.getElementById('system-findings-banner-dismiss');
    var ignoreBtn = document.getElementById('system-findings-banner-ignore-today');

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
