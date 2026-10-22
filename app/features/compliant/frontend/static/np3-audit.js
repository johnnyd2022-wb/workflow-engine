// NP1/NP2/NP3 food safety (plan 2.4b): am I ready for my verifier, and what do I record next?
// One script for both views: Summary (readiness, verification, what needs doing) and Checks
// (every check by section, with search and readiness filters). The server works out every
// state. A check that sits in two sections is one check: counts, filters and searches use
// each check once.
(function () {
  'use strict';

  function init() {
  var root = document.querySelector('[data-np3-audit-root]');
  if (!root || root.dataset.bound === '1') return;
  root.dataset.bound = '1';
  var NP = root.dataset.programmeShort || 'NP3';
  var VIEW = root.dataset.np3View || 'summary';
  var CHECK = '/compliant/nz-alcohol/np3-audit/check/';
  var CHECKS = '/compliant/nz-alcohol/food-safety/checks';

  var error = root.querySelector('[data-np3-error]');
  var facts = root.querySelector('[data-np3-health-cards]');
  var coreLine = root.querySelector('[data-np3-core-stats]');
  var queue = root.querySelector('[data-np3-work-queue]');
  var queueItems = root.querySelector('[data-np3-work-queue-items]');
  var prep = root.querySelector('[data-np3-preparation]');
  var filters = root.querySelector('[data-np3-filters]');
  var sections = root.querySelector('[data-np3-category-tabs]');
  var listRoot = root.querySelector('[data-np3-categories]');
  var heading = root.querySelector('[data-np3-active-category]');
  var countLine = root.querySelector('[data-np3-register-count]');
  var search = root.querySelector('[data-np3-check-search]');

  var audit = null;
  var unique = [];
  var params = new URLSearchParams(window.location.search);
  var FILTERS = ['ok', 'attention', 'overdue', 'due-soon', 'remediation'];
  var activeFilter = FILTERS.indexOf(params.get('filter')) !== -1 ? params.get('filter') : 'all';
  var activeCategory = params.get('section');
  var query = '';

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
  function matchesFilter(row, filter) {
    if (filter === 'ok') return row.state === 'ready';
    if (filter === 'attention') return row.state === 'attention' || row.state === 'missing';
    if (filter === 'overdue') return isOverdue(row);
    if (filter === 'due-soon') return isDueSoon(row);
    if (filter === 'remediation') return Boolean(row.open_remediation);
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

  // The five readiness figures. On Summary each one opens Checks filtered to it; on Checks they
  // are the filter row.
  function readiness() {
    var h = audit.health || {};
    var ready = Number(h.ok || 0), total = ready + Number(h.needs_attention || 0);
    var percent = total ? Math.round((ready / total) * 100) : 0;
    return [
      ['ok', 'Ready', ready + ' of ' + total, percent + '% of checks have current proof', 'good', ready],
      ['attention', 'Needs evidence', String(h.needs_attention || 0), 'Missing or out-of-date proof', h.needs_attention ? 'warn' : '', Number(h.needs_attention || 0)],
      ['overdue', 'Overdue reviews', String(h.overdue || 0), 'Past their review date', h.overdue ? 'bad' : '', Number(h.overdue || 0)],
      ['due-soon', 'Due in 30 days', String(h.due_soon || 0), 'Reviews coming up', '', Number(h.due_soon || 0)],
      ['remediation', 'Follow-ups open', String(h.open_remediation || 0), 'Logged issues not closed', h.open_remediation ? 'bad' : '', Number(h.open_remediation || 0)],
    ];
  }

  function renderFacts() {
    facts.replaceChildren();
    readiness().forEach(function (f) {
      facts.append(el('a', { className: 'np3-fact' + (f[4] ? ' np3-fact--' + f[4] : ''), href: CHECKS + '?filter=' + f[0], 'data-np3-filter': f[0] }, [
        el('span', { className: 'np3-fact__label', text: f[1] }),
        el('strong', { className: 'np3-fact__value', text: f[2] }),
        el('span', { className: 'np3-fact__note', text: f[3] }),
      ]));
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
    var steps = audit.guided_steps || [];
    var urgent = unique.filter(function (r) { var k = status(r).text; return k === 'Follow-up open' || k === 'Overdue'; })
      .concat(unique.filter(function (r) { return r.state === 'missing'; }));
    var shown = 0;
    steps.forEach(function (step) {
      var href = step.opens === 'check'
        ? CHECK + encodeURIComponent(step.control_id)
        : CHECKS + '?filter=' + encodeURIComponent(step.filter || 'all') + (step.category_key ? '&section=' + encodeURIComponent(step.category_key) : '');
      queueItems.append(el('li', { className: 'np3-next__item np3-next__item--' + (step.severity || 'attention') }, [
        el('div', {}, [el('strong', { text: step.title }), el('span', { text: step.description })]),
        el('a', { href: href, text: step.opens === 'check' ? 'Open check' : 'Show them' }),
      ]));
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

  function checkRow(row) {
    var st = status(row);
    var link = el('a', { className: 'np3-check np3-check--' + st.key, href: CHECK + encodeURIComponent(row.control_id), 'data-control-id': row.control_id });
    var last = lastRecorded(row);
    var fromCore = !last && Number(row.derived_evidence_count || 0) > 0;
    link.append(
      el('span', { className: 'np3-check__main' }, [
        el('strong', { className: 'np3-check__title', text: row.topic || row.control_title || NP + ' check' }),
        el('span', { className: 'np3-check__summary', text: row.requirement_summary || '' }),
      ]),
      el('span', { className: 'np3-check__meta', text: last ? 'Last ' + shortDate(last) + (row.review_due_date ? ' · next ' + shortDate(row.review_due_date) : '') : fromCore ? 'Shown by Production records' : 'Nothing recorded yet' }),
      el('span', { className: 'np3-tag np3-tag--' + st.key, text: st.text })
    );
    return link;
  }

  function setUrl() {
    var q = new URLSearchParams();
    if (activeFilter !== 'all') q.set('filter', activeFilter);
    else if (activeCategory) q.set('section', activeCategory);
    history.replaceState(null, '', window.location.pathname + (q.toString() ? '?' + q.toString() : ''));
  }

  function renderFilters() {
    filters.replaceChildren();
    var options = [['all', 'All checks', unique.length, '']].concat(readiness().map(function (f) {
      return [f[0], f[1], unique.filter(function (r) { return matchesFilter(r, f[0]); }).length, f[4]];
    }));
    options.forEach(function (f) {
      var on = activeFilter === f[0];
      var b = el('button', { type: 'button', className: 'np3-chip' + (f[3] ? ' np3-chip--' + f[3] : '') + (on ? ' is-active' : ''), 'aria-pressed': String(on), 'data-np3-filter': f[0] }, [
        el('span', { text: f[1] }), el('strong', { text: String(f[2]) }),
      ]);
      b.addEventListener('click', function () { activeFilter = f[0]; query = ''; search.value = ''; setUrl(); renderChecks(); });
      filters.append(b);
    });
  }

  function renderChecks() {
    var byCategory = {};
    (audit.categories || []).forEach(function (c) { byCategory[c.key] = []; });
    (audit.rows || []).forEach(function (row) { (byCategory[row.category_key] = byCategory[row.category_key] || []).push(row); });
    if (!activeCategory || !byCategory[activeCategory]) activeCategory = (audit.categories || [])[0] && audit.categories[0].key;
    renderFilters();
    var narrowing = !!query || activeFilter !== 'all';
    sections.hidden = narrowing;
    sections.replaceChildren();
    (audit.categories || []).forEach(function (category, index) {
      var rows = byCategory[category.key] || [];
      var todo = rows.filter(function (r) { return status(r).key !== 'good'; }).length;
      var active = category.key === activeCategory;
      var b = el('button', { type: 'button', role: 'tab', id: 'np3-category-tab-' + index, className: 'np3-section-tab' + (active ? ' is-active' : ''), 'aria-selected': String(active), 'aria-controls': 'np3-category-panel' }, [
        el('strong', { text: category.title }),
        el('span', { className: todo ? 'np3-section-tab__todo' : 'np3-section-tab__done', text: todo ? todo + ' to do' : 'All ready' }),
      ]);
      b.addEventListener('click', function () { activeCategory = category.key; setUrl(); renderChecks(); });
      sections.append(b);
    });
    listRoot.replaceChildren();
    var panel = el('div', { id: 'np3-category-panel', role: 'tabpanel' });
    var rows;
    if (narrowing) {
      rows = unique.filter(matchesSearch).filter(function (r) { return matchesFilter(r, activeFilter); });
      var label = (readiness().find(function (f) { return f[0] === activeFilter; }) || [])[1];
      heading.textContent = query ? 'Search results' : label || 'Matching checks';
      countLine.textContent = plural(rows.length, 'check') + (query ? ' match "' + search.value.trim() + '"' : '') + '.';
    } else {
      var category = (audit.categories || []).find(function (c) { return c.key === activeCategory; }) || {};
      rows = byCategory[activeCategory] || [];
      var todo = rows.filter(function (r) { return status(r).key !== 'good'; }).length;
      heading.textContent = category.title || 'Every check';
      countLine.textContent = plural(rows.length, 'check') + (todo ? ' · ' + todo + ' to do' : ' · all ready');
    }
    panel.append(rows.length
      ? el('div', { className: 'np3-check-list' }, rows.map(checkRow))
      : el('p', { className: 'np3-empty', text: query ? 'No ' + NP + ' checks match this search.' : 'Nothing here right now.' }));
    listRoot.append(panel);
  }

  function render() {
    if (!audit) return;
    var seen = {};
    unique = (audit.rows || []).filter(function (row) {
      if (seen[row.control_id]) return false;
      seen[row.control_id] = true;
      return true;
    });
    if (VIEW === 'summary') {
      renderFacts();
      renderCore();
      renderQueue();
      prep.replaceChildren.apply(prep, (audit.preparation_items || []).map(function (t) { return el('li', { text: t }); }));
    } else {
      renderChecks();
    }
    root.setAttribute('aria-busy', 'false');
  }

  if (search) search.addEventListener('input', function () { query = search.value.trim().toLowerCase(); if (query) activeFilter = 'all'; renderChecks(); });
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
