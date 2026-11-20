/**
 * Single contract for human-readable inventory lines in the execution UI (triggers, cards, subtitles).
 * Load before execution-render-inputs.js / execution-modal-secondary.js (after inventory-type-utils if both present).
 */
(function (root) {
  'use strict';

  /** "12 kg" style quantity + unit (or either). */
  function quantityUnitLine(inv) {
    if (!inv) return '';
    var q = inv.quantity != null ? String(inv.quantity) : '';
    var u = inv.unit || '';
    if (q && u) return q + ' ' + u;
    return q || u || '';
  }

  /**
   * Picker / dropdown selection label: "Process - Name - qty unit" (plain text, for textContent).
   */
  function formatTriggerLabel(inv) {
    if (!inv) return '';
    var head = (inv.process_name ? String(inv.process_name) + ' - ' : '') + String(inv.name || '');
    return head + ' - ' + quantityUnitLine(inv).trim();
  }

  /**
   * Subtitle under the selected item row: "Process · qty unit" (when process exists).
   */
  function formatSelectedRowSubtitle(inv) {
    if (!inv) return '';
    return (inv.process_name ? String(inv.process_name) + ' · ' : '') + quantityUnitLine(inv);
  }

  /**
   * Add-another dropdown card one-liner: "qty unit · Process" (legacy order, plain text before escapeHtml in HTML).
   */
  function formatDropdownCardSubtitle(inv) {
    if (!inv) return '';
    var parts = [];
    var qu = quantityUnitLine(inv);
    if (qu) parts.push(qu);
    if (inv.process_name) parts.push(String(inv.process_name));
    return parts.join(' · ');
  }

  root.InventoryDisplay = {
    quantityUnitLine: quantityUnitLine,
    formatTriggerLabel: formatTriggerLabel,
    formatSelectedRowSubtitle: formatSelectedRowSubtitle,
    formatDropdownCardSubtitle: formatDropdownCardSubtitle,
  };
})(typeof window !== 'undefined' ? window : this);
