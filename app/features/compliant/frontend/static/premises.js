(function () {
  'use strict';
  var root = document.querySelector('[data-premises-root]');
  if (!root) return;
  var error = root.querySelector('[data-premises-error]');
  var state;
  function report(message) { error.textContent = message || ''; error.hidden = !message; }
  function text(parent, tag, value) {
    var element = document.createElement(tag); element.textContent = value; parent.appendChild(element); return element;
  }
  async function api(path, body) {
    var csrf = document.querySelector('meta[name="csrf-token"]');
    var response = await fetch(path, { method: body ? 'POST' : 'GET', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf ? csrf.content : '' },
      body: body ? JSON.stringify(body) : undefined });
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not save Customs premises.');
    return data;
  }
  function choices(select, rows, label) {
    if (!select) return;
    var previous = select.value;
    select.replaceChildren(); text(select, 'option', 'Choose ' + label).value = '';
    rows.forEach(function (row) { text(select, 'option', row.name || row.number).value = row.id; });
    if (rows.some(function (row) { return row.id === previous; })) select.value = previous;
  }
  function locations() {
    var select = root.querySelector('[data-location-select]');
    var site = root.querySelector('[data-site-select]');
    if (!select || !site) return;
    select.replaceChildren(); text(select, 'option', 'Main area (without a named stock location)').value = '';
    state.locations.filter(function (row) { return row.site_id === site.value; }).forEach(function (row) {
      text(select, 'option', row.name).value = row.id;
    });
  }
  async function load() {
    state = await api('/api/compliant/nz-alcohol/premises');
    choices(root.querySelector('[data-licence-select]'), state.licences, 'a licence');
    choices(root.querySelector('[data-site-select]'), state.sites, 'a site'); locations();
    var licences = root.querySelector('[data-licences]'); licences.replaceChildren();
    if (!state.licences.length) text(licences, 'p', 'No CCA licences registered.');
    state.licences.forEach(function (row) {
      var card = document.createElement('article'); text(card, 'h3', row.number + ' · ' + row.name);
      text(card, 'p', state.kinds[row.kind] + ' · Entity ' + row.legal_entity_reference);
      text(card, 'p', row.valid_from + ' to ' + (row.valid_until || 'ongoing') + ' · ' + row.evidence_reference);
      licences.appendChild(card);
    });
    var coverage = root.querySelector('[data-coverage]'); coverage.replaceChildren();
    if (!state.coverage.length) text(coverage, 'p', 'No licensed areas assigned.');
    state.coverage.forEach(function (row) {
      var site = state.sites.find(function (item) { return item.id === row.site_id; });
      var licence = state.licences.find(function (item) { return item.id === row.licence_id; });
      var location = state.locations.find(function (item) { return item.id === row.location_id; });
      var card = document.createElement('article');
      text(card, 'h3', (site ? site.name : 'Archived site') + ' · ' + (location ? location.name : row.location_id ? 'Archived location' : 'Main area'));
      text(card, 'p', (licence ? licence.number : 'Licence') + ' · ' + row.valid_from + ' to ' + (row.valid_until || 'ongoing'));
      text(card, 'p', row.evidence_reference); coverage.appendChild(card);
    });
  }
  var siteSelect = root.querySelector('[data-site-select]');
  if (siteSelect) siteSelect.addEventListener('change', locations);
  function bind(selector, path) {
    var form = root.querySelector(selector); if (!form) return;
    form.addEventListener('submit', async function (event) {
      event.preventDefault(); report(''); var button = form.querySelector('button'); button.disabled = true;
      var body = Object.fromEntries(new FormData(form));
      body.valid_until = body.valid_until || null;
      if (Object.hasOwn(body, 'location_id')) body.location_id = body.location_id || null;
      try { await api(path, body); form.reset(); await load(); }
      catch (err) { report(err.message); } finally { button.disabled = false; }
    });
  }
  bind('[data-licence-form]', '/api/compliant/nz-alcohol/cca-licences');
  bind('[data-coverage-form]', '/api/compliant/nz-alcohol/cca-coverage');
  load().catch(function (err) { report(err.message); });
}());
