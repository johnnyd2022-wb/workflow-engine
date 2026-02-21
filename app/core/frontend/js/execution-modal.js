// ============================================================
// SHARED EXECUTION MODAL FUNCTIONS
// ============================================================
// This file provides openExecutionModal and submitExecution functions
// that can be used in both flows2.html and core2.html
//
// Configuration:
// Set window.ExecutionModalConfig before loading this script:
//   window.ExecutionModalConfig = {
//     onStepCompleted: async function() {
//       // Called after step is completed successfully
//       // e.g., await loadExecutions(); await loadInventory();
//       // or: await loadInventoryV2();
//     }
//   };
//
// Dependencies:
// - CoreAPI (must be loaded before this script)
// - escapeHtml function (must be defined globally)
// - getCurrentUser function (must be defined globally)
// - showNotification function (must be defined globally)
// ============================================================

(function() {
  'use strict';
  
  // Get configuration or use defaults
  const config = window.ExecutionModalConfig || {
    onStepCompleted: async function() {
      console.warn('ExecutionModalConfig.onStepCompleted not configured. Set window.ExecutionModalConfig before loading this script.');
    }
  };
  
  // ============================================================
  // OPEN EXECUTION MODAL
  // ============================================================
  window.openExecutionModal = async function(executionId, executionStep, stepDefinition) {
    const modal = document.getElementById('execute-step-modal');
    if (!modal) {
      console.error('Execution modal not found');
      return;
    }
    
    // Store current execution context
    modal.dataset.executionId = executionId;
    modal.dataset.executionStepId = executionStep.id;
    
    // Set step name
    const stepNameEl = modal.querySelector('#execute-step-name');
    if (stepNameEl) {
      stepNameEl.textContent = stepDefinition.name || 'Unknown Step';
    }
    
    // Clear previous content
    const inputsContainer = modal.querySelector('#execute-inputs-container');
    const promptsContainer = modal.querySelector('#execute-prompts-container');
    const outputsContainer = modal.querySelector('#execute-outputs-container');
    
    if (inputsContainer) inputsContainer.innerHTML = '';
    if (promptsContainer) promptsContainer.innerHTML = '';
    if (outputsContainer) outputsContainer.innerHTML = '';
    
    // Load inventory, expired/flagged, and untracked materials in parallel (for highlighting step inputs)
    const [inventoryData, expiredData, untrackedData] = await Promise.all([
      CoreAPI.getInventory(),
      CoreAPI.getExpiredMaterials().catch(function() { return { expired_raw_materials: [], impacted_items: [] }; }),
      CoreAPI.getUntrackedItems().catch(function() { return { untracked_items: [] }; })
    ]);
    const allInventory = inventoryData.inventory_items || [];
    const expiredRaw = (expiredData && expiredData.expired_raw_materials) ? expiredData.expired_raw_materials : [];
    const impactedItems = (expiredData && expiredData.impacted_items) ? expiredData.impacted_items : [];
    const untrackedItems = (untrackedData && untrackedData.untracked_items) ? untrackedData.untracked_items : [];
    const expiredIds = new Set(expiredRaw.map(function(m) { return String(m.id); }));
    const impactedIds = new Set(impactedItems.map(function(i) { return String(i.id); }));
    const untrackedIds = new Set(untrackedItems.map(function(i) { return String(i.id); }));
    function getExpiredReason(id) {
      if (expiredIds.has(String(id))) return 'Expired';
      var imp = impactedItems.find(function(i) { return String(i.id) === String(id); });
      if (imp && imp.expired_raw_material_name) return 'Made with expired: ' + imp.expired_raw_material_name;
      if (imp) return 'Made with expired ingredients';
      if (untrackedIds.has(String(id))) return 'Untracked inventory item — reconciliation required';
      return null;
    }
    
    // Simple unit conversion function for frontend
    function convertUnit(quantity, fromUnit, toUnit) {
      if (!fromUnit || !toUnit || fromUnit.toLowerCase() === toUnit.toLowerCase()) {
        return quantity;
      }
      
      const from = fromUnit.toLowerCase();
      const to = toUnit.toLowerCase();
      
      // Mass conversions (to kg)
      const massFactors = {
        'kg': 1.0,
        'g': 0.001,
        'mg': 0.000001,
        'lb': 0.453592,
        'oz': 0.0283495,
        'ton': 1000.0,
        'tonne': 1000.0
      };
      
      // Volume conversions (to L)
      const volumeFactors = {
        'l': 1.0,
        'ml': 0.001,
        'gal': 3.78541,
        'm3': 1000.0,
        'ft3': 28.3168
      };
      
      // Length conversions (to m)
      const lengthFactors = {
        'm': 1.0,
        'cm': 0.01,
        'mm': 0.001,
        'ft': 0.3048,
        'in': 0.0254
      };
      
      // Check if both units are in the same category
      const fromMass = from in massFactors;
      const toMass = to in massFactors;
      const fromVolume = from in volumeFactors;
      const toVolume = to in volumeFactors;
      const fromLength = from in lengthFactors;
      const toLength = to in lengthFactors;
      
      if (fromMass && toMass) {
        const fromFactor = massFactors[from];
        const toFactor = massFactors[to];
        return (quantity * fromFactor) / toFactor;
      }
      if (fromVolume && toVolume) {
        const fromFactor = volumeFactors[from];
        const toFactor = volumeFactors[to];
        return (quantity * fromFactor) / toFactor;
      }
      if (fromLength && toLength) {
        const fromFactor = lengthFactors[from];
        const toFactor = lengthFactors[to];
        return (quantity * fromFactor) / toFactor;
      }
      
      // If units don't match or are incompatible, return original quantity
      return quantity;
    }
    
    // Render variable inputs (inventory selection)
    const variableInputs = (stepDefinition.inputs || []).filter(input => 
      input.requires_inventory_selection !== false && input.is_variable !== false
    );
    
    // Render confirm inputs (editable quantity/unit at execution)
    // These are inputs where is_variable is true but requires_inventory_selection is false
    const confirmInputs = (stepDefinition.inputs || []).filter(input => {
      const isVariable = input.is_variable !== false;
      const requiresInventory = input.requires_inventory_selection !== false;
      // Confirm at execution: variable but doesn't require inventory selection
      return isVariable && !requiresInventory;
    });
    
    if (variableInputs.length > 0 && inputsContainer) {
      variableInputs.forEach(input => {
        const inputSection = document.createElement('div');
        inputSection.className = 'execute-input-section';
        inputSection.style.cssText = 'margin-bottom: 20px; padding: 16px; border: 1px solid var(--border-light); border-radius: var(--radius-md);';
        
        // Filter inventory by material name (shows all matching items)
        const matchingInventory = allInventory.filter(inv => 
          inv.name.toLowerCase().includes(input.name.toLowerCase()) || 
          input.name.toLowerCase().includes(inv.name.toLowerCase())
        );
        
        // Get current execution ID from modal context
        const currentExecutionId = modal.dataset.executionId;
        
        // Sort inventory: items with same execution_id first, then others
        const sortedInventory = matchingInventory.sort((a, b) => {
          const aExecutionId = a.source_execution_id || a.execution_id || null;
          const bExecutionId = b.source_execution_id || b.execution_id || null;
          
          // If current execution ID is available, prioritize items from same execution
          if (currentExecutionId) {
            const aMatches = aExecutionId && String(aExecutionId) === String(currentExecutionId);
            const bMatches = bExecutionId && String(bExecutionId) === String(currentExecutionId);
            
            if (aMatches && !bMatches) return -1; // a comes first
            if (!aMatches && bMatches) return 1;  // b comes first
          }
          
          // If both match or both don't match, maintain original order
          return 0;
        });
        
        // Check if no matching inventory is available
        const hasNoInventory = sortedInventory.length === 0;
        const errorStyle = hasNoInventory ? 'border: 2px solid var(--error, #ef4444);' : '';
        const errorMessage = hasNoInventory ? `<p class="execute-input-no-inventory-warning" style="color: var(--error, #ef4444); font-size: 12px; margin-top: 4px; font-weight: 500;">⚠️ No matching inventory items found. Please add inventory before executing this step.</p>` : '';
        
        inputSection.innerHTML = `
          <div style="margin-bottom: 12px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
              ${escapeHtml(input.name)} 
              <span style="color: var(--text-secondary); font-weight: normal;">(Expected: ${input.quantity || '0'} ${input.unit || ''})</span>
              <span style="color: var(--error, #ef4444);">*</span>
            </label>
            <select class="form-select execute-inventory-select" data-input-name="${escapeHtml(input.name)}" data-required="true" required style="width: 100%; padding: 10px 16px; border-radius: var(--radius-lg); ${errorStyle} background: var(--bg-card); color: var(--text-primary); font-size: 14px;">
              <option value="">Select inventory item...</option>
              ${sortedInventory.map(inv => {
                // Build metadata display string
                const metadataParts = [];
                
                // Add created date if available
                if (inv.created_at) {
                  try {
                    const date = new Date(inv.created_at);
                    const formattedDate = date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
                    metadataParts.push(`Created: ${formattedDate}`);
                  } catch (e) {
                    // Ignore date parsing errors
                  }
                }
                
                // Add execution prompts/metadata if available
                if (inv.extra_data && inv.extra_data.execution_prompts) {
                  const prompts = inv.extra_data.execution_prompts;
                  const promptEntries = Object.entries(prompts).slice(0, 2); // Show first 2 prompts
                  if (promptEntries.length > 0) {
                    const promptStr = promptEntries.map(([key, value]) => `${escapeHtml(key)}: ${escapeHtml(String(value))}`).join(', ');
                    metadataParts.push(promptStr);
                  }
                }
                
                // Add process name if available
                if (inv.process_name) {
                  metadataParts.push(`Process: ${escapeHtml(inv.process_name)}`);
                }
                
                // Build the display text - prepend process name to product name
                const productName = inv.process_name ? `${escapeHtml(inv.process_name)} - ${escapeHtml(inv.name)}` : escapeHtml(inv.name);
                let displayText = `${productName} - ${inv.quantity} ${inv.unit}`;
                
                // Add supplier/batch info if available (for raw materials)
                if (inv.supplier) {
                  displayText += ` (${escapeHtml(inv.supplier)})`;
                }
                if (inv.supplier_batch_number) {
                  displayText += ` - Batch: ${escapeHtml(inv.supplier_batch_number)}`;
                }
                
                // Add metadata if available
                if (metadataParts.length > 0) {
                  displayText += ` | ${metadataParts.join(' | ')}`;
                }
                
                // Highlight expired/flagged items (same concept as sourcemap check-needed)
                const reason = getExpiredReason(inv.id);
                const prefix = reason ? '⚠ ' + reason + ': ' : '';
                
                return `
                  <option value="${inv.id}" data-quantity="${inv.quantity}" data-unit="${inv.unit}" data-expired-reason="${reason ? escapeHtml(reason) : ''}" title="${escapeHtml(displayText)}">
                    ${prefix}${displayText}
                  </option>
                `;
              }).join('')}
            </select>
            <div class="execute-input-expired-warning" data-input-name="${escapeHtml(input.name)}" style="display: none; margin-top: 8px; padding: 10px 12px; background: hsl(0, 93%, 94%); border: 1px solid var(--error, #ef4444); border-radius: var(--radius-md); color: #b91c1c; font-size: 13px; font-weight: 500;" role="alert"></div>
            ${errorMessage}
            ${hasNoInventory ? `<p style="margin-top: 8px;"><button type="button" class="btn btn-secondary btn-sm add-missing-item-btn" data-input-name="${escapeHtml(input.name)}" data-input-quantity="${escapeHtml(String(input.quantity != null ? input.quantity : ''))}" data-input-unit="${escapeHtml(input.unit || '')}" data-source-output-id="${input.source_output_id ? escapeHtml(String(input.source_output_id)) : ''}" data-source-step-id="${input.source_step_id ? escapeHtml(String(input.source_step_id)) : ''}" data-source-process-id="${input.source_process_id ? escapeHtml(String(input.source_process_id)) : ''}" style="font-size: 13px;">Add Missing Item</button></p>` : ''}
          </div>
          <div>
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">Quantity to Consume <span style="color: var(--error, #ef4444);">*</span></label>
            <div style="display: flex; align-items: center; gap: 8px;">
              <input type="number" class="form-input execute-quantity-input" data-input-name="${escapeHtml(input.name)}" data-step-unit="${escapeHtml(input.unit || '')}" data-original-quantity="${input.quantity || ''}" data-required="true" required placeholder="${input.quantity || '0'}" value="${input.quantity || ''}" step="0.01" min="0.01" style="flex: 1; padding: 10px 16px; border-radius: var(--radius-lg); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;">
              <span class="execute-quantity-unit-display" style="font-size: 14px; color: var(--text-secondary); min-width: 40px; text-align: left;">${input.unit || ''}</span>
            </div>
            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">When you select an inventory item, quantity updates to that item's total. You can edit to consume less.</p>
          </div>
        `;
        
        // Add event listeners to clear error styling when user fixes issues
        const select = inputSection.querySelector('.execute-inventory-select');
        const quantityInput = inputSection.querySelector('.execute-quantity-input');
        const unitDisplay = inputSection.querySelector('.execute-quantity-unit-display');
        
        if (select) {
          const expiredWarningEl = inputSection.querySelector('.execute-input-expired-warning');
          select.addEventListener('change', function() {
            if (this.value) {
              // Show/hide expired warning (step-specific: only items in this step's dropdown)
              const option = this.options[this.selectedIndex];
              const reason = option && option.dataset.expiredReason;
              if (reason) {
                if (expiredWarningEl) {
                  expiredWarningEl.textContent = 'Check: ' + reason;
                  expiredWarningEl.style.display = 'block';
                }
                this.style.border = '2px solid var(--error, #ef4444)';
                this.style.boxShadow = '0 0 0 1px var(--error, #ef4444)';
              } else {
                if (expiredWarningEl) {
                  expiredWarningEl.style.display = 'none';
                  expiredWarningEl.textContent = '';
                }
                this.style.border = '';
                this.style.boxShadow = '';
              }
              // When user selects an inventory item: set quantity to that item's total (for confirmation)
              // User can edit down if consuming less. DAG traces via execution_id; no need to assume previous-step usage.
              if (option && unitDisplay && quantityInput) {
                const inventoryUnit = option.dataset.unit || '';
                const inventoryQuantity = option.dataset.quantity != null && option.dataset.quantity !== '' ? option.dataset.quantity : quantityInput.value;
                quantityInput.value = inventoryQuantity;
                quantityInput.dataset.originalQuantity = inventoryQuantity;
                unitDisplay.textContent = inventoryUnit;
                quantityInput.dataset.inventoryUnit = inventoryUnit;
              }
              // Clear quantity error if inventory is selected
              if (quantityInput) {
                quantityInput.style.border = '';
              }
              // Re-enable submit button if it was disabled
              const submitBtn = modal.querySelector('#execute-step-submit-btn');
              if (submitBtn && submitBtn.disabled) {
                // Check if all required inputs now have inventory
                const allRequiredSelects = modal.querySelectorAll('.execute-inventory-select[data-required="true"]');
                let allHaveInventory = true;
                allRequiredSelects.forEach(s => {
                  if (!s.value || s.value === '') {
                    allHaveInventory = false;
                  }
                });
                if (allHaveInventory) {
                  submitBtn.disabled = false;
                  submitBtn.style.opacity = '1';
                  submitBtn.style.cursor = 'pointer';
                  submitBtn.title = '';
                }
              }
            } else {
              // No inventory selected: hide expired warning and clear border
              if (expiredWarningEl) {
                expiredWarningEl.style.display = 'none';
                expiredWarningEl.textContent = '';
              }
              this.style.border = '';
              this.style.boxShadow = '';
              if (unitDisplay && quantityInput) {
                // Reset to step definition when no inventory is selected
                unitDisplay.textContent = quantityInput.dataset.stepUnit || input.unit || '';
                quantityInput.value = input.quantity || '';
                quantityInput.dataset.originalQuantity = input.quantity || '';
                quantityInput.dataset.inventoryUnit = '';
              }
            }
          });
        }
        
        if (quantityInput) {
          if (!quantityInput.dataset.originalQuantity || quantityInput.dataset.originalQuantity === '' || quantityInput.dataset.originalQuantity === 'undefined') {
            quantityInput.dataset.originalQuantity = input.quantity || quantityInput.value || '0';
          }
          quantityInput.addEventListener('input', function() {
            if (parseFloat(this.value) > 0) this.style.border = '';
          });
        }
        
        // Add Missing Item: fromOutput = from previous output; else raw material modal
        const addMissingBtn = inputSection.querySelector('.add-missing-item-btn');
        if (addMissingBtn) {
          addMissingBtn.addEventListener('click', function() {
            var fromOutput = Boolean(this.dataset.sourceOutputId || this.dataset.sourceStepId || this.dataset.sourceProcessId);
            var sourceOutputId = this.dataset.sourceOutputId || '';
            var name_ = this.dataset.inputName || '';
            var quantity_ = this.dataset.inputQuantity != null && this.dataset.inputQuantity !== '' ? this.dataset.inputQuantity : '';
            var unit_ = this.dataset.inputUnit || '';
            if (fromOutput && window.openAddUntrackedOutputModal) {
              window.addInventoryContext = { fromExecutionModal: true, inputName: name_ };
              window.openAddUntrackedOutputModal(
                { name: name_, quantity: quantity_, unit: unit_, id: sourceOutputId || undefined },
                modal.dataset.executionId,
                modal.dataset.executionStepId
              );
              var untrackedModal = document.getElementById('add-untracked-output-modal');
              if (untrackedModal) untrackedModal.style.zIndex = '1001';
            } else if (!fromOutput && window.openAddInventoryModalForMissingInput) {
              window.openAddInventoryModalForMissingInput({ name: name_, quantity: quantity_, unit: unit_ });
            }
          });
        }
        
        inputsContainer.appendChild(inputSection);
      });
    }
    
    // Render confirm inputs (editable quantity/unit)
    if (confirmInputs.length > 0 && inputsContainer) {
      confirmInputs.forEach(input => {
        const inputSection = document.createElement('div');
        inputSection.className = 'execute-input-section';
        inputSection.style.cssText = 'margin-bottom: 20px; padding: 16px; border: 1px solid var(--border-light); border-radius: var(--radius-md);';
        
        inputSection.innerHTML = `
          <div style="margin-bottom: 12px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
              ${escapeHtml(input.name)} 
              <span style="color: var(--text-secondary); font-weight: normal;">(Expected: ${input.quantity || '0'} ${input.unit || ''})</span>
              <span style="color: var(--error, #ef4444);">*</span>
            </label>
          </div>
          <div style="margin-bottom: 12px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">Quantity <span style="color: var(--error, #ef4444);">*</span></label>
            <input type="number" class="form-input execute-confirm-quantity-input" data-input-name="${escapeHtml(input.name)}" data-required="true" required placeholder="${input.quantity || '0'}" value="${input.quantity || ''}" step="0.01" min="0" style="width: 100%; padding: 10px 16px; border-radius: var(--radius-lg); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;">
          </div>
          <div>
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">Unit <span style="color: var(--error, #ef4444);">*</span></label>
            <select class="form-select execute-confirm-unit-input" data-input-name="${escapeHtml(input.name)}" data-required="true" required style="width: 100%; padding: 10px 16px; border-radius: var(--radius-lg); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;">
              <option value="">Select unit...</option>
              ${['kg', 'g', 'mg', 'lb', 'oz', 'ton', 'tonne', 'l', 'ml', 'gal', 'm3', 'ft3', 'm', 'cm', 'mm', 'ft', 'in', 'units', 'pcs', 'pieces', 'boxes', 'pallets', 'containers'].map(unit => `
                <option value="${unit}" ${input.unit === unit ? 'selected' : ''}>${unit}</option>
              `).join('')}
            </select>
          </div>
        `;
        
        // Add event listeners to clear error styling
        const quantityInput = inputSection.querySelector('.execute-confirm-quantity-input');
        const unitSelect = inputSection.querySelector('.execute-confirm-unit-input');
        
        if (quantityInput) {
          quantityInput.addEventListener('input', function() {
            if (this.value && parseFloat(this.value) > 0) {
              this.style.border = '';
            }
          });
        }
        
        if (unitSelect) {
          unitSelect.addEventListener('change', function() {
            if (this.value) {
              this.style.border = '';
            }
          });
        }
        
        inputsContainer.appendChild(inputSection);
      });
    }
    
    if (inputsContainer && variableInputs.length === 0 && confirmInputs.length === 0) {
      inputsContainer.innerHTML = '<p style="color: var(--text-secondary); font-size: 14px; padding: 16px;">No variable inputs for this step.</p>';
    }
    
    // Render execution prompts
    const executionPrompts = stepDefinition.execution_prompts || [];
    if (executionPrompts.length > 0 && promptsContainer) {
      executionPrompts.forEach(prompt => {
        const promptSection = document.createElement('div');
        promptSection.className = 'execute-prompt-section';
        promptSection.style.cssText = 'margin-bottom: 16px;';
        
        let inputHtml = '';
        if (prompt.type === 'text') {
          inputHtml = `<input type="text" class="form-input execute-prompt-input" data-prompt-label="${escapeHtml(prompt.label)}" ${prompt.required !== false ? 'required' : ''} style="width: 100%; padding: 10px 16px; border-radius: var(--radius-lg); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;">`;
        } else if (prompt.type === 'number') {
          inputHtml = `<input type="number" class="form-input execute-prompt-input" data-prompt-label="${escapeHtml(prompt.label)}" ${prompt.required !== false ? 'required' : ''} step="0.01" style="width: 100%; padding: 10px 16px; border-radius: var(--radius-lg); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;">`;
        } else if (prompt.type === 'date') {
          inputHtml = `<input type="date" class="form-input execute-prompt-input" data-prompt-label="${escapeHtml(prompt.label)}" ${prompt.required !== false ? 'required' : ''} style="width: 100%; padding: 10px 16px; border-radius: var(--radius-lg); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;">`;
        } else if (prompt.type === 'select') {
          inputHtml = `<select class="form-select execute-prompt-input" data-prompt-label="${escapeHtml(prompt.label)}" ${prompt.required !== false ? 'required' : ''} style="width: 100%; padding: 10px 16px; border-radius: var(--radius-lg); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;"><option value="">Select...</option></select>`;
        }
        
        promptSection.innerHTML = `
          <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
            ${escapeHtml(prompt.label)}${prompt.required !== false ? ' <span style="color: var(--error);">*</span>' : ''}${prompt.unit ? ` (${escapeHtml(prompt.unit)})` : ''}
          </label>
          ${inputHtml}
        `;
        
        // Add event listener to clear error styling when user fixes issues
        const promptInput = promptSection.querySelector('.execute-prompt-input');
        if (promptInput) {
          promptInput.addEventListener('input', function() {
            if (this.value.trim()) {
              this.style.border = '';
            }
          });
          promptInput.addEventListener('change', function() {
            if (this.value.trim()) {
              this.style.border = '';
            }
          });
        }
        
        promptsContainer.appendChild(promptSection);
      });
    } else if (promptsContainer) {
      promptsContainer.innerHTML = '<p style="color: var(--text-secondary); font-size: 14px; padding: 16px;">No execution prompts for this step.</p>';
    }
    
    // Render variable outputs (confirmation/override)
    const variableOutputs = (stepDefinition.outputs || []).filter(output =>
      output.requires_execution_confirmation !== false && output.is_variable !== false
    );
    const outputNameNorm = function(n) { return (n || '').trim().toLowerCase(); };
    const unitNorm = function(u) { return (u || '').trim(); };

    // Fetch matching untracked per output from backend (includes qty>0 and qty 0 consumed in this execution).
    // Do not pass process_id so untracked items without source_execution (e.g. manually added) are included.
    let matchingUntrackedPerOutput = [];
    const currentExecutionId = modal.dataset.executionId;
    if (variableOutputs.length > 0 && currentExecutionId && typeof CoreAPI.getMatchingUntracked === 'function') {
      try {
        const results = await Promise.all(
          variableOutputs.map(function(o) {
            var name = (o.name && String(o.name).trim()) || '';
            var unit = (o.unit && String(o.unit).trim()) || 'units';
            return CoreAPI.getMatchingUntracked(name, unit, null, currentExecutionId);
          })
        );
        matchingUntrackedPerOutput = results.map(function(r) { return (r && r.matching_untracked) ? r.matching_untracked : []; });
      } catch (e) {
        console.warn('Could not fetch matching untracked per output', e);
      }
    }

    if (variableOutputs.length > 0 && outputsContainer) {
      variableOutputs.forEach((output, index) => {
        const outputSection = document.createElement('div');
        outputSection.className = 'execute-output-section';
        outputSection.style.cssText = 'margin-bottom: 20px; padding: 16px; border: 1px solid var(--border-light); border-radius: var(--radius-md);';
        const outputId = output.id != null ? escapeHtml(String(output.id)) : '';
        const outName = output.name || '';
        const outUnit = output.unit || 'units';
        // Match = backend semantics: name case-insensitive (ilike), unit exact after trim. Use API result when available.
        const matchingFromApi = matchingUntrackedPerOutput[index];
        const matchingUntracked = (matchingFromApi != null && Array.isArray(matchingFromApi))
          ? matchingFromApi
          : (untrackedItems || []).filter(function(u) {
              if (!u || !u.id) return false;
              if (outputNameNorm(u.name) !== outputNameNorm(outName)) return false;
              if (unitNorm(u.unit) !== unitNorm(outUnit)) return false;
              var q = parseFloat(u.quantity);
              return !isNaN(q) && q >= 0;
            });
        var defaultId = matchingUntracked.length === 1 ? String(matchingUntracked[0].id) : '';
        var hasMatch = matchingUntracked.length > 0;
        outputSection.innerHTML = `
          <div style="margin-bottom: 12px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
              ${escapeHtml(output.name)}
              <span style="color: var(--text-secondary); font-weight: normal;">(Expected: ${output.quantity || '0'} ${output.unit || ''})</span>
            </label>
            <input type="number" class="form-input execute-output-quantity-input" data-output-name="${escapeHtml(output.name)}" placeholder="${output.quantity || '0'}" value="${output.quantity || ''}" step="0.01" min="0" style="width: 100%; padding: 10px 16px; border-radius: var(--radius-lg); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;">
            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">Actual produced quantity (override if different from expected)</p>
            <div class="execute-reconcile-untracked-wrapper" data-output-name="${escapeHtml(outName)}" style="display: ${hasMatch ? 'block' : 'none'}; margin-top: 12px; padding: 12px 16px; background: hsl(42, 93%, 96%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; position: relative;">
              <input type="hidden" class="execute-reconcile-untracked-value" data-output-name="${escapeHtml(outName)}" value="${escapeHtml(defaultId)}">
              <label style="display: block; font-weight: 600; color: #92400e; margin-bottom: 8px;">Reconcile to untracked item (optional)</label>
              <p style="margin: 0 0 8px 0; color: #92400e; font-size: 12px;">Choose an item from the dropdown to reconcile when you complete the step.</p>
              <div class="execute-reconcile-untracked-trigger" role="button" tabindex="0" style="display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 10px 14px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px; cursor: pointer; min-height: 44px;">
                <span class="execute-reconcile-trigger-label" style="flex: 1; text-align: left;">— None —</span>
                <svg class="execute-reconcile-trigger-arrow" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink: 0; margin-left: 8px; transition: transform 0.2s;"><polyline points="6 9 12 15 18 9"/></svg>
              </div>
              <div class="execute-reconcile-untracked-dropdown" style="display: none; position: absolute; top: 100%; left: 0; right: 0; z-index: 100; margin-top: 6px; max-height: 320px; overflow-y: auto; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); box-shadow: 0 10px 25px rgba(0,0,0,0.15); padding: 8px;">
                <div class="execute-reconcile-untracked-cards" style="display: flex; flex-direction: column; gap: 8px;"></div>
              </div>
            </div>
          </div>
        `;
        outputsContainer.appendChild(outputSection);

        if (hasMatch) {
          var wrapper = outputSection.querySelector('.execute-reconcile-untracked-wrapper');
          var trigger = outputSection.querySelector('.execute-reconcile-untracked-trigger');
          var triggerLabel = outputSection.querySelector('.execute-reconcile-trigger-label');
          var triggerArrow = outputSection.querySelector('.execute-reconcile-trigger-arrow');
          var dropdown = outputSection.querySelector('.execute-reconcile-untracked-dropdown');
          var cardsContainer = outputSection.querySelector('.execute-reconcile-untracked-cards');
          var hiddenInput = outputSection.querySelector('.execute-reconcile-untracked-value');
          var safeId = function(s) { return String(s).replace(/\s+/g, '-').replace(/[^a-zA-Z0-9-]/g, '').slice(0, 40); };
          var detailId = function(uOrId) { var id = typeof uOrId === 'string' ? uOrId : (uOrId && uOrId.id); return 'execute-reconcile-details-' + safeId(outName) + '-' + id; };
          var arrowId = function(uOrId) { var id = typeof uOrId === 'string' ? uOrId : (uOrId && uOrId.id); return 'execute-reconcile-arrow-' + safeId(outName) + '-' + id; };

          function getSelectionLabel(id) {
            if (!id) return '— None —';
            var u = matchingUntracked.find(function(x) { return String(x.id) === id; });
            if (!u) return '— None —';
            var qtyLabel = (u.remaining_balance_to_reconcile != null && String(u.remaining_balance_to_reconcile).trim() !== '') ? 'Unreconciled: ' + u.remaining_balance_to_reconcile : (u.quantity != null ? u.quantity : '0');
            return (u.name || 'Unknown') + ' · ' + qtyLabel + ' ' + (u.unit || '');
          }

          function closeDropdown() {
            dropdown.style.display = 'none';
            if (triggerArrow) triggerArrow.style.transform = '';
            document.removeEventListener('click', closeDropdownOutside);
          }
          function closeDropdownOutside(e) {
            if (wrapper && !wrapper.contains(e.target)) closeDropdown();
          }
          function openDropdown() {
            dropdown.style.display = 'block';
            if (triggerArrow) triggerArrow.style.transform = 'rotate(180deg)';
            setTimeout(function() { document.addEventListener('click', closeDropdownOutside); }, 0);
          }
          function toggleDropdown() {
            var isOpen = dropdown.style.display === 'block';
            if (isOpen) closeDropdown(); else openDropdown();
          }
          trigger.addEventListener('click', function(e) { e.stopPropagation(); toggleDropdown(); });
          trigger.addEventListener('keydown', function(e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleDropdown(); } });
          dropdown.addEventListener('click', function(e) { e.stopPropagation(); });

          function setSelection(selectedId) {
            hiddenInput.value = selectedId || '';
            triggerLabel.textContent = getSelectionLabel(selectedId);
            wrapper.querySelectorAll('.execute-reconcile-untracked-card').forEach(function(c) {
              var id = c.dataset.untrackedId || '';
              var selected = id === selectedId;
              c.classList.toggle('execute-reconcile-card-selected', selected);
              c.style.borderColor = selected ? 'var(--warning, #f59e0b)' : '';
              c.style.boxShadow = selected ? '0 0 0 2px rgba(245, 158, 11, 0.25)' : '';
            });
            closeDropdown();
          }

          function toggleCardDetails(itemId) {
            var details = outputSection.querySelector('#' + detailId(itemId));
            var arrow = outputSection.querySelector('#' + arrowId(itemId));
            if (!details || !arrow) return;
            var isExpanded = details.style.display === 'block';
            details.style.display = isExpanded ? 'none' : 'block';
            arrow.style.transform = isExpanded ? 'rotate(0deg)' : 'rotate(90deg)';
          }

          var noneCard = document.createElement('div');
          noneCard.className = 'execute-reconcile-untracked-card' + (defaultId ? '' : ' execute-reconcile-card-selected');
          noneCard.dataset.untrackedId = '';
          noneCard.style.cssText = 'padding: 10px 14px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s;';
          noneCard.innerHTML = '<span style="color: var(--text-secondary); font-size: 13px;">— None —</span>';
          noneCard.onclick = function(e) { e.stopPropagation(); setSelection(''); };
          cardsContainer.appendChild(noneCard);

          matchingUntracked.forEach(function(u) {
            var id = String(u.id);
            var card = document.createElement('div');
            card.className = 'execute-reconcile-untracked-card card card-interactive' + (id === defaultId ? ' execute-reconcile-card-selected' : '');
            card.dataset.untrackedId = id;
            card.style.cssText = 'margin-bottom: 0; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s; overflow: hidden;';
            var createdStr = '';
            if (u.created_at) {
              try { createdStr = new Date(u.created_at).toLocaleDateString(); } catch (e) {}
            }
            var unreconciledQty = (u.remaining_balance_to_reconcile != null && String(u.remaining_balance_to_reconcile).trim() !== '') ? String(u.remaining_balance_to_reconcile).trim() : null;
            var subtitleParts = [];
            if (unreconciledQty !== null) {
              subtitleParts.push('Unreconciled: ' + escapeHtml(unreconciledQty) + ' ' + escapeHtml(u.unit || ''));
            } else {
              subtitleParts.push(escapeHtml(u.quantity != null ? String(u.quantity) : '0') + ' ' + escapeHtml(u.unit || ''));
            }
            if (u.process_name || u.step_name) {
              var ps = [u.process_name, u.step_name].filter(Boolean).map(function(x) { return escapeHtml(x); }).join(' · ');
              if (ps) subtitleParts.push(ps);
            }
            if (u.source_step_completed_by) subtitleParts.push('Completed by: ' + escapeHtml(u.source_step_completed_by));
            var subtitleLine = subtitleParts.join(' · ');
            var promptsHtml = '';
            if (u.source_step_execution_prompts && typeof u.source_step_execution_prompts === 'object' && Object.keys(u.source_step_execution_prompts).length > 0) {
              promptsHtml = '<div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-default);"><div style="font-size: 11px; font-weight: 600; color: var(--text-secondary); margin-bottom: 8px;">Step metadata</div><div style="display: flex; flex-direction: column; gap: 6px;">' +
                Object.entries(u.source_step_execution_prompts).map(function(e) {
                  return '<div style="padding: 6px 10px; background: var(--bg-secondary, #f9fafb); border-radius: 6px;"><span style="color: var(--text-secondary); font-size: 11px;">' + escapeHtml(e[0]) + '</span><br><span style="color: var(--text-primary); font-size: 13px;">' + escapeHtml(String(e[1])) + '</span></div>';
                }).join('') + '</div></div>';
            }
            var detailsParts = [];
            if (unreconciledQty !== null) {
              detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Unreconciled quantity</span> ' + escapeHtml(unreconciledQty) + ' ' + escapeHtml(u.unit || '') + '</p>');
            }
            if (u.process_name) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Process</span> ' + escapeHtml(u.process_name) + '</p>');
            if (u.step_name) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Step</span> ' + escapeHtml(u.step_name) + '</p>');
            if (createdStr) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Created</span> ' + escapeHtml(createdStr) + '</p>');
            if (u.supplier) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Supplier</span> ' + escapeHtml(u.supplier) + '</p>');
            if (u.supplier_batch_number) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Batch</span> ' + escapeHtml(u.supplier_batch_number) + '</p>');
            card.innerHTML =
              '<div class="process-card-header" style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; word-wrap: break-word; overflow-wrap: break-word;">' +
                '<div style="flex: 1; min-width: 0; cursor: pointer;" data-expand-trigger="1">' +
                  '<h4 style="margin: 0; font-size: 14px; font-weight: 600; color: var(--text-primary);">' + escapeHtml(u.name || 'Unknown') + '</h4>' +
                  '<p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-secondary);">' + subtitleLine + '</p>' +
                '</div>' +
                '<svg class="execute-reconcile-arrow" id="' + arrowId(u) + '" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink: 0; cursor: pointer; transform: rotate(0deg); transition: transform 0.2s;" data-expand-trigger="1">' +
                  '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>' +
                '</svg>' +
              '</div>' +
              '<div class="execute-reconcile-details" id="' + detailId(u) + '" style="display: none; padding: 12px 16px; border-top: 1px solid var(--border-default); background: var(--bg-secondary, #f9fafb); font-size: 13px;">' +
                detailsParts.join('') +
                promptsHtml +
              '</div>';
            card.onclick = function(e) {
              if (e.target.closest('[data-expand-trigger="1"]')) {
                e.stopPropagation();
                toggleCardDetails(id);
                return;
              }
              setSelection(id);
            };
            cardsContainer.appendChild(card);
          });
          setSelection(defaultId);
        }
      });
    } else if (outputsContainer) {
      outputsContainer.innerHTML = '<p style="color: var(--text-secondary); font-size: 14px; padding: 16px;">No variable outputs for this step.</p>';
    }
    
    // Check if any required inputs have no available inventory
    let hasMissingInventory = false;
    const missingInventoryInputs = [];
    const allInputSections = inputsContainer.querySelectorAll('.execute-input-section');
    allInputSections.forEach(section => {
      const select = section.querySelector('.execute-inventory-select');
      if (select && select.dataset.required === 'true') {
        // Get all options and filter out empty values (CSS doesn't support != in selectors)
        const allOptions = select.querySelectorAll('option');
        const validOptions = Array.from(allOptions).filter(opt => opt.value && opt.value !== '');
        if (validOptions.length === 0) {
          hasMissingInventory = true;
          const inputName = select.dataset.inputName;
          missingInventoryInputs.push(inputName);
        }
      }
    });
    
    // Disable submit button if required inventory is missing
    const submitButton = modal.querySelector('#execute-step-submit-btn');
    if (submitButton) {
      if (hasMissingInventory) {
        submitButton.disabled = true;
        submitButton.style.opacity = '0.5';
        submitButton.style.cursor = 'not-allowed';
        const missingList = missingInventoryInputs.map(name => `"${name}"`).join(', ');
        submitButton.title = `Cannot execute: Required inventory items are not available for: ${missingList}. Please add inventory before executing this step.`;
        
        // Show a warning notification
        showNotification('error', 'Missing Inventory', `Cannot execute: No matching inventory found for required inputs: ${missingList}. Please add inventory items before executing this step.`);
      } else {
        submitButton.disabled = false;
        submitButton.style.opacity = '1';
        submitButton.style.cursor = 'pointer';
        submitButton.title = '';
      }
    }
    
    // Show modal
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  };
  
  // ============================================================
  // SUBMIT EXECUTION (Complete Step with Data)
  // ============================================================
  window.submitExecution = async function() {
    const modal = document.getElementById('execute-step-modal');
    if (!modal) return;
    
    const executionId = modal.dataset.executionId;
    const executionStepId = modal.dataset.executionStepId;
    
    if (!executionId || !executionStepId) {
      showNotification('error', 'Error', 'Execution context missing.');
      return;
    }
    
    // VALIDATION: Check required variable inputs
    const validationErrors = [];
    
    // Check inventory selections for variable inputs
    const inventorySelects = modal.querySelectorAll('.execute-inventory-select[data-required="true"]');
    inventorySelects.forEach(select => {
      const inventoryId = select.value;
      const inputName = select.dataset.inputName;
      
      // Check if inventory is selected
      if (!inventoryId || inventoryId === '') {
        validationErrors.push(`Please select inventory for "${inputName}"`);
        // Highlight the field
        select.style.border = '2px solid var(--error, #ef4444)';
      } else {
        select.style.border = '';
        
        // Check quantity
        const quantityInput = modal.querySelector(`.execute-quantity-input[data-input-name="${inputName}"]`);
        if (quantityInput) {
          const quantity = parseFloat(quantityInput.value);
          if (!quantity || isNaN(quantity) || quantity <= 0) {
            validationErrors.push(`Please enter a valid quantity for "${inputName}"`);
            quantityInput.style.border = '2px solid var(--error, #ef4444)';
          } else {
            quantityInput.style.border = '';
            
            // Check if quantity exceeds available inventory
            // Note: Quantity is assumed to be in the inventory item's unit
            const option = select.options[select.selectedIndex];
            if (option && option.dataset.quantity) {
              const availableQty = parseFloat(option.dataset.quantity);
              const inventoryUnit = option.dataset.unit || '';
              const quantityUnit = quantityInput.dataset.inventoryUnit || inventoryUnit;
              
              // Since the quantity is entered in the inventory item's unit (shown in the unit display),
              // we can compare directly. The backend will handle any unit conversion if needed.
              if (quantity > availableQty) {
                validationErrors.push(`Quantity for "${inputName}" (${quantity} ${quantityUnit}) exceeds available inventory (${availableQty} ${inventoryUnit})`);
                quantityInput.style.border = '2px solid var(--error, #ef4444)';
              }
            }
          }
        }
      }
    });
    
    // VALIDATION: Check required execution prompts
    const promptInputs = modal.querySelectorAll('.execute-prompt-input[required]');
    promptInputs.forEach(input => {
      const label = input.dataset.promptLabel;
      const value = input.value.trim();
      
      if (!value) {
        validationErrors.push(`Please fill in required field: "${label}"`);
        input.style.border = '2px solid var(--error, #ef4444)';
      } else {
        input.style.border = '';
      }
    });
    
    // Validate confirm inputs (editable quantity/unit)
    const confirmQuantityInputs = modal.querySelectorAll('.execute-confirm-quantity-input[data-required="true"]');
    const confirmUnitSelects = modal.querySelectorAll('.execute-confirm-unit-input[data-required="true"]');
    
    confirmQuantityInputs.forEach(input => {
      const quantity = parseFloat(input.value);
      const inputName = input.dataset.inputName;
      const unitSelect = Array.from(confirmUnitSelects).find(sel => sel.dataset.inputName === inputName);
      const unit = unitSelect ? unitSelect.value : '';
      
      if (isNaN(quantity) || quantity <= 0) {
        validationErrors.push(`Please enter a valid quantity for "${inputName}"`);
        input.style.border = '2px solid var(--error, #ef4444)';
      } else {
        input.style.border = '';
      }
      
      if (!unit) {
        validationErrors.push(`Please select a unit for "${inputName}"`);
        if (unitSelect) unitSelect.style.border = '2px solid var(--error, #ef4444)';
      } else if (unitSelect) {
        unitSelect.style.border = '';
      }
    });
    
    // If validation errors exist, show them and prevent submission
    if (validationErrors.length > 0) {
      showNotification('error', 'Validation Error', validationErrors.join('. ') + '.');
      // Scroll to first error
      const firstError = modal.querySelector('[style*="border: 2px solid var(--error"]');
      if (firstError) {
        firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
        firstError.focus();
      }
      return;
    }
    
    // Additional check: Ensure all required variable inputs have inventory selected
    const requiredSelects = modal.querySelectorAll('.execute-inventory-select[data-required="true"]');
    const missingSelections = [];
    for (const select of requiredSelects) {
      if (!select.value || select.value === '') {
        missingSelections.push(select.dataset.inputName);
        select.style.border = '2px solid var(--error, #ef4444)';
      }
    }
    
    if (missingSelections.length > 0) {
      const missingList = missingSelections.map(name => `"${name}"`).join(', ');
      showNotification('error', 'Validation Error', `Please select inventory for all required inputs: ${missingList}.`);
      const firstMissing = modal.querySelector('.execute-inventory-select[data-required="true"]:not([value])');
      if (firstMissing) {
        firstMissing.scrollIntoView({ behavior: 'smooth', block: 'center' });
        firstMissing.focus();
      }
      return;
    }
    
    try {
      // Collect variable inputs (inventory selections)
      const actualInputs = [];
      inventorySelects.forEach(select => {
        const inventoryId = select.value;
        if (inventoryId) {
          const quantityInput = modal.querySelector(`.execute-quantity-input[data-input-name="${select.dataset.inputName}"]`);
          const quantity = quantityInput ? parseFloat(quantityInput.value) : 0;
          const option = select.options[select.selectedIndex];
          const unit = option ? option.dataset.unit : '';
          
          actualInputs.push({
            name: select.dataset.inputName,
            inventory_item_id: inventoryId,
            quantity: quantity,
            unit: unit
          });
        }
      });
      
      // Collect confirm inputs (editable quantity/unit)
      const confirmQuantityInputs = modal.querySelectorAll('.execute-confirm-quantity-input');
      const confirmUnitSelects = modal.querySelectorAll('.execute-confirm-unit-input');
      confirmQuantityInputs.forEach(quantityInput => {
        const inputName = quantityInput.dataset.inputName;
        const quantity = parseFloat(quantityInput.value);
        // Find matching unit select
        const unitSelect = Array.from(confirmUnitSelects).find(sel => sel.dataset.inputName === inputName);
        const unit = unitSelect ? unitSelect.value : '';
        
        if (inputName && !isNaN(quantity) && quantity > 0 && unit) {
          actualInputs.push({
            name: inputName,
            quantity: quantity,
            unit: unit
          });
        }
      });
      
      // Collect execution prompts
      const executionData = {};
      const allPromptInputs = modal.querySelectorAll('.execute-prompt-input');
      allPromptInputs.forEach(input => {
        const label = input.dataset.promptLabel;
        const value = input.value.trim();
        if (label && value) {
          executionData[label] = value;
        }
      });
      
      // Get step definition for output units
      const executionDataForOutputs = await CoreAPI.getExecution(executionId);
      const executionStepsForOutputs = executionDataForOutputs.execution_steps || [];
      const readyStepForOutputs = executionStepsForOutputs.find(es => es.id === executionStepId);
      const processDataForOutputs = await CoreAPI.getProcess(executionDataForOutputs.process_id);
      const stepDefinitionForOutputs = processDataForOutputs.steps.find(s => s.id === readyStepForOutputs.step_id);
      
      // Collect ALL outputs (both variable and static) to store as intermediate products
      const actualOutputs = [];
      const allStepOutputs = stepDefinitionForOutputs.outputs || [];
      
      // First, collect variable outputs (user-entered quantities). Always include each variable output
      // so reconciliation selection (untracked_item_id) is never dropped when quantity is empty.
      const outputInputs = modal.querySelectorAll('.execute-output-quantity-input');
      const variableOutputNames = new Set();
      outputInputs.forEach(input => {
        const name = (input.dataset.outputName || '').trim();
        if (!name) return;
        const outputDef = allStepOutputs.find(o => o.name === name);
        let quantity = parseFloat(input.value);
        if (isNaN(quantity) || quantity < 0) {
          quantity = outputDef && (outputDef.quantity != null) ? parseFloat(outputDef.quantity) : 0;
          if (isNaN(quantity) || quantity < 0) quantity = 0;
        }
        const reconcileInput = Array.from(modal.querySelectorAll('.execute-reconcile-untracked-value')).find(function(el) {
          return (el.dataset.outputName || '').trim() === name;
        });
        const untrackedItemId = (reconcileInput && reconcileInput.value && reconcileInput.value.trim()) ? reconcileInput.value.trim() : null;
        const outPayload = {
          name: name,
          quantity: quantity,
          unit: outputDef ? (outputDef.unit || 'units') : 'units'
        };
        if (untrackedItemId) outPayload.untracked_item_id = untrackedItemId;
        actualOutputs.push(outPayload);
        variableOutputNames.add(name);
      });
      
      // Then, add static outputs (use step definition quantities)
      allStepOutputs.forEach(outputDef => {
        // Skip if already added as variable output
        if (!variableOutputNames.has(outputDef.name)) {
          actualOutputs.push({
            name: outputDef.name,
            quantity: outputDef.quantity || 0,
            unit: outputDef.unit || 'units'
          });
        }
      });
      
      // Get current user for recording
      const user = await getCurrentUser();
      executionData.completed_by = user.username;
      executionData.completed_by_email = user.email;
      executionData.completed_at = new Date().toISOString();

      // Complete the step (expired/flagged items are highlighted in the Execute Step modal dropdowns; no separate modal)
      const completeResult = await CoreAPI.completeStep(executionId, executionStepId, {
        actual_inputs: actualInputs,
        actual_outputs: actualOutputs,
        execution_data: executionData
      });
      
      // Close modal
      modal.style.display = 'none';
      document.body.style.overflow = 'auto';
      
      var warnings = completeResult && completeResult.execution_warnings;
      if (warnings && warnings.length > 0) {
        showNotification('warning', 'Step completed with warnings', warnings.join(' '));
      } else {
        showNotification('success', 'Step Completed', 'Step has been completed successfully.');
      }
      
      // Call configurable callback to reload data
      if (config.onStepCompleted) {
        await config.onStepCompleted();
      }
      
    } catch (error) {
      console.error('Failed to complete step:', error);
      showNotification('error', 'Failed to Complete Step', error.message || 'Failed to complete step. Please try again.');
    }
  };

  // ============================================================
  // ADD MISSING ITEM (in-flow raw material)
  // ============================================================
  // Opens the page's Add Inventory modal with prefill. Set window.addInventoryContext
  // so the add-inventory submit handler can call refreshExecutionModalInventory(savedItem) on success.
  window.openAddInventoryModalForMissingInput = function(prefill) {
    var addModal = document.getElementById('add-inventory-modal');
    if (!addModal) return;
    var form = addModal.querySelector('form');
    if (form) {
      var nameEl = form.querySelector('[name="name"]');
      var qtyEl = form.querySelector('[name="quantity"]');
      var unitEl = form.querySelector('[name="unit"]');
      if (nameEl) nameEl.value = prefill.name || '';
      if (qtyEl) qtyEl.value = prefill.quantity != null && prefill.quantity !== '' ? prefill.quantity : '';
      if (unitEl) unitEl.value = prefill.unit || 'kg';
    }
    window.addInventoryContext = { fromExecutionModal: true, inputName: prefill.name || '' };
    addModal.style.zIndex = '1001'; // Above execution modal (z-index 1000)
    addModal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  };

  // Open lightweight "Add untracked output" modal (missing output recorded during execution).
  window.openAddUntrackedOutputModal = function(outputDef, executionId, executionStepId) {
    var m = document.getElementById('add-untracked-output-modal');
    if (!m) return;
    var nameEl = document.getElementById('untracked-output-name');
    var qtyEl = document.getElementById('untracked-output-quantity');
    var unitEl = document.getElementById('untracked-output-unit');
    var dateEl = document.getElementById('untracked-output-date');
    if (nameEl) nameEl.value = outputDef.name || '';
    if (qtyEl) qtyEl.value = outputDef.quantity != null && outputDef.quantity !== '' ? outputDef.quantity : '';
    if (unitEl) {
      var allowedUnits = ['kg', 'g', 'L', 'mL', 'pcs', 'units'];
      var u = (outputDef.unit || 'kg').trim();
      unitEl.value = allowedUnits.indexOf(u) !== -1 ? u : 'kg';
    }
    if (dateEl) {
      var today = new Date();
      dateEl.value = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
    }
    window.untrackedOutputContext = {
      executionId: executionId,
      executionStepId: executionStepId,
      outputId: outputDef.id || null
    };
    m.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  };

  // Submit handler for add-untracked-output form (bound when DOM ready so form exists)
  function bindUntrackedOutputForm() {
    var form = document.getElementById('add-untracked-output-form');
    if (!form) return;
    form.addEventListener('submit', async function(e) {
      e.preventDefault();
      var ctx = window.untrackedOutputContext;
      if (!ctx) return;
      var name = (form.querySelector('[name="name"]') || {}).value;
      var quantity = parseFloat((form.querySelector('[name="quantity"]') || {}).value);
      var unit = (form.querySelector('[name="unit"]') || {}).value;
      var inventoryType = (form.querySelector('[name="inventory_type"]') || {}).value || 'work_in_progress';
      var dateEl = document.getElementById('untracked-output-date');
      var recordedDate = dateEl ? dateEl.value : null;
      if (!name || !unit || isNaN(quantity) || quantity < 0) {
        if (typeof showNotification === 'function') showNotification('error', 'Validation error', 'Please provide a valid name, unit, and non-negative quantity.');
        return;
      }
      var uuidRe = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
      var payload = {
        name: name,
        quantity: quantity,
        unit: unit,
        inventory_type: inventoryType,
        source_execution_id: ctx.executionId || undefined,
        source_execution_step_id: ctx.executionStepId || undefined,
        untracked: true,
        metadata: recordedDate ? { recorded_date: recordedDate } : {}
      };
      if (ctx.outputId && uuidRe.test(String(ctx.outputId))) payload.source_output_id = ctx.outputId;
      try {
        var created = await CoreAPI.createInventoryItem(payload);
        var m = document.getElementById('add-untracked-output-modal');
        if (m) { m.style.display = 'none'; document.body.style.overflow = 'auto'; }
        window.untrackedOutputContext = null;
        if (typeof showNotification === 'function') showNotification('success', 'Untracked output added', 'Item has been added to inventory and flagged for reconciliation.');
        if (window.addInventoryContext && window.addInventoryContext.fromExecutionModal && created) {
          await window.refreshExecutionModalInventory(created);
        }
        if (config.onStepCompleted) await config.onStepCompleted();
      } catch (err) {
        console.error('Failed to add untracked output:', err);
        if (typeof showNotification === 'function') showNotification('error', 'Failed to add', err.message || 'Could not add untracked output.');
      }
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindUntrackedOutputForm);
  } else {
    bindUntrackedOutputForm();
  }

  // Called by core2/flows2 add-inventory success when item was added from execution modal.
  // Refetches inventory and updates execute-step-modal dropdowns; optionally selects the new item.
  window.refreshExecutionModalInventory = async function(newItem) {
    var modal = document.getElementById('execute-step-modal');
    if (!modal || modal.style.display === 'none') return;
    var ctx = window.addInventoryContext;
    if (!ctx || !ctx.fromExecutionModal) return;

    var inventoryData = await CoreAPI.getInventory();
    var allInventory = inventoryData.inventory_items || [];
    var currentExecutionId = modal.dataset.executionId;

    var selects = modal.querySelectorAll('.execute-inventory-select');
    for (var i = 0; i < selects.length; i++) {
      var select = selects[i];
      var inputName = select.dataset.inputName;
      if (!inputName) continue;
      var matching = allInventory.filter(function(inv) {
        return inv.name.toLowerCase().indexOf(inputName.toLowerCase()) !== -1 ||
          inputName.toLowerCase().indexOf(inv.name.toLowerCase()) !== -1;
      });
      matching.sort(function(a, b) {
        var aEid = a.source_execution_id || a.execution_id || null;
        var bEid = b.source_execution_id || b.execution_id || null;
        if (currentExecutionId) {
          var aMatch = aEid && String(aEid) === String(currentExecutionId);
          var bMatch = bEid && String(bEid) === String(currentExecutionId);
          if (aMatch && !bMatch) return -1;
          if (!aMatch && bMatch) return 1;
        }
        return 0;
      });
      var optionsHtml = matching.map(function(inv) {
        var displayText = (inv.process_name ? inv.process_name + ' - ' : '') + inv.name + ' - ' + inv.quantity + ' ' + inv.unit;
        if (inv.supplier) displayText += ' (' + (inv.supplier || '') + ')';
        return '<option value="' + inv.id + '" data-quantity="' + (inv.quantity || '') + '" data-unit="' + (inv.unit || '') + '">' + escapeHtml(displayText) + '</option>';
      }).join('');
      select.innerHTML = '<option value="">Select inventory item...</option>' + optionsHtml;
      if (newItem && ctx.inputName && inputName === ctx.inputName) {
        var newId = (newItem.id != null) ? String(newItem.id) : '';
        select.value = newId;
        var opt = select.options[select.selectedIndex];
        if (opt && opt.value) {
          var section = select.closest('.execute-input-section');
          if (section) {
            var qtyInput = section.querySelector('.execute-quantity-input');
            var unitDisplay = section.querySelector('.execute-quantity-unit-display');
            if (qtyInput) {
              qtyInput.value = opt.dataset.quantity != null ? opt.dataset.quantity : qtyInput.value;
              qtyInput.dataset.inventoryUnit = opt.dataset.unit || '';
            }
            if (unitDisplay) unitDisplay.textContent = opt.dataset.unit || '';
            var noInvWarning = section.querySelector('.execute-input-no-inventory-warning');
            if (noInvWarning) {
              noInvWarning.style.display = 'none';
            }
            select.style.border = '';
            select.style.boxShadow = '';
          }
          var submitBtn = modal.querySelector('#execute-step-submit-btn');
          if (submitBtn) {
            var allRequired = modal.querySelectorAll('.execute-inventory-select[data-required="true"]');
            var allHave = true;
            allRequired.forEach(function(s) { if (!s.value) allHave = false; });
            if (allHave) {
              submitBtn.disabled = false;
              submitBtn.style.opacity = '1';
              submitBtn.style.cursor = 'pointer';
              submitBtn.title = '';
            }
          }
        }
      }
    }
    window.addInventoryContext = null;
  };

})();
