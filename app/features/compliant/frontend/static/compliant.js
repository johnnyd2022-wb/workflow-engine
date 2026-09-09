(function () {
  'use strict';
  var root = document.querySelector('[data-compliant-root]');
  if (!root || root.dataset.boundCompliant === '1') return;
  root.dataset.boundCompliant = '1';

  var state = { overview: null };
  var errorEl = root.querySelector('[data-compliant-error]');
  var frameworkRoot = root.querySelector('[data-frameworks]');
  var summaryEl = root.querySelector('[data-compliant-summary]');
  var readinessEl = root.querySelector('[data-readiness]');
  var setupEl = root.querySelector('[data-compliant-setup]');
  var priorityActionsEl = root.querySelector('[data-priority-actions]');
  var frameworkSelect = root.querySelector('[data-framework-select]');
  var controlSelect = root.querySelector('[data-control-select]');
  var captureGuidance = root.querySelector('[data-capture-guidance]');
  var declaredLalField = root.querySelector('[data-declared-lal-field]');
  var evidenceHeading = root.querySelector('[data-evidence-control-heading]');
  var evidenceSummary = root.querySelector('[data-evidence-control-summary]');

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
  function scrollTo(target) { target.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  function setSubmitting(form, submitting) {
    var submit = form.querySelector('button[type="submit"]');
    if (!submit) return;
    if (!submit.dataset.defaultLabel) submit.dataset.defaultLabel = submit.textContent;
    submit.disabled = submitting;
    submit.textContent = submitting ? 'Saving…' : submit.dataset.defaultLabel;
  }

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
    evidenceHeading.textContent = 'Evidence for: ' + control.control_id.replace(/-/g, ' ');
    evidenceSummary.textContent = control.description;
    captureGuidance.textContent = (control.source_reference ? 'NP3 guidance card: ' + control.source_reference + '. ' : '') + (needs.length ? 'To record this: ' + needs.join(', ') + '.' : 'Add a clear record, attachment reference, or reasoned attestation.');
    declaredLalField.hidden = !(capture.fields || []).includes('declared_litres_of_alcohol');
  }
  function coverageLabel(framework) {
    var coverage = framework.evidence_coverage || {};
    return (coverage.current_controls || 0) + ' / ' + (coverage.total_controls || 0) + ' current';
  }
  function renderModuleHealth(frameworks) {
    var target = root.querySelector('[data-module-health]'); clear(target);
    if (!frameworks.length) return;
    var label = document.createElement('p'); label.className = 'compliant-eyebrow'; label.textContent = 'EVIDENCE COVERAGE BY MODULE'; target.appendChild(label);
    var cards = document.createElement('div'); cards.className = 'module-health-grid';
    frameworks.forEach(function (framework) {
      var coverage = framework.evidence_coverage || {};
      var card = document.createElement('article'); card.className = 'module-health-card state-' + framework.state;
      card.appendChild(textElement('strong', framework.name));
      card.appendChild(textElement('span', String(coverage.percent || 0) + '%', 'module-health-percent'));
      card.appendChild(textElement('small', coverageLabel(framework) + ' evidence controls', 'module-health-count'));
      cards.appendChild(card);
    });
    target.appendChild(cards);
  }
  function textElement(tag, value, className) { var el = document.createElement(tag); el.textContent = value; if (className) el.className = className; return el; }
  function frameworkCard(framework) {
    var allPassing = framework.state === 'compliant';
    var card = document.createElement('details'); card.className = 'compliant-framework' + (allPassing ? ' compliant-framework--passing' : ''); card.open = !allPassing;
    var summary = document.createElement('summary');
    var stateBadge = document.createElement('span'); stateBadge.className = statusClass(framework.state); stateBadge.textContent = framework.state;
    var h2 = document.createElement('h2'); h2.textContent = framework.name;
    var score = textElement('span', coverageLabel(framework), 'framework-score');
    summary.appendChild(stateBadge); summary.appendChild(h2); summary.appendChild(score); card.appendChild(summary);
    var source = document.createElement('p');
    if (framework.source_url) { var link = document.createElement('a'); link.href = framework.source_url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = framework.source_title + ' ↗'; source.appendChild(link); }
    else source.textContent = framework.source_title + ' — configure your council source.';
    var list = document.createElement('ul');
    framework.controls.forEach(function (control) {
      var item = document.createElement('li'); item.className = 'framework-control framework-control--' + control.state;
      var copy = document.createElement('div'); var strong = document.createElement('strong'); strong.textContent = control.control_id.replace(/-/g, ' '); copy.appendChild(strong);
      copy.appendChild(textElement('span', control.description, 'framework-control-description'));
      copy.appendChild(textElement('small', control.source_reference ? 'Guidance: ' + control.source_reference : control.reason, 'framework-control-reference'));
      var add = document.createElement('button'); add.type = 'button'; add.className = 'framework-control-action'; add.textContent = control.state === 'compliant' ? 'Review proof' : 'Add proof';
      add.addEventListener('click', function () { selectControl(framework.slug, control.control_id); scrollTo(root.querySelector('[data-record-target]')); root.querySelector('[data-record-form]').title.focus(); });
      item.appendChild(copy); item.appendChild(textElement('span', control.state, statusClass(control.state))); item.appendChild(add); list.appendChild(item);
    });
    var pack = document.createElement('button'); pack.type = 'button'; pack.textContent = 'Generate audit pack';
    pack.addEventListener('click', async function () {
      try { showError(''); var result = await api('/api/compliant/reports/' + encodeURIComponent(framework.slug), { method: 'POST', headers: csrfHeaders(), body: '{}' }); window.open(result.view_url, '_blank', 'noopener'); }
      catch (err) { showError(err.message); }
    });
    card.appendChild(source); card.appendChild(list); card.appendChild(pack); return card;
  }
  function selectControl(frameworkSlug, controlId) {
    frameworkSelect.value = frameworkSlug;
    frameworkSelect.dispatchEvent(new Event('change'));
    controlSelect.value = controlId;
    controlSelect.dispatchEvent(new Event('change'));
  }
  function actionButton(action) {
    var button = document.createElement('button'); button.type = 'button';
    button.textContent = action.kind === 'record' ? (action.state === 'attention' ? 'Rectify this' : action.state === 'review' ? 'Review proof' : 'Add proof') : action.kind === 'product' ? 'Map from Core' : 'Set this up';
    button.addEventListener('click', function () {
      if (action.kind === 'profile') { window.location.href = '/compliant/nz-alcohol/configuration'; return; }
      if (action.kind === 'product') {
        var productForm = root.querySelector('[data-product-form]');
        if (action.suggestions && action.suggestions.length) productForm.inventory_name.value = action.suggestions[0];
        scrollTo(root.querySelector('[data-product-target]')); productForm.inventory_name.focus(); return;
      }
      selectControl(action.framework_slug, action.control_id);
      scrollTo(root.querySelector('[data-record-target]')); root.querySelector('[data-record-form]').title.focus();
    });
    return button;
  }
  function renderPriorityActions(actions) {
    clear(priorityActionsEl);
    if (!actions.length) { priorityActionsEl.textContent = 'You have no priority actions right now. Keep records current and Compliant will surface the next gap.'; return; }
    actions.forEach(function (action, index) {
      var card = document.createElement('article'); card.className = 'priority-action priority-' + (action.state || action.kind);
      var number = document.createElement('span'); number.className = 'action-number'; number.textContent = String(index + 1);
      var body = document.createElement('div'); var heading = document.createElement('h3'); heading.textContent = action.title;
      var description = document.createElement('p'); description.textContent = action.description;
      var value = document.createElement('p'); value.className = 'action-value'; value.textContent = action.value;
      body.appendChild(heading); body.appendChild(description); body.appendChild(value);
      card.appendChild(number); card.appendChild(body); card.appendChild(actionButton(action)); priorityActionsEl.appendChild(card);
    });
  }
  function renderProductSuggestions(reconciliation) {
    var target = root.querySelector('[data-product-suggestions]'); clear(target);
    var names = reconciliation.unprofiled_inventory_names || [];
    if (!names.length) return;
    var intro = document.createElement('strong'); intro.textContent = 'Detected in Core — map with one click:'; target.appendChild(intro);
    names.slice(0, 6).forEach(function (name) {
      var button = document.createElement('button'); button.type = 'button'; button.className = 'suggestion'; button.textContent = name;
      button.addEventListener('click', function () { root.querySelector('[data-product-form]').inventory_name.value = name; root.querySelector('[data-product-form]').abv_percent.focus(); }); target.appendChild(button);
    });
  }
  function renderExistingEvidence(evidence) {
    var target = root.querySelector('[data-existing-evidence]'); clear(target);
    if (!evidence.length) { target.textContent = 'When your team uploads proof to a Core execution, it will appear here to reuse.'; return; }
    var intro = document.createElement('strong'); intro.textContent = 'Reuse proof already in Core:'; target.appendChild(intro);
    evidence.forEach(function (item) {
      var button = document.createElement('button'); button.type = 'button'; button.className = 'evidence-choice'; button.textContent = 'Use ' + item.title;
      button.addEventListener('click', function () {
        var form = root.querySelector('[data-record-form]');
        form.evidence_reference.value = item.title;
        form.source_refs.value = form.source_refs.value ? form.source_refs.value + ', ' + item.id : item.id;
        form.title.focus();
      }); target.appendChild(button);
    });
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
    var readiness = overview.evidence_readiness || {};
    readinessEl.textContent = readiness.total_controls ? readiness.current_controls + ' of ' + readiness.total_controls + ' applicable controls have current proof' : 'Your first useful result is one minute away';
    setupEl.hidden = !!(overview.profile && overview.profile.enabled);
    var reconciliation = overview.customs_reconciliation || {};
    root.querySelector('[data-customs-reconciliation]').textContent = 'Live calculated: ' + (reconciliation.production_litres_of_alcohol || '0') + ' LAL produced, ' + (reconciliation.wastage_litres_of_alcohol || '0') + ' LAL wasted. ' + (reconciliation.unprofiled_movement_count || 0) + ' movement(s) need a product profile.';
    clear(frameworkRoot);
    if (!overview.frameworks.length) { var empty = document.createElement('p'); empty.textContent = 'Enable Compliant to see your applicable framework packs.'; frameworkRoot.appendChild(empty); }
    overview.frameworks.forEach(function (framework) { frameworkRoot.appendChild(frameworkCard(framework)); });
    renderModuleHealth(overview.frameworks || []);
    renderPriorityActions(overview.priority_actions || []);
    renderProductSuggestions(reconciliation);
    renderExistingEvidence(overview.core_proof_candidates || []);
    populateControls();
    var params = new URLSearchParams(window.location.search);
    if (params.get('framework') && params.get('control')) selectControl(params.get('framework'), params.get('control'));
  }
  async function load() {
    root.setAttribute('aria-busy', 'true');
    try {
      showError('');
      // These views are independent: run them together so the audit picture is limited
      // by the slowest request instead of the sum of three request round trips.
      var overviewRequest = api('/api/compliant/overview');
      var supportingRequests = Promise.allSettled([
        api('/api/compliant/records'),
        api('/api/compliant/alcohol-products'),
      ]);
      state.overview = await overviewRequest;
      render();
      var results = await supportingRequests;
      if (results[0].status === 'fulfilled') renderRecords(results[0].value.records || []);
      else renderRecords([]);
      if (results[1].status === 'fulfilled') renderProducts(results[1].value.products || []);
      else renderProducts([]);
      var secondaryFailures = results.filter(function (result) { return result.status === 'rejected'; });
      if (secondaryFailures.length) showError('Your readiness view is current, but some supporting lists could not load. Refresh to retry.');
    } catch (err) {
      showError(err.message);
      summaryEl.textContent = 'Unable to load';
    } finally {
      root.setAttribute('aria-busy', 'false');
    }
  }
  root.querySelector('[data-record-form]').addEventListener('submit', async function (event) {
    event.preventDefault(); var form = event.currentTarget; var refs = form.source_refs.value.split(',').map(function (value) { return value.trim(); }).filter(Boolean);
    var reviewMonths = Number(form.review_interval_months.value || 0);
    var dueDate = form.due_date.value || null;
    if (!dueDate && reviewMonths) { var next = new Date(); next.setMonth(next.getMonth() + reviewMonths); dueDate = next.toISOString().slice(0, 10); }
    var data = { framework_slug: form.framework_slug.value, control_id: form.control_id.value, record_type: form.record_type.value, status: form.status.value, title: form.title.value, period_start: form.period_start.value || null, period_end: form.period_end.value || null, due_date: dueDate, measured_value: form.measured_value.value || null, limit_value: form.limit_value.value || null, declared_litres_of_alcohol: form.declared_litres_of_alcohol.value || null, evidence_reference: form.evidence_reference.value || null, source_refs: refs, details: reviewMonths ? { review_interval_months: reviewMonths } : {} };
    setSubmitting(form, true);
    try { showError(''); await api('/api/compliant/records', { method: 'POST', headers: csrfHeaders(), body: JSON.stringify(data) }); form.reset(); await load(); }
    catch (err) { showError(err.message); }
    finally { setSubmitting(form, false); }
  });
  root.querySelector('[data-product-form]').addEventListener('submit', async function (event) {
    event.preventDefault(); var form = event.currentTarget;
    setSubmitting(form, true);
    try { showError(''); await api('/api/compliant/alcohol-products', { method: 'POST', headers: csrfHeaders(), body: JSON.stringify({ inventory_name: form.inventory_name.value, product_type: form.product_type.value, abv_percent: form.abv_percent.value, customs_product_code: form.customs_product_code.value || null }) }); form.reset(); await load(); }
    catch (err) { showError(err.message); }
    finally { setSubmitting(form, false); }
  });
  load();
})();
