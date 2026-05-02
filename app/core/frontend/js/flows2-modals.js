    window.openModal = function(modalId) {
      const modal = document.getElementById(modalId);
      if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
      }
    };
    
    window.closeModal = function(modalId) {
      const modal = document.getElementById(modalId);
      if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = '';
      }
    };
    
    function initializeModals() {
      // Open modal buttons
      const modalTriggers = document.querySelectorAll('[data-modal-open]');
      modalTriggers.forEach(trigger => {
        trigger.addEventListener('click', function(e) {
          e.preventDefault();
          e.stopPropagation();
          const modalId = this.getAttribute('data-modal-open');
          window.openModal(modalId);
        });
      });
      
      // Close modal buttons
      const closeButtons = document.querySelectorAll('[data-modal-close]');
      closeButtons.forEach(button => {
        button.addEventListener('click', function(e) {
          e.preventDefault();
          e.stopPropagation();
          const modal = this.closest('.modal-overlay');
          if (modal) window.closeModal(modal.id);
        });
      });
      
      // Close on overlay click - DISABLED to prevent accidental closes
      // const overlays = document.querySelectorAll('.modal-overlay');
      // overlays.forEach(overlay => {
      //   overlay.addEventListener('click', function(e) {
      //     if (e.target === this) {
      //       window.closeModal(this.id);
      //     }
      //   });
      // });
      
      // Close on Escape key
      document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
          document.querySelectorAll('.modal-overlay').forEach(modal => {
            if (modal.style.display === 'flex') {
              window.closeModal(modal.id);
            }
          });
        }
      });
    }
    
    // Tab switching and modal initialization
    function initializePage() {
      // Tab switching
      document.querySelectorAll('.tab-trigger').forEach(trigger => {
        trigger.addEventListener('click', () => {
          // Remove active from all triggers and contents
          document.querySelectorAll('.tab-trigger').forEach(t => t.classList.remove('active'));
          document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
          
          // Activate clicked tab
          trigger.classList.add('active');
          const tabId = trigger.getAttribute('data-tab');
          document.getElementById(tabId).classList.add('active');
        });
      });
      
      // Initialize modals
      initializeModals();
    }
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initializePage);
    } else {
      // DOM is already loaded
      initializePage();
    }
    
    async function addInventoryItem(form) {
      const formData = new FormData(form);
      const data = {
        name: formData.get('name'),
        quantity: parseFloat(formData.get('quantity')),
        unit: formData.get('unit'),
        inventory_type: 'raw_material',
        supplier: formData.get('supplier') || null,
        purchase_date: formData.get('purchaseDate') || null,
        supplier_batch_number: formData.get('batchNumber') || null,
        expiry_date: formData.get('expiryDate') || null,
        process_id: processId || null,
      };
      
      try {
        const saved = await CoreAPI.createInventoryItem(data);
        
        // Close modal
        closeModal('add-inventory-modal');
        
        // Reset form
        form.reset();
        
        // Reload inventory
        await loadInventory();
        
        // If added from execution modal (missing raw material), refresh step dropdown and select new item
        if (window.addInventoryContext && window.addInventoryContext.fromExecutionModal && typeof window.refreshExecutionModalInventory === 'function') {
          await window.refreshExecutionModalInventory(saved);
        }
        
        showNotification('success', 'Inventory Item Added', `"${data.name}" has been added to inventory successfully.`);
        
        return false; // Prevent form submission
      } catch (error) {
        console.error('Failed to add inventory item:', error);
        showNotification('error', 'Failed to Add Inventory Item', error.message || 'Failed to add inventory item. Please try again.');
        return false;
      }
    }
    // ============================================================
    // LOAD RAW MATERIALS FOR DROPDOWN
    // ============================================================
    let rawMaterialsCache = null;
    
    async function loadRawMaterials() {
      if (rawMaterialsCache) {
        return rawMaterialsCache;
      }
      
      try {
        const inventoryData = await CoreAPI.getInventory('raw_material');
        rawMaterialsCache = inventoryData.inventory_items || [];
        return rawMaterialsCache;
      } catch (error) {
        console.error('Failed to load raw materials:', error);
        return [];
      }
    }
    
    // ============================================================
    // UNIT GROUPS FOR SMART UNIT SELECTION
    // ============================================================
    const unitGroups = {
      weight: ['kg', 'g'],
      volume: ['L', 'mL'],
      count: ['pcs', 'units']
    };
    
    function getUnitGroup(unit) {
      for (const [group, units] of Object.entries(unitGroups)) {
        if (units.includes(unit)) {
          return group;
        }
      }
      return null;
    }
    
    function getRelatedUnits(unit) {
      const group = getUnitGroup(unit);
      if (group) {
        return unitGroups[group];
      }
      // If unit not found in groups, return all units
      return [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count];
    }
    
    function updateUnitDropdown(unitSelect, selectedUnit) {
      if (!selectedUnit) {
        // Show all units
        unitSelect.replaceChildren();
        [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
          const option = document.createElement('option');
          option.value = unit;
          option.textContent = unit;
          unitSelect.appendChild(option);
        });
        return;
      }
      
      const relatedUnits = getRelatedUnits(selectedUnit);
      const currentValue = unitSelect.value;
      
      unitSelect.replaceChildren();
      relatedUnits.forEach(unit => {
        const option = document.createElement('option');
        option.value = unit;
        option.textContent = unit;
        if (unit === currentValue || (currentValue === '' && unit === selectedUnit)) {
          option.selected = true;
        }
        unitSelect.appendChild(option);
      });
    }
    
    // ============================================================
    // SEARCHABLE DROPDOWN COMPONENT
    // ============================================================
    function createSearchableDropdown(items, onSelect, placeholder = 'Search raw materials or type new input...', unitSelect = null) {
      const uniqueId = `dropdown-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      const container = document.createElement('div');
      container.className = 'searchable-dropdown-container';
      container.style.position = 'relative';
      container.style.flex = '1';
      
      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'form-input io-name-input searchable-dropdown-input';
      input.setAttribute('placeholder', placeholder);
      input.setAttribute('autocomplete', 'off');
      input.setAttribute('data-dropdown-id', uniqueId);
      input.style.cssText =
        'width: 100%; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      const dropdown = document.createElement('div');
      dropdown.className = 'searchable-dropdown-list';
      dropdown.id = uniqueId;
      dropdown.style.cssText =
        'display: none; position: absolute; top: 100%; left: 0; right: 0; z-index: 1000; max-height: 200px; overflow-y: auto; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); margin-top: 4px; box-shadow: var(--shadow-lg, 0 8px 24px rgba(0, 0, 0, 0.12));';
      container.appendChild(input);
      container.appendChild(dropdown);
      let filteredItems = items;
      let selectedIndex = -1;
      const originalItems = items; // Keep reference to original items for comparison
      
      function renderDropdown() {
        dropdown.replaceChildren();
        if (filteredItems.length === 0) {
          const empty = document.createElement('div');
          empty.style.cssText =
            'padding: 12px; color: var(--text-secondary); text-align: center; font-size: 14px;';
          empty.textContent = 'No materials found';
          dropdown.appendChild(empty);
        } else {
          filteredItems.forEach((item, index) => {
            const baseDisplayName = item.displayName || item.name;
            const displayName = item.process_name ? `${item.process_name} - ${baseDisplayName}` : baseDisplayName;
            const row = document.createElement('div');
            row.className = 'dropdown-item' + (index === selectedIndex ? ' selected' : '');
            row.setAttribute('data-index', String(index));
            row.style.cssText =
              'padding: 10px 12px; cursor: pointer; border-bottom: 1px solid var(--border-light); transition: background 0.15s;';
            if (index === selectedIndex) {
              row.style.background = 'var(--bg-hover, rgba(0, 0, 0, 0.05))';
            }
            const line1 = document.createElement('div');
            line1.style.cssText = 'font-weight: 500; color: var(--text-primary); font-size: 14px;';
            line1.textContent = displayName;
            const line2 = document.createElement('div');
            line2.style.cssText = 'font-size: 12px; color: var(--text-secondary); margin-top: 2px;';
            line2.textContent = `${item.quantity || '0'} ${item.unit || ''}`.trim();
            row.appendChild(line1);
            row.appendChild(line2);
            row.addEventListener('mouseenter', () => {
              if (index !== selectedIndex) row.style.background = 'var(--bg-hover, rgba(0, 0, 0, 0.05))';
            });
            row.addEventListener('mouseleave', () => {
              if (index !== selectedIndex) row.style.background = 'transparent';
            });
            dropdown.appendChild(row);
          });
        }
        dropdown.style.display = filteredItems.length > 0 || input.value.trim() ? 'block' : 'none';
      }
      
      function filterItems(searchTerm) {
        const term = searchTerm.toLowerCase().trim();
        if (!term) {
          filteredItems = items;
        } else {
          filteredItems = items.filter(item => {
            const name = item.name.toLowerCase();
            const displayName = item.displayName ? item.displayName.toLowerCase() : '';
            const processName = item.process_name ? item.process_name.toLowerCase() : '';
            // Search in product name, display name, and process name
            return name.includes(term) || displayName.includes(term) || processName.includes(term);
          });
        }
        selectedIndex = -1;
        renderDropdown();
      }
      
      function selectItem(item) {
        if (onSelect) {
          onSelect(item);
        }
        input.value = item.name;
        // Update hidden input
        const hiddenInput = container.closest('.io-item')?.querySelector('.io-name-input-hidden');
        if (hiddenInput) {
          hiddenInput.value = item.name;
        }
        // Update unit dropdown if provided
        if (unitSelect && item.unit) {
          updateUnitDropdown(unitSelect, item.unit);
        }
        dropdown.style.display = 'none';
      }
      
      input.addEventListener('input', (e) => {
        const value = e.target.value;
        filterItems(value);
        // Always update hidden input when user types manually (for saving)
        const hiddenInput = container.closest('.io-item')?.querySelector('.io-name-input-hidden');
        if (hiddenInput) {
          hiddenInput.value = value.trim();
        }
        // If user is typing manually (not selecting from dropdown), show all units
        // Check if the typed value exactly matches any item name from original items
        const exactMatch = originalItems.find(item => item.name.toLowerCase() === value.toLowerCase().trim());
        if (unitSelect && !exactMatch && value.trim()) {
          // User is typing a custom name, show all units
          updateUnitDropdown(unitSelect, null);
        }
      });
      
      input.addEventListener('focus', () => {
        if (input.value.trim()) {
          filterItems(input.value);
        } else {
          filteredItems = items;
          renderDropdown();
        }
      });
      
      input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          selectedIndex = Math.min(selectedIndex + 1, filteredItems.length - 1);
          renderDropdown();
          const selectedEl = dropdown.querySelector(`[data-index="${selectedIndex}"]`);
          if (selectedEl) {
            selectedEl.scrollIntoView({ block: 'nearest' });
          }
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          selectedIndex = Math.max(selectedIndex - 1, -1);
          renderDropdown();
        } else if (e.key === 'Enter' && selectedIndex >= 0 && filteredItems[selectedIndex]) {
          e.preventDefault();
          selectItem(filteredItems[selectedIndex]);
        } else if (e.key === 'Escape') {
          dropdown.style.display = 'none';
        }
      });
      
      dropdown.addEventListener('click', (e) => {
        const itemEl = e.target.closest('.dropdown-item');
        if (itemEl) {
          const index = parseInt(itemEl.getAttribute('data-index'));
          if (filteredItems[index]) {
            selectItem(filteredItems[index]);
          }
        }
      });
      
      // Close dropdown when clicking outside
      document.addEventListener('click', (e) => {
        if (!container.contains(e.target)) {
          dropdown.style.display = 'none';
        }
      });
      
      return container;
    }
    window.addInputFromInventory = async function(button) {
      const ioSection = button.closest('.io-section');
      const ioList = ioSection.querySelector('.io-list');
      
      // Remove "No inputs defined" message if present
      const emptyMsg = ioList.querySelector('p');
      if (emptyMsg && emptyMsg.textContent.includes('No inputs defined')) {
        emptyMsg.remove();
      }
      
      // Load raw materials
      const rawMaterials = await loadRawMaterials();
      
      const ioItem = document.createElement('div');
      ioItem.className = 'io-item';
      ioItem.style.cssText = 'display: flex; align-items: center; gap: 8px; padding: 8px; border: 1px solid var(--border-light); border-radius: var(--radius-md); margin-bottom: 8px;';
      
      // Create searchable dropdown for material name
      const nameContainer = document.createElement('span');
      nameContainer.className = 'io-item-name';
      nameContainer.style.flex = '1';
      
      // Create unit select first so we can pass it to dropdown
      const unitSelect = document.createElement('select');
      unitSelect.className = 'form-select io-unit-input';
      unitSelect.style.cssText = 'width: 90px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      // Initialize with all units
      [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
        const option = document.createElement('option');
        option.value = unit;
        option.textContent = unit;
        unitSelect.appendChild(option);
      });
      
      const dropdown = createSearchableDropdown(
        rawMaterials,
        (item) => {
          // When item is selected, update the hidden input and unit dropdown
          const hiddenInput = ioItem.querySelector('.io-name-input-hidden');
          if (hiddenInput) {
            hiddenInput.value = item.name;
          }
          // Update unit dropdown with smart units
          if (item.unit) {
            updateUnitDropdown(unitSelect, item.unit);
          }
        },
        'Search raw materials or type new input...',
        unitSelect
      );
      
      // Add hidden input to store the actual name value
      const hiddenInput = document.createElement('input');
      hiddenInput.type = 'hidden';
      hiddenInput.className = 'io-name-input-hidden';
      hiddenInput.value = '';
      
      nameContainer.appendChild(dropdown);
      nameContainer.appendChild(hiddenInput);
      
      // Quantity input
      const quantitySpan = document.createElement('span');
      quantitySpan.className = 'io-item-quantity';
      const quantityInput = document.createElement('input');
      quantityInput.type = 'number';
      quantityInput.className = 'form-input io-quantity-input';
      quantityInput.placeholder = '0';
      quantityInput.style.cssText = 'width: 80px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      quantitySpan.appendChild(quantityInput);
      
      // Unit select (already created above, just need to add to span)
      const unitSpan = document.createElement('span');
      unitSpan.className = 'io-item-unit';
      unitSpan.appendChild(unitSelect);
      
      // Listen for manual unit changes to update dropdown if needed
      unitSelect.addEventListener('change', () => {
        // If user manually changes unit, we don't need to do anything special
        // The smart units are only applied when selecting from inventory
      });
      
      // Type select
      const typeSpan = document.createElement('span');
      typeSpan.className = 'io-item-type';
      typeSpan.style.position = 'relative';
      const typeSelect = document.createElement('select');
      typeSelect.className = 'form-select io-type-input';
      typeSelect.style.cssText = 'width: 180px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      const variableOption = document.createElement('option');
      variableOption.value = 'variable';
      variableOption.textContent = 'Select inventory at execution';
      typeSelect.appendChild(variableOption);
      const staticOption = document.createElement('option');
      staticOption.value = 'static';
      staticOption.textContent = 'Static';
      typeSelect.appendChild(staticOption);
      typeSpan.appendChild(typeSelect);
      
      // Tooltip icon
      const tooltipIcon = document.createElement('span');
      tooltipIcon.className = 'tooltip-icon';
      tooltipIcon.style.cssText = 'margin-left: 4px; cursor: help; color: var(--text-tertiary);';
      tooltipIcon.title = 'Select inventory at execution: You will choose which supplier batch is consumed when this step runs. Do NOT ask for batch numbers here. Static: System will not prompt for confirmation upon execution.';
      tooltipIcon.replaceChildren(flows2SvgHelpCircle14());
      typeSpan.appendChild(tooltipIcon);
      
      // Delete button
      const deleteButton = document.createElement('button');
      deleteButton.className = 'btn btn-ghost btn-icon btn-sm';
      deleteButton.style.padding = '4px';
      deleteButton.onclick = function() {
        ioItem.remove();
        updateStepMeta(button.closest('.step-card'));
      };
      deleteButton.replaceChildren(flows2SvgCloseX14());
      
      // Assemble the item
      ioItem.appendChild(nameContainer);
      ioItem.appendChild(quantitySpan);
      ioItem.appendChild(unitSpan);
      ioItem.appendChild(typeSpan);
      ioItem.appendChild(deleteButton);
      
      ioList.appendChild(ioItem);
      
      // Update step meta
      updateStepMeta(button.closest('.step-card'));
    };
    
    // ============================================================
    // ADD INPUT FROM PREVIOUS OUTPUT
    // ============================================================
    window.addInputFromPreviousOutput = async function(button) {
      const ioSection = button.closest('.io-section');
      const ioList = ioSection.querySelector('.io-list');
      const stepCard = button.closest('.step-card');
      
      // Remove "No inputs defined" message if present
      const emptyMsg = ioList.querySelector('p');
      if (emptyMsg && emptyMsg.textContent.includes('No inputs defined')) {
        emptyMsg.remove();
      }
      
      // Get previous step outputs
      const previousOutputs = getPreviousStepOutputs(stepCard);
      
      if (previousOutputs.length === 0) {
        showNotification('info', 'No Previous Outputs', 'There are no outputs from previous steps to use as inputs.');
        return;
      }
      
      const ioItem = document.createElement('div');
      ioItem.className = 'io-item';
      ioItem.style.cssText = 'display: flex; align-items: center; gap: 8px; padding: 8px; border: 1px solid var(--border-light); border-radius: var(--radius-md); margin-bottom: 8px;';
      
      // Create searchable dropdown for output name
      const nameContainer = document.createElement('span');
      nameContainer.className = 'io-item-name';
      nameContainer.style.flex = '1';
      
      // Create unit select
      const unitSelect = document.createElement('select');
      unitSelect.className = 'form-select io-unit-input';
      unitSelect.style.cssText = 'width: 90px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      // Initialize with all units
      [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
        const option = document.createElement('option');
        option.value = unit;
        option.textContent = unit;
        unitSelect.appendChild(option);
      });
      
      // Format items for dropdown (add step number prefix for display)
      const formattedOutputs = previousOutputs.map(output => ({
        ...output,
        displayName: `Step ${output.step_number}: ${output.name}`
      }));
      
      const dropdown = createSearchableDropdown(
        formattedOutputs,
        (item) => {
          // When item is selected, update the hidden input, quantity, and unit
          const hiddenInput = ioItem.querySelector('.io-name-input-hidden');
          if (hiddenInput) {
            hiddenInput.value = item.name;
          }
          // Set quantity and unit from the output
          const quantityInput = ioItem.querySelector('.io-quantity-input');
          if (quantityInput && item.quantity !== null) {
            quantityInput.value = item.quantity;
          }
          // Set unit (show all units but select the output's unit)
          if (item.unit) {
            unitSelect.value = item.unit;
          }
        },
        'Select from previous step outputs...',
        unitSelect
      );
      
      // Add hidden input to store the actual name value
      const hiddenInput = document.createElement('input');
      hiddenInput.type = 'hidden';
      hiddenInput.className = 'io-name-input-hidden';
      hiddenInput.value = '';
      
      nameContainer.appendChild(dropdown);
      nameContainer.appendChild(hiddenInput);
      
      // Quantity input
      const quantitySpan = document.createElement('span');
      quantitySpan.className = 'io-item-quantity';
      const quantityInput = document.createElement('input');
      quantityInput.type = 'number';
      quantityInput.className = 'form-input io-quantity-input';
      quantityInput.placeholder = '0';
      quantityInput.style.cssText = 'width: 80px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      quantitySpan.appendChild(quantityInput);
      
      // Unit select
      const unitSpan = document.createElement('span');
      unitSpan.className = 'io-item-unit';
      unitSpan.appendChild(unitSelect);
      
      // Type select
      const typeSpan = document.createElement('span');
      typeSpan.className = 'io-item-type';
      typeSpan.style.position = 'relative';
      const typeSelect = document.createElement('select');
      typeSelect.className = 'form-select io-type-input';
      typeSelect.style.cssText = 'width: 180px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      const variableOption = document.createElement('option');
      variableOption.value = 'variable';
      variableOption.textContent = 'Select inventory at execution';
      typeSelect.appendChild(variableOption);
      const staticOption = document.createElement('option');
      staticOption.value = 'static';
      staticOption.textContent = 'Static';
      typeSelect.appendChild(staticOption);
      // Set default to "Select inventory at execution" (variable) for outputs
      typeSelect.value = 'variable';
      // Mark this as created from output for confirmation dialog
      typeSelect.dataset.fromOutput = 'true';
      // Add change listener to show confirmation when changing away from "Select inventory at execution"
      typeSelect.addEventListener('change', function() {
        if (this.dataset.fromOutput === 'true' && this.value === 'static') {
          // Show custom modal instead of browser confirm
          showStaticInputWarningModal((confirmed) => {
            if (!confirmed) {
              // Revert to "Select inventory at execution"
              this.value = 'variable';
            }
          });
        }
      });
      typeSpan.appendChild(typeSelect);
      
      // Tooltip icon
      const tooltipIcon = document.createElement('span');
      tooltipIcon.className = 'tooltip-icon';
      tooltipIcon.style.cssText = 'margin-left: 4px; cursor: help; color: var(--text-tertiary);';
      tooltipIcon.title = 'Select inventory at execution: You will choose which supplier batch is consumed when this step runs. Do NOT ask for batch numbers here. Static: System will not prompt for confirmation upon execution.';
      tooltipIcon.replaceChildren(flows2SvgHelpCircle14());
      typeSpan.appendChild(tooltipIcon);
      
      // Delete button
      const deleteButton = document.createElement('button');
      deleteButton.className = 'btn btn-ghost btn-icon btn-sm';
      deleteButton.style.cssText = 'padding: 4px;';
      deleteButton.onclick = function() {
        ioItem.remove();
        updateStepMeta(stepCard);
        if (ioList.querySelectorAll('.io-item').length === 0) {
          const emptyMsg = document.createElement('p');
          emptyMsg.style.cssText = 'color: var(--text-secondary); font-size: 14px; padding: 0.625rem 0.75rem;';
          emptyMsg.textContent = 'No inputs defined';
          ioList.appendChild(emptyMsg);
        }
      };
      deleteButton.replaceChildren(flows2SvgCloseX14());
      
      // Assemble the item
      ioItem.appendChild(nameContainer);
      ioItem.appendChild(quantitySpan);
      ioItem.appendChild(unitSpan);
      ioItem.appendChild(typeSpan);
      ioItem.appendChild(deleteButton);
      
      ioList.appendChild(ioItem);
      updateStepMeta(stepCard);
    };
    
    // ============================================================
    // ADD NEW INPUT (manual entry)
    // ============================================================
    window.addNewInput = function(button) {
      const ioSection = button.closest('.io-section');
      const ioList = ioSection.querySelector('.io-list');
      const stepCard = button.closest('.step-card');
      
      // Remove "No inputs defined" message if present
      const emptyMsg = ioList.querySelector('p');
      if (emptyMsg && emptyMsg.textContent.includes('No inputs defined')) {
        emptyMsg.remove();
      }
      
      const ioItem = document.createElement('div');
      ioItem.className = 'io-item';
      ioItem.style.cssText = 'display: flex; align-items: center; gap: 8px; padding: 8px; border: 1px solid var(--border-light); border-radius: var(--radius-md); margin-bottom: 8px;';
      
      // Name input (regular text input, no dropdown)
      const nameContainer = document.createElement('span');
      nameContainer.className = 'io-item-name';
      nameContainer.style.flex = '1';
      const nameInput = document.createElement('input');
      nameInput.type = 'text';
      nameInput.className = 'form-input io-name-input';
      nameInput.placeholder = 'Enter input name';
      nameInput.style.cssText = 'width: 100%; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      nameContainer.appendChild(nameInput);
      
      // Quantity input
      const quantitySpan = document.createElement('span');
      quantitySpan.className = 'io-item-quantity';
      const quantityInput = document.createElement('input');
      quantityInput.type = 'number';
      quantityInput.className = 'form-input io-quantity-input';
      quantityInput.placeholder = '0';
      quantityInput.style.cssText = 'width: 80px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      quantitySpan.appendChild(quantityInput);
      
      // Unit select (all units available)
      const unitSpan = document.createElement('span');
      unitSpan.className = 'io-item-unit';
      const unitSelect = document.createElement('select');
      unitSelect.className = 'form-select io-unit-input';
      unitSelect.style.cssText = 'width: 90px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
        const option = document.createElement('option');
        option.value = unit;
        option.textContent = unit;
        unitSelect.appendChild(option);
      });
      unitSpan.appendChild(unitSelect);
      
      // Type select
      const typeSpan = document.createElement('span');
      typeSpan.className = 'io-item-type';
      typeSpan.style.position = 'relative';
      const typeSelect = document.createElement('select');
      typeSelect.className = 'form-select io-type-input';
      typeSelect.style.cssText = 'width: 180px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      const variableOption = document.createElement('option');
      variableOption.value = 'variable';
      variableOption.textContent = 'Select inventory at execution';
      typeSelect.appendChild(variableOption);
      const staticOption = document.createElement('option');
      staticOption.value = 'static';
      staticOption.textContent = 'Static';
      typeSelect.appendChild(staticOption);
      typeSpan.appendChild(typeSelect);
      
      // Tooltip icon
      const tooltipIcon = document.createElement('span');
      tooltipIcon.className = 'tooltip-icon';
      tooltipIcon.style.cssText = 'margin-left: 4px; cursor: help; color: var(--text-tertiary);';
      tooltipIcon.title = 'Select inventory at execution: You will choose which supplier batch is consumed when this step runs. Do NOT ask for batch numbers here. Static: System will not prompt for confirmation upon execution.';
      tooltipIcon.replaceChildren(flows2SvgHelpCircle14());
      typeSpan.appendChild(tooltipIcon);
      
      // Delete button
      const deleteButton = document.createElement('button');
      deleteButton.className = 'btn btn-ghost btn-icon btn-sm';
      deleteButton.style.cssText = 'padding: 4px;';
      deleteButton.onclick = function() {
        ioItem.remove();
        updateStepMeta(stepCard);
        if (ioList.querySelectorAll('.io-item').length === 0) {
          const emptyMsg = document.createElement('p');
          emptyMsg.style.cssText = 'color: var(--text-secondary); font-size: 14px; padding: 0.625rem 0.75rem;';
          emptyMsg.textContent = 'No inputs defined';
          ioList.appendChild(emptyMsg);
        }
      };
      deleteButton.replaceChildren(flows2SvgCloseX14());
      
      // Assemble the item
      ioItem.appendChild(nameContainer);
      ioItem.appendChild(quantitySpan);
      ioItem.appendChild(unitSpan);
      ioItem.appendChild(typeSpan);
      ioItem.appendChild(deleteButton);
      
      ioList.appendChild(ioItem);
      updateStepMeta(stepCard);
    };
    
    // ============================================================
    // ADD EXECUTION PROMPT
    // ============================================================
    window.addExecutionPrompt = function(button) {
      const ioSection = button.closest('.io-section');
      const ioList = ioSection.querySelector('.io-list');
      const stepCard = button.closest('.step-card');

      const emptyMsg = ioList.querySelector('p');
      if (emptyMsg && emptyMsg.textContent.includes('No execution prompts defined')) {
        emptyMsg.remove();
      }

      const ioItem = document.createElement('div');
      ioItem.className = 'io-item';
      ioItem.style.cssText =
        'display: flex; align-items: center; gap: 8px; padding: 8px; border: 1px solid var(--border-light); border-radius: var(--radius-md); margin-bottom: 8px;';

      const nameSpan = document.createElement('span');
      nameSpan.className = 'io-item-name';
      nameSpan.style.flex = '1';
      const labelIn = document.createElement('input');
      labelIn.type = 'text';
      labelIn.className = 'form-input prompt-label-input';
      labelIn.placeholder = 'Label (e.g., Batch number)';
      labelIn.style.cssText =
        'width: 100%; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      nameSpan.appendChild(labelIn);

      const typeSpan1 = document.createElement('span');
      typeSpan1.className = 'io-item-type';
      const typeSel = document.createElement('select');
      typeSel.className = 'form-select prompt-type-input';
      typeSel.style.cssText =
        'width: 120px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      [
        ['text', 'Text'],
        ['number', 'Number'],
        ['date', 'Date'],
        ['select', 'Select'],
        ['evidence', 'Evidence (upload)'],
      ].forEach(([val, label]) => {
        const o = document.createElement('option');
        o.value = val;
        o.textContent = label;
        typeSel.appendChild(o);
      });
      typeSpan1.appendChild(typeSel);

      const unitSpan = document.createElement('span');
      unitSpan.className = 'io-item-unit';
      const unitIn = document.createElement('input');
      unitIn.type = 'text';
      unitIn.className = 'form-input prompt-unit-input';
      unitIn.placeholder = 'Unit (optional)';
      unitIn.style.cssText =
        'width: 100px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      unitSpan.appendChild(unitIn);

      const reqSpan = document.createElement('span');
      reqSpan.className = 'io-item-type';
      const reqSel = document.createElement('select');
      reqSel.className = 'form-select prompt-required-input';
      reqSel.style.cssText =
        'width: 100px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      const reqT = document.createElement('option');
      reqT.value = 'true';
      reqT.textContent = 'Required';
      const reqF = document.createElement('option');
      reqF.value = 'false';
      reqF.textContent = 'Optional';
      reqSel.appendChild(reqT);
      reqSel.appendChild(reqF);
      reqSpan.appendChild(reqSel);

      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'btn btn-ghost btn-icon btn-sm';
      delBtn.style.padding = '4px';
      delBtn.replaceChildren(flows2SvgCloseX14());
      delBtn.addEventListener('click', () => {
        ioItem.remove();
        updateStepMeta(stepCard);
      });

      ioItem.appendChild(nameSpan);
      ioItem.appendChild(typeSpan1);
      ioItem.appendChild(unitSpan);
      ioItem.appendChild(reqSpan);
      ioItem.appendChild(delBtn);

      ioList.appendChild(ioItem);
      updateStepMeta(stepCard);
    };

    window.addOutput = function(button) {
      const ioSection = button.closest('.io-section');
      const ioList = ioSection.querySelector('.io-list');
      const stepCard = button.closest('.step-card');

      const emptyMsg = ioList.querySelector('p');
      if (emptyMsg && emptyMsg.textContent.includes('No outputs defined')) {
        emptyMsg.remove();
      }

      const ioItem = document.createElement('div');
      ioItem.className = 'io-item';
      ioItem.style.cssText =
        'display: flex; align-items: center; gap: 8px; padding: 8px; border: 1px solid var(--border-light); border-radius: var(--radius-md); margin-bottom: 8px;';

      const nameSpan = document.createElement('span');
      nameSpan.className = 'io-item-name';
      nameSpan.style.flex = '1';
      const nameIn = document.createElement('input');
      nameIn.type = 'text';
      nameIn.className = 'form-input io-name-input';
      nameIn.placeholder = 'Product name';
      nameIn.style.cssText =
        'width: 100%; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      nameSpan.appendChild(nameIn);

      const qtySpan = document.createElement('span');
      qtySpan.className = 'io-item-quantity';
      const qtyIn = document.createElement('input');
      qtyIn.type = 'number';
      qtyIn.className = 'form-input io-quantity-input';
      qtyIn.placeholder = '0';
      qtyIn.style.cssText =
        'width: 80px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      qtySpan.appendChild(qtyIn);

      const unitSpan = document.createElement('span');
      unitSpan.className = 'io-item-unit';
      const unitSel = document.createElement('select');
      unitSel.className = 'form-select io-unit-input';
      unitSel.style.cssText =
        'width: 90px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      ['kg', 'g', 'L', 'mL', 'pcs', 'units'].forEach((u) => {
        const o = document.createElement('option');
        o.value = u;
        o.textContent = u;
        unitSel.appendChild(o);
      });
      unitSpan.appendChild(unitSel);

      const typeSpan = document.createElement('span');
      typeSpan.className = 'io-item-type';
      typeSpan.style.position = 'relative';
      const typeSel = document.createElement('select');
      typeSel.className = 'form-select io-type-input';
      typeSel.style.cssText =
        'width: 180px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
      const optV = document.createElement('option');
      optV.value = 'variable';
      optV.textContent = 'Confirm at execution';
      const optS = document.createElement('option');
      optS.value = 'static';
      optS.textContent = 'Static';
      typeSel.appendChild(optV);
      typeSel.appendChild(optS);
      typeSpan.appendChild(typeSel);
      const outTooltip = document.createElement('span');
      outTooltip.className = 'tooltip-icon';
      outTooltip.style.cssText = 'margin-left: 4px; cursor: help; color: var(--text-tertiary);';
      outTooltip.title =
        'Confirm at execution: You will confirm or override the actual quantity produced when this step runs. Static: System will not prompt for confirmation upon execution.';
      outTooltip.replaceChildren(flows2SvgHelpCircle14());
      typeSpan.appendChild(outTooltip);

      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'btn btn-ghost btn-icon btn-sm';
      delBtn.style.padding = '4px';
      delBtn.replaceChildren(flows2SvgCloseX14());
      delBtn.addEventListener('click', () => {
        ioItem.remove();
        updateStepMeta(stepCard);
      });

      ioItem.appendChild(nameSpan);
      ioItem.appendChild(qtySpan);
      ioItem.appendChild(unitSpan);
      ioItem.appendChild(typeSpan);
      ioItem.appendChild(delBtn);

      ioList.appendChild(ioItem);
      updateStepMeta(stepCard);
    };
    
    // Helper function to update step meta (input/output counts)

    (function() {
      function initRecordWastageModal() {
        var recordWastageModal = document.getElementById('record-wastage-modal');
        var recordWastageCardsContainer = document.getElementById('record-wastage-cards-container');
        var recordWastageClose = document.getElementById('record-wastage-modal-close');
        var recordWastageCancel = document.getElementById('record-wastage-cancel');
        var recordWastageSubmit = document.getElementById('record-wastage-submit');
        if (!recordWastageModal || !recordWastageCardsContainer) return;
        async function openRecordWastageModal(optionalFilterIds) {
          recordWastageCardsContainer.replaceChildren();
          var loadMsg = document.createElement('p');
          loadMsg.style.cssText = 'padding: 16px; color: var(--text-secondary);';
          loadMsg.textContent = 'Loading inventory...';
          recordWastageCardsContainer.appendChild(loadMsg);
          recordWastageModal.style.display = 'flex';
          document.body.style.overflow = 'hidden';
          var filterIds = Array.isArray(optionalFilterIds) ? optionalFilterIds.map(String) : null;
          try {
            var data = await window.CoreAPI.getInventory();
            var items = (data.inventory_items || []).filter(function(item) {
              var q = parseFloat(item.quantity);
              return !isNaN(q) && q > 0;
            });
            if (filterIds && filterIds.length > 0) {
              var idSet = new Set(filterIds);
              items = items.filter(function(item) { return item && idSet.has(String(item.id)); });
            }
            if (items.length === 0) {
              recordWastageCardsContainer.replaceChildren();
              var emptyP = document.createElement('p');
              emptyP.style.cssText = 'padding: 16px; color: var(--text-secondary);';
              emptyP.textContent = filterIds
                ? 'No expired materials with quantity to dispose.'
                : 'No inventory with quantity to dispose.';
              recordWastageCardsContainer.appendChild(emptyP);
              return;
            }
            recordWastageCardsContainer.replaceChildren();
            items.forEach(function(item) {
              var qtyNum = parseFloat(item.quantity);
              var unit = item.unit || 'units';
              var card = document.createElement('div');
              card.className = 'wastage-card';
              card.style.cssText = 'border: 1px solid var(--border-default); border-radius: var(--radius-md); padding: 14px; background: var(--bg-card); display: flex; flex-direction: column; gap: 10px;';
              card.dataset.inventoryId = item.id;
              card.dataset.maxQuantity = String(item.quantity);
              var nameLine = (item.process_name ? item.process_name + ' – ' : '') + item.name;
              var topRow = document.createElement('div');
              topRow.style.cssText = 'display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;';
              var titleWrap = document.createElement('div');
              var nameSpan = document.createElement('span');
              nameSpan.style.cssText = 'font-weight: 600; color: var(--text-primary);';
              nameSpan.textContent = nameLine;
              var availSpan = document.createElement('span');
              availSpan.style.cssText = 'font-size: 12px; color: var(--text-secondary); margin-left: 6px;';
              availSpan.textContent = 'Available: ' + String(item.quantity) + ' ' + unit;
              titleWrap.appendChild(nameSpan);
              titleWrap.appendChild(availSpan);
              topRow.appendChild(titleWrap);
              var ctrlRow = document.createElement('div');
              ctrlRow.style.cssText = 'display: flex; align-items: center; gap: 8px; flex-wrap: wrap;';
              var qtyLab = document.createElement('label');
              qtyLab.style.cssText = 'font-size: 12px; color: var(--text-secondary);';
              qtyLab.textContent = 'Quantity to waste';
              var qtyInput = document.createElement('input');
              qtyInput.type = 'number';
              qtyInput.className = 'wastage-qty-input';
              qtyInput.min = '0';
              qtyInput.max = String(qtyNum);
              qtyInput.step = '0.0001';
              qtyInput.placeholder = '0';
              qtyInput.value = '';
              qtyInput.style.cssText =
                'width: 100px; padding: 8px 10px; border-radius: var(--radius-lg); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;';
              var unitSpan = document.createElement('span');
              unitSpan.style.cssText = 'font-size: 13px; color: var(--text-secondary);';
              unitSpan.textContent = unit;
              var wasteEntireBtn = document.createElement('button');
              wasteEntireBtn.type = 'button';
              wasteEntireBtn.className = 'btn btn-secondary btn-sm waste-entire-btn';
              wasteEntireBtn.style.fontSize = '12px';
              wasteEntireBtn.textContent = 'Waste entire item';
              ctrlRow.appendChild(qtyLab);
              ctrlRow.appendChild(qtyInput);
              ctrlRow.appendChild(unitSpan);
              ctrlRow.appendChild(wasteEntireBtn);
              card.appendChild(topRow);
              card.appendChild(ctrlRow);
              if (wasteEntireBtn) wasteEntireBtn.addEventListener('click', function() { qtyInput.value = String(item.quantity); });
              if (qtyInput) qtyInput.addEventListener('input', function() {
                var v = parseFloat(this.value);
                var max = parseFloat(card.dataset.maxQuantity);
                if (!isNaN(v) && v > max) this.value = String(max);
              });
              recordWastageCardsContainer.appendChild(card);
            });
          } catch (e) {
            console.error('Failed to load inventory for wastage', e);
            recordWastageCardsContainer.replaceChildren();
            var errP = document.createElement('p');
            errP.style.cssText = 'padding: 16px; color: var(--error, #ef4444);';
            errP.textContent = 'Failed to load inventory.';
            recordWastageCardsContainer.appendChild(errP);
          }
        }
        function closeRecordWastageModal() {
          recordWastageModal.style.display = 'none';
          document.body.style.overflow = 'auto';
        }
        async function submitRecordWastage() {
          var cards = recordWastageCardsContainer.querySelectorAll('.wastage-card');
          var entries = [];
          cards.forEach(function(card) {
            var id = card.dataset.inventoryId;
            var input = card.querySelector('.wastage-qty-input');
            var val = input && parseFloat(input.value);
            if (id && !isNaN(val) && val > 0) {
              var max = parseFloat(card.dataset.maxQuantity);
              if (!isNaN(max) && val > max) { val = max; if (input) input.value = String(max); }
              entries.push({ inventory_item_id: id, quantity_wasted: val });
            }
          });
          if (entries.length === 0) {
            if (typeof window.showNotification === 'function') window.showNotification('error', 'No quantity entered', 'Enter quantity to dispose for at least one item.');
            return;
          }
          try {
            var idemKey = (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()) + '-' + Math.random();
            var res = await window.CoreAPI.recordWastage(entries, { idempotencyKey: idemKey });
            closeRecordWastageModal();
            if (res && res.wastage_records && res.wastage_records.length && typeof window.showNotification === 'function') {
              window.showNotification('success', 'Inventory disposed', res.wastage_records.length + ' item(s) disposed. Quantity deducted from inventory.');
            }
            // No-op: system findings banner removed from this page.
            if (typeof loadInventory === 'function') loadInventory();
          } catch (e) {
            if (typeof window.showNotification === 'function') window.showNotification('error', 'Failed to dispose of inventory', e.message || 'Could not dispose of inventory.');
          }
        }
        window.openRecordWastageModalForExpired = function(itemIds) { openRecordWastageModal(itemIds); };
        if (recordWastageClose) recordWastageClose.addEventListener('click', closeRecordWastageModal);
        if (recordWastageCancel) recordWastageCancel.addEventListener('click', closeRecordWastageModal);
        if (recordWastageSubmit) recordWastageSubmit.addEventListener('click', submitRecordWastage);
      }
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initRecordWastageModal);
      } else {
        initRecordWastageModal();
      }
    })();
