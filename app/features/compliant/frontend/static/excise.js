// Customs page: the excise entry for each period (plan 2.1). The server builds every figure
// from recorded removals and validates every change; this script lays them out and posts
// the owner's actions. The entry lines follow Trade Single Window's column order so they
// can be copied across. Setup lives on Customs → Settings, stock on Customs → Stock.
(function () {
  'use strict';

  var TSW_LOGIN = 'https://www.tsw.govt.nz/external/application/login/app.html';
  var SETTINGS = '/compliant/nz-alcohol/customs/settings';
  var STOCK = '/compliant/nz-alcohol/customs/stock';
  var WINDOW = 3; // periods shown before "Earlier": the current one and the two before it

  // The SPA shell can swap page content in with HTMX, replacing this section after the
  // script has run; bind whichever copy is on the page now, once.
  function init() {
  var root = document.querySelector('[data-excise-root]');
  if (!root || root.dataset.bound === '1' || !window.CustomsUI) return;
  root.dataset.bound = '1';
  var page = root.closest('[data-compliant-root]') || document.body;
  var U = window.CustomsUI;
  var el = U.el, api = U.api, fmtDate = U.fmtDate, shortDate = U.shortDate, money = U.money, num = U.num;
  var fail = U.failer(page);
  var periodsEl = root.querySelector('[data-excise-periods]');
  var draftEl = root.querySelector('[data-excise-draft]');
  var positionEl = page.querySelector('[data-customs-position]');

  var state = { period: null, periods: [], draft: null, frequency: 'monthly', remindersFrom: null, showAll: false, showUntracked: false, position: null };

  // CONCEPT ONLY: three page styles behind one switch; removed once one is picked.
  function readStyle() {
    var q = new URLSearchParams(window.location.search).get('style');
    if (q === '1' || q === '2' || q === '3') return q;
    try { var s = window.localStorage.getItem('customs.style.v2'); if (s === '1' || s === '2' || s === '3') return s; } catch (_) {}
    return '1';
  }
  function style() { return page.getAttribute('data-customs-style') || '1'; }
  function setStyle(s) {
    page.setAttribute('data-customs-style', s);
    try { window.localStorage.setItem('customs.style.v2', s); } catch (_) {}
    page.querySelectorAll('[data-customs-style-pick] [data-style]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-style') === s)); });
    renderPeriods();
  }
  page.querySelectorAll('[data-customs-style-pick] [data-style]').forEach(function (b) {
    b.addEventListener('click', function () { setStyle(b.getAttribute('data-style')); });
  });
  setStyle(readStyle());

  function rateText(l) {
    if (!l.rate) return 'no rate';
    return '$' + l.rate + (l.basis === 'per_litre' ? ' /L' : ' /LAL');
  }

  // A period's status in words: never colour alone.
  function periodStatus(p) {
    if (p.status === 'lodged') return { key: 'lodged', text: p.nil_return ? 'Nil return lodged ' + shortDate(p.lodged_on) : 'Lodged ' + shortDate(p.lodged_on) };
    if (p.open) return { key: 'open', text: 'In progress' };
    // Before reminders began: nobody was asked to lodge it here, so it isn't "overdue".
    if (state.remindersFrom && p.period_end && p.period_end < state.remindersFrom) return { key: 'untracked', text: 'Not tracked' };
    var days = U.daysUntil(p.due);
    if (days < 0) return { key: 'overdue', text: 'Overdue · was due ' + shortDate(p.due), short: 'Overdue' };
    if (days === 0) return { key: 'due', text: 'Due today' };
    return { key: 'due', text: 'Due ' + shortDate(p.due) + ' · ' + U.plural(days, 'day') + ' left', short: 'Due ' + shortDate(p.due) };
  }
  function shortLabel(p) {
    // "October 2026" -> "Oct 2026"; six- and twelve-monthly labels are already short ranges.
    return state.frequency === 'monthly' ? p.label.replace(/^(\w{3})\w* /, '$1 ') : p.label;
  }

  function periodButton(p) {
    var st = periodStatus(p);
    var active = p.period_start === state.period;
    var chip = el('button', { type: 'button', role: 'listitem', className: 'excise-period excise-period--' + st.key + (active ? ' excise-period--active' : ''), 'data-period': p.period_start, 'data-period-status': st.key, 'aria-current': active ? 'true' : 'false' });
    chip.append(el('strong', { className: 'excise-period__label', text: shortLabel(p) }), el('span', { className: 'excise-period__status', text: st.short || st.text }));
    // The Ledger shows each period's figures in its row; the boxes leave them to the entry.
    chip.append(el('em', { className: 'excise-period__lal', text: p.status === 'lodged' && p.total_lal != null ? num(p.total_lal, 3) + ' LAL' : '' }));
    chip.append(el('em', { className: 'excise-period__total', text: p.status === 'lodged' && p.total != null ? money(p.total) : '' }));
    chip.addEventListener('click', function () { loadDraft(p.period_start); });
    return chip;
  }

  function renderPeriods() {
    periodsEl.replaceChildren();
    if (!state.periods.length) return;
    var untracked = function (p) { return periodStatus(p).key === 'untracked' && p.period_start !== state.period; };
    var recent = state.periods.slice(0, WINDOW);
    var older = state.periods.slice(WINDOW);
    var shown = state.showAll ? state.periods : recent;
    shown.forEach(function (p) {
      if (untracked(p) && !state.showUntracked) return;
      periodsEl.append(periodButton(p));
    });
    if (state.showAll) {
      var notTracked = older.filter(untracked);
      if (notTracked.length) {
        var nt = el('button', { type: 'button', className: 'excise-period excise-period--more excise-period--untracked-toggle', 'aria-expanded': String(state.showUntracked) });
        nt.append(el('strong', { text: state.showUntracked ? 'Hide months not tracked' : U.plural(notTracked.length, 'earlier month') }), el('span', { text: 'Not tracked' }));
        nt.addEventListener('click', function () { state.showUntracked = !state.showUntracked; renderPeriods(); });
        periodsEl.append(nt);
      }
    }
    if (older.length) {
      // Older periods fold into one control that says what is waiting in there. When the
      // period on screen is one of them, the control stands in for it, so three boxes stay three.
      var waiting = older.filter(function (p) { var k = periodStatus(p).key; return k === 'overdue' || k === 'due'; }).length;
      var picked = !state.showAll && older.find(function (p) { return p.period_start === state.period; });
      var more = el('button', { type: 'button', className: 'excise-period excise-period--more' + (picked ? ' excise-period--active excise-period--' + periodStatus(picked).key : ''), 'data-periods-earlier': '', 'aria-expanded': String(state.showAll) });
      var moreLabel = state.showAll ? 'Fewer' : (picked ? shortLabel(picked) : 'Earlier');
      var moreNote = state.showAll ? 'Back to the last ' + WINDOW : (picked ? 'Earlier · ' + (periodStatus(picked).short || periodStatus(picked).text) : (waiting ? U.plural(waiting, 'to lodge', 'to lodge') : older.length + ' more'));
      more.append(el('strong', { text: moreLabel }), el('span', { className: !state.showAll && waiting ? 'excise-period__waiting' : '', text: moreNote }));
      more.addEventListener('click', function () { state.showAll = !state.showAll; renderPeriods(); });
      periodsEl.append(more);
    }
    // The Ledger opens the selected row in place; the other styles keep the entry below the periods.
    var active = periodsEl.querySelector('.excise-period--active');
    if (style() === '3' && active) active.after(draftEl);
    else if (draftEl.previousElementSibling !== periodsEl) periodsEl.after(draftEl);
  }

  async function loadPeriods() {
    var data = await api('GET', '/api/compliant/nz-alcohol/excise/periods');
    var s = data.settings || {};
    state.frequency = s.frequency || 'monthly';
    state.remindersFrom = s.reminders_from || null;
    state.periods = data.periods || [];
    if (!state.period && state.periods.length) {
      var wanted = new URLSearchParams(window.location.search).get('period');
      var match = wanted && state.periods.find(function (p) { return p.period_start === wanted; });
      // Land on what needs doing: the oldest finished period not yet lodged, else the latest finished one.
      var todo = state.periods.filter(function (p) { return !p.open && p.status !== 'lodged' && periodStatus(p).key !== 'untracked'; });
      var pick = match || todo[todo.length - 1] || state.periods.find(function (p) { return !p.open; }) || state.periods[0];
      if (periodStatus(pick).key === 'untracked') state.showUntracked = true;
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

  function isNil(d) { return !(d.lines || []).length && !(d.adjustments || []).length; }

  function headPiece(d) {
    var st = d.status === 'lodged' ? periodStatus({ status: 'lodged', lodged_on: d.lodged_on, nil_return: d.nil_return }) : periodStatus({ open: d.open, due: d.due, status: d.status, period_end: d.period_end });
    var head = el('div', { className: 'customs-entry-head' });
    var title = el('h3', { text: d.label + (d.open ? ' so far' : '') });
    var pill = el('span', { className: 'customs-status customs-status--' + st.key, text: st.text });
    var sub;
    if (d.status === 'lodged') sub = 'Recorded as lodged' + (d.entry_reference ? ' (entry ' + d.entry_reference + ')' : '') + '. These figures are locked.';
    else if (d.open) sub = 'Still running: the figures change as stock leaves the licensed area. Lodge after ' + fmtDate(d.period_end) + '.';
    else sub = 'Lodge by ' + fmtDate(d.due) + ' (15th working day). Pay by the last working day of that month.';
    head.append(el('div', { className: 'customs-entry-head__title' }, [title, pill]), el('p', { className: 'excise-hint', text: sub }));
    if (st.key === 'overdue') {
      head.append(el('p', { className: 'customs-late', text: 'Customs adds 1% to unpaid duty the day after it is due, and another 4% after 7 days. Lodge and pay as soon as you can.' }));
    }
    return head;
  }

  function problemsPiece(d) {
    var items = [];
    if (d.legacy_unavailable) items.push({ text: 'Multiple-site excise needs a separate, complete entry for each source CCA. This view is for review only and cannot be recorded as lodged.' });
    (d.problems || []).forEach(function (p) {
      items.push({ text: p.product + ': ' + p.reason + (p.removals ? ' (' + U.plural(p.removals, 'removal') + ' left out)' : ''), href: SETTINGS + '#product-' + U.slug(p.product) });
    });
    if (!items.length) return null;
    var box = el('div', { className: 'customs-attention', role: 'note' });
    box.append(el('strong', { text: d.legacy_unavailable ? 'Not lodgeable here' : 'Fix before lodging' }));
    var ul = el('ul');
    items.forEach(function (t) {
      var li = el('li', { text: t.text + ' ' });
      if (t.href) li.append(el('a', { href: t.href, text: 'Fix in Settings' }));
      ul.append(li);
    });
    box.append(ul);
    return box;
  }

  function copyButton(value, label) {
    var b = el('button', { type: 'button', className: 'customs-copy', 'aria-label': 'Copy ' + label, title: 'Copy', text: 'Copy' });
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
    [['Excise item', ''], ['Product', ''], ['Units', 'num'], ['Litres', 'num'], ['LAL', 'num'], ['Rate', 'num'], ['Duty', 'num']].forEach(function (h) { hr.append(el('th', { scope: 'col', className: h[1], text: h[0] })); });
    table.append(el('thead', {}, [hr]));
    var body = el('tbody');
    d.lines.forEach(function (l) {
      var row = el('tr');
      [[l.tariff_item, 'mono', 'Excise item'], [l.product, '', 'Product'], [U.qty(l.units) + ' ' + l.unit, 'num', 'Units'], [num(l.litres, 3), 'num', 'Litres'], [num(l.lal, 3), 'num', 'LAL'], [rateText(l), 'num', 'Rate'], [money(l.duty), 'num', 'Duty']].forEach(function (c) {
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
      if (d.legacy_unavailable) return el('p', { className: 'customs-empty', text: 'No removals are shown by this legacy calculation.' });
      if (d.open) return el('p', { className: 'customs-empty', text: 'Nothing has left the licensed area yet this period.' });
      return el('div', { className: 'customs-empty customs-empty--nil' }, [
        el('strong', { text: 'Nothing was removed this period.' }),
        el('span', { text: ' Customs still needs a nil return: lodge 0.000 against your usual excise item, then record it here.' }),
      ]);
    }
    var cols = [
      ['Line', '', function (l) { return l.line; }],
      ['Excise item', 'mono', function (l) { return l.excise_item; }],
      ['Description', 'desc', function (l) { return l.description; }],
      ['Units sold', 'num', function (l) { return l.units != null ? U.amount(l.units, l.unit) : '—'; }],
      ['Litres', 'num', function (l) { return num(l.supplementary_litres, 3); }],
      ['LAL', 'num', function (l) { return num(l.statistical_lal, 3); }],
      ['Rate', 'num', function (l) { return rateText(l); }],
      ['Duty', 'num', function (l) { return money(l.duty); }],
      ['Levy', 'num', function (l) { return money(l.levy); }],
      ['GST on levy', 'num', function (l) { return money(l.gst_on_levy); }],
    ];
    var table = el('table', { className: 'customs-entry-table' });
    table.append(el('caption', { text: 'Entry lines, in Trade Single Window order' }));
    var hr = el('tr');
    cols.forEach(function (c) { hr.append(el('th', { scope: 'col', className: c[1], text: c[0] })); });
    table.append(el('thead', {}, [hr]));
    var body = el('tbody');
    e.lines.forEach(function (l) {
      var row = el('tr');
      cols.forEach(function (c) { row.append(el('td', { className: c[1], text: String(c[2](l)), 'data-label': c[0] })); });
      body.append(row);
    });
    table.append(body);
    return el('div', { className: 'customs-table-wrap' }, [table]);
  }

  function creditPiece(d) {
    if (!(d.returns || []).length) return null;
    var what = d.returns.map(function (r) { return U.qty(r.quantity) + ' ' + r.unit + ' ' + r.product; }).join(', ');
    return el('p', { className: 'customs-note', text: 'Stock came back into the licensed area this period (' + what + '). If duty was paid when it left, it may be a duty credit: Trade Single Window has a separate Duty credit field.' });
  }

  function breakdownPiece(d) {
    if (!(d.lines || []).length && !(d.adjustments || []).length) return null;
    var det = el('details', { className: 'customs-breakdown' });
    var count = (d.lines || []).reduce(function (n, l) { return n + l.removals.length; }, 0);
    det.append(el('summary', { text: 'Where these figures come from · ' + U.plural(count, 'removal') }));
    var kinds = { sale: 'Sold', moved_out: 'Moved out' };
    (d.lines || []).forEach(function (l) {
      det.append(el('h4', { text: l.product + ' · ' + U.amount(l.units, l.unit) + ' · ' + l.lal + ' LAL' }));
      var ul = el('ul');
      l.removals.forEach(function (r) {
        ul.append(el('li', { text: fmtDate(r.date) + ' · ' + (kinds[r.kind] || r.kind) + ' · ' + r.quantity + (r.batch ? ' from ' + r.batch : '') + ' at ' + r.abv_percent + '% · ' + r.reference + (r.customer ? ' · ' + r.customer : '') + ' · ' + r.lal + ' LAL' }));
      });
      det.append(ul);
    });
    if ((d.adjustments || []).length) {
      det.append(el('h4', { text: 'Carried in from lodged periods' }));
      var adj = el('ul');
      d.adjustments.forEach(function (a) { adj.append(el('li', { text: a.product + ': ' + a.quantity + ' on ' + fmtDate(a.date) + ' (' + a.reference + '), ' + a.lal + ' LAL, belongs to ' + a.belongs_to_label + ' but was recorded after it was lodged' })); });
      det.append(adj);
    }
    return det;
  }

  function linksPiece(d) {
    var wrap = el('p', { className: 'customs-links' });
    wrap.append(el('a', { href: TSW_LOGIN, target: '_blank', rel: 'noopener', 'data-tsw-link': '', text: 'Open Trade Single Window ↗' }));
    if (state.frequency === 'monthly') {
      wrap.append(document.createTextNode(' · '), el('a', { href: '/crm/excise?month=' + d.period_start.slice(0, 7), text: 'Sales behind ' + d.label }));
    }
    return wrap;
  }

  function lodgePiece(d) {
    if (d.status === 'lodged' || d.open || d.legacy_unavailable) return null;
    var nil = isNil(d);
    var form = el('form', { className: 'customs-lodge' });
    var ref = el('input', { name: 'entry_reference', id: 'excise-entry-ref', placeholder: 'Customs entry number (optional)', maxlength: '100', 'aria-label': 'Customs entry number' });
    var on = el('input', { name: 'lodged_on', id: 'excise-lodged-on', type: 'date', 'aria-label': 'Lodged on' });
    on.value = U.todayIso();
    var btn = el('button', { type: 'submit', className: 'workspace-button workspace-button--primary', text: nil ? 'Record nil return as lodged' : 'Record as lodged' });
    form.append(ref, on, btn);
    form.addEventListener('submit', async function (e) {
      e.preventDefault(); fail(''); btn.disabled = true;
      try {
        var res = await api('POST', '/api/compliant/nz-alcohol/excise/lodge', { period_start: d.period_start, lodged_on: on.value, entry_reference: ref.value });
        state.draft = res.draft; await loadPeriods(); renderDraft(res.draft); loadPosition();
        page.dispatchEvent(new CustomEvent('customs:lodged'));
      } catch (err) { fail(err.message); btn.disabled = false; }
    });
    return form;
  }

  function renderDraft(d) {
    draftEl.replaceChildren();
    // The entry sheet: the four figures to copy (tiles when wide, a list on a phone), the lines, then record it.
    [headPiece(d), problemsPiece(d), tilesPiece(d), summaryListPiece(d), entryTablePiece(d), creditPiece(d), lodgePiece(d), linksPiece(d), breakdownPiece(d)].forEach(function (p) { if (p) draftEl.append(p); });
  }

  // --- where things stand -----------------------------------------------------------------

  function renderPosition(p) {
    if (!positionEl) return;
    positionEl.replaceChildren();
    var y = p.year || {}; var st = p.stocktake || {}; var setup = p.setup || {};
    var toLodge = p.unlodged_periods || 0;
    var lodgeFact = toLodge
      ? U.fact('To lodge', U.plural(toLodge, 'entry', 'entries'), p.overdue_periods ? p.overdue_periods + ' overdue' : 'Next due ' + shortDate((state.periods.find(function (x) { return !x.open && x.status !== 'lodged'; }) || {}).due), p.overdue_periods ? 'bad' : 'warn')
      : U.fact('To lodge', 'All lodged', 'Next: ' + (p.this_period || {}).label + ' after it ends', 'good');
    var thisPeriod = p.this_period || {};
    var periodFact = U.fact(thisPeriod.label ? thisPeriod.label + ' so far' : 'This period', thisPeriod.estimate != null ? money(thisPeriod.estimate) : num(thisPeriod.total_lal || 0, 3) + ' LAL', thisPeriod.estimate != null ? num(thisPeriod.total_lal || 0, 3) + ' LAL removed' : 'Estimate once every product is set up');
    var stockFact = st.open_differences
      ? U.fact('Stocktake', U.plural(st.open_differences, 'difference') + ' open', money(st.open_duty) + ' duty if removed', 'warn')
      : U.fact('Stocktake', st.next_due ? (st.overdue ? 'Overdue' : 'Due ' + U.dayMonth(st.next_due)) : 'Not scheduled', st.last_completed_on ? 'Last counted ' + fmtDate(st.last_completed_on) : 'No stocktake yet', st.overdue ? 'bad' : '');
    var yearFact = U.fact('Duty, last 12 months', U.wholeMoney(y.duty), y.estimated_duty && Number(y.estimated_duty) ? U.wholeMoney(y.lodged_duty) + ' lodged + ' + U.wholeMoney(y.estimated_duty) + ' to lodge' : U.plural(y.lodged_periods || 0, 'entry', 'entries') + ' lodged');
    var facts = el('div', { className: 'customs-position__facts' }, [lodgeFact, periodFact, yearFact, stockFact]);
    if ((setup.incomplete || []).length) facts.append(U.fact('Setup', U.plural(setup.incomplete.length, 'product') + ' to finish', setup.incomplete.slice(0, 2).join(', '), 'warn'));

    // One sentence for the Ledger: the same facts, read in a breath.
    var bits = [toLodge ? U.plural(toLodge, 'entry', 'entries') + ' to lodge' + (p.overdue_periods ? ' (' + p.overdue_periods + ' overdue)' : '') : 'Every entry lodged'];
    bits.push(U.wholeMoney(y.duty) + ' duty in the last 12 months');
    bits.push(st.open_differences ? U.plural(st.open_differences, 'stocktake difference') + ' open' : (st.next_due ? 'stocktake ' + (st.overdue ? 'overdue' : 'due ' + U.dayMonth(st.next_due)) : 'no stocktake scheduled'));
    var line = el('p', { className: 'customs-position__line', text: bits.join(' · ') + '.' });

    var more = el('div', { className: 'customs-position__more' });
    var cadence = el('div', { className: 'customs-position__block' }, [el('h3', { text: 'How often you lodge' })]);
    var freqName = { monthly: 'monthly', six_monthly: 'six-monthly', twelve_monthly: 'yearly' }[p.frequency] || 'monthly';
    var allowed = y.twelve_monthly_allowed ? 'yearly' : (y.six_monthly_allowed ? 'six-monthly' : null);
    var cadenceText = 'You lodge ' + freqName + '.';
    if (allowed && p.frequency === 'monthly') cadenceText += ' At ' + U.wholeMoney(y.duty) + ' a year you could ask Customs to lodge ' + allowed + ' (up to ' + U.wholeMoney(allowed === 'yearly' ? y.twelve_monthly_limit : y.six_monthly_limit) + ')' + (y.monthly_until && y.monthly_until > U.todayIso() ? ' once you have lodged monthly until ' + fmtDate(y.monthly_until) : '') + '.';
    cadence.append(el('p', { className: 'excise-hint', text: cadenceText }), el('a', { href: SETTINGS + '#lodging', text: 'Lodging settings' }));
    more.append(cadence);
    var rem = el('div', { className: 'customs-position__block' }, [el('h3', { text: 'Remissions to claim' })]);
    if ((p.remissions || []).length) {
      var ul = el('ul', { className: 'customs-position__list' });
      p.remissions.slice(0, 4).forEach(function (r) { ul.append(el('li', { text: U.amount(r.quantity, r.unit) + ' ' + r.product + ' broken ' + U.dayMonth(r.date) + (r.duty ? ' · ' + money(Math.abs(r.duty)) : '') })); });
      rem.append(ul, el('p', { className: 'excise-hint', text: 'Broken or damaged stock is dutiable unless Customs remits it (form NZCS 277).' }));
    } else {
      rem.append(el('p', { className: 'excise-hint', text: 'None: no breakage recorded at a stocktake in the last 12 months.' }));
    }
    rem.append(el('a', { href: STOCK, text: 'Stock and stocktake' }));
    more.append(rem);
    positionEl.append(line, facts, more);
  }

  async function loadPosition() {
    try { state.position = await api('GET', '/api/compliant/nz-alcohol/excise/position'); renderPosition(state.position); }
    catch (err) { fail(err.message); }
  }

  Promise.all([loadPeriods(), loadPosition()]).catch(function (err) { fail(err.message); }).finally(function () {
    // The "next due" fact reads the periods, which may land after the position.
    if (state.position) renderPosition(state.position);
    page.setAttribute('aria-busy', 'false');
  });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  document.addEventListener('htmx:afterSwap', init);
})();
