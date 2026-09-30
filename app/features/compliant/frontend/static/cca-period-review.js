// Read-only source-CCA review; totals and nil/lodgement remain unresolved on the server.
(function () {
  'use strict';

  function node(tag, text) {
    var element = document.createElement(tag);
    element.textContent = text;
    return element;
  }

  async function getJson(url) {
    var response = await fetch(url, { credentials: 'include', headers: { Accept: 'application/json' } });
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The CCA review could not be loaded');
    return data;
  }

  function render(output, review) {
    output.replaceChildren();
    output.append(node('h3', review.source_cca.number + ' · ' + review.source_cca.name));
    output.append(node('p', 'Observed producer excise due: $' + Number(review.observed_excise_duty).toFixed(2) +
      '. This is not total duty, paid duty, or a lodged entry.'));
    if (!review.movements.length) output.append(node('p', 'No recognised movements for this CCA in the selected period. A nil return cannot be inferred.'));
    var list = node('ul', '');
    review.movements.forEach(function (movement) {
      var description = movement.occurred_on + ' · ' + movement.quantity + ' ' + movement.unit + ' · ' +
        (movement.treatment === 'recorded_excise_unpaid_transfer' ? 'CCA transfer without duty' : 'Producer home removal, excise due') +
        ' · consignment ' + movement.consignment_reference;
      list.append(node('li', description));
    });
    if (review.movements.length) output.append(list);
    output.append(node('p', review.unassigned_movements.length + ' movement(s) have unresolved source/accounting and may belong to this CCA. ' +
      review.other_source_cca_count + ' other source CCA(s) have recognised movements in this period.'));
    var gaps = node('ul', '');
    review.remaining_sources.forEach(function (source) { gaps.append(node('li', source)); });
    output.append(node('h4', 'Still needed for a complete entry'), gaps);
  }

  async function init() {
    var root = document.querySelector('[data-cca-period-review]');
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    var form = root.querySelector('[data-cca-period-form]');
    var output = root.querySelector('[data-cca-period-results]');
    var select = form.elements.licence_id;
    var today = new Date();
    var start = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1));
    var end = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() + 1, 1));
    form.elements.start.value = start.toISOString().slice(0, 10);
    form.elements.end.value = end.toISOString().slice(0, 10);
    try {
      var premises = await getJson('/api/compliant/nz-alcohol/premises');
      (premises.licences || []).filter(function (licence) { return licence.kind === 'lma' || licence.kind === 'oss'; })
        .forEach(function (licence) {
          var option = node('option', licence.number + ' · ' + licence.name);
          option.value = licence.id;
          select.append(option);
        });
      if (!select.options.length) output.append(node('p', 'Add an LMA or OSS licence before reviewing CCA movements.'));
    } catch (error) { output.append(node('p', error.message)); }
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      output.replaceChildren(node('p', 'Loading CCA movements…'));
      var query = new URLSearchParams({ licence_id: select.value, start: form.elements.start.value, end: form.elements.end.value });
      try { render(output, await getJson('/api/compliant/nz-alcohol/excise/cca-period-review?' + query.toString())); }
      catch (error) { output.replaceChildren(node('p', error.message)); }
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  document.addEventListener('htmx:afterSwap', init);
})();
