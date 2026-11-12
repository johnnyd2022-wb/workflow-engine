/* Sales › Margins (live-cogs 8.1f-2): profit per product per month. Binds to its page root on
   every arrival (boosted navigation swaps #page-content and keeps window). Text via textContent. */
(function () {
  'use strict';
  var API = '/api/core/costing/margins';
  var money = new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' });
  var STATUS = { estimated: 'Includes estimated cost', unknown: 'Cost not known yet', partial: 'Cost partly known' };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function num(v) { return v == null ? null : Number(v); }
  function fmt(v) { return v == null ? '—' : money.format(Number(v)); }
  function pct(v) { return v == null ? '—' : Number(v).toFixed(1) + '%'; }
  function units(v) { var n = Number(v); return (Math.round(n * 100) / 100).toLocaleString('en-NZ'); }
  function monthLabel(ym) {
    var p = ym.split('-');
    return new Date(Number(p[0]), Number(p[1]) - 1, 1).toLocaleDateString('en-NZ', { month: 'short', year: 'numeric' });
  }
  /* Range totals for one product (or all). A month with no figure is left out and counted, so the
     known months still add up and the page says how many are missing; nothing is shown as $0. */
  function total(rows) {
    var t = { units: 0, revenue: null, cost: null, duty: null, margin: null, statuses: [], dutyTracked: true,
      months: 0, missingRevenue: 0, missingCost: 0, marginRevenue: 0 };
    var all = {}, noRevenue = {}, noCost = {};
    function plus(a, b) { return b == null ? a : (a || 0) + b; }
    rows.forEach(function (r) {
      t.units += Number(r.units);
      all[r.month] = true;
      if (r.revenue == null) noRevenue[r.month] = true;
      if (r.cost == null) noCost[r.month] = true;
      t.revenue = plus(t.revenue, num(r.revenue));
      t.cost = plus(t.cost, num(r.cost));
      if (r.duty_tracked) t.duty = plus(t.duty, num(r.duty)); else t.dutyTracked = false;
      if (r.margin != null) { t.margin = plus(t.margin, num(r.margin)); t.marginRevenue += num(r.revenue) || 0; }
      t.statuses.push(r.cost_status);
    });
    // Calendar months, not product-months: "revenue from 1 of 6 months".
    t.months = Object.keys(all).length;
    t.missingRevenue = Object.keys(noRevenue).length;
    t.missingCost = Object.keys(noCost).length;
    // The margin % is over the months that have a margin, so a missing month can't skew it.
    t.percent = t.margin != null && t.marginRevenue ? (t.margin / t.marginRevenue) * 100 : null;
    t.status = ['unknown', 'partial', 'estimated'].filter(function (s) { return t.statuses.indexOf(s) >= 0; })[0] || 'actual';
    return t;
  }

  function bind() {
    var root = document.querySelector('[data-margins-root]');
    if (!root || root.getAttribute('data-bound') === '1') return;
    root.setAttribute('data-bound', '1');
    var q = function (s) { return root.querySelector(s); };
    var els = {
      form: q('[data-margins-range]'), from: q('#mg-from'), to: q('#mg-to'), error: q('[data-margins-error]'),
      summary: q('[data-margins-summary]'), note: q('[data-margins-note]'), list: q('[data-margins-list]'),
      empty: q('[data-margins-empty]'),
    };
    var seq = 0;
    var params = new URLSearchParams(location.search);
    if (params.get('from')) els.from.value = params.get('from');
    if (params.get('to')) els.to.value = params.get('to');

    els.form.addEventListener('submit', function (e) {
      e.preventDefault();
      var url = new URL(location.href);
      url.searchParams.set('from', els.from.value);
      url.searchParams.set('to', els.to.value);
      history.replaceState(history.state, '', url);
      load();
    });

    function load() {
      var mine = ++seq;
      root.setAttribute('aria-busy', 'true');
      els.error.hidden = true;
      var qs = [];
      if (els.from.value) qs.push('from=' + encodeURIComponent(els.from.value));
      if (els.to.value) qs.push('to=' + encodeURIComponent(els.to.value));
      fetch(API + (qs.length ? '?' + qs.join('&') : ''), { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || 'Margins couldn’t load'); return d; }); })
        .then(function (body) { if (mine === seq) render(body); })
        .catch(function (err) { if (mine !== seq) return; els.error.textContent = err.message; els.error.hidden = false; })
        .finally(function () { if (mine === seq) root.setAttribute('aria-busy', 'false'); });
    }

    function render(body) {
      if (!els.from.value) els.from.value = body.from;
      if (!els.to.value) els.to.value = body.to;
      var rows = body.rows || [];
      els.list.replaceChildren();
      els.empty.hidden = rows.length > 0;
      els.summary.hidden = rows.length === 0;
      els.note.hidden = true;
      if (!rows.length) return;
      summary(total(rows), rows);
      var byProduct = {};
      rows.forEach(function (r) { (byProduct[r.product] = byProduct[r.product] || []).push(r); });
      Object.keys(byProduct)
        .map(function (name) { return { name: name, rows: byProduct[name], t: total(byProduct[name]) }; })
        .sort(function (a, b) { return (b.t.revenue || 0) - (a.t.revenue || 0); })
        .forEach(function (p) { els.list.appendChild(product(p)); });
    }

    function figure(label, value, extra) {
      var f = el('div', 'mg-figure');
      f.appendChild(el('span', 'mg-figure__label', label));
      f.appendChild(el('span', 'mg-figure__value', value));
      if (extra) f.appendChild(el('span', 'mg-figure__extra', extra));
      return f;
    }

    function summary(t, rows) {
      function of(missing) { return missing ? 'Complete for ' + (t.months - missing) + ' of ' + t.months + ' months' : null; }
      els.summary.replaceChildren(
        figure('Revenue', fmt(t.revenue), of(t.missingRevenue) || 'ex GST'),
        figure('Production cost', fmt(t.cost), of(t.missingCost)),
        figure('Duty', t.dutyTracked ? fmt(t.duty) : 'Not tracked'),
        figure('Margin', fmt(t.margin), t.percent == null ? null : pct(t.percent))
      );
      var notes = [];
      if (t.status !== 'actual') notes.push(STATUS[t.status] + ' — open a product to see which months.');
      if (!t.dutyTracked) notes.push('Duty isn’t included: the NZ Alcohol module is off.');
      if (rows.some(function (r) { return r.revenue == null; })) {
        notes.push('Some months have sales with no usable amount (another currency, or no line amounts from Xero), so their revenue and margin show as —.');
      }
      if (notes.length) { els.note.textContent = notes.join(' '); els.note.hidden = false; }
    }

    function product(p) {
      var li = el('li', 'mg-product workspace-card');
      var head = el('button', 'mg-product__head');
      head.type = 'button';
      head.setAttribute('aria-expanded', 'false');
      var name = el('span', 'mg-product__name', p.name);
      head.appendChild(name);
      var nums = el('span', 'mg-product__nums');
      nums.appendChild(el('span', 'mg-num', units(p.t.units) + ' sold'));
      nums.appendChild(el('span', 'mg-num', 'Revenue ' + fmt(p.t.revenue)));
      nums.appendChild(el('span', 'mg-num mg-num--margin', 'Margin ' + fmt(p.t.margin)));
      if (p.t.percent != null) {
        nums.appendChild(el('span', 'mg-pill' + (p.t.percent < 0 ? ' mg-pill--bad' : ''), pct(p.t.percent)));
      }
      head.appendChild(nums);
      if (p.t.status !== 'actual') head.appendChild(el('span', 'mg-flag', STATUS[p.t.status]));
      li.appendChild(head);
      var detail = el('div', 'mg-product__detail');
      detail.hidden = true;
      li.appendChild(detail);
      head.addEventListener('click', function () {
        var open = head.getAttribute('aria-expanded') !== 'true';
        head.setAttribute('aria-expanded', String(open));
        detail.hidden = !open;
        if (open && !detail.childNodes.length) detail.appendChild(months(p.rows));
      });
      return li;
    }

    function months(rows) {
      var table = el('table', 'mg-months');
      var thead = el('thead');
      var tr = el('tr');
      ['Month', 'Units', 'Revenue', 'Cost', 'Duty', 'Margin', 'Per unit'].forEach(function (h) { tr.appendChild(el('th', null, h)); });
      thead.appendChild(tr);
      table.appendChild(thead);
      var tbody = el('tbody');
      rows.forEach(function (r) {
        var row = el('tr');
        var cell = el('td');
        var toggle = el('button', 'mg-month', monthLabel(r.month));
        toggle.type = 'button';
        toggle.setAttribute('aria-expanded', 'false');
        cell.appendChild(toggle);
        row.appendChild(cell);
        row.appendChild(el('td', null, units(r.units)));
        row.appendChild(el('td', null, fmt(r.revenue)));
        var cost = el('td', null, fmt(r.cost));
        if (r.cost_status !== 'actual') cost.appendChild(el('span', 'mg-flag mg-flag--inline', r.cost_status));
        row.appendChild(cost);
        row.appendChild(el('td', null, r.duty_tracked ? fmt(r.duty) : '—'));
        row.appendChild(el('td', null, fmt(r.margin) + (r.margin_percent != null ? ' · ' + pct(r.margin_percent) : '')));
        row.appendChild(el('td', null, fmt(r.average_cost_per_unit)));
        tbody.appendChild(row);
        var more = el('tr', 'mg-lines');
        more.hidden = true;
        var td = el('td');
        td.colSpan = 7;
        more.appendChild(td);
        tbody.appendChild(more);
        toggle.addEventListener('click', function () {
          var open = toggle.getAttribute('aria-expanded') !== 'true';
          toggle.setAttribute('aria-expanded', String(open));
          more.hidden = !open;
          if (open && !td.childNodes.length) td.appendChild(lines(r.lines));
        });
      });
      table.appendChild(tbody);
      var wrap = el('div', 'mg-months-wrap');
      wrap.appendChild(table);
      return wrap;
    }

    function lines(list) {
      var ul = el('ul', 'mg-sale-lines');
      list.forEach(function (l) {
        var li = el('li', 'mg-sale');
        var top = el('div', 'mg-sale__top');
        top.appendChild(el('strong', null, (l.credit_note ? 'Credit ' : '') + l.reference));
        top.appendChild(el('span', null, new Date(l.sold_on + 'T00:00:00').toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' })));
        top.appendChild(el('span', null, units(l.units) + ' units · ' + fmt(l.revenue)));
        li.appendChild(top);
        var parts = (l.batches || []).map(function (b) {
          return (b.batch ? 'Batch ' + b.batch : b.name) + ': ' + units(b.units) + ' at ' + (b.unit_cost ? fmt(b.unit_cost) : 'unknown cost');
        });
        if (Number(l.unbatched_units) > 0) parts.push(units(l.unbatched_units) + ' not matched to a batch (average cost)');
        if (parts.length) li.appendChild(el('p', 'mg-sale__batches', parts.join(' · ')));
        ul.appendChild(li);
      });
      return ul;
    }

    load();
  }

  bind();
  if (!window.__marginsPageListener) {
    window.__marginsPageListener = true;
    document.addEventListener('htmx:afterSettle', bind);
  }
})();
