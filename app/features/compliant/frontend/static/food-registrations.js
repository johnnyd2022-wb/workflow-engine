(function () {
  'use strict';
  var root = document.querySelector('[data-food-register]');
  if (!root) return;
  var error = root.querySelector('[data-food-error]');
  function text(parent, tag, value) { var el = document.createElement(tag); el.textContent = value; parent.append(el); return el; }
  function report(message) { error.textContent = message || ''; error.hidden = !message; }
  async function api(path, body) {
    var token = document.querySelector('meta[name="csrf-token"]');
    var response = await fetch(path, { method: body ? 'POST' : 'GET', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token ? token.content : '' },
      body: body ? JSON.stringify(body) : undefined });
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not save food registration.');
    return data;
  }
  function choices(selector, rows) {
    var select = root.querySelector(selector); if (!select) return;
    var previous = select.value;
    select.replaceChildren(); text(select, 'option', 'Choose…').value = '';
    rows.forEach(function (row) { text(select, 'option', row.name).value = row.id; });
    if (rows.some(function (row) { return row.id === previous; })) select.value = previous;
  }
  async function load() {
    var data = await api('/api/compliant/food-registrations');
    choices('[data-food-programmes]', Object.entries(data.programmes).map(function (pair) { return { id: pair[0], name: pair[1] }; }));
    choices('[data-food-activities]', Object.entries(data.activities).map(function (pair) { return { id: pair[0], name: pair[1] }; }));
    choices('[data-food-registration-select]', data.registrations); choices('[data-food-sites]', data.sites);
    var list = root.querySelector('[data-food-registration-list]'); list.replaceChildren();
    if (!data.registrations.length) text(list, 'p', 'No registrations recorded. Existing verification history remains unassigned.');
    data.registrations.forEach(function (row) {
      var article = text(list, 'article', ''); text(article, 'h3', row.reference + ' · ' + row.name);
      text(article, 'p', data.programmes[row.programme] + ' · ' + row.registered_on + ' to ' + (row.valid_until || 'ongoing'));
      text(article, 'p', row.evidence_reference);
      var link = text(article, 'a', row.programme === 'fcp' ? 'Open registration context' : 'Open verification history');
      link.href = '/compliant/nz-alcohol/food-safety?registration_id=' + encodeURIComponent(row.id) + '#verification';
      link.setAttribute('hx-boost', 'false');
    });
    var scopes = root.querySelector('[data-food-scope-list]'); scopes.replaceChildren();
    if (!data.coverage.length) text(scopes, 'p', 'No site activities linked yet.');
    data.coverage.forEach(function (row) {
      var registration = data.registrations.find(function (r) { return r.id === row.registration_id; });
      var site = data.sites.find(function (r) { return r.id === row.site_id; });
      var article = text(scopes, 'article', '');
      text(article, 'h3', (site ? site.name : 'Archived site') + ' · ' + data.activities[row.activity]);
      text(article, 'p', (registration ? registration.name : 'Registration') + ' · ' + row.evidence_reference);
    });
  }
  function bind(selector, path) {
    var form = root.querySelector(selector); if (!form) return;
    form.addEventListener('submit', async function (event) {
      event.preventDefault(); report(''); var button = form.querySelector('button'); button.disabled = true;
      var body = Object.fromEntries(new FormData(form));
      if (Object.hasOwn(body, 'valid_until')) body.valid_until = body.valid_until || null;
      try { await api(path, body); form.reset(); await load(); }
      catch (err) { report(err.message); } finally { button.disabled = false; }
    });
  }
  bind('[data-food-registration-form]', '/api/compliant/food-registrations');
  bind('[data-food-scope-form]', '/api/compliant/food-registrations/coverage');
  load().catch(function (err) { report(err.message); });
}());
