/**
 * Notifications: what needs you, late first, each with the action that resolves it.
 *
 * Reads CoreAPI.getSystemFindings(). Core's own checks (expired stock, output dates, untracked
 * items, tasks) are turned into notifications here; every other check describes its own in the
 * generic module contract (data.system_alerts: title, description, due_date, href, action_label,
 * optional area and summary) and is rendered without this file knowing which module sent it.
 *
 * Every notification has one primary action, shown as a button on the row, plus any secondary
 * links. Hiding is per browser (sessionStorage), and the menu says so.
 */
(function () {
  'use strict';

  var DAY = 24 * 3600 * 1000;
  var SOON_DAYS = 7;
  // CONCEPT ONLY: the style switch goes when one style is chosen.
  var STYLE_KEY = 'nt-style';

  // Core checks' areas. Module checks name their own (system_finding.area or .category).
  var CORE_AREAS = {
    expired_materials: 'Stock',
    output_expiry: 'Stock',
    untracked_items: 'Stock',
    output_ready_date: 'Production',
    tasks_due: 'Tasks'
  };

  /** ?category= links from the Production overview's health bar. */
  var CATEGORY_CHECKS = {
    traceability: ['untracked_items'],
    inventory: ['expired_materials', 'output_expiry'],
    availability: ['output_ready_date']
  };

  // ── Dates in words ─────────────────────────────────────────────────────────────────────
  function todayStart() { var d = new Date(); d.setHours(0, 0, 0, 0); return d; }
  function todayKey() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function parseDay(value) {
    if (!value) return null;
    var text = String(value);
    var d = /^\d{4}-\d{2}-\d{2}$/.test(text) ? new Date(text + 'T00:00:00') : new Date(text);
    if (Number.isNaN(d.getTime())) return null;
    d.setHours(0, 0, 0, 0);
    return d;
  }
  function shortDate(d) {
    var opts = { day: 'numeric', month: 'short' };
    if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
    return d.toLocaleDateString('en-NZ', opts);
  }
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }
  /** 2.8, not the stored 2.8000. */
  function amount(value) {
    var n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString('en-NZ', { maximumFractionDigits: 3 }) : String(value);
  }

  /** How late, in a bucket and in words. `kind` changes the verb: an expiry, a ready date or a due date. */
  function timing(dueValue, kind) {
    var due = parseDay(dueValue);
    if (!due) return { bucket: 'undated', words: '', days: null, ms: Infinity };
    var days = Math.round((due - todayStart()) / DAY);
    var words;
    if (kind === 'expired') {
      words = days < 0 ? 'Expired ' + plural(-days, 'day') + ' ago' : (days === 0 ? 'Expires today' : 'Expires ' + shortDate(due));
    } else if (kind === 'ready') {
      words = days <= 0 ? 'Ready now' : 'Ready ' + shortDate(due);
    } else if (days < 0) {
      words = plural(-days, 'day') + ' late';
    } else if (days === 0) {
      words = 'Due today';
    } else if (days === 1) {
      words = 'Due tomorrow';
    } else if (days <= SOON_DAYS) {
      words = 'Due in ' + days + ' days';
    } else {
      words = 'Due ' + shortDate(due);
    }
    var late = kind === 'ready' ? false : days < 0;
    var bucket = late ? 'late' : (kind !== 'ready' && days <= SOON_DAYS ? 'soon' : 'later');
    return { bucket: bucket, words: words, days: days, ms: due.getTime() };
  }

  // ── Hiding (this browser only) ─────────────────────────────────────────────────────────
  function scopeTag() {
    var org = document.querySelector('meta[name="current-org-id"]');
    var user = document.querySelector('meta[name="current-user-id"]');
    return (org && org.getAttribute('content') || '') + '_' + (user && user.getAttribute('content') || '');
  }
  // Keys unchanged from the previous page, so what someone hid stays hidden.
  function snoozeKey(r) { return 'corechecks_finding_ignore_date_' + scopeTag() + '_' + r.checkId + '_' + r.itemKey; }
  function hideKey(r) { return 'corechecks_finding_dismissed_' + scopeTag() + '_' + r.checkId + '_' + r.itemKey; }
  function store(fn) { try { return fn(window.sessionStorage); } catch (e) { return null; } }
  function hiddenState(r) {
    if (store(function (s) { return s.getItem(hideKey(r)); }) === '1') return 'hidden';
    if (store(function (s) { return s.getItem(snoozeKey(r)); }) === todayKey()) return 'snoozed';
    return null;
  }

  // ── Notifications from the findings ────────────────────────────────────────────────────
  function safeHref(value) {
    var href = value == null ? '' : String(value).trim();
    return href.charAt(0) === '/' && href.charAt(1) !== '/' ? href : '';
  }
  function text(value, fallback) {
    var t = value == null ? '' : String(value).trim();
    return t || fallback;
  }
  function lotHref(id) { return '/core/inventory/view?item=' + encodeURIComponent(id); }
  /** Record disposal with these lots, all of each, and the reason already filled in. */
  function disposeHref(ids) {
    return '/core/inventory/dispose?item_ids=' + ids.map(encodeURIComponent).join(',') + '&whole=1&reason=Expired';
  }

  function record(fields) {
    var t = timing(fields.due, fields.dueKind);
    return Object.assign({ secondary: [], detail: '', area: 'Other' }, fields, { timing: t });
  }

  function fromExpired(checkId, data) {
    var impacted = Array.isArray(data.impacted_items) ? data.impacted_items : [];
    return (Array.isArray(data.expired_raw_materials) ? data.expired_raw_materials : []).map(function (raw) {
      var id = raw && raw.id != null ? String(raw.id) : '';
      if (!id) return null;
      var used = impacted.filter(function (it) { return it && String(it.expired_raw_material_id) === id; })
        .map(function (it) { return text(it.name, ''); }).filter(Boolean);
      var names = Array.from(new Set(used));
      return record({
        checkId: checkId, itemKey: id, area: CORE_AREAS[checkId], lotId: id,
        title: text(raw.name, 'A raw material') + (raw.supplier_batch_number ? ' · lot ' + raw.supplier_batch_number : '') + ' has expired',
        detail: (raw.quantity != null ? amount(raw.quantity) + ' ' + text(raw.unit, '') + ' still in stock.' : 'Still in stock.')
          + (names.length ? ' Used in ' + names.join(', ') + '.' : ''),
        due: raw.expiry_date, dueKind: 'expired',
        primary: { label: 'Dispose', href: disposeHref([id]) },
        secondary: [
          { label: 'Open the lot', href: lotHref(id) },
          names.length ? { label: 'Trace where it went', href: '/core/sourcemap?show=check-needed' } : null
        ].filter(Boolean)
      });
    });
  }

  function fromOutputDate(checkId, data, kind) {
    var rows = Array.isArray(data[kind === 'expired' ? 'output_expiry_items' : 'output_ready_date_items'])
      ? data[kind === 'expired' ? 'output_expiry_items' : 'output_ready_date_items'] : [];
    var seen = {};
    return rows.map(function (x) {
      var item = x && x.inventory_item_id != null ? String(x.inventory_item_id) : '';
      var date = kind === 'expired' ? (x.expiry_at || x.expiry_date) : x.ready_date;
      var key = (kind === 'expired' ? 'oe_' : 'ord_') + item + '_' + (x.step_id || '') + '_' + (date || '');
      if (!item || seen[key]) return null;
      seen[key] = true;
      var where = [x.process_name, x.step_name].filter(Boolean).join(' · ');
      var pid = x.process_id != null ? String(x.process_id) : '';
      return record({
        checkId: checkId, itemKey: key, area: CORE_AREAS[checkId],
        title: text(x.item_name, 'An output') + (kind === 'expired' ? ' reaches its expiry date' : ' is waiting for its ready date'),
        detail: text(x.message, where ? 'Set by ' + where + '.' : ''),
        due: date, dueKind: kind,
        primary: { label: 'Open the lot', href: lotHref(item) },
        secondary: pid ? [{ label: 'Open the workflow', href: '/core/flows?id=' + encodeURIComponent(pid) }] : []
      });
    });
  }

  function fromUntracked(checkId, data) {
    return (Array.isArray(data.untracked_items) ? data.untracked_items : []).map(function (u) {
      var id = u && u.id != null ? String(u.id) : '';
      if (!id) return null;
      var pid = u.process_id ? String(u.process_id) : '';
      var sid = u.producing_step_id ? String(u.producing_step_id) : '';
      var step = text(u.producing_step_name || u.step_name, '');
      var primary = pid && sid
        ? { label: 'Record ' + (step || 'the step'), href: '/core/flows/batches/start?draft=1&id=' + encodeURIComponent(pid) + '&step_id=' + encodeURIComponent(sid) + '&return_to=' + encodeURIComponent('/core/notifications') }
        : (pid ? { label: 'Open the workflow', href: '/core/flows?id=' + encodeURIComponent(pid) } : { label: 'Open the lot', href: lotHref(id) });
      var left = u.remaining_balance_to_reconcile != null ? amount(u.remaining_balance_to_reconcile) + ' ' + text(u.unit, '') + ' ' : '';
      return record({
        checkId: checkId, itemKey: 'ut_' + id, area: CORE_AREAS[checkId], untrackedId: id, itemName: u.name,
        title: text(u.name, 'An item') + ' has no step that made it',
        detail: left + 'in stock without a production record'
          + (step ? '. Recording "' + step + '"' + (u.process_name ? ' in ' + u.process_name : '') + ' links it.' : '. Record the step that made it to link it.'),
        due: null,
        primary: primary,
        secondary: primary.href.indexOf('/core/inventory/view') === 0 ? [] : [{ label: 'Open the lot', href: lotHref(id) }]
      });
    });
  }

  function fromTasks(checkId, data) {
    var overdue = Array.isArray(data.overdue_tasks) ? data.overdue_tasks : [];
    var soon = Array.isArray(data.due_soon_tasks) ? data.due_soon_tasks : [];
    return overdue.concat(soon).map(function (task) {
      var id = task && task.id != null ? String(task.id) : '';
      if (!id) return null;
      var source = task.source === 'crm' ? 'crm' : 'core';
      var who = text(task.assigned_to_name, 'No one assigned');
      return record({
        checkId: checkId, itemKey: 'task_' + (task.source || 'core') + '_' + id + '_' + (task.due_date || ''), area: CORE_AREAS[checkId],
        title: text(task.title, 'A task'),
        detail: (source === 'crm' ? 'Sales' : 'Production') + ' task · ' + who,
        due: task.due_date,
        primary: { label: 'Open the task', href: source === 'crm' ? '/crm/tasks' : '/core/tasks' }
      });
    });
  }

  function fromModule(checkId, data) {
    var finding = data.system_finding && typeof data.system_finding === 'object' ? data.system_finding : {};
    var area = text(finding.area || finding.category, 'Other');
    var summary = null;
    var rows = [];
    (Array.isArray(data.system_alerts) ? data.system_alerts : []).forEach(function (alert) {
      if (!alert || alert.id == null) return;
      var href = safeHref(alert.href);
      var r = record({
        checkId: checkId, itemKey: 'module_' + String(alert.id), area: text(alert.area, area),
        title: text(alert.title, 'Something needs attention'),
        detail: text(alert.description, ''),
        due: alert.due_date,
        primary: href ? { label: text(alert.action_label, 'Open'), href: href } : null
      });
      // A summary counts the alerts beside it: it heads their group instead of being one more row.
      if (alert.summary) summary = r; else rows.push(r);
    });
    if (summary && !rows.length) rows.push(summary);
    return { rows: rows, summary: summary && rows.indexOf(summary) === -1 ? summary : null };
  }

  function buildAll(findings) {
    var all = [];
    var summaries = {};
    findings.forEach(function (f) {
      var checkId = f && f.check_id != null ? String(f.check_id) : '';
      if (!checkId) return;
      var data = f.data && typeof f.data === 'object' ? f.data : {};
      var rows;
      if (Array.isArray(data.system_alerts) && data.system_alerts.length) {
        var built = fromModule(checkId, data);
        rows = built.rows;
        if (built.summary) summaries[built.summary.area] = built.summary;
      } else if (checkId === 'expired_materials') rows = fromExpired(checkId, data);
      else if (checkId === 'output_expiry') rows = fromOutputDate(checkId, data, 'expired');
      else if (checkId === 'output_ready_date') rows = fromOutputDate(checkId, data, 'ready');
      else if (checkId === 'untracked_items') rows = fromUntracked(checkId, data);
      else if (checkId === 'tasks_due') rows = fromTasks(checkId, data);
      else rows = f.text ? [record({ checkId: checkId, itemKey: 'gen_' + checkId, area: 'Other', title: String(f.text), primary: null })] : [];
      rows.forEach(function (r) { if (r) all.push(r); });
    });
    var order = { late: 0, soon: 1, undated: 2, later: 3 };
    all.sort(function (a, b) {
      return (order[a.timing.bucket] - order[b.timing.bucket]) || (a.timing.ms - b.timing.ms) || a.title.localeCompare(b.title);
    });
    return { rows: all, summaries: summaries };
  }

  // ── The page ───────────────────────────────────────────────────────────────────────────
  function init(root) {
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    var $ = function (sel) { return root.querySelector(sel); };
    var els = {
      list: $('[data-nt-list]'), detail: $('[data-nt-detail]'), areas: $('[data-nt-areas]'),
      summary: $('[data-nt-summary]'), heading: $('[data-nt-heading]')
    };
    var state = { view: 'active', area: '', style: '1', selected: null, all: [], summaries: {}, caseStatus: {} };

    function el(tag, className, content) {
      var node = document.createElement(tag);
      if (className) node.className = className;
      if (content != null) node.textContent = content;
      return node;
    }
    function link(action, className) {
      var a = el('a', className, action.label);
      a.href = action.href;
      return a;
    }

    // CONCEPT ONLY ─────────────────────────────────────────────────────────────────────────
    function readStyle() {
      var fromUrl = new URLSearchParams(window.location.search).get('style');
      var saved = null;
      try { saved = window.localStorage.getItem(STYLE_KEY); } catch (e) { /* private mode */ }
      var style = ['1', '2', '3'].indexOf(fromUrl) !== -1 ? fromUrl : (['1', '2', '3'].indexOf(saved) !== -1 ? saved : '1');
      setStyle(style, false);
    }
    function setStyle(style, remember) {
      state.style = style;
      root.setAttribute('data-notifications-style', style);
      root.querySelectorAll('[data-nt-style]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.ntStyle === style ? 'true' : 'false'); });
      if (remember) { try { window.localStorage.setItem(STYLE_KEY, style); } catch (e) { /* private mode */ } }
    }
    root.querySelectorAll('[data-nt-style]').forEach(function (b) {
      b.addEventListener('click', function () { setStyle(b.dataset.ntStyle, true); render(); });
    });
    // ────────────────────────────────────────────────────────────────────────────────────────

    function categoryFilter() {
      var c = (new URLSearchParams(window.location.search).get('category') || '').toLowerCase();
      return Object.prototype.hasOwnProperty.call(CATEGORY_CHECKS, c) ? CATEGORY_CHECKS[c] : null;
    }

    function visible() {
      var checks = categoryFilter();
      return state.all.filter(function (r) {
        var hidden = hiddenState(r);
        if (state.view === 'active' ? hidden : !hidden) return false;
        if (checks && checks.indexOf(r.checkId) === -1) return false;
        return true;
      });
    }

    // Cases, for untracked items: an action beside the fix, when operational cases are on.
    function casesOn() { var m = document.querySelector('meta[name="operational-cases-enabled"]'); return m && m.content === 'true'; }
    async function loadCases(rows) {
      if (!casesOn() || !window.CoreAPI || typeof window.CoreAPI.getCaseSourceStatus !== 'function') return;
      var ids = rows.filter(function (r) { return r.untrackedId; }).slice(0, 25).map(function (r) { return r.untrackedId; });
      if (!ids.length) return;
      try { state.caseStatus = ((await window.CoreAPI.getCaseSourceStatus(ids)) || {}).cases || {}; } catch (e) { state.caseStatus = {}; }
    }
    function caseAction(r) {
      if (!r.untrackedId || !Object.prototype.hasOwnProperty.call(state.caseStatus, r.untrackedId)) return null;
      var info = state.caseStatus[r.untrackedId];
      if (!info) return { label: 'Create a case', href: '/core/cases/new?source_entity_id=' + encodeURIComponent(r.untrackedId) + '&item_name=' + encodeURIComponent(r.itemName || '') };
      return { label: info.is_terminal ? 'Review the last case' : 'Open the case', href: safeHref(info.href) || '/core/cases' };
    }
    function secondaries(r) { var c = caseAction(r); return c ? r.secondary.concat([c]) : r.secondary; }

    function hideMenu(r) {
      var wrap = el('div', 'nt-more');
      var toggle = el('button', 'nt-more__toggle');
      toggle.type = 'button';
      toggle.setAttribute('aria-haspopup', 'menu');
      toggle.setAttribute('aria-expanded', 'false');
      toggle.setAttribute('aria-label', 'More for ' + r.title);
      toggle.appendChild(el('span', null, '⋯')).setAttribute('aria-hidden', 'true');
      var menu = el('div', 'nt-more__menu');
      menu.setAttribute('role', 'menu');
      menu.hidden = true;
      function item(label, title, fn) {
        var b = el('button', 'nt-more__item', label);
        b.type = 'button';
        b.setAttribute('role', 'menuitem');
        if (title) b.title = title;
        b.addEventListener('click', function (ev) { ev.stopPropagation(); fn(); render(); });
        menu.appendChild(b);
      }
      if (state.view === 'archive') {
        item('Show again', null, function () { store(function (s) { s.removeItem(snoozeKey(r)); s.removeItem(hideKey(r)); }); });
      } else {
        item('Hide until tomorrow', 'Only on this browser. The work stays open.', function () { store(function (s) { s.setItem(snoozeKey(r), todayKey()); }); });
        item('Hide for this session', 'Only on this browser. The work stays open.', function () { store(function (s) { s.setItem(hideKey(r), '1'); }); });
      }
      menu.appendChild(el('p', 'nt-more__note', 'Hiding only changes this browser.'));
      toggle.addEventListener('click', function (ev) {
        ev.stopPropagation();
        var open = menu.hidden;
        closeMenus();
        menu.hidden = !open;
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (open) { var first = menu.querySelector('button'); if (first) first.focus(); }
      });
      wrap.append(toggle, menu);
      return wrap;
    }
    /** Style 2's detail has room to show hiding as plain buttons rather than a ⋯ menu. */
    function hideButtons(r) {
      var wrap = el('div', 'nt-detail__hide');
      function btn(label, fn) {
        var b = el('button', 'nt-detail__hide-btn', label);
        b.type = 'button';
        b.addEventListener('click', function () { fn(); render(); });
        wrap.appendChild(b);
      }
      if (state.view === 'archive') {
        btn('Show again', function () { store(function (s) { s.removeItem(snoozeKey(r)); s.removeItem(hideKey(r)); }); });
      } else {
        btn('Hide until tomorrow', function () { store(function (s) { s.setItem(snoozeKey(r), todayKey()); }); });
        btn('Hide for this session', function () { store(function (s) { s.setItem(hideKey(r), '1'); }); });
      }
      wrap.appendChild(el('span', 'nt-detail__hide-note', 'Only on this browser; the work stays open.'));
      return wrap;
    }

    function closeMenus() {
      root.querySelectorAll('.nt-more__menu').forEach(function (m) { m.hidden = true; });
      root.querySelectorAll('.nt-more__toggle').forEach(function (t) { t.setAttribute('aria-expanded', 'false'); });
    }

    function when(r) {
      if (!r.timing.words) return null;
      return el('span', 'nt-when nt-when--' + r.timing.bucket, r.timing.words);
    }

    /** One notification as a row: what, why, when, and its fix as a button. */
    function row(r, compact) {
      var li = el('li', 'nt-row nt-row--' + r.timing.bucket);
      li.dataset.checkId = r.checkId;
      li.dataset.itemKey = r.itemKey;
      var main = el('div', 'nt-row__main');
      if (!compact) main.appendChild(el('span', 'nt-row__area', r.area));
      main.appendChild(el('p', 'nt-row__title', r.title));
      if (r.detail) main.appendChild(el('p', 'nt-row__detail', r.detail));
      var more = secondaries(r);
      if (more.length) {
        var links = el('p', 'nt-row__links');
        more.forEach(function (a) { links.appendChild(link(a, 'nt-row__link')); });
        main.appendChild(links);
      }
      var side = el('div', 'nt-row__side');
      var w = when(r);
      if (w) side.appendChild(w);
      if (r.primary) side.appendChild(link(r.primary, 'workspace-button workspace-button--primary nt-row__action'));
      side.appendChild(hideMenu(r));
      li.append(main, side);
      return li;
    }

    var BUCKETS = [
      ['late', 'Late'], ['soon', 'This week'], ['undated', 'To check'], ['later', 'Coming up']
    ];

    // Style 1: sections by how late, each row with its action.
    function renderQueue(rows) {
      var frag = document.createDocumentFragment();
      BUCKETS.forEach(function (b) {
        var inBucket = rows.filter(function (r) { return r.timing.bucket === b[0]; });
        if (!inBucket.length) return;
        var section = el('section', 'nt-section nt-section--' + b[0]);
        var h = el('h3', 'nt-section__title', b[1]);
        h.appendChild(el('span', 'nt-section__count', String(inBucket.length)));
        var ul = el('ul', 'nt-rows');
        inBucket.forEach(function (r) { ul.appendChild(row(r)); });
        section.append(h, ul);
        frag.appendChild(section);
      });
      return frag;
    }

    // Style 2: a quiet list; the chosen one is beside it with every action.
    function renderInbox(rows) {
      var ul = el('ul', 'nt-inbox');
      ul.setAttribute('role', 'listbox');
      ul.setAttribute('aria-label', 'Notifications');
      if (!rows.some(function (r) { return r.itemKey === state.selected; })) state.selected = rows.length ? rows[0].itemKey : null;
      rows.forEach(function (r, i) {
        var li = el('li', 'nt-inbox__item nt-inbox__item--' + r.timing.bucket);
        li.setAttribute('role', 'option');
        li.tabIndex = r.itemKey === state.selected ? 0 : -1;
        li.setAttribute('aria-selected', r.itemKey === state.selected ? 'true' : 'false');
        li.dataset.itemKey = r.itemKey;
        li.dataset.checkId = r.checkId;
        li.appendChild(el('span', 'nt-inbox__title', r.title));
        var meta = el('span', 'nt-inbox__meta', r.area);
        var w = when(r);
        if (w) { meta.appendChild(document.createTextNode(' · ')); meta.appendChild(w); }
        li.appendChild(meta);
        li.addEventListener('click', function () { select(r.itemKey, true); });
        li.addEventListener('keydown', function (ev) {
          var to = null;
          if (ev.key === 'ArrowDown' || ev.key === 'j') to = rows[i + 1];
          if (ev.key === 'ArrowUp' || ev.key === 'k') to = rows[i - 1];
          if (to) { ev.preventDefault(); select(to.itemKey, true); }
          if (ev.key === 'Enter' && r.primary) { ev.preventDefault(); window.location.href = r.primary.href; }
        });
        ul.appendChild(li);
      });
      renderDetail(rows);
      return ul;
    }
    function select(key, focus) {
      state.selected = key;
      els.list.querySelectorAll('.nt-inbox__item').forEach(function (li) {
        var on = li.dataset.itemKey === key;
        li.setAttribute('aria-selected', on ? 'true' : 'false');
        li.tabIndex = on ? 0 : -1;
        if (on && focus) li.focus();
      });
      renderDetail(visible().filter(areaMatch));
    }
    function renderDetail(rows) {
      var r = rows.filter(function (x) { return x.itemKey === state.selected; })[0];
      els.detail.replaceChildren();
      if (!r) return;
      els.detail.appendChild(el('p', 'nt-detail__area', r.area));
      els.detail.appendChild(el('h3', 'nt-detail__title', r.title));
      var w = when(r);
      if (w) els.detail.appendChild(w);
      if (r.detail) els.detail.appendChild(el('p', 'nt-detail__text', r.detail));
      var actions = el('div', 'nt-detail__actions');
      if (r.primary) actions.appendChild(link(r.primary, 'workspace-button workspace-button--primary'));
      secondaries(r).forEach(function (a) { actions.appendChild(link(a, 'workspace-button')); });
      els.detail.appendChild(actions);
      els.detail.appendChild(hideButtons(r));
    }

    // Style 3: one card per area, most late first, with the area's bulk action where there is one.
    function renderAreas(rows) {
      var groups = {};
      rows.forEach(function (r) { (groups[r.area] = groups[r.area] || []).push(r); });
      var names = Object.keys(groups).sort(function (a, b) {
        var late = function (n) { return groups[n].filter(function (r) { return r.timing.bucket === 'late'; }).length; };
        return (late(b) - late(a)) || (groups[b].length - groups[a].length) || a.localeCompare(b);
      });
      var frag = document.createDocumentFragment();
      names.forEach(function (name) {
        var items = groups[name];
        var lateCount = items.filter(function (r) { return r.timing.bucket === 'late'; }).length;
        var card = el('section', 'nt-group');
        var head = el('div', 'nt-group__head');
        var titles = el('div', 'nt-group__titles');
        titles.appendChild(el('h3', 'nt-group__title', name));
        var counts = el('p', 'nt-group__counts', plural(items.length, 'notification'));
        if (lateCount) { counts.appendChild(document.createTextNode(' · ')); counts.appendChild(el('span', 'nt-when nt-when--late', lateCount + ' late')); }
        titles.appendChild(counts);
        var summary = state.summaries[name];
        if (summary && summary.detail) titles.appendChild(el('p', 'nt-group__summary', summary.detail));
        head.appendChild(titles);
        var bulk = bulkAction(items) || (summary && summary.primary);
        if (bulk) head.appendChild(link(bulk, 'workspace-button nt-group__bulk'));
        var ul = el('ul', 'nt-rows');
        items.forEach(function (r) { ul.appendChild(row(r, true)); });
        card.append(head, ul);
        frag.appendChild(card);
      });
      return frag;
    }
    /** Several expired lots: dispose of them together, on one Record disposal page. */
    function bulkAction(items) {
      var lots = items.filter(function (r) { return r.checkId === 'expired_materials' && r.lotId; }).map(function (r) { return r.lotId; });
      return lots.length > 1 ? { label: 'Dispose all ' + lots.length + ' expired', href: disposeHref(lots) } : null;
    }

    function areaMatch(r) { return !state.area || r.area === state.area; }

    function renderAreaChips(rows) {
      var counts = {};
      rows.forEach(function (r) { counts[r.area] = (counts[r.area] || 0) + 1; });
      var names = Object.keys(counts).sort();
      if (state.area && !counts[state.area]) state.area = '';
      els.areas.replaceChildren();
      if (names.length < 2) return;
      [['', 'All', rows.length]].concat(names.map(function (n) { return [n, n, counts[n]]; })).forEach(function (c) {
        var b = el('button', 'nt-chip', c[1] + ' ');
        b.type = 'button';
        b.appendChild(el('span', 'nt-chip__count', String(c[2])));
        b.setAttribute('aria-pressed', state.area === c[0] ? 'true' : 'false');
        b.addEventListener('click', function () { state.area = c[0]; render(); });
        els.areas.appendChild(b);
      });
    }

    function empty(message) {
      var p = el('p', 'nt-empty', message);
      els.list.replaceChildren(p);
      els.detail.hidden = true;
    }

    function render() {
      closeMenus();
      var rows = visible();
      renderAreaChips(rows);
      var shown = rows.filter(areaMatch);
      var late = shown.filter(function (r) { return r.timing.bucket === 'late'; }).length;
      els.heading.textContent = state.view === 'archive' ? 'Hidden on this browser' : 'Needs you';
      els.summary.textContent = state.view === 'archive'
        ? (shown.length ? plural(shown.length, 'notification') + ' hidden. They come back tomorrow or when this browser session ends.' : '')
        : (shown.length ? plural(shown.length, 'notification') + (late ? ', ' + late + ' late' : '') + '.' : '');
      if (!shown.length) {
        empty(state.view === 'archive' ? 'Nothing hidden.' : (categoryFilter() ? 'Nothing here needs you.' : 'Nothing needs you right now.'));
        return;
      }
      els.detail.hidden = state.style !== '2';
      var content = state.style === '2' ? renderInbox(shown) : state.style === '3' ? renderAreas(shown) : renderQueue(shown);
      els.list.replaceChildren(content);
    }

    async function load() {
      var data = null;
      try {
        data = window.CoreAPI && typeof window.CoreAPI.getSystemFindings === 'function' ? await window.CoreAPI.getSystemFindings() : null;
      } catch (e) {
        data = null;
      }
      if (!root.isConnected) return;
      if (!data || !Array.isArray(data.findings)) {
        // Not "nothing needs you": the page couldn't ask (GL-U04).
        els.summary.textContent = '';
        empty("Couldn't load notifications. Reload the page to try again.");
        root.setAttribute('aria-busy', 'false');
        return;
      }
      var built = buildAll(data.findings);
      state.all = built.rows;
      state.summaries = built.summaries;
      await loadCases(state.all);
      if (!root.isConnected) return;
      render();
      root.setAttribute('aria-busy', 'false');
      if (window.SystemFindingsNotifications && typeof window.SystemFindingsNotifications.refreshBadge === 'function') {
        window.SystemFindingsNotifications.refreshBadge();
      }
    }

    root.querySelectorAll('[data-nt-view]').forEach(function (b) {
      b.addEventListener('click', function () {
        state.view = b.dataset.ntView;
        root.querySelectorAll('[data-nt-view]').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
        render();
      });
    });
    root.addEventListener('click', function (ev) { if (!ev.target.closest('.nt-more')) closeMenus(); });
    root.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') closeMenus(); });

    readStyle();
    if (window.LiveSync) {
      window.LiveSync.subscribe({
        key: 'notifications-cases',
        match: function (evt) { return evt.entity_type === 'operational_case'; },
        onChange: function () { if (!document.hidden && root.isConnected) load(); }
      });
    }
    load();
  }

  function boot() { init(document.querySelector('[data-notifications-page]')); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
  document.addEventListener('htmx:afterSettle', boot);
})();
