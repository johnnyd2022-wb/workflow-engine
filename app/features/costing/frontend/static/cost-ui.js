/* Live cost where people look (spec 8.1e-2): the lot cost panel, the batch cost card and the
   "Total paid" field on Add Inventory. One module, loaded by each page that shows cost; every
   piece first asks /api/core/costing/me and renders nothing at all for someone who can't see cost.
   DOM is built with createElement/textContent only: lot and supplier names are user/Xero text. */
(function () {
  'use strict';
  if (window.BizECost) return; // shared module; pages bind their own roots

  var API = '/api/core/costing';
  var mePromise = null;
  var meAt = 0;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function csrf() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }
  /* One retry key per logical action (remove this entry, mark this lot free), kept until the
     server answers for certain, so a retry after a lost reply replays instead of repeating. */
  var actionKeys = {};
  function keyFor(id) { return actionKeys[id] || (actionKeys[id] = newKey()); }
  function settle(id, err) { if (!err || (err.status && err.status < 500 && err.status !== 409)) delete actionKeys[id]; }
  function newKey() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return 'k' + Date.now().toString(36) + Math.random().toString(36).slice(2);
  }
  function request(method, url, body, key) {
    var headers = { 'Accept': 'application/json' };
    if (method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRFToken'] = csrf();
      if (key) headers['Idempotency-Key'] = key;
    }
    return fetch(url, { method: method, credentials: 'same-origin', headers: headers, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          if (!r.ok) { var err = new Error(data.error || 'Something went wrong'); err.status = r.status; throw err; }
          return data;
        });
      });
  }

  /* Who may see and enter cost. Cached briefly; a 404 (feature off) is "no". */
  function me() {
    if (mePromise && Date.now() - meAt < 30000) return mePromise;
    meAt = Date.now();
    mePromise = request('GET', API + '/me').catch(function () {
      return { enabled: false, can_view: false, can_manage: false };
    });
    return mePromise;
  }

  /* Money: always 2 dp, up to 4 when the cents matter ($0.0125 per g). */
  function money(value) {
    if (value == null || value === '') return null;
    var n = Number(value);
    if (!isFinite(n)) return null;
    var abs = Math.abs(n);
    var digits = abs !== 0 && abs < 1 && Math.round(abs * 100) !== abs * 100 ? 4 : 2;
    var text = abs.toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: digits });
    return (n < 0 ? '−$' : '$') + text;
  }
  function perUnit(value, unit) {
    var m = money(value);
    return m ? m + (unit ? ' per ' + unit : '') : null;
  }
  /* "= $1.38 per bottle · $1.97 per litre": stock counted in units whose name carries a pack size
     ("Glass bottle 700 mL", "Juniper 25 kg bag") also gets the bulk price, so a 700 mL and a 1 L
     bottle can be compared. Anything else reads "= $X per <unit>" as before. */
  var COUNT_UNITS = /^(bottles?|units?|each|ea|cases?|cans?|jars?|packs?|bags?|boxes|box|pcs|pieces?|sacks?|tubs?|pallets?|containers?|kegs?)$/i;
  function parsePack(text, typed) {
    // A size in the text: "700 mL", "1,000 mL" (thousands comma), "1,5 L" (decimal comma), ".5L",
    // "25kg". A multipack ("24 x 200ml", "6x700ml", "700ml x 6") counts every container. A ratio
    // ("650 g/L") is a strength, not a size, and is skipped. The last size wins. Mirrors
    // app/core/utils/packs.py parse_pack, which the server uses to store the pack.
    var src = String(text || '').replace(/\u00a0/g, ' ');
    var re = /(?:(\d+)\s*[x×]\s*)?(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d*[.,]?\d+)\s*(ml|millilitres?|milliliters?|l|litres?|liters?|g|grams?|kg|kilos?|kilograms?)(?![a-z])(?!\s*\/)(?:\s*[x×]\s*(\d+)(?!\s*[a-z]))?/gi;
    var match, last = null;
    while ((match = re.exec(src)) !== null) last = match;
    if (!last) {
      // Typed into the Pack size field (never read from a name): a count with no size, "500 labels".
      var counted = typed ? /^\s*(\d{1,6})\s*(?:[x×]\s*)?(?:([a-z])[a-z .\-]{0,30})?\s*$/i.exec(src) : null;
      // "12 oz" is a weight we can't read, not twelve of something: refuse it rather than guess.
      var word = typed ? src.replace(/^\s*\d+\s*(?:[x×]\s*)?/i, '').trim().toLowerCase().split(' ')[0] : '';
      var weight = /^(oz|ounces?|lbs?|pounds?|gal|gallons?|mg|milligrams?|cl|dl|pts?|pints?|qts?|quarts?|tonnes?|tons?|fl|met(re|er)s?|cm|mm|ft|foot|feet|inch(es)?|in|l|ml|g|kg)$/.test(word);
      return counted && !weight && Number(counted[1]) > 1 ? { count: Number(counted[1]), size: null, unit: null } : null;
    }
    var raw = last[2];
    var size = /^\d{1,3}(,\d{3})+(\.\d+)?$/.test(raw) ? Number(raw.replace(/,/g, '')) : Number(raw.replace(',', '.'));
    var count = Number(last[1] || last[4] || 1);
    var u = last[3].toLowerCase();
    if (!(size > 0) || !(count > 0)) return null;
    var unit = /^(ml|milli)/.test(u) ? 'mL' : /^(l$|litre|liter)/.test(u) ? 'L' : /^(g$|gram)/.test(u) ? 'g' : 'kg';
    return { count: count, size: size, unit: unit };
  }
  function packText(pack) {
    if (!pack) return '';
    if (!pack.unit) return pack.count + ' pcs';
    var size = pack.size.toLocaleString('en-NZ', { maximumFractionDigits: 4 }) + ' ' + pack.unit;
    return pack.count > 1 ? pack.count + ' × ' + size : size;
  }
  function packSize(name, packed) {
    // The stored/typed pack when there is one, else a size in the item's name.
    var pack = packed == null ? parsePack(name) : packed ? parsePack(packed, true) : null; // a pack field's blank means none
    if (!pack) return null;
    if (!pack.unit) return { count: pack.count, amount: null, per: null }; // a count, no size
    var n = pack.size * pack.count;
    var bulk = pack.unit === 'mL' ? { amount: n / 1000, per: 'litre' } : pack.unit === 'L' ? { amount: n, per: 'litre' }
      : pack.unit === 'g' ? { amount: n / 1000, per: 'kg' } : { amount: n, per: 'kg' };
    bulk.count = pack.count;
    return bulk;
  }
  function packHint(amount, quantity, unit, name, packed) {
    var each = amount / quantity;
    var counted = COUNT_UNITS.test(String(unit || '').trim());
    var first = counted && /^(each|ea)$/i.test(String(unit).trim())
      ? '= ' + money(each) + ' each'
      : '= ' + perUnit(each, counted ? dutyUnit(unit) : unit);
    var pack = counted ? packSize(name, packed) : null;
    if (!pack) return first;
    // "= $48.00 per case · $2.00 each of 24 · $10.00 per litre"
    var parts = [first];
    if (pack.count > 1) parts.push(money(each / pack.count) + ' each of ' + pack.count);
    if (pack.per) parts.push(perUnit(each / pack.amount, pack.per));
    return parts.join(' · ');
  }
  function dutyUnit(unit) {
    var words = { bottles: 'bottle', units: 'unit', cases: 'case', cans: 'can', jars: 'jar', packs: 'pack',
      bags: 'bag', boxes: 'box', pieces: 'piece', sacks: 'sack', tubs: 'tub', pcs: 'piece',
      kegs: 'keg', containers: 'container', pallets: 'pallet' };
    return words[String(unit || '').toLowerCase()] || unit || 'unit';
  }
  /* The batch card's duty line (spec Q6): never a guess; "not tracked" when the module is off. */
  function dutyLine(duty, unit) {
    if (!duty) return null;
    if (!duty.tracked) return 'Duty not tracked';
    if (duty.per_unit == null) return 'Duty not worked out — ' + (duty.missing || 'Not an excise product or no rate set');
    return 'Duty if sold today ' + (money(duty.per_unit) || '—') + ' · landed ' +
      (money(duty.landed_per_unit) || '—') + ' per ' + dutyUnit(unit);
  }
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }

  var SOURCE_WORDS = {
    purchase: 'Recorded from a purchase',
    manual: 'Entered by hand',
    free: 'Free',
    production: 'From the batch that made it',
    transfer: 'Moved from another site',
    mixed: 'From more than one source',
    none: null,
  };

  function statusLine(cost) {
    var unit = cost.unit;
    if (cost.status === 'actual') return { tone: 'ok', text: perUnit(cost.unit_cost, unit) };
    if (cost.status === 'estimated') {
      var from = cost.estimate_from && cost.estimate_from.name !== cost.name ? ' from ' + cost.estimate_from.name : ' from the last price paid';
      return { tone: 'warn', text: 'Estimated' + from + ' — ' + perUnit(cost.unit_cost, unit) };
    }
    if (cost.status === 'partial') {
      var known = Number(cost.known_unit_cost) > 0 ? ' — ' + perUnit(cost.known_unit_cost, unit) + ' so far' : '';
      return { tone: 'warn', text: 'Not fully costed' + known };
    }
    return { tone: 'muted', text: 'Not costed yet' };
  }

  function pill(tone, text) {
    var node = el('span', 'cost-pill cost-pill--' + tone, text);
    return node;
  }

  /* ---------------------------------------------------------------- lot cost panel */

  function lotPanel(itemId, mount, options) {
    options = options || {};
    if (!mount || !itemId) return;
    mount.replaceChildren();
    me().then(function (who) {
      if (!who.can_view) { mount.hidden = true; return; }
      mount.hidden = false;
      var section = el('section', 'cost-panel');
      section.setAttribute('aria-label', 'Cost');
      section.appendChild(el('h3', 'cost-panel__title', 'Cost'));
      var body = el('div', 'cost-panel__body');
      body.appendChild(el('p', 'cost-muted', 'Loading cost…'));
      section.appendChild(body);
      mount.appendChild(section);
      load();

      function load() {
        request('GET', API + '/lots/' + encodeURIComponent(itemId) + '/cost')
          .then(function (cost) { render(cost); })
          .catch(function () { body.replaceChildren(el('p', 'cost-muted', 'Cost isn’t available right now.')); });
      }

      function render(cost) {
        body.replaceChildren();
        var line = statusLine(cost);
        var head = el('p', 'cost-panel__figure');
        head.appendChild(pill(line.tone, line.text));
        body.appendChild(head);

        var facts = el('dl', 'cost-facts');
        var source = SOURCE_WORDS[cost.source];
        var from = provenanceNode(cost.provenance);
        if (from && cost.status !== 'unknown') addFact(facts, 'Source', from);
        else if (source && cost.status !== 'unknown') addFact(facts, 'Source', source);
        var split = cost.pack_breakdown; // a multipack lot: its price per bottle and per litre or kg
        if (split) {
          addFact(facts, 'Pack', split.pack);
          if (split.per_container) {
            addFact(facts, split.containers > 1 ? 'Each' : 'Per ' + split.pack, money(split.per_container) + (split.containers > 1 ? ' (1 of ' + split.containers + ')' : ''));
          }
          if (split.per_litre) addFact(facts, 'Per litre', money(split.per_litre));
          if (split.per_kg) addFact(facts, 'Per kg', money(split.per_kg));
        }
        if (Number(cost.unpriced_quantity) > 0 && Number(cost.priced_quantity) > 0) {
          addFact(facts, 'Priced', cost.priced_quantity + ' of ' + (Number(cost.priced_quantity) + Number(cost.unpriced_quantity)) + ' ' + (cost.unit || ''));
        }
        if (facts.childNodes.length) body.appendChild(facts);

        var others = (cost.missing || []).filter(function (m) { return m.inventory_item_id !== cost.inventory_item_id; });
        if (others.length) body.appendChild(missingLine(others));
        if ((cost.warnings || []).indexOf('refund_exceeds_cost') >= 0) {
          body.appendChild(el('p', 'cost-muted', 'A refund on this lot is bigger than what it cost, so its cost shows as $0.'));
        }

        var hand = (cost.entries || []).filter(function (e) { return e.kind === 'manual' || e.kind === 'free'; });
        if (hand.length) {
          var list = el('ul', 'cost-entries');
          hand.forEach(function (entry) {
            var li = el('li', 'cost-entries__row');
            var label = entry.kind === 'free' ? 'Marked free' : money(entry.amount) + ' for ' + entry.quantity + ' ' + (cost.unit || '');
            li.appendChild(el('span', '', label));
            if (who.can_manage && cost.editable) {
              var remove = el('button', 'workspace-button cost-link-button', 'Remove');
              remove.type = 'button';
              remove.setAttribute('aria-label', 'Remove ' + label);
              remove.addEventListener('click', function () {
                remove.disabled = true;
                var removeId = 'delete:' + entry.id;
                request('DELETE', API + '/lots/' + encodeURIComponent(itemId) + '/cost/' + encodeURIComponent(entry.id), null, keyFor(removeId))
                  .then(function (next) { settle(removeId); render(next); if (options.onChange) options.onChange(next); })
                  .catch(function (err) { settle(removeId, err); remove.disabled = false; showError(err.message); });
              });
              li.appendChild(remove);
            }
            list.appendChild(li);
          });
          body.appendChild(list);
        }

        if (!cost.editable) return; // its cost comes from where it was made or moved from (Source says which)
        if (!who.can_manage) return;
        body.appendChild(entryForm(cost));
      }

      function entryForm(cost) {
        var wrap = el('div', 'cost-entry');
        var open = el('button', 'workspace-button', cost.status === 'actual' ? 'Change what was paid' : 'Enter what was paid');
        open.type = 'button';
        var free = el('button', 'workspace-button cost-link-button', 'Mark as free');
        free.type = 'button';
        var actions = el('div', 'cost-entry__actions');
        actions.appendChild(open);
        actions.appendChild(free);
        wrap.appendChild(actions);

        var form = el('form', 'cost-entry__form');
        form.hidden = true;
        form.noValidate = true;
        var label = el('label', 'cost-field');
        label.appendChild(el('span', 'cost-field__label', 'Total paid (ex GST)'));
        var input = el('input');
        input.type = 'text';
        input.inputMode = 'decimal';
        input.autocomplete = 'off';
        input.className = 'cost-money-input';
        label.appendChild(input);
        form.appendChild(label);
        var hint = el('p', 'cost-hint', 'For all ' + wholeQuantity(cost) + ' ' + (cost.unit || '') + ' this lot came in with.');
        form.appendChild(hint);
        var error = el('p', 'cost-error');
        error.setAttribute('role', 'alert');
        form.appendChild(error);
        var row = el('div', 'cost-entry__actions');
        var save = el('button', 'workspace-button workspace-button--primary', 'Save');
        save.type = 'submit';
        var cancel = el('button', 'workspace-button cost-link-button', 'Cancel');
        cancel.type = 'button';
        row.appendChild(save);
        row.appendChild(cancel);
        form.appendChild(row);
        wrap.appendChild(form);

        var key = null; // one key per entry attempt, kept across retries of it
        open.addEventListener('click', function () { form.hidden = false; actions.hidden = true; key = newKey(); input.focus(); });
        cancel.addEventListener('click', function () { form.hidden = true; actions.hidden = false; error.textContent = ''; open.focus(); });
        input.addEventListener('input', function () { key = newKey(); error.textContent = ''; });
        form.addEventListener('submit', function (e) {
          e.preventDefault();
          var amount = parseMoney(input.value);
          if (amount == null) { error.textContent = 'Enter an amount, like 45.00'; input.focus(); return; }
          save.disabled = true;
          request('PUT', API + '/lots/' + encodeURIComponent(itemId) + '/cost', { kind: 'manual', amount: amount, quantity: wholeQuantity(cost), replace: 'all' }, key)
            .then(function (next) { render(next); if (options.onChange) options.onChange(next); })
            .catch(function (err) { save.disabled = false; error.textContent = err.message; input.focus(); });
        });
        free.addEventListener('click', function () {
          free.disabled = true;
          request('PUT', API + '/lots/' + encodeURIComponent(itemId) + '/cost', { kind: 'free', replace: 'all' }, keyFor('free:' + itemId))
            .then(function (next) { settle('free:' + itemId); render(next); if (options.onChange) options.onChange(next); })
            .catch(function (err) { settle('free:' + itemId, err); free.disabled = false; showError(err.message); });
        });
        return wrap;
      }

      function showError(message) {
        var p = el('p', 'cost-error', message);
        p.setAttribute('role', 'alert');
        body.appendChild(p);
      }
    });
  }

  /* "Waiting on Coriander seed, Juniper berries (2 lots)": one link per material, to its lot. */
  function missingLine(missing) {
    var groups = [];
    var byName = {};
    missing.forEach(function (m) {
      var name = m.name || 'Unnamed lot';
      if (!byName[name]) { byName[name] = { name: name, ids: [] }; groups.push(byName[name]); }
      byName[name].ids.push(m.inventory_item_id);
    });
    var p = el('p', 'cost-muted');
    p.appendChild(document.createTextNode('Waiting on the cost of '));
    groups.forEach(function (g, i) {
      if (i) p.appendChild(document.createTextNode(i === groups.length - 1 ? ' and ' : ', '));
      var a = el('a', '', g.name);
      a.href = '/core/inventory/view?item=' + encodeURIComponent(g.ids[0]);
      p.appendChild(a);
      if (g.ids.length > 1) p.appendChild(document.createTextNode(' (' + g.ids.length + ' lots)'));
    });
    p.appendChild(document.createTextNode('.'));
    return p;
  }

  function wholeQuantity(cost) {
    var total = Number(cost.priced_quantity || 0) + Number(cost.unpriced_quantity || 0);
    return total > 0 ? String(total) : '1';
  }

  function addFact(list, term, value) {
    var row = el('div', 'cost-facts__row');
    row.appendChild(el('dt', '', term));
    var dd = el('dd');
    if (value && value.nodeType) dd.appendChild(value); else dd.textContent = value;
    row.appendChild(dd);
    list.appendChild(row);
  }

  /* "Recorded from Botanical Supply Co, 3 Oct 2026" with a link to where it came from. */
  function provenanceNode(p) {
    if (!p || typeof p.href !== 'string' || p.href.charAt(0) !== '/' || p.href.charAt(1) === '/') return null;
    var when = p.date ? new Date(p.date + 'T00:00:00').toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' }) : '';
    var lead = { purchase: 'Recorded from ', batch: 'Made in a ',
      transfer: p.site ? 'Moved from ' + p.site + ' — ' : 'Moved from another site — ' }[p.kind];
    if (!lead) return null;
    var span = el('span');
    span.appendChild(document.createTextNode(lead));
    var a = el('a', '', p.kind === 'batch' ? (p.name || 'batch') + ' batch' : p.kind === 'transfer' ? 'the lot it came from' : (p.name || 'a purchase'));
    a.href = p.href;
    span.appendChild(a);
    if (when) span.appendChild(document.createTextNode(', ' + when));
    return span;
  }

  /* "45", "45.5", "$1,200.00" -> "1200.00"; null when it isn't money (4 dp max, not negative). */
  function parseMoney(raw) {
    var text = String(raw == null ? '' : raw).replace(/[$,\s]/g, '');
    if (!/^\d+(\.\d{1,4})?$/.test(text)) return null;
    return text;
  }

  /* ---------------------------------------------------------------- batch cost card */

  function batchCard(executionId, mount) {
    if (!mount || !executionId) return;
    mount.replaceChildren();
    mount.hidden = true;
    me().then(function (who) {
      if (!who.can_view) return;
      request('GET', API + '/executions/' + encodeURIComponent(executionId) + '/cost').then(function (cost) {
        mount.hidden = false;
        mount.replaceChildren(renderBatch(cost));
      }).catch(function () { /* no card is better than a broken one */ });
    });
  }

  function renderBatch(cost) {
    var card = el('section', 'cost-card');
    card.setAttribute('aria-label', 'Batch cost');
    card.appendChild(el('h4', 'cost-card__title', 'Cost'));
    if ((cost.warnings || []).indexOf('too_large') >= 0) {
      card.appendChild(el('p', 'cost-muted', 'This batch’s history is too long to cost here.'));
      return card;
    }
    var outputs = cost.outputs || [];
    var finished = outputs.length > 0;
    var total = finished ? cost.known_input_cost : cost.cost_so_far;
    if (!finished && !(cost.inputs || []).length) {
      card.appendChild(el('p', 'cost-muted', 'No materials recorded against this batch yet. Cost builds up as each step records what went in.'));
      return card;
    }
    var figures = el('div', 'cost-card__figures');
    figures.appendChild(figure(finished ? 'Materials' : 'Cost so far', money(total) || '$0.00'));
    outputs.forEach(function (o) {
      var unitText = perUnit(o.unit_cost, o.unit);
      var outputFigure = figure(o.name + ' per ' + dutyUnit(o.unit), unitText ? money(o.unit_cost) : '—');
      var line = dutyLine(o.duty_today, o.unit);
      if (line) outputFigure.appendChild(el('p', 'cost-muted', line));
      figures.appendChild(outputFigure);
    });
    card.appendChild(figures);

    var status = finished ? cost.status : cost.cost_so_far_status;
    if (status === 'estimated') card.appendChild(pill('warn', 'Includes estimates from earlier prices'));
    if (status === 'partial' || status === 'unknown' || (cost.missing || []).length) {
      var missing = cost.missing || [];
      var box = el('div', 'cost-card__missing');
      box.appendChild(pill('warn', missing.length ? 'Incomplete — ' + plural(missing.length, 'input') + ' not costed' : 'Incomplete'));
      if (missing.length) {
        var list = el('ul', 'cost-card__missing-list');
        missing.forEach(function (m) {
          var li = el('li');
          var a = el('a', '', m.name || 'Unnamed lot');
          a.href = '/core/inventory/view?item=' + encodeURIComponent(m.inventory_item_id);
          li.appendChild(a);
          list.appendChild(li);
        });
        box.appendChild(list);
        box.appendChild(el('p', 'cost-muted', 'Open a lot to enter what was paid for it.'));
      }
      card.appendChild(box);
    }
    if (cost.split_assumed) {
      card.appendChild(el('p', 'cost-muted', 'Cost is split between outputs by quantity, because no split was recorded.'));
    }
    return card;
  }

  function figure(label, value) {
    var wrap = el('div', 'cost-figure');
    wrap.appendChild(el('span', 'cost-figure__label', label));
    wrap.appendChild(el('span', 'cost-figure__value', value));
    return wrap;
  }

  /* ---------------------------------------------------------------- Add Inventory field */

  /* Adds "Total paid (ex GST)" after `anchor` for people who may enter cost. Returns a handle
     whose value() is the money string, null when blank, or false when it isn't valid. */
  function totalPaidField(anchor, options) {
    options = options || {};
    var handle = { value: function () { return null; }, ready: me() };
    if (!anchor) return handle;
    handle.ready.then(function (who) {
      if (!who.can_manage) return;
      var wrap = el('div', 'cost-add-field ' + (options.className || ''));
      // Stable id (one field per form): a boosted visit must render the same page as a full load.
      var id = options.id || 'cost-total-paid';
      var label = el('label', options.labelClass || 'cost-field__label', 'Total paid (ex GST) ');
      label.htmlFor = id;
      label.appendChild(el('span', 'cost-optional', '(optional)'));
      var input = el('input');
      input.id = id;
      input.type = 'text';
      input.inputMode = 'decimal';
      input.autocomplete = 'off';
      input.name = 'totalPaid';
      input.placeholder = '0.00';
      input.className = options.inputClass || 'cost-money-input';
      var hint = el('p', 'cost-hint');
      hint.id = id + '-hint';
      hint.setAttribute('aria-live', 'polite');
      input.setAttribute('aria-describedby', hint.id);
      wrap.appendChild(label);
      wrap.appendChild(input);
      wrap.appendChild(hint);
      anchor.insertAdjacentElement('afterend', wrap);

      function update() {
        var raw = input.value.trim();
        if (!raw) { hint.textContent = options.hint || 'Lets Biz-E cost every batch made from this stock.'; wrap.classList.remove('is-invalid'); return; }
        var amount = parseMoney(raw);
        if (amount == null) { hint.textContent = 'Enter an amount, like 45.00'; wrap.classList.add('is-invalid'); return; }
        wrap.classList.remove('is-invalid');
        var q = options.quantity ? Number(options.quantity()) : NaN;
        var unit = options.unit ? options.unit() : '';
        hint.textContent = q > 0 ? packHint(Number(amount), q, unit, options.name ? options.name() : '', options.pack ? options.pack() : null) : '';
      }
      input.addEventListener('input', update);
      (options.watch || []).forEach(function (node) { if (node) node.addEventListener('input', update); if (node) node.addEventListener('change', update); });
      update();
      handle.value = function () {
        var raw = input.value.trim();
        if (!raw) return null;
        var amount = parseMoney(raw);
        if (amount == null) { input.focus(); return false; }
        return amount;
      };
      handle.clear = function () { input.value = ''; update(); };
      handle.refresh = update; // a form that fills name/quantity/unit in code calls this after
      handle.input = input;
    });
    return handle;
  }

  /* "Pack size" on Add Inventory: what one unit of counted stock holds ("24 × 200 mL"), so a
     workflow can use it in bottles, mL or g and cost each by its share. Not a cost field: shown to
     everyone adding stock, for counted units only. Filled from the item's name until edited. */
  function packField(anchor, options) {
    options = options || {};
    var handle = { value: function () { return null; }, refresh: function () {}, attached: false };
    if (!anchor) return handle;
    var id = options.id || 'inventory-pack';
    var wrap = el('div', 'cost-add-field pack-field');
    var label = el('label', options.labelClass || 'cost-field__label', 'Pack size ');
    label.htmlFor = id;
    label.appendChild(el('span', 'cost-optional', '(optional)'));
    var input = el('input');
    input.id = id;
    input.type = 'text';
    input.autocomplete = 'off';
    input.name = 'pack';
    input.placeholder = 'e.g. 24 × 200 mL';
    input.className = options.inputClass || 'cost-money-input';
    var hint = el('p', 'cost-hint');
    hint.id = id + '-hint';
    hint.setAttribute('aria-live', 'polite');
    input.setAttribute('aria-describedby', hint.id);
    wrap.appendChild(label);
    wrap.appendChild(input);
    wrap.appendChild(hint);
    anchor.insertAdjacentElement('afterend', wrap);
    var edited = false;
    if (options.initial) { input.value = options.initial; edited = true; }

    function unitWord() { return dutyUnit(options.unit ? options.unit() : ''); }
    function update() {
      paint();
      if (options.onChange) options.onChange(); // the cost hint follows the pack, filled, cleared or unreadable
    }
    function paint() {
      var counted = COUNT_UNITS.test(String(options.unit ? options.unit() : '').trim());
      if (!edited && options.name) input.value = counted ? packText(parsePack(options.name())) : '';
      wrap.hidden = !counted && !input.value.trim();
      var raw = input.value.trim();
      wrap.classList.remove('is-invalid');
      if (!raw) { hint.textContent = 'What one ' + unitWord() + ' holds, so workflows can use it in bottles, mL or g.'; return; }
      var pack = parsePack(raw, true);
      if (!pack) { hint.textContent = 'Write it like 24 × 200 mL, 700 mL, 25 kg or 500 pcs'; wrap.classList.add('is-invalid'); return; }
      if (!pack.unit) hint.textContent = 'One ' + unitWord() + ' = ' + pack.count + '. Workflows can take single ones.';
      else hint.textContent = pack.count > 1
        ? 'One ' + unitWord() + ' = ' + pack.count + ' × ' + packText({ count: 1, size: pack.size, unit: pack.unit }) +
          '. Workflows can take single ones or ' + (pack.unit === 'g' || pack.unit === 'kg' ? 'grams' : 'mL') + '.'
        : 'One ' + unitWord() + ' holds ' + packText(pack) + '.';
    }
    input.addEventListener('input', function () { edited = true; update(); }); // blank by hand stays blank
    (options.watch || []).forEach(function (node) { if (node) { node.addEventListener('input', update); node.addEventListener('change', update); } });
    update();
    handle.attached = true;
    handle.input = input;
    handle.refresh = update;
    handle.text = function () { return wrap.hidden ? '' : input.value.trim(); };
    handle.value = function () {
      // null: none given; false: unreadable (the form says so); else the text the server parses
      if (wrap.hidden) return null;
      var raw = input.value.trim();
      if (!raw) return null;
      if (!parsePack(raw, true)) { input.focus(); return false; }
      return raw;
    };
    handle.clear = function () { input.value = ''; edited = false; update(); };
    return handle;
  }

  /* Run `fn(BizECost)` now, or once this module has loaded (inline page scripts run first). */
  function whenReady(fn) { fn(window.BizECost); }

  window.BizECost = {
    me: me, lotPanel: lotPanel, batchCard: batchCard, dutyLine: dutyLine, packHint: packHint, totalPaidField: totalPaidField,
    packField: packField, parsePack: parsePack, packText: packText,
    money: money, parseMoney: parseMoney, whenReady: whenReady, request: request,
  };
  document.dispatchEvent(new CustomEvent('bizecost:ready'));
})();
