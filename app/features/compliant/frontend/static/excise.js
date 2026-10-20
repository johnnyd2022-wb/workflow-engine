// Customs page: the excise entry for each period (plan 2.1). The server builds every figure
// from recorded removals and validates every change; this script lays them out and posts
// the owner's actions. The entry lines follow Trade Single Window's column order so they
// can be copied across.
(function () {
  'use strict';

  // The SPA shell can swap page content in with HTMX, replacing this section after the
  // script has run; bind whichever copy is on the page now, once.
  function init() {
  var root = document.querySelector('[data-excise-root]');
  if (!root || root.dataset.bound === '1') return;
  root.dataset.bound = '1';
  var page = root.closest('[data-compliant-root]') || document.body;

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
  function shortDate(iso) { if (!iso) return '—'; var d = new Date(iso + 'T00:00:00'); return isNaN(d) ? iso : d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' }); }
  function rateText(l) {
    if (!l.rate) return 'no rate';
    return '$' + l.rate + (l.basis === 'per_litre' ? ' /L' : ' /LAL');
  }
  function money(v) { return v == null ? '—' : '$' + Number(v).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function num(v, dp) { return v == null ? '—' : Number(v).toLocaleString('en-NZ', { minimumFractionDigits: dp, maximumFractionDigits: dp }); }
  function todayIso() { var d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
  function daysUntil(iso) { return Math.round((new Date(iso + 'T00:00:00') - new Date(todayIso() + 'T00:00:00')) / 86400000); }
  var errorEl = document.querySelector('[data-compliant-error]');
  function fail(msg) { if (msg) console.error('[excise]', msg); if (errorEl) { errorEl.textContent = msg; errorEl.hidden = !msg; } }

  var state = { period: null, periods: [], draft: null, frequency: 'monthly', remindersFrom: null };

  // A period's status in words: never colour alone.
  function periodStatus(p) {
    if (p.status === 'lodged') return { key: 'lodged', text: p.nil_return ? 'Nil return lodged ' + shortDate(p.lodged_on) : 'Lodged ' + shortDate(p.lodged_on) };
    if (p.open) return { key: 'open', text: 'In progress' };
    // Before reminders began: nobody was asked to lodge it here, so it isn't "overdue".
    if (state.remindersFrom && p.period_end && p.period_end < state.remindersFrom) return { key: 'untracked', text: 'Not tracked' };
    var days = daysUntil(p.due);
    if (days < 0) return { key: 'overdue', text: 'Overdue · was due ' + shortDate(p.due), short: 'Overdue' };
    if (days === 0) return { key: 'due', text: 'Due today' };
    return { key: 'due', text: 'Due ' + shortDate(p.due) + ' · ' + days + ' day' + (days === 1 ? '' : 's') + ' left', short: 'Due ' + shortDate(p.due) };
  }

  function renderPeriods() {
    var wrap = root.querySelector('[data-excise-periods]');
    wrap.replaceChildren();
    if (!state.periods.length) return;
    var earlier = state.periods.filter(function (p) { return periodStatus(p).key === 'untracked' && p.period_start !== state.period; });
    state.periods.forEach(function (p) {
      var st = periodStatus(p);
      if (!state.showEarlier && earlier.indexOf(p) !== -1) return;
      var chip = el('button', { type: 'button', role: 'listitem', className: 'excise-period excise-period--' + st.key + (p.period_start === state.period ? ' excise-period--active' : ''), 'data-period': p.period_start, 'data-period-status': st.key, 'aria-current': p.period_start === state.period ? 'true' : 'false' });
      chip.append(el('strong', { text: p.label }), el('span', { text: st.short || st.text }));
      // The lodged figure shows on the phone's list; wider screens have room for the entry beside it.
      if (p.status === 'lodged' && p.total_lal) chip.append(el('em', { text: num(p.total_lal, 3) + ' LAL' }));
      chip.addEventListener('click', function () { loadDraft(p.period_start); });
      wrap.append(chip);
    });
    if (earlier.length) {
      // Months before reminders began fold into one quiet control.
      var more = el('button', { type: 'button', className: 'excise-period excise-period--more', 'aria-expanded': String(!!state.showEarlier) });
      more.append(el('strong', { text: state.showEarlier ? 'Hide earlier months' : earlier.length + ' earlier month' + (earlier.length === 1 ? '' : 's') }), el('span', { text: 'Not tracked' }));
      more.addEventListener('click', function () { state.showEarlier = !state.showEarlier; renderPeriods(); });
      wrap.append(more);
    }
    var active = wrap.querySelector('.excise-period--active');
    // Wide screens scroll the chips to the selected period; the phone's list stays newest first.
    if (active && window.matchMedia('(min-width: 721px)').matches) {
      var right = active.offsetLeft - wrap.offsetLeft + active.offsetWidth;
      wrap.scrollLeft = right > wrap.clientWidth ? right - wrap.clientWidth + 24 : 0;
    }
  }

  async function loadPeriods() {
    var data = await api('GET', '/api/compliant/nz-alcohol/excise/periods');
    var s = data.settings || {};
    state.frequency = s.frequency || 'monthly';
    state.remindersFrom = s.reminders_from || null;
    document.getElementById('excise-frequency').value = state.frequency;
    document.getElementById('excise-tracking-from').value = s.tracking_from || '';
    var hint = page.querySelector('[data-excise-settings-hint]');
    if (hint) hint.textContent = { monthly: 'Lodging monthly', six_monthly: 'Lodging six-monthly', twelve_monthly: 'Lodging yearly' }[state.frequency] + (s.tracking_from ? ' · reminders from ' + fmtDate(s.tracking_from) : ' · reminders on');
    state.periods = data.periods || [];
    if (!state.period && state.periods.length) {
      var wanted = new URLSearchParams(window.location.search).get('period');
      var match = wanted && state.periods.find(function (p) { return p.period_start === wanted; });
      // Land on what needs doing: the oldest finished period not yet lodged, else the latest finished one.
      var todo = state.periods.filter(function (p) { return !p.open && p.status !== 'lodged' && periodStatus(p).key !== 'untracked'; });
      var pick = match || todo[todo.length - 1] || state.periods.find(function (p) { return !p.open; }) || state.periods[0];
      await loadDraft(pick.period_start);
    } else {
      renderPeriods();
    }
  }

  async function loadDraft(start) {
    state.period = start;
    renderPeriods();
    var data = await api('GET', '/api/compliant/nz-alcohol/excise?period=' + encodeURIComponent(start));
    if (state.period !== start) return;
    state.draft = data.draft;
    renderDraft(data.draft);
  }

  // --- the pieces the entry is built from ----------------------------------------------

  function headPiece(d) {
    var st = d.status === 'lodged' ? periodStatus({ status: 'lodged', lodged_on: d.lodged_on, nil_return: d.nil_return }) : periodStatus({ open: d.open, due: d.due, status: d.status });
    var head = el('div', { className: 'customs-entry-head' });
    var title = el('h3', { text: d.label + (d.open ? ' so far' : '') });
    var pill = el('span', { className: 'customs-status customs-status--' + st.key, text: st.text });
    var sub = el('p', { className: 'excise-hint', text: d.status === 'lodged'
      ? ('Recorded as lodged' + (d.entry_reference ? ' (entry ' + d.entry_reference + ')' : '') + '. These figures are locked.')
      : (d.open ? 'This period is still running; the figures will change.' : 'Lodge by ' + fmtDate(d.due) + ' (15th working day; public holidays not counted). Pay by the last working day of that month.') });
    head.append(el('div', { className: 'customs-entry-head__title' }, [title, pill]), sub);
    return head;
  }

  function problemsPiece(d) {
    var items = [];
    if (d.legacy_unavailable) items.push('Multiple-site excise needs a separate, complete entry for each source CCA. This view is for review only and cannot be recorded as lodged.');
    (d.problems || []).forEach(function (p) { items.push(p.product + ': ' + p.reason + (p.removals ? ' (' + p.removals + ' removal' + (p.removals === 1 ? '' : 's') + ' left out)' : '')); });
    if (!items.length) return null;
    var box = el('div', { className: 'customs-attention', role: 'note' });
    box.append(el('strong', { text: d.legacy_unavailable ? 'Not lodgeable here' : 'Fix before lodging' }));
    var ul = el('ul');
    items.forEach(function (t) { ul.append(el('li', { text: t })); });
    box.append(ul);
    if ((d.problems || []).length) {
      var fix = el('button', { type: 'button', className: 'customs-link', text: 'Open products and rates' });
      fix.addEventListener('click', function () { var s = page.querySelector('[data-excise-setup]'); if (s) { s.open = true; s.scrollIntoView({ behavior: 'smooth', block: 'start' }); } });
      box.append(fix);
    }
    return box;
  }

  function copyButton(value, label) {
    var b = el('button', { type: 'button', className: 'customs-copy', 'aria-label': 'Copy ' + label, title: 'Copy' , text: 'Copy' });
    b.addEventListener('click', function () {
      var done = function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 1400); };
      try { navigator.clipboard.writeText(String(value)).then(done, function () {}); } catch (_) {}
    });
    return b;
  }

  function figures(d) {
    var e = d.entry;
    if (!e || !e.lines.length) return null;
    return [
      { key: 'duty', label: 'Excise duty', value: e.total_duty },
      { key: 'levy', label: 'Alcohol levy', value: e.total_levy },
      { key: 'gst', label: 'GST on the levy', value: e.total_gst },
      { key: 'total', label: 'Total to pay Customs', value: e.total },
    ];
  }

  function tilesPiece(d) {
    var f = figures(d);
    if (!f) return null;
    var wrap = el('div', { className: 'customs-tiles' });
    f.forEach(function (x) {
      var tile = el('div', { className: 'customs-tile customs-tile--' + x.key });
      tile.append(el('span', { className: 'customs-tile__label', text: x.label }), el('span', { className: 'customs-tile__value', text: money(x.value) }));
      tile.append(copyButton(Number(x.value).toFixed(2), x.label));
      wrap.append(tile);
    });
    return wrap;
  }

  function summaryListPiece(d) {
    var f = figures(d);
    if (!f) return null;
    var dl = el('dl', { className: 'customs-summary' });
    f.forEach(function (x) {
      var row = el('div', { className: 'customs-summary__row customs-summary__row--' + x.key });
      row.append(el('dt', { text: x.label }), el('dd', { text: money(x.value) }), copyButton(Number(x.value).toFixed(2), x.label));
      dl.append(row);
    });
    return dl;
  }

  // Lodged before the entry lines existed: show the saved per-product lines as they were.
  function savedLinesPiece(d) {
    var table = el('table', { className: 'customs-entry-table' });
    table.append(el('caption', { text: 'As lodged (recorded before levy and GST were shown here)' }));
    var hr = el('tr');
    [['Excise item', ''], ['Product', ''], ['Litres', 'num'], ['LAL', 'num'], ['Rate', 'num'], ['Duty', 'num']].forEach(function (h) { hr.append(el('th', { scope: 'col', className: h[1], text: h[0] })); });
    table.append(el('thead', {}, [hr]));
    var body = el('tbody');
    d.lines.forEach(function (l) {
      var row = el('tr');
      [[l.tariff_item, 'mono', 'Excise item'], [l.product, '', 'Product'], [num(l.litres, 3), 'num', 'Litres'], [num(l.lal, 3), 'num', 'LAL'], [rateText(l), 'num', 'Rate'], [money(l.duty), 'num', 'Duty']].forEach(function (c) {
        row.append(el('td', { className: c[1], text: String(c[0]), 'data-label': c[2] }));
      });
      body.append(row);
    });
    table.append(body);
    return el('div', { className: 'customs-table-wrap customs-table-wrap--saved' }, [table]);
  }

  function entryTablePiece(d) {
    var e = d.entry;
    if (!e && (d.lines || []).length) return savedLinesPiece(d);
    if (!e || !e.lines.length) {
      var nothing = d.open ? 'Nothing removed yet this period.' : 'Nothing was removed this period: lodge a nil return.';
      return el('p', { className: 'customs-empty', text: d.legacy_unavailable ? 'No removals are shown by this legacy calculation.' : nothing });
    }
    var table = el('table', { className: 'customs-entry-table' });
    var cap = el('caption', { text: 'Entry lines, in Trade Single Window order' });
    table.append(cap);
    var hr = el('tr');
    [['Line', ''], ['Excise item', ''], ['Description', ''], ['Litres', 'num'], ['LAL', 'num'], ['Rate', 'num'], ['Duty', 'num'], ['Levy', 'num'], ['GST on levy', 'num']].forEach(function (h) { hr.append(el('th', { scope: 'col', className: h[1], text: h[0] })); });
    table.append(el('thead', {}, [hr]));
    var body = el('tbody');
    e.lines.forEach(function (l) {
      var row = el('tr');
      [[l.line, ''], [l.excise_item, 'mono'], [l.description, ''], [num(l.supplementary_litres, 3), 'num'], [num(l.statistical_lal, 3), 'num'], [rateText(l), 'num'], [money(l.duty), 'num'], [money(l.levy), 'num'], [money(l.gst_on_levy), 'num']].forEach(function (c, i) {
        var td = el('td', { className: c[1], text: String(c[0]) });
        td.setAttribute('data-label', ['Line', 'Excise item', 'Description', 'Litres', 'LAL', 'Rate', 'Duty', 'Levy', 'GST on levy'][i]);
        row.append(td);
      });
      body.append(row);
    });
    table.append(body);
    return el('div', { className: 'customs-table-wrap' }, [table]);
  }

  function breakdownPiece(d) {
    if (!(d.lines || []).length && !(d.adjustments || []).length && !(d.returns || []).length) return null;
    var det = el('details', { className: 'customs-breakdown' });
    var count = (d.lines || []).reduce(function (n, l) { return n + l.removals.length; }, 0);
    det.append(el('summary', { text: 'Where these figures come from · ' + count + ' removal' + (count === 1 ? '' : 's') }));
    (d.lines || []).forEach(function (l) {
      det.append(el('h4', { text: l.product + ' · ' + l.units + ' ' + l.unit + ' · ' + l.lal + ' LAL' }));
      var ul = el('ul');
      l.removals.forEach(function (r) {
        ul.append(el('li', { text: fmtDate(r.date) + ' · ' + (r.kind === 'sale' ? 'Sold' : 'Moved out') + ' · ' + r.quantity + (r.batch ? ' from ' + r.batch : '') + ' at ' + r.abv_percent + '% · ' + r.reference + (r.customer ? ' · ' + r.customer : '') + ' · ' + r.lal + ' LAL' }));
      });
      det.append(ul);
    });
    if ((d.adjustments || []).length) {
      det.append(el('h4', { text: 'Carried in from lodged periods' }));
      var adj = el('ul');
      d.adjustments.forEach(function (a) { adj.append(el('li', { text: a.product + ': ' + a.quantity + ' on ' + fmtDate(a.date) + ' (' + a.reference + '), ' + a.lal + ' LAL, belongs to ' + a.belongs_to_label + ' but was recorded after it was lodged' })); });
      det.append(adj);
    }
    if ((d.returns || []).length) {
      det.append(el('p', { className: 'excise-hint', text: 'Stock came back into the licensed area (' + d.returns.map(function (r) { return r.quantity + ' ' + r.unit + ' ' + r.product; }).join(', ') + '). If duty was paid when it left, raise a possible credit with Customs; it isn\'t claimed here.' }));
    }
    return det;
  }

  function linksPiece(d) {
    var wrap = el('p', { className: 'customs-links' });
    wrap.append(el('a', { href: 'https://www.tradesinglewindow.govt.nz/', target: '_blank', rel: 'noopener', text: 'Open Trade Single Window ↗' }));
    if (state.frequency === 'monthly') {
      wrap.append(document.createTextNode(' · '), el('a', { href: '/crm/excise?month=' + d.period_start.slice(0, 7), text: 'Sales behind ' + d.label }));
    }
    return wrap;
  }

  function lodgePiece(d) {
    if (d.status === 'lodged' || d.open || d.legacy_unavailable) return null;
    var nil = !(d.lines || []).length && !(d.adjustments || []).length;
    var form = el('form', { className: 'customs-lodge' });
    var ref = el('input', { name: 'entry_reference', id: 'excise-entry-ref', placeholder: 'Customs entry number (optional)', maxlength: '100', 'aria-label': 'Customs entry number' });
    var on = el('input', { name: 'lodged_on', id: 'excise-lodged-on', type: 'date', 'aria-label': 'Lodged on' });
    on.value = todayIso();
    var btn = el('button', { type: 'submit', className: 'workspace-button workspace-button--primary', text: nil ? 'Record nil return as lodged' : 'Record as lodged' });
    form.append(ref, on, btn);
    form.addEventListener('submit', async function (e) {
      e.preventDefault(); fail(''); btn.disabled = true;
      try {
        var res = await api('POST', '/api/compliant/nz-alcohol/excise/lodge', { period_start: d.period_start, lodged_on: on.value, entry_reference: ref.value });
        state.draft = res.draft; await loadPeriods(); renderDraft(res.draft);
      } catch (err) { fail(err.message); btn.disabled = false; }
    });
    return form;
  }

  function renderDraft(d) {
    var wrap = root.querySelector('[data-excise-draft]');
    wrap.replaceChildren();
    // The entry sheet: the four figures to copy (tiles when wide, a list on a phone), the lines, then record it.
    [headPiece(d), problemsPiece(d), tilesPiece(d), summaryListPiece(d), entryTablePiece(d), lodgePiece(d), linksPiece(d), breakdownPiece(d)].forEach(function (p) { if (p) wrap.append(p); });
  }

  var categories = null;
  function categorySelect(id, name, value) {
    var sel = el('select', { name: 'excise_category', id: id + '-type', 'aria-label': 'Product type for ' + name });
    sel.append(el('option', { value: '', text: 'Product type…' }));
    var groups = {};
    (categories || []).forEach(function (c) {
      if (!groups[c.group]) { groups[c.group] = el('optgroup', { label: c.group }); sel.append(groups[c.group]); }
      groups[c.group].append(el('option', { value: c.key, text: c.label }));
    });
    sel.value = value || '';
    return sel;
  }

  async function loadProducts() {
    if (categories === null) categories = (await api('GET', '/api/compliant/nz-alcohol/excise/categories')).categories;
    var data = await api('GET', '/api/compliant/nz-alcohol/excise/products');
    var wrap = page.querySelector('[data-excise-products]'); wrap.replaceChildren();
    if (!data.products.length) { wrap.append(el('p', { className: 'excise-hint', text: 'Add a workflow first; its final output appears here.' })); return; }
    data.products.forEach(function (p) {
      var f = el('form', { className: 'excise-inline-form excise-product' });
      var id = 'excise-p-' + p.name.replace(/[^a-z0-9]+/gi, '-').toLowerCase();
      var vol = el('input', { name: 'pack_volume_ml', id: id + '-vol', type: 'number', min: '1', step: '1', placeholder: 'mL per ' + (p.unit || 'unit'), 'aria-label': 'Pack volume for ' + p.name });
      var type = categorySelect(id, p.name, p.excise_category);
      var tar = el('input', { name: 'tariff_item', id: id + '-tariff', placeholder: 'Tariff item (override)', maxlength: '100', 'aria-label': 'Tariff item override for ' + p.name });
      var abv = el('input', { name: 'abv_fallback', id: id + '-abv', type: 'number', min: '0', max: '100', step: '0.1', placeholder: 'ABV fallback %', 'aria-label': 'Fallback ABV for ' + p.name });
      vol.value = p.pack_volume_ml || ''; tar.value = p.tariff_item || ''; abv.value = p.abv_fallback || '';
      f.append(el('strong', { text: p.name }), type, vol, abv, tar, el('button', { type: 'submit', text: 'Save' }));
      f.addEventListener('submit', async function (e) {
        e.preventDefault(); fail('');
        try { await api('PUT', '/api/compliant/nz-alcohol/excise/products', { name: p.name, excise_category: type.value, pack_volume_ml: vol.value, tariff_item: tar.value, abv_fallback: abv.value }); await loadProducts(); if (state.period) await loadDraft(state.period); }
        catch (err) { fail(err.message); }
      });
      wrap.append(f);
    });
  }

  async function loadRates() {
    var data = await api('GET', '/api/compliant/nz-alcohol/excise/rates');
    var wrap = page.querySelector('[data-excise-rates]'); wrap.replaceChildren();
    if (!data.rates.length) { wrap.append(el('p', { className: 'excise-hint', text: 'No overrides: every product uses the built-in rate for its type.' })); return; }
    var ul = el('ul');
    data.rates.forEach(function (r) { ul.append(el('li', { text: r.tariff_item + ': ' + money(r.rate_per_lal) + ' per LAL from ' + fmtDate(r.effective_from) })); });
    wrap.append(ul);
  }

  async function loadLocations() {
    var locs = await api('GET', '/api/core/stock-locations');
    var wrap = page.querySelector('[data-excise-locations]'); wrap.replaceChildren();
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

  page.querySelector('[data-excise-settings]').addEventListener('submit', async function (e) {
    e.preventDefault(); fail('');
    try { await api('PUT', '/api/compliant/nz-alcohol/excise/settings', { frequency: document.getElementById('excise-frequency').value, tracking_from: document.getElementById('excise-tracking-from').value || null }); state.period = null; await loadPeriods(); }
    catch (err) { fail(err.message); }
  });
  page.querySelector('[data-excise-rate-form]').addEventListener('submit', async function (e) {
    e.preventDefault(); fail(''); var f = e.currentTarget;
    try { await api('POST', '/api/compliant/nz-alcohol/excise/rates', { tariff_item: f.tariff_item.value, rate_per_lal: f.rate_per_lal.value, effective_from: f.effective_from.value }); f.reset(); await loadRates(); if (state.period) await loadDraft(state.period); }
    catch (err) { fail(err.message); }
  });
  page.querySelector('[data-excise-location-form]').addEventListener('submit', async function (e) {
    e.preventDefault(); fail(''); var f = e.currentTarget;
    try { await api('POST', '/api/core/stock-locations', { name: f.name.value, inside_licensed_area: f.inside_licensed_area.checked }); f.reset(); await loadLocations(); }
    catch (err) { fail(err.message); }
  });
  page.querySelector('[data-excise-move-form]').addEventListener('submit', async function (e) {
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
