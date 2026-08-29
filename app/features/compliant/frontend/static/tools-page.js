/**
 * Compliant Tools page controller.
 *
 * Form fields are rendered server-side from the catalogue (tools.html); this script only
 * (a) wires each form's submit to its solve endpoint and renders the result via
 * tools-render.js, and (b) handles "add row" for array fields (yield_loss steps).
 */
(function () {
  'use strict';
  var R = window.CompliantToolsRender;
  var root = document.querySelector('[data-compliant-tools-root]');
  if (!R || !root || root.dataset.bound === '1') return;
  root.dataset.bound = '1';

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function readArrayField(form, name) {
    var group = form.querySelector('[data-array-field="' + name + '"]');
    if (!group) return undefined;
    return Array.prototype.map.call(group.querySelectorAll('.ct-array-row'), function (row) {
      var obj = {};
      Array.prototype.forEach.call(row.querySelectorAll('[data-item]'), function (el) {
        obj[el.dataset.item] = el.value;
      });
      return obj;
    });
  }

  function wireArrayAdd(form) {
    Array.prototype.forEach.call(form.querySelectorAll('.ct-array-add'), function (btn) {
      btn.addEventListener('click', function () {
        var group = btn.closest('[data-array-field]');
        var rows = group.querySelector('[data-rows]');
        var template = rows.querySelector('.ct-array-row');
        var clone = template.cloneNode(true);
        Array.prototype.forEach.call(clone.querySelectorAll('input, select'), function (el) {
          el.value = '';
        });
        rows.appendChild(clone);
      });
    });
  }

  function wireForm(form) {
    var key = form.dataset.calculator;
    var entry = (window.__compliantToolsCatalogue || {})[key];
    var resultEl = form.parentNode.querySelector('[data-result]');
    wireArrayAdd(form);

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var values = {};
      Array.prototype.forEach.call(form.querySelectorAll('input, select'), function (el) {
        if (el.type === 'submit' || el.closest('.ct-array-row')) return;
        values[el.name] = el.value;
      });
      if (entry) {
        Object.keys(entry.inputs).forEach(function (name) {
          if (entry.inputs[name].type === 'array') values[name] = readArrayField(form, name);
        });
      }
      var payload = entry ? R.buildPayload(entry, values) : values;
      resultEl.innerHTML = '<p class="ct-loading">Calculating…</p>';
      fetch('/api/compliant/tools/' + key + '/solve', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
        body: JSON.stringify(payload),
      })
        .then(function (res) {
          return res.json().then(function (body) {
            resultEl.innerHTML = res.ok
              ? R.renderResult(entry || { inputs: {} }, body)
              : R.renderError(body.error);
          });
        })
        .catch(function () {
          resultEl.innerHTML = R.renderError('Network error — please try again');
        });
    });
  }

  Array.prototype.forEach.call(root.querySelectorAll('form[data-calculator]'), wireForm);
})();
