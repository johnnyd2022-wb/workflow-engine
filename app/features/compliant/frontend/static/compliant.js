(function () {
  'use strict';
  var root = document.querySelector('[data-compliant-root]');
  if (!root || root.dataset.boundCompliant === '1') return;
  root.dataset.boundCompliant = '1';

  var state = { overview: null };
  var errorEl = root.querySelector('[data-compliant-error]');
  var frameworkRoot = root.querySelector('[data-frameworks]');
  var summaryEl = root.querySelector('[data-compliant-summary]');
  var setupEl = root.querySelector('[data-compliant-setup]');
  var frameworkSelect = root.querySelector('[data-framework-select]');
  var controlSelect = root.querySelector('[data-control-select]');
  var captureGuidance = root.querySelector('[data-capture-guidance]');
  var declaredLalField = root.querySelector('[data-declared-lal-field]');

  function showError(message) {
    errorEl.textContent = message || '';
    errorEl.hidden = !message;
  }
  function csrfHeaders() {
    var token = document.querySelector('meta[name="csrf-token"]');
    return { 'Content-Type': 'application/json', 'X-CSRFToken': token ? token.content : '' };
  }
  async function api(url, options) {
    var response = await fetch(url, options || {});
    var body = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(body.error || 'Request failed');
    return body;
  }
  function clear(element) { while (element.firstChild) element.removeChild(element.firstChild); }
  function statusClass(status) { return 'state state-' + (status || 'setup'); }
  function option(value, label) { var el = document.createElement('option'); el.value = value; el.textContent = label; return el; }

  function populateControls() {
    clear(frameworkSelect); clear(controlSelect);
    (state.overview.frameworks || []).forEach(function (framework) {
      frameworkSelect.appendChild(option(framework.slug, framework.name));
    });
    function renderControls() {
      clear(controlSelect);
      var framework = (state.overview.frameworks || []).find(function (item) { return item.slug === frameworkSelect.value; });
      if (!framework) return;
      framework.controls.forEach(function (control) { controlSelect.appendChild(option(control.control_id, control.control_id.replace(/-/g, ' '))); });
      renderCaptureGuidance();
    }
    frameworkSelect.onchange = renderControls;
    controlSelect.onchange = renderCaptureGuidance;
    renderControls();
  }
  function renderCaptureGuidance() {
    var framework = (state.overview.frameworks || []).find(function (item) { return item.slug === frameworkSelect.value; });
    var control = framework && framework.controls.find(function (item) { return item.control_id === controlSelect.value; });
    if (!control) { captureGuidance.textContent = ''; declaredLalField.hidden = true; return; }
    var capture = control.capture || {}; var needs = [];
    if (capture.period) needs.push('period start and end');
    if (capture.evidence) needs.push('evidence reference');
    if (capture.source_refs) needs.push('linked Core source');
    if (capture.due_date) needs.push('review or expiry date');
    (capture.fields || []).forEach(function (field) { needs.push(field.replace(/_/g, ' ')); });
    captureGuidance.textContent = control.description + (needs.length ? ' Required: ' + needs.join(', ') + '.' : '');
    declaredLalField.hidden = !(capture.fields || []).includes('declared_litres_of_alcohol');
  }
  function frameworkCard(framework) {
    var card = document.createElement('article'); card.className = 'compliant-framework';
    var stateBadge = document.createElement('span'); stateBadge.className = statusClass(framework.state); stateBadge.textContent = framework.state;
    var h2 = document.createElement('h2'); h2.textContent = framework.name;
    var source = document.createElement('p');
    if (framework.source_url) { var link = document.createElement('a'); link.href = framework.source_url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = framework.source_title + ' ↗'; source.appendChild(link); }
    else source.textContent = framework.source_title + ' — configure your council source.';
    var list = document.createElement('ul');
    framework.controls.forEach(function (control) { var item = document.createElement('li'); var strong = document.createElement('strong'); strong.textContent = control.control_id.replace(/-/g, ' ') + ': '; item.appendChild(strong); item.appendChild(document.createTextNode(control.reason)); list.appendChild(item); });
    var pack = document.createElement('button'); pack.type = 'button'; pack.textContent = 'Generate audit pack';
    pack.addEventListener('click', async function () {
      try { showError(''); var result = await api('/api/compliant/reports/' + encodeURIComponent(framework.slug), { method: 'POST', headers: csrfHeaders(), body: '{}' }); window.open(result.view_url, '_blank', 'noopener'); }
      catch (err) { showError(err.message); }
    });
    card.appendChild(stateBadge); card.appendChild(h2); card.appendChild(source); card.appendChild(list); card.appendChild(pack); return card;
  }
  function renderRecords(records) {
    var target = root.querySelector('[data-recent-records]'); clear(target);
    if (!records.length) { target.textContent = 'No records yet.'; return; }
    var table = document.createElement('table'); var head = document.createElement('thead'); var row = document.createElement('tr'); ['Framework', 'Control', 'Record', 'Status', 'Evidence'].forEach(function (label) { var th = document.createElement('th'); th.textContent = label; row.appendChild(th); }); head.appendChild(row); table.appendChild(head);
    var body = document.createElement('tbody'); records.forEach(function (record) { var tr = document.createElement('tr'); [record.framework_slug, record.control_id, record.title, record.status, record.evidence_reference || '—'].forEach(function (value) { var td = document.createElement('td'); td.textContent = value; tr.appendChild(td); }); body.appendChild(tr); }); table.appendChild(body); target.appendChild(table);
  }
  function renderProducts(products) {
    var target = root.querySelector('[data-alcohol-products]'); clear(target);
    if (!products.length) { target.textContent = 'No alcohol product profiles yet — unprofiled production will be shown as a reconciliation gap.'; return; }
    var list = document.createElement('ul');
    products.forEach(function (product) { var item = document.createElement('li'); item.textContent = product.inventory_name + ' · ' + product.product_type + ' · ' + product.abv_percent + '% ABV'; list.appendChild(item); });
    target.appendChild(list);
  }
  function render() {
    var overview = state.overview; var counts = overview.counts || {};
    var coverage = overview.data_coverage || {};
    summaryEl.textContent = (counts.attention || 0) + ' need attention · ' + (counts.compliant || 0) + ' on track · ' + (coverage.unresolved_live_data_gaps || 0) + ' live-data gaps';
    setupEl.hidden = !!(overview.profile && overview.profile.enabled);
    var reconciliation = overview.customs_reconciliation || {};
    root.querySelector('[data-customs-reconciliation]').textContent = 'Live calculated: ' + (reconciliation.production_litres_of_alcohol || '0') + ' LAL produced, ' + (reconciliation.wastage_litres_of_alcohol || '0') + ' LAL wasted. ' + (reconciliation.unprofiled_movement_count || 0) + ' movement(s) need a product profile.';
    clear(frameworkRoot);
    if (!overview.frameworks.length) { var empty = document.createElement('p'); empty.textContent = 'Enable Compliant to see your applicable framework packs.'; frameworkRoot.appendChild(empty); }
    overview.frameworks.forEach(function (framework) { frameworkRoot.appendChild(frameworkCard(framework)); });
    var catalogueSelect = root.querySelector('[data-trade-waste-council]');
    clear(catalogueSelect); catalogueSelect.appendChild(option('', 'Choose if trade waste applies'));
    (overview.trade_waste_catalogues || []).forEach(function (catalogue) { catalogueSelect.appendChild(option(catalogue.slug, catalogue.name)); });
    if (overview.profile && overview.profile.settings) {
      catalogueSelect.value = overview.profile.settings.trade_waste_council || '';
      root.querySelector('[data-profile-form]').council_name.value = overview.profile.council_name || '';
      root.querySelector('[data-profile-form]').consent.value = overview.profile.trade_waste_consent_reference || '';
      root.querySelector('[data-profile-form]').require_core_source_refs.checked = Boolean(overview.profile.settings.require_core_source_refs);
    }
    populateControls();
  }
  async function load() {
    try { showError(''); state.overview = await api('/api/compliant/overview'); render(); var records = await api('/api/compliant/records'); renderRecords(records.records || []); var products = await api('/api/compliant/alcohol-products'); renderProducts(products.products || []); }
    catch (err) { showError(err.message); summaryEl.textContent = 'Unable to load'; }
  }
  root.querySelector('[data-profile-form]').addEventListener('submit', async function (event) {
    event.preventDefault(); var form = event.currentTarget; var types = Array.prototype.map.call(form.querySelectorAll('input[name="product_type"]:checked'), function (input) { return input.value; });
    try { showError(''); await api('/api/compliant/profile', { method: 'PUT', headers: csrfHeaders(), body: JSON.stringify({ enabled: true, council_name: form.council_name.value || null, trade_waste_consent_reference: form.consent.value || null, settings: { alcohol_product_types: types, trade_waste_required: Boolean(form.consent.value || form.trade_waste_council.value), trade_waste_council: form.trade_waste_council.value || null, require_core_source_refs: form.require_core_source_refs.checked } }) }); await load(); }
    catch (err) { showError(err.message); }
  });
  root.querySelector('[data-record-form]').addEventListener('submit', async function (event) {
    event.preventDefault(); var form = event.currentTarget; var refs = form.source_refs.value.split(',').map(function (value) { return value.trim(); }).filter(Boolean);
    var data = { framework_slug: form.framework_slug.value, control_id: form.control_id.value, record_type: form.record_type.value, status: form.status.value, title: form.title.value, period_start: form.period_start.value || null, period_end: form.period_end.value || null, due_date: form.due_date.value || null, measured_value: form.measured_value.value || null, limit_value: form.limit_value.value || null, declared_litres_of_alcohol: form.declared_litres_of_alcohol.value || null, evidence_reference: form.evidence_reference.value || null, source_refs: refs, details: {} };
    try { showError(''); await api('/api/compliant/records', { method: 'POST', headers: csrfHeaders(), body: JSON.stringify(data) }); form.reset(); await load(); }
    catch (err) { showError(err.message); }
  });
  root.querySelector('[data-product-form]').addEventListener('submit', async function (event) {
    event.preventDefault(); var form = event.currentTarget;
    try { showError(''); await api('/api/compliant/alcohol-products', { method: 'POST', headers: csrfHeaders(), body: JSON.stringify({ inventory_name: form.inventory_name.value, product_type: form.product_type.value, abv_percent: form.abv_percent.value, customs_product_code: form.customs_product_code.value || null }) }); form.reset(); await load(); }
    catch (err) { showError(err.message); }
  });
  load();
})();
