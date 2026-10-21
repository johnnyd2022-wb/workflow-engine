// NP1/NP2/NP3 food safety register (plan 2.4b): am I ready for my verifier, and what do I
// record next? The server works out every state; this page lays it out. A check that sits in
// two sections is one check: counts, filters and searches use each check once.
(function () {
  'use strict';

  function init() {
  var root = document.querySelector('[data-np3-audit-root]');
  if (!root || root.dataset.bound === '1') return;
  root.dataset.bound = '1';
  var NP = root.dataset.programmeShort || 'NP3';
  var CHECK = '/compliant/nz-alcohol/np3-audit/check/';

  var error = root.querySelector('[data-np3-error]');
  var facts = root.querySelector('[data-np3-health-cards]');
  var coreLine = root.querySelector('[data-np3-core-stats]');
  var sections = root.querySelector('[data-np3-category-tabs]');
  var listRoot = root.querySelector('[data-np3-categories]');
  var heading = root.querySelector('[data-np3-active-category]');
  var countLine = root.querySelector('[data-np3-register-count]');
  var queue = root.querySelector('[data-np3-work-queue]');
  var queueItems = root.querySelector('[data-np3-work-queue-items]');
  var packCards = root.querySelector('[data-np3-pack-cards]');
  var search = root.querySelector('[data-np3-check-search]');
  var prep = root.querySelector('[data-np3-preparation]');

  var audit = null;
  var unique = [];
  var activeCategory = null;
  var activeFilter = 'all';
  var query = '';
  var FILTERS = ['ok', 'attention', 'overdue', 'due-soon', 'remediation'];
  var wanted = new URLSearchParams(window.location.search).get('filter');
  if (FILTERS.indexOf(wanted) !== -1) activeFilter = wanted;

  // CONCEPT ONLY: three page styles behind one switch; removed once one is picked.
  function readStyle() {
    var q = new URLSearchParams(window.location.search).get('style');
    if (q === '1' || q === '2' || q === '3') return q;
    try { var s = window.localStorage.getItem('np3.style'); if (s === '1' || s === '2' || s === '3') return s; } catch (_) {}
    return '1';
  }
  function style() { return root.getAttribute('data-np3-style') || '1'; }
  function setStyle(s) {
    root.setAttribute('data-np3-style', s);
    try { window.localStorage.setItem('np3.style', s); } catch (_) {}
    root.querySelectorAll('[data-np3-style-pick] [data-style]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-style') === s)); });
    render();
  }
  root.querySelectorAll('[data-np3-style-pick] [data-style]').forEach(function (b) {
    b.addEventListener('click', function () { setStyle(b.getAttribute('data-style')); });
  });

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (attrs[k] == null) return;
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'className') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (k) { if (k) n.append(k); });
    return n;
  }
  function showError(message) { error.textContent = message || ''; error.hidden = !message; }
  function today() { var d = new Date(); d.setHours(0, 0, 0, 0); return d; }
  function asDate(iso) { return iso ? new Date(String(iso).slice(0, 10) + 'T00:00:00') : null; }
  function shortDate(iso) {
    var d = asDate(iso);
    if (!d || isNaN(d)) return '';
    var opts = { day: 'numeric', month: 'short' };
    if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
    return d.toLocaleDateString('en-NZ', opts);
  }
  function plural(n, word, many) { return n + ' ' + (n === 1 ? word : (many || word + 's')); }

  function isOverdue(row) { var d = asDate(row.review_due_date); return !!d && d < today(); }
  function isDueSoon(row) {
    var d = asDate(row.review_due_date);
    if (!d || d < today()) return false;
    var limit = today(); limit.setDate(limit.getDate() + 30);
    return d <= limit;
  }
  function matchesFilter(row) {
    if (activeFilter === 'ok') return row.state === 'ready';
    if (activeFilter === 'attention') return row.state === 'attention' || row.state === 'missing';
    if (activeFilter === 'overdue') return isOverdue(row);
    if (activeFilter === 'due-soon') return isDueSoon(row);
    if (activeFilter === 'remediation') return Boolean(row.open_remediation);
    return true;
  }
  function matchesSearch(row) {
    if (!query) return true;
    return [row.topic, row.control_title, row.control_id, row.requirement_summary].some(function (v) {
      return String(v || '').toLowerCase().indexOf(query) !== -1;
    });
  }
  // One status in words for a check, worst first: what a verifier would pick up on.
  function status(row) {
    if (row.open_remediation) return { key: 'bad', text: 'Follow-up open' };
    if (isOverdue(row)) return { key: 'bad', text: 'Overdue' };
    if (row.state === 'missing') return { key: 'warn', text: 'Needs evidence' };
    if (row.state === 'attention') return { key: 'warn', text: row.guidance_update_required ? 'Guidance changed' : 'Needs attention' };
    if (isDueSoon(row)) return { key: 'warn', text: 'Due ' + shortDate(row.review_due_date) };
    return { key: 'good', text: 'Ready' };
  }
  function lastRecorded(row) {
    var dates = (row.history || []).map(function (h) { return h.created_at; }).filter(Boolean).sort();
    return dates.length ? dates[dates.length - 1] : row.latest_recorded_at || null;
  }

  // Twelve months of a check's records, oldest first: recorded, missed (its review had fallen
  // due and nothing came in), or nothing expected. Built from the rows' own history.
  function strip(row, months) {
    var now = new Date();
    var recorded = {};
    (row.history || []).forEach(function (h) { if (h.created_at) recorded[String(h.created_at).slice(0, 7)] = (recorded[String(h.created_at).slice(0, 7)] || 0) + 1; });
    var due = row.review_due_date ? String(row.review_due_date).slice(0, 7) : null;
    var cells = [];
    for (var i = months - 1; i >= 0; i -= 1) {
      var d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      var key = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
      var state = recorded[key] ? 'done' : (due && key >= due && isOverdue(row) ? 'missed' : 'none');
      var label = d.toLocaleDateString('en-NZ', { month: 'short', year: 'numeric' }) + ': ' + (state === 'done' ? plural(recorded[key], 'record') : state === 'missed' ? 'review overdue' : 'nothing due');
      cells.push(el('span', { className: 'np3-strip__cell np3-strip__cell--' + state, title: label }));
    }
    return el('span', { className: 'np3-strip', role: 'img', 'aria-label': 'Last ' + months + ' months of records' }, cells);
  }

  function checkRow(row) {
    var st = status(row);
    var link = el('a', { className: 'np3-check np3-check--' + st.key, href: CHECK + encodeURIComponent(row.control_id), 'data-control-id': row.control_id });
    var main = el('span', { className: 'np3-check__main' }, [
      el('strong', { className: 'np3-check__title', text: row.topic || row.control_title || NP + ' check' }),
      el('span', { className: 'np3-check__summary', text: row.requirement_summary || '' }),
    ]);
    var last = lastRecorded(row);
    var fromCore = !last && Number(row.derived_evidence_count || 0) > 0;
    var meta = el('span', { className: 'np3-check__meta', text: last ? 'Last ' + shortDate(last) + (row.review_due_date ? ' · next ' + shortDate(row.review_due_date) : '') : fromCore ? 'Shown by Production records' : 'Nothing recorded yet' });
    link.append(main, strip(row, 12), meta, el('span', { className: 'np3-tag np3-tag--' + st.key, text: st.text }));
    return link;
  }

  function renderFacts() {
    facts.replaceChildren();
    var h = audit.health || {};
    var ready = Number(h.ok || 0), total = ready + Number(h.needs_attention || 0);
    var percent = total ? Math.round((ready / total) * 100) : 0;
    var items = [
      ['ok', 'Ready', ready + ' of ' + total, percent + '% of checks have current proof', 'good'],
      ['attention', 'Needs evidence', String(h.needs_attention || 0), 'Missing or out-of-date proof', (h.needs_attention ? 'warn' : '')],
      ['overdue', 'Overdue reviews', String(h.overdue || 0), 'Past their review date', (h.overdue ? 'bad' : '')],
      ['due-soon', 'Due in 30 days', String(h.due_soon || 0), 'Reviews coming up', ''],
      ['remediation', 'Follow-ups open', String(h.open_remediation || 0), 'Logged issues not closed', (h.open_remediation ? 'bad' : '')],
    ];
    items.forEach(function (f) {
      var b = el('button', { type: 'button', className: 'np3-fact' + (f[4] ? ' np3-fact--' + f[4] : '') + (activeFilter === f[0] ? ' is-active' : ''), 'aria-pressed': String(activeFilter === f[0]), 'data-np3-filter': f[0] }, [
        el('span', { className: 'np3-fact__label', text: f[1] }),
        el('strong', { className: 'np3-fact__value', text: f[2] }),
        el('span', { className: 'np3-fact__note', text: f[3] }),
      ]);
      b.addEventListener('click', function () { activeFilter = activeFilter === f[0] ? 'all' : f[0]; render(); });
      facts.append(b);
    });
  }

  function renderCore() {
    var stats = audit.core_evidence || {};
    var live = stats.live_np3_evidence || {};
    coreLine.replaceChildren(
      document.createTextNode('From Production: '),
      el('a', { href: '/core/inventory/live', text: plural(live.dag_traced_final_products || 0, 'traceable batch', 'traceable batches') }),
      document.createTextNode(' · '),
      el('a', { href: '/core/executions/live', text: plural(stats.completed_core_steps_with_captured_data || 0, 'production record') }),
      document.createTextNode(' · '),
      el('a', { href: '/core/inventory/live', text: plural(live.supplier_identified_materials || 0, 'material') + ' with a supplier' })
    );
  }

  function renderQueue() {
    queueItems.replaceChildren();
    var steps = (audit.guided_steps || []).slice();
    var urgent = unique.filter(function (r) { var k = status(r).text; return k === 'Follow-up open' || k === 'Overdue'; })
      .concat(unique.filter(function (r) { return r.state === 'missing'; }));
    var shown = 0;
    steps.forEach(function (step) {
      var item = el('li', { className: 'np3-next__item np3-next__item--' + (step.severity || 'attention') });
      var action;
      if (step.opens === 'check') action = el('a', { href: CHECK + encodeURIComponent(step.control_id), text: 'Open check' });
      else {
        action = el('button', { type: 'button', className: 'np3-link', text: 'Show them' });
        action.addEventListener('click', function () { activeFilter = step.filter || 'all'; if (step.category_key) activeCategory = step.category_key; query = ''; search.value = ''; render(); listRoot.scrollIntoView({ behavior: 'smooth', block: 'start' }); });
      }
      item.append(el('div', {}, [el('strong', { text: step.title }), el('span', { text: step.description })]), action);
      queueItems.append(item);
      shown += 1;
    });
    urgent.forEach(function (row) {
      if (shown >= 5 || steps.some(function (s) { return s.control_id === row.control_id; })) return;
      var st = status(row);
      queueItems.append(el('li', { className: 'np3-next__item np3-next__item--' + (st.key === 'bad' ? 'high' : 'attention') }, [
        el('div', {}, [el('strong', { text: row.topic }), el('span', { text: st.text === 'Needs evidence' ? 'No proof recorded for this check yet.' : st.text + (row.review_due_date ? ' since ' + shortDate(row.review_due_date) : '') + '.' })]),
        el('a', { href: CHECK + encodeURIComponent(row.control_id), text: 'Open check' }),
      ]));
      shown += 1;
    });
    queue.hidden = !shown;
  }

  // The five topics a verifier always covers (MPI NP3 guidance), each with its own checks.
  var MANDATORY = [
    ['Competency and training', ['staff-competency']],
    ['Cleaning', ['cleaning-and-hygiene', 'food-contact-equipment-cleaning', 'cleaning-chemicals-food-safe']],
    ['Personal hygiene and health', ['personal-hygiene', 'health-and-sickness']],
    ['Sourcing and tracing', ['suppliers-and-purchasing', 'receiving-food', 'trace-and-recall']],
    ['Process controls', ['time-temperature-processing', 'storage-stock-rotation', 'calibration', 'cross-contamination']],
  ];
  function renderPack() {
    packCards.replaceChildren();
    var byId = {};
    unique.forEach(function (r) { byId[r.control_id] = r; });
    MANDATORY.forEach(function (topic) {
      var rows = topic[1].map(function (id) { return byId[id]; }).filter(Boolean);
      if (!rows.length) return;
      var ready = rows.filter(function (r) { return status(r).key === 'good'; }).length;
      var card = el('article', { className: 'np3-pack__card' + (ready === rows.length ? ' np3-pack__card--ready' : '') });
      card.append(el('div', { className: 'np3-pack__head' }, [
        el('h3', { text: topic[0] }),
        el('span', { className: 'np3-tag np3-tag--' + (ready === rows.length ? 'good' : 'warn'), text: ready + ' of ' + rows.length + ' ready' }),
      ]));
      var proof = ((rows[0].evidence_playbook || {}).proof || []).slice(0, 3);
      if (proof.length) {
        card.append(el('p', { className: 'np3-pack__label', text: 'Be ready to show' }));
        card.append(el('ul', { className: 'np3-pack__proof' }, proof.map(function (p) { return el('li', { text: p }); })));
      }
      card.append(el('ul', { className: 'np3-pack__checks' }, rows.map(function (r) {
        var st = status(r);
        return el('li', {}, [el('a', { href: CHECK + encodeURIComponent(r.control_id), text: r.topic }), el('span', { className: 'np3-tag np3-tag--' + st.key, text: st.text })]);
      })));
      packCards.append(card);
    });
  }

  function renderSections(byCategory) {
    sections.replaceChildren();
    (audit.categories || []).forEach(function (category, index) {
      var rows = byCategory[category.key] || [];
      var todo = rows.filter(function (r) { return status(r).key !== 'good'; }).length;
      var active = category.key === activeCategory && !query && activeFilter === 'all';
      var b = el('button', { type: 'button', role: 'tab', id: 'np3-category-tab-' + index, className: 'np3-section-tab' + (active ? ' is-active' : ''), 'aria-selected': String(active), 'aria-controls': 'np3-category-panel' }, [
        el('strong', { text: category.title }),
        el('span', { className: todo ? 'np3-section-tab__todo' : 'np3-section-tab__done', text: todo ? todo + ' to do' : 'All ready' }),
      ]);
      b.addEventListener('click', function () { activeCategory = category.key; activeFilter = 'all'; query = ''; search.value = ''; render(); });
      sections.append(b);
    });
  }

  function renderList(byCategory) {
    listRoot.replaceChildren();
    var category = (audit.categories || []).find(function (c) { return c.key === activeCategory; });
    var narrowing = !!query || activeFilter !== 'all';
    var panel = el('div', { id: 'np3-category-panel', role: 'tabpanel' });
    function list(rows) { return el('div', { className: 'np3-check-list' }, rows.map(checkRow)); }
    if (narrowing) {
      var rows = unique.filter(matchesSearch).filter(matchesFilter);
      var label = activeFilter !== 'all' ? (facts.querySelector('[data-np3-filter="' + activeFilter + '"] .np3-fact__label') || {}).textContent : '';
      heading.textContent = query ? 'Search results' : label || 'Matching checks';
      countLine.textContent = plural(rows.length, 'check') + (query ? ' match "' + search.value.trim() + '"' : '') + '.';
      panel.append(rows.length ? list(rows) : el('p', { className: 'np3-empty', text: query ? 'No ' + NP + ' checks match this search.' : 'Nothing here right now.' }));
      if (activeFilter !== 'all') {
        var clear = el('button', { type: 'button', className: 'np3-link', text: 'Show every check' });
        clear.addEventListener('click', function () { activeFilter = 'all'; render(); });
        panel.append(clear);
      }
    } else if (style() === '2') {
      // Rhythm: every section at once, each check with its year of records.
      heading.textContent = 'Every check, month by month';
      countLine.textContent = plural(unique.length, 'check') + ' · each square is a month: recorded, review overdue, or nothing due.';
      (audit.categories || []).forEach(function (c) {
        var rows = byCategory[c.key] || [];
        if (!rows.length) return;
        panel.append(el('h3', { className: 'np3-group-title', text: c.title }), list(rows));
      });
    } else {
      var rowsIn = byCategory[category.key] || [];
      heading.textContent = category.title;
      var todo = rowsIn.filter(function (r) { return status(r).key !== 'good'; }).length;
      countLine.textContent = plural(rowsIn.length, 'check') + (todo ? ' · ' + todo + ' to do' : ' · all ready');
      panel.append(list(rowsIn));
    }
    listRoot.append(panel);
  }

  function render() {
    if (!audit) return;
    var byCategory = {};
    var seen = {};
    unique = [];
    (audit.categories || []).forEach(function (c) { byCategory[c.key] = []; });
    (audit.rows || []).forEach(function (row) {
      (byCategory[row.category_key] = byCategory[row.category_key] || []).push(row);
      if (!seen[row.control_id]) { seen[row.control_id] = true; unique.push(row); }
    });
    if (!activeCategory || !byCategory[activeCategory]) activeCategory = (audit.categories || [])[0] && audit.categories[0].key;
    renderFacts();
    renderCore();
    renderQueue();
    renderPack();
    renderSections(byCategory);
    renderList(byCategory);
    prep.replaceChildren.apply(prep, (audit.preparation_items || []).map(function (t) { return el('li', { text: t }); }));
    root.setAttribute('aria-busy', 'false');
  }

  search.addEventListener('input', function () { query = search.value.trim().toLowerCase(); render(); });
  setStyle(readStyle());
  fetch('/api/compliant/np3-audit', { credentials: 'include', headers: { Accept: 'application/json' } }).then(function (response) {
    if (!response.ok) throw new Error('Could not load the ' + NP + ' register');
    return response.json();
  }).then(function (data) { audit = data; render(); }).catch(function (err) {
    root.setAttribute('aria-busy', 'false');
    showError(err.message || 'Could not load the ' + NP + ' register');
  });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  document.addEventListener('htmx:afterSwap', init);
}());
