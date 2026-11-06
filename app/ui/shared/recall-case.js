/* Recall cases (GL-P03).

   window.BizeRecall.render(container, caseId, canWork)  the customer checklist on a recall case
   window.BizeRecall.start(line, opts)                    "Start a recall…" from a lot's panel

   Biz-E never sends a recall notice: it drafts one per customer to copy, and a person records
   that it went out, who acknowledged it, and how much came back or was disposed of. The case can
   only be resolved once every customer is accounted for (the server enforces it; the blockers
   list here says what's left). Same dialog look as moving stock (move-stock.css). */
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
  function fmtDate(iso) { return iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : ''; }

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
    if (!res.ok) throw new Error(data.error || data.message || 'That could not be saved. Try again.');
    return data;
  }

  var RISK = { health: 'Risk to health', quality: 'Quality problem', regulatory: 'Regulatory' };

  // --- the checklist on the case page -------------------------------------------------------------

  function contactStatus(c) {
    if (c.unreachable_note) return ['Unreachable', 'rc-chip--muted'];
    if (c.done) return ['Accounted for', 'rc-chip--ok'];
    if (c.acknowledged_at) return ['Acknowledged', 'rc-chip--progress'];
    if (c.notice_sent_at) return ['Notice sent', 'rc-chip--progress'];
    return ['Not contacted', 'rc-chip--todo'];
  }

  function render(container, caseId, canWork) {
    var recallId = null;
    container.hidden = false;
    container.replaceChildren(el('p', { className: 'oc-status', text: 'Loading the recall…' }));

    function reload() {
      return api('GET', '/api/core/recalls/by-case/' + encodeURIComponent(caseId)).then(function (data) {
        draw(data.recall);
      }).catch(function (err) {
        container.replaceChildren(el('p', { className: 'oc-status oc-status--error', role: 'alert', text: err.message }));
      });
    }

    function draw(r) {
      recallId = r.id;
      container.replaceChildren();
      var head = el('div', { className: 'rc-head' });
      if (r.is_drill) head.append(el('span', { className: 'rc-chip rc-chip--drill', text: 'Drill: nothing is held, nothing real is sent' }));
      head.append(el('h2', { text: r.is_drill ? 'Recall drill' : 'Recall' }));
      head.append(el('p', { className: 'rc-reason', text: (RISK[r.risk] || r.risk) + ': ' + r.reason }));
      var facts = [
        r.lots_in_scope.length + ' lot' + (r.lots_in_scope.length === 1 ? '' : 's') + ' in scope',
        r.is_drill ? 'no stock held' : r.holds_placed + ' on quality hold',
        r.progress.customers + ' customer' + (r.progress.customers === 1 ? '' : 's'),
      ];
      head.append(el('p', { className: 'rc-facts', text: facts.join(' · ') }));
      container.append(head);

      var p = r.progress;
      var pct = Number(p.supplied) > 0 ? Math.round((Number(p.accounted) / Number(p.supplied)) * 100) : 100;
      var meter = el('div', { className: 'rc-progress' }, [
        el('div', { className: 'rc-progress__row' }, [
          el('strong', { text: p.complete ? 'Ready to resolve' : 'Not finished' }),
          el('span', { text: (p.acknowledged + p.unreachable) + ' of ' + p.customers + ' customers answered · ' + p.accounted + ' of ' + p.supplied + ' accounted for' }),
        ]),
        el('div', { className: 'rc-progress__bar', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(pct), 'aria-label': 'Units accounted for' }, [
          (function () { var fill = el('span'); fill.style.width = pct + '%'; return fill; })(),
        ]),
      ]);
      container.append(meter);
      if (p.blockers.length) {
        var list = el('ul', { className: 'rc-blockers', 'aria-label': 'Still to do before it can be resolved' });
        p.blockers.forEach(function (b) { list.append(el('li', { text: b })); });
        container.append(list);
      }

      if (!r.contacts.length) {
        container.append(el('p', { className: 'rc-empty', text: 'None of this stock was sold yet, so there is nobody to contact. Check what is held, then resolve the case.' }));
        return;
      }
      var cards = el('div', { className: 'rc-contacts' });
      r.contacts.forEach(function (c) { cards.append(card(c)); });
      container.append(cards);
    }

    function card(c) {
      var st = contactStatus(c);
      var art = el('article', { className: 'rc-contact', 'data-rc-contact': c.id }, [
        el('div', { className: 'rc-contact__top' }, [
          el('div', {}, [
            el('h3', { text: c.customer_name }),
            el('p', { className: 'rc-contact__what', text: c.quantity_supplied + ' ' + c.unit + ' of ' + c.product_name + (c.invoices.length ? ' · ' + c.invoices.join(', ') : '') }),
          ]),
          el('span', { className: 'rc-chip ' + st[1], text: st[0] }),
        ]),
      ]);
      var trail = [];
      if (c.notice_sent_at) trail.push('Notice sent ' + fmtDate(c.notice_sent_at) + ' by ' + c.notice_channel);
      if (c.acknowledged_at) trail.push('Acknowledged ' + fmtDate(c.acknowledged_at) + ' by ' + c.acknowledged_by + (c.ack_note ? ' (' + c.ack_note + ')' : ''));
      if (c.unreachable_note) trail.push('Unreachable: ' + c.unreachable_note);
      if (Number(c.recovered_qty) || Number(c.disposed_qty)) trail.push(c.recovered_qty + ' recovered · ' + c.disposed_qty + ' disposed of by them');
      if (trail.length) {
        var ul = el('ul', { className: 'rc-contact__trail' });
        trail.forEach(function (t) { ul.append(el('li', { text: t })); });
        art.append(ul);
      }
      var actions = el('div', { className: 'rc-contact__actions' });
      var notice = el('button', { type: 'button', className: 'workspace-button', text: 'Notice to send' });
      notice.addEventListener('click', function () { showNotice(c); });
      actions.append(notice);
      if (canWork) {
        if (!c.notice_sent_at && !c.unreachable_note) actions.append(button('Mark notice sent', function () { noticeSentForm(c); }));
        if (!c.acknowledged_at && !c.unreachable_note) {
          actions.append(button('Acknowledged…', function () { ackForm(c); }));
          actions.append(button('Can’t reach them…', function () { unreachableForm(c); }));
        }
        if (!c.unreachable_note) actions.append(button('Recovered / disposed…', function () { qtyForm(c); }));
      }
      art.append(actions);
      return art;
    }

    function button(label, fn) {
      var b = el('button', { type: 'button', className: 'workspace-button', text: label });
      b.addEventListener('click', fn);
      return b;
    }

    // One dialog shape for every customer action.
    function dialog(title, fields, submitText, send) {
      var d = el('dialog', { className: 'mv-dialog rc-dialog', 'aria-labelledby': 'rc-title', 'data-rc-dialog': '' });
      var form = el('form', { className: 'mv-form', 'hx-boost': 'false', novalidate: '' });
      d.append(form);
      (document.querySelector('#page-content') || document.body).append(d);
      form.append(el('h2', { id: 'rc-title', text: title }));
      var inputs = {};
      fields.forEach(function (f) {
        var input = f.type === 'textarea' ? el('textarea', { name: f.name, rows: '3', maxlength: '2000' })
          : el('input', { name: f.name, type: f.type || 'text', maxlength: '255' });
        if (f.value != null) input.value = f.value;
        if (f.attrs) Object.keys(f.attrs).forEach(function (k) { input.setAttribute(k, f.attrs[k]); });
        inputs[f.name] = input;
        var label = el('label', { className: 'mv-field' }, [el('span', { className: 'mv-field__label', text: f.label }), input]);
        if (f.hint) label.append(el('span', { className: 'mv-hint', text: f.hint }));
        form.append(label);
      });
      var error = el('p', { className: 'mv-error', role: 'alert', hidden: '' });
      var cancel = el('button', { type: 'button', className: 'workspace-button', text: 'Cancel' });
      var submit = el('button', { type: 'submit', className: 'workspace-button workspace-button--primary', text: submitText });
      cancel.addEventListener('click', function () { d.close(); });
      form.append(error, el('div', { className: 'mv-actions' }, [cancel, submit]));
      d.addEventListener('close', function () { d.remove(); });
      form.addEventListener('submit', async function (e) {
        e.preventDefault();
        submit.disabled = true; error.hidden = true;
        try { await send(inputs); d.close(); await reload(); }
        catch (err) { error.textContent = err.message; error.hidden = false; submit.disabled = false; }
      });
      d.showModal();
      var first = fields[0] && inputs[fields[0].name];
      if (first) first.focus();
    }

    function path(c, action) { return '/api/core/recalls/' + recallId + '/contacts/' + c.id + '/' + action; }
    function today() { return new Date().toISOString(); }

    function noticeSentForm(c) {
      dialog('Notice sent to ' + c.customer_name, [
        { name: 'channel', label: 'How it was sent', hint: 'Email, phone call, visit…', value: 'email' },
      ], 'Record it', function (i) { return api('POST', path(c, 'notice-sent'), { channel: i.channel.value, sent_at: today() }); });
    }
    function ackForm(c) {
      dialog(c.customer_name + ' acknowledged', [
        { name: 'by', label: 'Who acknowledged it', hint: 'Name or role at ' + c.customer_name },
        { name: 'note', label: 'Note (optional)', type: 'textarea', hint: 'e.g. how many they still hold, pulled from the shelf' },
      ], 'Record acknowledgement', function (i) { return api('POST', path(c, 'acknowledged'), { by: i.by.value, note: i.note.value, at: today() }); });
    }
    function unreachableForm(c) {
      dialog('Can’t reach ' + c.customer_name, [
        { name: 'note', label: 'What was tried', type: 'textarea', hint: 'Calls, emails and visits, with dates. Kept on the recall.' },
      ], 'Record as unreachable', function (i) { return api('POST', path(c, 'unreachable'), { note: i.note.value }); });
    }
    function qtyForm(c) {
      dialog('What happened to the ' + c.quantity_supplied + ' ' + c.unit, [
        { name: 'recovered', label: 'Came back to you', type: 'number', value: c.recovered_qty, attrs: { min: '0', step: 'any', inputmode: 'decimal' },
          hint: 'Record the goods themselves under Sales: Record a return (damaged puts them on hold).' },
        { name: 'disposed', label: 'Disposed of by them', type: 'number', value: c.disposed_qty, attrs: { min: '0', step: 'any', inputmode: 'decimal' } },
      ], 'Save', function (i) { return api('POST', path(c, 'quantities'), { recovered: i.recovered.value || 0, disposed: i.disposed.value || 0 }); });
    }

    async function showNotice(c) {
      var data = await api('GET', path(c, 'notice'));
      var d = el('dialog', { className: 'mv-dialog rc-dialog rc-notice', 'aria-labelledby': 'rc-notice-title' });
      var subject = el('input', { type: 'text', readonly: '', value: data.notice.subject, 'aria-label': 'Subject' });
      var body = el('textarea', { rows: '12', readonly: '', 'aria-label': 'Message' });
      body.value = data.notice.body;
      var copy = el('button', { type: 'button', className: 'workspace-button workspace-button--primary', text: 'Copy message' });
      var close = el('button', { type: 'button', className: 'workspace-button', text: 'Close' });
      var done = el('p', { className: 'mv-hint', role: 'status' });
      copy.addEventListener('click', function () {
        var text = data.notice.subject + '\n\n' + data.notice.body;
        (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(function () {
          done.textContent = 'Copied. Send it from your own email, then mark the notice sent.';
        }).catch(function () { body.select(); done.textContent = 'Select and copy the message above.'; });
      });
      close.addEventListener('click', function () { d.close(); });
      d.append(el('div', { className: 'mv-form' }, [
        el('h2', { id: 'rc-notice-title', text: 'Notice for ' + c.customer_name }),
        el('p', { className: 'mv-hint', text: 'Biz-E doesn’t send this. Check it, send it yourself, then record that you did.' }),
        el('label', { className: 'mv-field' }, [el('span', { className: 'mv-field__label', text: 'Subject' }), subject]),
        el('label', { className: 'mv-field' }, [el('span', { className: 'mv-field__label', text: 'Message' }), body]),
        done,
        el('div', { className: 'mv-actions' }, [close, copy]),
      ]));
      d.addEventListener('close', function () { d.remove(); });
      (document.querySelector('#page-content') || document.body).append(d);
      d.showModal();
    }

    return reload();
  }

  // --- starting one from a lot -------------------------------------------------------------------

  function start(line) {
    var d = el('dialog', { className: 'mv-dialog rc-dialog', 'aria-labelledby': 'rc-start-title', 'data-rc-start': '' });
    var form = el('form', { className: 'mv-form', 'hx-boost': 'false', novalidate: '' });
    d.append(form);
    (document.querySelector('#page-content') || document.body).append(d);
    var due = new Date(Date.now() + 3 * 864e5).toLocaleDateString('en-CA');
    var reason = el('textarea', { name: 'reason', rows: '3', maxlength: '2000' });
    var risk = el('select', { name: 'risk' }, [
      el('option', { value: 'health', text: 'Risk to health' }),
      el('option', { value: 'quality', text: 'Quality problem' }),
      el('option', { value: 'regulatory', text: 'Regulatory requirement' }),
    ]);
    var dueInput = el('input', { name: 'due', type: 'date', value: due });
    var drill = el('input', { name: 'drill', type: 'checkbox' });
    var error = el('p', { className: 'mv-error', role: 'alert', hidden: '' });
    var cancel = el('button', { type: 'button', className: 'workspace-button', text: 'Cancel' });
    var submit = el('button', { type: 'submit', className: 'workspace-button workspace-button--primary', text: 'Start recall' });
    drill.addEventListener('change', function () { submit.textContent = drill.checked ? 'Start drill' : 'Start recall'; });
    form.append(
      el('h2', { id: 'rc-start-title', text: 'Recall ' + line.name }),
      el('p', { className: 'mv-hint', text: 'Biz-E finds every customer who got this lot or anything made from it, and holds what’s still in stock. It drafts each customer’s notice; it never sends anything.' }),
      el('label', { className: 'mv-field' }, [el('span', { className: 'mv-field__label', text: 'Why' }), reason]),
      el('label', { className: 'mv-field' }, [el('span', { className: 'mv-field__label', text: 'How serious' }), risk]),
      el('label', { className: 'mv-field' }, [el('span', { className: 'mv-field__label', text: 'Finish by' }), dueInput]),
      el('label', { className: 'rc-drill' }, [drill, el('span', { text: 'This is a drill: hold nothing, label every notice as a drill' })]),
      error,
      el('div', { className: 'mv-actions' }, [cancel, submit])
    );
    cancel.addEventListener('click', function () { d.close(); });
    d.addEventListener('close', function () { d.remove(); });
    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      if (!reason.value.trim()) { error.textContent = 'Say why the lot is recalled.'; error.hidden = false; reason.focus(); return; }
      submit.disabled = true; error.hidden = true;
      try {
        var data = await api('POST', '/api/core/recalls', {
          lot_id: line.id, reason: reason.value, risk: risk.value, is_drill: drill.checked,
          due_at: new Date(dueInput.value + 'T17:00:00').toISOString(),
        });
        window.location.assign('/core/cases/' + encodeURIComponent(data.recall.case.id));
      } catch (err) {
        error.textContent = err.message; error.hidden = false; submit.disabled = false;
      }
    });
    d.showModal();
    reason.focus();
  }

  window.BizeRecall = { render: render, start: start };
})();
