/**
 * Notifications page: flat list of system findings — one card per underlying item,
 * sorted newest-first. Uses CoreAPI.getSystemFindings() only (no banner HTML).
 */
(function () {
  'use strict';

  var CATEGORY_LABELS = {
    expired_materials: 'Expired raw materials',
    output_expiry: 'Custom output expiry',
    output_ready_date: 'Output ready date',
    untracked_items: 'Untracked items'
  };

  function todayDateKey() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function ignoreKey(checkId, itemKey) {
    return 'corechecks_finding_ignore_date_' + String(checkId) + '_' + String(itemKey);
  }

  function dismissedKey(checkId, itemKey) {
    return 'corechecks_finding_dismissed_' + String(checkId) + '_' + String(itemKey);
  }

  function isIgnoredToday(checkId, itemKey, todayKey) {
    return sessionStorage.getItem(ignoreKey(checkId, itemKey)) === todayKey;
  }

  function isDismissed(checkId, itemKey) {
    return sessionStorage.getItem(dismissedKey(checkId, itemKey)) === '1';
  }

  function parseDateMs(dateStr) {
    if (!dateStr) return null;
    try {
      var d = new Date(dateStr);
      var t = d.getTime();
      if (Number.isNaN(t)) return null;
      return t;
    } catch (e) {
      return null;
    }
  }

  function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
      var d = new Date(dateStr);
      if (Number.isNaN(d.getTime())) return '—';
      return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: '2-digit' }).toUpperCase();
    } catch (e) {
      return '—';
    }
  }

  function pickTriggeredDate(item, finding, data) {
    var itemMeta = item && item.metadata && typeof item.metadata === 'object' ? item.metadata : {};
    var dataMeta = data && data.metadata && typeof data.metadata === 'object' ? data.metadata : {};
    var candidates = [
      item && item.notification_triggered_at,
      item && item.triggered_at,
      item && item.detected_at,
      item && item.evaluated_at,
      itemMeta.evaluated_at,
      finding && finding.triggered_at,
      finding && finding.detected_at,
      finding && finding.created_at,
      finding && finding.updated_at,
      data && data.triggered_at,
      data && data.detected_at,
      data && data.evaluated_at,
      data && data.generated_at,
      dataMeta.evaluated_at
    ];
    for (var i = 0; i < candidates.length; i += 1) {
      if (parseDateMs(candidates[i])) return String(candidates[i]);
    }
    return '';
  }

  function categoryLabel(checkId) {
    return CATEGORY_LABELS[checkId] || String(checkId || '').replace(/_/g, ' ') || 'System finding';
  }

  function safeUnique(arr) {
    var out = [];
    var seen = new Set();
    (arr || []).forEach(function (x) {
      var s = x == null ? '' : String(x);
      if (!s) return;
      if (seen.has(s)) return;
      seen.add(s);
      out.push(s);
    });
    return out;
  }

  function itemKeyOutputExpiry(x) {
    var iid = x && x.inventory_item_id != null ? String(x.inventory_item_id) : '';
    var exp = x && (x.expiry_at || x.expiry_date) ? String(x.expiry_at || x.expiry_date) : '';
    var sid = x && x.step_id != null ? String(x.step_id) : '';
    return 'oe_' + iid + '_' + sid + '_' + exp;
  }

  function itemKeyOutputReady(x) {
    var iid = x && x.inventory_item_id != null ? String(x.inventory_item_id) : '';
    var rd = x && x.ready_date ? String(x.ready_date) : '';
    var sid = x && x.step_id != null ? String(x.step_id) : '';
    return 'ord_' + iid + '_' + sid + '_' + rd;
  }

  function itemKeyUntracked(u) {
    return u && u.id != null ? 'ut_' + String(u.id) : '';
  }

  async function fetchFindings() {
    var api = window.CoreAPI;
    if (!api || typeof api.getSystemFindings !== 'function') return [];
    try {
      var data = await api.getSystemFindings();
      return (data && Array.isArray(data.findings)) ? data.findings : [];
    } catch (e) {
      return [];
    }
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
        emptyEl.className = 'notification-page__empty';
        body.appendChild(emptyEl);
      }
    } else if (emptyEl) {
      emptyEl.remove();
    }
  }

  function closeAllOverflowMenus() {
    var menus = document.querySelectorAll('.notifications-list-item__overflow-menu');
    menus.forEach(function (menu) {
      menu.hidden = true;
    });
    var toggles = document.querySelectorAll('.notifications-list-item__overflow-toggle');
    toggles.forEach(function (toggle) {
      toggle.setAttribute('aria-expanded', 'false');
    });

    var actionMenus = document.querySelectorAll('.notifications-list-item__actions-menu');
    actionMenus.forEach(function (menu) {
      menu.hidden = true;
    });
    var actionToggles = document.querySelectorAll('.notifications-list-item__actions-toggle');
    actionToggles.forEach(function (toggle) {
      toggle.setAttribute('aria-expanded', 'false');
    });
  }

  function bindOverflowMenuHandlers() {
    if (window.__coreNotificationsOverflowHandlersBound) return;
    window.__coreNotificationsOverflowHandlersBound = true;

    document.addEventListener('click', function (ev) {
      if (!ev.target || !ev.target.closest('.notifications-list-item__overflow')) {
        closeAllOverflowMenus();
      }
    });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') closeAllOverflowMenus();
    });
  }

  function createOverflowMenuItem(label, onClick) {
    var item = document.createElement('button');
    item.type = 'button';
    item.className = 'notifications-list-item__overflow-item';
    item.textContent = label;
    item.addEventListener('click', onClick);
    return item;
  }

  function createActionsRow(inner, record) {
    if (!record.actions || !record.actions.length) return;

    var field = document.createElement('div');
    field.className = 'notifications-list-item__field notifications-list-item__field--actions-menu';

    var lab = document.createElement('div');
    lab.className = 'notifications-list-item__label';
    lab.textContent = 'Actions:';

    var menuWrap = document.createElement('div');
    menuWrap.className = 'notifications-list-item__actions-dropdown';

    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'notifications-list-item__actions-toggle';
    toggle.setAttribute('aria-haspopup', 'menu');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.textContent = 'Actions';

    var menu = document.createElement('div');
    menu.className = 'notifications-list-item__actions-menu';
    menu.setAttribute('role', 'menu');
    menu.hidden = true;

    record.actions.forEach(function (a) {
      if (a.type === 'link') {
        var link = document.createElement('a');
        link.className = 'notifications-list-item__actions-item';
        link.href = a.href;
        if (a.boost === false) link.setAttribute('hx-boost', 'false');
        link.textContent = a.label;
        link.setAttribute('role', 'menuitem');
        menu.appendChild(link);
      } else if (a.type === 'button' && a.action === 'dispose-expired') {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'notifications-list-item__actions-item';
        btn.textContent = a.label;
        btn.setAttribute('role', 'menuitem');
        (function (rid) {
          btn.addEventListener('click', function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            if (typeof window.openRecordWastageModalForExpired === 'function') {
              window.openRecordWastageModalForExpired([rid]);
            }
            closeAllOverflowMenus();
          });
        })(a.rawId);
        menu.appendChild(btn);
      } else if (a.type === 'reconcile') {
        var rlink = document.createElement('a');
        rlink.className = 'notifications-list-item__actions-item system-findings-untracked-item__reconcile-link';
        rlink.href = a.href;
        rlink.setAttribute('hx-boost', 'false');
        rlink.textContent = a.label;
        rlink.setAttribute('role', 'menuitem');
        if (a.processId) {
          rlink.setAttribute('data-reconcile-process-id', a.processId);
          rlink.setAttribute('data-reconcile-process-name', a.processName || '');
          rlink.setAttribute('data-reconcile-step-name', a.stepName || '');
        }
        menu.appendChild(rlink);
      }
    });

    toggle.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      var willOpen = menu.hidden;
      closeAllOverflowMenus();
      menu.hidden = !willOpen;
      toggle.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    });

    menuWrap.appendChild(toggle);
    menuWrap.appendChild(menu);
    field.appendChild(lab);
    field.appendChild(menuWrap);
    inner.appendChild(field);
  }

  function appendOverflowMenu(inner, checkId, itemKey, todayKey, onChange) {
    var wrap = document.createElement('div');
    wrap.className = 'notifications-list-item__overflow';

    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'notifications-list-item__overflow-toggle';
    toggle.setAttribute('aria-label', 'Open notification options');
    toggle.setAttribute('aria-haspopup', 'menu');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.innerHTML = '<span aria-hidden="true">&#8942;</span>';

    var menu = document.createElement('div');
    menu.className = 'notifications-list-item__overflow-menu';
    menu.setAttribute('role', 'menu');
    menu.hidden = true;

    var snoozeItem = createOverflowMenuItem('Snooze for today', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      sessionStorage.setItem(ignoreKey(checkId, itemKey), todayKey);
      onChange();
    });
    snoozeItem.setAttribute('role', 'menuitem');

    var hideItem = createOverflowMenuItem('Hide', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      sessionStorage.setItem(dismissedKey(checkId, itemKey), '1');
      onChange();
    });
    hideItem.setAttribute('role', 'menuitem');

    toggle.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      var willOpen = menu.hidden;
      closeAllOverflowMenus();
      menu.hidden = !willOpen;
      toggle.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    });

    menu.appendChild(snoozeItem);
    menu.appendChild(hideItem);
    wrap.appendChild(toggle);
    wrap.appendChild(menu);
    inner.appendChild(wrap);
  }

  function appendLabeledField(inner, labelText, valueText, emphasis, fieldClassName) {
    var field = document.createElement('div');
    field.className = 'notifications-list-item__field' + (fieldClassName ? (' ' + fieldClassName) : '');
    var lab = document.createElement('div');
    lab.className = 'notifications-list-item__label';
    lab.textContent = labelText;
    var val = document.createElement('span');
    val.className = 'notifications-list-item__value' + (emphasis ? ' notifications-list-item__value--emphasis' : '');
    val.textContent = valueText;
    field.appendChild(lab);
    field.appendChild(val);
    inner.appendChild(field);
  }

  function appendLabeledPre(inner, labelText, preText) {
    var field = document.createElement('div');
    field.className = 'notifications-list-item__field notifications-list-item__field--stacked';
    var lab = document.createElement('div');
    lab.className = 'notifications-list-item__label';
    lab.textContent = labelText;
    var val = document.createElement('div');
    val.className = 'notifications-list-item__value';
    var pre = document.createElement('pre');
    pre.className = 'notifications-list-item__detail-pre';
    pre.textContent = preText;
    val.appendChild(pre);
    field.appendChild(lab);
    field.appendChild(val);
    inner.appendChild(field);
  }

  function buildNotificationRecords(findings, todayKey) {
    var records = [];

    findings.forEach(function (f) {
      var checkId = f && f.check_id != null ? String(f.check_id) : '';
      if (!checkId) return;
      var data = f.data && typeof f.data === 'object' ? f.data : {};

      if (checkId === 'expired_materials') {
        var impactedAll = Array.isArray(data.impacted_items) ? data.impacted_items : [];
        var expired = Array.isArray(data.expired_raw_materials) ? data.expired_raw_materials.slice() : [];
        expired.sort(function (a, b) {
          var aMs = parseDateMs(a && (a.created_at || a.purchase_date || a.expiry_date));
          var bMs = parseDateMs(b && (b.created_at || b.purchase_date || b.expiry_date));
          return (bMs || 0) - (aMs || 0);
        });

        expired.forEach(function (raw) {
          var rawId = raw && raw.id != null ? String(raw.id) : null;
          if (!rawId) return;
          if (isIgnoredToday(checkId, rawId, todayKey)) return;
          if (isDismissed(checkId, rawId)) return;

          var dateStr = raw.created_at || raw.purchase_date || raw.expiry_date;
          var sortMs = parseDateMs(dateStr) || 0;
          var impacted = impactedAll.filter(function (it) {
            if (!it) return false;
            var tied = it.expired_raw_material_id != null ? String(it.expired_raw_material_id) : null;
            return tied === rawId;
          });
          var impactedNames = safeUnique(
            impacted.map(function (x) { return (x && (x.name || x.id)) ? String(x.name || x.id) : ''; })
          );
          var impactedLine = impactedNames.length ? impactedNames.join(', ') : '';

          records.push({
            checkId: checkId,
            itemKey: rawId,
            sortMs: sortMs,
            triggeredDateText: formatDate(pickTriggeredDate(raw, f, data) || todayKey),
            systemFinding: categoryLabel(checkId),
            detailDateCaption: 'Expiry:',
            detailDateText: formatDate(dateStr),
            itemName: raw.name || rawId,
            extraFields: impactedLine
              ? [{ label: 'Impacted downstream items:', value: impactedLine }]
              : [],
            actions: [
              { type: 'link', href: '/core/sourcemap?show=check-needed', label: 'Review in Sourcemap', boost: false },
              { type: 'button', label: 'Dispose of inventory item', action: 'dispose-expired', rawId: rawId }
            ]
          });
        });
        return;
      }

      if (checkId === 'output_expiry') {
        var oeItems = Array.isArray(data.output_expiry_items) ? data.output_expiry_items : [];
        var seenOe = new Set();
        oeItems.forEach(function (x) {
          var ik = itemKeyOutputExpiry(x);
          if (!ik || seenOe.has(ik)) return;
          seenOe.add(ik);
          if (isIgnoredToday(checkId, ik, todayKey)) return;
          if (isDismissed(checkId, ik)) return;

          var expStr = x && (x.expiry_at || x.expiry_date) ? String(x.expiry_at || x.expiry_date) : '';
          var sortMs = parseDateMs(expStr) || 0;
          var name = (x && x.item_name) ? String(x.item_name) : (x.inventory_item_id || '—');
          var processStep = [x.process_name, x.step_name].filter(Boolean).join(' · ');
          var pid = x && x.process_id != null ? String(x.process_id).trim() : '';

          var actions = [];
          if (pid) {
            actions.push({ type: 'link', href: '/core/flows?id=' + encodeURIComponent(pid), label: 'Open process', boost: false });
          }

          var oeExtra = [];
          if (processStep) {
            oeExtra.push({ label: 'Process / step:', value: processStep });
          }
          records.push({
            checkId: checkId,
            itemKey: ik,
            sortMs: sortMs,
            triggeredDateText: formatDate(pickTriggeredDate(x, f, data) || todayKey),
            systemFinding: categoryLabel(checkId),
            detailDateCaption: 'Expiry:',
            detailDateText: formatDate(expStr),
            itemName: name,
            extraFields: oeExtra,
            actions: actions
          });
        });
        return;
      }

      if (checkId === 'output_ready_date') {
        var orItems = Array.isArray(data.output_ready_date_items) ? data.output_ready_date_items : [];
        var seenOr = new Set();
        orItems.forEach(function (x) {
          var ik = itemKeyOutputReady(x);
          if (!ik || seenOr.has(ik)) return;
          seenOr.add(ik);
          if (isIgnoredToday(checkId, ik, todayKey)) return;
          if (isDismissed(checkId, ik)) return;

          var rd = x && x.ready_date ? String(x.ready_date) : '';
          var sortMs = parseDateMs(rd) || parseDateMs(x && x.metadata && x.metadata.evaluated_at) || 0;
          var name = (x && x.item_name) ? String(x.item_name) : (x.inventory_item_id || '—');
          var processStep = [x.process_name, x.step_name].filter(Boolean).join(' · ');
          var pid = x && x.process_id != null ? String(x.process_id).trim() : '';
          var detail = (x && x.message && String(x.message).trim()) ? String(x.message).trim() : '';

          var actions = [];
          if (pid) {
            actions.push({ type: 'link', href: '/core/flows?id=' + encodeURIComponent(pid), label: 'Open process', boost: false });
          }

          var ordExtra = [];
          if (processStep) {
            ordExtra.push({ label: 'Process / step:', value: processStep });
          }
          if (detail) {
            ordExtra.push({ label: 'Details:', value: detail });
          }
          records.push({
            checkId: checkId,
            itemKey: ik,
            sortMs: sortMs,
            triggeredDateText: formatDate(pickTriggeredDate(x, f, data) || todayKey),
            systemFinding: categoryLabel(checkId),
            detailDateCaption: 'Ready from date:',
            detailDateText: formatDate(rd),
            itemName: name,
            extraFields: ordExtra,
            actions: actions
          });
        });
        return;
      }

      if (checkId === 'untracked_items') {
        var untracked = Array.isArray(data.untracked_items) ? data.untracked_items : [];
        untracked.forEach(function (u) {
          var ik = itemKeyUntracked(u);
          if (!ik) return;
          if (isIgnoredToday(checkId, ik, todayKey)) return;
          if (isDismissed(checkId, ik)) return;

          var created = u && u.created_at ? String(u.created_at) : '';
          var sortMs = parseDateMs(created) || 0;
          var name = (u && u.name) ? String(u.name) : (u.id || '—');
          var unreconciled = u.remaining_balance_to_reconcile != null ? String(u.remaining_balance_to_reconcile) : null;
          var impactedParts = [];
          if (unreconciled !== null) {
            impactedParts.push(unreconciled + ' ' + (u.unit || '') + ' unreconciled');
          }
          if (u.process_name || u.step_name) {
            impactedParts.push([u.process_name, u.step_name].filter(Boolean).join(' · '));
          }
          var impactedLine = impactedParts.filter(Boolean).join(' · ');

          var processId = (u.process_id != null && String(u.process_id).trim() !== '') ? String(u.process_id) : '';
          var processName = (u.process_name != null) ? String(u.process_name) : '';
          var stepName = (u.producing_step_name != null && u.producing_step_name !== '') ? u.producing_step_name : (u.step_name || '');

          var reconcileHref = processId ? '#' : '/core/sourcemap?show=check-needed';
          var reconcileLabel = processId ? 'Reconcile this item' : 'Open Source Map to reconcile';

          var utExtra = [];
          if (impactedLine) {
            utExtra.push({ label: 'Context:', value: impactedLine });
          }
          records.push({
            checkId: checkId,
            itemKey: ik,
            sortMs: sortMs,
            triggeredDateText: formatDate(pickTriggeredDate(u, f, data) || todayKey),
            systemFinding: categoryLabel(checkId),
            detailDateCaption: 'Created:',
            detailDateText: formatDate(created),
            itemName: name,
            extraFields: utExtra,
            actions: [
              {
                type: 'reconcile',
                href: reconcileHref,
                label: reconcileLabel,
                processId: processId,
                processName: processName,
                stepName: stepName
              }
            ]
          });
        });
        return;
      }

      /* Unknown check: single row */
      var genKey = 'gen_' + checkId;
      if (isIgnoredToday(checkId, genKey, todayKey)) return;
      if (isDismissed(checkId, genKey)) return;
      var msg = (f && f.text != null) ? String(f.text) : checkId;
      var rawJson = Object.keys(data).length ? JSON.stringify(data, null, 2) : '';
      var unkExtra = [{ label: 'Message:', value: msg, emphasis: true }];
      if (rawJson) {
        unkExtra.push({ label: 'Technical details:', value: rawJson, pre: true });
      }
      records.push({
        checkId: checkId,
        itemKey: genKey,
        sortMs: 0,
        triggeredDateText: formatDate(pickTriggeredDate(null, f, data) || todayKey),
        systemFinding: categoryLabel(checkId),
        detailDateCaption: null,
        detailDateText: null,
        itemName: null,
        extraFields: unkExtra,
        actions: []
      });
    });

    records.sort(function (a, b) { return (b.sortMs || 0) - (a.sortMs || 0); });
    return records;
  }

  function renderLi(record, todayKey, onChange) {
    var li = document.createElement('li');
    li.className = 'system-findings-item notifications-list-item';
    li.setAttribute('data-check-id', record.checkId);
    li.setAttribute('data-item-key', record.itemKey);

    var inner = document.createElement('div');
    inner.className = 'notifications-list-item__inner';
    appendOverflowMenu(inner, record.checkId, record.itemKey, todayKey, onChange);

    appendLabeledField(inner, 'Date triggered:', record.triggeredDateText || formatDate(todayKey), false, 'notifications-list-item__field--date');
    appendLabeledField(inner, 'System finding:', record.systemFinding || categoryLabel(record.checkId), false, 'notifications-list-item__field--finding');

    if (record.itemName != null && String(record.itemName).length) {
      appendLabeledField(inner, 'Item name:', String(record.itemName), true);
    }

    if (record.detailDateCaption && record.detailDateText) {
      appendLabeledField(inner, record.detailDateCaption, record.detailDateText, false);
    }

    (record.extraFields || []).forEach(function (row) {
      if (!row || row.value == null || String(row.value).trim() === '') return;
      if (row.pre) {
        appendLabeledPre(inner, row.label || 'Details:', String(row.value));
      } else {
        appendLabeledField(inner, row.label || 'Details:', String(row.value), !!row.emphasis);
      }
    });

    createActionsRow(inner, record);

    li.appendChild(inner);
    return li;
  }

  async function renderCards() {
    var listEl = document.getElementById('system-findings-list');
    var bannerBody = document.getElementById('system-findings-banner-body');
    var banner = document.getElementById('system-findings-banner');

    if (!listEl || !bannerBody || !banner) return;

    bannerBody.hidden = false;
    bannerBody.removeAttribute('hidden');
    banner.style.display = 'block';

    var todayKey = todayDateKey();
    var findings = await fetchFindings();
    var records = buildNotificationRecords(findings, todayKey);

    listEl.innerHTML = '';

    var onChange = function () {
      renderCards();
    };

    records.forEach(function (rec) {
      listEl.appendChild(renderLi(rec, todayKey, onChange));
    });

    ensureEmptyState(records.length);

    if (window.SystemFindingsNotifications && typeof window.SystemFindingsNotifications.refreshBadge === 'function') {
      window.SystemFindingsNotifications.refreshBadge();
    }
  }

  function init() {
    bindOverflowMenuHandlers();
    renderCards();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
