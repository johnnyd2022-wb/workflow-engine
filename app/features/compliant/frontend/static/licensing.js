// Liquor licensing register (plan 2.5). The server validates and works out every date
// (renew-by, fee, certificate expiry); this page collects entries and shows the state.
(function () {
  'use strict';

  // Plain names for the licensing checks; the catalogue's wording is what an inspector asks.
  var CHECK_NAMES = {
    'licence-scope': 'Licence details recorded',
    'licence-conditions': 'Licence conditions kept',
    'certified-manager': 'Certified managers in place',
    'licence-renewal': 'Renewal dates tracked',
    'service-practices': 'Age and intoxication training and incidents',
    'licence-displayed': 'Licence and manager on duty displayed',
    'responsibility-policy': 'Host responsibility policy current',
    'remote-seller-website': 'Website shows the licence and age checks'
  };
  var CHECK_LABELS = { current: 'Current', due: 'Review soon', overdue: 'Overdue', missing: 'No record', attention: 'Needs attention', setup: 'Set up', compliant: 'From the register' };
  var TONES = {
    ok: 'good', current: 'good', compliant: 'good', in_use: 'good',
    due: 'warn', attention: 'warn', setup: 'warn', missing: 'warn',
    late: 'bad', expired: 'bad', overdue: 'bad',
    ended: 'muted'
  };
  var LOG_LIMIT = 5;

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

  function day(iso) { return new Date(iso.slice(0, 10) + 'T00:00:00'); }

  function fmt(iso) {
    if (!iso) return '';
    return day(iso).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function daysFrom(iso) {
    var today = new Date(); today.setHours(0, 0, 0, 0);
    return Math.round((day(iso) - today) / 86400000);
  }

  // "in 20 days", "today", "3 days ago": the words beside every date that matters.
  function when(iso) {
    if (!iso) return '';
    var n = daysFrom(iso);
    if (n === 0) return 'today';
    if (n === 1) return 'tomorrow';
    if (n === -1) return 'yesterday';
    return n > 0 ? 'in ' + n + ' days' : Math.abs(n) + ' days ago';
  }

  function todayIso() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function chip(code, label) {
    return el('span', { className: 'lic-status lic-status--' + (TONES[code] || 'muted'), text: label });
  }

  function formData(form) {
    var out = {};
    new FormData(form).forEach(function (value, key) { out[key] = value; });
    return out;
  }

  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }

  function init(root) {
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    var $ = function (sel) { return root.querySelector(sel); };
    var canManage = root.dataset.canManage === '1';
    var canRecord = root.dataset.canRecord === '1';
    var state = null;
    var showAllLog = false;

    function fail(err) {
      console.error(err);
      var box = $('[data-licensing-error]');
      box.textContent = err.message || String(err);
      box.hidden = false;
      root.setAttribute('aria-busy', 'false');
      box.scrollIntoView({ block: 'nearest' });
    }
    function ok() { $('[data-licensing-error]').hidden = true; }

    async function act(method, url, body) {
      try { ok(); render(await api(method, url, body)); return true; } catch (err) { fail(err); return false; }
    }

    // Dialogs: one per form, plus a small one that asks for a single date or name.
    function dialog(name) { return $('[data-lic-dialog="' + name + '"]'); }
    function openDialog(name) {
      var d = dialog(name);
      if (typeof d.showModal === 'function') d.showModal(); else d.setAttribute('open', '');
      var first = d.querySelector('input:not([type="hidden"]), select, textarea');
      if (first) first.focus();
    }
    function closeDialog(d) { if (typeof d.close === 'function') d.close(); else d.removeAttribute('open'); }
    root.querySelectorAll('[data-dialog-close]').forEach(function (b) {
      b.addEventListener('click', function () { closeDialog(b.closest('dialog')); });
    });
    root.querySelectorAll('[data-open-dialog]').forEach(function (b) {
      b.addEventListener('click', function () { openDialog(b.dataset.openDialog); });
    });
    root.querySelectorAll('[data-log-open]').forEach(function (b) {
      b.addEventListener('click', function () { openDialog('log'); });
    });

    var askResolve = null;
    function ask(title, label, type, value) {
      $('[data-ask-title]').textContent = title;
      $('[data-ask-label]').textContent = label;
      var input = $('[data-ask-input]');
      input.type = type;
      input.value = value || '';
      openDialog('ask');
      return new Promise(function (resolve) { askResolve = resolve; });
    }
    dialog('ask').addEventListener('close', function () { if (askResolve) { askResolve(null); askResolve = null; } });
    $('[data-ask-form]').addEventListener('submit', function (e) {
      e.preventDefault();
      var value = $('[data-ask-input]').value.trim();
      var resolve = askResolve;
      askResolve = null;
      closeDialog(dialog('ask'));
      if (resolve) resolve(value || null);
    });

    function button(label, onClick, extra) {
      var b = el('button', { type: 'button', className: 'lic-action' + (extra ? ' ' + extra : ''), text: label });
      b.addEventListener('click', onClick);
      return b;
    }

    function lodgeLicence(lic) {
      return async function () {
        var d = await ask('Renewal lodged', 'When did you file the renewal?', 'date', todayIso());
        if (d) act('POST', '/api/compliant/licensing/licences/' + lic.id + '/renewal-lodged', { lodged_on: d });
      };
    }
    function nameManager(lic) {
      return async function () {
        var name = await ask('Manager on duty', 'Who is the manager on duty for ' + lic.event_name + '?', 'text', '');
        if (name) act('PUT', '/api/compliant/licensing/licences/' + lic.id, { manager_on_duty: name });
      };
    }
    function lodgeManager(m) {
      return async function () {
        var d = await ask('Renewal lodged', 'When did ' + m.holder_name + ' file the renewal?', 'date', todayIso());
        if (d) act('POST', '/api/compliant/licensing/managers/' + m.id + '/renewal-lodged', { lodged_on: d });
      };
    }

    function licenceActions(lic) {
      if (!canManage || lic.status !== 'current') return null;
      var actions = el('div', { className: 'licensing-actions' });
      var base = '/api/compliant/licensing/licences/' + lic.id;
      if (lic.kind !== 'special' && !lic.renewal_lodged_on) {
        actions.append(button('Renewal lodged', lodgeLicence(lic), 'lic-action--main'));
      }
      if (lic.renewal_lodged_on) {
        actions.append(button('Renewal granted', async function () {
          var d = await ask('Renewal granted', 'New expiry date on the renewed licence', 'date', '');
          if (d) act('POST', base + '/renewed', { expires_on: d });
        }, 'lic-action--main'));
      }
      if (lic.annual_fee_due_on) {
        actions.append(button('Annual fee paid', function () { act('POST', base + '/fee-paid'); }));
      }
      if (lic.kind === 'special' && !lic.manager_on_duty) {
        actions.append(button('Name the manager', nameManager(lic), 'lic-action--main'));
      }
      return actions.childNodes.length ? actions : null;
    }

    function sitePicker(lic, s) {
      var picker = el('select', { 'aria-label': 'Site for ' + (lic.licence_number || lic.kind_label), className: 'lic-site-picker' });
      picker.append(el('option', { value: '', text: 'Choose site' }));
      (s.sites || []).forEach(function (site) { picker.append(el('option', { value: site.id, text: site.name })); });
      picker.value = lic.site_id || '';
      return el('div', { className: 'lic-site' }, [picker, button('Assign site', function () {
        if (picker.value) act('PUT', '/api/compliant/licensing/licences/' + lic.id, { site_id: picker.value });
      })]);
    }

    function licenceCard(lic, s) {
      var facts = [];
      var more = [];
      function fact(list, label, value) { if (value) list.push(el('dt', { text: label }), el('dd', { text: value })); }
      if (lic.kind === 'special') {
        fact(facts, 'Event', lic.event_name);
        fact(facts, 'Dates', fmt(lic.event_starts_on) + (lic.event_ends_on && lic.event_ends_on !== lic.event_starts_on ? ' to ' + fmt(lic.event_ends_on) : ''));
        fact(facts, 'Manager on duty', lic.manager_on_duty || 'Not named yet');
      } else {
        fact(facts, 'Expires', lic.expires_on ? fmt(lic.expires_on) + (lic.status === 'current' ? ' · ' + when(lic.expires_on) : '') : '');
        fact(facts, 'File renewal by', lic.renewal_lodged_on || lic.status !== 'current' ? '' : fmt(lic.renewal_file_by) + ' · ' + when(lic.renewal_file_by));
        fact(facts, 'Annual fee due', lic.annual_fee_due_on ? fmt(lic.annual_fee_due_on) + (lic.annual_fee_overdue ? ' (overdue)' : '') : '');
      }
      fact(facts, 'Site', lic.site_name || 'Not assigned');
      fact(more, 'Premises', lic.premises);
      fact(more, 'DLC', lic.issuing_dlc);
      fact(more, 'Endorsements', lic.endorsement_labels.join(', '));
      fact(more, 'Sale hours', lic.sale_hours);
      fact(more, 'Delivery hours', lic.delivery_hours_start ? lic.delivery_hours_start + ' to ' + lic.delivery_hours_end : '');
      fact(more, 'Conditions', lic.conditions);
      var details = null;
      if (more.length || (canManage && lic.status === 'current')) {
        details = el('details', { className: 'lic-card__more' }, [el('summary', { text: 'Site, conditions and hours' }), more.length ? el('dl', {}, more) : null]);
        if (canManage && lic.status === 'current') {
          details.append(sitePicker(lic, s), button('No longer held', function () {
            if (window.confirm('Mark this licence as no longer held? It stays in the records.')) act('POST', '/api/compliant/licensing/licences/' + lic.id + '/end');
          }, 'lic-action--quiet'));
        }
      }
      return el('article', { className: 'licensing-card lic-card lic-card--' + (TONES[lic.state_code] || 'muted') }, [
        el('div', { className: 'lic-card__head' }, [
          el('h3', {}, [el('span', { text: lic.kind_label }), lic.licence_number ? el('small', { text: lic.licence_number }) : null]),
          chip(lic.state_code, lic.state_label)
        ]),
        el('dl', { className: 'lic-card__facts' }, facts),
        licenceActions(lic),
        details
      ]);
    }

    function renderLicences(s) {
      var host = $('[data-licensing-licences]');
      var live = s.licences.filter(function (l) { return l.status === 'current'; });
      var ended = s.licences.filter(function (l) { return l.status !== 'current'; });
      host.replaceChildren();
      if (!s.licences.length) host.append(el('p', { className: 'lic-empty', text: 'No licences yet. Add yours, including special licences for events.' }));
      live.forEach(function (lic) { host.append(licenceCard(lic, s)); });
      var box = $('[data-lic-ended-licences]');
      box.hidden = !ended.length;
      box.querySelector('summary').textContent = 'Ended or no longer held (' + ended.length + ')';
      box.querySelector('.lic-licences').replaceChildren.apply(box.querySelector('.lic-licences'), ended.map(function (lic) { return licenceCard(lic, s); }));
    }

    function managerRow(m) {
      var actions = el('div', { className: 'lic-row__actions' });
      if (canManage && m.active) {
        var base = '/api/compliant/licensing/managers/' + m.id;
        if (!m.renewal_lodged_on) actions.append(button('Renewal lodged', lodgeManager(m)));
        else actions.append(button('Renewed', async function () {
          var d = await ask('Certificate renewed', 'New expiry date', 'date', '');
          if (d) act('POST', base + '/renewed', { expires_on: d });
        }));
        actions.append(button('Left', function () {
          if (window.confirm(m.holder_name + ' no longer works here?')) act('POST', base + '/end');
        }, 'lic-action--quiet'));
      }
      return el('li', { className: 'lic-row' }, [
        el('div', { className: 'lic-row__main' }, [
          el('strong', { text: m.holder_name }),
          el('span', { text: [m.certificate_number, m.issuing_dlc].filter(Boolean).join(' · ') })
        ]),
        el('span', { className: 'lic-row__date', text: m.active ? 'Expires ' + fmt(m.expires_on) : 'Expired ' + fmt(m.expires_on) }),
        chip(m.state_code, m.state_label),
        actions.childNodes.length ? actions : null
      ]);
    }

    function renderManagers(s) {
      var active = s.managers.filter(function (m) { return m.active; });
      var gone = s.managers.filter(function (m) { return !m.active; });
      var list = $('[data-licensing-managers]');
      list.replaceChildren();
      if (!active.length) list.append(el('li', { className: 'lic-empty', text: 'No managers’ certificates yet.' }));
      active.forEach(function (m) { list.append(managerRow(m)); });
      var box = $('[data-lic-ended-managers]');
      box.hidden = !gone.length;
      box.querySelector('summary').textContent = 'No longer with us (' + gone.length + ')';
      box.querySelector('ul').replaceChildren.apply(box.querySelector('ul'), gone.map(managerRow));
      var select = $('[data-manager-user]');
      if (select.options.length === 1) s.staff.forEach(function (p) { select.append(el('option', { value: p.id, text: p.name })); });
    }

    function checkInfo(c) {
      if (c.from_register) return c.reason;
      if (!c.latest) return c.reason;
      return c.latest.title + ' · ' + fmt(c.latest.recorded_on) + (c.latest.review_due ? ' · review by ' + fmt(c.latest.review_due) : '');
    }

    function renderChecks(s) {
      var list = $('[data-licensing-checks]');
      list.replaceChildren();
      s.checks.forEach(function (c) {
        var li = el('li', { className: 'lic-row lic-row--check', title: c.description }, [
          el('div', { className: 'lic-row__main' }, [el('strong', { text: CHECK_NAMES[c.control_id] || c.description }), el('span', { text: checkInfo(c) })]),
          chip(c.state, CHECK_LABELS[c.state] || c.state)
        ]);
        if (!c.from_register && canRecord) {
          li.append(el('div', { className: 'lic-row__actions' }, [button(c.latest ? 'Record again' : 'Record', function () { openCheck(c); }, c.latest ? '' : 'lic-action--main')]));
        }
        list.append(li);
      });
    }

    function openCheck(c) {
      var form = $('[data-check-form]');
      form.reset();
      form.control_id.value = c.control_id;
      $('[data-check-form-title]').textContent = CHECK_NAMES[c.control_id] || 'Record a check';
      $('[data-check-form-asks]').textContent = c.description;
      var review = new Date(); review.setFullYear(review.getFullYear() + 1);
      form.due_date.value = review.getFullYear() + '-' + String(review.getMonth() + 1).padStart(2, '0') + '-' + String(review.getDate()).padStart(2, '0');
      openDialog('check');
    }

    function renderLog(s) {
      var list = $('[data-licensing-log]');
      list.replaceChildren();
      if (!s.log.length) list.append(el('li', { className: 'lic-empty', text: 'Nothing logged yet. Log every refusal and incident, even small ones.' }));
      var rows = showAllLog ? s.log : s.log.slice(0, LOG_LIMIT);
      rows.forEach(function (e) {
        var where = [e.location, e.staff_name].filter(Boolean).join(' · ');
        list.append(el('li', { className: 'lic-row lic-row--log' }, [
          el('div', { className: 'lic-row__main' }, [
            el('strong', { text: e.kind_label }),
            el('span', { className: 'lic-row__what', text: e.description }),
            e.action_taken ? el('span', { className: 'lic-row__action', text: 'Action: ' + e.action_taken }) : null,
            where || e.reference ? el('span', { className: 'lic-row__where', text: [where, e.reference].filter(Boolean).join(' · ') }) : null
          ]),
          el('span', { className: 'lic-row__date', text: new Date(e.occurred_at).toLocaleString('en-NZ', { dateStyle: 'medium', timeStyle: 'short' }) })
        ]));
      });
      var more = $('[data-lic-log-more]');
      more.hidden = s.log.length <= LOG_LIMIT;
      more.textContent = showAllLog ? 'Show the latest ' + LOG_LIMIT : 'Show all ' + s.log.length + ' entries';
    }

    function tile(label, value, note, tone) {
      return el('div', { className: 'lic-fact lic-fact--' + tone }, [
        el('span', { className: 'lic-fact__label', text: label }),
        el('strong', { className: 'lic-fact__value', text: value }),
        el('span', { className: 'lic-fact__note', text: note })
      ]);
    }

    // The four answers: can we sell, who can manage, is the proof current, is the log kept.
    function summarise(s) {
      var live = s.licences.filter(function (l) { return l.status === 'current'; });
      var standing = live.filter(function (l) { return l.kind !== 'special'; });
      var worst = standing.slice().sort(function (a, b) {
        var rank = { expired: 0, late: 1, due: 2, ok: 3 };
        return (rank[a.state_code] ?? 4) - (rank[b.state_code] ?? 4);
      })[0];
      var licence;
      if (!live.length) licence = { value: 'None recorded', note: 'Add your licence', tone: 'warn' };
      else if (!worst) licence = { value: 'Special only', note: plural(live.length, 'special licence'), tone: 'good' };
      else {
        var tone = TONES[worst.state_code] || 'muted';
        var next = worst.renewal_lodged_on ? 'Renewal lodged ' + fmt(worst.renewal_lodged_on) : 'File renewal by ' + fmt(worst.renewal_file_by);
        licence = { value: worst.state_code === 'ok' ? 'Current' : (worst.state_code === 'due' ? 'Renewal due' : (worst.state_code === 'late' ? 'Renewal late' : 'Expired')), note: next, tone: tone };
      }
      var active = s.managers.filter(function (m) { return m.active; });
      var current = active.filter(function (m) { return m.state_code !== 'expired'; });
      var renewing = active.filter(function (m) { return m.state_code === 'due'; }).sort(function (a, b) { return a.expires_on < b.expires_on ? -1 : 1; })[0];
      var managers = {
        value: current.length ? current.length + ' current' : 'None current',
        note: renewing ? renewing.holder_name + ' renews by ' + fmt(renewing.expires_on) : (current.length ? 'No renewals due' : 'Add a manager’s certificate'),
        tone: !current.length ? 'bad' : (renewing ? 'warn' : 'good')
      };
      var good = s.checks.filter(function (c) { return c.state === 'current' || c.state === 'compliant'; }).length;
      var overdue = s.checks.filter(function (c) { return c.state === 'overdue' || c.state === 'attention'; }).length;
      var missing = s.checks.filter(function (c) { return c.state === 'missing' || c.state === 'setup'; }).length;
      var soon = s.checks.filter(function (c) { return c.state === 'due'; }).length;
      var notes = [];
      if (overdue) notes.push(overdue + ' overdue');
      if (missing) notes.push(plural(missing, 'with no record', 'with no record'));
      if (soon) notes.push(soon + ' to review soon');
      var checks = {
        value: good + ' of ' + s.checks.length + ' current', note: notes.join(', ') || 'Every check has current proof',
        tone: overdue ? 'bad' : (missing || soon ? 'warn' : 'good') };
      var recent = s.log.filter(function (e) { return (Date.now() - new Date(e.occurred_at).getTime()) <= 90 * 86400000; });
      var log = {
        value: recent.length ? plural(recent.length, 'entry', 'entries') : 'Nothing logged',
        note: s.log.length ? 'In the last 90 days · latest ' + new Date(s.log[0].occurred_at).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' }) : 'Log every refusal and incident',
        tone: 'muted' };
      return { licence: licence, managers: managers, checks: checks, log: log };
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
          ends.append(el('label', { className: 'lic-check' }, [el('input', { type: 'checkbox', name: 'endorsements', value: k.value }), k.label]));
        });
        var logKind = $('[data-log-kind]');
        s.log_kinds.forEach(function (k) { logKind.append(el('option', { value: k.value, text: k.label })); });
        syncKind();
      }
      root.querySelectorAll('[data-licensing-manage]').forEach(function (n) { n.hidden = !canManage; });
      root.querySelectorAll('[data-log-open]').forEach(function (n) { n.hidden = !canRecord; });
      var sum = summarise(s);
      $('[data-lic-facts]').replaceChildren(
        tile('Licence', sum.licence.value, sum.licence.note, sum.licence.tone),
        tile('Certified managers', sum.managers.value, sum.managers.note, sum.managers.tone),
        tile('Checks with proof', sum.checks.value, sum.checks.note, sum.checks.tone),
        tile('Incident and refusal log', sum.log.value, sum.log.note, sum.log.tone)
      );
      ['licences', 'managers', 'checks', 'log'].forEach(function (key) {
        var part = sum[key === 'licences' ? 'licence' : key];
        var verdict = $('[data-lic-verdict="' + key + '"]');
        verdict.textContent = part.value + ' · ' + part.note;
        verdict.className = 'lic-verdict lic-verdict--' + part.tone;
      });
      renderLicences(s);
      renderManagers(s);
      renderChecks(s);
      renderLog(s);
      root.setAttribute('aria-busy', 'false');
    }

    $('[data-lic-log-more]').addEventListener('click', function () { showAllLog = !showAllLog; if (state) renderLog(state); });

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
      if (await act('POST', '/api/compliant/licensing/licences', body)) { form.reset(); syncKind(); closeDialog(dialog('licence')); }
    });
    $('[data-manager-form]').addEventListener('submit', async function (e) {
      e.preventDefault();
      var body = formData(e.target);
      if (!body.user_id) delete body.user_id;
      if (await act('POST', '/api/compliant/licensing/managers', body)) { e.target.reset(); closeDialog(dialog('manager')); }
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
        closeDialog(dialog('check'));
        render(await api('GET', '/api/compliant/licensing'));
      } catch (err) { fail(err); }
    });
    $('[data-log-form]').addEventListener('submit', async function (e) {
      e.preventDefault();
      var body = formData(e.target);
      if (body.occurred_at) body.occurred_at = new Date(body.occurred_at).toISOString();
      else delete body.occurred_at;
      Object.keys(body).forEach(function (k) { if (body[k] === '') delete body[k]; });
      if (await act('POST', '/api/compliant/licensing/log', body)) { e.target.reset(); closeDialog(dialog('log')); }
    });

    api('GET', '/api/compliant/licensing').then(render).catch(fail);
  }

  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  bize.onPage('[data-licensing-root]', init);
})();
