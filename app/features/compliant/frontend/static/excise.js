// Excise workspace (plan 2.1). The server builds every figure from recorded removals and
// validates every change; this script lays them out and posts the owner's actions.
(function () {
  'use strict';

  // The SPA shell can swap page content in with HTMX, replacing this section after the
  // script has run; bind whichever copy is on the page now, once.
  function init() {
  var root = document.querySelector('[data-excise-root]');
  if (!root || root.dataset.bound === '1') return;
  root.dataset.bound = '1';

  function csrf() { var m = document.querySelector('meta[name="csrf-token"]'); return m ? m.getAttribute('content') : ''; }
  async function api(method, url, body) {
    var headers = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET') headers['X-CSRFToken'] = csrf();
    var res = await fetch(url, { method: method, credentials: 'include', headers: headers, body: body === undefined ? undefined : JSON.stringify(body) });
    var data = {}; try { data = await res.json(); } catch (_) {}
    if (!res.ok) throw new Error(data.error || ('Request failed (' + res.status + ')'));
    return data;
  }
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (k === 'text') n.textContent = attrs[k]; else if (k === 'className') n.className = attrs[k]; else n.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (k) { if (k) n.append(k); });
    return n;
  }
  function fmtDate(iso) { if (!iso) return '—'; var d = new Date(iso + 'T00:00:00'); return isNaN(d) ? iso : d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' }); }
  function money(v) { return v == null ? '—' : '$' + Number(v).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  var errorEl = document.querySelector('[data-compliant-error]');
  function fail(msg) { if (msg) console.error('[excise]', msg); if (errorEl) { errorEl.textContent = msg; errorEl.hidden = !msg; } }

  var state = { period: null };

  async function loadPeriods() {
    var data = await api('GET', '/api/compliant/nz-alcohol/excise/periods');
    var s = data.settings || {};
    document.getElementById('excise-frequency').value = s.frequency || 'monthly';
    document.getElementById('excise-tracking-from').value = s.tracking_from || '';
    var wrap = root.querySelector('[data-excise-periods]');
    wrap.replaceChildren();
    (data.periods || []).forEach(function (p) {
      var chip = el('button', { type: 'button', role: 'listitem', className: 'excise-period' + (p.status === 'lodged' ? ' excise-period--lodged' : '') + (p.open ? ' excise-period--open' : '') });
      chip.append(el('strong', { text: p.label }), el('span', { text: p.open ? 'In progress' : (p.status === 'lodged' ? ('Lodged ' + fmtDate(p.lodged_on)) : ('Due ' + fmtDate(p.due))) }));
      chip.addEventListener('click', function () { loadDraft(p.period_start); });
      wrap.append(chip);
    });
    if (!state.period && data.periods && data.periods.length) {
      var firstClosed = data.periods.find(function (p) { return !p.open; }) || data.periods[0];
      await loadDraft(firstClosed.period_start);
    }
  }

  async function loadDraft(start) {
    state.period = start;
    var data = await api('GET', '/api/compliant/nz-alcohol/excise?period=' + encodeURIComponent(start));
    renderDraft(data.draft);
    root.querySelectorAll('.excise-period').forEach(function (c) { c.classList.toggle('excise-period--active', c.textContent.indexOf(data.draft.label) === 0); });
  }

  function renderDraft(d) {
    var wrap = root.querySelector('[data-excise-draft]');
    wrap.replaceChildren();
    var head = el('div', { className: 'excise-draft-head' });
    var title = el('h3', { text: d.label + (d.status === 'lodged' ? ' · lodged' : (d.open ? ' · in progress' : ' · draft')) });
    var sub = el('p', { className: 'excise-hint', text: d.status === 'lodged'
      ? ('Recorded as lodged on ' + fmtDate(d.lodged_on) + (d.entry_reference ? ' (entry ' + d.entry_reference + ')' : '') + (d.nil_return ? ' as a nil return' : '') + '. These figures are locked.')
      : ('Due by ' + fmtDate(d.due) + ' (15th working day; public holidays not counted). Payment is due by the last working day of that month.') });
    var totals = el('p', { className: 'excise-totals', text: d.total_lal + ' LAL · ' + money(d.total_duty) + ' duty' });
    head.append(el('div', {}, [title, sub]), totals);
    wrap.append(head);

    if ((d.problems || []).length) {
      var probs = el('ul', { className: 'excise-problems' });
      d.problems.forEach(function (p) { probs.append(el('li', { text: p.product + ': ' + p.reason + (p.removals ? ' (' + p.removals + ' removal' + (p.removals === 1 ? '' : 's') + ' left out)' : '') })); });
      wrap.append(el('p', { className: 'excise-warning', text: 'Some removals can\'t be counted yet. Fix these before lodging:' }), probs);
    }

    if (!(d.lines || []).length && !(d.adjustments || []).length) {
      wrap.append(el('p', { text: d.open ? 'Nothing removed yet this period.' : 'Nothing was removed this period: lodge a nil return.' }));
    } else {
      var table = el('table', { className: 'excise-table' });
      var hr = el('tr'); ['Tariff item', 'Product', 'Units', 'Litres', 'LAL', 'Rate', 'Duty'].forEach(function (h) { hr.append(el('th', { text: h })); });
      table.append(el('thead', {}, [hr]));
      var body = el('tbody');
      (d.lines || []).forEach(function (l) {
        var row = el('tr');
        [l.tariff_item, l.product, l.units + ' ' + l.unit, l.litres, l.lal, l.rate_per_lal ? money(l.rate_per_lal) : 'no rate', money(l.duty)].forEach(function (v) { row.append(el('td', { text: v })); });
        body.append(row);
        var detail = el('tr', { className: 'excise-detail' });
        var cell = el('td', { colspan: '7' });
        var det = el('details');
        det.append(el('summary', { text: l.removals.length + ' removal' + (l.removals.length === 1 ? '' : 's') }));
        var ul = el('ul');
        l.removals.forEach(function (r) {
          ul.append(el('li', { text: fmtDate(r.date) + ' · ' + (r.kind === 'sale' ? 'Sold' : 'Moved out') + ' · ' + r.quantity + (r.batch ? ' from ' + r.batch : '') + ' at ' + r.abv_percent + '% · ' + r.reference + (r.customer ? ' · ' + r.customer : '') + ' · ' + r.lal + ' LAL' }));
        });
        det.append(ul); cell.append(det); detail.append(cell); body.append(detail);
      });
      table.append(body);
      wrap.append(el('div', { className: 'excise-table-wrap' }, [table]));
      if ((d.adjustments || []).length) {
        wrap.append(el('h4', { text: 'Carried in from lodged periods' }));
        var adj = el('ul');
        d.adjustments.forEach(function (a) { adj.append(el('li', { text: a.product + ': ' + a.quantity + ' on ' + fmtDate(a.date) + ' (' + a.reference + '), ' + a.lal + ' LAL, belongs to ' + a.belongs_to_label + ' but was recorded after it was lodged' })); });
        wrap.append(adj);
      }
    }
    if ((d.returns || []).length) {
      wrap.append(el('p', { className: 'excise-hint', text: 'Stock came back into the licensed area this period (' + d.returns.map(function (r) { return r.quantity + ' ' + r.unit + ' ' + r.product; }).join(', ') + '). If duty was paid when it left, raise a possible credit with Customs; it isn\'t claimed here.' }));
    }

    if (d.status !== 'lodged' && !d.open) {
      var form = el('form', { className: 'excise-inline-form excise-lodge' });
      var ref = el('input', { name: 'entry_reference', id: 'excise-entry-ref', placeholder: 'Customs entry number (optional)', maxlength: '100', 'aria-label': 'Customs entry number' });
      var on = el('input', { name: 'lodged_on', id: 'excise-lodged-on', type: 'date', 'aria-label': 'Lodged on' });
      on.value = new Date().toISOString().slice(0, 10);
      var btn = el('button', { type: 'submit', text: (d.lines || []).length || (d.adjustments || []).length ? 'Record as lodged' : 'Record nil return as lodged' });
      form.append(ref, on, btn);
      form.addEventListener('submit', async function (e) {
        e.preventDefault(); fail('');
        try {
          var res = await api('POST', '/api/compliant/nz-alcohol/excise/lodge', { period_start: d.period_start, lodged_on: on.value, entry_reference: ref.value });
          renderDraft(res.draft); await loadPeriods();
        } catch (err) { fail(err.message); }
      });
      wrap.append(form);
    }
  }

  async function loadProducts() {
    var data = await api('GET', '/api/compliant/nz-alcohol/excise/products');
    var wrap = root.querySelector('[data-excise-products]'); wrap.replaceChildren();
    if (!data.products.length) { wrap.append(el('p', { className: 'excise-hint', text: 'Add a workflow first; its final output appears here.' })); return; }
    data.products.forEach(function (p) {
      var f = el('form', { className: 'excise-inline-form excise-product' });
      var id = 'excise-p-' + p.name.replace(/[^a-z0-9]+/gi, '-').toLowerCase();
      var vol = el('input', { name: 'pack_volume_ml', id: id + '-vol', type: 'number', min: '1', step: '1', placeholder: 'mL per ' + (p.unit || 'unit'), 'aria-label': 'Pack volume for ' + p.name });
      var tar = el('input', { name: 'tariff_item', id: id + '-tariff', placeholder: 'Tariff item', maxlength: '100', 'aria-label': 'Tariff item for ' + p.name });
      var abv = el('input', { name: 'abv_fallback', id: id + '-abv', type: 'number', min: '0', max: '100', step: '0.1', placeholder: 'ABV fallback %', 'aria-label': 'Fallback ABV for ' + p.name });
      vol.value = p.pack_volume_ml || ''; tar.value = p.tariff_item || ''; abv.value = p.abv_fallback || '';
      f.append(el('strong', { text: p.name }), vol, tar, abv, el('button', { type: 'submit', text: 'Save' }));
      f.addEventListener('submit', async function (e) {
        e.preventDefault(); fail('');
        try { await api('PUT', '/api/compliant/nz-alcohol/excise/products', { name: p.name, pack_volume_ml: vol.value, tariff_item: tar.value, abv_fallback: abv.value }); await loadProducts(); if (state.period) await loadDraft(state.period); }
        catch (err) { fail(err.message); }
      });
      wrap.append(f);
    });
  }

  async function loadRates() {
    var data = await api('GET', '/api/compliant/nz-alcohol/excise/rates');
    var wrap = root.querySelector('[data-excise-rates]'); wrap.replaceChildren();
    if (!data.rates.length) { wrap.append(el('p', { className: 'excise-hint', text: 'No rates yet. Duty shows as "no rate" until you add one.' })); return; }
    var ul = el('ul');
    data.rates.forEach(function (r) { ul.append(el('li', { text: r.tariff_item + ': ' + money(r.rate_per_lal) + ' per LAL from ' + fmtDate(r.effective_from) })); });
    wrap.append(ul);
  }

  async function loadLocations() {
    var locs = await api('GET', '/api/core/stock-locations');
    var wrap = root.querySelector('[data-excise-locations]'); wrap.replaceChildren();
    var ul = el('ul');
    [locs.default].concat(locs.locations).forEach(function (l) { ul.append(el('li', { text: l.name + (l.inside_licensed_area ? ' · inside the licensed area' : ' · outside (moving stock here is a removal)') })); });
    wrap.append(ul);
    var to = document.getElementById('excise-move-to'); to.replaceChildren();
    [locs.default].concat(locs.locations).forEach(function (l) { to.append(el('option', { value: l.id || '', text: l.name })); });
    var inv = await api('GET', '/api/core/inventory?type=final_product');
    var items = inv.inventory_items || inv.items || [];
    var sel = document.getElementById('excise-move-item'); sel.replaceChildren();
    items.filter(function (i) { return Number(i.quantity) > 0; }).forEach(function (i) {
      sel.append(el('option', { value: i.id, text: i.name + (i.supplier_batch_number ? ' · ' + i.supplier_batch_number : '') + ' · ' + Number(i.quantity) + ' ' + i.unit }));
    });
  }

  root.querySelector('[data-excise-settings]').addEventListener('submit', async function (e) {
    e.preventDefault(); fail('');
    try { await api('PUT', '/api/compliant/nz-alcohol/excise/settings', { frequency: document.getElementById('excise-frequency').value, tracking_from: document.getElementById('excise-tracking-from').value || null }); state.period = null; await loadPeriods(); }
    catch (err) { fail(err.message); }
  });
  root.querySelector('[data-excise-rate-form]').addEventListener('submit', async function (e) {
    e.preventDefault(); fail(''); var f = e.currentTarget;
    try { await api('POST', '/api/compliant/nz-alcohol/excise/rates', { tariff_item: f.tariff_item.value, rate_per_lal: f.rate_per_lal.value, effective_from: f.effective_from.value }); f.reset(); await loadRates(); if (state.period) await loadDraft(state.period); }
    catch (err) { fail(err.message); }
  });
  root.querySelector('[data-excise-location-form]').addEventListener('submit', async function (e) {
    e.preventDefault(); fail(''); var f = e.currentTarget;
    try { await api('POST', '/api/core/stock-locations', { name: f.name.value, inside_licensed_area: f.inside_licensed_area.checked }); f.reset(); await loadLocations(); }
    catch (err) { fail(err.message); }
  });
  root.querySelector('[data-excise-move-form]').addEventListener('submit', async function (e) {
    e.preventDefault(); fail(''); var f = e.currentTarget;
    try {
      var res = await api('POST', '/api/core/inventory/' + encodeURIComponent(f.item_id.value) + '/move', { quantity: f.quantity.value, to_location_id: f.to_location_id.value || null, occurred_on: f.occurred_on.value || null });
      fail(''); f.quantity.value = '';
      await loadLocations(); if (state.period) await loadDraft(state.period);
      if (res.excise_removal && errorEl) { errorEl.hidden = true; }
    } catch (err) { fail(err.message); }
  });

  Promise.all([loadPeriods(), loadProducts(), loadRates(), loadLocations()]).catch(function (err) { fail(err.message); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  document.addEventListener('htmx:afterSwap', init);
})();
