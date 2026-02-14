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
  
  // Context set when user clicks "Add missing item"; used by choice modal to open Add Inventory or Record output modal.
  let _missingItemContext = null;
  
  // Create untracked inventory item and refresh execution modal. Used from both inline flow and from Record missing output modal.
  async function createUntrackedItemWithContext(context, options) {
    if (!context) return;
    const {
      name,
      quantity,
      unit,
      inventoryType,
      sourceType,
      inputName,
      processId,
      stepId,
      metadataExtras,
    } = options || {};
    const parsedQuantity = parseFloat(quantity);
    if (!name || !unit || !parsedQuantity || isNaN(parsedQuantity) || parsedQuantity <= 0) {
      showNotification('error', 'Invalid Missing Item', 'Please provide a name, valid quantity, and unit to record the missing item.');
      return;
    }
    try {
      const user = await getCurrentUser();
      const baseMetadata = {
        untracked: true,
        untracked_source: sourceType || 'raw_material',
        untracked_input_name: inputName || null,
        untracked_execution_id: context.executionId || null,
        untracked_execution_step_id: context.executionStep && context.executionStep.id ? context.executionStep.id : null,
        untracked_process_id: processId || null,
        untracked_step_id: stepId || null,
        untracked_recorded_by: user && (user.username || user.email) ? (user.username || user.email) : null,
        untracked_recorded_at: new Date().toISOString(),
      };
      const metadata = Object.assign({}, baseMetadata, metadataExtras || {});
      await CoreAPI.createInventoryItem({
        name: name,
        quantity: parsedQuantity,
        unit: unit,
        inventory_type: inventoryType || 'raw_material',
        metadata: metadata,
      });
      showNotification('success', 'Missing Item Recorded', `"${name}" has been recorded as an untracked inventory item. Inventory has been refreshed for this step.`);
      await window.openExecutionModal(context.executionId, context.executionStep, context.stepDefinition);
    } catch (error) {
      console.error('Failed to record missing item from execution flow:', error);
      showNotification('error', 'Failed to Record Missing Item', error.message || 'Failed to record missing item. Please try again.');
    }
  }
  
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
    
    // Load inventory, expired data, execution (for process_id/step_id when classifying missing inputs via backend DAG)
    const [inventoryData, expiredData, executionData] = await Promise.all([
      CoreAPI.getInventory(),
      CoreAPI.getExpiredMaterials().catch(function() { return { expired_raw_materials: [], impacted_items: [] }; }),
      CoreAPI.getExecution(executionId).catch(function() { return null; })
    ]);
    const allInventory = inventoryData.inventory_items || [];
    const expiredRaw = (expiredData && expiredData.expired_raw_materials) ? expiredData.expired_raw_materials : [];
    const impactedItems = (expiredData && expiredData.impacted_items) ? expiredData.impacted_items : [];
    const expiredIds = new Set(expiredRaw.map(function(m) { return String(m.id); }));
    const impactedIds = new Set(impactedItems.map(function(i) { return String(i.id); }));
    function getExpiredReason(id) {
      if (expiredIds.has(String(id))) return 'Expired';
      var imp = impactedItems.find(function(i) { return String(i.id) === String(id); });
      if (imp && imp.expired_raw_material_name) return 'Made with expired: ' + imp.expired_raw_material_name;
      return imp ? 'Made with expired ingredients' : null;
    }
    
    // Helper: create an untracked inventory item (delegates to IIFE-level createUntrackedItemWithContext).
    async function createUntrackedInventoryItem(options) {
      await createUntrackedItemWithContext({ executionId, executionStep, stepDefinition }, options);
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
    // Classify missing inputs via backend (source_step_id / source_process_id only — no name matching)
    let missingInputClassification = {};
    if (executionData && executionData.process_id && executionStep && executionStep.step_id && variableInputs.length > 0) {
      try {
        const inputsPayload = variableInputs.map(function(i) {
          return {
            name: (i.name || '').trim(),
            source_step_id: i.source_step_id || null,
            source_process_id: i.source_process_id || null,
            source_output_id: i.source_output_id || null
          };
        });
        const res = await CoreAPI.classifyMissingInputs(executionData.process_id, executionStep.step_id, inputsPayload);
        if (res && res.by_input_name) missingInputClassification = res.by_input_name;
        // Log what the system is using to choose which modal to show for "Add missing item"
        console.group('[Execution modal] Missing-input classification (source_step_id / source_process_id)');
        console.log('executionId:', executionId, 'process_id:', executionData.process_id, 'step_id:', executionStep.step_id);
        console.log('Inputs sent:', inputsPayload);
        console.log('DAG result (by_input_name):', JSON.stringify(missingInputClassification, null, 2));
        console.groupEnd();
      } catch (e) {
        console.warn('Could not classify missing inputs:', e);
      }
    }
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
        const missingItemType = hasNoInventory ? (missingInputClassification[(input.name || '').trim()] || 'raw') : 'raw';
        if (hasNoInventory) {
          const modalLabel = missingItemType === 'output' ? 'Record missing output' : 'Add Inventory (raw)';
          console.log('[Execution modal] Missing item:', input.name, '→', missingItemType, '(will open:', modalLabel + ')');
        }
        const errorStyle = hasNoInventory ? 'border: 2px solid var(--error, #ef4444);' : '';
        const errorMessage = hasNoInventory
          ? `
            <div class="execute-missing-inventory" data-input-name="${escapeHtml(input.name)}" style="margin-top: 8px;">
              <p style="color: var(--error, #ef4444); font-size: 12px; margin: 0 0 6px 0; font-weight: 500;">
                ⚠️ No matching inventory items found. You can record a missing item without leaving this flow.
              </p>
              <button type="button" class="btn btn-secondary btn-sm execute-add-missing-item-trigger" data-input-name="${escapeHtml(input.name)}" data-missing-type="${missingItemType}">
                Add missing item
              </button>
            </div>
          `
          : '';
        
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
          </div>
          <div>
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">Quantity to Consume <span style="color: var(--error, #ef4444);">*</span></label>
            <div style="display: flex; align-items: center; gap: 8px;">
              <input type="number" class="form-input execute-quantity-input" data-input-name="${escapeHtml(input.name)}" data-step-unit="${escapeHtml(input.unit || '')}" data-original-quantity="${input.quantity || ''}" data-required="true" required placeholder="${input.quantity || '0'}" value="${input.quantity || ''}" step="0.01" min="0.01" style="flex: 1; padding: 10px 16px; border-radius: var(--radius-lg); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;">
              <span class="execute-quantity-unit-display" style="font-size: 14px; color: var(--text-secondary); min-width: 40px; text-align: left;">${input.unit || ''}</span>
            </div>
            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">Quantity defaults to the step requirement; if the selected batch has less than required, it defaults to available. You can edit as needed.</p>
          </div>
        `;
        
        // Add event listeners to clear error styling when user fixes issues
        const select = inputSection.querySelector('.execute-inventory-select');
        const quantityInput = inputSection.querySelector('.execute-quantity-input');
        const unitDisplay = inputSection.querySelector('.execute-quantity-unit-display');
        const addMissingTriggerBtn = inputSection.querySelector('.execute-add-missing-item-trigger');
        
        // Single "Add missing item" opens the relevant modal: Add Inventory (raw) or Record missing output (output from previous step)
        if (addMissingTriggerBtn) {
          addMissingTriggerBtn.addEventListener('click', function () {
            _missingItemContext = { input: input, executionId: executionId, executionStep: executionStep, stepDefinition: stepDefinition };
            const missingType = this.getAttribute('data-missing-type') || 'raw';
            if (missingType === 'output') {
              openRecordMissingOutputModal();
            } else {
              const addModalEl = document.getElementById('add-inventory-modal');
              if (addModalEl) {
                addModalEl.style.zIndex = '1100';
                if (typeof window.openModal === 'function') {
                  window.openModal('add-inventory-modal');
                } else {
                  addModalEl.style.display = 'flex';
                  document.body.style.overflow = 'hidden';
                }
                const nameInput = addModalEl.querySelector('input[name="name"]');
                if (nameInput && input.name) {
                  nameInput.value = input.name;
                }
              }
            }
          });
        }
        
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
              // When user selects an inventory item: use step required quantity unless selected batch has less
              if (option && unitDisplay && quantityInput) {
                const inventoryUnit = option.dataset.unit || '';
                const availableQty = parseFloat(option.dataset.quantity);
                const available = !isNaN(availableQty) ? availableQty : 0;
                const stepRequired = parseFloat(input.quantity);
                const required = !isNaN(stepRequired) ? stepRequired : 0;
                const stepUnit = input.unit || '';
                const requiredInInventoryUnit = (stepUnit && inventoryUnit) ? convertUnit(required, stepUnit, inventoryUnit) : required;
                const quantityToUse = (available > 0 && available < requiredInInventoryUnit) ? available : (requiredInInventoryUnit > 0 ? requiredInInventoryUnit : available);
                quantityInput.value = quantityToUse;
                quantityInput.dataset.originalQuantity = String(quantityToUse);
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
        
        inputsContainer.appendChild(inputSection);
      });
    }
    
    // Render confirm inputs (editable quantity/unit) — quantity and unit prefilled from process step
    if (confirmInputs.length > 0 && inputsContainer) {
      const standardUnits = ['kg', 'g', 'mg', 'lb', 'oz', 'ton', 'tonne', 'l', 'ml', 'gal', 'm3', 'ft3', 'm', 'cm', 'mm', 'ft', 'in', 'units', 'pcs', 'pieces', 'boxes', 'pallets', 'containers'];
      confirmInputs.forEach(input => {
        const stepUnit = (input.unit || '').trim();
        const unitOptions = stepUnit && !standardUnits.includes(stepUnit) ? [stepUnit, ...standardUnits] : standardUnits;
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
              ${unitOptions.map(unit => `
                <option value="${escapeHtml(unit)}" ${(input.unit || '') === unit ? 'selected' : ''}>${escapeHtml(unit)}</option>
              `).join('')}
            </select>
          </div>
        `;
        
        const quantityInput = inputSection.querySelector('.execute-confirm-quantity-input');
        const unitSelect = inputSection.querySelector('.execute-confirm-unit-input');
        if (unitSelect && stepUnit) {
          unitSelect.value = stepUnit;
        }
        
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
    
    if (variableOutputs.length > 0 && outputsContainer) {
      variableOutputs.forEach(output => {
        const outputSection = document.createElement('div');
        outputSection.className = 'execute-output-section';
        outputSection.style.cssText = 'margin-bottom: 20px; padding: 16px; border: 1px solid var(--border-light); border-radius: var(--radius-md);';
        
        outputSection.innerHTML = `
          <div style="margin-bottom: 12px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
              ${escapeHtml(output.name)} 
              <span style="color: var(--text-secondary); font-weight: normal;">(Expected: ${output.quantity || '0'} ${output.unit || ''})</span>
            </label>
            <input type="number" class="form-input execute-output-quantity-input" data-output-name="${escapeHtml(output.name)}" placeholder="${output.quantity || '0'}" value="${output.quantity || ''}" step="0.01" min="0" style="width: 100%; padding: 10px 16px; border-radius: var(--radius-lg); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;">
            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">Actual produced quantity (override if different from expected)</p>
          </div>
        `;
        
        outputsContainer.appendChild(outputSection);
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
      
      // First, collect variable outputs (user-entered quantities)
      const outputInputs = modal.querySelectorAll('.execute-output-quantity-input');
      const variableOutputNames = new Set();
      outputInputs.forEach(input => {
        const name = input.dataset.outputName;
        const quantity = parseFloat(input.value);
        if (name && !isNaN(quantity)) {
          const outputDef = allStepOutputs.find(o => o.name === name);
          
          actualOutputs.push({
            name: name,
            quantity: quantity,
            unit: outputDef ? (outputDef.unit || 'units') : 'units'
          });
          variableOutputNames.add(name);
        }
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
      await CoreAPI.completeStep(executionId, executionStepId, {
        actual_inputs: actualInputs,
        actual_outputs: actualOutputs,
        execution_data: executionData
      });
      
      // Close modal
      modal.style.display = 'none';
      document.body.style.overflow = 'auto';
      
      showNotification('success', 'Step Completed', 'Step has been completed successfully.');
      
      // Call configurable callback to reload data
      if (config.onStepCompleted) {
        await config.onStepCompleted();
      }
      
    } catch (error) {
      console.error('Failed to complete step:', error);
      showNotification('error', 'Failed to Complete Step', error.message || 'Failed to complete step. Please try again.');
    }
  };
  
  // Open "Record missing output item" modal (used when Add missing item is for an input that is a previous-step output)
  function openRecordMissingOutputModal() {
    const ctx = _missingItemContext;
    const outputModal = document.getElementById('execute-missing-output-modal');
    if (!ctx || !outputModal) return;
    const input = ctx.input;
    const executionId = ctx.executionId;
    const executionStep = ctx.executionStep;
    const container = document.getElementById('execute-missing-output-form-container');
    if (!container) return;

    function closeOutputModal() {
      if (outputModal) {
        outputModal.style.display = 'none';
        document.body.style.overflow = '';
      }
    }

    container.innerHTML = '<p style="color: var(--text-secondary); font-size: 13px;">Loading...</p>';
    var safeName = (input && input.name && typeof escapeHtml === 'function') ? escapeHtml(input.name) : (input && input.name ? String(input.name).replace(/"/g, '&quot;').replace(/</g, '&lt;') : '');
    var safeUnit = (input && input.unit && typeof escapeHtml === 'function') ? escapeHtml(input.unit) : (input && input.unit ? String(input.unit).replace(/"/g, '&quot;').replace(/</g, '&lt;') : '');
    var formHtml = '<div style="padding: 0 0 20px 0;">' +
      '<p style="font-size: 12px; color: var(--text-secondary); margin: 0 0 12px 0;">Record a missing output item that should have been produced earlier.</p>' +
      '<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px;">' +
      '<div><label style="display: block; font-size: 12px; font-weight: 500; color: var(--text-primary); margin-bottom: 4px;">Process</label>' +
      '<select class="form-select execute-missing-output-process" style="width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 13px;"><option value="">Loading...</option></select></div>' +
      '<div><label style="display: block; font-size: 12px; font-weight: 500; color: var(--text-primary); margin-bottom: 4px;">Step</label>' +
      '<select class="form-select execute-missing-output-step" style="width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 13px;"><option value="">Select process first</option></select></div></div>' +
      '<div style="margin-bottom: 12px;"><label style="display: block; font-size: 12px; font-weight: 500; color: var(--text-primary); margin-bottom: 4px;">Item Name</label>' +
      '<input type="text" class="form-input execute-missing-output-name" value="' + safeName + '" style="width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 13px;"></div>' +
      '<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px;">' +
      '<div><label style="display: block; font-size: 12px; font-weight: 500; color: var(--text-primary); margin-bottom: 4px;">Quantity</label>' +
      '<input type="number" class="form-input execute-missing-output-quantity" value="' + (input && input.quantity != null ? input.quantity : '') + '" step="0.01" min="0.01" style="width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 13px;"></div>' +
      '<div><label style="display: block; font-size: 12px; font-weight: 500; color: var(--text-primary); margin-bottom: 4px;">Unit</label>' +
      '<input type="text" class="form-input execute-missing-output-unit" value="' + safeUnit + '" style="width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 13px;"></div></div>' +
      '<div style="margin-bottom: 16px;"><label style="display: block; font-size: 12px; font-weight: 500; color: var(--text-primary); margin-bottom: 4px;">Date (when this output was produced)</label>' +
      '<input type="date" class="form-input execute-missing-output-date" style="width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 13px;"></div>' +
      '<div style="display: flex; justify-content: flex-end; gap: 8px;">' +
      '<button type="button" class="btn btn-secondary execute-missing-output-cancel">Cancel</button>' +
      '<button type="button" class="btn btn-primary execute-missing-output-save">Save and refresh</button></div></div>';
    container.innerHTML = formHtml;

    outputModal.style.zIndex = '1100';
    outputModal.style.display = 'flex';
    document.body.style.overflow = 'hidden';

    var outNameInput = container.querySelector('.execute-missing-output-name');
    var outQtyInput = container.querySelector('.execute-missing-output-quantity');
    var outUnitInput = container.querySelector('.execute-missing-output-unit');
    var outDateInput = container.querySelector('.execute-missing-output-date');
    var processSelect = container.querySelector('.execute-missing-output-process');
    var stepSelect = container.querySelector('.execute-missing-output-step');
    var outCancelBtn = container.querySelector('.execute-missing-output-cancel');
    var outSaveBtn = container.querySelector('.execute-missing-output-save');

    if (outCancelBtn) outCancelBtn.addEventListener('click', closeOutputModal);

    (async function () {
      try {
        var execData = await CoreAPI.getExecution(executionId);
        var currentProcessId = execData.process_id;
        var processes = await CoreAPI.getProcesses();
        if (processSelect) {
          processSelect.innerHTML = '';
          processes.forEach(function (proc) {
            var opt = document.createElement('option');
            opt.value = proc.id;
            opt.textContent = proc.name || 'Untitled process';
            if (String(proc.id) === String(currentProcessId)) opt.selected = true;
            processSelect.appendChild(opt);
          });
        }
        async function loadSteps(processId, preselectStep) {
          if (!stepSelect || !processId) return;
          stepSelect.innerHTML = '<option value="">Loading...</option>';
          try {
            var processData = await CoreAPI.getProcess(processId);
            var steps = processData.steps || [];
            stepSelect.innerHTML = '';
            steps.forEach(function (step) {
              var o = document.createElement('option');
              o.value = step.id;
              o.textContent = step.name || 'Untitled step';
              if (preselectStep && executionStep && executionStep.step_id && String(step.id) === String(executionStep.step_id)) o.selected = true;
              stepSelect.appendChild(o);
            });
            var selStepId = stepSelect.value;
            var selStep = steps.find(function (s) { return String(s.id) === String(selStepId); });
            if (selStep && selStep.outputs && selStep.outputs.length > 0) {
              var def = selStep.outputs[0];
              if (outNameInput) outNameInput.value = def.name || outNameInput.value;
              if (outQtyInput && def.quantity != null) outQtyInput.value = def.quantity;
              if (outUnitInput && def.unit) outUnitInput.value = def.unit;
            }
          } catch (err) {
            stepSelect.innerHTML = '<option value="">Failed to load</option>';
          }
        }
        await loadSteps(currentProcessId, true);
        if (processSelect) processSelect.addEventListener('change', function () { loadSteps(this.value, false); });
      } catch (err) {
        if (processSelect) processSelect.innerHTML = '<option value="">Failed to load</option>';
      }
    })();

    if (outSaveBtn && outNameInput && outQtyInput && outUnitInput) {
      outSaveBtn.addEventListener('click', async function () {
        var itemName = (outNameInput.value || '').trim() || (input && input.name) || '';
        var qty = parseFloat(outQtyInput.value);
        var unitValue = (outUnitInput.value || (input && input.unit) || '').trim();
        var dateValue = outDateInput && outDateInput.value ? outDateInput.value : null;
        var selectedProcessId = processSelect && processSelect.value ? processSelect.value : null;
        var selectedStepId = stepSelect && stepSelect.value ? stepSelect.value : null;
        if (!selectedProcessId) { showNotification('error', 'Missing Process', 'Please select a process.'); return; }
        if (!selectedStepId) { showNotification('error', 'Missing Step', 'Please select a step.'); return; }
        if (!itemName) { showNotification('error', 'Invalid Name', 'Please enter a name.'); return; }
        if (!qty || isNaN(qty) || qty <= 0) { showNotification('error', 'Invalid Quantity', 'Please enter a valid quantity.'); return; }
        if (!unitValue) { showNotification('error', 'Invalid Unit', 'Please enter a unit.'); return; }
        try {
          var processDataForOutputs = await CoreAPI.getProcess(selectedProcessId);
          var allSteps = processDataForOutputs.steps || [];
          var matchedStep = allSteps.find(function (s) { return String(s.id) === String(selectedStepId); }) || null;
          var inventoryType = (matchedStep && matchedStep.is_terminal_step) ? 'final_product' : 'work_in_progress';
          var metadataExtras = {};
          if (dateValue) metadataExtras.untracked_output_date = dateValue;
          closeOutputModal();
          await createUntrackedItemWithContext(ctx, {
            name: itemName,
            quantity: qty,
            unit: unitValue,
            inventoryType: inventoryType,
            sourceType: 'missing_output',
            inputName: input && input.name ? input.name : null,
            processId: selectedProcessId,
            stepId: matchedStep ? matchedStep.id : selectedStepId,
            metadataExtras: metadataExtras
          });
        } catch (error) {
          console.error('Failed to record missing output:', error);
          showNotification('error', 'Failed to Record Missing Output', error.message || 'Please try again.');
        }
      });
    }
  }

  // One-time wiring: output modal close button
  function wireMissingItemModals() {
    const outputModal = document.getElementById('execute-missing-output-modal');
    if (!outputModal) return;
    function closeOutputModal() {
      outputModal.style.display = 'none';
      document.body.style.overflow = '';
    }
    outputModal.querySelectorAll('.execute-missing-output-close').forEach(function (b) {
      b.addEventListener('click', closeOutputModal);
    });
  }
  
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wireMissingItemModals);
  } else {
    wireMissingItemModals();
  }
  
})();
