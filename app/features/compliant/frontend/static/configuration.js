(function () {
  'use strict';
  var root = document.querySelector('[data-compliant-configuration-root]');
  if (!root) return;
  var form = root.querySelector('[data-configuration-form]'); var error = root.querySelector('[data-configuration-error]');
  function csrfHeaders() { var token = document.querySelector('meta[name="csrf-token"]'); return { 'Content-Type': 'application/json', 'X-CSRFToken': token ? token.content : '' }; }
  function showError(message) { error.textContent = message || ''; error.hidden = !message; }
  function selected(name) { return Array.prototype.map.call(form.querySelectorAll('input[name="' + name + '"]:checked'), function (input) { return input.value; }); }
  function populate(overview) {
    var profile = overview.profile || {}; var settings = profile.settings || {}; form.enabled.checked = Boolean(profile.enabled);
    form.food_control_programme.value = settings.food_control_programme || 'np3'; form.liquor_licence_reference.value = settings.liquor_licence_reference || ''; form.liquor_licence_due_date.value = settings.liquor_licence_due_date || '';
    form.np3_verification_date.value = settings.np3_verification_date || ''; form.np3_verifier_name.value = settings.np3_verifier_name || ''; form.np3_verification_location.value = settings.np3_verification_location || '';
    form.council_name.value = profile.council_name || ''; form.consent.value = profile.trade_waste_consent_reference || ''; form.require_core_source_refs.checked = Boolean(settings.require_core_source_refs);
    Array.prototype.forEach.call(form.querySelectorAll('input[name="product_type"]'), function (input) { input.checked = (settings.alcohol_product_types || []).includes(input.value); });
    Array.prototype.forEach.call(form.querySelectorAll('input[name="liquor_licence_type"]'), function (input) { input.checked = (settings.liquor_licence_types || []).includes(input.value); });
    var council = form.querySelector('[data-trade-waste-council]'); (overview.trade_waste_catalogues || []).forEach(function (item) { var option = document.createElement('option'); option.value = item.slug; option.textContent = item.name; council.appendChild(option); }); council.value = settings.trade_waste_council || '';
  }
  fetch('/api/compliant/overview').then(function (response) { return response.json().then(function (body) { if (!response.ok) throw new Error(body.error || 'Could not load configuration'); return body; }); }).then(populate).catch(function (err) { showError(err.message); });
  form.addEventListener('submit', function (event) { event.preventDefault(); var licenceTypes = selected('liquor_licence_type'); var productTypes = selected('product_type'); var council = form.trade_waste_council.value || null;
    var payload = { enabled: form.enabled.checked, industry_module: 'nz_alcohol', council_name: form.council_name.value || null, trade_waste_consent_reference: form.consent.value || null, settings: { alcohol_product_types: productTypes, food_control_programme: form.food_control_programme.value, liquor_licence_types: licenceTypes, liquor_licence_reference: form.liquor_licence_reference.value || null, liquor_licence_due_date: form.liquor_licence_due_date.value || null, np3_verification_date: form.np3_verification_date.value || null, np3_verifier_name: form.np3_verifier_name.value || null, np3_verification_location: form.np3_verification_location.value || null, trade_waste_council: council, trade_waste_required: Boolean(council || form.consent.value), require_core_source_refs: form.require_core_source_refs.checked } };
    fetch('/api/compliant/profile', { method: 'PUT', headers: csrfHeaders(), body: JSON.stringify(payload) }).then(function (response) { return response.json().then(function (body) { if (!response.ok) throw new Error(body.error || 'Could not save configuration'); return body; }); }).then(function () { showError(''); }).catch(function (err) { showError(err.message); });
  });
})();
