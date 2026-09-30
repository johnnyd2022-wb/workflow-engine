(function () {
  'use strict';
  var root = document.querySelector('[data-compliant-configuration-root]');
  if (!root) return;
  var form = root.querySelector('[data-configuration-form]'); var error = root.querySelector('[data-configuration-error]');
  var profileSettings = {};
  function csrfHeaders() { var token = document.querySelector('meta[name="csrf-token"]'); return { 'Content-Type': 'application/json', 'X-CSRFToken': token ? token.content : '' }; }
  function showError(message) { error.textContent = message || ''; error.hidden = !message; }
  function selected(name) { return Array.prototype.map.call(form.querySelectorAll('input[name="' + name + '"]:checked'), function (input) { return input.value; }); }
  function updateFoodSafetyTab(programme) {
    var tab = document.querySelector('[data-food-safety-tab]');
    if (!tab) return;
    tab.textContent = programme === 'np1' || programme === 'np2' || programme === 'np3' ? programme.toUpperCase() : 'Food safety';
    tab.hidden = programme === 'none';
  }
  function populate(overview) {
    var profile = overview.profile || {}; var settings = profile.settings || {}; profileSettings = settings; form.enabled.checked = Boolean(profile.enabled);
    form.food_control_programme.value = settings.food_control_programme || 'np3'; form.liquor_licence_reference.value = settings.liquor_licence_reference || ''; form.liquor_licence_due_date.value = settings.liquor_licence_due_date || '';
    form.np3_verification_date.value = settings.np3_verification_date || ''; form.np3_verifier_name.value = settings.np3_verifier_name || ''; form.np3_verification_location.value = settings.np3_verification_location || ''; form.np3_review_interval_months.value = String(settings.np3_review_interval_months || 6); form.np3_execution_evidence_mode.value = settings.np3_execution_evidence_mode || 'recommended';
    form.council_name.value = profile.council_name || ''; form.consent.value = profile.trade_waste_consent_reference || ''; form.require_core_source_refs.checked = Boolean(settings.require_core_source_refs);
    Array.prototype.forEach.call(form.querySelectorAll('input[name="product_type"]'), function (input) { input.checked = (settings.alcohol_product_types || []).includes(input.value); });
    Array.prototype.forEach.call(form.querySelectorAll('input[name="liquor_licence_type"]'), function (input) { input.checked = (settings.liquor_licence_types || []).includes(input.value); });
    var council = form.querySelector('[data-trade-waste-council]'); (overview.trade_waste_catalogues || []).forEach(function (item) { var option = document.createElement('option'); option.value = item.slug; option.textContent = item.name; council.appendChild(option); }); council.value = settings.trade_waste_council || '';
  }
  fetch('/api/compliant/overview').then(function (response) { return response.json().then(function (body) { if (!response.ok) throw new Error(body.error || 'Could not load configuration'); return body; }); }).then(function (overview) { populate(overview); updateFoodSafetyTab((overview.profile || {}).settings && (overview.profile || {}).settings.food_control_programme || 'np3'); }).catch(function (err) { showError(err.message); });
  form.addEventListener('submit', function (event) { event.preventDefault(); var licenceTypes = selected('liquor_licence_type'); var productTypes = selected('product_type'); var council = form.trade_waste_council.value || null;
    var payload = { enabled: form.enabled.checked, industry_module: 'nz_alcohol', council_name: form.council_name.value || null, trade_waste_consent_reference: form.consent.value || null, settings: { alcohol_product_types: productTypes, food_control_programme: form.food_control_programme.value, liquor_licence_types: licenceTypes, liquor_licence_reference: form.liquor_licence_reference.value || null, liquor_licence_due_date: form.liquor_licence_due_date.value || null, np3_verification_date: form.np3_verification_date.value || null, np3_verifier_name: form.np3_verifier_name.value || null, np3_verification_location: form.np3_verification_location.value || null, np3_review_interval_months: Number(form.np3_review_interval_months.value), np3_check_review_intervals: profileSettings.np3_check_review_intervals || {}, np3_execution_evidence_mode: form.np3_execution_evidence_mode.value, trade_waste_council: council, trade_waste_required: Boolean(council || form.consent.value), require_core_source_refs: form.require_core_source_refs.checked } };
    // Settings are replaced wholesale on save, so carry keys edited elsewhere on this page.
    if (Array.isArray(profileSettings.abv_product_rules)) payload.settings.abv_product_rules = profileSettings.abv_product_rules;
    // csrfHeaders() explicitly reads meta[name="csrf-token"] and sends X-CSRFToken.
    fetch('/api/compliant/profile', { method: 'PUT', headers: csrfHeaders(), body: JSON.stringify(payload) }).then(function (response) { return response.json().then(function (body) { if (!response.ok) throw new Error(body.error || 'Could not save configuration'); return body; }); }).then(function (body) { profileSettings = body.profile.settings || payload.settings; updateFoodSafetyTab(profileSettings.food_control_programme || 'np3'); showError(''); }).catch(function (err) { showError(err.message); }); // nosemgrep: raw-fetch-post
  });
  // ---- ABV on alcohol products ------------------------------------------------------
  // Rules match each workflow's final-step output names, case-insensitively, the same
  // phrase + exact/contains shape the CRM uses for Xero product mappings. A matched
  // final step gets a required "ABV (%)" field that Core enforces at completion.
  var abvRoot = root.querySelector('[data-abv-rules]');
  var abvRules = [];
  var abvCandidates = [];
  function abvKey(rule) { return rule.match_type + ':' + rule.pattern.trim().toLowerCase(); }
  function abvMatch(name) {
    var lowered = String(name || '').trim().toLowerCase();
    if (!lowered) return null;
    var exact = abvRules.find(function (rule) { return rule.match_type === 'exact' && rule.pattern.trim().toLowerCase() === lowered; });
    if (exact) return exact;
    return abvRules.find(function (rule) { return rule.match_type === 'contains' && lowered.indexOf(rule.pattern.trim().toLowerCase()) !== -1; }) || null;
  }
  function abvShowError(message) { var el = abvRoot.querySelector('[data-abv-error]'); el.textContent = message || ''; el.hidden = !message; }
  function abvSetStatus(text) { abvRoot.querySelector('[data-abv-status]').textContent = text || ''; }
  function abvRender() {
    var body = abvRoot.querySelector('[data-abv-candidates]');
    body.textContent = '';
    if (!abvCandidates.length) {
      var emptyRow = document.createElement('tr');
      var emptyCell = document.createElement('td');
      emptyCell.colSpan = 4;
      emptyCell.textContent = 'No workflows with a final-step output yet. Add one in Production, then come back.';
      emptyRow.appendChild(emptyCell);
      body.appendChild(emptyRow);
    }
    abvCandidates.forEach(function (candidate) {
      var row = document.createElement('tr');
      var tickCell = document.createElement('td');
      var tick = document.createElement('input');
      tick.type = 'checkbox';
      tick.setAttribute('aria-label', 'Require ABV for ' + candidate.output_name);
      var hasExact = abvRules.some(function (rule) { return rule.match_type === 'exact' && rule.pattern.trim().toLowerCase() === candidate.output_name.trim().toLowerCase(); });
      var byPhrase = !hasExact && abvMatch(candidate.output_name);
      // Covered by a phrase: show it as required (ticked) but locked -- untick by removing
      // the phrase below, not per product, or the box would contradict the status.
      tick.checked = hasExact || Boolean(byPhrase);
      tick.disabled = Boolean(byPhrase);
      if (byPhrase) tick.title = 'Covered by the phrase "' + byPhrase.pattern + '". Remove that phrase to choose products individually.';
      tick.addEventListener('change', function () {
        var rule = { pattern: candidate.output_name, match_type: 'exact' };
        if (tick.checked) { if (!abvRules.some(function (r) { return abvKey(r) === abvKey(rule); })) abvRules.push(rule); }
        else { abvRules = abvRules.filter(function (r) { return abvKey(r) !== abvKey(rule); }); }
        abvRender(); abvSetStatus('Unsaved changes');
      });
      tickCell.appendChild(tick);
      var workflowCell = document.createElement('td');
      workflowCell.textContent = candidate.process_name + (candidate.is_draft ? ' (draft)' : '');
      var outputCell = document.createElement('td');
      outputCell.textContent = candidate.output_name;
      var small = document.createElement('small');
      small.textContent = 'Final step: ' + candidate.step_name;
      outputCell.appendChild(document.createElement('br'));
      outputCell.appendChild(small);
      var statusCell = document.createElement('td');
      var match = abvMatch(candidate.output_name);
      var badge = document.createElement('span');
      badge.className = 'state ' + (match ? 'state-compliant' : 'state-setup');
      badge.textContent = match ? (match.match_type === 'exact' ? 'ABV required' : 'ABV required · contains "' + match.pattern + '"') : 'Not required';
      statusCell.appendChild(badge);
      [tickCell, workflowCell, outputCell, statusCell].forEach(function (cell) { row.appendChild(cell); });
      body.appendChild(row);
    });
    var list = abvRoot.querySelector('[data-abv-rule-list]');
    list.textContent = '';
    abvRules.filter(function (rule) { return rule.match_type === 'contains'; }).forEach(function (rule) {
      var item = document.createElement('li');
      var label = document.createElement('span');
      label.textContent = 'Final product name contains "' + rule.pattern + '"';
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'suggestion';
      remove.textContent = 'Remove';
      remove.addEventListener('click', function () {
        abvRules = abvRules.filter(function (r) { return abvKey(r) !== abvKey(rule); });
        abvRender(); abvSetStatus('Unsaved changes');
      });
      item.appendChild(label); item.appendChild(remove); list.appendChild(item);
    });
    list.hidden = !list.children.length;
  }
  function abvLoad(body) {
    abvRules = (body.rules || []).map(function (rule) { return { pattern: rule.pattern, match_type: rule.match_type }; });
    abvCandidates = body.candidates || [];
    profileSettings.abv_product_rules = abvRules.slice();
    abvRender();
  }
  if (abvRoot) {
    fetch('/api/compliant/nz-alcohol/abv-rules').then(function (response) { return response.json().then(function (body) { if (!response.ok) throw new Error(body.error || 'Could not load ABV rules'); return body; }); }).then(abvLoad).catch(function (err) { abvShowError(err.message); });
    abvRoot.querySelector('[data-abv-contains-form]').addEventListener('submit', function (event) {
      event.preventDefault();
      var input = event.target.pattern;
      var pattern = input.value.trim();
      if (!pattern) return;
      var rule = { pattern: pattern, match_type: 'contains' };
      if (!abvRules.some(function (r) { return abvKey(r) === abvKey(rule); })) abvRules.push(rule);
      input.value = '';
      abvRender(); abvSetStatus('Unsaved changes');
    });
    abvRoot.querySelector('[data-abv-save]').addEventListener('click', function () {
      abvShowError(''); abvSetStatus('Saving…');
      fetch('/api/compliant/nz-alcohol/abv-rules', { method: 'PUT', headers: csrfHeaders(), body: JSON.stringify({ rules: abvRules }) }).then(function (response) { return response.json().then(function (body) { if (!response.ok) throw new Error(body.error || 'Could not save ABV rules'); return body; }); }).then(function (body) { abvLoad(body); abvSetStatus('Saved'); }).catch(function (err) { abvSetStatus(''); abvShowError(err.message); }); // nosemgrep: raw-fetch-post
    });
  }
})();
