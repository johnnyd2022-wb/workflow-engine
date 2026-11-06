/* Quality hold and release on a lot (GL-P02).

   window.BizeHold.hold(line, opts)     asks why, offers the lots made from this one (those still
                                         in stock ticked), and places the hold.
   window.BizeHold.release(line, opts)  asks what was checked, and releases the open hold.
   window.BizeHold.history(itemId)      resolves to the lot's holds, newest first.

   `line` is an Inventory line: id, name, quantity, unit, quality_hold. opts.onDone() runs after a
   change is recorded. Same dialog look as moving stock (move-stock.css). */
(function () {
  'use strict';

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
  function fmt(n) { return Number(n).toLocaleString(undefined, { maximumFractionDigits: 4 }); }

  async function api(method, path, body) {
    var headers = { Accept: 'application/json' };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      var token = document.querySelector('meta[name="csrf-token"]');
      headers['X-CSRFToken'] = token ? token.content : '';
    }
    var res = await fetch(path, { method: method, credentials: 'same-origin', headers: headers,
      body: body === undefined ? undefined : JSON.stringify(body) });
    var data = {};
    try { data = await res.json(); } catch (_) { /* empty */ }
    if (!res.ok) throw new Error(data.error || 'That could not be saved. Try again.');
    return data;
  }

  function holdsUrl(id) { return '/api/core/inventory/' + encodeURIComponent(id) + '/holds'; }

  function shell(titleText) {
    var dialog = el('dialog', { className: 'mv-dialog qh-dialog', 'aria-labelledby': 'qh-title', 'data-hold-dialog': '' });
    var form = el('form', { className: 'mv-form', 'hx-boost': 'false', novalidate: '' });
    dialog.append(form);
    (document.querySelector('#page-content') || document.body).append(dialog);
    form.append(el('h2', { id: 'qh-title', text: titleText }));
    dialog.addEventListener('close', function () { dialog.remove(); });
    dialog.showModal();
    return { dialog: dialog, form: form };
  }

  function textArea(name, label, hint, placeholder) {
    var input = el('textarea', { name: name, rows: '3', maxlength: '500', required: '', placeholder: placeholder || '' });
    var wrap = el('label', { className: 'mv-field' }, [el('span', { className: 'mv-field__label', text: label }), input]);
    if (hint) wrap.append(el('span', { className: 'mv-hint', text: hint }));
    return { wrap: wrap, input: input };
  }

  function actions(form, submitText, dialog) {
    var error = el('p', { className: 'mv-error', role: 'alert', hidden: '' });
    var submit = el('button', { type: 'submit', className: 'workspace-button workspace-button--primary', 'data-qh-submit': '', text: submitText });
    var cancel = el('button', { type: 'button', className: 'workspace-button', text: 'Cancel' });
    cancel.addEventListener('click', function () { dialog.close(); });
    form.append(error, el('div', { className: 'mv-actions' }, [cancel, submit]));
    return { error: error, submit: submit };
  }

  function hold(line, opts) {
    opts = opts || {};
    var ui = shell('Hold ' + line.name);
    ui.form.append(el('p', { className: 'mv-hint', text: 'While it is held it can’t be used in production, sold, sent to a tasting or dispatched. You can still count it, move it whole or dispose of it.' }));
    var reason = textArea('reason', 'Why is it held?', 'Shown on the lot and in its history.', 'e.g. Cloudy after bottling, waiting on a retest');
    ui.form.append(reason.wrap);
    var related = el('fieldset', { className: 'qh-related', 'data-qh-related': '' }, [el('legend', { text: 'Made from this lot' }), el('p', { className: 'mv-hint', text: 'Checking what was made from it…' })]);
    ui.form.append(related);
    var bits = actions(ui.form, 'Hold lot', ui.dialog);

    api('GET', holdsUrl(line.id)).then(function (data) {
      var made = (data.made_from || []);
      related.replaceChildren(el('legend', { text: 'Made from this lot' }));
      if (!made.length) {
        related.append(el('p', { className: 'mv-hint', text: 'Nothing has been made from it yet.' }));
        return;
      }
      related.append(el('p', { className: 'mv-hint', text: 'Hold these too? Lots still in stock are ticked.' }));
      var list = el('ul', { className: 'qh-related__list' });
      made.forEach(function (lot) {
        var box = el('input', { type: 'checkbox', name: 'also_hold', value: lot.id });
        if (lot.on_hold) { box.checked = true; box.disabled = true; } else if (lot.in_stock) box.checked = true;
        var label = el('label', { className: 'qh-related__item' }, [box, el('span', { text: lot.name }),
          el('span', { className: 'mv-hint', text: lot.on_hold ? 'Already on hold' : (lot.in_stock ? fmt(lot.quantity) + ' ' + (lot.unit || '') + ' in stock' : 'None left') })]);
        list.append(el('li', {}, [label]));
      });
      related.append(list);
    }).catch(function () {
      related.replaceChildren(el('legend', { text: 'Made from this lot' }), el('p', { className: 'mv-hint', text: 'Couldn’t check what was made from it. You can hold those lots on their own.' }));
    });

    ui.form.addEventListener('submit', async function (e) {
      e.preventDefault();
      var text = reason.input.value.trim();
      if (!text) { bits.error.textContent = 'Say why the lot is held.'; bits.error.hidden = false; reason.input.focus(); return; }
      var also = Array.prototype.map.call(ui.form.querySelectorAll('input[name="also_hold"]:checked:not(:disabled)'), function (b) { return b.value; });
      bits.submit.disabled = true;
      bits.error.hidden = true;
      try {
        var done = await api('POST', holdsUrl(line.id), { reason: text, also_hold: also });
        ui.dialog.close();
        if (opts.onDone) opts.onDone(done);
      } catch (err) {
        bits.error.textContent = err.message;
        bits.error.hidden = false;
        bits.submit.disabled = false;
      }
    });
    reason.input.focus();
  }

  function release(line, opts) {
    opts = opts || {};
    var current = line.quality_hold;
    if (!current) return;
    var ui = shell('Release ' + line.name);
    ui.form.append(el('p', { className: 'mv-hint', text: 'Held because: ' + current.reason }));
    var note = textArea('note', 'What was checked?', 'Your name and this note are kept in the lot’s history.', 'e.g. Re-filtered, retested and passed');
    ui.form.append(note.wrap);
    var bits = actions(ui.form, 'Release lot', ui.dialog);
    ui.form.addEventListener('submit', async function (e) {
      e.preventDefault();
      var text = note.input.value.trim();
      if (!text) { bits.error.textContent = 'Say what was checked before releasing it.'; bits.error.hidden = false; note.input.focus(); return; }
      bits.submit.disabled = true;
      bits.error.hidden = true;
      try {
        var done = await api('POST', '/api/core/holds/' + encodeURIComponent(current.id) + '/release', { note: text });
        ui.dialog.close();
        if (opts.onDone) opts.onDone(done);
      } catch (err) {
        bits.error.textContent = err.message;
        bits.error.hidden = false;
        bits.submit.disabled = false;
      }
    });
    note.input.focus();
  }

  function history(itemId) {
    return api('GET', holdsUrl(itemId)).then(function (data) { return data.history || []; });
  }

  window.BizeHold = { hold: hold, release: release, history: history };
})();
