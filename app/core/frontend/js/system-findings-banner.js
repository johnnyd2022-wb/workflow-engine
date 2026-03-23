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

    // Frontend-only per-check filtering for notifications UI.
    // These sessionStorage keys are set by notifications.html card actions.
    var filteredFindings = [];
    var todayKey = todayDateKey();
    findings.forEach(function (f, idx) {
      var checkId = f && f.check_id != null ? String(f.check_id) : '';
      if (!checkId) {
        // If we cannot identify the check, keep it (best-effort visibility).
        filteredFindings.push(f);
        return;
      }
      if (sessionStorage.getItem('corechecks_finding_ignore_date_' + checkId) === todayKey) return;
      if (sessionStorage.getItem('corechecks_finding_dismissed_' + checkId) === '1') return;
      filteredFindings.push(f);
    });
    findings = filteredFindings;

    if (findings.length === 0) {
      hideSystemFindingsBanner();
      return;
    }

    var sourcemapUrl = '/core/sourcemap?show=check-needed';
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
        if (expiredIds.length > 0) {
          menuItems += '<button type="button" class="system-findings-item__menu-item" data-action="dispose">Dispose of inventory item</button>';
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
        '<li class="system-findings-item" data-index="' + index + '" data-check-id="' + escapeHtml(checkId) + '">' +
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
    } else if (checkId === 'output_expiry') {
      var items = data.output_expiry_items;
      if (Array.isArray(items) && items.length > 0) {
        var seenIds = new Set();
        items = items.filter(function (x) {
          var id = x && (x.inventory_item_id || x.id);
          if (!id || seenIds.has(id)) return false;
          seenIds.add(id);
          return true;
        });
        parts.push('<p class="system-findings-item__detail-section"><strong>Custom output expiry (expired or near expiry):</strong></p>');
        items.forEach(function (x) {
          var name = escapeHtml(x && x.item_name ? x.item_name : x.inventory_item_id || '—');
          var processStep = [x.process_name, x.step_name].filter(Boolean).join(' · ');
          var severity = (x.severity === 'red') ? 'Expired' : 'Near expiry';
          var expiryDate = x.expiry_at || x.expiry_date;
          expiryDate = expiryDate ? escapeHtml(String(expiryDate)) : '';
          parts.push('<div class="system-findings-output-expiry-item" style="margin-bottom: 8px; padding: 8px 12px; border: 1px solid var(--border-default); border-radius: 6px; font-size: 13px;">' +
            '<p style="margin: 0 0 4px 0; font-weight: 600;">' + name + '</p>' +
            (processStep ? '<p style="margin: 0 0 4px 0; color: var(--text-secondary); font-size: 12px;">' + escapeHtml(processStep) + '</p>' : '') +
            '<p style="margin: 0; font-size: 12px;"><span style="color: var(--error, #ef4444);">' + escapeHtml(severity) + '</span>' + (expiryDate ? ' — Expiry: ' + expiryDate : '') + '</p>' +
            '</div>');
        });
      }
    } else if (checkId === 'output_ready_date') {
      var items = data.output_ready_date_items;
      if (Array.isArray(items) && items.length > 0) {
        var seenIds = new Set();
        items = items.filter(function (x) {
          var id = x && (x.inventory_item_id || x.id);
          if (!id || seenIds.has(id)) return false;
          seenIds.add(id);
          return true;
        });
        parts.push('<p class="system-findings-item__detail-section"><strong>Output ready date:</strong></p>');
        items.forEach(function (x) {
          var name = (x && x.item_name) ? x.item_name : (x.inventory_item_id || '—');
          var processStep = [x.process_name, x.step_name].filter(Boolean).join(' · ');
          var innerHtml = typeof window.renderReadyDateStatus === 'function'
            ? window.renderReadyDateStatus(
                { state: x.state, readyDate: x.ready_date, outputName: name, severity: x.severity, detail: x.message, processStep: processStep },
                escapeHtml
              )
            : (function () {
                var readyFrom = x.ready_date
                  ? (window.parseISODate && window.parseISODate(x.ready_date) != null
                    ? escapeHtml(new Date(window.parseISODate(x.ready_date)).toLocaleDateString(undefined, { dateStyle: 'medium' }))
                    : escapeHtml(String(x.ready_date)))
                  : '—';
                var stateLabel = (x.state && x.state.trim()) ? x.state.trim() : ((x.severity === 'amber') ? 'Nearing ready' : 'Not ready');
                var severityColor = (x.severity === 'amber') ? 'var(--warning, #f59e0b)' : 'var(--error, #ef4444)';
                var detail = (x.message && x.message.trim()) ? escapeHtml(x.message.trim()) : 'Output not yet ready.';
                return '<p style="margin: 0 0 4px 0; font-weight: 600;">' + escapeHtml(name) + '</p>' +
                  '<p style="margin: 4px 0 0 0; font-size: 12px;">&#x26A0;&#xFE0F; Ready from: ' + readyFrom + '</p>' +
                  '<p style="margin: 2px 0 0 0; font-size: 12px;"><span style="color: ' + severityColor + ';">Status: ' + escapeHtml(stateLabel) + '</span></p>' +
                  '<p style="margin: 2px 0 0 0; font-size: 12px; color: var(--text-secondary);">Detail: ' + detail + '</p>';
              })();
          parts.push('<div class="system-findings-output-ready-date-item" style="margin-bottom: 8px; padding: 8px 12px; border: 1px solid var(--border-default); border-radius: 6px; font-size: 13px;">' +
            innerHtml +
            '</div>');
        });
      }
    } else if (checkId === 'untracked_items') {
      var untracked = data.untracked_items;
      if (Array.isArray(untracked) && untracked.length > 0) {
        parts.push('<p class="system-findings-item__detail-section"><strong>Untracked item(s):</strong></p>');
        untracked.forEach(function (u, itemIndex) {
          var name = escapeHtml(u && u.name ? u.name : u.id || '—');
          var detailsId = 'system-finding-untracked-details-' + itemIndex;
          var subtitleParts = [];
          if (u.process_name || u.step_name) {
            subtitleParts.push([u.process_name, u.step_name].filter(Boolean).map(function (x) { return escapeHtml(x); }).join(' · '));
          }
          var unreconciled = u.remaining_balance_to_reconcile != null ? String(u.remaining_balance_to_reconcile) : null;
          if (unreconciled !== null) {
            subtitleParts.push(escapeHtml(unreconciled) + ' ' + escapeHtml(u.unit || '') + ' unreconciled');
          }
          var subtitle = subtitleParts.length ? ('<p style="margin: 2px 0 0 0; font-size: 12px; color: var(--text-secondary);">' + subtitleParts.join(' · ') + '</p>') : '';
          var detailParts = [];
          if (unreconciled !== null) {
            detailParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Unreconciled quantity</span> ' + escapeHtml(unreconciled) + ' ' + escapeHtml(u.unit || '') + '</p>');
          }
          if (u.process_name) detailParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Process</span> ' + escapeHtml(u.process_name) + '</p>');
          if (u.producing_step_name) detailParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Step to execute to reconcile</span> ' + escapeHtml(u.producing_step_name) + '</p>');
          else if (u.step_name) detailParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Step</span> ' + escapeHtml(u.step_name) + '</p>');
          if (u.created_at) detailParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Created</span> ' + escapeHtml(u.created_at) + '</p>');
          if (u.notes) detailParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Notes</span> ' + escapeHtml(u.notes) + '</p>');
          if (u.source_step_completed_by) detailParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Completed by</span> ' + escapeHtml(u.source_step_completed_by) + '</p>');
          var promptsHtml = '';
          if (u.source_step_execution_prompts && typeof u.source_step_execution_prompts === 'object' && Object.keys(u.source_step_execution_prompts).length > 0) {
            promptsHtml = '<div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border-default);"><div style="font-size: 11px; font-weight: 600; color: var(--text-secondary); margin-bottom: 6px;">Step metadata</div><div style="display: flex; flex-direction: column; gap: 4px;">' +
              Object.entries(u.source_step_execution_prompts).map(function (e) {
                return '<div style="padding: 4px 8px; background: var(--bg-secondary, #f9fafb); border-radius: 4px;"><span style="color: var(--text-secondary); font-size: 11px;">' + escapeHtml(e[0]) + '</span><br><span style="font-size: 12px;">' + escapeHtml(String(e[1])) + '</span></div>';
              }).join('') + '</div></div>';
          }
          var processId = (u.process_id != null && String(u.process_id).trim() !== '') ? String(u.process_id) : '';
          var processName = (u.process_name != null) ? String(u.process_name) : '';
          var stepName = (u.producing_step_name != null && u.producing_step_name !== '') ? u.producing_step_name : (u.step_name || '');
          var reconcileAttrs = ' data-reconcile-process-id="' + escapeHtml(processId) + '" data-reconcile-process-name="' + escapeHtml(processName) + '" data-reconcile-step-name="' + escapeHtml(stepName) + '"';
          var reconcileLabel = processId ? 'Click here to reconcile untracked item' : 'Open Source Map to reconcile';
          var reconcileHref = processId ? '#' : '/core/sourcemap?show=check-needed';
          var reconcileLink = '<a href="' + reconcileHref + '" class="system-findings-untracked-item__reconcile-link"' + reconcileAttrs + ' style="flex-shrink: 0; font-size: 12px; color: var(--link-color, #2563eb); text-decoration: none;">' + escapeHtml(reconcileLabel) + '</a>';
          parts.push(
            '<div class="system-findings-untracked-item" style="margin-bottom: 8px; border: 1px solid var(--border-default); border-radius: 6px; overflow: hidden;">' +
              '<div style="display: flex; align-items: center; padding: 10px 12px; background: var(--bg-secondary, #f9fafb); gap: 8px;">' +
                '<button type="button" class="system-findings-untracked-item__summary" aria-expanded="false" aria-controls="' + escapeHtml(detailsId) + '" style="flex: 1; text-align: left; padding: 0; border: none; background: transparent; cursor: pointer; display: flex; align-items: center; gap: 8px; font: inherit; min-width: 0;">' +
                  '<svg class="system-findings-untracked-item__chevron" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink: 0; transition: transform 0.2s;"><polyline points="6 9 12 15 18 9"/></svg>' +
                  '<div style="flex: 1; min-width: 0;">' +
                    '<p style="margin: 0; font-weight: 600;">' + name + '</p>' +
                    subtitle +
                  '</div>' +
                '</button>' +
                reconcileLink +
              '</div>' +
              '<div id="' + escapeHtml(detailsId) + '" class="system-findings-untracked-item__details" hidden style="padding: 10px 12px; border-top: 1px solid var(--border-default); background: #fff; font-size: 13px;">' +
                detailParts.join('') + promptsHtml +
              '</div>' +
            '</div>'
          );
        });
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

  function onUntrackedItemSummaryClick(ev) {
    var btn = ev.target && ev.target.closest && ev.target.closest('.system-findings-untracked-item__summary');
    if (!btn || btn.getAttribute('aria-controls') == null) return;
    var detailsId = btn.getAttribute('aria-controls');
    var details = document.getElementById(detailsId);
    if (!details) return;
    var expanded = btn.getAttribute('aria-expanded') !== 'true';
    btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    details.hidden = !expanded;
    var chevron = btn.querySelector('.system-findings-untracked-item__chevron');
    if (chevron) chevron.style.transform = expanded ? 'rotate(180deg)' : 'rotate(0deg)';
  }

  function openReconcileModal(processId, processName, stepName) {
    var modal = document.getElementById('system-findings-reconcile-modal');
    var bodyEl = document.getElementById('system-findings-reconcile-modal-body');
    if (!modal || !bodyEl) return;
    var stepDisplay = stepName ? escapeHtml(stepName) : 'the step that produced this output';
    var processDisplay = processName ? escapeHtml(processName) : 'the process';
    bodyEl.innerHTML = 'This untracked item was produced as an output. To reconcile it, go to the process <strong>' + processDisplay + '</strong> and execute the step <strong>' + stepDisplay + '</strong>. You can then link the output to existing inventory or record it there.';
    modal.setAttribute('data-reconcile-process-id', processId || '');
    modal.style.display = 'flex';
  }

  function closeReconcileModal() {
    var modal = document.getElementById('system-findings-reconcile-modal');
    if (modal) modal.style.display = 'none';
  }

  function onReconcileLinkClick(ev) {
    var link = ev.target && ev.target.closest && ev.target.closest('.system-findings-untracked-item__reconcile-link');
    if (!link) return;
    var processId = link.getAttribute('data-reconcile-process-id');
    var processName = link.getAttribute('data-reconcile-process-name') || '';
    var stepName = link.getAttribute('data-reconcile-step-name') || '';
    if (processId) {
      ev.preventDefault();
      ev.stopPropagation();
      openReconcileModal(processId, processName, stepName);
    }
    /* when no processId, link href is Source Map URL – allow default navigation */
  }

  function onReconcileModalGo(ev) {
    var modal = document.getElementById('system-findings-reconcile-modal');
    if (!modal) return;
    var processId = modal.getAttribute('data-reconcile-process-id');
    closeReconcileModal();
    if (processId) {
      window.location.href = '/core/flows?id=' + encodeURIComponent(processId);
    }
  }

  function onReconcileModalCancel(ev) {
    closeReconcileModal();
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
      listEl.addEventListener('click', onUntrackedItemSummaryClick);
      listEl.addEventListener('click', onReconcileLinkClick);
      listEl.addEventListener('click', onFindingActionClick);
    }
    var reconcileModal = document.getElementById('system-findings-reconcile-modal');
    if (reconcileModal) {
      reconcileModal.addEventListener('click', function (ev) {
        if (ev.target === reconcileModal) closeReconcileModal();
      });
    }
    var reconcileModalCancel = document.getElementById('system-findings-reconcile-modal-cancel');
    if (reconcileModalCancel) reconcileModalCancel.addEventListener('click', onReconcileModalCancel);
    var reconcileModalGo = document.getElementById('system-findings-reconcile-modal-go');
    if (reconcileModalGo) reconcileModalGo.addEventListener('click', onReconcileModalGo);
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
