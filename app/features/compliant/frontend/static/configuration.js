(function () {
  'use strict';
  var root = document.querySelector('[data-compliant-configuration-root]');
  if (!root) return;

  // Each section is its own form and saves only itself: the saved profile with that section's
  // fields on top. The whole page used to be one form with one Save.
  var NAMES = ['workspace', 'products', 'food', 'visit', 'licence', 'tradeWaste', 'evidence', 'abv'];
  var PRODUCTS = { spirits: 'Spirits', beer: 'Beer', wine: 'Wine or vineyard', cider: 'Cider', mead: 'Mead', rtd: 'RTDs' };
  var LICENCES = { on: 'On-licence', off: 'Off-licence', club: 'Club licence', special: 'Special licence' };
  var PROGRAMMES = { np1: 'National Programme 1', np2: 'National Programme 2', np3: 'National Programme 3', none: 'No national programme' };
  var INTERVALS = { 1: 'Every month', 3: 'Every 3 months', 6: 'Every 6 months', 12: 'Every year' };
  var EVIDENCE = { off: 'Off', recommended: 'Recommended: each step offers a place for a file', required: 'Required: a step needs a file to complete' };
  var LABELS = { workspace: 'NZ Alcohol', products: 'what leaves your site', food: 'food safety', visit: 'the verification visit', licence: 'the licence', tradeWaste: 'trade waste', evidence: 'evidence records', abv: 'ABV' };

  var saved = { enabled: false, council_name: '', consent: '', settings: {} };
  var councils = [];
  var abv = { saved: [], draft: [], candidates: [] };
  var stack = root.querySelector('[data-cs-stack]');
  var loadError = root.querySelector('[data-configuration-error]');
  var savebar = root.querySelector('[data-cs-savebar]');

  function section(name) { return root.querySelector('[data-cs-section="' + name + '"]'); }
  function form(name) { return section(name).querySelector('[data-cs-form]'); }
  function csrfHeaders() { var token = document.querySelector('meta[name="csrf-token"]'); return { 'Content-Type': 'application/json', 'X-CSRFToken': token ? token.content : '' }; }
  function json(response, fallback) { return response.json().catch(function () { return {}; }).then(function (body) { if (!response.ok) throw new Error(body.error || fallback); return body; }); }
  function ticked(f, name) { return Array.prototype.filter.call(f.querySelectorAll('input[name="' + name + '"]'), function (input) { return input.checked; }).map(function (input) { return input.value; }); }
  function tick(f, name, values) { Array.prototype.forEach.call(f.querySelectorAll('input[name="' + name + '"]'), function (input) { input.checked = values.indexOf(input.value) !== -1; }); }
  function radio(f, name, value) { Array.prototype.forEach.call(f.querySelectorAll('input[name="' + name + '"]'), function (input) { input.checked = input.value === value; }); }
  function chosen(f, name) { var input = f.querySelector('input[name="' + name + '"]:checked'); return input ? input.value : ''; }
  function dateWords(value) {
    if (!value) return '';
    var parts = value.split('-').map(Number);
    return new Date(parts[0], parts[1] - 1, parts[2]).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' });
  }
  // In the form's order, not the order they were ticked or sorted.
  function words(list, names) { return list.length ? Object.keys(names).filter(function (key) { return list.indexOf(key) !== -1; }).map(function (key) { return names[key]; }).join(', ') : 'None chosen'; }

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
  function isDirty(name) {
    if (name === 'abv') return abvKeys(abv.draft) !== abvKeys(abv.saved);
    return JSON.stringify(draft(name)) !== JSON.stringify(values(name, saved));
  }

  // The read-first rows (Style 3), from what is saved.
  function rows(name) {
    if (name === 'abv') {
      var required = abv.candidates.filter(function (candidate) { return abvMatch(abv.saved, candidate.output_name); }).map(function (candidate) { return candidate.output_name; });
      var phrases = abv.saved.filter(function (rule) { return rule.match_type === 'contains'; }).map(function (rule) { return '“' + rule.pattern + '”'; });
      return [['ABV required on', required.length ? required.join(', ') : 'None']].concat(phrases.length ? [['Phrases', phrases.join(', ')]] : []);
    }
    var v = values(name, saved);
    return {
      workspace: function () { return [['Compliance', v.enabled ? 'On' : 'Off']]; },
      products: function () { return [['Products', words(v.alcohol_product_types, PRODUCTS)]]; },
      food: function () {
        var list = [['Programme', PROGRAMMES[v.food_control_programme]]];
        if (v.food_control_programme !== 'none') list.push(['Review each signed check', INTERVALS[v.np3_review_interval_months]], ['Evidence on Production steps', EVIDENCE[v.np3_execution_evidence_mode]]);
        return list;
      },
      visit: function () {
        if (!v.np3_verification_date) return [['Visit', 'Not booked']];
        return [['Visit', dateWords(v.np3_verification_date)], ['Verifier', v.np3_verifier_name || 'Not set'], ['Where', v.np3_verification_location || 'Not set']];
      },
      licence: function () {
        return [['Kind', words(v.liquor_licence_types, LICENCES)], ['Reference', v.liquor_licence_reference || 'Not set'], ['Renewal or event', dateWords(v.liquor_licence_due_date) || 'Not set']];
      },
      tradeWaste: function () {
        var council = councils.find(function (item) { return item.slug === v.trade_waste_council; });
        return [['Council catalogue', council ? council.name : 'None'], ['Council or water provider', v.council_name || 'Not set'], ['Consent', v.consent || 'None yet']];
      },
      evidence: function () { return [['Linked Production record', v.require_core_source_refs ? 'Required on every record' : 'Optional']]; },
    }[name]();
  }
  function renderRead(name) {
    var dl = section(name).querySelector('[data-cs-read]');
    dl.textContent = '';
    rows(name).forEach(function (pair) {
      var row = document.createElement('div');
      row.className = 'cs-row';
      var dt = document.createElement('dt');
      dt.textContent = pair[0];
      var dd = document.createElement('dd');
      dd.textContent = pair[1];
      row.appendChild(dt);
      row.appendChild(dd);
      dl.appendChild(row);
    });
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
      NAMES.forEach(renderRead);
      showNpOnly();
      section(name).dataset.editing = 'false';
      setNote(name, 'Saved.');
      return true;
    }).catch(function (err) {
      setError(name, err.message);
      return false;
    }).then(function (ok) {
      button.disabled = false;
      button.textContent = 'Save';
      refreshBar();
      return ok;
    });
  }
  function discard(name) {
    fill(name);
    setError(name, '');
    section(name).dataset.editing = 'false';
    refreshBar();
  }
  function refreshBar() {
    var dirty = NAMES.filter(isDirty);
    savebar.hidden = !dirty.length;
    var list = dirty.map(function (name) { return LABELS[name]; });
    var text = list.length > 1 ? list.slice(0, -1).join(', ') + ' and ' + list[list.length - 1] : list.join('');
    root.querySelector('[data-cs-savebar-text]').textContent = 'Unsaved changes to ' + text;
  }

  // ---- ABV on alcohol products -------------------------------------------------------------
  // Rules match each workflow's final-step output names, case-insensitively, the same phrase +
  // exact/contains shape the CRM uses for Xero product mappings. A matched final step gets a
  // required "ABV (%)" field that Core enforces at completion.
  function abvKey(rule) { return rule.match_type + ':' + rule.pattern.trim().toLowerCase(); }
  function abvKeys(rules) { return rules.map(abvKey).sort().join('|'); }
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
        refreshBar();
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
        refreshBar();
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
    refreshBar();
  }

  // ---- layout switch (CONCEPT ONLY: deleted with the two layouts not picked) ---------------
  function setStyle(style) {
    root.dataset.csStyle = style;
    root.querySelectorAll('[data-cs-style-pick]').forEach(function (button) { button.setAttribute('aria-pressed', String(button.dataset.csStylePick === style)); });
    NAMES.forEach(function (name) { section(name).dataset.editing = 'false'; });
    try { window.localStorage.setItem('compliance-settings-style', style); } catch (_) { /* a convenience only */ }
  }
  (function () {
    var wanted = new URLSearchParams(window.location.search).get('style');
    var kept = null;
    try { kept = window.localStorage.getItem('compliance-settings-style'); } catch (_) { /* storage blocked */ }
    setStyle(['1', '2', '3'].includes(wanted) ? wanted : (['1', '2', '3'].includes(kept) ? kept : '1'));
  })();

  // ---- wiring -------------------------------------------------------------------------------
  NAMES.forEach(function (name) {
    var s = section(name);
    s.dataset.editing = 'false';
    form(name).addEventListener('submit', function (event) { event.preventDefault(); saveSection(name); });
    form(name).addEventListener('input', refreshBar);
    form(name).addEventListener('change', function () { showNpOnly(); refreshBar(); });
    s.querySelector('[data-cs-change]').addEventListener('click', function () { fill(name); setNote(name, ''); s.dataset.editing = 'true'; });
    s.querySelector('[data-cs-cancel]').addEventListener('click', function () { discard(name); });
  });
  section('abv').querySelector('[data-abv-add-phrase]').addEventListener('click', addPhrase);
  section('abv').querySelector('[data-abv-phrase]').addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); addPhrase(); } });
  root.querySelectorAll('[data-cs-style-pick]').forEach(function (button) { button.addEventListener('click', function () { setStyle(button.dataset.csStylePick); }); });
  root.querySelector('[data-cs-save-all]').addEventListener('click', function () {
    NAMES.filter(isDirty).reduce(function (chain, name) { return chain.then(function (ok) { return ok ? saveSection(name) : false; }); }, Promise.resolve(true));
  });
  root.querySelector('[data-cs-discard-all]').addEventListener('click', function () { NAMES.filter(isDirty).forEach(discard); });
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
      NAMES.forEach(function (name) { fill(name); renderRead(name); });
      stack.hidden = false;
      refreshBar();
    }).catch(function (err) {
      stack.hidden = true;
      root.querySelector('[data-cs-load-message]').textContent = err.message;
      loadError.hidden = false;
    }).then(function () { root.setAttribute('aria-busy', 'false'); });
  }
  load();
})();
