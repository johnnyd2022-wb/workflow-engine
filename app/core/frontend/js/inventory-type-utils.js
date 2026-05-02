/**
 * Shared inventory tab / expected-type normalization for execution UI (picker, SPA, open-step).
 * Load before execution-render-inputs.js and any consumer that needs identical classification rules.
 */
(function (root) {
  'use strict';

  function getInvType(inv) {
    return inv && (inv.inventory_type || inv.type || inv.category || inv.item_type || '');
  }

  /**
   * Map API inventory types onto picker tab keys: raw_material | work_in_progress | final_product.
   */
  function normalizeInventoryTabType(inv) {
    var t = String(getInvType(inv) || '').toLowerCase().trim();
    if (!t) return 'raw_material';
    if (t === 'intermediate' || t === 'work_in_progress' || t === 'wip') return 'work_in_progress';
    if (t === 'final' || t === 'final_product') return 'final_product';
    if (t === 'raw' || t === 'raw_material') return 'raw_material';
    return t;
  }

  /**
   * Hint from process designer (inventory category chosen for this input).
   * Returns tab key or null if unset / unrecognized.
   */
  function normalizeExpectedInventoryTabHint(inp) {
    if (!inp) return null;
    var v = inp.expected_inventory_type != null ? inp.expected_inventory_type : inp.expectedInventoryType;
    if (v == null || v === '') return null;
    var s = String(v).toLowerCase().trim();
    if (s === 'intermediate' || s === 'wip' || s === 'work_in_progress') return 'work_in_progress';
    if (s === 'final' || s === 'final_product') return 'final_product';
    if (s === 'raw' || s === 'raw_material') return 'raw_material';
    return null;
  }

  root.InventoryTypeUtils = {
    getInvType: getInvType,
    normalizeInventoryTabType: normalizeInventoryTabType,
    normalizeExpectedInventoryTabHint: normalizeExpectedInventoryTabHint,
  };
})(typeof window !== 'undefined' ? window : this);
