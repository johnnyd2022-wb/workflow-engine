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
    
    // Load inventory for variable inputs (includes system_findings e.g. output_ready_date)
    const inventoryData = await CoreAPI.getInventory();
    const allInventory = inventoryData.inventory_items || [];
    modal._inventoryForSubmit = allInventory;
    
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
        const errorMessage = hasNoInventory ? `<p style="color: var(--error, #ef4444); font-size: 12px; margin-top: 4px; font-weight: 500;">⚠️ No matching inventory items found. Please add inventory before executing this step.</p>` : '';
        
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
                
                // Build the display text - prepend process name to product name; show Not ready if output_ready_date finding
                const hasReadyDateFinding = Array.isArray(inv.system_findings) && inv.system_findings.some(f => f && f.check_id === 'output_ready_date');
                const productName = inv.process_name ? `${escapeHtml(inv.process_name)} - ${escapeHtml(inv.name)}` : escapeHtml(inv.name);
                let displayText = `${productName} - ${inv.quantity} ${inv.unit}`;
                if (hasReadyDateFinding) displayText += ' \u26A0\uFE0F Not ready';
                
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
                
                return `
                  <option value="${inv.id}" data-quantity="${inv.quantity}" data-unit="${inv.unit}" title="${escapeHtml(displayText)}">
                    ${displayText}
                  </option>
                `;
              }).join('')}
            </select>
            ${errorMessage}
          </div>
          <div>
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">Quantity to Consume <span style="color: var(--error, #ef4444);">*</span></label>
            <div style="display: flex; align-items: center; gap: 8px;">
              <input type="number" class="form-input execute-quantity-input" data-input-name="${escapeHtml(input.name)}" data-step-unit="${escapeHtml(input.unit || '')}" data-required="true" required placeholder="${input.quantity || '0'}" value="${input.quantity || ''}" step="0.01" min="0.01" style="flex: 1; padding: 10px 16px; border-radius: var(--radius-lg); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;">
              <span class="execute-quantity-unit-display" style="font-size: 14px; color: var(--text-secondary); min-width: 40px; text-align: left;">${input.unit || ''}</span>
            </div>
            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">Quantity will be converted to selected inventory item's unit automatically</p>
          </div>
        `;
        
        // Add event listeners to clear error styling when user fixes issues
        const select = inputSection.querySelector('.execute-inventory-select');
        const quantityInput = inputSection.querySelector('.execute-quantity-input');
        const unitDisplay = inputSection.querySelector('.execute-quantity-unit-display');
        
        if (select) {
          select.addEventListener('change', function() {
            if (this.value) {
              this.style.border = '';
              // Update unit display and convert quantity to match selected inventory item
              const option = this.options[this.selectedIndex];
              if (option && unitDisplay && quantityInput) {
                const inventoryUnit = option.dataset.unit || '';
                const stepUnit = quantityInput.dataset.stepUnit || '';
                const currentQuantity = parseFloat(quantityInput.value) || 0;
                
                // Convert quantity from step definition unit to inventory unit
                if (stepUnit && inventoryUnit && stepUnit.toLowerCase() !== inventoryUnit.toLowerCase()) {
                  const convertedQuantity = convertUnit(currentQuantity, stepUnit, inventoryUnit);
                  quantityInput.value = convertedQuantity.toFixed(6).replace(/\.?0+$/, ''); // Remove trailing zeros
                }
                
                // Update unit display
                unitDisplay.textContent = inventoryUnit;
                // Store the unit on the quantity input for validation
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
            } else if (unitDisplay && quantityInput) {
              // Reset unit display and quantity to step definition values when no inventory is selected
              const stepUnit = quantityInput.dataset.stepUnit || input.unit || '';
              unitDisplay.textContent = stepUnit;
              // Reset quantity to original step definition value
              quantityInput.value = input.quantity || '';
              quantityInput.dataset.inventoryUnit = '';
            }
          });
        }
        
        if (quantityInput) {
          quantityInput.addEventListener('input', function() {
            const qty = parseFloat(this.value);
            if (qty && qty > 0) {
              this.style.border = '';
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
    
    if (variableOutputs.length > 0 && outputsContainer) {
      variableOutputs.forEach(output => {
        const outputSection = document.createElement('div');
        outputSection.className = 'execute-output-section';
        outputSection.style.cssText = 'margin-bottom: 20px; padding: 16px; border: 1px solid var(--border-light); border-radius: var(--radius-md);';
        const outputId = (typeof window.getExecutionOutputId === 'function') ? window.getExecutionOutputId(output) : (output.id || 'out-' + (output.name || '').replace(/\s+/g, '-'));
        const ce = (output.extra_data || {}).custom_expiry;
        const rd = (output.extra_data || {}).ready_date;
        let customExpiryHtml = '';
        let expiryInputHtml = '';
        let readyDateHtml = '';
        if (ce && ce.enabled) {
          const mode = (ce.mode || '').trim();
          if (mode !== 'fixed_duration' && mode !== 'set_at_execution') return;
          if (mode === 'fixed_duration') {
            const v = (ce.duration_value != null) ? ce.duration_value : ce.expiry_days;
            const u = (ce.duration_unit || 'days');
            const msg = 'Output must be consumed in ' + String(v != null ? v : 'X') + ' ' + String(u) + '.';
            customExpiryHtml = '<div class="execute-output-expiry-warning" style="margin-bottom: 12px; padding: 10px 14px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; color: #92400e;"><strong>⚠️ Custom expiry rule applies:</strong> ' + escapeHtml(msg) + '</div>';
          } else if (mode === 'set_at_execution') {
            expiryInputHtml = (typeof window.renderExecutionExpiryUI === 'function')
              ? window.renderExecutionExpiryUI(output, escapeHtml)
              : '';
          }
        }
        if (rd && rd.enabled) {
          const rdMode = (rd.mode || '').trim();
          if (rdMode === 'fixed_duration' && rd.duration_value != null && rd.duration_unit) {
            const v = rd.duration_value;
            const u = rd.duration_unit;
            const msg = 'Output cannot be consumed for ' + String(v) + ' ' + String(u) + ' after step completion.';
            readyDateHtml = '<div class="execute-output-ready-date-warning" style="margin-bottom: 12px; padding: 10px 14px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; color: #92400e;"><strong>⚠️ Ready Date rule applies:</strong> ' + escapeHtml(msg) + '</div>';
          } else if (rdMode === 'set_at_execution') {
            readyDateHtml = (typeof window.renderExecutionReadyDateUI === 'function')
              ? window.renderExecutionReadyDateUI(output, escapeHtml)
              : '';
          } else if (rd.date) {
            const readyDate = new Date(rd.date);
            if (!isNaN(readyDate.getTime()) && readyDate > new Date()) {
              const msg = (rd.prompt && rd.prompt.trim()) ? escapeHtml(rd.prompt.trim()) : ('This output cannot be used until ' + readyDate.toLocaleDateString(undefined, { dateStyle: 'long' }) + '.');
              readyDateHtml = '<div class="execute-output-ready-date-warning" style="margin-bottom: 12px; padding: 10px 14px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; color: #92400e;"><strong>⚠️ Ready Date rule applies:</strong> ' + msg + '</div>';
            }
          }
        }
        outputSection.innerHTML = `
          ${customExpiryHtml}
          ${readyDateHtml}
          ${expiryInputHtml}
          <div style="margin-bottom: 12px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
              ${escapeHtml(output.name)} 
              <span style="color: var(--text-secondary); font-weight: normal;">(Expected: ${output.quantity || '0'} ${output.unit || ''})</span>
            </label>
            <input type="number" class="form-input execute-output-quantity-input" data-output-id="${escapeHtml(outputId)}" placeholder="${output.quantity || '0'}" value="${output.quantity || ''}" step="0.01" min="0" style="width: 100%; padding: 10px 16px; border-radius: var(--radius-lg); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px;">
            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">Actual produced quantity (override if different from expected)</p>
          </div>
        `;
        
        outputsContainer.appendChild(outputSection);

        // Wire expiry input toggle (set_at_execution)
        try {
          const expiryBox = outputSection.querySelector('.execute-output-expiry-input');
          if (expiryBox) {
            const modeSel = outputSection.querySelector('.execute-output-expiry-input-mode');
            const durFields = outputSection.querySelector('.execute-output-expiry-duration-fields');
            const dtFields = outputSection.querySelector('.execute-output-expiry-datetime-fields');
            const warnFields = outputSection.querySelector('.execute-output-expiry-warning-fields');
            if (modeSel && durFields && dtFields) {
              const apply = function() {
                const v = modeSel.value;
                durFields.style.display = v === 'duration' ? 'block' : 'none';
                dtFields.style.display = v === 'datetime' ? 'block' : 'none';
                if (warnFields) warnFields.style.display = (v === 'duration' || v === 'datetime') ? 'block' : 'none';
              };
              modeSel.addEventListener('change', apply);
              apply();
              (function() {
                const validator = window.CustomExpiryValidation;
                function runValidation() {
                  const v = modeSel.value;
                  const errEl = expiryBox.querySelector('.execute-output-expiry-validation-error');
                  const warnValEl = expiryBox.querySelector('.execute-output-expiry-warning-value');
                  const warnUnitEl = expiryBox.querySelector('.execute-output-expiry-warning-unit');
                  if (!errEl || !warnValEl || !warnUnitEl) return;
                  errEl.style.display = 'none';
                  errEl.textContent = '';
                  warnValEl.style.borderColor = '';
                  warnUnitEl.style.borderColor = '';
                  if (v !== 'duration' && v !== 'datetime') return;
                  const warnVal = parseInt(warnValEl.value, 10);
                  const warnUnit = (warnUnitEl.value || 'days').trim();
                  let expiryHours = null;
                  let expiryLabel = 'the expiry period';
                  if (v === 'duration') {
                    const durValEl = expiryBox.querySelector('.execute-output-expiry-duration-value');
                    const durUnitEl = expiryBox.querySelector('.execute-output-expiry-duration-unit');
                    const durVal = durValEl ? parseInt(durValEl.value, 10) : null;
                    const durUnit = (durUnitEl ? (durUnitEl.value || 'days') : 'days').trim();
                    expiryHours = validator && typeof validator.durationToHours === 'function'
                      ? validator.durationToHours(durVal != null && !isNaN(durVal) ? durVal : null, durUnit)
                      : null;
                    expiryLabel = (durVal != null ? durVal : '') + ' ' + durUnit;
                  } else {
                    const dtEl = expiryBox.querySelector('.execute-output-expiry-datetime');
                    const raw = dtEl ? (dtEl.value || '').trim() : '';
                    if (raw) {
                      const expiryAt = new Date(raw);
                      if (!isNaN(expiryAt.getTime())) {
                        expiryHours = (expiryAt.getTime() - Date.now()) / (1000 * 60 * 60);
                        expiryLabel = 'the expiry date/time';
                      }
                    }
                  }
                  if (expiryHours != null && expiryHours <= 0 && v === 'datetime') {
                    errEl.textContent = 'Expiry date and time must be in the future.';
                    errEl.style.display = 'block';
                    return;
                  }
                  const result = validator && typeof validator.validateWarnNotLongerThanExpiry === 'function'
                    ? validator.validateWarnNotLongerThanExpiry({
                        warnValue: isNaN(warnVal) ? null : warnVal,
                        warnUnit: warnUnit,
                        expiryHours: expiryHours,
                        expiryLabel: expiryLabel,
                      })
                    : { valid: true };
                  if (!result.valid) {
                    errEl.textContent = result.message || 'Warn period must not be longer than the expiry period.';
                    errEl.style.display = 'block';
                    warnValEl.style.borderColor = 'var(--danger, #dc2626)';
                    warnUnitEl.style.borderColor = 'var(--danger, #dc2626)';
                  }
                }
                [expiryBox.querySelector('.execute-output-expiry-duration-value'), expiryBox.querySelector('.execute-output-expiry-duration-unit'), expiryBox.querySelector('.execute-output-expiry-warning-value'), expiryBox.querySelector('.execute-output-expiry-warning-unit'), expiryBox.querySelector('.execute-output-expiry-datetime')].forEach(function(el) {
                  if (el) { el.addEventListener('input', runValidation); el.addEventListener('change', runValidation); }
                });
                modeSel.addEventListener('change', runValidation);
              })();
            }
          }
        } catch (e) {}
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

    // Warn if any selected inventory has output_ready_date (not yet ready) and require confirmation
    const invList = modal._inventoryForSubmit || [];
    const notReadyUsed = [];
    inventorySelects.forEach(select => {
      const invId = select.value;
      if (!invId) return;
      const item = invList.find(i => String(i.id) === String(invId));
      if (!item || !Array.isArray(item.system_findings)) return;
      const finding = item.system_findings.find(f => f && f.check_id === 'output_ready_date');
      if (finding) {
        const inputName = select.dataset.inputName || 'Input';
        notReadyUsed.push({ inputName, itemName: item.name || 'Unknown', reason: finding.reason || 'Output not yet ready' });
      }
    });
    if (notReadyUsed.length > 0) {
      const confirmed = typeof window.showReadyDateConfirmModal === 'function'
        ? await window.showReadyDateConfirmModal(notReadyUsed)
        : false;
      if (!confirmed) return;
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

      // Validate set_at_execution expiry: warn must not exceed expiry period (use shared validator)
      const expiryValidator = window.CustomExpiryValidation;
      const expiryValidationErrors = [];
      const getOutputId = window.getExecutionOutputId || function(o) { return (o && o.id) ? String(o.id) : ('out-' + (o && o.name ? String(o.name).replace(/\s+/g, '-') : 'unknown')); };
      (allStepOutputs || []).forEach(function(outputDef) {
        const ce = (outputDef.extra_data || {}).custom_expiry;
        if (!ce || !ce.enabled || (ce.mode || '') !== 'set_at_execution') return;
        const outId = getOutputId(outputDef);
        const outName = (outputDef.name || '').trim();
        const box = Array.from(modal.querySelectorAll('.execute-output-expiry-input')).find(function(b) {
          return (b.dataset.outputId || '').trim() === outId;
        });
        if (!box) return;
        const modeSel = box.querySelector('.execute-output-expiry-input-mode');
        const inputMode = modeSel ? (modeSel.value || 'duration') : 'duration';
        const warnValEl = box.querySelector('.execute-output-expiry-warning-value');
        const warnUnitEl = box.querySelector('.execute-output-expiry-warning-unit');
        const warnVal = warnValEl ? parseInt((warnValEl.value || '').trim(), 10) : 0;
        const warnUnit = ((warnUnitEl && warnUnitEl.value) || 'days').trim();
        let expiryHours = null;
        let expiryLabel = 'the expiry period';
        if (inputMode === 'duration') {
          const dvEl = box.querySelector('.execute-output-expiry-duration-value');
          const duEl = box.querySelector('.execute-output-expiry-duration-unit');
          const dv = dvEl ? parseInt((dvEl.value || '').trim(), 10) : null;
          const du = ((duEl && duEl.value) || 'days').trim();
          expiryHours = expiryValidator && typeof expiryValidator.durationToHours === 'function'
            ? expiryValidator.durationToHours(dv != null && !isNaN(dv) ? dv : null, du)
            : null;
          expiryLabel = (dv != null ? dv : '') + ' ' + du;
        } else {
          const dtEl = box.querySelector('.execute-output-expiry-datetime');
          const raw = dtEl ? (dtEl.value || '').trim() : '';
          if (raw) {
            const expiryAt = new Date(raw);
            if (!isNaN(expiryAt.getTime())) {
              expiryHours = (expiryAt.getTime() - Date.now()) / (1000 * 60 * 60);
              expiryLabel = 'the expiry date/time';
            }
          }
        }
        if (expiryHours != null && expiryHours <= 0 && inputMode === 'datetime') {
          expiryValidationErrors.push('Output "' + outName + '": expiry date and time must be in the future.');
          return;
        }
        const result = expiryValidator && typeof expiryValidator.validateWarnNotLongerThanExpiry === 'function'
          ? expiryValidator.validateWarnNotLongerThanExpiry({
              outputName: outName,
              warnValue: isNaN(warnVal) ? null : warnVal,
              warnUnit: warnUnit,
              expiryHours: expiryHours,
              expiryLabel: expiryLabel,
            })
          : { valid: true };
        if (!result.valid) {
          expiryValidationErrors.push(result.message || 'Output "' + outName + '": warn period must not be longer than the expiry period.');
        }
      });
      if (expiryValidationErrors.length > 0) {
        showNotification('error', 'Invalid expiry settings', expiryValidationErrors[0]);
        const firstBox = modal.querySelector('.execute-output-expiry-input');
        if (firstBox) firstBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }

      const readyDateValidationErrors = [];
      (allStepOutputs || []).forEach(outputDef => {
        const rd = (outputDef.extra_data || {}).ready_date;
        if (!rd || !rd.enabled || (rd.mode || '') !== 'set_at_execution') return;
        const outName = (outputDef.name || '').trim();
        const getOutputId = window.getExecutionOutputId || (o => (o && o.id) ? String(o.id) : ('out-' + (o && o.name ? String(o.name).replace(/\s+/g, '-') : 'unknown')));
        const outputId = getOutputId(outputDef);
        const payload = (typeof window.collectExecutionOutputReadyDatePayload === 'function')
          ? window.collectExecutionOutputReadyDatePayload(modal, outputId)
          : null;
        if (!payload || !payload.date) {
          readyDateValidationErrors.push('Output "' + outName + '": set the date when this output can be used.');
        }
      });
      if (readyDateValidationErrors.length > 0) {
        showNotification('error', 'Ready date required', readyDateValidationErrors[0]);
        const firstReadyBox = modal.querySelector('.execute-output-ready-date-input');
        if (firstReadyBox) firstReadyBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }

      // First, collect variable outputs (user-entered quantities)
      const outputInputs = modal.querySelectorAll('.execute-output-quantity-input');
      const variableOutputNames = new Set();
      const getOutputIdForPayload = window.getExecutionOutputId || function(o) { return (o && o.id) ? String(o.id) : ('out-' + (o && o.name ? String(o.name).replace(/\s+/g, '-') : 'unknown')); };
      outputInputs.forEach(input => {
        const outputId = (input.dataset.outputId || '').trim();
        if (!outputId) return;
        const outputDef = allStepOutputs.find(o => getOutputIdForPayload(o) === outputId);
        if (!outputDef) return;
        const name = outputDef.name;
        const quantity = parseFloat(input.value);
        if (name && !isNaN(quantity)) {
          const outPayload = {
            name: name,
            quantity: quantity,
            unit: (outputDef ? (outputDef.unit || 'units') : 'units').trim()
          };
          // Capture operator-set expiry when configured as set_at_execution (logic in core-api.js)
          if (typeof window.applyExecutionOutputExpiryToPayload === 'function') {
            window.applyExecutionOutputExpiryToPayload(modal, outputId, outputDef, outPayload);
          }
          if (typeof window.applyExecutionOutputReadyDateToPayload === 'function') {
            window.applyExecutionOutputReadyDateToPayload(modal, outputId, outputDef, outPayload);
          }
          actualOutputs.push(outPayload);
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
            unit: (outputDef.unit || 'units').trim()
          });
        }
      });
      
      // Get current user for recording
      const user = await getCurrentUser();
      executionData.completed_by = user.username;
      executionData.completed_by_email = user.email;
      executionData.completed_at = new Date().toISOString();
      
      // Complete the step
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
  
})();
