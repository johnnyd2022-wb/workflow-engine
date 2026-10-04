// Food-safety verification lifecycle (plan 2.2): the next verification date, corrective
// actions, and recording a visit. The server applies MPI's frequency rules; this page
// shows its suggestion and records what the verifier actually set.
(function () {
  'use strict';

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  async function api(method, url, body) {
    var root = document.querySelector('[data-verification-root]');
    var selected = root ? root.dataset.registrationId || '' : '';
    if (selected) {
      if (method === 'GET') url += (url.indexOf('?') === -1 ? '?' : '&') + 'registration_id=' + encodeURIComponent(selected);
      else body = Object.assign({}, body || {}, { registration_id: selected });
    }
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
    (children || []).forEach(function (c) { if (c) node.append(typeof c === 'string' ? document.createTextNode(c) : c); });
    return node;
  }

  function fmt(iso) {
    if (!iso) return '';
    return new Date(iso + 'T00:00:00').toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function init(root) {
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    var $ = function (sel) { return root.querySelector(sel); };
    var canManage = root.dataset.canManage === '1';
    var canRecord = root.dataset.canRecord === '1';
    var form = $('[data-verification-form]');
    var state = null;
    var registrationSelect = $('[data-verification-registration-select]');
    var requestedRegistration = new URLSearchParams(window.location.search).get('registration_id') || '';
    root.dataset.registrationId = '';
    registrationSelect.addEventListener('change', function () {
      root.dataset.registrationId = registrationSelect.value;
      form.reset(); $('[data-verification-new-actions]').replaceChildren();
      api('GET', '/api/compliant/verification').then(render).catch(fail);
    });

    function fail(err) {
      console.error(err);
      var box = $('[data-verification-error]');
      box.textContent = err.message || String(err);
      box.hidden = false;
    }
    function clearError() { $('[data-verification-error]').hidden = true; }

    function render(s) {
      if ((s.registration_id || '') !== (root.dataset.registrationId || '')) return;
      state = s;
      registrationSelect.replaceChildren(el('option', { value: '', text: 'Unassigned history / organisation settings' }));
      (s.registrations || []).forEach(function (row) {
        registrationSelect.append(el('option', { value: row.id, text: row.name + ' · ' + row.reference }));
      });
      registrationSelect.value = s.registration_id || '';
      if (requestedRegistration) {
        var wanted = requestedRegistration; requestedRegistration = '';
        if ((s.registrations || []).some(function (row) { return row.id === wanted; })) {
          root.dataset.registrationId = wanted; registrationSelect.value = wanted;
          api('GET', '/api/compliant/verification').then(render).catch(fail); return;
        }
      }
      var head = $('[data-verification-headline]');
      var sub = $('[data-verification-sub]');
      var chip = $('[data-verification-chip]');
      var programme = (s.programme || '').toUpperCase();
      chip.hidden = true;
      if (s.state === 'not_applicable') {
        head.textContent = s.registration_programme === 'fcp' ? 'Food control plan registration' : 'No national programme selected';
        sub.textContent = s.registration_programme === 'fcp' ? 'Use your plan and verifier’s schedule. National programme frequency rules do not apply.' : 'Select your food safety programme in Configuration.';
      } else if (s.state === 'not_recorded') {
        head.textContent = 'When is your ' + programme + ' verification?';
        sub.textContent = 'Record your last verification, or when you registered, and the next date is worked out for you.';
      } else if (s.state === 'no_further') {
        head.textContent = 'No further verification needed';
        sub.textContent = 'Your last verification on ' + fmt(s.last.verified_on) + ' was acceptable, so ' + programme + ' needs no further routine verification.';
      } else {
        var initial = !s.last;
        head.textContent = (initial ? 'Initial verification due ' : 'Next verification due ') + fmt(s.next_due);
        sub.textContent = initial
          ? 'Worked out from your ' + programme + ' registration on ' + fmt(s.registered_on) + '.'
          : 'Last verified ' + fmt(s.last.verified_on) + ' by ' + s.last.verifier_name + ' (' + s.last.outcome + '). Frequency: ' + s.frequency + '.';
        chip.hidden = false;
        chip.className = 'verification-chip' + (s.overdue ? ' verification-chip--bad' : s.days_until <= 60 ? ' verification-chip--warn' : '');
        chip.textContent = s.overdue ? 'Overdue' : s.days_until === 0 ? 'Today' : 'In ' + s.days_until + ' day' + (s.days_until === 1 ? '' : 's');
      }

      var reg = $('[data-verification-registration]');
      reg.hidden = !!s.registration_id || !(canManage && !s.last && s.state !== 'not_applicable');
      if (s.registered_on) reg.registered_on.value = s.registered_on;
      if (s.registered_as) reg.registered_as.value = s.registered_as;

      var list = $('[data-verification-actions]');
      list.replaceChildren();
      s.actions.forEach(function (a) {
        var meta = (a.owner || 'No owner') + ' · due ' + fmt(a.due_on);
        var li = el('li', { className: 'verification-action' + (a.status === 'done' ? ' verification-action--done' : a.overdue ? ' verification-action--overdue' : '') }, [
          el('div', {}, [el('strong', { text: a.description }), el('small', { text: a.status === 'done' ? meta + ' · done ' + fmt(a.done_on) + (a.done_note ? ': ' + a.done_note : '') : meta + (a.overdue ? ' · overdue' : '') })])
        ]);
        if (a.status === 'open' && canRecord) {
          var done = el('button', { type: 'button', className: 'suggestion', text: 'Mark done' });
          done.addEventListener('click', async function () {
            var note = window.prompt('What was done? (optional)', '');
            if (note === null) return;
            done.disabled = true;
            try { clearError(); render(await api('POST', '/api/compliant/verification/actions/' + a.id + '/complete', { note: note })); }
            catch (err) { fail(err); done.disabled = false; }
          });
          li.append(done);
        }
        list.append(li);
      });
      $('[data-verification-actions-wrap]').hidden = !s.actions.length;

      $('[data-verification-record-wrap]').hidden = !canRecord || s.state === 'not_applicable';
      $('[data-verification-history-fields]').hidden = !!s.last;
      var prev = form.previous_step;
      if (!prev.options.length) {
        Object.keys(s.steps).forEach(function (k) { prev.append(el('option', { value: k, text: s.steps[k] })); });
      }
      var body = $('[data-verification-history]');
      body.replaceChildren();
      s.verifications.forEach(function (v) {
        body.append(el('tr', {}, [
          el('td', { text: fmt(v.verified_on) }),
          el('td', { text: v.verifier_name + (v.verifier_agency ? ' (' + v.verifier_agency + ')' : '') }),
          el('td', { text: v.outcome + (v.initial ? ' · initial' : '') }),
          el('td', { text: v.frequency }),
          el('td', { text: v.next_due ? fmt(v.next_due) : '—' })
        ]));
      });
      $('[data-verification-history-wrap]').hidden = !s.verifications.length;
      suggest();
    }

    var suggestTimer = null;
    function suggest() {
      clearTimeout(suggestTimer);
      suggestTimer = setTimeout(async function () {
        if (!state || state.state === 'not_applicable') return;
        var outcome = form.querySelector('input[name="outcome"]:checked').value;
        $('[data-verification-attitude]').hidden = outcome !== 'unacceptable';
        var initial = !state.last && form.initial.checked;
        $('[data-verification-previous]').hidden = !!state.last || initial;
        var q = new URLSearchParams({ outcome: outcome, initial: initial ? 'true' : 'false' });
        if (outcome === 'unacceptable') q.set('attitude', form.attitude.value);
        if (!state.last && !initial) q.set('previous_step', form.previous_step.value);
        if (state.last) q.set('previous_step', String(state.current_step));
        if (form.verified_on.value) q.set('verified_on', form.verified_on.value);
        try {
          var selectedRegistration = root.dataset.registrationId;
          var s = await api('GET', '/api/compliant/verification/suggest?' + q.toString());
          if (selectedRegistration !== root.dataset.registrationId) return;
          var select = $('[data-verification-step]');
          select.replaceChildren();
          s.allowed.forEach(function (o) {
            select.append(el('option', { value: String(o.step), text: o.frequency + (o.step === s.step ? ' (the rules give this)' : '') }));
          });
          select.value = String(s.step);
          $('[data-verification-next]').value = s.next_due || '';
          $('[data-verification-suggestion]').textContent = 'MPI’s rules give ' + s.frequency + ' for this outcome. Change it if your verifier set something else; their report is what counts.';
        } catch (err) { fail(err); }
      }, 150);
    }

    async function stepChanged() {
      if (!form.verified_on.value) return;
      var months = { 1: 3, 2: 6, 3: 9, 4: 12, 5: 18, 6: 24, 7: 36, 8: null }[form.step.value];
      if (!months) { form.next_due.value = ''; return; }
      var d = new Date(form.verified_on.value + 'T00:00:00');
      var day = d.getDate();
      d.setDate(1); d.setMonth(d.getMonth() + months);
      var last = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
      d.setDate(Math.min(day, last));
      form.next_due.value = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }

    function addAction() {
      var owner = el('select', { name: 'owner', 'aria-label': 'Owner' }, [el('option', { value: '', text: 'Owner…' })].concat(
        (state ? state.staff : []).map(function (p) { return el('option', { value: p.id, text: p.name }); })));
      var row = el('div', { className: 'verification-new-action' }, [
        el('label', {}, ['What needs doing', el('input', { name: 'description', maxlength: '500' })]),
        el('label', {}, ['Owner', owner]),
        el('label', {}, ['Due', el('input', { type: 'date', name: 'due_on' })]),
        el('button', { type: 'button', className: 'verification-remove', 'aria-label': 'Remove this action', text: '×' })
      ]);
      row.querySelector('.verification-remove').addEventListener('click', function () { row.remove(); });
      $('[data-verification-new-actions]').append(row);
    }

    ['change', 'input'].forEach(function (ev) {
      form.addEventListener(ev, function (e) {
        if (e.target.name === 'step') stepChanged();
        else if (['outcome', 'attitude', 'initial', 'previous_step', 'verified_on'].indexOf(e.target.name) !== -1) suggest();
      });
    });
    $('[data-verification-add-action]').addEventListener('click', addAction);

    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      clearError();
      var button = form.querySelector('button[type="submit"]');
      var actions = Array.prototype.map.call(root.querySelectorAll('.verification-new-action'), function (row) {
        return { description: row.querySelector('[name="description"]').value, owner_user_id: row.querySelector('[name="owner"]').value || null,
          due_on: row.querySelector('[name="due_on"]').value };
      }).filter(function (a) { return a.description || a.due_on; });
      var outcome = form.querySelector('input[name="outcome"]:checked').value;
      var body = {
        verified_on: form.verified_on.value, verifier_name: form.verifier_name.value, verifier_agency: form.verifier_agency.value,
        report_reference: form.report_reference.value, outcome: outcome, attitude: outcome === 'unacceptable' ? form.attitude.value : null,
        step: form.step.value, next_due: form.next_due.value || null, notes: form.notes.value, actions: actions
      };
      if (state && !state.last) {
        body.initial = form.initial.checked;
        if (!form.initial.checked) body.previous_step = form.previous_step.value;
      }
      button.disabled = true;
      try {
        render(await api('POST', '/api/compliant/verification', body));
        form.reset();
        $('[data-verification-new-actions]').replaceChildren();
        $('[data-verification-record-wrap]').open = false;
      } catch (err) { fail(err); }
      button.disabled = false;
    });

    $('[data-verification-registration]').addEventListener('submit', async function (e) {
      e.preventDefault();
      clearError();
      var f = e.target;
      try { render(await api('PUT', '/api/compliant/verification/registration', { registered_on: f.registered_on.value, registered_as: f.registered_as.value })); }
      catch (err) { fail(err); }
    });

    api('GET', '/api/compliant/verification').then(render).catch(fail);
  }

  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  bize.onPage('[data-verification-root]', init);
})();
