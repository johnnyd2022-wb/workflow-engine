(function () {
  'use strict';
  var root = document.querySelector('[data-compliant-root]');
  if (!root || root.dataset.boundCompliant === '1') return;
  root.dataset.boundCompliant = '1';

  var state = { overview: null };
  // The only remaining generic record form is Customs (NP3 evidence is per-check, its own workspace).
  var CUSTOMS_FRAMEWORK = 'customs-alcohol';
  var evidenceWorkspace = root.dataset.compliantSurface === 'customs';
  var errorEl = root.querySelector('[data-compliant-error]');
  var frameworkRoot = root.querySelector('[data-frameworks]');
  var summaryEl = root.querySelector('[data-compliant-summary]');
  var readinessEl = root.querySelector('[data-readiness]');
  var controlSelect = root.querySelector('[data-control-select]');
  var captureGuidance = root.querySelector('[data-capture-guidance]');
  var declaredLalField = root.querySelector('[data-declared-lal-field]');
  var evidenceHeading = root.querySelector('[data-evidence-control-heading]');
  var evidenceSummary = root.querySelector('[data-evidence-control-summary]');
  var selectedCoreSources = new Map();
  var coreSourceOffset = 0;

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
  function option(value, label) { var el = document.createElement('option'); el.value = value; el.textContent = label; return el; }
  function setSubmitting(form, submitting) {
    var submit = form.querySelector('button[type="submit"]');
    if (!submit) return;
    if (!submit.dataset.defaultLabel) submit.dataset.defaultLabel = submit.textContent;
    submit.disabled = submitting;
    submit.textContent = submitting ? 'Saving…' : submit.dataset.defaultLabel;
  }

  function customsFramework() {
    return (state.overview.frameworks || []).find(function (item) { return item.slug === CUSTOMS_FRAMEWORK; });
  }
  function populateControls() {
    clear(controlSelect);
    var framework = customsFramework();
    if (!framework) return;
    framework.controls.forEach(function (control) { controlSelect.appendChild(option(control.control_id, control.control_id.replace(/-/g, ' '))); });
    controlSelect.onchange = renderCaptureGuidance;
    renderCaptureGuidance();
  }
  function renderCaptureGuidance() {
    var framework = customsFramework();
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
  function moduleSummaryHealth(framework) {
    var coverage = framework.evidence_coverage || {};
    var health = framework.summary_health || {};
    var ready = Number(health.evidence_ready == null ? coverage.current_controls || 0 : health.evidence_ready);
    var total = Number(health.total_controls == null ? coverage.total_controls || 0 : health.total_controls);
    return {
      score: Number(health.score == null ? coverage.percent || 0 : health.score),
      currentControls: Number(health.current_controls == null ? ready : health.current_controls),
      totalControls: total,
      evidenceReady: ready,
      needsAttention: Number(health.needs_attention == null ? Math.max(0, total - ready) : health.needs_attention),
      overdue: Number(health.overdue || 0)
    };
  }
  function moduleMetric(number, label, tone) {
    var metric = document.createElement('span'); metric.className = 'compliant-framework-summary__metric compliant-framework-summary__metric--' + tone;
    metric.appendChild(textElement('strong', String(number)));
    metric.appendChild(document.createTextNode(' ' + label));
    return metric;
  }
  function np3ReadinessBar(health) {
    var bar = document.createElement('div');
    bar.className = 'compliant-framework-summary__progress';
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-label', 'NP3 evidence readiness');
    bar.setAttribute('aria-valuemin', '0');
    bar.setAttribute('aria-valuemax', '100');
    bar.setAttribute('aria-valuenow', String(health.score));
    var fill = document.createElement('span');
    fill.style.width = Math.max(0, Math.min(100, health.score)) + '%';
    bar.appendChild(fill);
    return bar;
  }
  function renderModuleHealth(frameworks) {
    var target = frameworkRoot; clear(target);
    if (!frameworks.length) return;
    frameworks.forEach(function (framework) {
      var health = moduleSummaryHealth(framework);
      var card = document.createElement('article'); card.className = 'module-health-card compliant-framework-summary state-' + framework.state;
      card.appendChild(textElement('h2', framework.name, 'compliant-framework-summary__title'));
      card.appendChild(textElement('p', 'Compliance score: ' + health.score + '%', 'compliant-framework-summary__score'));
      if (framework.slug === 'np3-food-control') card.appendChild(np3ReadinessBar(health));
      card.appendChild(textElement('p', health.currentControls + ' / ' + health.totalControls + ' current evidence controls', 'compliant-framework-summary__coverage'));
      var metrics = document.createElement('div'); metrics.className = 'compliant-framework-summary__metrics';
      metrics.appendChild(moduleMetric(health.evidenceReady, 'evidence ready', 'ready'));
      metrics.appendChild(moduleMetric(health.needsAttention, 'need attention', 'attention'));
      metrics.appendChild(moduleMetric(health.overdue, 'overdue', 'overdue'));
      card.appendChild(metrics);
      // Only these two have a workspace: NP3 evidence is per-check, Customs keeps the generic
      // record form. Any other framework in the catalogue has no capture page yet.
      var destination = framework.slug === 'np3-food-control'
        ? '/compliant/nz-alcohol/food-safety'
        : framework.slug === CUSTOMS_FRAMEWORK ? '/compliant/nz-alcohol/customs' : null;
      if (destination) {
        var link = document.createElement('a'); link.href = destination; link.setAttribute('hx-boost', 'false');
        link.className = 'compliant-framework-summary__link';
        link.textContent = framework.slug === 'np3-food-control' ? 'Open NP3' : 'Open Customs';
        card.appendChild(link);
      }
      target.appendChild(card);
    });
  }
  function textElement(tag, value, className) { var el = document.createElement(tag); el.textContent = value; if (className) el.className = className; return el; }
  function selectControl(controlId) {
    controlSelect.value = controlId;
    controlSelect.dispatchEvent(new Event('change'));
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
  function renderSelectedCoreSources() {
    var target = root.querySelector('[data-core-source-selected]'); clear(target);
    if (!selectedCoreSources.size) { target.textContent = 'No Core records selected.'; return; }
    selectedCoreSources.forEach(function (item) {
      var button = document.createElement('button'); button.type = 'button';
      button.textContent = 'Remove ' + item.title;
      button.addEventListener('click', function () {
        selectedCoreSources.delete(item.id);
        root.querySelectorAll('input[name="core_source_ref"]').forEach(function (input) { if (input.value === item.id) input.checked = false; });
        renderSelectedCoreSources();
      });
      target.appendChild(button);
    });
  }
  function renderCoreSourcePicker(candidates, append) {
    var target = root.querySelector('[data-core-source-picker]');
    if (!append) clear(target);
    if (!candidates.length && !append) { target.textContent = 'No Core records found.'; renderSelectedCoreSources(); return; }
    candidates.forEach(function (item) {
      var label = document.createElement('label'); label.className = 'core-source-picker__choice';
      var checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.name = 'core_source_ref'; checkbox.value = item.id;
      checkbox.checked = selectedCoreSources.has(item.id);
      checkbox.addEventListener('change', function () {
        var form = root.querySelector('[data-record-form]');
        if (checkbox.checked && selectedCoreSources.size >= 30) {
          checkbox.checked = false;
          showError('Choose at most 30 Core source records.');
          return;
        }
        if (checkbox.checked) selectedCoreSources.set(item.id, item);
        else selectedCoreSources.delete(item.id);
        if (checkbox.checked && item.kind === 'file' && !form.evidence_reference.value) form.evidence_reference.value = item.title;
        renderSelectedCoreSources();
      });
      label.appendChild(checkbox);
      var date = item.created_at ? new Date(item.created_at).toLocaleString() : '';
      label.appendChild(document.createTextNode(' ' + item.title + ' (' + item.kind.replace(/-/g, ' ') + (date ? ' · ' + date : '') + ')'));
      target.appendChild(label);
    });
    renderSelectedCoreSources();
  }
  async function searchCoreSources(append) {
    var kind = root.querySelector('[data-core-source-kind]').value;
    var query = root.querySelector('[data-core-source-query]').value.trim();
    var offset = append ? coreSourceOffset : 0;
    try {
      var result = await api('/api/compliant/core-sources?kind=' + encodeURIComponent(kind) + '&q=' + encodeURIComponent(query) + '&offset=' + offset);
      renderCoreSourcePicker(result.sources || [], append);
      coreSourceOffset = offset + (result.sources || []).length;
      root.querySelector('[data-core-source-more]').hidden = !result.has_more;
    } catch (err) { showError(err.message); }
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
    if (summaryEl) summaryEl.textContent = (counts.attention || 0) + ' need attention · ' + (counts.compliant || 0) + ' on track · ' + (coverage.unresolved_live_data_gaps || 0) + ' live-data gaps';
    var readiness = overview.evidence_readiness || {};
    if (readinessEl) readinessEl.textContent = readiness.total_controls ? readiness.current_controls + ' of ' + readiness.total_controls + ' applicable controls have current proof' : 'Your first useful result is one minute away';
    if (!evidenceWorkspace) {
      renderModuleHealth(overview.frameworks || []);
      return;
    }
    var reconciliation = overview.customs_reconciliation || {};
    root.querySelector('[data-customs-reconciliation]').textContent = 'Live calculated: ' + (reconciliation.production_litres_of_alcohol || '0') + ' LAL produced, ' + (reconciliation.wastage_litres_of_alcohol || '0') + ' LAL wasted. ' + (reconciliation.unprofiled_movement_count || 0) + ' movement(s) need a product profile.';
    renderProductSuggestions(reconciliation);
    searchCoreSources(false);
    populateControls();
    var control = new URLSearchParams(window.location.search).get('control');
    if (control) selectControl(control);
  }
  async function load() {
    root.setAttribute('aria-busy', 'true');
    try {
      showError('');
      var overviewRequest = api('/api/compliant/overview');
      if (!evidenceWorkspace) {
        state.overview = await overviewRequest;
        render();
        return;
      }
      // Evidence lists are independent: load them together without delaying the
      // mapping and record workspace behind serial requests.
      var supportingRequests = Promise.allSettled([
        api('/api/compliant/records?framework=' + encodeURIComponent(CUSTOMS_FRAMEWORK)),
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
      if (summaryEl) summaryEl.textContent = 'Unable to load';
    } finally {
      root.setAttribute('aria-busy', 'false');
    }
  }
  var recordForm = root.querySelector('[data-record-form]');
  if (recordForm) {
    root.querySelector('[data-core-source-search]').addEventListener('click', function () { searchCoreSources(false); });
    root.querySelector('[data-core-source-more]').addEventListener('click', function () { searchCoreSources(true); });
    root.querySelector('[data-core-source-query]').addEventListener('keydown', function (event) {
      if (event.key === 'Enter') { event.preventDefault(); searchCoreSources(false); }
    });
  }
  if (recordForm) recordForm.addEventListener('submit', async function (event) {
    event.preventDefault(); var form = event.currentTarget; var refs = Array.from(selectedCoreSources.keys());
    var reviewMonths = Number(form.review_interval_months.value || 0);
    var dueDate = form.due_date.value || null;
    if (!dueDate && reviewMonths) { var next = new Date(); next.setMonth(next.getMonth() + reviewMonths); dueDate = next.toISOString().slice(0, 10); }
    var data = { framework_slug: form.framework_slug.value, control_id: form.control_id.value, record_type: form.record_type.value, status: form.status.value, title: form.title.value, period_start: form.period_start.value || null, period_end: form.period_end.value || null, due_date: dueDate, measured_value: form.measured_value.value || null, limit_value: form.limit_value.value || null, declared_litres_of_alcohol: form.declared_litres_of_alcohol.value || null, evidence_reference: form.evidence_reference.value || null, source_refs: refs, details: reviewMonths ? { review_interval_months: reviewMonths } : {} };
    setSubmitting(form, true);
    try { showError(''); await api('/api/compliant/records', { method: 'POST', headers: csrfHeaders(), body: JSON.stringify(data) }); form.reset(); selectedCoreSources.clear(); await load(); }
    catch (err) { showError(err.message); }
    finally { setSubmitting(form, false); }
  });
  var productForm = root.querySelector('[data-product-form]');
  if (productForm) productForm.addEventListener('submit', async function (event) {
    event.preventDefault(); var form = event.currentTarget;
    setSubmitting(form, true);
    try { showError(''); await api('/api/compliant/alcohol-products', { method: 'POST', headers: csrfHeaders(), body: JSON.stringify({ inventory_name: form.inventory_name.value, product_type: form.product_type.value, abv_percent: form.abv_percent.value, customs_product_code: form.customs_product_code.value || null }) }); form.reset(); await load(); }
    catch (err) { showError(err.message); }
    finally { setSubmitting(form, false); }
  });
  load();
})();
