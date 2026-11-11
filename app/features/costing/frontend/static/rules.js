/* Purchase rules (live-cogs 8.1e-2 / 8.1c-2 UI). Binds to its page root on every arrival.
   DOM is built with createElement/textContent: payees and descriptions come from Xero. */
(function () {
  'use strict';
  var API = '/api/core/costing/rules';
  var TREATMENT = { stock: 'Stock to record', not_stock: 'Not stock', duty: 'Duty', overhead: 'Overhead' };
  var TONE = { stock: 'ok', not_stock: 'muted', duty: 'muted', overhead: 'muted' };
  var UNITS = ['kg', 'g', 'L', 'mL', 'units', 'pcs', 'bottles'];

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function key() {
    return window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : 'k' + Date.now() + Math.random();
  }
  function call(method, url, body, idem) {
    var token = document.querySelector('meta[name="csrf-token"]');
    var headers = { Accept: 'application/json' };
    if (method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRFToken'] = token ? token.content : '';
      if (idem) headers['Idempotency-Key'] = idem;
    }
    return fetch(url, { method: method, credentials: 'same-origin', headers: headers, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) {
          if (!r.ok) { var e = new Error(d.error || 'Something went wrong'); e.status = r.status; throw e; }
          return d;
        });
      });
  }

  /* "Payee is Moore Wilson and description contains juniper" */
  function sentence(rule) {
    var verb = rule.match_type === 'contains' ? ' contains ' : ' is ';
    var parts = [];
    if (rule.payee_pattern) parts.push(['Payee', verb, rule.payee_pattern]);
    if (rule.description_pattern) parts.push(['Description', verb, rule.description_pattern]);
    if (rule.account_code) parts.push(['Account', ' is ', rule.account_code]);
    var p = el('p', 'ru-rule__when');
    parts.forEach(function (part, i) {
      if (i) p.appendChild(document.createTextNode(' and '));
      p.appendChild(document.createTextNode(i ? part[0].toLowerCase() + part[1] : part[0] + part[1]));
      p.appendChild(el('strong', '', part[2]));
    });
    return p;
  }

  function templateSummary(rows) {
    return rows.map(function (r) {
      var share = r.share === 'rest' ? 'the rest' : Number(r.share) + '%';
      var qty = r.quantity_mode === 'fixed' ? r.quantity + ' ' + r.unit
        : r.quantity_mode === 'from_price' ? 'qty from $' + r.unit_price + ' per ' + r.unit
        : 'ask quantity';
      return r.name + ' — ' + share + ', ' + qty;
    });
  }

  function bind() {
    var root = document.querySelector('[data-rules-root]');
    if (!root || root.getAttribute('data-bound') === '1') return;
    root.setAttribute('data-bound', '1');
    var canManage = root.getAttribute('data-can-manage') === 'true';
    var q = function (sel) { return root.querySelector(sel); };
    var els = {
      error: q('[data-rules-error]'), state: q('[data-rules-state]'), list: q('[data-rules-list]'), empty: q('[data-rules-empty]'),
      add: q('[data-rules-add]'), dialog: q('[data-rules-dialog]'), form: q('[data-rules-form]'), title: q('[data-rules-dialog-title]'),
      rows: q('[data-rules-rows]'), addRow: q('[data-rules-add-row]'), template: q('[data-rules-template]'),
      dialogError: q('[data-rules-dialog-error]'), cancel: q('[data-rules-cancel]'), save: q('[data-rules-save]'),
    };
    var rules = [];
    var editing = null;
    var saveKey = null;
    var opener = null;

    function showError(message) { els.error.textContent = message || ''; els.error.hidden = !message; }

    function load() {
      return call('GET', API).then(function (body) {
        rules = body.rules || [];
        render();
      }).catch(function (err) { showError('Rules couldn’t load: ' + err.message); els.state.textContent = ''; })
        .finally(function () { root.setAttribute('aria-busy', 'false'); });
    }

    function render() {
      els.state.textContent = rules.length ? rules.length + (rules.length === 1 ? ' rule' : ' rules') : '';
      els.empty.hidden = rules.length > 0;
      els.list.replaceChildren();
      rules.forEach(function (rule) { els.list.appendChild(card(rule)); });
    }

    function card(rule) {
      var li = el('li', 'ru-rule workspace-card' + (rule.is_active ? '' : ' is-off'));
      var head = el('div', 'ru-rule__head');
      head.appendChild(sentence(rule));
      head.appendChild(el('span', 'cost-pill cost-pill--' + (rule.is_active ? TONE[rule.treatment] : 'muted'),
        rule.is_active ? TREATMENT[rule.treatment] : 'Off'));
      li.appendChild(head);
      if (rule.template && rule.template.length) {
        var list = el('ul', 'ru-rule__rows');
        templateSummary(rule.template).forEach(function (t) { list.appendChild(el('li', '', t)); });
        li.appendChild(list);
      }
      if (canManage) {
        var actions = el('div', 'ru-rule__actions');
        var edit = el('button', 'workspace-button', 'Edit');
        edit.type = 'button';
        edit.addEventListener('click', function () { open(rule, edit); });
        var toggle = el('button', 'workspace-button', rule.is_active ? 'Switch off' : 'Switch on');
        toggle.type = 'button';
        toggle.addEventListener('click', function () {
          toggle.disabled = true;
          call('PUT', API + '/' + encodeURIComponent(rule.id), body(rule, { is_active: !rule.is_active }), key())
            .then(function () { showError(''); return load(); })
            .catch(function (err) { toggle.disabled = false; showError(err.message); });
        });
        var del = el('button', 'workspace-button cost-link-button', 'Delete');
        del.type = 'button';
        del.addEventListener('click', function () {
          if (!window.confirm('Delete this rule? Purchases already recorded stay as they are.')) return;
          del.disabled = true;
          call('DELETE', API + '/' + encodeURIComponent(rule.id), null, key())
            .then(function () { showError(''); return load(); })
            .catch(function (err) { del.disabled = false; showError(err.message); });
        });
        actions.appendChild(edit);
        actions.appendChild(toggle);
        actions.appendChild(del);
        li.appendChild(actions);
      }
      return li;
    }

    function body(rule, changes) {
      var out = {
        account_code: rule.account_code, payee_pattern: rule.payee_pattern, description_pattern: rule.description_pattern,
        match_type: rule.match_type, treatment: rule.treatment, template: rule.template, is_active: rule.is_active,
      };
      Object.keys(changes || {}).forEach(function (k) { out[k] = changes[k]; });
      return out;
    }

    /* ---- dialog ---- */
    function field(name) { return els.form.elements[name]; }

    function open(rule, trigger) {
      editing = rule || null;
      opener = trigger || null;
      saveKey = key();
      els.title.textContent = rule ? 'Edit rule' : 'Add a rule';
      ['payee_pattern', 'description_pattern', 'account_code'].forEach(function (n) { field(n).value = rule && rule[n] ? rule[n] : ''; });
      field('match_type').value = rule ? rule.match_type : 'exact';
      field('treatment').value = rule ? rule.treatment : 'stock';
      els.rows.replaceChildren();
      (rule && rule.template ? rule.template : []).forEach(addRow);
      els.dialogError.textContent = '';
      els.save.disabled = false;
      syncTemplate();
      els.dialog.showModal();
      field('payee_pattern').focus();
    }

    function close() {
      els.dialog.close();
      if (opener && opener.isConnected) opener.focus();
    }

    function syncTemplate() { els.template.hidden = field('treatment').value !== 'stock'; }

    function addRow(data) {
      data = data || {};
      var row = el('div', 'ru-row');
      function input(label, name, value, attrs) {
        var wrap = el('label', 'cost-field ru-row__' + name);
        wrap.appendChild(el('span', 'cost-field__label', label));
        var node = el('input');
        node.type = 'text';
        node.name = name;
        node.autocomplete = 'off';
        node.value = value == null ? '' : value;
        Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        wrap.appendChild(node);
        row.appendChild(wrap);
        return node;
      }
      function select(label, name, options, value) {
        var wrap = el('label', 'cost-field ru-row__' + name);
        wrap.appendChild(el('span', 'cost-field__label', label));
        var node = el('select');
        node.name = name;
        options.forEach(function (o) {
          var opt = el('option', '', o[1]);
          opt.value = o[0];
          node.appendChild(opt);
        });
        node.value = value;
        wrap.appendChild(node);
        row.appendChild(wrap);
        return node;
      }
      input('Item', 'name', data.name, { maxlength: '255', placeholder: 'e.g. Juniper berries' });
      select('Unit', 'unit', UNITS.map(function (u) { return [u, u]; }), data.unit || 'kg');
      var shareSel = select('Share', 'share_kind', [['pct', '% of purchase'], ['rest', 'The rest']], data.share === 'rest' ? 'rest' : 'pct');
      var pct = input('%', 'share', data.share && data.share !== 'rest' ? Number(data.share) : '', { inputmode: 'decimal', placeholder: '100' });
      var mode = select('Quantity', 'quantity_mode', [['ask', 'Ask each time'], ['fixed', 'Same each time'], ['from_price', 'From the price']], data.quantity_mode || 'ask');
      var qty = input('How much', 'quantity', data.quantity, { inputmode: 'decimal' });
      var price = input('Price per unit', 'unit_price', data.unit_price, { inputmode: 'decimal' });
      var remove = el('button', 'workspace-button cost-link-button ru-row__remove', 'Remove');
      remove.type = 'button';
      remove.setAttribute('aria-label', 'Remove this item');
      remove.addEventListener('click', function () { row.remove(); });
      row.appendChild(remove);
      function sync() {
        pct.closest('label').hidden = shareSel.value === 'rest';
        qty.closest('label').hidden = mode.value !== 'fixed';
        price.closest('label').hidden = mode.value !== 'from_price';
      }
      shareSel.addEventListener('change', sync);
      mode.addEventListener('change', sync);
      sync();
      els.rows.appendChild(row);
      return row;
    }

    function readTemplate() {
      var rows = Array.prototype.slice.call(els.rows.querySelectorAll('.ru-row'));
      if (!rows.length || field('treatment').value !== 'stock') return null;
      return rows.map(function (row) {
        var get = function (n) { var node = row.querySelector('[name="' + n + '"]'); return node ? node.value.trim() : ''; };
        var out = { name: get('name'), unit: get('unit'), inventory_type: 'raw_material', quantity_mode: get('quantity_mode') };
        out.share = get('share_kind') === 'rest' ? 'rest' : get('share');
        if (out.quantity_mode === 'fixed') out.quantity = get('quantity');
        if (out.quantity_mode === 'from_price') out.unit_price = get('unit_price');
        return out;
      });
    }

    function save(e) {
      e.preventDefault();
      var text = function (n) { var v = field(n).value.trim(); return v || null; };
      var payload = {
        payee_pattern: text('payee_pattern'), description_pattern: text('description_pattern'), account_code: text('account_code'),
        match_type: field('match_type').value, treatment: field('treatment').value, template: readTemplate(),
        is_active: editing ? editing.is_active : true,
      };
      if (!payload.payee_pattern && !payload.description_pattern && !payload.account_code) {
        els.dialogError.textContent = 'Fill in a payee, a description or an account code.';
        field('payee_pattern').focus();
        return;
      }
      els.save.disabled = true;
      els.dialogError.textContent = '';
      var request = editing
        ? call('PUT', API + '/' + encodeURIComponent(editing.id), payload, saveKey)
        : call('POST', API, payload, saveKey);
      request.then(function () { close(); showError(''); return load(); })
        .catch(function (err) {
          els.save.disabled = false;
          if (err.status && err.status < 500) saveKey = key(); // a refusal: the next try is a new request
          els.dialogError.textContent = err.status === 409 ? 'A rule for exactly these purchases already exists. Edit that one instead.' : err.message;
          els.dialogError.focus && els.dialogError.focus();
        });
    }

    if (els.add) els.add.addEventListener('click', function () { open(null, els.add); });
    els.addRow.addEventListener('click', function () { var row = addRow({}); row.querySelector('input').focus(); });
    field('treatment').addEventListener('change', syncTemplate);
    els.cancel.addEventListener('click', close);
    els.form.addEventListener('submit', save);
    els.form.addEventListener('input', function () { saveKey = key(); });
    load();
  }

  bind();
  if (!window.__rulesPageListener) {
    window.__rulesPageListener = true;
    document.addEventListener('htmx:afterSettle', bind);
  }
})();
