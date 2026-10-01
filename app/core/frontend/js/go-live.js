// Go-live stocktake (plan 1.3). The server validates everything (whole bottles, ABV
// range, go-live date first); this page collects the count and shows what's recorded.
(function () {
  'use strict';

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  async function api(method, url, body) {
    var headers = { 'Accept': 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET') headers['X-CSRFToken'] = csrfToken();
    var resp = await fetch(url, { method: method, credentials: 'include', headers: headers,
      body: body === undefined ? undefined : JSON.stringify(body) });
    var data = {};
    try { data = await resp.json(); } catch (_) { /* empty */ }
    if (!resp.ok) throw new Error(data.error || ('Request failed (' + resp.status + ')'));
    return data;
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'className') node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) node.append(c); });
    return node;
  }

  function field(label, input) { return el('label', { className: 'gl-field' }, [document.createTextNode(label), input]); }

  function init(root) {
    if (!root || root.dataset.glBound === '1') return;
    root.dataset.glBound = '1';
    var $ = function (sel) { return root.querySelector(sel); };
    var state = { status: null };

    function say(text, ok) {
      var m = $('[data-gl-message]');
      m.textContent = text || '';
      m.className = 'gl-message ' + (ok ? 'gl-message--ok' : 'gl-message--error');
      m.hidden = !text;
      if (text) m.scrollIntoView({ block: 'nearest' });
    }

    function lotRow(product) {
      var counted = !!product.counted;
      var row = el('div', { className: 'gl-lot', 'data-gl-lot': product.name });
      row.append(
        field('Batch ID', el('input', { type: 'text', 'data-k': 'batch_id', placeholder: 'e.g. VAT44', maxlength: '255' })),
        field('Quantity (' + product.unit + ')', el('input', { type: 'number', 'data-k': 'quantity', min: '0', step: counted ? '1' : 'any', inputmode: counted ? 'numeric' : 'decimal' })),
        field('Bottled on', el('input', { type: 'date', 'data-k': 'bottled_on' })),
        field('ABV %', el('input', { type: 'number', 'data-k': 'abv_percent', min: '0', max: '100', step: '0.1' })),
        el('button', { type: 'button', className: 'gl-remove', 'aria-label': 'Remove this batch', text: '×' })
      );
      row.querySelector('.gl-remove').addEventListener('click', function () { row.remove(); });
      return row;
    }

    function renderProducts(finals) {
      var wrap = $('[data-gl-products]');
      wrap.replaceChildren();
      if (!finals.length) {
        wrap.append(el('p', { className: 'gl-hint', text: 'Add a workflow first: each workflow\'s final output gets a row here.' }));
        return;
      }
      finals.forEach(function (product) {
        var lots = el('div', { style: 'display:flex; flex-direction:column; gap:8px;' });
        lots.append(lotRow(product));
        var add = el('button', { type: 'button', className: 'gl-link-btn', text: '+ Add another batch' });
        add.addEventListener('click', function () { lots.append(lotRow(product)); });
        var name = el('div', { className: 'gl-product-name', text: product.name });
        name.append(el('span', { className: 'gl-product-meta', text: product.workflow }));
        var box = el('div', { className: 'gl-product', 'data-gl-product': product.name, 'data-unit': product.unit }, [name, lots, add]);
        if (product.counted) {
          box.append(el('div', { className: 'gl-row' }, [
            field('Library stock (mL, part-filled)', el('input', { type: 'number', min: '0', step: '1', inputmode: 'numeric', 'data-gl-library': product.name, placeholder: '0' }))
          ]));
        }
        wrap.append(box);
      });
    }

    function wipRow() {
      var row = el('div', { className: 'gl-wip', 'data-gl-wip': '1' });
      var unit = el('select', { 'data-k': 'unit' });
      ['l', 'ml', 'kg', 'g', 'units'].forEach(function (u) { unit.append(el('option', { value: u, text: u === 'l' ? 'L' : (u === 'ml' ? 'mL' : u) })); });
      row.append(
        field('What', el('input', { type: 'text', 'data-k': 'name', list: 'gl-intermediate-names', placeholder: 'e.g. Aged gin' })),
        field('Quantity', el('input', { type: 'number', 'data-k': 'quantity', min: '0', step: 'any' })),
        field('Unit', unit),
        field('ABV %', el('input', { type: 'number', 'data-k': 'abv_percent', min: '0', max: '100', step: '0.1' })),
        field('Batch ID', el('input', { type: 'text', 'data-k': 'batch_id', placeholder: 'e.g. Barrel 3' })),
        el('button', { type: 'button', className: 'gl-remove', 'aria-label': 'Remove', text: '×' })
      );
      row.querySelector('.gl-remove').addEventListener('click', function () { row.remove(); });
      return row;
    }

    function renderOpening(items) {
      var wrap = $('[data-gl-opening-wrap]');
      var body = $('[data-gl-opening-rows]');
      body.replaceChildren();
      (items || []).forEach(function (i) {
        body.append(el('tr', {}, [
          el('td', { text: i.name }), el('td', { text: i.batch_id || '—' }),
          el('td', { text: i.quantity + ' ' + ({ l: 'L', ml: 'mL' }[String(i.unit).toLowerCase()] || i.unit) }),
          el('td', { text: i.abv_percent ? i.abv_percent + '%' : '—' }),
          el('td', { text: i.bottled_on || '—' })
        ]));
      });
      wrap.hidden = !(items && items.length);
    }

    function render(status) {
      state.status = status;
      var date = $('[data-gl-date]');
      date.value = status.go_live_date || new Date().toISOString().slice(0, 10);
      root.querySelector('[data-gl-step="date"]').classList.toggle('gl-step--done', !!status.go_live_date);
      var wf = status.workflow_count || 0;
      $('[data-gl-workflow-summary]').textContent = wf
        ? wf + (wf === 1 ? ' workflow' : ' workflows') + ' set up. Each one\'s final output appears under Finished goods below.'
        : 'No workflows yet. Start from a template for your type of production, or build one step by step.';
      root.querySelector('[data-gl-step="workflows"]').classList.toggle('gl-step--done', wf > 0);
      $('[data-gl-raw-summary]').textContent = (status.raw_material_count || 0) + ' raw material and packaging lines in stock. Add them the usual way, by hand, spreadsheet or barcode.';
      renderProducts(status.final_outputs || []);
      var dl = document.getElementById('gl-intermediate-names');
      dl.replaceChildren();
      (status.intermediate_outputs || []).forEach(function (o) { dl.append(el('option', { value: o.name })); });
      if (!$('[data-gl-wip-rows]').children.length) $('[data-gl-wip-rows]').append(wipRow());
      renderOpening(status.opening_items);
      root.querySelector('[data-gl-step="count"]').classList.toggle('gl-step--done', !!(status.opening_items || []).length);
    }

    function collectRows() {
      var rows = [];
      root.querySelectorAll('[data-gl-product]').forEach(function (box) {
        var name = box.getAttribute('data-gl-product');
        var unit = box.getAttribute('data-unit');
        box.querySelectorAll('[data-gl-lot]').forEach(function (lot) {
          var get = function (k) { var i = lot.querySelector('[data-k="' + k + '"]'); return i ? i.value.trim() : ''; };
          if (!get('quantity')) return;
          rows.push({ name: name, unit: unit, inventory_type: 'final_product', quantity: get('quantity'),
            batch_id: get('batch_id'), bottled_on: get('bottled_on'), abv_percent: get('abv_percent') });
        });
        var lib = box.querySelector('[data-gl-library]');
        if (lib && lib.value.trim()) {
          rows.push({ name: name + ' - Library stock', unit: 'ml', inventory_type: 'final_product', quantity: lib.value.trim() });
        }
      });
      root.querySelectorAll('[data-gl-wip]').forEach(function (w) {
        var get = function (k) { var i = w.querySelector('[data-k="' + k + '"]'); return i ? i.value.trim() : ''; };
        if (!get('name') || !get('quantity')) return;
        rows.push({ name: get('name'), unit: get('unit'), inventory_type: 'work_in_progress', quantity: get('quantity'),
          abv_percent: get('abv_percent'), batch_id: get('batch_id') });
      });
      return rows;
    }

    $('[data-gl-add-wip]').addEventListener('click', function () { $('[data-gl-wip-rows]').append(wipRow()); });

    $('[data-gl-save-date]').addEventListener('click', async function () {
      try {
        render(await api('PUT', '/api/core/go-live', { go_live_date: $('[data-gl-date]').value }));
        say('Go-live date saved. Tracing starts on ' + state.status.go_live_date + '.', true);
      } catch (err) { say(err.message, false); }
    });

    $('[data-gl-save-count]').addEventListener('click', async function () {
      var error = $('[data-gl-count-error]');
      error.hidden = true;
      var rows = collectRows();
      if (!rows.length) { error.textContent = 'Enter at least one quantity.'; error.hidden = false; return; }
      try {
        var result = await api('POST', '/api/core/opening-stock', { items: rows });
        $('[data-gl-wip-rows]').replaceChildren();
        render(result);
        say('Recorded ' + result.created + (result.created === 1 ? ' line' : ' lines') + ' of opening stock.', true);
      } catch (err) { error.textContent = err.message; error.hidden = false; }
    });

    api('GET', '/api/core/go-live').then(render).catch(function (err) { say(err.message, false); });
  }

  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  bize.onPage('[data-go-live-root]', init);
})();
