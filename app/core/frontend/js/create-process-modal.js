(function() {
  'use strict';
  
  let currentStep = 1;
  const totalSteps = 3;
  let guidedInputs = [];
  let guidedOutputs = [];
  let selectedInventoryItems = new Set(); // Track selected inventory items to prevent duplicates
  
  // Open the create process modal
  window.openCreateProcessModal = function() {
    const modal = document.getElementById('create-process-modal');
    if (modal) {
      modal.style.display = 'flex';
      document.body.style.overflow = 'hidden';
      currentStep = 1;
      guidedInputs = [];
      guidedOutputs = [];
      // Clear inventory cache to get fresh data
      inventoryCache = null;
      selectedInventoryItems.clear();
      updateStepDisplay();
      resetForm();
    }
  };
  
  // Close modal
  function closeModal() {
    const modal = document.getElementById('create-process-modal');
    if (modal) {
      modal.style.display = 'none';
      document.body.style.overflow = 'auto';
    }
  }
  
  // Reset form
  function resetForm() {
    document.getElementById('guided-step-name').value = '';
    document.getElementById('guided-step-description').value = '';
    document.getElementById('guided-inputs-list').innerHTML = '';
    document.getElementById('guided-outputs-list').innerHTML = '';
    guidedInputs = [];
    guidedOutputs = [];
    selectedInventoryItems.clear();
  }
  
  // Update step display
  function updateStepDisplay() {
    // Update step indicators
    for (let i = 1; i <= totalSteps; i++) {
      const indicator = document.querySelector(`.step-indicator[data-step="${i}"]`);
      if (indicator) {
        if (i === currentStep) {
          indicator.style.background = 'var(--primary, #3b82f6)';
          indicator.style.color = 'white';
          indicator.style.border = 'none';
        } else if (i < currentStep) {
          indicator.style.background = 'var(--success, #10b981)';
          indicator.style.color = 'white';
          indicator.style.border = 'none';
        } else {
          indicator.style.background = 'var(--bg-secondary, #f3f4f6)';
          indicator.style.color = 'var(--text-secondary)';
          indicator.style.border = '2px solid var(--border-default, #e5e7eb)';
        }
      }
    }
    
    // Show/hide steps
    for (let i = 1; i <= totalSteps; i++) {
      const stepDiv = document.getElementById(`create-process-step-${i}`);
      if (stepDiv) {
        stepDiv.style.display = i === currentStep ? 'block' : 'none';
      }
    }
  }
  
  // Navigate to next step
  window.createProcessNextStep = function() {
    if (currentStep === 1) {
      // Validate step 1
      const stepName = document.getElementById('guided-step-name').value.trim();
      if (!stepName) {
        alert('Please enter a step name');
        return;
      }
    }
    
    if (currentStep < totalSteps) {
      currentStep++;
      updateStepDisplay();
    }
  };
  
  // Navigate to previous step
  window.createProcessPreviousStep = function() {
    if (currentStep > 1) {
      currentStep--;
      updateStepDisplay();
    }
  };
  
  // Unit groups (matching flows2.html)
  const unitGroups = {
    weight: ['kg', 'g'],
    volume: ['L', 'mL'],
    count: ['pcs', 'units']
  };
  
  // Load inventory items (all types)
  let inventoryCache = null;
  async function loadInventoryItems() {
    if (inventoryCache) {
      return inventoryCache;
    }
    
    try {
      // Load all inventory types - try multiple approaches
      let items = [];
      const processId = window.processId;
      
      console.log('Loading inventory items, processId:', processId);
      
      // Try loading with processId first
      if (processId) {
        try {
          const inventoryData = await CoreAPI.getInventory(null, processId);
          items = inventoryData.inventory_items || [];
          console.log('Loaded inventory with processId:', items.length);
        } catch (err) {
          console.warn('Failed to load inventory with processId:', err);
        }
      }
      
      // If no items, try loading all raw materials
      if (items.length === 0) {
        try {
          const rawMaterialsData = await CoreAPI.getInventory('raw_material');
          const rawItems = rawMaterialsData.inventory_items || [];
          items.push(...rawItems);
          console.log('Loaded raw materials:', rawItems.length);
        } catch (err) {
          console.warn('Failed to load raw materials:', err);
        }
      }
      
      // If still no items, try loading all inventory without filters
      if (items.length === 0) {
        try {
          const allInventoryData = await CoreAPI.getInventory();
          items = allInventoryData.inventory_items || [];
          console.log('Loaded all inventory:', items.length);
        } catch (err) {
          console.warn('Failed to load all inventory:', err);
        }
      }
      
      // Get unique inventory items by name only (no duplicates)
      const uniqueItems = [];
      const seenNames = new Set();
      
      items.forEach(item => {
        if (item && item.name && !seenNames.has(item.name)) {
          seenNames.add(item.name);
          uniqueItems.push({
            name: item.name,
            unit: item.unit || ''
          });
        }
      });
      
      inventoryCache = uniqueItems;
      return uniqueItems;
    } catch (error) {
      console.error('Failed to load inventory items:', error);
      console.error('Error details:', error.message, error.stack);
      return [];
    }
  }
  
  // Create searchable dropdown for inventory (simplified version)
  function createInventorySearchableDropdown(items, onSelect, container) {
    const uniqueId = `guided-dropdown-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const dropdownContainer = document.createElement('div');
    dropdownContainer.className = 'searchable-dropdown-container';
    dropdownContainer.style.position = 'relative';
    dropdownContainer.style.width = '100%';
    
    dropdownContainer.innerHTML = `
      <input 
        type="text" 
        class="form-input guided-input-name searchable-dropdown-input" 
        placeholder="Search inventory items..."
        autocomplete="off"
        style="width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 13px;"
        data-dropdown-id="${uniqueId}"
      />
      <div 
        class="searchable-dropdown-list" 
        id="${uniqueId}"
        style="display: none; position: absolute; top: 100%; left: 0; right: 0; z-index: 1000; max-height: 200px; overflow-y: auto; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); margin-top: 4px; box-shadow: var(--shadow-lg, 0 8px 24px rgba(0, 0, 0, 0.12));"
      ></div>
    `;
    
    const input = dropdownContainer.querySelector('.searchable-dropdown-input');
    const dropdown = dropdownContainer.querySelector('.searchable-dropdown-list');
    let filteredItems = items;
    let selectedIndex = -1;
    const currentInputValue = input.value; // Store current input value to check if item is already selected
    
    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }
    
    function getAvailableItems() {
      // Filter out already selected items (except the one currently selected in this input)
      // Note: items parameter is already filtered before being passed to this function
      // This function is mainly for re-filtering when focus happens
      return items.filter(item => {
        const isSelected = selectedInventoryItems.has(item.name);
        const isCurrentSelection = input.value.trim() === item.name;
        return !isSelected || isCurrentSelection;
      });
    }
    
    // Initialize filteredItems with all items (they're already filtered before being passed in)
    filteredItems = items;
    
    function renderDropdown() {
      if (filteredItems.length === 0) {
        dropdown.innerHTML = '<div style="padding: 12px; color: var(--text-secondary); text-align: center; font-size: 13px;">No items available (all items may already be selected)</div>';
      } else {
        dropdown.innerHTML = filteredItems.map((item, index) => {
          return `
            <div 
              class="dropdown-item ${index === selectedIndex ? 'selected' : ''}"
              data-index="${index}"
              style="padding: 10px 12px; cursor: pointer; border-bottom: 1px solid var(--border-light); transition: background 0.15s; ${index === selectedIndex ? 'background: var(--bg-hover, rgba(0, 0, 0, 0.05));' : ''}"
              onmouseover="this.style.background='var(--bg-hover, rgba(0, 0, 0, 0.05))'"
              onmouseout="if (!this.classList.contains('selected')) this.style.background='transparent'"
            >
              <div style="font-weight: 500; color: var(--text-primary); font-size: 13px;">${escapeHtml(item.name)}</div>
            </div>
          `;
        }).join('');
      }
      dropdown.style.display = filteredItems.length > 0 || input.value.trim() ? 'block' : 'none';
    }
    
    function filterItems(searchTerm) {
      const term = searchTerm.toLowerCase().trim();
      const availableItems = getAvailableItems();
      if (!term) {
        filteredItems = availableItems;
      } else {
        filteredItems = availableItems.filter(item => {
          return item.name.toLowerCase().includes(term);
        });
      }
      selectedIndex = -1;
      renderDropdown();
    }
    
    function selectItem(item) {
      // Remove previous selection from this input if any
      const previousValue = input.value.trim();
      if (previousValue && previousValue !== item.name) {
        selectedInventoryItems.delete(previousValue);
      }
      
      if (onSelect) {
        onSelect(item);
      }
      input.value = item.name;
      // Mark this item as selected
      selectedInventoryItems.add(item.name);
      dropdown.style.display = 'none';
    }
    
    input.addEventListener('input', (e) => {
      filterItems(e.target.value);
    });
    
    input.addEventListener('focus', () => {
      // Re-filter to exclude newly selected items
      const availableItems = getAvailableItems();
      filteredItems = availableItems;
      renderDropdown();
    });
    
    input.addEventListener('blur', () => {
      // Delay hiding to allow click events
      setTimeout(() => {
        dropdown.style.display = 'none';
      }, 200);
    });
    
    dropdown.addEventListener('click', (e) => {
      const itemEl = e.target.closest('.dropdown-item');
      if (itemEl) {
        const index = parseInt(itemEl.dataset.index);
        if (filteredItems[index]) {
          const itemToSelect = filteredItems[index];
          selectItem(itemToSelect);
        }
      }
    });
    
    // Keyboard navigation
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIndex = Math.min(selectedIndex + 1, filteredItems.length - 1);
        renderDropdown();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIndex = Math.max(selectedIndex - 1, -1);
        renderDropdown();
      } else if (e.key === 'Enter' && selectedIndex >= 0 && filteredItems[selectedIndex]) {
        e.preventDefault();
        const itemToSelect = filteredItems[selectedIndex];
        selectItem(itemToSelect);
      }
    });
    
    return dropdownContainer;
  }
  
  // Collapse all inputs except the specified one
  function collapseAllInputs(exceptId = null) {
    const allInputs = document.querySelectorAll('#guided-inputs-list > div');
    allInputs.forEach(inputEl => {
      if (inputEl.id !== exceptId) {
        const contentArea = inputEl.querySelector('.guided-input-content');
        const expandIcon = inputEl.querySelector('.guided-input-expand-icon');
        if (contentArea && expandIcon) {
          contentArea.style.display = 'none';
          expandIcon.style.transform = 'rotate(0deg)';
          inputEl.dataset.expanded = 'false';
        }
      }
    });
  }
  
  // Collapse all outputs except the specified one
  function collapseAllOutputs(exceptId = null) {
    const allOutputs = document.querySelectorAll('#guided-outputs-list > div');
    allOutputs.forEach(outputEl => {
      if (outputEl.id !== exceptId) {
        const contentArea = outputEl.querySelector('.guided-output-content');
        const expandIcon = outputEl.querySelector('.guided-output-expand-icon');
        if (contentArea && expandIcon) {
          contentArea.style.display = 'none';
          expandIcon.style.transform = 'rotate(0deg)';
          outputEl.dataset.expanded = 'false';
        }
      }
    });
  }
  
  // Toggle input expand/collapse
  function toggleInputExpand(inputId) {
    const inputEl = document.getElementById(inputId);
    if (!inputEl) return;
    
    const contentArea = inputEl.querySelector('.guided-input-content');
    const expandIcon = inputEl.querySelector('.guided-input-expand-icon');
    if (!contentArea || !expandIcon) return;
    
    const isExpanded = inputEl.dataset.expanded === 'true';
    if (isExpanded) {
      contentArea.style.display = 'none';
      expandIcon.style.transform = 'rotate(0deg)';
      inputEl.dataset.expanded = 'false';
    } else {
      contentArea.style.display = 'block';
      expandIcon.style.transform = 'rotate(180deg)';
      inputEl.dataset.expanded = 'true';
      // Collapse all other inputs
      collapseAllInputs(inputId);
    }
  }
  
  // Toggle output expand/collapse
  function toggleOutputExpand(outputId) {
    const outputEl = document.getElementById(outputId);
    if (!outputEl) return;
    
    const contentArea = outputEl.querySelector('.guided-output-content');
    const expandIcon = outputEl.querySelector('.guided-output-expand-icon');
    if (!contentArea || !expandIcon) return;
    
    const isExpanded = outputEl.dataset.expanded === 'true';
    if (isExpanded) {
      contentArea.style.display = 'none';
      expandIcon.style.transform = 'rotate(0deg)';
      outputEl.dataset.expanded = 'false';
    } else {
      contentArea.style.display = 'block';
      expandIcon.style.transform = 'rotate(180deg)';
      outputEl.dataset.expanded = 'true';
      // Collapse all other outputs
      collapseAllOutputs(outputId);
    }
  }
  
  // Add guided input
  window.addGuidedInput = async function(type) {
    // Collapse all existing inputs before adding a new one
    collapseAllInputs();
    
    const inputId = `guided-input-${Date.now()}`;
    const inputContainer = document.createElement('div');
    inputContainer.id = inputId;
    inputContainer.dataset.expanded = 'true'; // New input starts expanded
    inputContainer.style.cssText = 'background: var(--bg-card, #ffffff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md); margin-bottom: 12px; overflow: hidden;';
    
    // Create header with expand/collapse
    const header = document.createElement('div');
    header.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 12px; cursor: pointer; background: var(--bg-secondary, #f9fafb);';
    header.onclick = () => toggleInputExpand(inputId);
    
    const headerLeft = document.createElement('div');
    headerLeft.style.cssText = 'display: flex; align-items: center; gap: 8px;';
    
    const expandIcon = document.createElement('svg');
    expandIcon.className = 'guided-input-expand-icon';
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
    titleSpan.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary);';
    titleSpan.textContent = type === 'inventory' ? 'Inventory Input' : 'New Input';
    headerLeft.appendChild(titleSpan);
    
    header.appendChild(headerLeft);
    
    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.onclick = (e) => {
      e.stopPropagation();
      window.removeGuidedInput(inputId);
    };
    removeButton.style.cssText = 'padding: 4px 8px; border: none; background: transparent; color: var(--error, #ef4444); cursor: pointer; font-size: 12px;';
    removeButton.textContent = 'Remove';
    header.appendChild(removeButton);
    
    inputContainer.appendChild(header);
    
    // Create content area
    const contentArea = document.createElement('div');
    contentArea.className = 'guided-input-content';
    contentArea.style.cssText = 'padding: 12px; display: block;';
    
    if (type === 'inventory') {
      // Load inventory items
      const inventoryItems = await loadInventoryItems();
      
      console.log('Loaded inventory items for dropdown:', inventoryItems.length, inventoryItems);
      
      if (inventoryItems.length === 0) {
        // Show a message if no inventory items are available
        const messageDiv = document.createElement('div');
        messageDiv.style.cssText = 'padding: 12px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); color: var(--text-secondary); font-size: 13px;';
        messageDiv.textContent = 'No inventory items available. Please add inventory items first.';
        contentArea.appendChild(messageDiv);
        inputContainer.appendChild(contentArea);
        document.getElementById('guided-inputs-list').appendChild(inputContainer);
        return;
      }
      
      // Name field with searchable dropdown
      const nameField = document.createElement('div');
      nameField.style.marginBottom = '12px';
      const nameLabel = document.createElement('label');
      nameLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      nameLabel.textContent = 'Inventory Item';
      nameField.appendChild(nameLabel);
      
      // Filter out already selected inventory items
      const availableItems = inventoryItems.filter(item => !selectedInventoryItems.has(item.name));
      
      const nameDropdown = createInventorySearchableDropdown(
        availableItems,
        (item) => {
          // When item is selected, update unit if available
          const unitSelect = inputContainer.querySelector('.guided-input-unit');
          if (unitSelect && item.unit) {
            unitSelect.value = item.unit;
          }
          // Mark this item as selected
          selectedInventoryItems.add(item.name);
          // Update the dropdown to exclude this item from other inputs
          updateInventoryDropdowns();
        },
        inputContainer
      );
      nameField.appendChild(nameDropdown);
      inputContainer.appendChild(nameField);
      
      // Quantity field
      const quantityField = document.createElement('div');
      quantityField.style.marginBottom = '12px';
      const quantityLabel = document.createElement('label');
      quantityLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      quantityLabel.textContent = 'Quantity';
      quantityField.appendChild(quantityLabel);
      const quantityInput = document.createElement('input');
      quantityInput.type = 'number';
      quantityInput.className = 'guided-input-quantity';
      quantityInput.placeholder = '0';
      quantityInput.step = '0.01';
      quantityInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
      quantityField.appendChild(quantityInput);
      inputContainer.appendChild(quantityField);
      
      // Unit dropdown
      const unitField = document.createElement('div');
      unitField.style.marginBottom = '12px';
      const unitLabel = document.createElement('label');
      unitLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      unitLabel.textContent = 'Unit';
      unitField.appendChild(unitLabel);
      const unitSelect = document.createElement('select');
      unitSelect.className = 'guided-input-unit form-select';
      unitSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
      [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
        const option = document.createElement('option');
        option.value = unit;
        option.textContent = unit;
        unitSelect.appendChild(option);
      });
      unitField.appendChild(unitSelect);
      inputContainer.appendChild(unitField);
      
      // Execution type dropdown
      const typeField = document.createElement('div');
      const typeLabel = document.createElement('label');
      typeLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      typeLabel.textContent = 'Execution Type';
      typeField.appendChild(typeLabel);
      const typeSelect = document.createElement('select');
      typeSelect.className = 'guided-input-execution-type form-select';
      typeSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
      
      const variableOption = document.createElement('option');
      variableOption.value = 'variable';
      variableOption.textContent = 'Select inventory at execution';
      typeSelect.appendChild(variableOption);
      
      const staticOption = document.createElement('option');
      staticOption.value = 'static';
      staticOption.textContent = 'Use this exact input every execution';
      typeSelect.appendChild(staticOption);
      
      typeField.appendChild(typeSelect);
      
      // Explanation text
      const explanationDiv = document.createElement('div');
      explanationDiv.style.cssText = 'margin-top: 8px; padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); font-size: 12px; color: var(--text-secondary); line-height: 1.4;';
      explanationDiv.id = `guided-input-explanation-${inputId}`;
      explanationDiv.innerHTML = '<strong>Select inventory at execution:</strong> You will choose which supplier batch is consumed when this step runs. This allows you to track specific batches through your process.';
      typeField.appendChild(explanationDiv);
      
      // Update explanation when type changes
      typeSelect.addEventListener('change', function() {
        const explanation = document.getElementById(`guided-input-explanation-${inputId}`);
        if (this.value === 'variable') {
          explanation.innerHTML = '<strong>Select inventory at execution:</strong> You will choose which supplier batch is consumed when this step runs. This allows you to track specific batches through your process.';
        } else {
          explanation.innerHTML = '<strong>Use this exact input every execution:</strong> The system will use the same quantity and unit for every execution without prompting. Use this for consistent inputs that don\'t vary between batches.';
        }
      });
      
      contentArea.appendChild(typeField);
    } else {
      // New Input
      
      // Name field
      const nameField = document.createElement('div');
      nameField.style.marginBottom = '12px';
      const nameLabel = document.createElement('label');
      nameLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      nameLabel.textContent = 'Name';
      nameField.appendChild(nameLabel);
      const nameInput = document.createElement('input');
      nameInput.type = 'text';
      nameInput.className = 'guided-input-name';
      nameInput.placeholder = 'e.g., Water, Additive';
      nameInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
      nameField.appendChild(nameInput);
      inputContainer.appendChild(nameField);
      
      // Quantity field
      const quantityField = document.createElement('div');
      quantityField.style.marginBottom = '12px';
      const quantityLabel = document.createElement('label');
      quantityLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      quantityLabel.textContent = 'Quantity';
      quantityField.appendChild(quantityLabel);
      const quantityInput = document.createElement('input');
      quantityInput.type = 'number';
      quantityInput.className = 'guided-input-quantity';
      quantityInput.placeholder = '0';
      quantityInput.step = '0.01';
      quantityInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
      quantityField.appendChild(quantityInput);
      inputContainer.appendChild(quantityField);
      
      // Unit dropdown
      const unitField = document.createElement('div');
      unitField.style.marginBottom = '12px';
      const unitLabel = document.createElement('label');
      unitLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      unitLabel.textContent = 'Unit';
      unitField.appendChild(unitLabel);
      const unitSelect = document.createElement('select');
      unitSelect.className = 'guided-input-unit form-select';
      unitSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
      [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
        const option = document.createElement('option');
        option.value = unit;
        option.textContent = unit;
        unitSelect.appendChild(option);
      });
      unitField.appendChild(unitSelect);
      inputContainer.appendChild(unitField);
      
      // Execution type dropdown
      const typeField = document.createElement('div');
      const typeLabel = document.createElement('label');
      typeLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      typeLabel.textContent = 'Execution Type';
      typeField.appendChild(typeLabel);
      const typeSelect = document.createElement('select');
      typeSelect.className = 'guided-input-execution-type form-select';
      typeSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
      
      const promptOption = document.createElement('option');
      promptOption.value = 'prompt';
      promptOption.textContent = 'Prompt at execution';
      typeSelect.appendChild(promptOption);
      
      const staticOption = document.createElement('option');
      staticOption.value = 'static';
      staticOption.textContent = 'Use this exact input every execution';
      typeSelect.appendChild(staticOption);
      
      typeField.appendChild(typeSelect);
      
      // Explanation text
      const explanationDiv = document.createElement('div');
      explanationDiv.style.cssText = 'margin-top: 8px; padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); font-size: 12px; color: var(--text-secondary); line-height: 1.4;';
      explanationDiv.id = `guided-input-explanation-${inputId}`;
      explanationDiv.innerHTML = '<strong>Prompt at execution:</strong> You will be asked to enter or confirm the quantity and unit when this step runs. Use this for inputs that may vary between executions.';
      typeField.appendChild(explanationDiv);
      
      // Update explanation when type changes
      typeSelect.addEventListener('change', function() {
        const explanation = document.getElementById(`guided-input-explanation-${inputId}`);
        if (this.value === 'prompt') {
          explanation.innerHTML = '<strong>Prompt at execution:</strong> You will be asked to enter or confirm the quantity and unit when this step runs. Use this for inputs that may vary between executions.';
        } else {
          explanation.innerHTML = '<strong>Use this exact input every execution:</strong> The system will use the same quantity and unit for every execution without prompting. Use this for consistent inputs that don\'t vary between batches.';
        }
      });
      
      contentArea.appendChild(typeField);
    }
    
    inputContainer.appendChild(contentArea);
    document.getElementById('guided-inputs-list').appendChild(inputContainer);
  };
  
  // Update all inventory dropdowns to exclude selected items
  function updateInventoryDropdowns() {
    const allInputs = document.querySelectorAll('#guided-inputs-list > div');
    allInputs.forEach(inputEl => {
      const nameInput = inputEl.querySelector('.guided-input-name.searchable-dropdown-input');
      if (nameInput) {
        // This is an inventory input - we'd need to rebuild the dropdown
        // For now, we'll just filter on the fly when showing dropdown
      }
    });
  }
  
  // Remove guided input
  window.removeGuidedInput = function(inputId) {
    const inputElement = document.getElementById(inputId);
    if (inputElement) {
      // Get the selected inventory item name before removing
      const nameInput = inputElement.querySelector('.guided-input-name.searchable-dropdown-input');
      if (nameInput && nameInput.value) {
        selectedInventoryItems.delete(nameInput.value.trim());
      }
      inputElement.remove();
    }
  };
  
  // Add guided output
  window.addGuidedOutput = function() {
    // Collapse all existing outputs before adding a new one
    collapseAllOutputs();
    
    const outputId = `guided-output-${Date.now()}`;
    const outputContainer = document.createElement('div');
    outputContainer.id = outputId;
    outputContainer.dataset.expanded = 'true'; // New output starts expanded
    outputContainer.style.cssText = 'background: var(--bg-card, #ffffff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md); margin-bottom: 12px; overflow: hidden;';
    
    // Create header with expand/collapse
    const header = document.createElement('div');
    header.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 12px; cursor: pointer; background: var(--bg-secondary, #f9fafb);';
    header.onclick = () => toggleOutputExpand(outputId);
    
    const headerLeft = document.createElement('div');
    headerLeft.style.cssText = 'display: flex; align-items: center; gap: 8px;';
    
    const expandIcon = document.createElement('svg');
    expandIcon.className = 'guided-output-expand-icon';
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
    titleSpan.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary);';
    titleSpan.textContent = 'Output';
    headerLeft.appendChild(titleSpan);
    
    header.appendChild(headerLeft);
    
    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.onclick = (e) => {
      e.stopPropagation();
      window.removeGuidedOutput(outputId);
    };
    removeButton.style.cssText = 'padding: 4px 8px; border: none; background: transparent; color: var(--error, #ef4444); cursor: pointer; font-size: 12px;';
    removeButton.textContent = 'Remove';
    header.appendChild(removeButton);
    
    outputContainer.appendChild(header);
    
    // Create content area
    const contentArea = document.createElement('div');
    contentArea.className = 'guided-output-content';
    contentArea.style.cssText = 'padding: 12px; display: block;';
    
    // Name field
    const nameField = document.createElement('div');
    nameField.style.marginBottom = '12px';
    const nameLabel = document.createElement('label');
    nameLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    nameLabel.textContent = 'Name';
    nameField.appendChild(nameLabel);
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'guided-output-name';
    nameInput.placeholder = 'e.g., Mixed Base, Final Product';
    nameInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
    nameField.appendChild(nameInput);
    contentArea.appendChild(nameField);
    
    // Quantity field
    const quantityField = document.createElement('div');
    quantityField.style.marginBottom = '12px';
    const quantityLabel = document.createElement('label');
    quantityLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    quantityLabel.textContent = 'Quantity';
    quantityField.appendChild(quantityLabel);
    const quantityInput = document.createElement('input');
    quantityInput.type = 'number';
    quantityInput.className = 'guided-output-quantity';
    quantityInput.placeholder = '0';
    quantityInput.step = '0.01';
    quantityInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
    quantityField.appendChild(quantityInput);
    contentArea.appendChild(quantityField);
    
    // Unit dropdown
    const unitField = document.createElement('div');
    unitField.style.marginBottom = '12px';
    const unitLabel = document.createElement('label');
    unitLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    unitLabel.textContent = 'Unit';
    unitField.appendChild(unitLabel);
    const unitSelect = document.createElement('select');
    unitSelect.className = 'guided-output-unit form-select';
    unitSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
    [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
      const option = document.createElement('option');
      option.value = unit;
      option.textContent = unit;
      unitSelect.appendChild(option);
    });
    unitField.appendChild(unitSelect);
    contentArea.appendChild(unitField);
    
    outputContainer.appendChild(contentArea);
    document.getElementById('guided-outputs-list').appendChild(outputContainer);
  };
  
  // Remove guided output
  window.removeGuidedOutput = function(outputId) {
    const outputElement = document.getElementById(outputId);
    if (outputElement) {
      outputElement.remove();
    }
  };
  
  // Create step from guided flow
  window.createProcessFromGuidedFlow = async function() {
    const stepName = document.getElementById('guided-step-name').value.trim();
    const stepDescription = document.getElementById('guided-step-description').value.trim();
    
    if (!stepName) {
      alert('Please enter a step name');
      return;
    }
    
    // Collect inputs
    const inputs = [];
    const inputElements = document.querySelectorAll('#guided-inputs-list > div');
    inputElements.forEach(inputEl => {
      // Get name - could be from searchable dropdown (input) or regular input
      const nameInput = inputEl.querySelector('.guided-input-name');
      let name = '';
      if (nameInput) {
        // Check if it's a searchable dropdown input or regular input
        if (nameInput.classList.contains('searchable-dropdown-input')) {
          name = nameInput.value.trim();
        } else {
          name = nameInput.value.trim();
        }
      }
      
      // Get quantity
      const quantityInput = inputEl.querySelector('.guided-input-quantity');
      const quantity = quantityInput ? (quantityInput.value || '').trim() : '';
      
      // Get unit from dropdown
      const unitSelect = inputEl.querySelector('.guided-input-unit');
      const unit = unitSelect ? unitSelect.value : '';
      
      // Get execution type
      const executionTypeSelect = inputEl.querySelector('.guided-input-execution-type');
      const executionType = executionTypeSelect ? executionTypeSelect.value : 'prompt';
      
      if (name && unit) {
        // Map execution type to the existing structure
        // variable = Select inventory at execution (requires_inventory_selection: true, is_variable: true)
        // static = Use exact input (is_variable: false, requires_inventory_selection: false)
        // prompt = Prompt at execution (is_variable: true, requires_inventory_selection: false)
        const isVariable = executionType === 'variable' || executionType === 'prompt';
        const requiresInventorySelection = executionType === 'variable';
        
        inputs.push({
          name: name,
          quantity: quantity ? parseFloat(quantity) : null,
          unit: unit,
          is_variable: isVariable,
          requires_inventory_selection: requiresInventorySelection
        });
      }
    });
    
    // Collect outputs
    const outputs = [];
    const outputElements = document.querySelectorAll('#guided-outputs-list > div');
    outputElements.forEach(outputEl => {
      const name = outputEl.querySelector('.guided-output-name')?.value.trim();
      const unitSelect = outputEl.querySelector('.guided-output-unit');
      const unit = unitSelect ? unitSelect.value : '';
      const quantityInput = outputEl.querySelector('.guided-output-quantity');
      const quantity = quantityInput ? (quantityInput.value || '').trim() : '';
      
      if (name && unit) {
        // Outputs are automatically added to inventory (can be used in subsequent steps)
        outputs.push({
          name: name,
          unit: unit,
          quantity: quantity ? parseFloat(quantity) : null,
          is_variable: true, // Outputs are always variable (can be used in subsequent steps)
          requires_execution_confirmation: true
        });
      }
    });
    
    // Get process ID from the page
    const processId = window.processId;
    if (!processId) {
      alert('Process ID is missing');
      return;
    }
    
    // Calculate step number
    const stepsContainer = document.getElementById('steps-container');
    const stepCount = stepsContainer ? stepsContainer.querySelectorAll('.step-card').length + 1 : 1;
    
    try {
      // Create the step via API
      const stepData = {
        step_number: stepCount,
        name: stepName,
        description: stepDescription,
        inputs: inputs,
        outputs: outputs
      };
      
      const saved = await CoreAPI.createStep(processId, stepData);
      
      if (saved && saved.id) {
        // Close modal
        closeModal();
        resetForm();
        
        // Reload steps
        if (window.loadSteps) {
          await window.loadSteps();
        }
        
        // Show success notification
        if (window.showNotification) {
          window.showNotification('success', 'Step Created', `"${stepName}" has been created successfully`);
        }
      }
    } catch (error) {
      console.error('Failed to create step:', error);
      alert('Failed to create step: ' + (error.message || 'Unknown error'));
    }
  };
  
  // Close modal on overlay click or close button
  document.addEventListener('DOMContentLoaded', function() {
    const modal = document.getElementById('create-process-modal');
    if (modal) {
      // Close on overlay click
      modal.addEventListener('click', function(e) {
        if (e.target === modal) {
          closeModal();
        }
      });
      
      // Close on close button
      const closeButtons = modal.querySelectorAll('[data-modal-close]');
      closeButtons.forEach(btn => {
        btn.addEventListener('click', closeModal);
      });
    }
  });
})();
