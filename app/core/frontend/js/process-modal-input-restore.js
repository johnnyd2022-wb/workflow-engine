(function() {
  'use strict';

  // Populate a guided input container from saved step data (used when loading a step or when adding in parallel with load data).
  async function populateGuidedInputFromLoadData(container, data, type, context) {
    if (!container || !data || !data.name) return;
    const { selectedInventoryItems, loadInventoryItems, syncGuidedNewInputExecutionSegments } = context;
    const nameInput = container.querySelector('.guided-input-name');
    if (nameInput) {
      nameInput.value = data.name;
      if (nameInput.classList.contains('searchable-dropdown-input')) {
        selectedInventoryItems.add(data.name);
        try {
          const categorizedItems = await loadInventoryItems();
          const allItems = [
            ...(categorizedItems.raw_material || []),
            ...(categorizedItems.work_in_progress || []),
            ...(categorizedItems.final_product || [])
          ];
          const matchingItem = allItems.find(item => item.name === data.name);
          if (matchingItem) {
            const unitSelect = container.querySelector('.guided-input-unit');
            if (unitSelect) unitSelect.value = data.unit || matchingItem.unit || '';
            if (!data.expected_inventory_type && type === 'inventory') {
              const cat = matchingItem.inventory_type || matchingItem.category;
              if (cat === 'raw_material' || cat === 'work_in_progress' || cat === 'final_product') {
                container.dataset.expectedInventoryType = cat;
              }
            }
          }
        } catch (err) {
          console.warn('Could not load inventory items for restoration:', err);
        }
        nameInput.dispatchEvent(new Event('input'));
        nameInput.dispatchEvent(new Event('blur'));
      } else {
        nameInput.dispatchEvent(new Event('input'));
        nameInput.dispatchEvent(new Event('blur'));
      }
    }
    const quantityInput = container.querySelector('.guided-input-quantity');
    if (quantityInput && data.quantity !== null && data.quantity !== undefined) {
      quantityInput.value = data.quantity;
    }
    const unitSelect = container.querySelector('.guided-input-unit');
    if (unitSelect && data.unit && !unitSelect.value) {
      unitSelect.value = data.unit;
    }
    const executionTypeSelect = container.querySelector('.guided-input-execution-type');
    if (executionTypeSelect) {
      if (type === 'inventory') {
        executionTypeSelect.value = 'variable';
      } else {
        if (data.requires_inventory_selection) executionTypeSelect.value = 'variable';
        else if (data.is_variable === false) executionTypeSelect.value = 'static';
        else executionTypeSelect.value = 'prompt';
      }
      executionTypeSelect.dispatchEvent(new Event('change'));
    }
    if (type === 'new') syncGuidedNewInputExecutionSegments(container);
    if (data.source_output_id) container.dataset.sourceOutputId = data.source_output_id;
    if (data.expected_inventory_type) {
      container.dataset.expectedInventoryType = data.expected_inventory_type;
      if (typeof container._applyExpectedTypeUI === 'function') {
        container._applyExpectedTypeUI();
      }
    }
    setTimeout(() => {
      const nameDisplay = container.querySelector('.guided-input-name-display');
      const titleSpan = container.querySelector('.guided-input-title');
      if (nameDisplay && titleSpan && data.name) {
        nameDisplay.textContent = data.name;
        nameDisplay.style.display = 'inline';
        titleSpan.style.display = 'none';
      }
    }, 100);
  }

  window.ProcessModalInputRestore = Object.freeze({ populateGuidedInputFromLoadData });
})();
