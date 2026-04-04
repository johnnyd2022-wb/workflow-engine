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

  /** Deep-link filter: ?category= matches system status bar routing (see core2 health nav). */
  var NOTIFY_CATEGORY_CHECKS = {
    traceability: ['untracked_items'],
    inventory: ['expired_materials', 'output_expiry'],
    availability: ['output_ready_date']
  };

  function getActiveNotificationCategoryFilter() {
    try {
      var q = new URLSearchParams(window.location.search || '');
      var c = (q.get('category') || '').trim().toLowerCase();
      if (Object.prototype.hasOwnProperty.call(NOTIFY_CATEGORY_CHECKS, c)) {
        return c;
      }
    } catch (e) {
      /* ignore */
    }
    return null;
  }

  function recordMatchesNotificationCategory(record, category) {
    var allowed = NOTIFY_CATEGORY_CHECKS[category];
    if (!allowed || !record || record.checkId == null) {
      return false;
    }
    return allowed.indexOf(String(record.checkId)) !== -1;
  }

  function ensureCategoryFilterStrip(category) {
    var listEl = document.getElementById('system-findings-list');
    if (!listEl || !listEl.parentNode) {
      return;
    }
    var id = 'notifications-category-filter-strip';
    var strip = document.getElementById(id);
    if (!category) {
      if (strip) {
        strip.remove();
      }
      return;
    }
    var labels = { traceability: 'Traceability', inventory: 'Inventory', availability: 'Availability' };
    if (!strip) {
      strip = document.createElement('div');
      strip.id = id;
      strip.className = 'notifications-category-filter-strip';
      listEl.parentNode.insertBefore(strip, listEl);
    }
    strip.textContent = '';
    var p = document.createElement('p');
    p.className = 'notifications-category-filter-strip__text';
    p.appendChild(document.createTextNode('Filtered to '));
    var strong = document.createElement('strong');
    strong.textContent = labels[category] || category;
    p.appendChild(strong);
    p.appendChild(document.createTextNode('. '));
    var a = document.createElement('a');
    a.href = '/core/notifications';
    a.className = 'notifications-category-filter-strip__clear';
    a.setAttribute('hx-boost', 'false');
    a.textContent = 'Show all notifications';
    p.appendChild(a);
    strip.appendChild(p);
  }

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
      return d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: '2-digit' });
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
      item && item.created_at,
      item && item.purchase_date,
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

  function resolveTriggeredDateText(item, finding, data) {
    var triggered = pickTriggeredDate(item, finding, data);
    if (!triggered) return 'Unknown';
    var formatted = formatDate(triggered);
    return formatted === '—' ? 'Unknown' : formatted;
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

  function fallbackText(value, fallbackValue) {
    if (value == null) return fallbackValue;
    var text = String(value).trim();
    return text ? text : fallbackValue;
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
            triggeredDateText: resolveTriggeredDateText(raw, f, data),
            systemFinding: categoryLabel(checkId),
            summaryText: 'Inventory item ' + fallbackText(raw.name || rawId, 'Unknown item') + ' expired on ' + formatDate(dateStr) + '.',
            detailText: impactedLine
              ? 'Select from the actions below to remove this expired item or open Sourcemap to trace usage in: ' + impactedLine + '.'
              : 'Select from the actions below to remove this expired item from inventory or open Sourcemap to trace usage.',
            detailDateCaption: null,
            detailDateText: null,
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

          records.push({
            checkId: checkId,
            itemKey: ik,
            sortMs: sortMs,
            triggeredDateText: resolveTriggeredDateText(x, f, data),
            systemFinding: categoryLabel(checkId),
            summaryText: 'Inventory item ' + fallbackText(name, 'Unknown item') + ' has an output expiry date of ' + formatDate(expStr) + '.',
            detailText: processStep
              ? 'This warning was detected for process step: ' + processStep + '. Select an action below to review and update the process.'
              : 'Select an action below to review this item and update the related process settings.',
            detailDateCaption: null,
            detailDateText: null,
            itemName: name,
            extraFields: [],
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
            triggeredDateText: resolveTriggeredDateText(x, f, data),
            systemFinding: categoryLabel(checkId),
            summaryText: fallbackText(name, 'This item') + ' is set to be ready from ' + formatDate(rd) + '.',
            detailText: detail
              ? detail + (processStep ? ' (' + processStep + ')' : '')
              : (processStep
                ? 'Detected on process step: ' + processStep + '. Select an action below to review the process.'
                : 'Select an action below to review this ready-date warning.'),
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

          var processId = (u.process_id != null && String(u.process_id).trim() !== '') ? String(u.process_id) : '';
          var processName = (u.process_name != null) ? String(u.process_name) : '';
          var stepName = (u.producing_step_name != null && u.producing_step_name !== '') ? u.producing_step_name : (u.step_name || '');

          var createdText = formatDate(created);
          var untrackedActions = [];
          if (processId) {
            untrackedActions.push({
              type: 'reconcile',
              href: '#',
              label: 'Go to process step to execute and reconcile',
              processId: processId,
              processName: processName,
              stepName: stepName
            });
          }
          untrackedActions.push({
            type: 'link',
            href: '/core/sourcemap?show=check-needed',
            label: processId
              ? 'Review in Sourcemap'
              : 'Find process step in Sourcemap to execute and reconcile',
            boost: false
          });
          records.push({
            checkId: checkId,
            itemKey: ik,
            sortMs: sortMs,
            triggeredDateText: resolveTriggeredDateText(u, f, data),
            systemFinding: categoryLabel(checkId),
            summaryText: 'Inventory item ' + fallbackText(name, 'Unknown item') + ' is currently untracked in inventory.',
            detailText: stepName
              ? 'Context: ' + (unreconciled !== null ? unreconciled : '0') + ' ' + (u.unit || '') + ' of '
                + fallbackText(name, 'this item') + ' was recorded as unreconciled on ' + createdText
                + '. Execute step "' + stepName + '" in process "' + fallbackText(processName, 'the linked process')
                + '" to create output and reconcile against this inventory item.'
              : 'Context: ' + (unreconciled !== null ? unreconciled : '0') + ' ' + (u.unit || '') + ' of '
                + fallbackText(name, 'this item') + ' was recorded as unreconciled on ' + createdText
                + '. Use the actions below to find the process step, execute it, and reconcile this item.',
            detailDateCaption: null,
            detailDateText: null,
            itemName: name,
            extraFields: [],
            actions: untrackedActions
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
        triggeredDateText: resolveTriggeredDateText(null, f, data),
        systemFinding: categoryLabel(checkId),
        summaryText: msg,
        detailText: rawJson ? 'Technical details are included below.' : '',
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

    appendLabeledField(inner, 'Date triggered:', record.triggeredDateText || 'Unknown', false, 'notifications-list-item__field--date');
    appendLabeledField(
      inner,
      'System finding:',
      record.summaryText || record.systemFinding || categoryLabel(record.checkId),
      true,
      'notifications-list-item__field--finding'
    );

    if (record.detailText && String(record.detailText).trim()) {
      appendLabeledField(inner, 'Details:', String(record.detailText), false, 'notifications-list-item__field--narrative');
    }

    if (record.detailDateCaption && record.detailDateText && record.detailDateText !== '—') {
      appendLabeledField(inner, record.detailDateCaption, record.detailDateText, false, 'notifications-list-item__field--supporting');
    }

    (record.extraFields || []).forEach(function (row) {
      if (!row || row.value == null || String(row.value).trim() === '') return;
      if (row.pre) {
        appendLabeledPre(inner, row.label || 'Technical details:', String(row.value));
      } else {
        appendLabeledField(inner, row.label || 'Details:', String(row.value), !!row.emphasis, 'notifications-list-item__field--supporting');
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

    var categoryFilter = getActiveNotificationCategoryFilter();
    if (categoryFilter) {
      records = records.filter(function (rec) {
        return recordMatchesNotificationCategory(rec, categoryFilter);
      });
    }
    ensureCategoryFilterStrip(categoryFilter);

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
