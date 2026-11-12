/* Production › Costs (live-cogs 8.1e-2): cost readiness per product. Binds to its page root on
   every arrival (boosted navigation swaps #page-content and keeps window). */
(function () {
  'use strict';
  var API = '/api/core/costing';

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function get(url) {
    return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.error || 'Something went wrong');
        return d;
      });
    });
  }

  function bind() {
    var root = document.querySelector('[data-costs-root]');
    if (!root || root.getAttribute('data-bound') === '1') return;
    root.setAttribute('data-bound', '1');
    var els = {
      error: root.querySelector('[data-costs-error]'),
      summary: root.querySelector('[data-costs-summary]'),
      howto: root.querySelector('[data-costs-howto]'),
      list: root.querySelector('[data-costs-list]'),
      empty: root.querySelector('[data-costs-empty]'),
      prices: root.querySelector('[data-prices]'),
      pricesList: root.querySelector('[data-prices-list]'),
      pricesEmpty: root.querySelector('[data-prices-empty]'),
      pricesError: root.querySelector('[data-prices-error]'),
    };
    var canManage = root.getAttribute('data-can-manage') === 'true';

    Promise.all([get(API + '/readiness'), window.BizECost ? window.BizECost.me() : Promise.resolve({})])
      .then(function (results) { render(results[0].products || [], results[1] || {}); })
      .catch(function (err) {
        els.summary.textContent = '';
        els.error.textContent = 'Costs couldn’t load: ' + err.message;
        els.error.hidden = false;
      })
      .finally(function () { root.setAttribute('aria-busy', 'false'); });
    loadPrices();

    function render(products, who) {
      if (!products.length) {
        els.summary.textContent = '';
        els.empty.hidden = false;
        return;
      }
      var ready = products.filter(function (p) { return p.ready; }).length;
      els.summary.textContent = ready === products.length
        ? 'All ' + products.length + ' products have a full cost.'
        : ready + ' of ' + products.length + ' products have a full cost.';
      if (ready < products.length && canManage) howTo(who);
      var ordered = products.slice().sort(function (a, b) {
        if (a.ready !== b.ready) return a.ready ? 1 : -1;
        return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
      });
      els.list.replaceChildren();
      ordered.forEach(function (p) { els.list.appendChild(row(p)); });
    }

    function howTo(who) {
      els.howto.replaceChildren();
      els.howto.appendChild(el('h2', '', 'Costing what’s missing'));
      var steps = el('ul', 'co-howto__list');
      if (who.xero_connected) {
        var li = el('li');
        li.appendChild(document.createTextNode('Record purchases from Xero on '));
        var a = el('a', '', 'Purchases');
        a.href = '/core/costing/purchases';
        li.appendChild(a);
        li.appendChild(document.createTextNode('.'));
        steps.appendChild(li);
      }
      steps.appendChild(el('li', '', 'Enter what you paid when you add stock — it’s on every Add Inventory screen.'));
      steps.appendChild(el('li', '', 'Or open a lot below and enter what was paid for it.'));
      els.howto.appendChild(steps);
      els.howto.hidden = false;
    }

    function row(p) {
      var li = el('li', 'co-row' + (p.ready ? ' co-row--ready' : ''));
      var button = el('button', 'co-row__head');
      button.type = 'button';
      button.setAttribute('aria-expanded', 'false');
      var detailId = 'co-detail-' + p.key.replace(/[^a-z0-9]/gi, '-');
      button.setAttribute('aria-controls', detailId);
      button.appendChild(el('span', 'co-row__name', p.name || 'Unnamed product'));
      var status = p.ready
        ? el('span', 'cost-pill cost-pill--ok', 'Full cost')
        : el('span', 'cost-pill cost-pill--warn', p.materials_total
          ? p.materials_costed + ' of ' + p.materials_total + ' materials costed'
          : 'No materials recorded');
      button.appendChild(status);
      var chevron = el('span', 'co-row__chevron');
      chevron.setAttribute('aria-hidden', 'true');
      button.appendChild(chevron);
      li.appendChild(button);
      var detail = el('div', 'co-row__detail');
      detail.id = detailId;
      detail.hidden = true;
      li.appendChild(detail);
      var loaded = false;
      button.addEventListener('click', function () {
        var open = button.getAttribute('aria-expanded') !== 'true';
        button.setAttribute('aria-expanded', String(open));
        detail.hidden = !open;
        if (open && !loaded) { loaded = true; loadDetail(p, detail); }
      });
      return li;
    }

    function loadDetail(p, detail) {
      detail.appendChild(el('p', 'cost-muted', 'Loading…'));
      get(API + '/readiness/' + encodeURIComponent(p.key)).then(function (d) {
        detail.replaceChildren();
        if (!d.materials.length) {
          detail.appendChild(el('p', 'cost-muted', d.basis === 'latest_batch'
            ? 'Its latest batch recorded no materials going in.'
            : 'No batch yet, and its workflow doesn’t list what goes into it.'));
          return;
        }
        detail.appendChild(el('p', 'cost-muted', d.basis === 'latest_batch'
          ? 'From its latest batch.'
          : 'No batch yet — from what its workflow says it uses.'));
        if (d.execution_id && window.BizECost) {
          var mount = el('div');
          detail.appendChild(mount);
          window.BizECost.batchCard(d.execution_id, mount);
        }
        var list = el('ul', 'co-materials');
        d.materials.forEach(function (m) {
          var item = el('li', 'co-material');
          var name;
          if (m.inventory_item_id) {
            name = el('a', 'co-material__name', m.name || 'Unnamed lot');
            name.href = '/core/inventory/view?item=' + encodeURIComponent(m.inventory_item_id);
          } else {
            name = el('span', 'co-material__name', m.name);
          }
          item.appendChild(name);
          item.appendChild(m.costed
            ? el('span', 'cost-pill cost-pill--ok', m.status === 'estimated' ? 'Estimated' : 'Costed')
            : el('span', 'cost-pill cost-pill--muted', m.inventory_item_id ? 'Not costed' : 'No costed stock yet'));
          list.appendChild(item);
        });
        detail.appendChild(list);
      }).catch(function (err) {
        detail.replaceChildren(el('p', 'cost-error', 'Couldn’t load this product: ' + err.message));
      });
    }

    /* ------------------------------------------------ what you pay for materials (8.1f-3a) */
    var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    function monthName(key, withYear) {
      var parts = key.split('-');
      var name = MONTHS[Number(parts[1]) - 1] || key;
      return withYear ? name + ' ' + parts[0] : name;
    }
    function shortDate(iso) {
      var d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso);
      if (isNaN(d)) return iso;
      return d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear();
    }
    function price(raw) {
      if (raw == null) return '—';
      var n = Number(raw);
      if (!isFinite(n)) return '—';
      var digits = Math.abs(n) >= 1 || n === 0 ? 2 : 4;
      if (n > 0 && n < 0.00005) return '<$0.0001';
      if (n < 0 && Math.abs(n) < 0.0001) digits = 6;
      return '$' + n.toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: digits });
    }
    function per(unit) { return unit ? ' / ' + unit : ''; }

    function loadPrices() {
      get(API + '/materials').then(function (d) {
        var materials = d.materials || [];
        els.prices.hidden = false;
        els.pricesError.hidden = true;
        els.pricesError.textContent = '';
        els.pricesList.replaceChildren();
        els.pricesEmpty.hidden = materials.length > 0;
        materials.forEach(function (m, index) { els.pricesList.appendChild(priceRow(m, index)); });
      }).catch(function (err) {
        els.prices.hidden = false;
        els.pricesList.replaceChildren();
        els.pricesEmpty.hidden = true;
        els.pricesError.textContent = 'Prices couldn’t load: ' + err.message;
        els.pricesError.hidden = false;
      });
    }

    function priceRow(m, index) {
      var li = el('li', 'co-row');
      var button = el('button', 'co-row__head');
      button.type = 'button';
      button.setAttribute('aria-expanded', 'false');
      var detailId = 'co-price-' + index;
      button.setAttribute('aria-controls', detailId);
      button.appendChild(el('span', 'co-row__name', m.name));
      var figure = el('span', 'co-price');
      if (m.latest_unit_price == null) {
        var reason = m.latest_reason === 'too_large'
          ? 'History too large to calculate'
          : m.latest_reason === 'other_units' ? 'Price is in other units' : 'Latest price unavailable';
        figure.appendChild(el('span', 'co-price__when', reason));
      } else {
        figure.appendChild(el('span', 'co-price__value', price(m.latest_unit_price) + per(m.unit)));
        figure.appendChild(el('span', 'co-price__when', 'last paid ' + shortDate(m.latest_date)));
      }
      button.appendChild(figure);
      var chevron = el('span', 'co-row__chevron');
      chevron.setAttribute('aria-hidden', 'true');
      button.appendChild(chevron);
      li.appendChild(button);
      var detail = el('div', 'co-row__detail');
      detail.id = detailId;
      detail.hidden = true;
      li.appendChild(detail);
      var loaded = false;
      button.addEventListener('click', function () {
        var open = button.getAttribute('aria-expanded') !== 'true';
        button.setAttribute('aria-expanded', String(open));
        detail.hidden = !open;
        if (open && !loaded) { loaded = true; loadHistory(m, detail); }
      });
      return li;
    }

    function loadHistory(m, detail) {
      detail.appendChild(el('p', 'cost-muted', 'Loading…'));
      get(API + '/materials/' + encodeURIComponent(m.name) + '/history').then(function (h) {
        detail.replaceChildren();
        if (h.too_large) {
          detail.appendChild(el('p', 'cost-muted', 'This material has more history than Biz-E can add up in one go, so there’s no month-by-month view for it.'));
          return;
        }
        var priced = h.months.filter(function (row) { return row.average_unit_cost != null; });
        if (!priced.length) {
          detail.appendChild(el('p', 'cost-muted', m.latest_date
            ? 'Nothing bought in the last year. The latest price is from ' + shortDate(m.latest_date) + '.'
            : 'Nothing bought in the last year in a unit that compares with ' + (h.unit || 'its main unit') + '.'));
          return;
        }
        detail.appendChild(el('p', 'co-trend', trend(priced, h.unit)));
        if (priced.length > 1) detail.appendChild(chart(h, priced));
        if (priced.length > 1) detail.appendChild(monthsTable(priced, h.unit));
        var unconverted = h.months.reduce(function (n, row) { return n + (row.unconverted || 0); }, 0);
        if (unconverted) {
          detail.appendChild(el('p', 'cost-muted', unconverted === 1
            ? 'One price was in a unit that can’t be compared with ' + h.unit + ', so it’s left out.'
            : unconverted + ' prices were in a unit that can’t be compared with ' + h.unit + ', so they’re left out.'));
        }
      }).catch(function (err) {
        detail.replaceChildren(el('p', 'cost-error', 'Couldn’t load prices: ' + err.message));
      });
    }

    function trend(priced, unit) {
      var first = priced[0], last = priced[priced.length - 1];
      if (priced.length === 1) {
        return 'Bought in ' + monthName(last.month, true) + ' at ' + price(last.average_unit_cost) + per(unit) + ' on average.';
      }
      var a = Number(first.average_unit_cost), b = Number(last.average_unit_cost);
      if (!a) return 'Last bought in ' + monthName(last.month, true) + ' at ' + price(last.average_unit_cost) + per(unit) + '.';
      var change = Math.round((b - a) / a * 100);
      var span = ' from ' + monthName(first.month, true) + ' to ' + monthName(last.month, true);
      if (change === 0) return 'Steady at about ' + price(last.average_unit_cost) + per(unit) + span + '.';
      return (change > 0 ? 'Up ' : 'Down ') + Math.abs(change) + '%' + span + ' (' + price(first.average_unit_cost) + ' → ' + price(last.average_unit_cost) + per(unit) + ').';
    }

    /* A dot per month on a scale fitted to the prices (a 2% rise is visible), joined by a line.
       Dots, not bars: bars would have to start at $0 to be honest, which flattens every change. */
    function chart(h, priced) {
      var months = allMonths(h.from, h.to);
      var byKey = {};
      h.months.forEach(function (row) { byKey[row.month] = row; });
      var values = priced.map(function (row) { return Number(row.average_unit_cost); });
      var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
      var pad = Math.max((hi - lo) * 0.15, hi * 0.02, 0.01);
      lo -= pad; hi += pad;
      function height(v) { return 8 + 72 * (v - lo) / (hi - lo); } // % of the plot, room above for labels
      var first = priced[0].month, last = priced[priced.length - 1].month;
      var wrap = el('div', 'co-bars');
      wrap.setAttribute('role', 'img');
      wrap.setAttribute('aria-label', 'Average price per month, ' + monthName(h.from, true) + ' to ' +
        monthName(h.to, true) + '. Each month is listed below.');
      wrap.style.setProperty('--co-months', String(months.length));
      var NS = 'http://www.w3.org/2000/svg';
      var svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('class', 'co-bars__line');
      svg.setAttribute('viewBox', '0 0 100 100');
      svg.setAttribute('preserveAspectRatio', 'none');
      svg.setAttribute('aria-hidden', 'true');
      var points = [];
      months.forEach(function (k, i) {
        var col = el('div', 'co-bars__col');
        var row = byKey[k];
        var v = row && row.average_unit_cost != null ? Number(row.average_unit_cost) : NaN;
        var plot = el('div', 'co-bars__plot');
        if (isFinite(v)) {
          var y = height(v);
          points.push(((i + 0.5) / months.length * 100).toFixed(2) + ',' + (100 - y).toFixed(2));
          var dot = el('span', 'co-bars__dot');
          dot.style.bottom = y + '%';
          dot.tabIndex = 0;
          dot.title = monthName(k, true) + ': ' + price(row.average_unit_cost) + per(h.unit) + ' average, ' +
            row.purchases + (row.purchases === 1 ? ' purchase' : ' purchases');
          dot.setAttribute('aria-label', dot.title);
          if (k === first || k === last) dot.appendChild(el('span', 'co-bars__value', price(row.average_unit_cost)));
          plot.appendChild(dot);
        }
        col.appendChild(plot);
        var label = el('span', 'co-bars__label', monthName(k, false));
        if (months.length > 12 && i % 2) label.classList.add('co-bars__label--skip');
        col.appendChild(label);
        wrap.appendChild(col);
      });
      var line = document.createElementNS(NS, 'polyline');
      line.setAttribute('points', points.join(' '));
      line.setAttribute('vector-effect', 'non-scaling-stroke');
      svg.appendChild(line);
      wrap.insertBefore(svg, wrap.firstChild);
      return wrap;
    }

    function allMonths(from, to) {
      var out = [], y = Number(from.slice(0, 4)), mo = Number(from.slice(5, 7));
      var ey = Number(to.slice(0, 4)), em = Number(to.slice(5, 7));
      while (y < ey || (y === ey && mo <= em)) {
        out.push(y + '-' + (mo < 10 ? '0' : '') + mo);
        mo += 1; if (mo > 12) { mo = 1; y += 1; }
      }
      return out;
    }

    function monthsTable(priced, unit) {
      var wrap = el('details', 'co-months-toggle');
      wrap.appendChild(el('summary', '', 'Each month'));
      var table = el('table', 'co-months');
      var head = el('tr');
      var ranged = priced.some(function (row) { return row.min_unit_price !== row.max_unit_price; });
      var heads = ['Month', 'Average' + per(unit), 'Quantity priced'];
      if (ranged) heads.push('Range');
      heads.forEach(function (t, i) {
        var th = el('th', i === 3 ? 'co-months__range' : '', t);
        th.scope = 'col';
        head.appendChild(th);
      });
      var thead = el('thead'); thead.appendChild(head); table.appendChild(thead);
      var tbody = el('tbody');
      priced.slice().reverse().forEach(function (row) {
        var tr = el('tr');
        tr.appendChild(el('td', '', monthName(row.month, true)));
        tr.appendChild(el('td', '', price(row.average_unit_cost)));
        tr.appendChild(el('td', '', Number(row.priced_quantity).toLocaleString('en-NZ', { maximumFractionDigits: 3 }) + (unit ? ' ' + unit : '')));
        if (ranged) {
          tr.appendChild(el('td', 'co-months__range', row.min_unit_price === row.max_unit_price
            ? price(row.min_unit_price) : price(row.min_unit_price) + '–' + price(row.max_unit_price)));
        }
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      wrap.appendChild(table);
      return wrap;
    }
  }

  bind();
  if (!window.__costsPageListener) { // the script re-runs on each boosted visit; one listener is enough
    window.__costsPageListener = true;
    document.addEventListener('htmx:afterSettle', bind);
  }
})();
