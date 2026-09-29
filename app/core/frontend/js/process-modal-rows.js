(function() {
  'use strict';

  const { normalisePromptOptions } = window.ProcessModalUtils;

  function getGuidedInputListElement(type) {
    return document.getElementById('guided-inputs-list-unified');
  }

  function getAllGuidedInputElements() {
    const list = document.getElementById('guided-inputs-list-unified');
    return list ? Array.from(list.querySelectorAll(':scope > div')) : [];
  }

  function collectCurrentInputs() {
    const inputs = [];
    const inputElements = getAllGuidedInputElements();
    inputElements.forEach(inputEl => {
      const nameInput = inputEl.querySelector('.guided-input-name');
      let name = '';
      if (nameInput) {
        if (nameInput.classList.contains('searchable-dropdown-input')) {
          name = nameInput.value.trim();
        } else {
          name = nameInput.value.trim();
        }
      }

      const quantityInput = inputEl.querySelector('.guided-input-quantity');
      const quantity = quantityInput ? (quantityInput.value || '').trim() : '';

      const unitSelect = inputEl.querySelector('.guided-input-unit');
      const unit = unitSelect ? unitSelect.value : '';

      const executionTypeSelect = inputEl.querySelector('.guided-input-execution-type');
      const executionType = executionTypeSelect ? executionTypeSelect.value : 'prompt';
      const inputType = inputEl.dataset.inputType || (inputEl.getAttribute && inputEl.getAttribute('data-input-type')) || '';
      const requiresInventorySelection = (inputType === 'inventory' || inputType === 'previous_output') ? true : (executionType === 'variable');
      const isVariable = executionType === 'variable' || executionType === 'prompt';
      const sourceOutputId = inputEl.dataset.sourceOutputId || null;
      const expectedInventoryType = inputEl.dataset.expectedInventoryType || null;

      if (name && unit) {
        const row = {
          name: name,
          quantity: quantity ? parseFloat(quantity) : null,
          unit: unit,
          executionType: executionType,
          requires_inventory_selection: requiresInventorySelection,
          is_variable: isVariable
        };
        if (sourceOutputId) row.source_output_id = sourceOutputId;
        if (expectedInventoryType) row.expected_inventory_type = expectedInventoryType;
        inputs.push(row);
      }
    });
    return inputs;
  }

  function collectCurrentOutputs() {
    const outputs = [];
    const outputElements = document.querySelectorAll('#guided-outputs-list > div');
    outputElements.forEach(outputEl => {
      const name = outputEl.querySelector('.guided-output-name')?.value.trim();
      const unitSelect = outputEl.querySelector('.guided-output-unit');
      const unit = unitSelect ? unitSelect.value : '';
      const quantityInput = outputEl.querySelector('.guided-output-quantity');
      const quantity = quantityInput ? (quantityInput.value || '').trim() : '';

      if (name && unit) {
        outputs.push({
          name: name,
          unit: unit,
          quantity: quantity ? parseFloat(quantity) : null
        });
      }
    });
    return outputs;
  }

  function collectCurrentPrompts() {
    const prompts = [];
    const promptElements = document.querySelectorAll('#guided-prompts-list > div');
    promptElements.forEach(promptEl => {
      const label = promptEl.querySelector('.guided-prompt-label')?.value.trim();
      const typeSelect = promptEl.querySelector('.guided-prompt-type');
      const type = typeSelect ? typeSelect.value : 'text';
      const unitSelect = promptEl.querySelector('.guided-prompt-unit');
      const unit = unitSelect ? (unitSelect.value || '').trim() : null;
      const requiredSelect = promptEl.querySelector('.guided-prompt-required');
      const required = requiredSelect ? requiredSelect.value === 'true' : true;
      const optionsInput = promptEl.querySelector('.guided-prompt-options');

      if (label) {
        const prompt = {
          label: label,
          type: type,
          unit: unit || null,
          required: required
        };
        if (type === 'select') prompt.options = normalisePromptOptions(optionsInput ? optionsInput.value : []);
        prompts.push(prompt);
      }
    });
    return prompts;
  }

  function collapseAllInputs(exceptId = null) {
    const allInputs = getAllGuidedInputElements();
    allInputs.forEach(inputEl => {
      if (inputEl.id !== exceptId) {
        const contentArea = inputEl.querySelector('.guided-input-content');
        const expandIcon = inputEl.querySelector('.guided-input-expand-icon');
        const expandHint = inputEl.querySelector('.guided-input-expand-hint');
        if (contentArea && expandIcon) {
          contentArea.style.display = 'none';
          expandIcon.style.transform = 'rotate(0deg)';
          inputEl.dataset.expanded = 'false';
          if (expandHint) expandHint.textContent = '(click to expand)';
        }
      }
    });
  }

  function collapseAllOutputs(exceptId = null) {
    const allOutputs = document.querySelectorAll('#guided-outputs-list > div');
    allOutputs.forEach(outputEl => {
      if (outputEl.id !== exceptId) {
        const contentArea = outputEl.querySelector('.guided-output-content');
        const expandIcon = outputEl.querySelector('.guided-output-expand-icon');
        const expandHint = outputEl.querySelector('.guided-output-expand-hint');
        if (contentArea && expandIcon) {
          contentArea.style.display = 'none';
          expandIcon.style.transform = 'rotate(0deg)';
          outputEl.dataset.expanded = 'false';
          if (expandHint) expandHint.textContent = '(click to expand)';
        }
      }
    });
  }

  function toggleInputExpand(inputId) {
    const inputEl = document.getElementById(inputId);
    if (!inputEl) return;

    const contentArea = inputEl.querySelector('.guided-input-content');
    const expandIcon = inputEl.querySelector('.guided-input-expand-icon');
    const expandHint = inputEl.querySelector('.guided-input-expand-hint');
    if (!contentArea || !expandIcon) return;

    const isExpanded = inputEl.dataset.expanded === 'true';
    if (isExpanded) {
      contentArea.style.display = 'none';
      expandIcon.style.transform = 'rotate(0deg)';
      inputEl.dataset.expanded = 'false';
      if (expandHint) expandHint.textContent = '(click to expand)';
    } else {
      contentArea.style.display = 'block';
      expandIcon.style.transform = 'rotate(180deg)';
      inputEl.dataset.expanded = 'true';
      if (expandHint) expandHint.textContent = '(click to collapse)';
      // Collapse all other inputs
      collapseAllInputs(inputId);
    }
  }

  function toggleOutputExpand(outputId) {
    const outputEl = document.getElementById(outputId);
    if (!outputEl) return;

    const contentArea = outputEl.querySelector('.guided-output-content');
    const expandIcon = outputEl.querySelector('.guided-output-expand-icon');
    const expandHint = outputEl.querySelector('.guided-output-expand-hint');
    if (!contentArea || !expandIcon) return;

    const isExpanded = outputEl.dataset.expanded === 'true';
    if (isExpanded) {
      contentArea.style.display = 'none';
      expandIcon.style.transform = 'rotate(0deg)';
      outputEl.dataset.expanded = 'false';
      if (expandHint) expandHint.textContent = '(click to expand)';
    } else {
      contentArea.style.display = 'block';
      expandIcon.style.transform = 'rotate(180deg)';
      outputEl.dataset.expanded = 'true';
      if (expandHint) expandHint.textContent = '(click to collapse)';
      // Collapse all other outputs
      collapseAllOutputs(outputId);
    }
  }

  window.ProcessModalRows = Object.freeze({
    getGuidedInputListElement,
    getAllGuidedInputElements,
    collectCurrentInputs,
    collectCurrentOutputs,
    collectCurrentPrompts,
    collapseAllInputs,
    collapseAllOutputs,
    toggleInputExpand,
    toggleOutputExpand
  });
})();
