(function () {
  'use strict';
  var root = document.querySelector('[data-compliant-configuration-root]');
  if (!root) return;

  // Each section is its own form and saves only itself: the saved profile with that section's
  // fields on top. The whole page used to be one form with one Save.
  var NAMES = ['workspace', 'products', 'food', 'visit', 'licence', 'tradeWaste', 'evidence', 'abv'];

  var saved = { enabled: false, council_name: '', consent: '', settings: {} };
  var councils = [];
  var abv = { saved: [], draft: [], candidates: [] };
  var stack = root.querySelector('[data-cs-stack]');
  var loadError = root.querySelector('[data-configuration-error]');

  function section(name) { return root.querySelector('[data-cs-section="' + name + '"]'); }
  function form(name) { return section(name).querySelector('[data-cs-form]'); }
  function csrfHeaders() { var token = document.querySelector('meta[name="csrf-token"]'); return { 'Content-Type': 'application/json', 'X-CSRFToken': token ? token.content : '' }; }
  function json(response, fallback) { return response.json().catch(function () { return {}; }).then(function (body) { if (!response.ok) throw new Error(body.error || fallback); return body; }); }
  function ticked(f, name) { return Array.prototype.filter.call(f.querySelectorAll('input[name="' + name + '"]'), function (input) { return input.checked; }).map(function (input) { return input.value; }); }
  function tick(f, name, values) { Array.prototype.forEach.call(f.querySelectorAll('input[name="' + name + '"]'), function (input) { input.checked = values.indexOf(input.value) !== -1; }); }
  function radio(f, name, value) { Array.prototype.forEach.call(f.querySelectorAll('input[name="' + name + '"]'), function (input) { input.checked = input.value === value; }); }
  function chosen(f, name) { var input = f.querySelector('input[name="' + name + '"]:checked'); return input ? input.value : ''; }
  // What a section's form says now, and what is saved, in the same shape.
  function values(name, s) {
    var settings = s.settings;
    return {
      workspace: function () { return { enabled: Boolean(s.enabled) }; },
      products: function () { return { alcohol_product_types: (settings.alcohol_product_types || []).slice().sort() }; },
      food: function () { return { food_control_programme: settings.food_control_programme || 'np3', np3_review_interval_months: Number(settings.np3_review_interval_months || 6), np3_execution_evidence_mode: settings.np3_execution_evidence_mode || 'recommended' }; },
      visit: function () { return { np3_verification_date: settings.np3_verification_date || '', np3_verifier_name: settings.np3_verifier_name || '', np3_verification_location: settings.np3_verification_location || '' }; },
      licence: function () { return { liquor_licence_types: (settings.liquor_licence_types || []).slice().sort(), liquor_licence_reference: settings.liquor_licence_reference || '', liquor_licence_due_date: settings.liquor_licence_due_date || '' }; },
      tradeWaste: function () { return { trade_waste_council: settings.trade_waste_council || '', council_name: s.council_name || '', consent: s.consent || '' }; },
      evidence: function () { return { require_core_source_refs: Boolean(settings.require_core_source_refs) }; },
    }[name]();
  }
  function draft(name) {
    var f = form(name);
    return {
      workspace: function () { return { enabled: f.enabled.checked }; },
      products: function () { return { alcohol_product_types: ticked(f, 'product_type').sort() }; },
      food: function () { return { food_control_programme: f.food_control_programme.value, np3_review_interval_months: Number(f.np3_review_interval_months.value), np3_execution_evidence_mode: chosen(f, 'np3_execution_evidence_mode') || 'recommended' }; },
      visit: function () { return { np3_verification_date: f.np3_verification_date.value, np3_verifier_name: f.np3_verifier_name.value.trim(), np3_verification_location: f.np3_verification_location.value.trim() }; },
      licence: function () { return { liquor_licence_types: ticked(f, 'liquor_licence_type').sort(), liquor_licence_reference: f.liquor_licence_reference.value.trim(), liquor_licence_due_date: f.liquor_licence_due_date.value }; },
      tradeWaste: function () { return { trade_waste_council: f.trade_waste_council.value, council_name: f.council_name.value.trim(), consent: f.consent.value.trim() }; },
      evidence: function () { return { require_core_source_refs: f.require_core_source_refs.checked }; },
    }[name]();
  }
  function fill(name) {
    var f = form(name);
    if (name === 'abv') {
      abv.draft = abv.saved.map(function (rule) { return { pattern: rule.pattern, match_type: rule.match_type }; });
      renderAbv();
      return;
    }
    var v = values(name, saved);
    if (name === 'workspace') f.enabled.checked = v.enabled;
    if (name === 'products') tick(f, 'product_type', v.alcohol_product_types);
    if (name === 'food') { f.food_control_programme.value = v.food_control_programme; f.np3_review_interval_months.value = String(v.np3_review_interval_months); radio(f, 'np3_execution_evidence_mode', v.np3_execution_evidence_mode); }
    if (name === 'visit') { f.np3_verification_date.value = v.np3_verification_date; f.np3_verifier_name.value = v.np3_verifier_name; f.np3_verification_location.value = v.np3_verification_location; }
    if (name === 'licence') { tick(f, 'liquor_licence_type', v.liquor_licence_types); f.liquor_licence_reference.value = v.liquor_licence_reference; f.liquor_licence_due_date.value = v.liquor_licence_due_date; }
    if (name === 'tradeWaste') { f.trade_waste_council.value = v.trade_waste_council; f.council_name.value = v.council_name; f.consent.value = v.consent; }
    if (name === 'evidence') f.require_core_source_refs.checked = v.require_core_source_refs;
    showNpOnly();
  }
  // Food-safety-only fields follow the programme being chosen; the visit follows the saved one.
  function showNpOnly() {
    var programme = form('food').food_control_programme.value;
    section('food').querySelectorAll('[data-cs-np-only]').forEach(function (el) { el.hidden = programme === 'none'; });
    section('visit').hidden = (saved.settings.food_control_programme || 'np3') === 'none';
  }
  function updateFoodSafetyTab(programme) {
    document.querySelectorAll('[data-food-safety-tab]').forEach(function (tab) {
      if (tab.dataset.sectionTab === 'np3') tab.textContent = ['np1', 'np2', 'np3'].includes(programme) ? programme.toUpperCase() : 'Food safety';
      tab.hidden = programme === 'none';
    });
  }
  function updateLicensingTab(types) {
    document.querySelectorAll('[data-section-tab="licensing"]').forEach(function (tab) { tab.hidden = !types.length; });
  }

  // ---- saving ---------------------------------------------------------------------------
  function payload(name) {
    var next = { enabled: saved.enabled, council_name: saved.council_name, consent: saved.consent, settings: Object.assign({}, saved.settings) };
    var d = draft(name);
    if (name === 'workspace') next.enabled = d.enabled;
    else if (name === 'tradeWaste') { next.settings.trade_waste_council = d.trade_waste_council || null; next.council_name = d.council_name; next.consent = d.consent; }
    else Object.keys(d).forEach(function (key) { next.settings[key] = d[key] === '' ? null : d[key]; });
    next.settings.trade_waste_required = Boolean(next.settings.trade_waste_council || next.consent);
    return {
      enabled: next.enabled,
      industry_module: 'nz_alcohol',
      council_name: next.council_name || null,
      trade_waste_consent_reference: next.consent || null,
      settings: next.settings,
    };
  }
  function adopt(profile) {
    saved = { enabled: Boolean(profile.enabled), council_name: profile.council_name || '', consent: profile.trade_waste_consent_reference || '', settings: profile.settings || {} };
    updateFoodSafetyTab(saved.settings.food_control_programme || 'np3');
    updateLicensingTab(saved.settings.liquor_licence_types || []);
  }
  function setNote(name, text) { section(name).querySelector('[data-cs-saved]').textContent = text || ''; }
  function setError(name, text) { var el = section(name).querySelector('[data-cs-error]'); el.textContent = text || ''; el.hidden = !text; }
  function saveSection(name) {
    setError(name, '');
    setNote(name, '');
    var button = section(name).querySelector('.cs-save');
    button.disabled = true;
    button.textContent = 'Saving…';
    var request = name === 'abv'
      ? fetch('/api/compliant/nz-alcohol/abv-rules', { method: 'PUT', headers: csrfHeaders(), body: JSON.stringify({ rules: abv.draft }) }).then(function (r) { return json(r, 'Could not save ABV rules'); }).then(abvLoad) // nosemgrep: raw-fetch-post
      : fetch('/api/compliant/profile', { method: 'PUT', headers: csrfHeaders(), body: JSON.stringify(payload(name)) }).then(function (r) { return json(r, 'Could not save'); }).then(function (body) { adopt(body.profile || {}); }); // nosemgrep: raw-fetch-post
    return request.then(function () {
      // Only the saved section takes the new values; another section's unsaved edits stay put.
      fill(name);
      showNpOnly();
      setNote(name, 'Saved.');
      return true;
    }).catch(function (err) {
      setError(name, err.message);
      return false;
    }).then(function (ok) {
      button.disabled = false;
      button.textContent = 'Save';
      return ok;
    });
  }
  // ABV rules apply to workflow outputs; exact exclusions take priority over phrases.
  function abvKey(rule) { return rule.match_type + ':' + rule.pattern.trim().toLowerCase(); }
  function abvMatch(rules, name) {
    var lowered = String(name || '').trim().toLowerCase();
    if (!lowered) return null;
    var exact = rules.find(function (rule) { return rule.match_type === 'exact' && rule.pattern.trim().toLowerCase() === lowered; });
    if (exact) return exact;
    return rules.find(function (rule) { return rule.match_type === 'contains' && lowered.indexOf(rule.pattern.trim().toLowerCase()) !== -1; }) || null;
  }
  function renderAbv() {
    var list = section('abv').querySelector('[data-abv-candidates]');
    list.textContent = '';
    if (!abv.candidates.length) {
      var empty = document.createElement('li');
      empty.className = 'cs-empty';
      empty.textContent = 'No workflows with a final product yet. Add one in Production, then come back.';
      list.appendChild(empty);
    }
    abv.candidates.forEach(function (candidate) {
      var item = document.createElement('li');
      var label = document.createElement('label');
      label.className = 'cs-abv';
      var box = document.createElement('input');
      box.type = 'checkbox';
      var hasExact = abv.draft.some(function (rule) { return rule.match_type === 'exact' && rule.pattern.trim().toLowerCase() === candidate.output_name.trim().toLowerCase(); });
      var byPhrase = !hasExact && abvMatch(abv.draft, candidate.output_name);
      // Covered by a phrase: ticked but locked. Untick by removing the phrase, or the box
      // would contradict what applies.
      box.checked = hasExact || Boolean(byPhrase);
      box.disabled = Boolean(byPhrase);
      box.addEventListener('change', function () {
        var rule = { pattern: candidate.output_name, match_type: 'exact' };
        if (box.checked) { if (!abv.draft.some(function (r) { return abvKey(r) === abvKey(rule); })) abv.draft.push(rule); }
        else abv.draft = abv.draft.filter(function (r) { return abvKey(r) !== abvKey(rule); });
        renderAbv();
      });
      var text = document.createElement('span');
      var name = document.createElement('strong');
      name.textContent = candidate.output_name;
      var where = document.createElement('small');
      where.textContent = candidate.process_name + (candidate.is_draft ? ' (draft)' : '') + ' · final step: ' + candidate.step_name + (byPhrase ? ' · covered by “' + byPhrase.pattern + '”' : '');
      text.appendChild(name);
      text.appendChild(where);
      label.appendChild(box);
      label.appendChild(text);
      item.appendChild(label);
      list.appendChild(item);
    });
    var phrases = section('abv').querySelector('[data-abv-rule-list]');
    phrases.textContent = '';
    abv.draft.filter(function (rule) { return rule.match_type === 'contains'; }).forEach(function (rule) {
      var item = document.createElement('li');
      var label = document.createElement('span');
      label.textContent = 'Name contains “' + rule.pattern + '”';
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'cs-link cs-link--danger';
      remove.textContent = 'Remove';
      remove.setAttribute('aria-label', 'Remove the phrase ' + rule.pattern);
      remove.addEventListener('click', function () {
        abv.draft = abv.draft.filter(function (r) { return abvKey(r) !== abvKey(rule); });
        renderAbv();
      });
      item.appendChild(label);
      item.appendChild(remove);
      phrases.appendChild(item);
    });
    phrases.hidden = !phrases.children.length;
  }
  function abvLoad(body) {
    abv.saved = (body.rules || []).map(function (rule) { return { pattern: rule.pattern, match_type: rule.match_type }; });
    abv.candidates = body.candidates || [];
    // Settings are replaced wholesale on a profile save, so the profile carries the rules too.
    saved.settings.abv_product_rules = abv.saved.slice();
  }
  function addPhrase() {
    var input = section('abv').querySelector('[data-abv-phrase]');
    var pattern = input.value.trim();
    if (!pattern) return;
    var rule = { pattern: pattern, match_type: 'contains' };
    if (!abv.draft.some(function (r) { return abvKey(r) === abvKey(rule); })) abv.draft.push(rule);
    input.value = '';
    renderAbv();
  }

  // ---- wiring -------------------------------------------------------------------------------
  NAMES.forEach(function (name) {
    form(name).addEventListener('submit', function (event) { event.preventDefault(); saveSection(name); });
    form(name).addEventListener('change', function () { showNpOnly(); });
  });
  section('abv').querySelector('[data-abv-add-phrase]').addEventListener('click', addPhrase);
  section('abv').querySelector('[data-abv-phrase]').addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); addPhrase(); } });
  root.querySelector('[data-cs-retry]').addEventListener('click', load);

  // Settings that failed to load are not shown, so their defaults can't be saved over the real ones.
  function load() {
    root.setAttribute('aria-busy', 'true');
    loadError.hidden = true;
    Promise.all([
      fetch('/api/compliant/overview').then(function (r) { return json(r, 'Compliance settings could not load.'); }),
      fetch('/api/compliant/nz-alcohol/abv-rules').then(function (r) { return json(r, 'ABV rules could not load.'); }),
    ]).then(function (results) {
      var overview = results[0];
      adopt(overview.profile || {});
      councils = overview.trade_waste_catalogues || [];
      var select = form('tradeWaste').trade_waste_council;
      select.length = 1;
      councils.forEach(function (item) { var option = document.createElement('option'); option.value = item.slug; option.textContent = item.name; select.appendChild(option); });
      abvLoad(results[1]);
      NAMES.forEach(function (name) { fill(name); });
      stack.hidden = false;
    }).catch(function (err) {
      stack.hidden = true;
      root.querySelector('[data-cs-load-message]').textContent = err.message;
      loadError.hidden = false;
    }).then(function () { root.setAttribute('aria-busy', 'false'); });
  }
  load();
})();
