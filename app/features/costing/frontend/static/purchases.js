/* Purchases (live-cogs 8.1d): record what was bought in Xero into stock.
   Binds to the page root on every load (boosted navigation swaps #page-content only). */
(function () {
  'use strict';
  var API = '/api/core/costing/purchases';
  var REVIEW_TEXT = {
    amount_changed: 'The amount changed in Xero',
    recoded: 'Recoded in Xero to an account that isn’t stock',
    deleted_in_xero: 'Deleted or changed in Xero'
  };
  var money = new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' });

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }
  function num(value) {  // "2.0000" -> "2", "18.4022" stays as typed precision
    if (value === null || value === undefined || value === '') return '';
    var n = Number(value);
    return isFinite(n) ? String(Math.round(n * 10000) / 10000) : String(value);
  }
  /* Money as typed: at least 2 dp, up to 4, never rounded through a float ("10.0050" stays). */
  function cents(value) {
    if (value === null || value === undefined || value === '') return '';
    var m = String(value).trim().match(/^(-?)(\d*)(?:\.(\d*))?$/);
    if (!m) return String(value);
    var frac = (m[3] || '').replace(/0+$/, '');
    while (frac.length < 2) frac += '0';
    return m[1] + (m[2] || '0') + '.' + frac.slice(0, 4);
  }
  /* "12.3456" -> 123456 ten-thousandths; null when it isn't money. Sums stay exact. */
  function units(value) {
    var m = String(value == null ? '' : value).trim().replace(/[$,\s]/g, '').match(/^(-?)(\d+)(?:\.(\d{1,4}))?$/);
    if (!m) return null;
    var n = Number(m[2]) * 10000 + Number(((m[3] || '') + '0000').slice(0, 4));
    return m[1] ? -n : n;
  }
  function fromUnits(n) {
    var sign = n < 0 ? '-' : '';
    n = Math.abs(n);
    var whole = Math.floor(n / 10000);
    var frac = String(n % 10000).padStart(4, '0');
    return cents(sign + whole + '.' + frac);
  }
  function fmt(value) { return value === null || value === undefined ? '—' : money.format(Number(value)); }
  function fmtDate(iso, withYear) {
    if (!iso) return '';
    var d = new Date(iso + 'T00:00:00');
    var opts = { day: 'numeric', month: 'short' };
    if (withYear) opts.year = 'numeric';
    return d.toLocaleDateString('en-NZ', opts);
  }
  function uuid() {
    return (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()) + Math.random();
  }

  function init(root) {
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    var canManage = root.dataset.canManage === 'true';
    var canAdjust = root.dataset.canAdjust === 'true';
    var overheadsOn = root.dataset.overheads === 'true'; // 8.1h: freight can be added to the cost of stock
    var list = root.querySelector('[data-purchases-list]');
    var state = root.querySelector('[data-purchases-state]');
    var errorBox = root.querySelector('[data-purchases-error]');
    var toast = root.querySelector('[data-purchases-toast]');
    var dialog = root.querySelector('[data-purchases-dialog]');
    var batchbar = root.querySelector('[data-purchases-batchbar]');
    var tab = 'to_record';
    var history = null; // {from, to} while looking at a historical run
    var loadSeq = 0;
    var xeroConnected = root.dataset.xeroConnected === 'true';
    var cards = [];
    var selected = {};

    async function call(path, init) {
      var token = document.querySelector('meta[name="csrf-token"]');
      var res = await fetch(path, Object.assign({ credentials: 'same-origin' }, init || {}, {
        headers: Object.assign({
          'Content-Type': 'application/json',
          'X-CSRFToken': token ? token.content : ''
        }, (init && init.headers) || {})
      }));
      var body = null;
      try { body = await res.json(); } catch (e) { body = null; }
      if (!res.ok) {
        var err = new Error((body && body.error) || 'Something went wrong (' + res.status + ')');
        err.status = res.status;
        err.code = body && body.code;
        throw err;
      }
      return body;
    }
    /* The same action with the same body reuses its key until it succeeds or the server refuses
       it, so a retry after a lost reply replays instead of recording twice. */
    var actionKeys = {};
    async function post(path, body, method) {
      var payload = JSON.stringify(body || {});
      var id = (method || 'POST') + ' ' + path + ' ' + payload;
      if (!actionKeys[id]) actionKeys[id] = uuid();
      try {
        var out = await call(path, { method: method || 'POST', body: payload, headers: { 'Idempotency-Key': actionKeys[id] } });
        delete actionKeys[id];
        return out;
      } catch (err) {
        if (err.status && err.status < 500) delete actionKeys[id]; // refused: the next try is new
        throw err;
      }
    }
    /* Disable every control on a card while one of its actions is in flight. */
    function busy(node, on) {
      if (!node) return;
      node.querySelectorAll('button, input, select').forEach(function (c) { c.disabled = on; });
      node.setAttribute('aria-busy', on ? 'true' : 'false');
    }
    function showError(message) { errorBox.textContent = message || ''; errorBox.hidden = !message; }
    function showToast(text, action) {
      toast.replaceChildren(el('span', null, text));
      if (action) {
        var btn = el('button', 'workspace-button', action.label);
        btn.type = 'button';
        btn.addEventListener('click', function () { toast.hidden = true; action.run(); });
        toast.appendChild(btn);
      }
      toast.hidden = false;
      clearTimeout(showToast.timer);
      showToast.timer = setTimeout(function () { toast.hidden = true; }, 9000);
    }

    // --- loading -----------------------------------------------------------------------------
    function listUrl() {
      var url = API + '?tab=' + encodeURIComponent(tab);
      if (history) url += '&historical=1&from=' + history.from + '&to=' + history.to;
      return url;
    }
    async function load(keepError) {
      var seq = ++loadSeq; // only the newest request for the current tab and range may render
      root.setAttribute('aria-busy', 'true');
      if (!keepError) showError('');
      if (!xeroConnected) { renderNoXero(); root.setAttribute('aria-busy', 'false'); return; }
      try {
        var body = await call(listUrl());
        if (seq !== loadSeq) return;
        cards = body.cards || [];
        Object.keys(body.counts || {}).forEach(function (key) {
          var span = root.querySelector('[data-count="' + key + '"]');
          if (span) span.textContent = body.counts[key] ? String(body.counts[key]) : '';
        });
        selected = {};
        render();
      } catch (err) {
        if (seq !== loadSeq) return;
        state.textContent = '';
        showError(err.message);
      } finally {
        if (seq === loadSeq) root.setAttribute('aria-busy', 'false');
      }
      renderHistoryBar();
    }

    function renderNoXero() {
      list.replaceChildren();
      state.textContent = '';
      root.querySelector('[data-purchases-tabs]').hidden = true;
      var box = root.querySelector('[data-purchases-noxero]');
      if (box) box.hidden = false;
    }

    var historyBar = root.querySelector('[data-purchases-history]');
    function renderHistoryBar() {
      if (!historyBar) return;
      historyBar.hidden = !history;
      if (!history) return;
      historyBar.querySelector('[data-history-range]').textContent =
        'Earlier purchases, ' + fmtDate(history.from, true) + ' to ' + fmtDate(history.to, true);
    }

    // --- rendering ---------------------------------------------------------------------------
    function render() {
      list.replaceChildren();
      updateBatchbar();
      if (!cards.length) {
        state.textContent = tab === 'to_record'
          ? 'Nothing to record. New purchases arrive with each Xero sync.'
          : 'Nothing here.';
        return;
      }
      state.textContent = '';
      cards.forEach(function (card) { list.appendChild(cardNode(card)); });
    }

    function what(card) {
      var wrap = el('div', 'pu-what');
      var top = el('div', 'pu-what__top');
      top.appendChild(el('strong', 'pu-payee', card.document.payee || 'Unknown payee'));
      top.appendChild(el('span', 'pu-amount', fmt(card.amount)));
      wrap.appendChild(top);
      var meta = el('div', 'pu-meta');
      meta.appendChild(el('span', null, fmtDate(card.document.date)));
      if (card.document.source && card.document.source !== 'xero_bank' && card.document.reference) {
        meta.appendChild(el('span', null, card.document.reference)); // "Bill INV-0042 · PO 77"
      }
      if (card.description) meta.appendChild(el('span', null, card.description));
      meta.appendChild(el('span', null, card.account.name || card.account.code || ''));
      wrap.appendChild(meta);
      return wrap;
    }

    function badges(card) {
      var wrap = el('div', 'pu-badges');
      if (card.review_reason) wrap.appendChild(el('span', 'pu-badge pu-badge--warn', REVIEW_TEXT[card.review_reason] || 'Check this'));
      if (card.document.source === 'xero_bill') wrap.appendChild(el('span', 'pu-badge', 'Bill'));
      else if (card.document.source === 'xero_bill_credit') wrap.appendChild(el('span', 'pu-badge', 'Supplier credit'));
      else if (card.document.kind === 'refund') wrap.appendChild(el('span', 'pu-badge', 'Refund'));
      if (card.freight) wrap.appendChild(el('span', 'pu-badge pu-badge--ok', 'Freight'));
      if (card.state === 'partly_recorded') wrap.appendChild(el('span', 'pu-badge', fmt(card.open) + ' still to record'));
      if (card.state === 'recorded') {
        wrap.appendChild(el('span', 'pu-badge pu-badge--ok', card.auto_recorded ? 'Recorded by a rule' : 'Recorded'));
      }
      return wrap;
    }

    function proposal(card) {
      var wrap = el('div', 'pu-propose');
      if (tab !== 'to_record' || card.review_reason || card.document.kind === 'refund') return wrap;
      var pre = card.prefill;
      if (!pre || !pre.rows) return wrap;
      var title = pre.source === 'rule' ? 'Usually' : pre.source === 'last_time' ? 'Last time' : 'Nothing known yet';
      wrap.appendChild(el('span', 'pu-propose__title', title));
      if (pre.source !== 'none') {
        var ul = el('ul', 'pu-propose__rows');
        pre.rows.forEach(function (r) {
          ul.appendChild(el('li', null, (r.quantity ? num(r.quantity) + ' ' + r.unit + ' ' : '') + r.name + ' · ' + fmt(r.amount)));
        });
        wrap.appendChild(ul);
      }
      return wrap;
    }

    function actions(card, compact) {
      var wrap = el('div', 'pu-actions');
      if (!canManage) return wrap;
      function btn(label, primary, fn) {
        var b = el('button', 'workspace-button' + (primary ? ' workspace-button--primary' : ''), label);
        b.type = 'button';
        b.addEventListener('click', function (ev) { ev.stopPropagation(); fn(ev); });
        wrap.appendChild(b);
        return b;
      }
      if (card.review_reason) {
        btn('Keep as recorded', true, function () { act(card, 'review', { action: 'keep' }); });
        if (canAdjust && (card.allocations || []).length) btn('Edit amounts', false, function (ev) { openAllocations(card, ev); });
        if (canAdjust) btn('Unlink from stock', false, function () { act(card, 'review', { action: 'unlink' }); });
        return wrap;
      }
      if (tab === 'skipped' || tab === 'not_stock') {
        btn('Undo', false, function () { act(card, 'reopen'); });
        return wrap;
      }
      if (tab === 'recorded') return wrap;
      if (card.document.kind === 'refund') {
        if (canAdjust) btn('Lower the cost of…', true, function (ev) { openPick(card, 'refund', ev); });
        btn('Not stock', false, function () { act(card, 'not-stock'); });
        return wrap;
      }
      if (canAdjust) btn(card.prefill && card.prefill.source === 'rule' ? 'OK' : 'Record stock', true, function (ev) { openRecord(card, ev); });
      if (!compact && canAdjust) btn('Already in stock', false, function (ev) { openPick(card, 'link', ev); });
      btn('Not stock', false, function () { act(card, 'not-stock'); });
      if (overheadsOn && !compact) {
        var freight = btn('It’s freight', false, function () { act(card, 'freight'); });
        freight.title = 'Add this to the cost of the other stock on the same purchase';
      }
      btn('Skip', false, function () { act(card, 'skip'); });
      return wrap;
    }

    function cardNode(card) {
      var node = el('article', 'pu-card workspace-card');
      node.dataset.lineId = card.line_id;
      var left = el('div', 'pu-card__left');
      if (canManage && tab === 'to_record' && !history) {
        // Pick several to skip or mark not stock together.
        var check = el('input', 'pu-select');
        check.type = 'checkbox';
        check.setAttribute('aria-label', 'Select ' + (card.document.payee || 'purchase') + ' ' + fmt(card.amount));
        check.checked = !!selected[card.line_id];
        check.addEventListener('change', function () {
          if (check.checked) selected[card.line_id] = true; else delete selected[card.line_id];
          updateBatchbar();
        });
        node.classList.add('pu-card--selectable');
        node.appendChild(check);
      }
      left.appendChild(what(card));
      left.appendChild(badges(card));
      var right = el('div', 'pu-card__right');
      var pro = proposal(card);
      var acts = actions(card, false);
      right.appendChild(pro);
      right.appendChild(acts);
      node.appendChild(left);
      node.appendChild(right);
      if (!pro.childElementCount && !acts.childElementCount) node.classList.add('pu-card--solo');
      return node;
    }

    function updateBatchbar() {
      var count = Object.keys(selected).length;
      batchbar.hidden = count === 0;
      root.querySelector('[data-purchases-selected]').textContent = count + ' selected';
    }
    batchbar.addEventListener('click', async function (ev) {
      var action = ev.target && ev.target.dataset ? ev.target.dataset.batch : null;
      if (!action) return;
      if (action === 'cancel') { selected = {}; render(); return; }
      busy(batchbar, true);
      try {
        var body = await post(API + '/bulk', { line_ids: Object.keys(selected), action: action });
        var failed = (body.results || []).filter(function (r) { return !r.ok; }).length;
        showToast((body.results.length - failed) + ' done' + (failed ? ', ' + failed + ' not changed' : ''));
        await load();
      } catch (err) { showError(err.message); }
      busy(batchbar, false);
    });

    // --- actions -------------------------------------------------------------------------------
    async function act(card, action, body) {
      var node = list.querySelector('[data-line-id="' + card.line_id + '"]');
      busy(node, true);
      try {
        await post(API + '/' + card.line_id + '/' + action, body);
        var undo = action === 'skip' || action === 'not-stock' || action === 'freight';
        showToast(action === 'skip' ? 'Skipped' : action === 'not-stock' ? 'Marked not stock'
          : action === 'freight' ? 'Marked as freight' : 'Done',
          undo ? { label: 'Undo', run: function () { act(card, 'reopen'); } } : null);
        await load();
      } catch (err) {
        busy(node, false); // the card stays as it was, ready to try again
        showError(err.message);
      }
    }

    function field(labelText, input) {
      var label = el('label', 'pu-field');
      label.appendChild(el('span', null, labelText));
      label.appendChild(input);
      return label;
    }
    function input(type, value, attrs) {
      var node = el('input');
      node.type = type;
      if (value !== null && value !== undefined) node.value = value;
      Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
      return node;
    }

    var opener = null;
    function showDialog() {
      if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');
      var first = dialog.querySelector('[data-dialog-body] input:not([type=checkbox]), [data-dialog-body] input, [data-dialog-body] button');
      (first || dialog.querySelector('[data-dialog-save]')).focus();
    }
    function closeDialog() {
      dialog.close();
      if (opener && opener.isConnected) opener.focus();
      opener = null;
    }
    function openDialog(title, caption, onSave, ev) {
      opener = ev && ev.currentTarget ? ev.currentTarget : document.activeElement;
      dialog.querySelector('[data-dialog-title]').textContent = title;
      dialog.querySelector('[data-dialog-caption]').textContent = caption;
      dialog.querySelector('[data-dialog-body]').replaceChildren();
      dialog.querySelector('[data-dialog-sum]').textContent = '';
      dialog.querySelector('[data-dialog-rest]').hidden = true;
      var errorEl = dialog.querySelector('[data-dialog-error]');
      errorEl.hidden = true;
      dialog.onSave = onSave;
      dialog.querySelector('[data-dialog-save]').disabled = false;
      return dialog.querySelector('[data-dialog-body]');
    }
    dialog.querySelector('[data-dialog-cancel]').addEventListener('click', closeDialog);
    dialog.addEventListener('cancel', function (ev) { ev.preventDefault(); closeDialog(); });
    dialog.querySelector('[data-purchases-form]').addEventListener('submit', async function (ev) {
      ev.preventDefault();
      var errorEl = dialog.querySelector('[data-dialog-error]');
      var save = dialog.querySelector('[data-dialog-save]');
      if (save.disabled) return; // already saving: a double click must not send twice
      save.disabled = true;
      errorEl.hidden = true;
      try {
        await dialog.onSave();
        closeDialog();
        await load();
      } catch (err) {
        errorEl.textContent = err.message;
        errorEl.hidden = false;
        errorEl.setAttribute('tabindex', '-1');
        errorEl.focus();
      } finally {
        save.disabled = false;
      }
    });

    function openRecord(card, ev) {
      var body = openDialog('Record ' + fmt(card.open) + ' from ' + (card.document.payee || 'this purchase'),
        'One row for each thing bought. Amounts are before GST; leave one amount blank and it takes the rest.', null, ev);
      var rowsBox = el('div', 'pu-rows__list');
      body.appendChild(rowsBox);
      var addBtn = el('button', 'workspace-button', 'Add a row');
      addBtn.type = 'button';
      body.appendChild(addBtn);
      var sumEl = dialog.querySelector('[data-dialog-sum]');
      var restBox = dialog.querySelector('[data-dialog-rest]');

      function addRow(r) {
        var box = el('div', 'pu-row-edit');
        var name = input('text', r.name || '', { required: '', 'aria-label': 'What', placeholder: 'e.g. Juniper berries' });
        var qty = input('text', num(r.quantity), { inputmode: 'decimal', required: '', 'aria-label': 'Quantity' });
        var unit = input('text', r.unit || '', { required: '', 'aria-label': 'Unit', placeholder: 'kg' });
        var amount = input('text', cents(r.amount), { inputmode: 'decimal', 'aria-label': 'Amount', placeholder: 'the rest' });
        var batch = input('text', '', { 'aria-label': 'Supplier batch number' });
        var expiry = input('date', '', { 'aria-label': 'Expiry date' });
        var pack = input('text', r.pack || '', { 'aria-label': 'Pack size', placeholder: '24 × 200 mL', autocomplete: 'off' });
        box.appendChild(field('What', name));
        box.appendChild(field('Quantity', qty));
        box.appendChild(field('Unit', unit));
        box.appendChild(field('Amount', amount));
        box.appendChild(field('Batch no.', batch));
        box.appendChild(field('Expiry', expiry));
        box.appendChild(field('Pack size', pack));
        if ((r.ask || []).indexOf('batch_number') >= 0) batch.required = true;
        box.read = function () {
          return {
            name: name.value.trim(), quantity: qty.value.trim(), unit: unit.value.trim(), amount: amount.value.trim(),
            inventory_type: r.inventory_type || 'raw_material',
            supplier_batch_number: batch.value.trim() || undefined, expiry_date: expiry.value || undefined,
            pack: pack.value.trim() || undefined
          };
        };
        amount.addEventListener('input', updateSum);
        rowsBox.appendChild(box);
      }
      function blanks() {
        return Array.prototype.filter.call(rowsBox.children, function (b) { return !b.read().amount; });
      }
      function total() {
        return Array.prototype.reduce.call(rowsBox.children, function (s, b) { return s + (units(b.read().amount) || 0); }, 0);
      }
      function updateSum() {
        var left = units(card.open) - total();
        var open = blanks().length;
        if (open === 1 && left >= 0) {
          sumEl.textContent = 'The blank row takes ' + fmt(fromUnits(left));
          restBox.hidden = true;
          return;
        }
        sumEl.textContent = left > 0 ? fmt(fromUnits(left)) + ' not yet in a row' : left < 0 ? fmt(fromUnits(-left)) + ' more than the purchase' : 'Adds up';
        restBox.hidden = !(left > 0);
      }
      var rows = (card.prefill && card.prefill.rows && card.prefill.rows.length) ? card.prefill.rows : [{ amount: card.open }];
      rows.forEach(addRow);
      addBtn.addEventListener('click', function () { addRow({}); updateSum(); rowsBox.lastChild.querySelector('input').focus(); });
      updateSum();
      showDialog();
      dialog.onSave = async function () {
        var rest = dialog.querySelector('input[name="rest"]:checked');
        var rowsOut = Array.prototype.map.call(rowsBox.children, function (b) { return b.read(); });
        var empty = rowsOut.filter(function (r) { return !r.amount; });
        if (empty.length > 1) throw new Error('Leave at most one amount blank; it takes the rest.');
        var bad = rowsOut.filter(function (r) { return r.amount && units(r.amount) === null; });
        if (bad.length) throw new Error('Amounts are numbers with up to 4 decimal places, like 12.50');
        if (empty.length === 1) {
          var left = units(card.open) - total();
          if (left <= 0) throw new Error('Nothing is left for the blank row. Fill in its amount or remove it.');
          empty[0].amount = fromUnits(left);
        }
        await post(API + '/' + card.line_id + '/record', { rows: rowsOut, rest: rest ? rest.value : 'later' });
        showToast('Recorded into stock', canManage ? {
          label: 'Remember for ' + (card.document.payee || 'this payee'),
          run: async function () {
            try { await post(API + '/' + card.line_id + '/remember'); showToast('Next time it will be filled in'); } catch (e) { showError(e.message); }
          }
        } : null);
      };
    }

    async function openPick(card, mode, ev) {
      var refund = mode === 'refund';
      var body = openDialog(refund ? 'Which stock was this refund for?' : 'Which stock did this pay for?',
        refund ? 'The refund lowers the cost of the stock you pick.' : 'Stock you added by hand around ' + fmtDate(card.document.date) + '. Say how much of each this purchase paid for.', null, ev);
      var picks = [];
      try {
        var found = await call(API + '/' + card.line_id + '/candidates');
        if (!found.candidates.length) body.appendChild(el('p', 'workspace-caption', 'No matching stock. Use Record stock instead.'));
        found.candidates.forEach(function (c) {
          var line = el('div', 'pu-pick');
          var check = input('checkbox', null, { 'aria-label': c.name });
          var amount = input('text', '', { inputmode: 'decimal', 'aria-label': 'Amount for ' + c.name, placeholder: refund ? '-0.00' : '0.00' });
          var qty = refund ? null : input('text', num(c.quantity), { inputmode: 'decimal', 'aria-label': 'Quantity of ' + c.name + ' this paid for' });
          var label = el('span', null, c.name + ' · ' + num(c.quantity) + ' ' + c.unit + (c.supplier ? ' · ' + c.supplier : '') + (c.purchase_date ? ' · ' + fmtDate(c.purchase_date) : ''));
          line.appendChild(check);
          line.appendChild(label);
          if (qty) {
            var qtyWrap = el('label', 'pu-pick__qty');
            qtyWrap.appendChild(qty);
            qtyWrap.appendChild(el('span', null, c.unit));
            line.appendChild(qtyWrap);
          }
          line.appendChild(amount);
          check.addEventListener('change', function () { if (check.checked && !amount.value && found.candidates.length === 1) amount.value = cents(card.open); });
          picks.push({ c: c, check: check, amount: amount, qty: qty });
          body.appendChild(line);
        });
      } catch (err) { showError(err.message); }
      if (!refund) dialog.querySelector('[data-dialog-rest]').hidden = false;
      showDialog();
      dialog.onSave = async function () {
        var lots = picks.filter(function (p) { return p.check.checked; })
          .map(function (p) {
            var lot = { inventory_item_id: p.c.inventory_item_id, amount: p.amount.value.trim() };
            if (p.qty && p.qty.value.trim()) lot.quantity = p.qty.value.trim();
            return lot;
          });
        if (!lots.length) throw new Error('Pick at least one');
        if (refund) {
          await post(API + '/' + card.line_id + '/refund', { lots: lots });
        } else {
          var rest = dialog.querySelector('input[name="rest"]:checked');
          await post(API + '/' + card.line_id + '/link', { lots: lots, rest: rest ? rest.value : 'later' });
        }
        showToast(refund ? 'Cost lowered' : 'Linked to stock');
      };
    }

    function openAllocations(card, ev) {
      var body = openDialog('Edit what this purchase paid for',
        'Xero now says ' + fmt(card.amount) + '. Change the amounts so they fit.', null, ev);
      var edits = [];
      (card.allocations || []).forEach(function (a) {
        var line = el('div', 'pu-pick pu-pick--edit');
        line.appendChild(el('span', null, (a.name || 'Stock') + (a.status === 'orphaned' ? ' (no longer linked)' : '')));
        var amount = input('text', cents(a.amount), { inputmode: 'decimal', 'aria-label': 'Amount for ' + (a.name || 'stock') });
        var qty = Number(a.amount) < 0 ? null : input('text', num(a.quantity), { inputmode: 'decimal', 'aria-label': 'Quantity for ' + (a.name || 'stock') });
        if (qty) line.appendChild(qty); else line.appendChild(el('span'));
        line.appendChild(amount);
        edits.push({ a: a, amount: amount, qty: qty });
        body.appendChild(line);
      });
      showDialog();
      dialog.onSave = async function () {
        await post(API + '/' + card.line_id + '/allocations', {
          allocations: edits.map(function (e) {
            var out = { id: e.a.id, amount: e.amount.value.trim() };
            if (e.qty) out.quantity = e.qty.value.trim();
            return out;
          })
        }, 'PUT');
        showToast('Amounts updated');
      };
    }

    // --- historical runs ----------------------------------------------------------------------
    var historyDialog = root.querySelector('[data-history-dialog]');
    var historyOpen = root.querySelector('[data-history-open]');
    if (historyOpen && historyDialog) {
      var hForm = historyDialog.querySelector('form');
      var hError = historyDialog.querySelector('[data-history-error]');
      var hSave = historyDialog.querySelector('[data-history-run]');
      historyOpen.addEventListener('click', function () {
        hError.hidden = true;
        var today = new Date();
        var iso = function (d) { return d.toISOString().slice(0, 10); };
        var from = new Date(today.getFullYear(), today.getMonth() - 3, 1);
        hForm.elements.from.value = hForm.elements.from.value || iso(from);
        hForm.elements.to.value = hForm.elements.to.value || iso(today);
        hForm.elements.to.max = iso(today);
        historyDialog.showModal();
        hForm.elements.from.focus();
      });
      historyDialog.querySelector('[data-history-cancel]').addEventListener('click', function () { historyDialog.close(); historyOpen.focus(); });
      hForm.addEventListener('submit', async function (ev) {
        ev.preventDefault();
        if (hSave.disabled) return;
        var range = { from: hForm.elements.from.value, to: hForm.elements.to.value };
        if (!range.from || !range.to) { hError.textContent = 'Pick both dates.'; hError.hidden = false; return; }
        hSave.disabled = true;
        hSave.textContent = 'Loading from Xero…';
        hError.hidden = true;
        try {
          var res = await post(API + '/historical-run', range);
          historyDialog.close();
          history = range;
          showToast(res.documents + (res.documents === 1 ? ' purchase' : ' purchases') + ' loaded from Xero');
          await load();
        } catch (err) {
          hError.textContent = err.code === 'needs_reconnect'
            ? 'Biz-E needs permission to read purchases. Reconnect Xero in Settings, then try again.'
            : err.message;
          hError.hidden = false;
        } finally {
          hSave.disabled = false;
          hSave.textContent = 'Load purchases';
        }
      });
    }
    if (historyBar) {
      historyBar.querySelector('[data-history-exit]').addEventListener('click', function () { history = null; load(); });
    }

    // --- tabs and keys ------------------------------------------------------------------------
    root.querySelectorAll('[data-purchases-tabs] [data-tab]').forEach(function (button) {
      button.addEventListener('click', function () {
        tab = button.dataset.tab;
        root.querySelectorAll('[data-purchases-tabs] [data-tab]').forEach(function (b) {
          if (b === button) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
        });
        load();
      });
    });
    load();
  }

  function boot() { document.querySelectorAll('[data-purchases-root]').forEach(init); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  document.addEventListener('htmx:afterSettle', boot);
})();
