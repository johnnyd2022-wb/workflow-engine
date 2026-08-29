/**
 * Node tests for the Compliant Tools pure render/serialise helpers.
 * Covers spec .agents/specs/compliant_tools.md AC16.
 * Run: node --test tests/js/compliant-tools-render.test.js
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

const R = require(
  path.join(__dirname, '..', '..', 'app', 'features', 'compliant', 'frontend', 'static', 'tools-render.js')
);
const CATALOGUE = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'fixtures', 'compliant_tools_catalogue.json'), 'utf8')
);
const byKey = {};
CATALOGUE.calculators.forEach((c) => { byKey[c.key] = c; });

const TIER1 = [
  'dilution', 'lal', 'standard_drinks', 'abv_abw', 'gravity_convert',
  'abv_from_og_fg', 'tank_volume', 'yield_loss', 'yeast_pitch', 'keg_fill',
];

// Pinned fixture input -> expected POST body, and a representative solver output.
const FIX = {
  dilution: {
    values: { solve_for: 'final_volume_ml', starting_abv: '40', starting_volume_ml: '1000', final_abv: '20' },
    payload: { solve_for: 'final_volume_ml', starting_abv: 40, starting_volume_ml: 1000, final_abv: 20 },
    result: { solved_field: 'final_volume_ml', solved_value: 2000, water_to_add_ml: 1000, disclaimer: 'Verify against a hydrometer.' },
  },
  lal: {
    values: { volume_l: '100', abv_pct: '40', lal: '' },
    payload: { volume_l: 100, abv_pct: 40 },
    result: { solved_field: 'lal', lal: 40, disclaimer: 'Operational estimate; confirm with NZ Customs.', sources: ['NZ Customs'] },
  },
  standard_drinks: {
    values: { solve_for: 'standard_drinks', volume_ml: '330', abv_pct: '5', standard_drinks: '' },
    payload: { solve_for: 'standard_drinks', volume_ml: 330, abv_pct: 5 },
    result: { standard_drinks: 1.302246, disclaimer: 'Verify per the Food Standards Code.', sources: ['FSANZ 2.7.1'] },
  },
  abv_abw: {
    values: { solve_for: 'abw_pct', abv_pct: '40', abw_pct: '', solution_sg: '0.9352' },
    payload: { solve_for: 'abw_pct', abv_pct: 40, solution_sg: 0.9352 },
    result: { abw_pct: 33.7571, disclaimer: 'Use a measured method for tax ABV.', sources: ['OIML R22'] },
  },
  gravity_convert: {
    values: { sg: '1.048', plato: '', brix: '', baume: '' },
    payload: { sg: 1.048 },
    result: { sg: 1.048, plato: 11.91, disclaimer: 'Brix is an approximation of Plato.', sources: ['ASBC'] },
  },
  abv_from_og_fg: {
    values: { og_sg: '1.050', fg_sg: '1.010' },
    payload: { og_sg: 1.05, fg_sg: 1.01 },
    result: { abv_pct: 5.25, apparent_attenuation_pct: 80, disclaimer: 'The 131.25 approximation; use a measured method.', sources: ['Palmer'] },
  },
  tank_volume: {
    values: { diameter_m: '1.0', cyl_height_m: '2.0', cone_height_m: '0.3', fill_height_m: '1.3' },
    payload: { diameter_m: 1, cyl_height_m: 2, cone_height_m: 0.3, fill_height_m: 1.3 },
    result: { capacity_l: 1649.336, filled_l: 863.938, disclaimer: 'Nominal geometry; ignores fittings.', sources: ['geometry'] },
  },
  yield_loss: {
    values: { start_volume_l: '1000', steps: [
      { name: 'brewhouse', loss_pct: '8', loss_l: '' },
      { name: 'fermentation', loss_pct: '5', loss_l: '' },
      { name: 'packaging', loss_pct: '2', loss_l: '' },
    ] },
    payload: { start_volume_l: 1000, steps: [
      { name: 'brewhouse', loss_pct: 8 },
      { name: 'fermentation', loss_pct: 5 },
      { name: 'packaging', loss_pct: 2 },
    ] },
    result: {
      final_volume_l: 856.52, total_loss_l: 143.48, effective_yield_pct: 85.652,
      per_step: [{ name: 'brewhouse', remaining_l: 920 }],
      disclaimer: 'Planning estimate; losses vary.', sources: ['arithmetic'],
    },
  },
  yeast_pitch: {
    values: { volume_l: '20', gravity_plato: '12', pitch_rate_m_per_ml_per_p: '1.0', pack_billion: '' },
    payload: { volume_l: 20, gravity_plato: 12, pitch_rate_m_per_ml_per_p: 1 },
    result: { cells_required_billion: 240, packs: 3, disclaimer: 'Assumes 100% viability; use a starter.', sources: ['White and Zainasheff, Yeast'] },
  },
  keg_fill: {
    values: { available_l: '1000', keg_size_l: '50', fill_loss_pct: '2' },
    payload: { available_l: 1000, keg_size_l: 50, fill_loss_pct: 2 },
    result: { full_kegs: 19, packaged_l: 950, loss_l: 19, remainder_l: 31, disclaimer: 'Estimate; fill loss varies.', sources: ['arithmetic'] },
  },
};

test('every Tier-1 calculator is in the catalogue with a fixture', () => {
  assert.deepEqual(
    CATALOGUE.calculators.map((c) => c.key).sort(),
    TIER1.slice().sort()
  );
  TIER1.forEach((k) => assert.ok(FIX[k], `missing fixture for ${k}`));
});

for (const key of TIER1) {
  test(`${key}: buildFormFields covers exactly the catalogue inputs`, () => {
    const entry = byKey[key];
    const fields = R.buildFormFields(entry);
    const names = fields.map((f) => f.name);
    const expected = [];
    if (entry.solve && entry.solve.field) expected.push(entry.solve.field);
    expected.push(...Object.keys(entry.inputs));
    assert.deepEqual(names, expected);

    const targets = [];
    if (entry.solve && entry.solve.field) targets.push.apply(targets, entry.solve.enum);
    if (entry.solve && entry.solve.one_omitted_of) targets.push.apply(targets, entry.solve.one_omitted_of);
    if (entry.solve && entry.solve.one_provided_of) targets.push.apply(targets, entry.solve.one_provided_of);
    fields.forEach((f) => {
      if (f.name === 'solve_for') return;
      assert.equal(f.is_solve_target, targets.indexOf(f.name) !== -1, `${key}.${f.name} solve-target flag`);
      assert.equal(f.type, entry.inputs[f.name].type);
      assert.equal(f.required, !!entry.inputs[f.name].required);
    });
  });

  test(`${key}: buildPayload from the pinned fixture input`, () => {
    assert.deepEqual(R.buildPayload(byKey[key], FIX[key].values), FIX[key].payload);
  });

  test(`${key}: solveUrl`, () => {
    assert.equal(R.solveUrl(byKey[key]), `/api/compliant/tools/${key}/solve`);
  });

  test(`${key}: renderResult shows values, disclaimer and sources`, () => {
    const res = FIX[key].result;
    const html = R.renderResult(byKey[key], res);
    Object.keys(res).forEach((k) => {
      if (k === 'disclaimer' || k === 'sources' || k === 'solved_field' || k === 'per_step') return;
      const v = res[k];
      const shown = Number.isInteger(v) ? String(v) : v.toLocaleString('en-NZ', { maximumFractionDigits: 4 });
      assert.ok(html.includes(shown), `${key}: result html missing ${k}=${shown}`);
    });
    assert.ok(html.includes(res.disclaimer), `${key}: missing disclaimer`);
    (res.sources || []).forEach((s) => assert.ok(html.includes(s), `${key}: missing source ${s}`));
  });
}

test('renderError echoes the message', () => {
  assert.ok(R.renderError('bad input').includes('bad input'));
});
