const test = require('node:test');
const assert = require('node:assert/strict');

global.window = global;
require('../../app/core/frontend/js/inventory-stock-summary.js');

const stock = global.InventoryStockSummary;

test('stock lines sum lots with matching name, type and unit only', () => {
  const groups = stock.group([
    { name: ' Juniper ', inventory_type: 'raw_material', unit: 'kg', quantity: '10' },
    { name: 'juniper', inventory_type: 'raw_material', unit: 'KG', quantity: '7.5' },
    { name: 'Juniper', inventory_type: 'raw_material', unit: 'L', quantity: '2' },
    { name: 'Juniper', inventory_type: 'final_product', unit: 'kg', quantity: '3' },
  ]);
  assert.equal(groups.length, 3);
  assert.equal(groups[0].total, 17.5);
  assert.equal(groups[0].lots.length, 2);
  assert.equal(stock.format(groups[0].total), '17.5');
});

test('non-finite or empty quantities do not inflate stock', () => {
  assert.equal(stock.onHand({ quantity: 'Infinity' }), 0);
  assert.equal(stock.onHand({ quantity: '' }), 0);
  assert.equal(stock.isVisible({ quantity: '0.00001' }), false);
  assert.equal(stock.isVisible({ quantity: '1' }), true);
});
