/* The Inventory page: status tiles and a filter bar over the stock table, and a side panel
   with one line's detail and audit history.

   Loaded from inside the page's content block, so it runs again on every visit, boosted or
   not. Everything it listens on lives inside the page root (replaced on each swap); the two
   exceptions, the document key handler and the LiveSync subscription, remove themselves once
   that root has left the document. */
(function () {
  'use strict';

  var root = document.querySelector('[data-inventory-view]');
  if (!root || root.dataset.inventoryViewReady === 'true') return;
  root.dataset.inventoryViewReady = 'true';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var EXPIRING_DAYS = 30;
  var GROUP_PREF_KEY = 'inventoryView.group';
  var TYPES = {
    raw_material: { label: 'Raw', css: 'raw' },
    work_in_progress: { label: 'Intermediate', css: 'wip' },
    final_product: { label: 'Final', css: 'final' },
  };
  var STATUSES = {
    '': { label: 'All stock', test: function () { return true; } },
    expiring: {
      label: 'Expiring in ' + EXPIRING_DAYS + ' days',
      tone: 'attention',
      test: function (item) { var d = daysToExpiry(item); return d != null && d >= 0 && d <= EXPIRING_DAYS; },
    },
    expired: {
      label: 'Expired',
      tone: 'overdue',
      test: function (item) { var d = daysToExpiry(item); return d != null && d < 0; },
    },
    'no-batch': {
      label: 'Raw, no batch number',
      tone: 'attention',
      test: function (item) { return item.inventory_type === 'raw_material' && !item.supplier_batch_number; },
    },
  };
  // extra_data keys that are whole structures with their own home in the product, not facts
  // about the line that belong in the panel's "More details" list.
  var HIDDEN_META = {
    execution_prompts: 1, execution_trace: 1, variable_inputs: 1, variable_output: 1,
    previous_steps_data: 1, inventory_audit_history: 1, reconciliation_history: 1,
    producing_process_name: 1, producing_step_name: 1,
  };
  var COLUMNS = [
    { key: 'name', label: 'Item', sortable: true },
    { key: 'type', label: 'Type' },
    { key: 'qty', label: 'On hand', sortable: true, numeric: true },
    { key: 'trend', label: 'Trend' },
    { key: 'expiry', label: 'Expiry', sortable: true },
    { key: 'since', label: 'In stock since', sortable: true },
    { key: 'go', label: '' },
  ];

  var canAdjust = root.dataset.canAdjust === 'true';
  var items = [];
  var loadSeq = 0;
  var openGroups = {};
  var state = {
    q: '', type: '', supplier: '', process: '', status: '',
    expFrom: '', expTo: '', purFrom: '', purTo: '', metaKey: '', metaText: '',
    sort: 'name', dir: 'asc', group: false, item: '',
  };
  var URL_KEYS = ['q', 'type', 'supplier', 'process', 'status', 'expFrom', 'expTo', 'purFrom', 'purTo', 'metaKey', 'metaText', 'item'];

  function $(selector) { return root.querySelector(selector); }
  var els = {
    glance: $('[data-inv-glance]'),
    count: $('#inv-view-count'),
    search: $('#inv-filter-search'),
    segments: $('[data-inv-segments]'),
    supplier: $('#inv-filter-supplier'),
    process: $('#inv-filter-process'),
    moreToggle: $('[data-inv-more-toggle]'),
    more: $('[data-inv-more]'),
    expFrom: $('#inv-filter-expiry-from'),
    expTo: $('#inv-filter-expiry-to'),
    purFrom: $('#inv-filter-purchase-from'),
    purTo: $('#inv-filter-purchase-to'),
    metaKey: $('#inv-filter-meta-key'),
    metaText: $('#inv-filter-meta-text'),
    group: $('[data-inv-group]'),
    active: $('[data-inv-active]'),
    loading: $('#inv-view-loading'),
    empty: $('#inv-view-empty'),
    tableWrap: $('#inv-view-table-wrap'),
    thead: $('#inv-view-table thead'),
    tbody: $('#inv-view-tbody'),
    drawer: $('[data-inv-drawer]'),
    drawerBody: $('[data-inv-drawer-body]'),
    drawerFoot: $('[data-inv-drawer-foot]'),
    drawerTitle: $('#inv-drawer-title'),
    drawerEyebrow: $('[data-inv-drawer-eyebrow]'),
    backdrop: $('[data-inv-backdrop]'),
  };
  var lastFocus = null;

  // ── Small helpers ────────────────────────────────────────────────────────────────────
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function svg(tag, attrs) {
    var node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    return node;
  }
  function icon(pathData, className) {
    var node = svg('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', class: className || 'inv-icon' });
    node.appendChild(svg('path', { d: pathData }));
    return node;
  }
  function qty(item) {
    var n = parseFloat(String(item.quantity == null ? '0' : item.quantity).trim());
    return isNaN(n) ? 0 : n;
  }
  function onHand(item) { return qty(item) >= 0.0001; }
  function fmtQty(n) { return Number(n).toLocaleString(undefined, { maximumFractionDigits: 4 }); }
  function datePart(iso) { return iso && typeof iso === 'string' ? iso.slice(0, 10) : ''; }
  // A stored date is a calendar day, not an instant: build it in local time so it never
  // slips a day west of UTC.
  function localDate(iso) {
    var p = datePart(iso).split('-');
    if (p.length !== 3) return null;
    var d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    return isNaN(d.getTime()) ? null : d;
  }
  function fmtDate(iso) {
    var d = localDate(iso);
    return d ? d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '';
  }
  function fmtDateTime(iso) {
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d.getTime())) return '';
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) + ', ' +
      d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  }
  function daysToExpiry(item) {
    var d = localDate(item.expiry_date);
    if (!d) return null;
    var now = new Date();
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.round((d - today) / 86400000);
  }
  function sinceDate(item) { return datePart(item.purchase_date) || datePart(item.created_at); }
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }
  function sourceLine(item) {
    var parts = [];
    if (item.inventory_type === 'raw_material') {
      if (item.supplier) parts.push(item.supplier);
      if (item.supplier_batch_number) parts.push('Batch ' + item.supplier_batch_number);
    } else {
      if (item.process_name) parts.push(item.process_name);
      var step = item.producing_step_name || item.source_step_name;
      if (step) parts.push(step);
      if (item.supplier_batch_number) parts.push('Batch ' + item.supplier_batch_number);
    }
    return parts.join(' · ');
  }
  function metaJson(item) {
    try { return JSON.stringify(item.extra_data || {}).toLowerCase(); } catch (e) { return ''; }
  }

  // ── Filtering, sorting, grouping ─────────────────────────────────────────────────────
  function passes(item, skip) {
    skip = skip || {};
    if (!skip.status && !STATUSES[state.status].test(item)) return false;
    if (!skip.type && state.type && (item.inventory_type || '') !== state.type) return false;
    if (state.supplier && String(item.supplier || '').trim() !== state.supplier) return false;
    if (state.process && String(item.process_name || '').trim() !== state.process) return false;

    var exp = datePart(item.expiry_date);
    if (state.expFrom && (!exp || exp < state.expFrom)) return false;
    if (state.expTo && (!exp || exp > state.expTo)) return false;
    var pur = datePart(item.purchase_date);
    if (state.purFrom && (!pur || pur < state.purFrom)) return false;
    if (state.purTo && (!pur || pur > state.purTo)) return false;

    if (state.metaKey) {
      var extra = item.extra_data;
      if (!extra || typeof extra !== 'object' || !Object.prototype.hasOwnProperty.call(extra, state.metaKey)) return false;
    }
    var metaNeedle = state.metaText.trim().toLowerCase();
    if (metaNeedle && metaJson(item).indexOf(metaNeedle) === -1) return false;

    var needle = state.q.trim().toLowerCase();
    if (needle) {
      var hay = [item.name, item.unit, item.supplier, item.process_name, item.source_step_name,
        item.producing_step_name, item.supplier_batch_number, item.barcode, metaJson(item)]
        .filter(Boolean).join(' ').toLowerCase();
      if (hay.indexOf(needle) === -1) return false;
    }
    return true;
  }

  function sortValue(row, key) {
    if (key === 'qty') return row.qty;
    if (key === 'expiry') return row.expiry || '';
    if (key === 'since') return row.since || '';
    return (row.name || '').toLowerCase();
  }
  function compareRows(a, b) {
    var av = sortValue(a, state.sort), bv = sortValue(b, state.sort);
    // Lines with no date sort last in either direction: they are not "earliest".
    if (state.sort === 'expiry' || state.sort === 'since') {
      if (!av && bv) return 1;
      if (av && !bv) return -1;
    }
    var out = av < bv ? -1 : av > bv ? 1 : 0;
    if (state.dir === 'desc') out = -out;
    if (out) return out;
    // Same product: earliest expiry first, the lot to use next.
    var an = (a.name || '').toLowerCase(), bn = (b.name || '').toLowerCase();
    if (an !== bn) return an < bn ? -1 : 1;
    if ((a.expiry || '') !== (b.expiry || '')) {
      if (!a.expiry) return 1;
      if (!b.expiry) return -1;
      return a.expiry < b.expiry ? -1 : 1;
    }
    return 0;
  }
  function lotRow(item) {
    return { kind: 'lot', item: item, name: item.name, qty: qty(item), expiry: datePart(item.expiry_date), since: sinceDate(item) };
  }
  function buildRows(filtered) {
    var lots = filtered.map(lotRow);
    if (!state.group) return lots.sort(compareRows);
    var byKey = {}, order = [];
    lots.forEach(function (row) {
      var key = (row.name || '').toLowerCase() + '|' + (row.item.unit || '').toLowerCase();
      if (!byKey[key]) { byKey[key] = []; order.push(key); }
      byKey[key].push(row);
    });
    var rows = order.map(function (key) {
      var members = byKey[key].sort(compareRows);
      if (members.length === 1) return members[0];
      var expiries = members.map(function (m) { return m.expiry; }).filter(Boolean).sort();
      var sinces = members.map(function (m) { return m.since; }).filter(Boolean).sort();
      return {
        kind: 'group', key: key, members: members, name: members[0].name, unit: members[0].item.unit,
        qty: members.reduce(function (sum, m) { return sum + m.qty; }, 0),
        expiry: expiries[0] || '', since: sinces[0] || '',
      };
    });
    return rows.sort(compareRows);
  }

  // ── Cells ────────────────────────────────────────────────────────────────────────────
  function typeBadge(type) {
    var meta = TYPES[type] || { label: type || 'Unknown', css: 'raw' };
    var badge = el('span', 'inv-type inv-type--' + meta.css);
    badge.appendChild(el('span', 'inv-type__dot'));
    badge.appendChild(document.createTextNode(meta.label));
    return badge;
  }
  function expiryNode(isoDate) {
    if (!isoDate) return el('span', 'inv-muted', '—');
    var days = daysToExpiry({ expiry_date: isoDate });
    var wrap = el('span', 'inv-expiry');
    if (days < 0) {
      wrap.appendChild(el('span', 'inv-pill inv-pill--overdue', days === -1 ? 'Expired yesterday' : 'Expired ' + (-days) + ' days ago'));
    } else if (days <= EXPIRING_DAYS) {
      wrap.appendChild(el('span', 'inv-pill inv-pill--attention', days === 0 ? 'Expires today' : days === 1 ? '1 day left' : days + ' days left'));
    }
    wrap.appendChild(el('span', days <= EXPIRING_DAYS ? 'inv-expiry__date inv-muted' : 'inv-expiry__date', fmtDate(isoDate)));
    return wrap;
  }
  function sparkline(item, width, height) {
    var history = item.event_summary && item.event_summary.quantity_history;
    if (!history || history.length < 2) return null;
    var vals = history.map(function (h) { return parseFloat(h.qty) || 0; });
    var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    if (min === max) return null;
    var pad = 2;
    var pts = vals.map(function (v, i) {
      var x = pad + (i / (vals.length - 1)) * (width - pad * 2);
      var y = height - pad - ((v - min) / (max - min)) * (height - pad * 2);
      return x.toFixed(1) + ',' + y.toFixed(1);
    });
    var falling = vals[vals.length - 1] < vals[0];
    var node = svg('svg', {
      class: 'inv-sparkline inv-sparkline--' + (falling ? 'down' : 'up'), width: width, height: height,
      viewBox: '0 0 ' + width + ' ' + height, role: 'img',
      'aria-label': 'Quantity ' + (falling ? 'down' : 'up') + ' from ' + fmtQty(vals[0]) + ' to ' + fmtQty(vals[vals.length - 1]) + ' over ' + plural(vals.length - 1, 'change'),
    });
    node.appendChild(svg('polygon', { class: 'inv-sparkline__area', points: pad + ',' + height + ' ' + pts.join(' ') + ' ' + (width - pad) + ',' + height }));
    node.appendChild(svg('polyline', { class: 'inv-sparkline__line', points: pts.join(' ') }));
    var last = pts[pts.length - 1].split(',');
    node.appendChild(svg('circle', { class: 'inv-sparkline__dot', cx: last[0], cy: last[1], r: 2 }));
    return node;
  }
  function qtyCell(amount, unit) {
    var td = el('td', 'inv-cell-qty');
    td.appendChild(el('span', 'inv-qty', fmtQty(amount)));
    td.appendChild(el('span', 'inv-unit', unit || ''));
    return td;
  }
  function cell(className, child) {
    var td = el('td', className);
    if (child) td.appendChild(child);
    return td;
  }
  function chevron(className) { return icon('m9 6 6 6-6 6', className || 'inv-icon inv-chevron'); }

  function lotTr(row, isChild) {
    var item = row.item;
    var tr = el('tr', 'inv-row' + (isChild ? ' inv-row--child' : '') + (state.item === item.id ? ' is-selected' : ''));
    tr.dataset.itemId = item.id;

    var itemTd = el('td', 'inv-cell-item');
    var open = el('button', 'inv-row__open', item.name);
    open.type = 'button';
    open.setAttribute('aria-haspopup', 'dialog');
    itemTd.appendChild(open);
    if (item.system_findings && item.system_findings.length) {
      var flag = el('span', 'inv-row__flag', plural(item.system_findings.length, 'finding'));
      flag.title = item.system_findings.map(function (f) { return f.reason; }).join('\n');
      itemTd.appendChild(flag);
    }
    var sub = sourceLine(item);
    itemTd.appendChild(el('span', 'inv-row__sub', sub || (item.inventory_type === 'raw_material' ? 'No supplier recorded' : 'No process recorded')));
    tr.appendChild(itemTd);
    tr.appendChild(cell('inv-cell-type', typeBadge(item.inventory_type)));
    tr.appendChild(qtyCell(row.qty, item.unit));
    tr.appendChild(cell('inv-cell-trend', sparkline(item, 84, 28)));
    tr.appendChild(cell('inv-cell-expiry', expiryNode(row.expiry)));
    tr.appendChild(cell('inv-cell-since', el('span', row.since ? '' : 'inv-muted', row.since ? fmtDate(row.since) : '—')));
    tr.appendChild(cell('inv-cell-go', chevron()));
    tr.addEventListener('click', function () { openDrawer(item.id, open); });
    return tr;
  }
  function groupTr(row) {
    var isOpen = !!openGroups[row.key];
    var tr = el('tr', 'inv-row inv-row--group' + (isOpen ? ' is-open' : ''));
    var itemTd = el('td', 'inv-cell-item');
    var toggle = el('button', 'inv-row__open', row.name);
    toggle.type = 'button';
    toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    itemTd.appendChild(toggle);
    itemTd.appendChild(el('span', 'inv-row__sub', plural(row.members.length, 'lot')));
    tr.appendChild(itemTd);
    tr.appendChild(cell('inv-cell-type', typeBadge(row.members[0].item.inventory_type)));
    tr.appendChild(qtyCell(row.qty, row.unit));
    tr.appendChild(cell('inv-cell-trend'));
    tr.appendChild(cell('inv-cell-expiry', expiryNode(row.expiry)));
    tr.appendChild(cell('inv-cell-since', el('span', row.since ? '' : 'inv-muted', row.since ? fmtDate(row.since) : '—')));
    tr.appendChild(cell('inv-cell-go', chevron('inv-icon inv-chevron inv-chevron--group')));
    tr.addEventListener('click', function () {
      openGroups[row.key] = !isOpen;
      renderTable();
      var again = els.tbody.querySelector('[data-group-key="' + cssEscape(row.key) + '"] .inv-row__open');
      if (again) again.focus();
    });
    tr.dataset.groupKey = row.key;
    return tr;
  }
  function cssEscape(value) {
    return window.CSS && CSS.escape ? CSS.escape(value) : String(value).replace(/["\\]/g, '\\$&');
  }

  // ── Rendering ────────────────────────────────────────────────────────────────────────
  function stock() { return items.filter(onHand); }

  function renderGlance() {
    var all = stock();
    els.glance.replaceChildren();
    Object.keys(STATUSES).forEach(function (key) {
      var def = STATUSES[key];
      var n = all.filter(def.test).length;
      var active = state.status === key;
      var tile = el('button', 'inv-tile' + (def.tone && n ? ' inv-tile--' + def.tone : '') + (active ? ' is-active' : ''));
      tile.type = 'button';
      tile.setAttribute('aria-pressed', active ? 'true' : 'false');
      tile.appendChild(el('strong', '', String(n)));
      tile.appendChild(el('span', '', key === '' ? (n === 1 ? 'Line on hand' : 'Lines on hand') : def.label));
      tile.addEventListener('click', function () {
        state.status = key;
        render();
      });
      els.glance.appendChild(tile);
    });
  }

  function renderSegments() {
    var scoped = stock().filter(function (item) { return passes(item, { type: true }); });
    els.segments.replaceChildren();
    [['', 'All']].concat(Object.keys(TYPES).map(function (k) { return [k, TYPES[k].label]; })).forEach(function (pair) {
      var n = pair[0] ? scoped.filter(function (i) { return i.inventory_type === pair[0]; }).length : scoped.length;
      var btn = el('button', 'inv-segment');
      btn.type = 'button';
      btn.setAttribute('aria-pressed', state.type === pair[0] ? 'true' : 'false');
      btn.appendChild(document.createTextNode(pair[1]));
      btn.appendChild(el('span', 'inv-segment__count', String(n)));
      btn.addEventListener('click', function () {
        state.type = pair[0];
        render();
      });
      els.segments.appendChild(btn);
    });
  }

  function activeFilters() {
    var out = [];
    function add(key, label) { out.push({ keys: [].concat(key), label: label }); }
    if (state.status) add('status', STATUSES[state.status].label);
    if (state.type) add('type', 'Type: ' + TYPES[state.type].label);
    if (state.supplier) add('supplier', 'Supplier: ' + state.supplier);
    if (state.process) add('process', 'Process: ' + state.process);
    if (state.expFrom || state.expTo) add(['expFrom', 'expTo'], 'Expiry ' + rangeLabel(state.expFrom, state.expTo));
    if (state.purFrom || state.purTo) add(['purFrom', 'purTo'], 'Purchased ' + rangeLabel(state.purFrom, state.purTo));
    if (state.metaKey) add('metaKey', 'Has field: ' + state.metaKey);
    if (state.metaText.trim()) add('metaText', 'Details contain “' + state.metaText.trim() + '”');
    if (state.q.trim()) add('q', 'Search: “' + state.q.trim() + '”');
    return out;
  }
  function rangeLabel(from, to) {
    if (from && to) return fmtDate(from) + ' – ' + fmtDate(to);
    return from ? 'from ' + fmtDate(from) : 'to ' + fmtDate(to);
  }
  function renderActive() {
    var filters = activeFilters();
    els.active.replaceChildren();
    els.active.hidden = !filters.length;
    filters.forEach(function (filter) {
      var chip = el('button', 'inv-chip');
      chip.type = 'button';
      chip.appendChild(el('span', '', filter.label));
      chip.appendChild(icon('m7 7 10 10M17 7 7 17', 'inv-icon inv-chip__x'));
      chip.setAttribute('aria-label', 'Remove filter: ' + filter.label);
      chip.addEventListener('click', function () {
        filter.keys.forEach(function (k) { state[k] = ''; });
        syncControls();
        render();
      });
      els.active.appendChild(chip);
    });
    if (filters.length) {
      var clear = el('button', 'inv-clear', 'Clear filters');
      clear.type = 'button';
      clear.id = 'inv-view-clear-filters';
      clear.addEventListener('click', clearFilters);
      els.active.appendChild(clear);
    }
    var advanced = [state.expFrom || state.expTo, state.purFrom || state.purTo, state.metaKey, state.metaText.trim()].filter(Boolean).length;
    els.moreToggle.querySelector('[data-inv-more-count]').textContent = advanced ? String(advanced) : '';
    els.moreToggle.classList.toggle('has-value', !!advanced);
    els.supplier.classList.toggle('has-value', !!state.supplier);
    els.process.classList.toggle('has-value', !!state.process);
  }
  function clearFilters() {
    ['q', 'type', 'supplier', 'process', 'status', 'expFrom', 'expTo', 'purFrom', 'purTo', 'metaKey', 'metaText']
      .forEach(function (k) { state[k] = ''; });
    syncControls();
    render();
    els.search.focus();
  }

  function renderHead() {
    var tr = el('tr');
    COLUMNS.forEach(function (col) {
      var th = el('th', 'inv-th inv-th--' + col.key + (col.numeric ? ' inv-th--num' : ''));
      th.scope = 'col';
      if (!col.sortable) {
        if (col.label) th.textContent = col.label;
        else th.appendChild(el('span', 'inv-sr', 'Open'));
      } else {
        var active = state.sort === col.key;
        th.setAttribute('aria-sort', active ? (state.dir === 'asc' ? 'ascending' : 'descending') : 'none');
        var btn = el('button', 'inv-sort' + (active ? ' is-active' : ''));
        btn.type = 'button';
        btn.appendChild(document.createTextNode(col.label));
        btn.appendChild(icon(active && state.dir === 'desc' ? 'm6 9 6 6 6-6' : 'm6 15 6-6 6 6', 'inv-icon inv-sort__arrow'));
        btn.addEventListener('click', function () {
          if (state.sort === col.key) state.dir = state.dir === 'asc' ? 'desc' : 'asc';
          else { state.sort = col.key; state.dir = col.key === 'qty' ? 'desc' : 'asc'; }
          renderHead();
          renderTable();
        });
        th.appendChild(btn);
      }
      tr.appendChild(th);
    });
    els.thead.replaceChildren(tr);
  }

  function renderTable() {
    var all = stock();
    var filtered = all.filter(function (item) { return passes(item); });
    var rows = buildRows(filtered);

    els.loading.hidden = true;
    if (filtered.length === all.length) els.count.textContent = plural(all.length, 'line') + ' on hand';
    else els.count.textContent = filtered.length + ' of ' + plural(all.length, 'line');

    els.empty.replaceChildren();
    els.empty.hidden = !!filtered.length;
    els.tableWrap.hidden = !filtered.length;
    if (!filtered.length) {
      els.tbody.replaceChildren();
      els.empty.appendChild(el('strong', '', all.length ? 'No stock matches these filters' : 'No inventory on hand yet'));
      els.empty.appendChild(el('span', '', all.length
        ? 'Try a different search, or clear the filters to see everything on hand.'
        : 'Stock appears here as you add it or as batches produce it.'));
      if (all.length) {
        var clear = el('button', 'workspace-button', 'Clear filters');
        clear.type = 'button';
        clear.addEventListener('click', clearFilters);
        els.empty.appendChild(clear);
      }
      return;
    }

    var fragment = document.createDocumentFragment();
    rows.forEach(function (row) {
      if (row.kind === 'lot') { fragment.appendChild(lotTr(row, false)); return; }
      fragment.appendChild(groupTr(row));
      if (openGroups[row.key]) row.members.forEach(function (member) { fragment.appendChild(lotTr(member, true)); });
    });
    els.tbody.replaceChildren(fragment);
  }

  function render() {
    renderGlance();
    renderSegments();
    renderActive();
    renderTable();
    writeUrl();
  }

  // ── Filter controls ──────────────────────────────────────────────────────────────────
  function fillSelect(select, values, emptyLabel, current) {
    select.replaceChildren();
    var first = el('option', '', emptyLabel);
    first.value = '';
    select.appendChild(first);
    values.forEach(function (value) {
      var option = el('option', '', value);
      option.value = value;
      select.appendChild(option);
    });
    select.value = values.indexOf(current) >= 0 ? current : '';
    return select.value;
  }
  function unique(list, getter) {
    var seen = {};
    list.forEach(function (item) {
      var v = getter(item);
      if (v && String(v).trim()) seen[String(v).trim()] = true;
    });
    return Object.keys(seen).sort(function (a, b) { return a.localeCompare(b); });
  }
  function fillOptions() {
    var all = stock();
    state.supplier = fillSelect(els.supplier, unique(all, function (i) { return i.supplier; }), 'Supplier', state.supplier);
    state.process = fillSelect(els.process, unique(all, function (i) { return i.process_name; }), 'Process', state.process);
    var keys = {};
    all.forEach(function (item) {
      var extra = item.extra_data;
      if (extra && typeof extra === 'object' && !Array.isArray(extra)) Object.keys(extra).forEach(function (k) { keys[k] = true; });
    });
    state.metaKey = fillSelect(els.metaKey, Object.keys(keys).sort(), 'Any field', state.metaKey);
  }
  function syncControls() {
    els.search.value = state.q;
    els.supplier.value = state.supplier;
    els.process.value = state.process;
    els.expFrom.value = state.expFrom;
    els.expTo.value = state.expTo;
    els.purFrom.value = state.purFrom;
    els.purTo.value = state.purTo;
    els.metaKey.value = state.metaKey;
    els.metaText.value = state.metaText;
    els.group.setAttribute('aria-pressed', state.group ? 'true' : 'false');
  }
  function bind(node, key) {
    function onChange() {
      // `change` also fires when a typed-in field loses focus; re-rendering then would replace
      // the chip or button the pointer is already pressing, and the click would land on nothing.
      if (state[key] === node.value) return;
      state[key] = node.value;
      render();
    }
    node.addEventListener('input', onChange);
    node.addEventListener('change', onChange);
  }
  function wireControls() {
    bind(els.search, 'q');
    bind(els.supplier, 'supplier');
    bind(els.process, 'process');
    bind(els.expFrom, 'expFrom');
    bind(els.expTo, 'expTo');
    bind(els.purFrom, 'purFrom');
    bind(els.purTo, 'purTo');
    bind(els.metaKey, 'metaKey');
    bind(els.metaText, 'metaText');
    els.moreToggle.addEventListener('click', function () {
      var open = els.more.hidden;
      els.more.hidden = !open;
      els.moreToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) els.expFrom.focus();
    });
    els.group.addEventListener('click', function () {
      state.group = !state.group;
      try { window.localStorage.setItem(GROUP_PREF_KEY, state.group ? '1' : '0'); } catch (e) { /* private mode */ }
      syncControls();
      renderTable();
    });
  }

  // ── URL: filters and the open line survive a refresh and can be shared ───────────────
  function readUrl() {
    var params = new URLSearchParams(window.location.search);
    URL_KEYS.forEach(function (key) {
      var value = params.get(key);
      if (value != null) state[key] = value;
    });
    if (!Object.prototype.hasOwnProperty.call(STATUSES, state.status)) state.status = '';
    if (state.type && !TYPES[state.type]) state.type = '';
    try { state.group = window.localStorage.getItem(GROUP_PREF_KEY) === '1'; } catch (e) { /* private mode */ }
    if (state.expFrom || state.expTo || state.purFrom || state.purTo || state.metaKey || state.metaText) {
      els.more.hidden = false;
      els.moreToggle.setAttribute('aria-expanded', 'true');
    }
  }
  function writeUrl() {
    if (!root.isConnected) return;
    var params = new URLSearchParams();
    URL_KEYS.forEach(function (key) {
      var value = String(state[key] || '').trim();
      if (value) params.set(key, value);
    });
    var query = params.toString();
    var next = window.location.pathname + (query ? '?' + query : '');
    if (next !== window.location.pathname + window.location.search) {
      window.history.replaceState(window.history.state, '', next);
    }
  }

  // ── Detail panel ─────────────────────────────────────────────────────────────────────
  function fact(list, label, value) {
    if (value == null || value === '') return;
    var row = el('div', 'inv-fact');
    row.appendChild(el('dt', '', label));
    var dd = el('dd');
    if (value instanceof Node) dd.appendChild(value); else dd.textContent = String(value);
    row.appendChild(dd);
    list.appendChild(row);
  }
  function section(title) {
    var wrap = el('section', 'inv-drawer__section');
    wrap.appendChild(el('h3', '', title));
    return wrap;
  }
  function humanKey(key) {
    var text = String(key).replace(/_/g, ' ');
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function renderDrawer(item) {
    els.drawerTitle.textContent = item.name;
    els.drawerEyebrow.replaceChildren(typeBadge(item.inventory_type));
    els.drawerBody.replaceChildren();

    var hero = el('div', 'inv-drawer__hero');
    var figure = el('div', 'inv-drawer__figure');
    figure.appendChild(el('span', 'inv-drawer__label', 'On hand'));
    var amount = el('p', 'inv-drawer__qty');
    amount.appendChild(el('span', '', fmtQty(qty(item))));
    amount.appendChild(el('small', '', item.unit || ''));
    figure.appendChild(amount);
    hero.appendChild(figure);
    var spark = sparkline(item, 168, 52);
    if (spark) {
      var trend = el('div', 'inv-drawer__trend');
      trend.appendChild(spark);
      trend.appendChild(el('span', 'inv-drawer__label', plural(item.event_summary.quantity_history.length - 1, 'change') + ' recorded'));
      hero.appendChild(trend);
    }
    els.drawerBody.appendChild(hero);

    if (item.system_findings && item.system_findings.length) {
      var findings = el('ul', 'inv-drawer__findings');
      item.system_findings.forEach(function (finding) { findings.appendChild(el('li', '', finding.reason || finding.check_id)); });
      els.drawerBody.appendChild(findings);
    }

    var details = section('Details');
    var list = el('dl', 'inv-facts');
    fact(list, 'Supplier', item.supplier);
    fact(list, 'Batch number', item.supplier_batch_number);
    fact(list, 'Process', item.process_name);
    fact(list, 'Step', item.producing_step_name || item.source_step_name);
    fact(list, 'Purchased', fmtDate(item.purchase_date));
    if (item.expiry_date) fact(list, 'Expiry', expiryNode(datePart(item.expiry_date)));
    fact(list, 'Ready to use', fmtDateTime(item.ready_date_display));
    fact(list, 'Barcode', item.barcode);
    fact(list, 'Added', fmtDateTime(item.created_at));
    details.appendChild(list);
    els.drawerBody.appendChild(details);

    var inputs = item.extra_data && Array.isArray(item.extra_data.variable_inputs) ? item.extra_data.variable_inputs : [];
    inputs = inputs.filter(function (input) { return input && input.name; });
    if (inputs.length) {
      var made = section('Made from');
      var madeList = el('ul', 'inv-drawer__inputs');
      inputs.forEach(function (input) {
        var li = el('li');
        li.appendChild(el('span', '', input.name));
        li.appendChild(el('span', 'inv-qty', [input.quantity, input.unit].filter(function (v) { return v != null && v !== ''; }).join(' ')));
        madeList.appendChild(li);
      });
      made.appendChild(madeList);
      els.drawerBody.appendChild(made);
    }

    var extra = item.extra_data && typeof item.extra_data === 'object' ? item.extra_data : {};
    var metaKeys = Object.keys(extra).filter(function (key) {
      var value = extra[key];
      return !HIDDEN_META[key] && value != null && value !== '' && typeof value !== 'object';
    }).sort();
    if (metaKeys.length) {
      var more = section('More details');
      var moreList = el('dl', 'inv-facts');
      metaKeys.forEach(function (key) { fact(moreList, humanKey(key), extra[key]); });
      more.appendChild(moreList);
      els.drawerBody.appendChild(more);
    }

    var history = section('Audit history');
    history.classList.add('inv-audit-history');
    var historyBody = el('div', 'inv-audit-history__body');
    historyBody.appendChild(el('span', 'inv-muted', 'Loading history…'));
    history.appendChild(historyBody);
    els.drawerBody.appendChild(history);
    loadHistory(item.id, history, historyBody);

    els.drawerFoot.replaceChildren();
    els.drawerFoot.hidden = !canAdjust;
    if (canAdjust) {
      // inventory-adjust.js opens its edit sheet for any .inv-adj-btn and reads these attributes.
      var edit = el('button', 'workspace-button workspace-button--primary inv-adj-btn inv-drawer__edit', 'Edit this line');
      edit.type = 'button';
      edit.dataset.itemId = item.id;
      edit.dataset.name = item.name || '';
      edit.dataset.type = item.inventory_type || '';
      edit.dataset.current = String(item.quantity != null ? item.quantity : '');
      edit.dataset.unit = item.unit || '';
      edit.dataset.supplier = item.supplier || '';
      edit.dataset.batch = item.supplier_batch_number || '';
      edit.dataset.purchase = datePart(item.purchase_date);
      edit.dataset.expiry = datePart(item.expiry_date);
      edit.dataset.barcode = item.barcode || '';
      els.drawerFoot.appendChild(edit);
    }
  }

  function loadHistory(itemId, sectionEl, body) {
    var ascending = false;
    var events = [];
    function draw() {
      body.replaceChildren();
      if (!events.length) { body.appendChild(el('span', 'inv-muted', 'No history recorded yet.')); return; }
      if (events.length > 1) {
        var sort = el('button', 'inv-audit-sort', ascending ? 'Oldest first' : 'Newest first');
        sort.type = 'button';
        sort.addEventListener('click', function () { ascending = !ascending; draw(); });
        body.appendChild(sort);
      }
      var timeline = el('ol', 'inv-audit-timeline');
      (ascending ? events : events.slice().reverse()).forEach(function (event) {
        var li = el('li', 'inv-audit-timeline__item');
        li.appendChild(el('span', 'inv-audit-timeline__dot'));
        var content = el('div', 'inv-audit-timeline__content');
        content.appendChild(el('span', 'inv-audit-timeline__text', event.summary || event.event_type));
        if (event.diff_rows && event.diff_rows.length) {
          var diff = el('ul', 'inv-audit-diff');
          event.diff_rows.forEach(function (row) {
            var item = el('li', 'inv-audit-diff__row');
            item.appendChild(el('span', 'inv-audit-diff__label', row.label));
            if (row.before != null) item.appendChild(el('span', 'inv-audit-diff__before', row.before));
            if (row.before != null && row.after != null) item.appendChild(el('span', 'inv-audit-diff__arrow', '→'));
            if (row.after != null) item.appendChild(el('span', 'inv-audit-diff__after', row.after));
            diff.appendChild(item);
          });
          content.appendChild(diff);
        }
        var meta = [event.actor, fmtDateTime(event.at)].filter(Boolean).join(' · ');
        if (meta) content.appendChild(el('span', 'inv-audit-timeline__time', meta));
        li.appendChild(content);
        timeline.appendChild(li);
      });
      body.appendChild(timeline);
    }
    fetch('/api/core/entities/inventory_item/' + encodeURIComponent(itemId) + '/story', { credentials: 'same-origin' })
      .then(function (response) {
        if (!response.ok) throw new Error('story ' + response.status);
        return response.json();
      })
      .then(function (data) {
        if (state.item !== itemId || !sectionEl.isConnected) return;
        events = data.events || [];
        draw();
      })
      .catch(function () {
        if (state.item !== itemId || !sectionEl.isConnected) return;
        body.replaceChildren(el('span', 'inv-muted', 'Could not load history.'));
      });
  }

  function markSelected() {
    Array.prototype.forEach.call(els.tbody.querySelectorAll('.inv-row'), function (tr) {
      tr.classList.toggle('is-selected', !!state.item && tr.dataset.itemId === state.item);
    });
  }
  function findItem(id) {
    for (var i = 0; i < items.length; i++) if (items[i].id === id) return items[i];
    return null;
  }
  function openDrawer(id, trigger) {
    var item = findItem(id);
    if (!item) return;
    if (trigger) lastFocus = trigger;
    state.item = id;
    renderDrawer(item);
    els.drawer.hidden = false;
    els.backdrop.hidden = false;
    root.classList.add('inv-drawer-open');
    markSelected();
    writeUrl();
    els.drawer.querySelector('[data-inv-drawer-close]').focus();
  }
  function closeDrawer() {
    if (els.drawer.hidden) return;
    state.item = '';
    els.drawer.hidden = true;
    els.backdrop.hidden = true;
    root.classList.remove('inv-drawer-open');
    markSelected();
    writeUrl();
    if (lastFocus && lastFocus.isConnected) lastFocus.focus();
    lastFocus = null;
  }
  function wireDrawer() {
    els.drawer.querySelector('[data-inv-drawer-close]').addEventListener('click', closeDrawer);
    els.backdrop.addEventListener('click', closeDrawer);
    els.drawer.addEventListener('keydown', function (event) {
      if (event.key !== 'Tab') return;
      var focusable = els.drawer.querySelectorAll('button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])');
      if (!focusable.length) return;
      var first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    function onKey(event) {
      if (!root.isConnected) { document.removeEventListener('keydown', onKey); return; }
      // The edit sheet sits above the panel and has its own Cancel; Escape belongs to it first.
      if (event.key === 'Escape' && !els.drawer.hidden && !document.body.classList.contains('inv-edit-open')) closeDrawer();
    }
    document.addEventListener('keydown', onKey);
  }

  // ── Loading ──────────────────────────────────────────────────────────────────────────
  function showLoadError() {
    els.loading.hidden = true;
    els.tableWrap.hidden = true;
    els.empty.hidden = false;
    els.empty.replaceChildren(
      el('strong', '', 'Inventory could not be loaded'),
      el('span', '', 'Check your connection and try again.')
    );
    var retry = el('button', 'workspace-button', 'Try again');
    retry.type = 'button';
    retry.addEventListener('click', function () {
      els.empty.hidden = true;
      els.loading.hidden = false;
      load();
    });
    els.empty.appendChild(retry);
    els.count.textContent = '';
  }
  function load() {
    var seq = ++loadSeq;
    if (!window.CoreAPI || !window.CoreAPI.getInventory) { showLoadError(); return Promise.resolve(); }
    return window.CoreAPI.getInventory().then(function (response) {
      if (seq !== loadSeq || !root.isConnected) return;
      items = response.inventory_items || [];
      fillOptions();
      render();
      if (state.item) {
        var current = findItem(state.item);
        if (current && onHand(current)) {
          if (els.drawer.hidden) openDrawer(state.item, null); else { renderDrawer(current); markSelected(); }
        } else {
          closeDrawer();
          state.item = '';
          writeUrl();
        }
      }
    }).catch(function (error) {
      if (seq !== loadSeq || !root.isConnected) return;
      if (window.console) console.error('[inventory] load failed', error);
      if (!items.length) showLoadError();
    });
  }

  function start() {
    readUrl();
    syncControls();
    wireControls();
    wireDrawer();
    renderHead();
    // inventory-adjust.js calls this after a successful save from its edit sheet.
    window.invAdjustOnSave = function () { if (root.isConnected) load(); };
    if (window.LiveSync && typeof window.LiveSync.subscribe === 'function') {
      var off = window.LiveSync.subscribe({
        key: 'inventory-view',
        match: function (event) { return event.entity_type === 'inventory_item'; },
        onChange: function () { if (root.isConnected) load(); else off(); },
      });
    }
    load();
  }

  // On a full page load this tag runs before core-api.js (which sits at the end of the shell).
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
