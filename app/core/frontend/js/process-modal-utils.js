(function() {
  'use strict';

  function summaryInputDisplayName(row) {
    if (!row) return '';
    return String(row.name || row.input_name || row.material_name || row.item_name || '').trim();
  }

  function summaryOutputDisplayName(row) {
    if (!row) return '';
    return String(row.name || row.output_name || '').trim();
  }

  function isCustomExecutionPrompt(prompt) {
    if (!prompt || !(prompt.label || '').trim()) return false;
    const label = (prompt.label || '').trim().toLowerCase();
    if (label === 'batch number' || label === 'evidence') return false;
    if (prompt.type === 'evidence') return false;
    return true;
  }

  function countLabeledExecutionPrompts(prompts) {
    if (!Array.isArray(prompts)) return 0;
    return prompts.filter(function(prompt) {
      return prompt && (prompt.label || '').trim();
    }).length;
  }

  function normalisePromptOptions(options) {
    const raw = Array.isArray(options) ? options : String(options || '').split(/\r?\n/);
    const seen = new Set();
    return raw.reduce(function(result, option) {
      const value = String(option == null ? '' : option).trim();
      if (value && !seen.has(value)) {
        seen.add(value);
        result.push(value);
      }
      return result;
    }, []);
  }

  function base64ToBlob(base64, mime) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type: mime || 'application/octet-stream' });
  }

  function escapeHtmlForText(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  window.ProcessModalUtils = Object.freeze({
    summaryInputDisplayName,
    summaryOutputDisplayName,
    isCustomExecutionPrompt,
    countLabeledExecutionPrompts,
    normalisePromptOptions,
    base64ToBlob,
    escapeHtmlForText
  });
})();
