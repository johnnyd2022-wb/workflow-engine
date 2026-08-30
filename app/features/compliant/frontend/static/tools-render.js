/**
 * Pure render/serialise helpers for the Compliant Tools page.
 *
 * No DOM, no fetch, no globals touched — so `node --test` can require() this directly
 * (the repo has no jsdom). The page controller (tools-page.js) wires these to the DOM.
 *
 * Run: node --test tests/js/compliant-tools-render.test.js
 */
'use strict';

(function (root) {
  function humanize(name) {
    return name
      .replace(/_/g, ' ')
      .replace(/\bml\b/i, 'mL')
      .replace(/\bsg\b/i, 'SG')
      .replace(/\babv\b/i, 'ABV')
      .replace(/\babw\b/i, 'ABW')
      .replace(/\blal\b/i, 'LAL')
      .replace(/\bpct\b/i, '%')
      .replace(/^\w/, function (c) { return c.toUpperCase(); });
  }

  function solveTargetNames(entry) {
    var s = entry.solve;
    if (!s) return [];
    if (s.field) return s.enum.slice();
    if (s.one_omitted_of) return s.one_omitted_of.slice();
    if (s.one_provided_of) return s.one_provided_of.slice();
    return [];
  }

  /**
   * One descriptor per top-level `inputs` field, in declaration order.
   * Array fields carry `item_fields` (a nested list). `solve_for` is added as a
   * synthetic enum field when the calculator uses an explicit target.
   */
  function buildFormFields(entry) {
    var fields = [];
    var s = entry.solve;
    if (s && s.field) {
      fields.push({
        name: s.field,
        label: 'Solve for',
        type: 'enum',
        unit: null,
        required: false,
        options: s.enum.slice(),
        default: s.default,
        is_solve_target: false,
      });
    }
    var targets = solveTargetNames(entry);
    Object.keys(entry.inputs).forEach(function (name) {
      var d = entry.inputs[name];
      var field = {
        name: name,
        label: humanize(name) + (d.unit ? ' (' + d.unit + ')' : ''),
        type: d.type,
        unit: d.unit === undefined ? null : d.unit,
        required: !!d.required,
        is_solve_target: targets.indexOf(name) !== -1,
      };
      if (d.type === 'enum') field.options = (d.enum || []).slice();
      if ('default' in d) field.default = d.default;
      if (d.type === 'array') {
        field.item_fields = Object.keys(d.item_fields).map(function (itemName) {
          var id = d.item_fields[itemName];
          return {
            name: itemName,
            label: humanize(itemName) + (id.unit ? ' (' + id.unit + ')' : ''),
            type: id.type,
            unit: id.unit === undefined ? null : id.unit,
            required: !!id.required,
            parent: name,
          };
        });
        field.min_items = d.min_items;
        field.max_items = d.max_items;
      }
      fields.push(field);
    });
    return fields;
  }

  function solveUrl(entry) {
    return '/api/compliant/tools/' + entry.key + '/solve';
  }

  function coerce(raw) {
    if (raw === '' || raw === null || raw === undefined) return undefined;
    var n = Number(raw);
    return Number.isFinite(n) && String(raw).trim() !== '' ? n : raw;
  }

  /**
   * Assemble the POST body from raw string field values keyed by field name.
   * Array fields expect `values[name]` to already be an array of row objects.
   * Empty values are dropped (so an omitted `one_omitted_of` target stays omitted).
   */
  function buildPayload(entry, values) {
    var payload = {};
    var s = entry.solve;
    if (s && s.field && values[s.field]) payload[s.field] = values[s.field];

    Object.keys(entry.inputs).forEach(function (name) {
      var d = entry.inputs[name];
      var raw = values[name];
      if (d.type === 'array') {
        if (!Array.isArray(raw)) return;
        var rows = raw
          .map(function (row) {
            var out = {};
            Object.keys(d.item_fields).forEach(function (itemName) {
              var v = row[itemName];
              if (v === '' || v === null || v === undefined) return;
              out[itemName] = d.item_fields[itemName].type === 'text' ? String(v) : coerce(v);
            });
            return out;
          })
          .filter(function (row) { return Object.keys(row).length > 0; });
        if (rows.length) payload[name] = rows;
        return;
      }
      var c = coerce(raw);
      if (c !== undefined) payload[name] = c;
    });
    return payload;
  }

  function esc(v) {
    return String(v)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatNumber(n) {
    if (typeof n !== 'number') return esc(n);
    return Number.isInteger(n) ? String(n) : n.toLocaleString('en-NZ', { maximumFractionDigits: 4 });
  }

  var META_KEYS = { disclaimer: 1, sources: 1, solved_field: 1, per_step: 1 };

  function renderResult(entry, result) {
    var rows = [];
    Object.keys(result).forEach(function (key) {
      if (META_KEYS[key]) return;
      rows.push(
        '<div class="ct-result-row"><span class="ct-result-label">' +
          esc(humanize(key)) +
          '</span><span class="ct-result-value">' +
          formatNumber(result[key]) +
          '</span></div>'
      );
    });
    if (Array.isArray(result.per_step)) {
      result.per_step.forEach(function (step) {
        rows.push(
          '<div class="ct-result-row ct-result-substep"><span class="ct-result-label">' +
            esc(step.name) +
            '</span><span class="ct-result-value">' +
            formatNumber(step.remaining_l) +
            ' L</span></div>'
        );
      });
    }
    var disclaimer = result.disclaimer
      ? '<p class="ct-disclaimer">' + esc(result.disclaimer) + '</p>'
      : '';
    var sources =
      Array.isArray(result.sources) && result.sources.length
        ? '<ul class="ct-sources">' +
          result.sources.map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') +
          '</ul>'
        : '';
    return '<div class="ct-result">' + rows.join('') + disclaimer + sources + '</div>';
  }

  function renderError(message) {
    return '<div class="ct-error" role="alert">' + esc(message || 'Calculation failed') + '</div>';
  }

  var api = {
    humanize: humanize,
    buildFormFields: buildFormFields,
    buildPayload: buildPayload,
    solveUrl: solveUrl,
    renderResult: renderResult,
    renderError: renderError,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.CompliantToolsRender = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
