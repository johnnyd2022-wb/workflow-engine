// Customs → Stock: where finished stock is (inside or outside the licensed area), moving it,
// and what the last stocktake explained. Counting itself happens on the Stocktake page; this
// page reads its results through the Customs lens: on the entry, a remission, or no duty.
(function () {
  'use strict';

  var REASONS = {
    found_elsewhere: 'Found elsewhere',
    removed_unrecorded: 'Removed without a record (tasting, samples, gift, missed sale)',
    broken: 'Broken, damaged or faulty',
    investigating: 'Still looking',
    unexplained_loss: "Can't explain (loss)",
    returned: 'Came back from a rep or event',
    removal_not_happened: "A recorded removal didn't happen",
    under_recorded: 'Production was under-recorded',
    unexplained_gain: "Can't explain (gain)",
  };
  var LIBRARY = /- library stock$/i;
  // The stocktake's own places for stock that has gone: not somewhere stock sits (stocktake.py).
  var GONE = ['Removed without a sale record', 'Unaccounted loss'];

  function init() {
    var page = document.querySelector('[data-customs-stock-root]');
    if (!page || page.dataset.bound === '1' || !window.CustomsUI) return;
    page.dataset.bound = '1';
    var U = window.CustomsUI;
    var el = U.el, api = U.api, money = U.money, fmtDate = U.fmtDate, num = U.num, qty = U.qty;
    var fail = U.failer(page);

    function bucket(res) {
      if (res.reason === 'investigating') return 'looking';
      if (res.reason === 'broken') return 'remission';
      return res.dutiable ? 'entry' : 'none';
    }
    var BUCKETS = [
      ['entry', 'On the excise entry', 'Dutiable removals: they are on the entry for the month they happened.'],
      ['remission', 'Claim a remission', "Broken or damaged stock is dutiable unless Customs remits it: apply on form NZCS 277, or note it on the entry if you're authorised to self-remit."],
      ['none', 'No duty', 'Stock that was still inside the licensed area, came back, or was recorded wrongly.'],
      ['looking', 'Still being looked into', 'Held open for 14 days; anything not found by then is a loss.'],
    ];

    async function loadStocktake() {
      var list = await api('GET', '/api/core/stocktakes');
      var sched = list.schedule || {};
      var open = list.open_variances || [];
      var openDuty = open.reduce(function (n, v) { return n + Math.abs(Number(v.cost || 0)); }, 0);
      var facts = page.querySelector('[data-stocktake-facts]'); facts.replaceChildren();
      facts.append(
        U.fact('Last counted', sched.last_completed_on ? fmtDate(sched.last_completed_on) : 'Never', sched.last_completed_on ? '' : 'Customs expects at least one stocktake a year'),
        U.fact('Next due', sched.next_due ? fmtDate(sched.next_due) : 'After the first count', { monthly: 'Counting monthly', quarterly: 'Counting quarterly', six_monthly: 'Counting six-monthly', annual: 'Counting yearly' }[sched.frequency] || '', sched.overdue ? 'bad' : ''),
        U.fact('Differences open', String(open.length), open.length ? money(openDuty) + ' duty if they were removed' : 'Every difference has a reason', open.length ? 'warn' : 'good')
      );
      var out = page.querySelector('[data-stocktake-outcome]'); out.replaceChildren();
      var stocktakes = list.stocktakes || [];
      var counting = stocktakes.find(function (s) { return s.status === 'counting'; });
      if (counting) {
        out.append(el('p', { className: 'customs-note' }, [document.createTextNode('A stocktake from ' + fmtDate(counting.counted_on) + ' is still being counted. '), el('a', { href: '/core/stocktake?id=' + encodeURIComponent(counting.id), text: 'Continue it' })]));
      }
      var done = stocktakes.filter(function (s) { return s.status === 'done'; })[0];
      if (!done) {
        if (!counting) out.append(el('p', { className: 'customs-empty', text: 'No stocktake yet. The first count sets what everything after it is checked against.' }));
        return;
      }
      var detail = await api('GET', '/api/core/stocktakes/' + encodeURIComponent(done.id));
      var recon = await api('GET', '/api/core/stocktakes/' + encodeURIComponent(done.id) + '/reconciliation');
      out.append(el('h3', { className: 'customs-sub', text: 'What the ' + fmtDate(done.counted_on) + ' count found' }));

      var groups = {};
      (detail.lines || []).forEach(function (line) {
        (line.resolutions || []).forEach(function (r) {
          (groups[bucket(r)] = groups[bucket(r)] || []).push({ line: line, res: r });
        });
      });
      var any = Object.keys(groups).length;
      if (!any) out.append(el('p', { className: 'customs-note', text: 'Everything counted matched the records.' }));
      var grid = el('div', { className: 'customs-buckets' });
      BUCKETS.forEach(function (b) {
        var items = groups[b[0]];
        if (!items) return;
        var card = el('article', { className: 'customs-bucket customs-bucket--' + b[0] });
        card.append(el('h4', { text: b[1] }), el('p', { className: 'excise-hint', text: b[2] }));
        var ul = el('ul', { className: 'customs-bucket__list' });
        items.forEach(function (x) {
          var r = x.res, line = x.line;
          var what = U.amount(r.quantity, line.unit) + ' ' + line.name.replace(/ - final product$/i, '') + (line.batch ? ' (' + line.batch + ')' : '');
          var li = el('li', {}, [el('strong', { text: what }), el('span', { text: (REASONS[r.reason] || r.reason) + (r.place && GONE.indexOf(r.place) === -1 ? ' · ' + r.place : '') + (r.occurred_on ? ' · ' + U.shortDate(r.occurred_on) : '') + (r.note ? ' · ' + r.note : '') })]);
          if (r.raise_with_customs) li.append(el('em', { text: 'Tell Customs' }));
          ul.append(li);
        });
        card.append(ul);
        grid.append(card);
      });
      if (any) out.append(grid);

      var products = recon.products || [];
      if (products.length) {
        var det = el('details', { className: 'customs-breakdown customs-recon' });
        det.append(el('summary', { text: 'Book stock against the count, by product' + (recon.since ? ' since ' + fmtDate(recon.since) : '') }));
        var table = el('table', { className: 'customs-recon-table' });
        var cols = [['Product', ''], ['Opening', 'num'], ['Made and in', 'num'], ['Removed', 'num'], ['Losses', 'num'], ['Expected', 'num'], ['Counted', 'num'], ['Difference', 'num'], ['Explained', 'num']];
        var hr = el('tr'); cols.forEach(function (c) { hr.append(el('th', { scope: 'col', className: c[1], text: c[0] })); });
        table.append(el('thead', {}, [hr]));
        var body = el('tbody');
        products.forEach(function (p) {
          var row = el('tr');
          [p.product.replace(/ - final product$/i, ''), p.opening, p.produced_and_in, p.removed, p.losses, p.expected, p.counted, p.variance, p.explained].forEach(function (v, i) {
            row.append(el('td', { className: cols[i][1], 'data-label': cols[i][0], text: i === 0 ? v : (v == null ? '—' : qty(v)) }));
          });
          body.append(row);
        });
        table.append(body);
        det.append(el('div', { className: 'customs-table-wrap' }, [table]));
        det.append(el('p', { className: 'excise-hint', text: 'Opening is the last count; removed is what left the licensed area (sales and moves out); expected is what the records say should be there.' }));
        out.append(det);
      }
    }

    async function loadPlaces() {
      var pos = await api('GET', '/api/core/stock-position');
      var wrap = page.querySelector('[data-stock-places]'); wrap.replaceChildren();
      var places = pos.places || [];
      var library = [];
      if (!places.length) { wrap.append(el('p', { className: 'customs-empty', text: 'No finished stock or work in progress on hand.' })); }
      var grid = el('div', { className: 'customs-place-grid' });
      places.filter(function (place) { return GONE.indexOf(place.name) === -1; }).forEach(function (place) {
        var byProduct = {};
        place.lots.forEach(function (lot) {
          if (LIBRARY.test(lot.name)) { library.push({ place: place, lot: lot }); return; }
          var key = lot.name.replace(/ - final product$/i, '') + (lot.stage === 'In progress' ? ' (in progress)' : '');
          var p = byProduct[key] = byProduct[key] || { qty: 0, unit: lot.unit, lots: 0 };
          p.qty += Number(lot.quantity); p.lots += 1;
        });
        var card = el('article', { className: 'customs-place customs-place--' + (place.inside_licensed_area ? 'inside' : 'outside') });
        card.append(el('div', { className: 'customs-place__head' }, [
          el('strong', { text: place.name }),
          el('span', { className: 'customs-chip customs-chip--' + (place.inside_licensed_area ? 'complete' : 'open'), text: place.inside_licensed_area ? 'Licensed area · duty unpaid' : 'Outside · duty paid' }),
        ]));
        if (place.total_measure && Number(place.total_measure)) card.append(el('p', { className: 'customs-place__lal', text: num(place.total_measure, 3) + ' LAL' }));
        var ul = el('ul', { className: 'customs-place__list' });
        Object.keys(byProduct).sort().forEach(function (name) {
          var p = byProduct[name];
          ul.append(el('li', {}, [el('span', { text: name }), el('strong', { text: U.amount(p.qty, p.unit) })]));
        });
        if (!ul.children.length) ul.append(el('li', { className: 'excise-hint', text: 'Only library stock here.' }));
        card.append(ul);
        grid.append(card);
      });
      if (places.length) wrap.append(grid);
      if (library.length) {
        var lib = el('div', { className: 'customs-library' });
        lib.append(el('h3', { className: 'customs-sub', text: 'Library stock' }), el('p', { className: 'excise-hint', text: 'Kept back from each batch. Duty unpaid while it stays in the licensed area; dutiable once it is tasted, used or taken out.' }));
        var ul2 = el('ul', { className: 'customs-plain-list' });
        library.forEach(function (x) { ul2.append(el('li', { text: x.lot.name.replace(LIBRARY, '').trim() + (x.lot.batch ? ' (' + x.lot.batch + ')' : '') + ': ' + U.amount(x.lot.quantity, x.lot.unit) + (x.lot.measure ? ' · ' + num(x.lot.measure, 3) + ' LAL' : '') + (x.place.inside_licensed_area ? '' : ' · at ' + x.place.name) })); });
        lib.append(ul2);
        wrap.append(lib);
      }
    }

    async function loadMoveForm() {
      var locs = await api('GET', '/api/core/stock-locations');
      var to = document.getElementById('excise-move-to'); to.replaceChildren();
      [locs.default].concat(locs.locations || []).forEach(function (l) { to.append(el('option', { value: l.id || '', text: l.name + (l.inside_licensed_area ? '' : ' (outside)') })); });
      var inv = await api('GET', '/api/core/inventory?type=final_product');
      var items = inv.inventory_items || inv.items || [];
      var sel = document.getElementById('excise-move-item'); sel.replaceChildren();
      items.filter(function (i) { return Number(i.quantity) > 0; }).forEach(function (i) {
        sel.append(el('option', { value: i.id, text: i.name.replace(/ - final product$/i, '') + (i.supplier_batch_number ? ' · ' + i.supplier_batch_number : '') + ' · ' + Number(i.quantity) + ' ' + i.unit }));
      });
      document.getElementById('excise-move-date').value = U.todayIso();
    }

    page.querySelectorAll('[data-stock-start]').forEach(function (b) {
      b.addEventListener('click', async function () {
        fail(''); b.disabled = true;
        try {
          var st = await api('POST', '/api/core/stocktakes', { kind: b.getAttribute('data-stock-start') });
          window.location.href = '/core/stocktake?id=' + encodeURIComponent(st.id);
        } catch (err) { fail(err.message); b.disabled = false; }
      });
    });
    page.querySelector('[data-excise-move-form]').addEventListener('submit', async function (e) {
      e.preventDefault(); fail(''); var f = e.currentTarget;
      var result = page.querySelector('[data-move-result]');
      try {
        var res = await api('POST', '/api/core/inventory/' + encodeURIComponent(f.item_id.value) + '/move', { quantity: f.quantity.value, to_location_id: f.to_location_id.value || null, occurred_on: f.occurred_on.value || null });
        result.textContent = res.excise_removal ? 'Moved. It left the licensed area, so it is a removal on the entry for ' + fmtDate(f.occurred_on.value || U.todayIso()).replace(/^\d+ /, '') + '.' : (res.direction === 'in' ? 'Moved back into the licensed area.' : 'Moved.');
        f.quantity.value = '';
        await Promise.all([loadPlaces(), loadMoveForm()]);
      } catch (err) { fail(err.message); }
    });
    page.querySelector('[data-excise-location-form]').addEventListener('submit', async function (e) {
      e.preventDefault(); fail(''); var f = e.currentTarget;
      try { await api('POST', '/api/core/stock-locations', { name: f.name.value, inside_licensed_area: f.inside_licensed_area.checked }); f.reset(); await loadMoveForm(); }
      catch (err) { fail(err.message); }
    });

    Promise.all([loadStocktake(), loadPlaces(), loadMoveForm()])
      .catch(function (err) { fail(err.message); })
      .finally(function () { page.setAttribute('aria-busy', 'false'); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  document.addEventListener('htmx:afterSwap', init);
})();
