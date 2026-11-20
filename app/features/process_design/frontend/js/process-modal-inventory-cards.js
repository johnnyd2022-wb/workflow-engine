(function() {
  'use strict';

  const { escapeHtmlForText } = window.ProcessModalUtils;

  // Summary under item name. Raw: none (user selects at execution). Intermediate/final: process name, unit.
  function inventoryCardSummary(item) {
    const isRaw = (item.inventory_type || item.category) === 'raw_material';
    if (isRaw) return '';
    const parts = [];
    if (item.process_name) parts.push('process name: ' + escapeHtmlForText(item.process_name));
    if (item.unit) parts.push('unit: ' + escapeHtmlForText(item.unit));
    return parts.join(', ');
  }

  // Helper text: all inventory categories select specific stock at execution (same behavior as raw materials).
  function inventoryExecutionHelperText(_item) {
    return 'You will select which batch or supplier to use when this step runs.';
  }

  // Build full metadata block. Raw: type + helper. Intermediate/final: type, unit, process, step, made-from list + helper (no execution metadata: supplier/batch/dates/prompts/variable_output/previous_steps).
  function inventoryCardMetadataHtml(item) {
    const lines = [];
    const cat = item.inventory_type || item.category;
    if (cat) {
      const label = cat === 'raw_material' ? 'Raw material' : cat === 'work_in_progress' ? 'Intermediate' : 'Final product';
      lines.push('<div class="meta-line"><span class="meta-label">Type:</span> ' + escapeHtmlForText(label) + '</div>');
    }
    const isRaw = cat === 'raw_material';
    if (!isRaw && item.unit != null && item.unit !== '') {
      lines.push('<div class="meta-line"><span class="meta-label">Unit:</span> ' + escapeHtmlForText(String(item.unit)) + '</div>');
    }
    if (!isRaw && item.process_name) {
      lines.push('<div class="meta-line"><span class="meta-label">Process:</span> ' + escapeHtmlForText(item.process_name) + '</div>');
    }
    if (!isRaw && item.source_step_name) {
      lines.push('<div class="meta-line"><span class="meta-label">Step:</span> ' + escapeHtmlForText(item.source_step_name) + '</div>');
    }
    const ed = item.extra_data;
    if (ed && typeof ed === 'object' && ed.variable_inputs && Array.isArray(ed.variable_inputs) && ed.variable_inputs.length > 0) {
      lines.push('<div class="meta-line"><span class="meta-label">Made from:</span></div>');
      ed.variable_inputs.forEach(function(inp, idx) {
        const n = inp && inp.name ? inp.name : 'Input ' + (idx + 1);
        const q = inp && inp.quantity != null ? inp.quantity : '';
        const u = inp && inp.unit ? inp.unit : '';
        lines.push('<div class="meta-line" style="padding-left: 12px;">' + escapeHtmlForText(n) + (q !== '' ? ' — ' + escapeHtmlForText(String(q)) + (u ? ' ' + escapeHtmlForText(u) : '') : '') + '</div>');
      });
    }
    lines.push('<div class="meta-line" style="font-style: italic;">' + escapeHtmlForText(inventoryExecutionHelperText(item)) + '</div>');
    return lines.join('');
  }

  window.ProcessModalInventoryCards = Object.freeze({
    inventoryCardSummary,
    inventoryExecutionHelperText,
    inventoryCardMetadataHtml
  });
})();
