/* Stock transfers (GL-P07 A4): what is on its way between sites and what has arrived.

   Receiving is one click when everything turned up ("Received in full"); "Something's different"
   opens the receipt form for shortages and damage. Moving stock opens the shared Move dialog
   (app/ui/shared/move-stock.js) after a stock picker. What is still to be received leads; finished
   transfers are listed underneath. */
(function () {
  'use strict';

  function init(root) {
    if (!root || root.dataset.bound) return;
    root.dataset.bound = '1';
    var $ = function (s) { return root.querySelector(s); };
    var message = $('[data-transfers-message]');
    var done = $('[data-transfers-done]');
    var state = $('[data-transfers-state]');
    var list = $('[data-transfers-list]');
    var arriving = $('[data-transfers-arriving]');
    var arrivingList = $('[data-transfers-arriving-list]');
    var moveButton = $('[data-transfers-move]');
    var pick = $('[data-transfers-pick]');
    var canAdjust = root.dataset.canAdjust === 'true';
    var data = null;

    function el(tag, cls, text) {
      var n = document.createElement(tag);
      if (cls) n.className = cls;
      if (text !== undefined) n.textContent = text;
      return n;
    }
    function fmt(n) { return Number(n).toLocaleString(undefined, { maximumFractionDigits: 4 }); }
    function fmtDate(iso) {
      if (!iso) return '';
      var d = new Date(iso + 'T00:00:00');
      return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
    }
    function today() { return new Date().toLocaleDateString('en-CA'); }

    async function api(path, init) {
      init = init || {};
      var token = document.querySelector('meta[name="csrf-token"]');
      var res = await fetch(path, Object.assign({ credentials: 'same-origin' }, init, {
        headers: Object.assign({ 'Content-Type': 'application/json', 'X-CSRFToken': token ? token.content : '' }, init.headers || {}),
      }));
      var body = {};
      try { body = await res.json(); } catch (_) { /* empty */ }
      if (!res.ok) throw new Error(body.error || 'The server could not answer. Try again in a moment.');
      return body;
    }
    function say(text) { done.textContent = text; done.hidden = !text; message.hidden = true; }
    function fail(error) { message.textContent = error.message; message.hidden = false; }

    function siteName(id) { var s = data.sites.get(id); return s || 'another site'; }
    function placeName(transfer, side) {
      var site = data.sites.get(transfer[side + '_site_id']) || transfer[side + '_site_name'] || 'another site';
      var loc = transfer[side + '_location_id'] && data.locations.get(transfer[side + '_location_id']);
      return loc ? site + ' · ' + loc : site;
    }
    function status(t) {
      if (t.status === 'received') return { text: 'Received', tone: 'ok' };
      if (t.status === 'part_received') return { text: fmt(t.received_quantity) + ' of ' + fmt(t.quantity) + ' received', tone: 'warn' };
      return { text: 'In transit', tone: 'transit' };
    }

    function receiptForm(t, card) {
      var form = el('form', 'tr-receipt');
      form.setAttribute('hx-boost', 'false');
      var fields = el('div', 'tr-receipt__fields');
      [['quantity', 'Arrived in good order', 'number', t.transit_quantity], ['damaged_quantity', 'Damaged', 'number', '0'],
        ['short_quantity', 'Missing', 'number', '0'], ['occurred_on', 'Arrived on', 'date', today()],
        ['loss_reason', 'What happened (for damaged or missing)', 'text', '']].forEach(function (f) {
        var label = el('label', 'tr-field');
        label.append(el('span', 'tr-field__label', f[1]));
        var input = el('input');
        input.name = f[0]; input.type = f[2]; input.value = f[3];
        if (f[2] === 'number') { input.min = '0'; input.step = 'any'; input.inputMode = 'decimal'; }
        if (f[2] === 'date') { input.required = true; input.max = today(); }
        if (f[2] === 'text') input.maxLength = 500;
        label.append(input);
        fields.append(label);
      });
      var confirm = el('label', 'tr-check');
      var check = el('input'); check.type = 'checkbox'; check.name = 'confirm_loss';
      confirm.append(check, document.createTextNode(' The damaged and missing amounts are final losses'));
      var hint = el('p', 'tr-hint', 'Anything not received and not confirmed lost stays in transit.');
      var actions = el('div', 'tr-actions');
      var cancel = el('button', 'workspace-button', 'Cancel'); cancel.type = 'button';
      var submit = el('button', 'workspace-button workspace-button--primary', 'Record receipt'); submit.type = 'submit';
      actions.append(cancel, submit);
      form.append(fields, confirm, hint, actions);
      cancel.addEventListener('click', function () { form.remove(); card.querySelector('[data-tr-different]').hidden = false; });
      var key = null, last = null;
      form.addEventListener('submit', async function (e) {
        e.preventDefault();
        var d = new FormData(form);
        var body = { quantity: d.get('quantity') || '0', damaged_quantity: d.get('damaged_quantity') || '0', short_quantity: d.get('short_quantity') || '0',
          occurred_on: d.get('occurred_on'), loss_reason: d.get('loss_reason'), confirm_loss: d.get('confirm_loss') === 'on' };
        await send(t, body, submit, key && last === JSON.stringify(body) ? key : null, function (k, j) { key = k; last = j; });
      });
      return form;
    }

    async function send(t, body, button, reuse, remember) {
      var json = JSON.stringify(body);
      var key = reuse || ((window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()));
      if (remember) remember(key, json);
      button.disabled = true;
      try {
        await api('/api/core/site-transfers/' + t.id + '/receipts', { method: 'POST', headers: { 'Idempotency-Key': key }, body: json });
        say(t.product_name + ': receipt recorded at ' + placeName(t, 'destination') + '.');
        await load();
      } catch (error) { fail(error); button.disabled = false; }
    }

    function card(t) {
      var article = el('article', 'tr-card tr-card--' + t.status);
      article.dataset.transferId = t.id;
      var head = el('div', 'tr-card__head');
      var title = el('h3', 'tr-card__title');
      title.append(el('span', '', t.product_name), el('span', 'tr-card__qty', fmt(t.quantity) + ' ' + t.unit));
      if (t.batch) title.append(el('span', 'tr-card__batch', 'Batch ' + t.batch));
      var st = status(t);
      head.append(title, el('span', 'tr-pill tr-pill--' + st.tone, st.text));
      var route = el('p', 'tr-card__route');
      route.append(el('span', '', placeName(t, 'source')), el('span', 'tr-arrow', ' → '), el('strong', '', placeName(t, 'destination')));
      var meta = el('p', 'tr-card__meta', [t.carrier, t.consignment_reference, 'left ' + fmtDate(t.occurred_on)].filter(Boolean).join(' · '));
      article.append(head, route, meta);
      if (Number(t.confirmed_loss_quantity) > 0) article.append(el('p', 'tr-card__loss', fmt(t.confirmed_loss_quantity) + ' ' + t.unit + ' confirmed lost'));
      var actions = el('div', 'tr-actions tr-card__actions');
      var transit = Number(t.transit_quantity);
      if (transit > 0 && canAdjust && data.available) {
        var full = el('button', 'workspace-button workspace-button--primary', transit === Number(t.quantity) ? 'Received in full' : 'Received the rest (' + fmt(transit) + ')');
        full.type = 'button';
        full.dataset.trFull = '';
        full.addEventListener('click', function () {
          send(t, { quantity: t.transit_quantity, damaged_quantity: '0', short_quantity: '0', occurred_on: today(), confirm_loss: false }, full);
        });
        var different = el('button', 'tr-link tr-link--button', 'Something’s different');
        different.type = 'button';
        different.dataset.trDifferent = '';
        different.addEventListener('click', function () {
          different.hidden = true;
          article.append(receiptForm(t, article));
          article.querySelector('.tr-receipt input').focus();
        });
        actions.append(full, different);
      }
      var docket = el('a', 'tr-link', 'Print transfer docket');
      docket.href = '/core/site-transfers/' + t.id + '/docket';
      docket.target = '_blank'; docket.rel = 'noopener'; docket.setAttribute('hx-boost', 'false');
      actions.append(docket);
      article.append(actions);
      return article;
    }

    function render() {
      var all = data.transfers;
      var open = all.filter(function (t) { return Number(t.transit_quantity) > 0; });
      var closed = all.filter(function (t) { return Number(t.transit_quantity) <= 0; });
      arriving.hidden = true;
      list.replaceChildren();
      arrivingList.replaceChildren();
      if (!data.available) state.textContent = 'Moving stock between sites isn’t switched on for your organisation. Transfers already recorded stay here.';
      else if (!all.length) state.textContent = 'Nothing has moved between sites yet. Use Move stock, or Move… on a line in Inventory.';
      else state.textContent = '';
      state.hidden = !state.textContent;
      // What to receive leads; everything else is history underneath.
      arriving.hidden = !open.length;
      $('[data-transfers-arriving-caption]').textContent = open.length === 1 ? 'One delivery is on its way.' : open.length + ' deliveries are on their way.';
      open.forEach(function (t) { arrivingList.append(card(t)); });
      closed.forEach(function (t) { list.append(card(t)); });
      if (moveButton) moveButton.hidden = !(data.available && canAdjust && data.canAuthorise && data.stock.length);
    }

    async function load() {
      root.setAttribute('aria-busy', 'true');
      try {
        var both = await Promise.all([api('/api/core/site-transfers'), api('/api/core/site-transfers/options')]);
        var position = both[0], options = both[1];
        data = {
          available: position.operations_available,
          transfers: position.transfers,
          sites: new Map(options.sites.map(function (s) { return [s.id, s.name]; })),
          locations: new Map(options.locations.map(function (l) { return [l.id, l.name]; })),
          stock: options.stock,
          canAuthorise: options.requirements.can_authorise !== false,
        };
        render();
      } catch (error) {
        fail(error);
        state.textContent = 'Transfers did not load. Reload the page to try again.';
        state.hidden = false;
      } finally {
        root.setAttribute('aria-busy', 'false');
      }
    }

    // Move stock: pick the line, then the shared Move dialog.
    function openPicker() {
      var search = pick.querySelector('#tr-pick-search');
      var box = pick.querySelector('[data-transfers-pick-list]');
      function draw() {
        var needle = search.value.trim().toLowerCase();
        box.replaceChildren();
        var rows = data.stock.filter(function (s) { return !needle || (s.name + ' ' + (s.batch || '')).toLowerCase().indexOf(needle) !== -1; }).slice(0, 60);
        if (!rows.length) box.append(el('p', 'tr-empty', 'No stock matches.'));
        rows.forEach(function (s) {
          var b = el('button', 'tr-pick__row');
          b.type = 'button';
          var area = s.location_id && data.locations.get(s.location_id);
          b.append(el('strong', '', s.name), el('span', '', [fmt(s.quantity) + ' ' + s.unit, siteName(s.site_id) + (area ? ' · ' + area : ''), s.batch].filter(Boolean).join(' · ')));
          b.addEventListener('click', function () {
            pick.close();
            window.BizeMove.open({ id: s.id, name: s.name, quantity: s.quantity, unit: s.unit, site_id: s.site_id,
              location_id: s.location_id, where: siteName(s.site_id) + (s.location_id && data.locations.get(s.location_id) ? ' · ' + data.locations.get(s.location_id) : '') },
            { onDone: function (r) {
              say(r.dispatched ? s.name + ' is on its way to ' + r.label + '.' : s.name + ' moved to ' + r.label + '.');
              load();
            } });
          });
          box.append(b);
        });
      }
      search.value = '';
      search.oninput = draw;
      draw();
      pick.showModal();
      setTimeout(function () { search.focus(); }, 0);
    }
    if (moveButton) moveButton.addEventListener('click', openPicker);

    load();
  }
  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  bize.onPage('[data-transfers-root]', init);
}());
