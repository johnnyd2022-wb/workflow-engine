(function() {
  'use strict';

  function createPromptActions({ unitGroups, updateStep4SummaryBar }) {
  // Add guided execution prompt
  function addGuidedPrompt() {
    // Collapse all existing prompts before adding a new one
    collapseAllPrompts();

    const promptId = `guided-prompt-${Date.now()}`;
    const promptContainer = document.createElement('div');
    promptContainer.id = promptId;
    promptContainer.dataset.expanded = 'true'; // New prompt starts expanded
    promptContainer.style.cssText = 'background: var(--bg-card, #ffffff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md); margin-bottom: 12px; overflow: hidden;';

    // Create header with expand/collapse
    const header = document.createElement('div');
    header.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 12px; cursor: pointer; background: var(--bg-secondary, #f9fafb);';
    header.onclick = () => togglePromptExpand(promptId);

    const headerLeft = document.createElement('div');
    headerLeft.style.cssText = 'display: flex; align-items: center; gap: 8px;';

    const expandIcon = document.createElement('svg');
    expandIcon.className = 'guided-prompt-expand-icon';
    expandIcon.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    expandIcon.setAttribute('width', '16');
    expandIcon.setAttribute('height', '16');
    expandIcon.setAttribute('viewBox', '0 0 24 24');
    expandIcon.setAttribute('fill', 'none');
    expandIcon.setAttribute('stroke', 'currentColor');
    expandIcon.setAttribute('stroke-width', '2');
    expandIcon.setAttribute('stroke-linecap', 'round');
    expandIcon.setAttribute('stroke-linejoin', 'round');
    expandIcon.style.cssText = 'transition: transform 0.2s; transform: rotate(180deg);';
    expandIcon.innerHTML = '<polyline points="6 9 12 15 18 9"></polyline>';
    headerLeft.appendChild(expandIcon);

    const titleSpan = document.createElement('span');
    titleSpan.className = 'guided-prompt-title';
    titleSpan.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary);';
    titleSpan.textContent = 'Execution Prompt';
    headerLeft.appendChild(titleSpan);

    // Add label display that will show when collapsed
    const labelDisplay = document.createElement('span');
    labelDisplay.className = 'guided-prompt-label-display';
    labelDisplay.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary); display: none;';
    labelDisplay.textContent = '';
    headerLeft.appendChild(labelDisplay);

    // Add expand/collapse hint text
    const expandHint = document.createElement('span');
    expandHint.className = 'guided-prompt-expand-hint';
    expandHint.style.cssText = 'font-size: 11px; color: var(--text-tertiary, #9ca3af); margin-left: 8px; font-style: italic;';
    expandHint.textContent = '(click to collapse)';
    headerLeft.appendChild(expandHint);

    header.appendChild(headerLeft);

    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.onclick = (e) => {
      e.stopPropagation();
      removeGuidedPrompt(promptId);
    };
    removeButton.style.cssText = 'padding: 4px 8px; border: none; background: transparent; color: var(--error, #ef4444); cursor: pointer; font-size: 12px;';
    removeButton.textContent = 'Remove';
    header.appendChild(removeButton);

    promptContainer.appendChild(header);

    // Create content area
    const contentArea = document.createElement('div');
    contentArea.className = 'guided-prompt-content';
    contentArea.style.cssText = 'padding: 12px; display: block;';

    // Function to update label display
    const updateLabelDisplay = () => {
      const labelInput = promptContainer.querySelector('.guided-prompt-label');
      const label = labelInput ? labelInput.value.trim() : '';

      if (label) {
        labelDisplay.textContent = label;
        labelDisplay.style.display = 'inline';
        titleSpan.style.display = 'none';
      } else {
        labelDisplay.style.display = 'none';
        titleSpan.style.display = 'inline';
      }
    };

    // Label field
    const labelField = document.createElement('div');
    labelField.style.marginBottom = '12px';
    const labelLabel = document.createElement('label');
    labelLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    labelLabel.textContent = 'Label';
    labelField.appendChild(labelLabel);
    const labelInput = document.createElement('input');
    labelInput.type = 'text';
    labelInput.className = 'guided-prompt-label';
    labelInput.placeholder = 'e.g., Temperature, Operator name';
    labelInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
    labelInput.addEventListener('input', updateLabelDisplay);
    labelInput.addEventListener('blur', updateLabelDisplay);
    labelField.appendChild(labelInput);
    contentArea.appendChild(labelField);

    // Type field
    const typeField = document.createElement('div');
    typeField.style.marginBottom = '12px';
    const typeLabel = document.createElement('label');
    typeLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    typeLabel.textContent = 'Type';
    typeField.appendChild(typeLabel);
    const typeSelect = document.createElement('select');
    typeSelect.className = 'guided-prompt-type form-select';
    typeSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
    const textOption = document.createElement('option');
    textOption.value = 'text';
    textOption.textContent = 'Text';
    typeSelect.appendChild(textOption);
    const numberOption = document.createElement('option');
    numberOption.value = 'number';
    numberOption.textContent = 'Number';
    typeSelect.appendChild(numberOption);
    const dateOption = document.createElement('option');
    dateOption.value = 'date';
    dateOption.textContent = 'Date';
    typeSelect.appendChild(dateOption);
    const selectOption = document.createElement('option');
    selectOption.value = 'select';
    selectOption.textContent = 'Select';
    typeSelect.appendChild(selectOption);
    typeField.appendChild(typeSelect);
    contentArea.appendChild(typeField);

    const optionsField = document.createElement('div');
    optionsField.className = 'guided-prompt-options-field';
    optionsField.style.cssText = 'margin-bottom: 12px; display: none;';
    const optionsLabel = document.createElement('label');
    optionsLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    optionsLabel.textContent = 'Choices (one per line)';
    optionsField.appendChild(optionsLabel);
    const optionsInput = document.createElement('textarea');
    optionsInput.className = 'guided-prompt-options';
    optionsInput.rows = 4;
    optionsInput.placeholder = 'Pass\nHold\nRework';
    optionsInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px; resize: vertical;';
    optionsField.appendChild(optionsInput);
    const optionsHint = document.createElement('p');
    optionsHint.style.cssText = 'margin: 4px 0 0; font-size: 11px; color: var(--text-secondary);';
    optionsHint.textContent = 'Operators can choose only one of these values.';
    optionsField.appendChild(optionsHint);
    typeSelect.addEventListener('change', function() {
      optionsField.style.display = typeSelect.value === 'select' ? 'block' : 'none';
    });
    contentArea.appendChild(optionsField);

    // Unit field (optional)
    const unitField = document.createElement('div');
    unitField.style.marginBottom = '12px';
    const unitLabel = document.createElement('label');
    unitLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    unitLabel.textContent = 'Unit (optional)';
    unitField.appendChild(unitLabel);
    const unitSelect = document.createElement('select');
    unitSelect.className = 'guided-prompt-unit form-select';
    unitSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
    // Add empty option for "no unit"
    const emptyUnitOption = document.createElement('option');
    emptyUnitOption.value = '';
    emptyUnitOption.textContent = 'No unit';
    unitSelect.appendChild(emptyUnitOption);
    // Add unit options from unitGroups (same as inputs/outputs)
    [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
      const option = document.createElement('option');
      option.value = unit;
      option.textContent = unit;
      unitSelect.appendChild(option);
    });
    unitField.appendChild(unitSelect);
    contentArea.appendChild(unitField);

    // Required field
    const requiredField = document.createElement('div');
    const requiredLabel = document.createElement('label');
    requiredLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    requiredLabel.textContent = 'Required';
    requiredField.appendChild(requiredLabel);
    const requiredSelect = document.createElement('select');
    requiredSelect.className = 'guided-prompt-required form-select';
    requiredSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px; margin-bottom: 4px;';
    const requiredOption = document.createElement('option');
    requiredOption.value = 'true';
    requiredOption.textContent = 'Required';
    requiredSelect.appendChild(requiredOption);
    const optionalOption = document.createElement('option');
    optionalOption.value = 'false';
    optionalOption.textContent = 'Optional';
    requiredSelect.appendChild(optionalOption);
    requiredField.appendChild(requiredSelect);
    contentArea.appendChild(requiredField);

    promptContainer.appendChild(contentArea);
    document.getElementById('guided-prompts-list').appendChild(promptContainer);
    if (typeof updateStep4SummaryBar === 'function') updateStep4SummaryBar();
  };

  // Collapse all prompts except the specified one
  function collapseAllPrompts(exceptId = null) {
    const allPrompts = document.querySelectorAll('#guided-prompts-list > div');
    allPrompts.forEach(promptEl => {
      if (promptEl.id !== exceptId) {
        const contentArea = promptEl.querySelector('.guided-prompt-content');
        const expandIcon = promptEl.querySelector('.guided-prompt-expand-icon');
        const expandHint = promptEl.querySelector('.guided-prompt-expand-hint');
        if (contentArea && expandIcon) {
          contentArea.style.display = 'none';
          expandIcon.style.transform = 'rotate(0deg)';
          promptEl.dataset.expanded = 'false';
          if (expandHint) expandHint.textContent = '(click to expand)';
        }
      }
    });
  }

  // Toggle prompt expand/collapse
  function togglePromptExpand(promptId) {
    const promptEl = document.getElementById(promptId);
    if (!promptEl) return;

    const contentArea = promptEl.querySelector('.guided-prompt-content');
    const expandIcon = promptEl.querySelector('.guided-prompt-expand-icon');
    const expandHint = promptEl.querySelector('.guided-prompt-expand-hint');
    if (!contentArea || !expandIcon) return;

    const isExpanded = promptEl.dataset.expanded === 'true';
    if (isExpanded) {
      contentArea.style.display = 'none';
      expandIcon.style.transform = 'rotate(0deg)';
      promptEl.dataset.expanded = 'false';
      if (expandHint) expandHint.textContent = '(click to expand)';
    } else {
      contentArea.style.display = 'block';
      expandIcon.style.transform = 'rotate(180deg)';
      promptEl.dataset.expanded = 'true';
      if (expandHint) expandHint.textContent = '(click to collapse)';
      // Collapse all other prompts
      collapseAllPrompts(promptId);
    }
  }

  // Remove guided prompt
  function removeGuidedPrompt(promptId) {
    const promptElement = document.getElementById(promptId);
    if (promptElement) {
      promptElement.remove();
      if (typeof updateStep4SummaryBar === 'function') updateStep4SummaryBar();
    }
  };


    return { addGuidedPrompt, removeGuidedPrompt };
  }

  window.ProcessModalPrompts = Object.freeze({ create: createPromptActions });
})();
