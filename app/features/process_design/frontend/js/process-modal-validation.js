(function() {
  'use strict';

  function validateInventoryInputs() {
    const list = document.getElementById('guided-inputs-list-unified');
    if (!list) return { valid: true };
    const rows = list.querySelectorAll(':scope > div[data-input-type="inventory"], :scope > div[data-input-type="previous_output"]');
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      const quantityInput = row.querySelector('.guided-input-quantity');
      const unitSelect = row.querySelector('.guided-input-unit');
      if (!quantityInput && !unitSelect) continue;
      const quantityStr = quantityInput ? (quantityInput.value || '').trim() : '';
      const unit = unitSelect ? (unitSelect.value || '').trim() : '';
      if (quantityStr === '' || unit === '') {
        return {
          valid: false,
          message: 'Please fill Quantity and Unit for all inventory items. Both are required.'
        };
      }
      const quantityNum = parseFloat(quantityStr);
      if (isNaN(quantityNum) || quantityNum <= 0) {
        return {
          valid: false,
          message: 'Quantity must be greater than 0 for all inventory items.'
        };
      }
    }
    return { valid: true };
  }

  function validateFixedExpiryWarning(outputs) {
    try {
      if (window.CustomExpiryValidation && typeof window.CustomExpiryValidation.validateFixedExpiryWarning === 'function') {
        return window.CustomExpiryValidation.validateFixedExpiryWarning(outputs);
      }
    } catch (e) {}
    return { valid: true };
  }

  window.ProcessModalValidation = Object.freeze({
    validateInventoryInputs,
    validateFixedExpiryWarning
  });
})();
