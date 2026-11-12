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
  }

  bind();
  if (!window.__costsPageListener) { // the script re-runs on each boosted visit; one listener is enough
    window.__costsPageListener = true;
    document.addEventListener('htmx:afterSettle', bind);
  }
})();
