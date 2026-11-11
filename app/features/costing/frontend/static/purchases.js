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
  function cents(value) {
    if (value === null || value === undefined || value === '') return '';
    var n = Number(value);
    return isFinite(n) ? n.toFixed(2) : String(value);
  }
  function fmt(value) { return value === null || value === undefined ? '—' : money.format(Number(value)); }
  function fmtDate(iso) {
    if (!iso) return '';
    var d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' });
  }
  function uuid() {
    return (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()) + Math.random();
  }

  function init(root) {
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    var canManage = root.dataset.canManage === 'true';
    var canAdjust = root.dataset.canAdjust === 'true';
    var list = root.querySelector('[data-purchases-list]');
    var state = root.querySelector('[data-purchases-state]');
    var errorBox = root.querySelector('[data-purchases-error]');
    var toast = root.querySelector('[data-purchases-toast]');
    var dialog = root.querySelector('[data-purchases-dialog]');
    var focusbar = root.querySelector('[data-purchases-focusbar]');
    var batchbar = root.querySelector('[data-purchases-batchbar]');
    var tab = 'to_record';
    var cards = [];
    var focusIndex = 0;
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
      if (!res.ok) throw new Error((body && body.error) || 'Something went wrong (' + res.status + ')');
      return body;
    }
    function post(path, body) {
      return call(path, { method: 'POST', body: JSON.stringify(body || {}), headers: { 'Idempotency-Key': uuid() } });
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

    // --- style switch (CONCEPT ONLY) -----------------------------------------------------------
    function applyStyle(value) {
      root.dataset.purchasesStyle = value;
      try { localStorage.setItem('purchases-style', value); } catch (e) { /* private mode */ }
      root.querySelectorAll('[data-purchases-style-pick] button').forEach(function (b) {
        b.setAttribute('aria-pressed', b.dataset.style === value ? 'true' : 'false');
      });
      render();
    }
    var initial = new URLSearchParams(location.search).get('style');
    if (!/^[123]$/.test(initial || '')) {
      try { initial = localStorage.getItem('purchases-style'); } catch (e) { initial = null; }
    }
    root.querySelectorAll('[data-purchases-style-pick] button').forEach(function (b) {
      b.addEventListener('click', function () { applyStyle(b.dataset.style); });
    });

    // --- loading -----------------------------------------------------------------------------
    async function load() {
      root.setAttribute('aria-busy', 'true');
      showError('');
      try {
        var body = await call(API + '?tab=' + encodeURIComponent(tab));
        cards = body.cards || [];
        Object.keys(body.counts || {}).forEach(function (key) {
          var span = root.querySelector('[data-count="' + key + '"]');
          if (span) span.textContent = body.counts[key] ? String(body.counts[key]) : '';
        });
        focusIndex = Math.min(focusIndex, Math.max(cards.length - 1, 0));
        selected = {};
        render();
      } catch (err) {
        state.textContent = '';
        showError(err.message);
      } finally {
        root.setAttribute('aria-busy', 'false');
      }
    }

    // --- rendering ---------------------------------------------------------------------------
    function render() {
      var style = root.dataset.purchasesStyle;
      list.replaceChildren();
      focusbar.hidden = !(style === '2' && tab === 'to_record' && cards.length);
      updateBatchbar();
      if (!cards.length) {
        state.textContent = tab === 'to_record'
          ? 'Nothing to record. New purchases arrive with each Xero sync.'
          : 'Nothing here.';
        return;
      }
      state.textContent = '';
      if (style === '3') list.appendChild(tableHead());
      cards.forEach(function (card, index) {
        var node = style === '3' ? row(card) : cardNode(card);
        if (style === '2') node.hidden = index !== focusIndex;
        list.appendChild(node);
      });
      if (style === '2') {
        root.querySelector('[data-purchases-progress]').textContent =
          (focusIndex + 1) + ' of ' + cards.length + ' to record';
      }
    }

    function what(card) {
      var wrap = el('div', 'pu-what');
      var top = el('div', 'pu-what__top');
      top.appendChild(el('strong', 'pu-payee', card.document.payee || 'Unknown payee'));
      top.appendChild(el('span', 'pu-amount', fmt(card.amount)));
      wrap.appendChild(top);
      var meta = el('div', 'pu-meta');
      meta.appendChild(el('span', null, fmtDate(card.document.date)));
      if (card.description) meta.appendChild(el('span', null, card.description));
      meta.appendChild(el('span', null, card.account.name || card.account.code || ''));
      wrap.appendChild(meta);
      return wrap;
    }

    function badges(card) {
      var wrap = el('div', 'pu-badges');
      if (card.review_reason) wrap.appendChild(el('span', 'pu-badge pu-badge--warn', REVIEW_TEXT[card.review_reason] || 'Check this'));
      if (card.document.kind === 'refund') wrap.appendChild(el('span', 'pu-badge', 'Refund'));
      if (card.state === 'partly_recorded') wrap.appendChild(el('span', 'pu-badge', fmt(card.open) + ' still to record'));
      if (card.state === 'recorded') wrap.appendChild(el('span', 'pu-badge pu-badge--ok', 'Recorded'));
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
        b.addEventListener('click', function (ev) { ev.stopPropagation(); fn(); });
        wrap.appendChild(b);
        return b;
      }
      if (card.review_reason) {
        btn('Keep as recorded', true, function () { act(card, 'review', { action: 'keep' }); });
        if (canAdjust) btn('Unlink from stock', false, function () { act(card, 'review', { action: 'unlink' }); });
        return wrap;
      }
      if (tab === 'skipped' || tab === 'not_stock') {
        btn('Undo', false, function () { act(card, 'reopen'); });
        return wrap;
      }
      if (tab === 'recorded') return wrap;
      if (card.document.kind === 'refund') {
        if (canAdjust) btn('Lower the cost of…', true, function () { openPick(card, 'refund'); });
        btn('Not stock', false, function () { act(card, 'not-stock'); });
        return wrap;
      }
      if (canAdjust) btn(card.prefill && card.prefill.source === 'rule' ? 'OK' : 'Record stock', true, function () { openRecord(card); });
      if (!compact && canAdjust) btn('Already in stock', false, function () { openPick(card, 'link'); });
      btn('Not stock', false, function () { act(card, 'not-stock'); });
      btn('Skip', false, function () { act(card, 'skip'); });
      return wrap;
    }

    function cardNode(card) {
      var node = el('article', 'pu-card workspace-card');
      node.dataset.lineId = card.line_id;
      var left = el('div', 'pu-card__left');
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

    function tableHead() {
      var head = el('div', 'pu-row pu-row--head');
      var all = el('input');
      all.type = 'checkbox';
      all.setAttribute('aria-label', 'Select all');
      all.addEventListener('change', function () {
        cards.forEach(function (c) { if (all.checked) selected[c.line_id] = true; else delete selected[c.line_id]; });
        render();
      });
      all.checked = cards.length > 0 && cards.every(function (c) { return selected[c.line_id]; });
      head.appendChild(all);
      ['Date', 'Payee', 'Details', 'Amount', ''].forEach(function (t) { head.appendChild(el('span', null, t)); });
      return head;
    }

    function row(card) {
      var node = el('div', 'pu-row');
      node.dataset.lineId = card.line_id;
      var check = el('input');
      check.type = 'checkbox';
      check.setAttribute('aria-label', 'Select ' + (card.document.payee || 'purchase'));
      check.checked = !!selected[card.line_id];
      check.disabled = tab !== 'to_record' || !canManage;
      check.addEventListener('change', function () {
        if (check.checked) selected[card.line_id] = true; else delete selected[card.line_id];
        updateBatchbar();
      });
      node.appendChild(check);
      node.appendChild(el('span', 'pu-row__date', fmtDate(card.document.date)));
      var who = el('span', 'pu-row__payee', card.document.payee || 'Unknown payee');
      node.appendChild(who);
      var details = el('span', 'pu-row__details');
      details.appendChild(el('span', null, card.description || ''));
      details.appendChild(badges(card));
      node.appendChild(details);
      node.appendChild(el('span', 'pu-row__amount', fmt(card.amount)));
      node.appendChild(actions(card, true));
      return node;
    }

    function updateBatchbar() {
      var count = Object.keys(selected).length;
      batchbar.hidden = !(root.dataset.purchasesStyle === '3' && count > 0);
      root.querySelector('[data-purchases-selected]').textContent = count + ' selected';
    }
    batchbar.addEventListener('click', async function (ev) {
      var action = ev.target && ev.target.dataset ? ev.target.dataset.batch : null;
      if (!action) return;
      if (action === 'cancel') { selected = {}; render(); return; }
      try {
        var body = await post(API + '/bulk', { line_ids: Object.keys(selected), action: action });
        var failed = (body.results || []).filter(function (r) { return !r.ok; }).length;
        showToast((body.results.length - failed) + ' done' + (failed ? ', ' + failed + ' not changed' : ''));
      } catch (err) { showError(err.message); }
      load();
    });

    // --- actions -------------------------------------------------------------------------------
    async function act(card, action, body) {
      try {
        await post(API + '/' + card.line_id + '/' + action, body);
        var undo = action === 'skip' || action === 'not-stock';
        showToast(action === 'skip' ? 'Skipped' : action === 'not-stock' ? 'Marked not stock' : 'Done',
          undo ? { label: 'Undo', run: function () { act(card, 'reopen'); } } : null);
      } catch (err) { showError(err.message); }
      load();
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

    function openDialog(title, caption, onSave) {
      dialog.querySelector('[data-dialog-title]').textContent = title;
      dialog.querySelector('[data-dialog-caption]').textContent = caption;
      dialog.querySelector('[data-dialog-body]').replaceChildren();
      dialog.querySelector('[data-dialog-sum]').textContent = '';
      dialog.querySelector('[data-dialog-rest]').hidden = true;
      var errorEl = dialog.querySelector('[data-dialog-error]');
      errorEl.hidden = true;
      dialog.onSave = onSave;
      if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');
      return dialog.querySelector('[data-dialog-body]');
    }
    dialog.querySelector('[data-dialog-cancel]').addEventListener('click', function () { dialog.close(); });
    dialog.querySelector('[data-purchases-form]').addEventListener('submit', async function (ev) {
      ev.preventDefault();
      var errorEl = dialog.querySelector('[data-dialog-error]');
      try {
        await dialog.onSave();
        dialog.close();
        load();
      } catch (err) {
        errorEl.textContent = err.message;
        errorEl.hidden = false;
      }
    });

    function openRecord(card) {
      var body = openDialog('Record ' + fmt(card.open) + ' from ' + (card.document.payee || 'this purchase'),
        'One row for each thing bought. Amounts are before GST.', null);
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
        var amount = input('text', cents(r.amount), { inputmode: 'decimal', required: '', 'aria-label': 'Amount' });
        var batch = input('text', '', { 'aria-label': 'Supplier batch number' });
        var expiry = input('date', '', { 'aria-label': 'Expiry date' });
        box.appendChild(field('What', name));
        box.appendChild(field('Quantity', qty));
        box.appendChild(field('Unit', unit));
        box.appendChild(field('Amount', amount));
        box.appendChild(field('Batch no.', batch));
        box.appendChild(field('Expiry', expiry));
        if ((r.ask || []).indexOf('batch_number') >= 0) batch.required = true;
        box.read = function () {
          return {
            name: name.value.trim(), quantity: qty.value.trim(), unit: unit.value.trim(), amount: amount.value.trim(),
            inventory_type: r.inventory_type || 'raw_material',
            supplier_batch_number: batch.value.trim() || undefined, expiry_date: expiry.value || undefined
          };
        };
        amount.addEventListener('input', updateSum);
        rowsBox.appendChild(box);
      }
      function total() {
        return Array.prototype.reduce.call(rowsBox.children, function (s, b) { return s + (Number(b.read().amount) || 0); }, 0);
      }
      function updateSum() {
        var left = Number(card.open) - total();
        sumEl.textContent = left > 0.00005 ? fmt(left) + ' not yet in a row' : left < -0.00005 ? fmt(-left) + ' more than the purchase' : 'Adds up';
        restBox.hidden = !(left > 0.00005);
      }
      var rows = (card.prefill && card.prefill.rows && card.prefill.rows.length) ? card.prefill.rows : [{ amount: card.open }];
      rows.forEach(addRow);
      addBtn.addEventListener('click', function () { addRow({}); updateSum(); });
      updateSum();
      dialog.onSave = async function () {
        var rest = dialog.querySelector('input[name="rest"]:checked');
        await post(API + '/' + card.line_id + '/record', {
          rows: Array.prototype.map.call(rowsBox.children, function (b) { return b.read(); }),
          rest: rest ? rest.value : 'later'
        });
        showToast('Recorded into stock', canManage ? {
          label: 'Remember for ' + (card.document.payee || 'this payee'),
          run: async function () {
            try { await post(API + '/' + card.line_id + '/remember'); showToast('Next time it will be filled in'); } catch (e) { showError(e.message); }
          }
        } : null);
      };
    }

    async function openPick(card, mode) {
      var refund = mode === 'refund';
      var body = openDialog(refund ? 'Which stock was this refund for?' : 'Which stock did this pay for?',
        refund ? 'The refund lowers the cost of the stock you pick.' : 'Stock you added by hand around ' + fmtDate(card.document.date) + '.', null);
      var picks = [];
      try {
        var found = await call(API + '/' + card.line_id + '/candidates');
        if (!found.candidates.length) body.appendChild(el('p', 'workspace-caption', 'No matching stock. Use Record stock instead.'));
        found.candidates.forEach(function (c) {
          var line = el('div', 'pu-pick');
          var check = input('checkbox', null, { 'aria-label': c.name });
          var amount = input('text', '', { inputmode: 'decimal', 'aria-label': 'Amount for ' + c.name, placeholder: refund ? '-0.00' : '0.00' });
          var label = el('span', null, c.name + ' · ' + num(c.quantity) + ' ' + c.unit + (c.supplier ? ' · ' + c.supplier : '') + (c.purchase_date ? ' · ' + fmtDate(c.purchase_date) : ''));
          line.appendChild(check);
          line.appendChild(label);
          line.appendChild(amount);
          check.addEventListener('change', function () { if (check.checked && !amount.value && found.candidates.length === 1) amount.value = cents(card.open); });
          picks.push({ c: c, check: check, amount: amount });
          body.appendChild(line);
        });
      } catch (err) { showError(err.message); }
      if (!refund) dialog.querySelector('[data-dialog-rest]').hidden = false;
      dialog.onSave = async function () {
        var lots = picks.filter(function (p) { return p.check.checked; })
          .map(function (p) { return { inventory_item_id: p.c.inventory_item_id, amount: p.amount.value.trim() }; });
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

    // --- tabs and keys ------------------------------------------------------------------------
    root.querySelectorAll('[data-purchases-tabs] [data-tab]').forEach(function (button) {
      button.addEventListener('click', function () {
        tab = button.dataset.tab;
        focusIndex = 0;
        root.querySelectorAll('[data-purchases-tabs] [data-tab]').forEach(function (b) {
          if (b === button) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
        });
        load();
      });
    });
    function onKey(ev) {
      if (!document.body.contains(root)) { document.removeEventListener('keydown', onKey); return; }
      if (root.dataset.purchasesStyle !== '2' || tab !== 'to_record' || dialog.open) return;
      if (/^(INPUT|TEXTAREA|SELECT)$/.test((ev.target && ev.target.tagName) || '')) return;
      var card = cards[focusIndex];
      if (ev.key === 'ArrowRight') { focusIndex = Math.min(focusIndex + 1, cards.length - 1); render(); }
      else if (ev.key === 'ArrowLeft') { focusIndex = Math.max(focusIndex - 1, 0); render(); }
      else if (!card || !canManage) return;
      else if (ev.key === '1' && canAdjust && !card.review_reason && card.document.kind === 'spend') openRecord(card);
      else if (ev.key === '2' && !card.review_reason) act(card, 'not-stock');
      else if (ev.key === '3' && !card.review_reason) act(card, 'skip');
    }
    document.addEventListener('keydown', onKey);

    applyStyle(/^[123]$/.test(initial || '') ? initial : '1');
    load();
  }

  function boot() { document.querySelectorAll('[data-purchases-root]').forEach(init); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  document.addEventListener('htmx:afterSettle', boot);
})();
