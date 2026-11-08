/* Moving stock (GL-P07 A4): one dialog for every move.

   window.BizeMove.open(line, opts) moves part or all of one stock line:
   - to another area at the same site: one step, recorded straight away;
   - to another site: a dispatch, in transit until someone records what arrived there.
   The compliance module's questions (if any) are asked in the same dialog, before Move is
   pressed, not as a refusal afterwards. `line` is an Inventory line: id, name, quantity, unit,
   site_id, location_id. opts.onDone(result) runs after a move is recorded. */
(function () {
  'use strict';

  var options = null;

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'className') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.append(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function today() { return new Date().toLocaleDateString('en-CA'); }
  function fmt(n) { return Number(n).toLocaleString(undefined, { maximumFractionDigits: 4 }); }

  async function api(method, path, body, key) {
    var headers = { Accept: 'application/json' };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      var token = document.querySelector('meta[name="csrf-token"]');
      headers['X-CSRFToken'] = token ? token.content : '';
    }
    if (key) headers['Idempotency-Key'] = key;
    var res = await fetch(path, { method: method, credentials: 'same-origin', headers: headers,
      body: body === undefined ? undefined : JSON.stringify(body) });
    var data = {};
    try { data = await res.json(); } catch (_) { /* empty */ }
    if (!res.ok) throw new Error(data.error || 'The move could not be recorded.');
    return data;
  }

  function loadOptions() {
    if (options) return Promise.resolve(options);
    return Promise.all([
      api('GET', '/api/core/site-transfers/options'),
      window.BizeSite ? window.BizeSite.choices() : Promise.resolve({ on: false, sites: [] }),
    ]).then(function (both) {
      options = both[0];
      options.choices = both[1];
      return options;
    });
  }

  /** Where this line could go: other areas at its own site, then other sites (and their areas). */
  function destinations(line) {
    var sites = (options.choices && options.choices.on ? options.choices.sites : []);
    var here = sites.filter(function (s) { return s.id === line.site_id; })[0];
    var groups = [];
    var areas = here ? here.areas : (options.locations || []).filter(function (l) { return l.site_id === line.site_id; });
    var local = [];
    if (line.location_id) local.push({ site: line.site_id, location: '', label: 'At ' + (here ? here.name : 'the site') + ' itself' });
    areas.forEach(function (a) { if (a.id !== line.location_id) local.push({ site: line.site_id, location: a.id, label: a.name }); });
    if (local.length) groups.push({ label: here ? 'Elsewhere at ' + here.name : 'Elsewhere here', items: local });
    sites.forEach(function (s) {
      if (s.id === line.site_id) return;
      var items = [{ site: s.id, location: '', label: s.name }];
      s.areas.forEach(function (a) { items.push({ site: s.id, location: a.id, label: s.name + ' · ' + a.name }); });
      groups.push({ label: 'To another site', items: items, other: true });
    });
    // Merge every "To another site" group into one.
    var merged = [], other = null;
    groups.forEach(function (g) {
      if (!g.other) { merged.push(g); return; }
      if (!other) { other = { label: g.label, items: [] }; merged.push(other); }
      other.items = other.items.concat(g.items);
    });
    return merged;
  }

  function field(label, input, hint) {
    var wrap = el('label', { className: 'mv-field' }, [el('span', { className: 'mv-field__label', text: label }), input]);
    if (hint) wrap.append(el('span', { className: 'mv-hint', text: hint }));
    return wrap;
  }

  function complianceFields(requirements) {
    var box = el('fieldset', { className: 'mv-compliance', 'data-mv-compliance': '' });
    var conditional = [];
    (requirements.fields || []).forEach(function (f) {
      if (['select', 'text', 'date'].indexOf(f.type) === -1 || !/^[a-z_]+$/.test(f.name)) return;
      var input;
      if (f.type === 'select') {
        input = el('select', { name: 'approval.' + f.name });
        input.append(el('option', { value: '', text: 'Choose…' }));
        (f.options || []).forEach(function (o) { input.append(el('option', { value: o.value, text: o.label })); });
      } else {
        input = el('input', { name: 'approval.' + f.name, type: f.type, maxlength: '500' });
      }
      if (f.required) input.required = true;
      var wrap = field(f.label, input, f.hint);
      box.append(wrap);
      if (f.show_when && typeof f.show_when === 'object') conditional.push({ wrap: wrap, input: input, when: f.show_when });
    });
    if (!box.childElementCount) return null;
    // A question that only applies to some answers waits until that answer is chosen.
    function refresh() {
      conditional.forEach(function (c) {
        var show = Object.keys(c.when).every(function (name) {
          var other = box.querySelector('[name="approval.' + name + '"]');
          return other && [].concat(c.when[name]).indexOf(other.value) !== -1;
        });
        c.wrap.hidden = !show;
        c.input.disabled = !show;
      });
    }
    box.addEventListener('change', refresh);
    refresh();
    return box;
  }

  function open(line, opts) {
    opts = opts || {};
    var dialog = el('dialog', { className: 'mv-dialog', 'aria-labelledby': 'mv-title', 'data-move-dialog': '' });
    var form = el('form', { className: 'mv-form', 'hx-boost': 'false', novalidate: '' });
    dialog.append(form);
    (document.querySelector('#page-content') || document.body).append(dialog);
    form.append(el('h2', { id: 'mv-title', text: 'Move ' + line.name }), el('p', { className: 'mv-hint', text: 'Loading where it can go…' }));
    dialog.addEventListener('close', function () { dialog.remove(); });
    dialog.showModal();

    loadOptions().then(function () {
      form.replaceChildren();
      var groups = destinations(line);
      var title = el('h2', { id: 'mv-title', text: 'Move ' + line.name });
      var have = el('p', { className: 'mv-hint', text: fmt(line.quantity) + ' ' + (line.unit || '') + ' here' + (line.where ? ', at ' + line.where : '') + '.' });
      form.append(title, have);
      if (!groups.length) {
        form.append(el('p', { text: 'There is nowhere else to move it yet: add a stock area or another site in Settings, Sites.' }),
          el('div', { className: 'mv-actions' }, [el('button', { type: 'button', className: 'workspace-button', 'data-mv-cancel': '', text: 'Close' })]));
        form.querySelector('[data-mv-cancel]').addEventListener('click', function () { dialog.close(); });
        return;
      }
      var qty = el('input', { name: 'quantity', type: 'number', min: '0.0001', step: 'any', required: '', inputmode: 'decimal', id: 'mv-quantity' });
      qty.value = String(Number(line.quantity));
      var to = el('select', { name: 'to', required: '', id: 'mv-to' });
      to.append(el('option', { value: '', text: 'Choose where…' }));
      groups.forEach(function (g) {
        var og = el('optgroup', { label: g.label });
        g.items.forEach(function (d) { og.append(el('option', { value: d.site + '|' + d.location, text: d.label })); });
        to.append(og);
      });
      form.append(field('Quantity', qty, 'Up to ' + fmt(line.quantity) + ' ' + (line.unit || '') + '.'), field('To', to));

      // Only for another site: who takes it, the reference on the docket, and when it left.
      var trip = el('div', { className: 'mv-trip', hidden: '' });
      var carrier = el('input', { name: 'carrier', maxlength: '120', id: 'mv-carrier', placeholder: 'e.g. Own van, Mainfreight' });
      var reference = el('input', { name: 'consignment_reference', maxlength: '160', id: 'mv-reference' });
      reference.value = 'MV-' + today().replace(/-/g, '') + '-' + Math.random().toString(36).slice(2, 6).toUpperCase();
      var when = el('input', { name: 'occurred_on', type: 'date', id: 'mv-date', max: today() });
      when.value = today();
      var note = el('p', { className: 'mv-note' });
      trip.append(note,
        field('Carrier', carrier), field('Docket reference', reference, 'Printed on the transfer docket.'), field('Leaving on', when));
      var compliance = complianceFields(options.requirements || {});
      if (compliance) trip.append(compliance);
      form.append(trip);

      var error = el('p', { className: 'mv-error', role: 'alert', hidden: '' });
      var submit = el('button', { type: 'submit', className: 'workspace-button workspace-button--primary', 'data-mv-submit': '', text: 'Move' });
      var cancel = el('button', { type: 'button', className: 'workspace-button', text: 'Cancel' });
      form.append(error, el('div', { className: 'mv-actions' }, [cancel, submit]));
      cancel.addEventListener('click', function () { dialog.close(); });

      function chosen() {
        var parts = (to.value || '|').split('|');
        return { site: parts[0], location: parts[1] || null };
      }
      // Inside the licensed area or not, as the server says (the compliance register when there is one).
      function licensed(siteId, locationId) {
        var site = ((options.choices && options.choices.sites) || []).filter(function (s) { return s.id === siteId; })[0];
        if (!locationId) return site ? site.main_area_licensed !== false : true;
        var area = site ? site.areas.filter(function (a) { return a.id === locationId; })[0] : null;
        return area ? !!area.inside_licensed_area : true;
      }
      function boundary() { var c = chosen(); return !!c.site && licensed(line.site_id, line.location_id) !== licensed(c.site, c.location); }
      // Another site, or across the licensed-area boundary: a recorded dispatch and receipt.
      function crossing() { var c = chosen(); return !!c.site && (c.site !== line.site_id || boundary()); }
      function sync() {
        var away = crossing();
        trip.hidden = !away;
        note.textContent = away && chosen().site === line.site_id
          ? 'This crosses the licensed-area boundary, so it is recorded as a dispatch and a receipt.'
          : 'It shows as in transit until it is received there.';
        carrier.required = away;
        submit.textContent = away ? 'Dispatch' : 'Move';
        if (away && options.requirements && options.requirements.can_authorise === false) {
          error.textContent = 'Moving stock to another site needs someone with compliance permission to authorise it.';
          error.hidden = false;
          submit.disabled = true;
        } else { error.hidden = true; submit.disabled = false; }
      }
      to.addEventListener('change', sync);
      setTimeout(function () { to.focus(); }, 0);

      var key = null, last = null;
      form.addEventListener('submit', async function (e) {
        e.preventDefault();
        if (!to.value) { error.textContent = 'Choose where it is going.'; error.hidden = false; return; }
        var amount = Number(qty.value);
        if (!(amount > 0) || amount > Number(line.quantity)) {
          error.textContent = 'Move between 0 and ' + fmt(line.quantity) + ' ' + (line.unit || '') + '.';
          error.hidden = false;
          return;
        }
        var c = chosen();
        var body, path;
        if (crossing()) {
          if (!carrier.value.trim()) { error.textContent = 'Say who is taking it.'; error.hidden = false; return; }
          var approval = {};
          new FormData(form).forEach(function (v, k) { if (k.indexOf('approval.') === 0 && v) approval[k.slice(9)] = v; });
          body = { source_item_id: line.id, destination_site_id: c.site, destination_location_id: c.location, quantity: qty.value,
            carrier: carrier.value.trim(), consignment_reference: reference.value.trim(), occurred_on: when.value, approval: approval };
          path = '/api/core/site-transfers';
        } else {
          body = { quantity: qty.value, to_location_id: c.location, occurred_on: today() };
          path = '/api/core/inventory/' + encodeURIComponent(line.id) + '/move';
        }
        var json = JSON.stringify(body);
        if (json !== last) { key = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()); last = json; }
        submit.disabled = true;
        error.hidden = true;
        try {
          var result = await api('POST', path, body, crossing() ? key : null);
          dialog.close();
          if (opts.onDone) opts.onDone({ dispatched: crossing(), result: result, label: to.selectedOptions[0].textContent });
        } catch (err) {
          // A refusal stays in the dialog, next to what caused it.
          error.textContent = err.message;
          error.hidden = false;
          submit.disabled = false;
        }
      });
    }).catch(function (err) {
      form.replaceChildren(el('h2', { id: 'mv-title', text: 'Move ' + line.name }), el('p', { className: 'mv-error', text: err.message }),
        el('div', { className: 'mv-actions' }, [el('button', { type: 'button', className: 'workspace-button', 'data-mv-cancel': '', text: 'Close' })]));
      form.querySelector('[data-mv-cancel]').addEventListener('click', function () { dialog.close(); });
    });
    return dialog;
  }

  /** Whether this business can move stock anywhere: several sites, or areas inside one. */
  function available() {
    return loadOptions().then(function () {
      return (options.choices && options.choices.on && options.choices.sites.length > 1) || (options.locations || []).length > 0;
    }).catch(function () { return false; });
  }

  window.BizeMove = { open: open, available: available };
})();
