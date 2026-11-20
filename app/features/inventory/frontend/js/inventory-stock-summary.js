(function () {
  'use strict';

  function onHand(item) {
    const quantity = parseFloat(String(item && item.quantity != null ? item.quantity : '0').trim());
    return Number.isFinite(quantity) ? quantity : 0;
  }

  function isVisible(item) {
    const quantity = onHand(item);
    return quantity > 0 && Math.abs(quantity) >= 0.0001;
  }

  function groupKey(item) {
    return [
      String(item.name || '').trim().toLowerCase(),
      item.inventory_type || '',
      String(item.unit || '').trim().toLowerCase(),
    ].join('\u0000');
  }

  function group(items) {
    const byKey = new Map();
    items.forEach(item => {
      const key = groupKey(item);
      let stock = byKey.get(key);
      if (!stock) {
        stock = {
          key,
          name: String(item.name || '').trim() || 'Unnamed item',
          type: item.inventory_type,
          unit: item.unit || '',
          lots: [],
          total: 0,
        };
        byKey.set(key, stock);
      }
      stock.lots.push(item);
      stock.total += onHand(item);
    });
    return [...byKey.values()];
  }

  function format(quantity) {
    return (Math.round(quantity * 10000) / 10000).toLocaleString(undefined, { maximumFractionDigits: 4 });
  }

  window.InventoryStockSummary = Object.freeze({ onHand, isVisible, groupKey, group, format });
})();
