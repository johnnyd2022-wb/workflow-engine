/**
 * Node unit tests: refreshExecutionModalInventory lifecycle (CI via pytest → node --test).
 * Run: node --test tests/js/execution-modal-inventory-refresh.test.js
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const secondaryPath = path.join(
  __dirname,
  '..',
  '..',
  'app',
  'core',
  'frontend',
  'js',
  'execution-modal-secondary.js'
);

test('refreshExecutionModalInventory clears picker caches before querying .execute-inventory-select', async () => {
  const previousWindow = global.window;
  const previousDocument = global.document;
  const previousAddInvCtx = global.addInventoryContext;
  const previousExecRI = global.ExecutionRenderInputs;
  const previousLocation = global.location;
  const previousExecModalSecondary = global.ExecutionModalSecondary;
  const previousInventoryDisplay = global.InventoryDisplay;

  try {
    global.window = global;
    global.location = { origin: 'http://localhost', pathname: '/core/x', search: '' };

    let clearCalls = 0;
    let selectQueryCalls = 0;

    const modal = {
      style: { display: 'block' },
      dataset: { executionId: 'exec-1' },
      querySelectorAll(sel) {
        if (sel === '.execute-inventory-select') {
          selectQueryCalls++;
          assert.equal(
            clearCalls,
            1,
            'ExecutionRenderInputs.clearInventoryPickerCardCaches must run before modal.querySelectorAll(.execute-inventory-select)'
          );
        }
        return [];
      },
      querySelector() {
        return null;
      },
    };

    global.document = {
      readyState: 'complete',
      body: { classList: { contains: () => false } },
      getElementById(id) {
        if (id === 'execute-step-modal') return modal;
        if (id === 'add-untracked-output-form') return null;
        return null;
      },
      addEventListener() {},
    };

    global.ExecutionRenderInputs = {
      clearInventoryPickerCardCaches(el) {
        assert.strictEqual(el, modal);
        clearCalls++;
      },
    };

    // The module IIFE binds to root = global.window = global, so exports land on
    // global rather than module.exports. Access them via global, not the require result.
    delete require.cache[require.resolve(secondaryPath)];
    require(secondaryPath);
    global.InventoryDisplay = {
      formatTriggerLabel: function () {
        return '';
      },
    };

    global.ExecutionModalSecondary.install({
      CoreAPI: {
        getInventory: async function () {
          return { inventory_items: [] };
        },
      },
    });

    global.addInventoryContext = { fromExecutionModal: true };

    await global.refreshExecutionModalInventory(null);

    assert.equal(clearCalls, 1, 'clearInventoryPickerCardCaches should run exactly once');
    assert.equal(selectQueryCalls, 1, 'inventory select query should run after clear');
  } finally {
    global.window = previousWindow;
    global.document = previousDocument;
    global.addInventoryContext = previousAddInvCtx;
    global.ExecutionRenderInputs = previousExecRI;
    global.location = previousLocation;
    global.ExecutionModalSecondary = previousExecModalSecondary;
    global.InventoryDisplay = previousInventoryDisplay;
    delete require.cache[require.resolve(secondaryPath)];
  }
});
