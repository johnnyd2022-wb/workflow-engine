/**
 * Node unit tests for the CRM configuration page's Product Mappings form.
 * Run: node --test tests/js/crm-configuration.test.js
 *
 * configuration.js declares a global `crmConfiguration()` Alpine factory, so it is loaded into a
 * vm sandbox with a stub CRMAPI. Bug under test: "Save mappings" appeared to do nothing when the
 * user had typed a phrase but not clicked "Add to review" first (the button was disabled until a
 * mapping was queued), and failures surfaced in a banner at the top of the page, out of view.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const vm = require('node:vm');

const SRC = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'features', 'crm', 'frontend', 'js', 'configuration.js'),
  'utf8'
);

function makePage({ createProductMappings, updateTraceabilityConfig } = {}) {
  const calls = { created: [], traceConfig: [] };
  const CRMAPI = {
    ensureBackButton() {},
    createProductMappings:
      createProductMappings ||
      (async (body) => {
        calls.created.push(body);
        return { product_mappings: body.mappings.map((m, i) => ({ id: `m${i}`, ...m })) };
      }),
    updateTraceabilityConfig:
      updateTraceabilityConfig ||
      (async (body) => {
        calls.traceConfig.push(body);
        return { matching_strategy: 'fifo', matching_key: 'batch_id', manual_review_days: 7, ...body };
      }),
  };
  const context = vm.createContext({ CRMAPI, window: {}, console });
  vm.runInContext(SRC, context);
  const page = context.crmConfiguration();
  page.finalProducts = [{ name: 'Wildflower - final product', source_output_id: 'out-1' }];
  return { page, calls };
}

function fillDraft(page, overrides = {}) {
  page.mappingDraft = {
    product_key: 'out-1||Wildflower - final product',
    xero_description_pattern: 'Wildflower',
    match_type: 'contains',
    notes: '',
    ...overrides,
  };
}

test('Save mappings with a completed draft and nothing queued saves the draft instead of doing nothing', async () => {
  const { page, calls } = makePage();
  fillDraft(page);

  await page.saveMappings();

  assert.equal(calls.created.length, 1, 'the draft mapping must be posted');
  assert.equal(calls.created[0].mappings[0].xero_description_pattern, 'Wildflower');
  assert.equal(calls.created[0].mappings[0].match_type, 'contains');
  assert.equal(page.mappings.length, 1);
  assert.equal(page.pendingMappings.length, 0);
  assert.equal(page.mappingDraft.xero_description_pattern, '', 'form is cleared after a save');
});

test('Save mappings is enabled for a complete draft or a non-empty review list, and only then', () => {
  const { page } = makePage();
  assert.equal(page.canSaveMappings, false, 'empty form has nothing to save');

  fillDraft(page, { xero_description_pattern: '   ' });
  assert.equal(page.canSaveMappings, false, 'a blank phrase is not saveable');

  fillDraft(page);
  assert.equal(page.canSaveMappings, true);

  page.mappingDraft = { product_key: '', xero_description_pattern: '', match_type: 'exact', notes: '' };
  page.pendingMappings = [{ biz_e_product_name: 'x', xero_description_pattern: 'y', match_type: 'exact' }];
  assert.equal(page.canSaveMappings, true, 'queued mappings alone are saveable');
});

test('a phrase differing only in case is treated as a duplicate and reported next to the form', () => {
  const { page } = makePage();
  fillDraft(page, { xero_description_pattern: 'Wildflower' });
  page.queueMapping();
  fillDraft(page, { xero_description_pattern: 'wildflower' });
  page.queueMapping();

  assert.equal(page.pendingMappings.length, 1, 'the server rejects case-insensitive duplicates, so the UI must too');
  assert.match(page.mappingError, /already/i);
});

test('a duplicate draft blocks Save mappings without posting anything', async () => {
  const { page, calls } = makePage();
  page.mappings = [
    { id: 'existing', biz_e_product_name: 'Wildflower - final product', xero_description_pattern: 'Wildflower' },
  ];
  fillDraft(page, { xero_description_pattern: 'WILDFLOWER' });

  await page.saveMappings();

  assert.equal(calls.created.length, 0);
  assert.match(page.mappingError, /already/i);
});

test('a failed save is reported next to the form and keeps the draft so it can be retried', async () => {
  const { page } = makePage({
    createProductMappings: async () => {
      throw new Error('This mapping already exists');
    },
  });
  fillDraft(page);

  await page.saveMappings();

  assert.equal(page.mappingError, 'This mapping already exists');
  assert.equal(page.savingMapping, false);
  assert.equal(page.pendingMappings.length, 1, 'the queued mapping is kept for a retry');
});

test('saving a partial-match mapping turns off exact-only matching first', async () => {
  const { page, calls } = makePage();
  page.traceConfig.strict = true;
  fillDraft(page);

  await page.saveMappings();

  assert.equal(calls.traceConfig.length, 1);
  assert.equal(calls.traceConfig[0].strict_mapping, false);
  assert.equal(calls.created.length, 1);
});

test('a successful save clears any earlier mapping error', async () => {
  const { page } = makePage();
  page.mappingError = 'stale';
  fillDraft(page);

  await page.saveMappings();

  assert.equal(page.mappingError, null);
});

test('saving configuration sends the tenant sales-figure obfuscation preference', async () => {
  const { page, calls } = makePage();
  page.traceConfig.obfuscate_sales_figures = true;

  await page.saveTraceConfig();

  assert.equal(calls.traceConfig.length, 1);
  assert.equal(calls.traceConfig[0].obfuscate_sales_figures, true);
  assert.equal(page.traceConfig.obfuscate_sales_figures, true);
});
