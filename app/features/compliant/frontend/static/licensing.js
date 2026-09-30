// Liquor licensing register (plan 2.5). The server validates and works out every date
// (renew-by, fee, certificate expiry); this page collects entries and shows the state.
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
    (children || []).forEach(function (c) { if (c) node.append(typeof c === 'string' ? document.createTextNode(c) : c); });
    return node;
  }

  function fmt(iso) {
    if (!iso) return '';
    return new Date(iso.slice(0, 10) + 'T00:00:00').toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function chip(code, label) { return el('span', { className: 'licensing-state licensing-state--' + code, text: label }); }

  function formData(form) {
    var out = {};
    new FormData(form).forEach(function (value, key) { out[key] = value; });
    return out;
  }

  function init(root) {
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    var $ = function (sel) { return root.querySelector(sel); };
    var canManage = root.dataset.canManage === '1';
    var canRecord = root.dataset.canRecord === '1';
    var state = null;

    function fail(err) {
      console.error(err);
      var box = $('[data-licensing-error]');
      box.textContent = err.message || String(err);
      box.hidden = false;
      box.scrollIntoView({ block: 'nearest' });
    }
    function ok() { $('[data-licensing-error]').hidden = true; }

    async function act(method, url, body) {
      try { ok(); render(await api(method, url, body)); return true; } catch (err) { fail(err); return false; }
    }

    function askDate(message, fallback) {
      var value = window.prompt(message + ' (YYYY-MM-DD)', fallback || new Date().toISOString().slice(0, 10));
      return value === null ? null : value.trim();
    }

    function renderLicences(s) {
      var host = $('[data-licensing-licences]');
      host.replaceChildren();
      if (!s.licences.length) host.append(el('p', { text: 'No licences yet. Add yours, including special licences for events.' }));
      s.licences.forEach(function (lic) {
        var rows = [];
        function row(label, value) { if (value) rows.push(el('dt', { text: label }), el('dd', { text: value })); }
        if (lic.kind === 'special') {
          row('Event', lic.event_name);
          row('Dates', fmt(lic.event_starts_on) + (lic.event_ends_on && lic.event_ends_on !== lic.event_starts_on ? ' to ' + fmt(lic.event_ends_on) : ''));
          row('Manager on duty', lic.manager_on_duty || 'Not named yet');
        } else {
          row('Premises', lic.premises);
          row('Expires', fmt(lic.expires_on));
          row('File renewal by', lic.renewal_lodged_on ? '' : fmt(lic.renewal_file_by));
          row('Annual fee due', fmt(lic.annual_fee_due_on) + (lic.annual_fee_overdue ? ' (overdue)' : ''));
        }
        row('Site', lic.site_name || 'Not assigned');
        row('DLC', lic.issuing_dlc);
        row('Endorsements', lic.endorsement_labels.join(', '));
        row('Sale hours', lic.sale_hours);
        row('Delivery hours', lic.delivery_hours_start ? lic.delivery_hours_start + ' to ' + lic.delivery_hours_end : '');
        row('Conditions', lic.conditions);
        var actions = el('div', { className: 'licensing-actions' });
        if (canManage && lic.status === 'current') {
          var sitePicker = el('select', { 'aria-label': 'Site for ' + (lic.licence_number || lic.kind_label) });
          sitePicker.append(el('option', { value: '', text: 'Choose site' }));
          (s.sites || []).forEach(function (site) { sitePicker.append(el('option', { value: site.id, text: site.name })); });
          sitePicker.value = lic.site_id || '';
          actions.append(sitePicker, button('Assign site', function () {
            if (sitePicker.value) act('PUT', '/api/compliant/licensing/licences/' + lic.id, { site_id: sitePicker.value });
          }));
          if (lic.kind !== 'special' && !lic.renewal_lodged_on) {
            actions.append(button('Renewal lodged', function () {
              var d = askDate('When did you file the renewal?'); if (d) act('POST', '/api/compliant/licensing/licences/' + lic.id + '/renewal-lodged', { lodged_on: d });
            }));
          }
          if (lic.renewal_lodged_on) {
            actions.append(button('Renewal granted', function () {
              var d = askDate('New expiry date on the renewed licence', ''); if (d) act('POST', '/api/compliant/licensing/licences/' + lic.id + '/renewed', { expires_on: d });
            }));
          }
          if (lic.annual_fee_due_on) {
            actions.append(button('Annual fee paid', function () { act('POST', '/api/compliant/licensing/licences/' + lic.id + '/fee-paid'); }));
          }
          if (lic.kind === 'special' && !lic.manager_on_duty) {
            actions.append(button('Name the manager', function () {
              var name = window.prompt('Manager on duty for ' + lic.event_name, ''); if (name) act('PUT', '/api/compliant/licensing/licences/' + lic.id, { manager_on_duty: name });
            }));
          }
          actions.append(button('No longer held', function () {
            if (window.confirm('Mark this licence as no longer held? It stays in the records.')) act('POST', '/api/compliant/licensing/licences/' + lic.id + '/end');
          }));
        }
        host.append(el('article', { className: 'licensing-card' }, [
          el('h3', { text: lic.kind_label + (lic.licence_number ? ' · ' + lic.licence_number : '') }),
          chip(lic.state_code, lic.state_label),
          el('dl', {}, rows),
          actions.childNodes.length ? actions : null
        ]));
      });
    }

    function button(label, onClick) {
      var b = el('button', { type: 'button', className: 'suggestion', text: label });
      b.addEventListener('click', onClick);
      return b;
    }

    function renderManagers(s) {
      var body = $('[data-licensing-managers]');
      body.replaceChildren();
      if (!s.managers.length) body.append(el('tr', {}, [el('td', { colspan: '6', text: 'No managers’ certificates yet.' })]));
      s.managers.forEach(function (m) {
        var cell = el('td');
        if (canManage && m.active) {
          if (!m.renewal_lodged_on) cell.append(button('Renewal lodged', function () {
            var d = askDate('When did ' + m.holder_name + ' file the renewal?'); if (d) act('POST', '/api/compliant/licensing/managers/' + m.id + '/renewal-lodged', { lodged_on: d });
          }));
          else cell.append(button('Renewed', function () {
            var d = askDate('New expiry date', ''); if (d) act('POST', '/api/compliant/licensing/managers/' + m.id + '/renewed', { expires_on: d });
          }));
          cell.append(button('Left', function () {
            if (window.confirm(m.holder_name + ' no longer works here?')) act('POST', '/api/compliant/licensing/managers/' + m.id + '/end');
          }));
        }
        body.append(el('tr', {}, [el('td', { text: m.holder_name }), el('td', { text: m.certificate_number }), el('td', { text: m.issuing_dlc || '' }),
          el('td', { text: fmt(m.expires_on) }), el('td', {}, [chip(m.state_code, m.state_label)]), cell]));
      });
      var select = $('[data-manager-user]');
      if (select.options.length === 1) s.staff.forEach(function (p) { select.append(el('option', { value: p.id, text: p.name })); });
    }

    function renderChecks(s) {
      var list = $('[data-licensing-checks]');
      list.replaceChildren();
      var labels = { current: 'Current', due: 'Review soon', overdue: 'Overdue', missing: 'No record', attention: 'Needs attention', setup: 'Set up', compliant: 'From the register' };
      s.checks.forEach(function (c) {
        var info = c.latest ? c.latest.title + ' · ' + fmt(c.latest.recorded_on) + (c.latest.review_due ? ' · review by ' + fmt(c.latest.review_due) : '') : c.reason;
        var li = el('li', { className: 'licensing-check' }, [
          el('div', {}, [el('strong', { text: c.description }), el('small', { text: c.from_register ? c.reason : info })]),
          chip(c.state === 'compliant' ? 'ok' : c.state, labels[c.state] || c.state)
        ]);
        if (!c.from_register && canRecord) {
          li.append(button(c.latest ? 'Record again' : 'Record', function () { openCheck(c); }));
        }
        list.append(li);
      });
    }

    function openCheck(c) {
      var form = $('[data-check-form]');
      form.hidden = false;
      form.control_id.value = c.control_id;
      $('[data-check-form-title]').textContent = c.description;
      var review = new Date(); review.setFullYear(review.getFullYear() + 1);
      form.due_date.value = review.toISOString().slice(0, 10);
      form.title.focus();
    }

    function renderLog(s) {
      var body = $('[data-licensing-log]');
      body.replaceChildren();
      if (!s.log.length) body.append(el('tr', {}, [el('td', { colspan: '5', text: 'Nothing logged yet.' })]));
      s.log.forEach(function (e) {
        body.append(el('tr', {}, [el('td', { text: new Date(e.occurred_at).toLocaleString('en-NZ', { dateStyle: 'medium', timeStyle: 'short' }) }),
          el('td', { text: e.kind_label }), el('td', { text: e.description + (e.location ? ' (' + e.location + ')' : '') }),
          el('td', { text: e.action_taken || '' }), el('td', { text: e.staff_name || '' })]));
      });
    }

    function render(s) {
      state = s;
      var site = $('[data-licence-site]');
      var previous = site.value;
      site.replaceChildren(el('option', { value: '', text: s.multiple_sites_enabled ? 'Choose site' : 'Not assigned' }));
      (s.sites || []).forEach(function (row) { site.append(el('option', { value: row.id, text: row.name })); });
      site.value = previous;
      site.required = !!s.multiple_sites_enabled;
      var kind = $('[data-licence-kind]');
      if (!kind.options.length) {
        s.kinds.forEach(function (k) { kind.append(el('option', { value: k.value, text: k.label })); });
        kind.value = 'off';
        var ends = $('[data-licence-endorsements]');
        s.endorsements.forEach(function (k) {
          ends.append(el('label', {}, [el('input', { type: 'checkbox', name: 'endorsements', value: k.value }), k.label]));
        });
        var logKind = $('[data-log-kind]');
        s.log_kinds.forEach(function (k) { logKind.append(el('option', { value: k.value, text: k.label })); });
        syncKind();
      }
      root.querySelectorAll('[data-licensing-manage]').forEach(function (n) { n.hidden = !canManage; });
      $('[data-log-form]').hidden = !canRecord;
      renderLicences(s);
      renderManagers(s);
      renderChecks(s);
      renderLog(s);
    }

    function syncKind() {
      var special = $('[data-licence-kind]').value === 'special';
      root.querySelectorAll('[data-special]').forEach(function (n) { n.hidden = !special; });
      root.querySelectorAll('[data-standing]').forEach(function (n) { n.hidden = special; });
    }
    $('[data-licence-kind]').addEventListener('change', syncKind);
    $('[data-manager-user]').addEventListener('change', function (e) { $('[data-manager-name]').hidden = !!e.target.value; });

    $('[data-licence-form]').addEventListener('submit', async function (e) {
      e.preventDefault();
      var form = e.target;
      var body = formData(form);
      body.endorsements = Array.prototype.map.call(form.querySelectorAll('[name="endorsements"]:checked'), function (i) { return i.value; });
      Object.keys(body).forEach(function (k) { if (body[k] === '') delete body[k]; });
      if (await act('POST', '/api/compliant/licensing/licences', body)) { form.reset(); syncKind(); form.closest('details').open = false; }
    });
    $('[data-manager-form]').addEventListener('submit', async function (e) {
      e.preventDefault();
      var body = formData(e.target);
      if (!body.user_id) delete body.user_id;
      if (await act('POST', '/api/compliant/licensing/managers', body)) { e.target.reset(); e.target.closest('details').open = false; }
    });
    $('[data-check-form]').addEventListener('submit', async function (e) {
      e.preventDefault();
      var body = formData(e.target);
      body.framework_slug = 'liquor-licence';
      body.record_type = 'attestation';
      try {
        ok();
        await api('POST', '/api/compliant/records', body);
        e.target.reset();
        e.target.hidden = true;
        render(await api('GET', '/api/compliant/licensing'));
      } catch (err) { fail(err); }
    });
    $('[data-check-cancel]').addEventListener('click', function () { $('[data-check-form]').hidden = true; });
    $('[data-log-form]').addEventListener('submit', async function (e) {
      e.preventDefault();
      var body = formData(e.target);
      if (body.occurred_at) body.occurred_at = new Date(body.occurred_at).toISOString();
      else delete body.occurred_at;
      if (await act('POST', '/api/compliant/licensing/log', body)) e.target.reset();
    });

    api('GET', '/api/compliant/licensing').then(render).catch(fail);
  }

  function boot() { init(document.querySelector('[data-licensing-root]')); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
  document.addEventListener('htmx:afterSwap', boot);
})();
