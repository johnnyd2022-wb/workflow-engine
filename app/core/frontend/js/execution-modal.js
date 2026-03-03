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

  // Full-screen doc overlay (app-like): no browser back button; "Back to step" closes overlay. Reusable for future SPA.
  window.openDocFullScreenOverlay = function(docUrl, docTitle) {
    if (!docUrl || docUrl === '#') return;
    var overlay = document.createElement('div');
    overlay.id = 'doc-fullscreen-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-label', docTitle || 'Step instructions');
    overlay.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 1100; display: flex; flex-direction: column; background: var(--bg-primary, #fff);';
    var bar = document.createElement('div');
    bar.style.cssText = 'flex-shrink: 0; display: flex; align-items: center; min-height: 48px; padding: 0 16px; border-bottom: 1px solid var(--border-default, #e5e7eb); background: var(--bg-card, #fff);';
    var backBtn = document.createElement('button');
    backBtn.type = 'button';
    backBtn.className = 'btn btn-secondary';
    backBtn.innerHTML = '&#8592; Back to step';
    backBtn.onclick = function() {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    };
    bar.appendChild(backBtn);
    var frameWrap = document.createElement('div');
    frameWrap.style.cssText = 'flex: 1; min-height: 0; width: 100%;';
    var iframe = document.createElement('iframe');
    iframe.src = docUrl;
    iframe.title = docTitle || 'Step instructions';
    iframe.style.cssText = 'width: 100%; height: 100%; border: none; display: block;';
    frameWrap.appendChild(iframe);
    overlay.appendChild(bar);
    overlay.appendChild(frameWrap);
    document.body.appendChild(overlay);
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
    const docsContainer = modal.querySelector('#execute-docs-container');
    const docsSection = modal.querySelector('#execute-docs-section');
    
    if (inputsContainer) inputsContainer.innerHTML = '';
    if (promptsContainer) promptsContainer.innerHTML = '';
    if (outputsContainer) outputsContainer.innerHTML = '';
    if (docsContainer) docsContainer.innerHTML = '';
    if (docsSection) docsSection.style.display = 'none';
    
    // Load inventory, expired/flagged, untracked, and step documentation in parallel
    const stepId = stepDefinition && stepDefinition.id ? String(stepDefinition.id) : null;
    const docsPromise = (stepId && typeof CoreAPI.getStepDocumentation === 'function')
      ? CoreAPI.getStepDocumentation(stepId).catch(function() { return { documents: [] }; })
      : Promise.resolve({ documents: [] });
    
    const [inventoryData, expiredData, untrackedData, docsData] = await Promise.all([
      CoreAPI.getInventory(),
      CoreAPI.getExpiredMaterials().catch(function() { return { expired_raw_materials: [], impacted_items: [] }; }),
      CoreAPI.getUntrackedItems().catch(function() { return { untracked_items: [] }; }),
      docsPromise
    ]);
    
    // Render step documentation (SOP) – read-only
    const documents = (docsData && docsData.documents) ? docsData.documents : [];
    if (documents.length > 0 && docsContainer && docsSection) {
      docsSection.style.display = 'block';
      documents.forEach(function(doc) {
        const block = document.createElement('div');
        block.style.cssText = 'margin-bottom: 16px; padding: 12px 16px; border: 1px solid var(--border-light); border-radius: var(--radius-md); background: var(--bg-secondary, #f9fafb);';
        const titleEl = document.createElement('div');
        titleEl.style.cssText = 'font-weight: 600; font-size: 14px; color: var(--text-primary); margin-bottom: 8px;';
        titleEl.textContent = doc.title || 'Documentation';
        block.appendChild(titleEl);
        if (doc.content_markdown) {
          const content = document.createElement('div');
          content.style.cssText = 'font-size: 13px; color: var(--text-primary); white-space: pre-wrap; line-height: 1.5;';
          content.innerHTML = (doc.content_markdown || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
          block.appendChild(content);
        } else if (doc.storage_path && doc.id) {
          const viewUrl = typeof CoreAPI.getProcessDocViewUrl === 'function' ? CoreAPI.getProcessDocViewUrl(doc.id) : '#';
          const downloadUrl = typeof CoreAPI.getProcessDocDownloadUrl === 'function' ? CoreAPI.getProcessDocDownloadUrl(doc.id) : viewUrl;
          const mime = (doc.mime_type || '').toLowerCase();
          const isPdf = mime.indexOf('pdf') !== -1;
          // Narrow viewport only: full-screen in-app overlay with "Back to step". Wide (e.g. touchscreen laptops) opens new tab.
          const isNarrowOrTouch = (typeof window !== 'undefined' && window.innerWidth <= 768);
          const openLabel = isPdf
            ? (isNarrowOrTouch ? 'Open instructions (full screen)' : 'Open PDF in new tab to read')
            : (isNarrowOrTouch ? 'View document' : 'View in new tab');
          const actionsDiv = document.createElement('div');
          actionsDiv.style.cssText = 'margin-top: 12px; display: flex; flex-wrap: wrap; align-items: center; gap: 12px;';
          const openBtn = document.createElement('a');
          openBtn.href = viewUrl;
          openBtn.rel = 'noopener';
          openBtn.target = isNarrowOrTouch ? '_self' : '_blank';
          openBtn.textContent = openLabel;
          openBtn.style.cssText = 'display: inline-flex; align-items: center; justify-content: center; min-height: 44px; min-width: 44px; padding: 12px 18px; background: var(--primary, #2563eb); color: #fff; border-radius: var(--radius-md); font-size: 14px; font-weight: 500; text-decoration: none; box-sizing: border-box;';
          if (isNarrowOrTouch && typeof window.openDocFullScreenOverlay === 'function') {
            openBtn.addEventListener('click', function(e) {
              e.preventDefault();
              window.openDocFullScreenOverlay(viewUrl, doc.title || 'Step instructions');
            });
          }
          const downloadLink = document.createElement('a');
          downloadLink.href = downloadUrl;
          downloadLink.target = '_blank';
          downloadLink.rel = 'noopener';
          downloadLink.download = true;
          downloadLink.textContent = 'Download';
          downloadLink.style.cssText = 'display: inline-flex; align-items: center; min-height: 44px; padding: 0 8px; color: var(--text-secondary); font-size: 14px; text-decoration: none;';
          actionsDiv.appendChild(openBtn);
          actionsDiv.appendChild(downloadLink);
          block.appendChild(actionsDiv);
          if (isPdf) {
            const hint = document.createElement('p');
            hint.style.cssText = 'font-size: 12px; color: var(--text-secondary); margin: 10px 0 0 0; line-height: 1.4;';
            hint.textContent = isNarrowOrTouch
              ? 'Opens full screen in the app. Tap "Back to step" to return.'
              : 'Opens in a new tab so you can read the instructions at full size.';
            block.appendChild(hint);
          }
        }
        docsContainer.appendChild(block);
      });
    }
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
        const safeInputName = (input.name || '').replace(/[^a-zA-Z0-9_-]/g, '_');

        inputSection.innerHTML = `
          <div style="margin-bottom: 12px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
              ${escapeHtml(input.name)} 
              <span style="color: var(--text-secondary); font-weight: normal;">(Expected: ${input.quantity || '0'} ${input.unit || ''})</span>
              <span style="color: var(--error, #ef4444);">*</span>
            </label>
            <input type="hidden" class="execute-inventory-select" data-input-name="${escapeHtml(input.name)}" data-required="true" data-quantity="" data-unit="" data-expired-reason="" value="">
            <div class="execute-inventory-picker-wrapper" style="position: relative;" data-input-name="${escapeHtml(input.name)}">
              <div class="execute-inventory-picker-trigger" role="button" tabindex="0" style="display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 10px 14px; border-radius: var(--radius-md); border: 1px solid var(--border-default); ${errorStyle} background: var(--bg-card); color: var(--text-primary); font-size: 14px; cursor: pointer; min-height: 44px;">
                <span class="execute-inventory-picker-label" style="flex: 1; text-align: left; min-width: 0;">Select inventory item...</span>
                <span class="execute-inventory-picker-arrow-box" style="flex-shrink: 0; margin-left: 8px; display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: var(--radius-md, 6px); border: 1px solid var(--border-default); background: var(--bg-secondary, #f9fafb); color: var(--text-secondary);">
                  <svg class="execute-inventory-picker-arrow" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="transition: transform 0.2s;"><polyline points="6 9 12 15 18 9"/></svg>
                </span>
              </div>
              <div class="execute-inventory-picker-dropdown" style="display: none; position: absolute; top: 100%; left: 0; right: 0; z-index: 100; margin-top: 6px; max-height: 320px; overflow-y: auto; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); box-shadow: 0 10px 25px rgba(0,0,0,0.15); padding: 8px;">
                <div class="execute-inventory-picker-cards" style="display: flex; flex-direction: column; gap: 8px;"></div>
              </div>
            </div>
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

        const hiddenInput = inputSection.querySelector('.execute-inventory-select');
        const quantityInput = inputSection.querySelector('.execute-quantity-input');
        const unitDisplay = inputSection.querySelector('.execute-quantity-unit-display');
        const wrapper = inputSection.querySelector('.execute-inventory-picker-wrapper');
        const trigger = inputSection.querySelector('.execute-inventory-picker-trigger');
        const triggerLabel = inputSection.querySelector('.execute-inventory-picker-label');
        const triggerArrow = inputSection.querySelector('.execute-inventory-picker-arrow');
        const dropdown = inputSection.querySelector('.execute-inventory-picker-dropdown');
        const cardsContainer = inputSection.querySelector('.execute-inventory-picker-cards');
        const expiredWarningEl = inputSection.querySelector('.execute-input-expired-warning');

        function getInventorySelectionLabel(invId) {
          if (!invId) return 'Select inventory item...';
          const inv = sortedInventory.find(function(i) { return String(i.id) === String(invId); });
          if (!inv) return 'Select inventory item...';
          const productName = inv.process_name ? escapeHtml(inv.process_name) + ' - ' + escapeHtml(inv.name) : escapeHtml(inv.name);
          return productName + ' - ' + (inv.quantity != null ? inv.quantity : '') + ' ' + (inv.unit || '');
        }

        function closeInventoryDropdown() {
          if (dropdown) dropdown.style.display = 'none';
          if (triggerArrow) triggerArrow.style.transform = 'rotate(0deg)';
          document.removeEventListener('click', closeInventoryDropdownOutside);
        }
        function closeInventoryDropdownOutside(e) {
          if (wrapper && !wrapper.contains(e.target)) closeInventoryDropdown();
        }
        function openInventoryDropdown() {
          if (dropdown) dropdown.style.display = 'block';
          if (triggerArrow) triggerArrow.style.transform = 'rotate(180deg)';
          setTimeout(function() { document.addEventListener('click', closeInventoryDropdownOutside); }, 0);
        }
        function setInventorySelection(invId) {
          hiddenInput.value = invId || '';
          hiddenInput.dataset.quantity = '';
          hiddenInput.dataset.unit = '';
          hiddenInput.dataset.expiredReason = '';
          if (triggerLabel) triggerLabel.textContent = getInventorySelectionLabel(invId);
          if (wrapper) {
            wrapper.querySelectorAll('.execute-inventory-input-card').forEach(function(c) {
              var id = c.dataset.inventoryId || '';
              var selected = id === (invId || '');
              c.classList.toggle('execute-reconcile-card-selected', selected);
              c.style.borderColor = selected ? 'var(--primary, #2563eb)' : '';
              c.style.boxShadow = selected ? '0 0 0 2px rgba(37, 99, 235, 0.25)' : '';
            });
          }
          if (trigger) {
            trigger.style.border = '';
            trigger.style.boxShadow = '';
          }
          if (expiredWarningEl) {
            expiredWarningEl.style.display = 'none';
            expiredWarningEl.textContent = '';
          }
          if (!invId) {
            if (unitDisplay && quantityInput) {
              unitDisplay.textContent = quantityInput.dataset.stepUnit || input.unit || '';
              quantityInput.value = input.quantity || '';
              quantityInput.dataset.originalQuantity = input.quantity || '';
              quantityInput.dataset.inventoryUnit = '';
            }
            closeInventoryDropdown();
            return;
          }
          const inv = sortedInventory.find(function(i) { return String(i.id) === String(invId); });
          if (inv && unitDisplay && quantityInput) {
            quantityInput.value = inv.quantity != null && inv.quantity !== '' ? inv.quantity : quantityInput.value;
            quantityInput.dataset.originalQuantity = inv.quantity != null ? String(inv.quantity) : '';
            unitDisplay.textContent = inv.unit || '';
            quantityInput.dataset.inventoryUnit = inv.unit || '';
          }
          if (inv) {
            hiddenInput.dataset.quantity = inv.quantity != null ? String(inv.quantity) : '';
            hiddenInput.dataset.unit = inv.unit || '';
            const reason = getExpiredReason(inv.id);
            hiddenInput.dataset.expiredReason = reason || '';
            if (reason && expiredWarningEl) {
              expiredWarningEl.textContent = 'Check: ' + reason;
              expiredWarningEl.style.display = 'block';
            }
            if (trigger) {
              trigger.style.border = reason ? '2px solid var(--error, #ef4444)' : '';
              trigger.style.boxShadow = reason ? '0 0 0 1px var(--error, #ef4444)' : '';
            }
          }
          if (quantityInput) quantityInput.style.border = '';
          const submitBtn = modal.querySelector('#execute-step-submit-btn');
          if (submitBtn && submitBtn.disabled) {
            const allRequired = modal.querySelectorAll('.execute-inventory-select[data-required="true"]');
            let allHave = true;
            allRequired.forEach(function(s) { if (!s.value || s.value === '') allHave = false; });
            if (allHave) {
              submitBtn.disabled = false;
              submitBtn.style.opacity = '1';
              submitBtn.style.cursor = 'pointer';
              submitBtn.title = '';
            }
          }
          closeInventoryDropdown();
        }

        function toggleInventoryCardDetails(cardId) {
          var details = inputSection.querySelector('#execute-inv-details-' + safeInputName + '-' + cardId);
          var arrow = inputSection.querySelector('#execute-inv-arrow-' + safeInputName + '-' + cardId);
          if (!details || !arrow) return;
          var isExpanded = details.style.display === 'block';
          details.style.display = isExpanded ? 'none' : 'block';
          arrow.style.transform = isExpanded ? 'rotate(0deg)' : 'rotate(90deg)';
        }

        if (trigger) {
          trigger.addEventListener('click', function(e) { e.stopPropagation(); if (dropdown.style.display === 'block') closeInventoryDropdown(); else openInventoryDropdown(); });
          trigger.addEventListener('keydown', function(e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (dropdown.style.display === 'block') closeInventoryDropdown(); else openInventoryDropdown(); } });
        }
        if (dropdown) dropdown.addEventListener('click', function(e) { e.stopPropagation(); });

        var noneCard = document.createElement('div');
        noneCard.className = 'execute-inventory-input-card execute-reconcile-untracked-card' + (sortedInventory.length > 0 ? '' : ' execute-reconcile-card-selected');
        noneCard.dataset.inventoryId = '';
        noneCard.style.cssText = 'padding: 10px 14px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s;';
        noneCard.innerHTML = '<span style="color: var(--text-secondary); font-size: 13px;">— None —</span>';
        noneCard.onclick = function(e) { e.stopPropagation(); setInventorySelection(''); };
        cardsContainer.appendChild(noneCard);

        sortedInventory.forEach(function(inv) {
          var id = String(inv.id);
          var card = document.createElement('div');
          card.className = 'execute-inventory-input-card card card-interactive execute-reconcile-untracked-card';
          card.dataset.inventoryId = id;
          card.style.cssText = 'margin-bottom: 0; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s; overflow: hidden;';
          var createdStr = '';
          if (inv.created_at) {
            try { createdStr = new Date(inv.created_at).toLocaleDateString(); } catch (e) {}
          }
          var subtitleParts = [];
          subtitleParts.push(escapeHtml(inv.quantity != null ? String(inv.quantity) : '0') + ' ' + escapeHtml(inv.unit || ''));
          if (inv.process_name) subtitleParts.push(escapeHtml(inv.process_name));
          var subtitleLine = subtitleParts.join(' · ');
          var detailsParts = [];
          if (inv.quantity != null) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Quantity</span> ' + escapeHtml(String(inv.quantity)) + ' ' + escapeHtml(inv.unit || '') + '</p>');
          if (inv.process_name) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Process</span> ' + escapeHtml(inv.process_name) + '</p>');
          if (createdStr) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Created</span> ' + escapeHtml(createdStr) + '</p>');
          if (inv.supplier) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Supplier</span> ' + escapeHtml(inv.supplier) + '</p>');
          if (inv.supplier_batch_number) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Batch</span> ' + escapeHtml(inv.supplier_batch_number) + '</p>');
          var promptsHtml = '';
          if (inv.extra_data && inv.extra_data.execution_prompts && typeof inv.extra_data.execution_prompts === 'object') {
            var prompts = inv.extra_data.execution_prompts;
            promptsHtml = '<div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-default);"><div style="font-size: 11px; font-weight: 600; color: var(--text-secondary); margin-bottom: 8px;">Step metadata</div><div style="display: flex; flex-direction: column; gap: 6px;">' +
              Object.entries(prompts).map(function(e) {
                return '<div style="padding: 6px 10px; background: var(--bg-secondary, #f9fafb); border-radius: 6px;"><span style="color: var(--text-secondary); font-size: 11px;">' + escapeHtml(e[0]) + '</span><br><span style="color: var(--text-primary); font-size: 13px;">' + escapeHtml(String(e[1])) + '</span></div>';
              }).join('') + '</div></div>';
          }
          var reason = getExpiredReason(inv.id);
          var titlePrefix = reason ? '⚠ ' + escapeHtml(reason) + ': ' : '';
          card.innerHTML =
            '<div class="process-card-header" style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; word-wrap: break-word; overflow-wrap: break-word;">' +
              '<div style="flex: 1; min-width: 0; cursor: pointer;" data-expand-trigger="1">' +
                '<h4 style="margin: 0; font-size: 14px; font-weight: 600; color: var(--text-primary);">' + titlePrefix + escapeHtml(inv.name || 'Unknown') + '</h4>' +
                '<p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-secondary);">' + subtitleLine + '</p>' +
              '</div>' +
              '<svg class="execute-reconcile-arrow" id="execute-inv-arrow-' + safeInputName + '-' + id + '" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink: 0; cursor: pointer; transform: rotate(0deg); transition: transform 0.2s;" data-expand-trigger="1">' +
                '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>' +
              '</svg>' +
            '</div>' +
            '<div class="execute-reconcile-details" id="execute-inv-details-' + safeInputName + '-' + id + '" style="display: none; padding: 12px 16px; border-top: 1px solid var(--border-default); background: var(--bg-secondary, #f9fafb); font-size: 13px;">' +
              detailsParts.join('') + promptsHtml +
            '</div>';
          card.onclick = function(e) {
            if (e.target.closest('[data-expand-trigger="1"]')) {
              e.stopPropagation();
              toggleInventoryCardDetails(id);
              return;
            }
            setInventorySelection(id);
          };
          cardsContainer.appendChild(card);
        });

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
    const currentStepId = stepDefinition.id ? String(stepDefinition.id) : null;
    if (executionPrompts.length > 0 && promptsContainer) {
      var executionIdForEvidence = modal.dataset.executionId || '';
      let evidenceListForStep = [];
      if (typeof CoreAPI.listEvidence === 'function' && executionIdForEvidence && currentStepId) {
        try {
          const res = await CoreAPI.listEvidence(executionIdForEvidence);
          const allEvidence = res.evidence || [];
          var byStepDef = new Map();
          var byExecStep = new Map();
          allEvidence.forEach(function(e) {
            if (e.step_definition_id) {
              var list = byStepDef.get(e.step_definition_id) || [];
              list.push(e);
              byStepDef.set(e.step_definition_id, list);
            }
            if (e.execution_step_id) {
              var list2 = byExecStep.get(e.execution_step_id) || [];
              list2.push(e);
              byExecStep.set(e.execution_step_id, list2);
            }
          });
          var stepList = (byStepDef.get(currentStepId) || []).concat(byExecStep.get(currentStepId) || []);
          evidenceListForStep = stepList.filter(function(e, i, arr) { return arr.findIndex(function(x) { return x.id === e.id; }) === i; });
        } catch (e) { evidenceListForStep = []; }
      }
      if (!modal.evidenceByStepId) modal.evidenceByStepId = new Map();
      modal.evidenceByStepId.set(currentStepId, evidenceListForStep);
      var maxEvidenceBytes = 10 * 1024 * 1024;
      if (typeof CoreAPI.getEvidenceConfig === 'function') {
        try {
          var evidenceCfg = await CoreAPI.getEvidenceConfig();
          if (evidenceCfg && evidenceCfg.max_file_size_bytes != null) maxEvidenceBytes = evidenceCfg.max_file_size_bytes;
        } catch (e) {}
      }
      executionPrompts.forEach(prompt => {
        const promptSection = document.createElement('div');
        promptSection.className = 'execute-prompt-section';
        promptSection.style.cssText = 'margin-bottom: 16px;';
        promptSection.dataset.promptLabel = prompt.label || '';
        promptSection.dataset.promptRequired = prompt.required !== false ? 'true' : 'false';
        promptSection.dataset.promptType = prompt.type || 'text';

        let inputHtml = '';
        if (prompt.type === 'evidence') {
          inputHtml = `
            <div class="execute-evidence-upload" data-step-id="${currentStepId || ''}" style="border: 2px dashed var(--border-default); border-radius: var(--radius-lg); padding: 16px; background: var(--bg-secondary, #f9fafb);">
              <p style="margin: 0 0 8px 0; font-size: 13px; color: var(--text-secondary);">Photos or PDFs (JPEG, PNG, PDF, max 10MB)</p>
              <input type="file" class="execute-evidence-file-input" accept="image/jpeg,image/png,application/pdf" multiple style="display: block; margin-bottom: 8px;">
              <div class="execute-evidence-list" style="margin-top: 12px;"></div>
            </div>
          `;
        } else if (prompt.type === 'text') {
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

        if (prompt.type === 'evidence') {
          const uploadZone = promptSection.querySelector('.execute-evidence-upload');
          const listEl = promptSection.querySelector('.execute-evidence-list');
          const fileInput = promptSection.querySelector('.execute-evidence-file-input');
          function renderEvidenceList(items) {
            if (!listEl) return;
            listEl.innerHTML = items.length === 0 ? '' : items.map(function(item) {
              var viewUrl = typeof CoreAPI.getEvidenceViewUrl === 'function' ? CoreAPI.getEvidenceViewUrl(item.id) : '#';
              var downloadUrl = typeof CoreAPI.getEvidenceDownloadUrl === 'function' ? CoreAPI.getEvidenceDownloadUrl(item.id) : '#';
              var id = (item.id && escapeHtml(item.id)) || '';
              return '<div class="execute-evidence-row" data-evidence-id="' + id + '" style="display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: var(--bg-card); border-radius: var(--radius-md); margin-bottom: 6px; font-size: 13px;"><span>' + escapeHtml(item.file_name || 'File') + '</span><div style="display: flex; gap: 8px; align-items: center;"><a href="' + escapeHtml(viewUrl) + '" target="_blank" rel="noopener" style="margin-left: 8px;">View</a><a href="' + escapeHtml(downloadUrl) + '" target="_blank" rel="noopener" style="margin-left: 4px;">Download</a><button type="button" class="execute-evidence-remove-btn" data-evidence-id="' + id + '" style="margin-left: 8px; padding: 2px 8px; font-size: 12px;">Remove</button></div></div>';
            }).join('');
          }
          listEl.addEventListener('click', async function(ev) {
            var btn = ev.target && ev.target.closest && ev.target.closest('.execute-evidence-remove-btn');
            if (!btn || !btn.dataset || !btn.dataset.evidenceId) return;
            var evidenceId = btn.dataset.evidenceId;
            if (!evidenceId || typeof CoreAPI.deleteEvidence !== 'function') return;
            btn.disabled = true;
            try {
              await CoreAPI.deleteEvidence(evidenceId);
              evidenceListForStep = evidenceListForStep.filter(function(e) { return e.id !== evidenceId; });
              if (modal.evidenceByStepId) modal.evidenceByStepId.set(currentStepId, evidenceListForStep);
              if (uploadZone) uploadZone.dataset.evidenceCount = String(evidenceListForStep.length);
              renderEvidenceList(evidenceListForStep);
              if (typeof showNotification === 'function') showNotification('success', 'Evidence removed', '');
            } catch (err) {
              if (typeof showNotification === 'function') showNotification('error', 'Remove failed', err && err.message ? err.message : 'Could not remove evidence.');
            }
            btn.disabled = false;
          });
          renderEvidenceList(evidenceListForStep);
          uploadZone.dataset.evidenceCount = String(evidenceListForStep.length);
          if (fileInput) {
            fileInput.addEventListener('change', async function() {
              var files = this.files;
              if (!files || !files.length || !executionIdForEvidence || !currentStepId || typeof CoreAPI.uploadEvidence !== 'function') return;
              var toUpload = [];
              for (var i = 0; i < files.length; i++) {
                var file = files[i];
                if (file.size > maxEvidenceBytes) {
                  if (typeof showNotification === 'function') showNotification('error', 'File too large', 'Max ' + Math.round(maxEvidenceBytes / (1024 * 1024)) + 'MB. Choose a smaller file.');
                  continue;
                }
                var fd = new FormData();
                fd.append('file', file);
                fd.append('execution_id', executionIdForEvidence);
                fd.append('step_id', currentStepId);
                toUpload.push(CoreAPI.uploadEvidence(fd));
              }
              if (toUpload.length === 0) { this.value = ''; return; }
              var settled = await Promise.allSettled(toUpload);
              var added = [];
              var failed = 0;
              settled.forEach(function(s, idx) {
                if (s.status === 'fulfilled' && s.value && s.value.id) added.push(s.value);
                else failed++;
              });
              evidenceListForStep = evidenceListForStep.concat(added);
              var seenIds = new Set();
              evidenceListForStep = evidenceListForStep.filter(function(e) {
                if (!e.id || seenIds.has(e.id)) return false;
                seenIds.add(e.id);
                return true;
              });
              if (modal.evidenceByStepId) modal.evidenceByStepId.set(currentStepId, evidenceListForStep);
              uploadZone.dataset.evidenceCount = String(evidenceListForStep.length);
              renderEvidenceList(evidenceListForStep);
              if (failed > 0 && typeof showNotification === 'function') showNotification('warning', 'Partial upload', failed + ' of ' + toUpload.length + ' file(s) failed to upload.');
              this.value = '';
            });
          }
        } else {
          const promptInput = promptSection.querySelector('.execute-prompt-input');
          if (promptInput) {
            promptInput.addEventListener('input', function() {
              if (this.value.trim()) this.style.border = '';
            });
            promptInput.addEventListener('change', function() {
              if (this.value.trim()) this.style.border = '';
            });
          }
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
        var ce = (output.extra_data || {}).custom_expiry;
        var customExpiryHtml = '';
        if (ce && ce.enabled) {
          var days = ce.expiry_days != null ? String(ce.expiry_days) : 'X';
          var prompt = (ce.expiry_prompt || '').trim() || ('This output should be consumed within ' + days + ' days.');
          customExpiryHtml = '<div class="execute-output-expiry-warning" style="margin-bottom: 12px; padding: 10px 14px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; color: #92400e;"><strong>⚠️ Custom expiry rule applies:</strong> ' + escapeHtml(prompt) + '</div>';
        }
        outputSection.innerHTML = `
          ${customExpiryHtml}
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
                <span class="execute-reconcile-trigger-label" style="flex: 1; text-align: left; min-width: 0;">— None —</span>
                <span class="execute-reconcile-trigger-arrow-box" style="flex-shrink: 0; margin-left: 8px; display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: var(--radius-md, 6px); border: 1px solid var(--border-default); background: var(--bg-secondary, #f9fafb); color: var(--text-secondary);">
                  <svg class="execute-reconcile-trigger-arrow" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="transition: transform 0.2s;"><polyline points="6 9 12 15 18 9"/></svg>
                </span>
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
            if (u.process_name || u.producing_step_name || u.step_name) {
              var stepLabel = (u.producing_step_name != null && u.producing_step_name !== '') ? u.producing_step_name : u.step_name;
              var ps = [u.process_name, stepLabel].filter(Boolean).map(function(x) { return escapeHtml(x); }).join(' · ');
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
            if (u.producing_step_name) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Step to execute to reconcile</span> ' + escapeHtml(u.producing_step_name) + '</p>');
            else if (u.step_name) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Step</span> ' + escapeHtml(u.step_name) + '</p>');
            if (createdStr) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Created</span> ' + escapeHtml(createdStr) + '</p>');
            if (u.notes) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Notes</span> ' + escapeHtml(u.notes) + '</p>');
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
      const hiddenInput = section.querySelector('.execute-inventory-select');
      if (hiddenInput && hiddenInput.dataset.required === 'true') {
        const cardsContainer = section.querySelector('.execute-inventory-picker-cards');
        const allCards = cardsContainer ? cardsContainer.querySelectorAll('.execute-inventory-input-card') : [];
        const validCards = Array.from(allCards).filter(function(c) { return (c.dataset.inventoryId || '') !== ''; });
        if (validCards.length === 0) {
          hasMissingInventory = true;
          const inputName = hiddenInput.dataset.inputName;
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
        const triggerEl = select.closest('.execute-input-section') && select.closest('.execute-input-section').querySelector('.execute-inventory-picker-trigger');
        if (triggerEl) triggerEl.style.border = '2px solid var(--error, #ef4444)';
      } else {
        const triggerEl = select.closest('.execute-input-section') && select.closest('.execute-input-section').querySelector('.execute-inventory-picker-trigger');
        if (triggerEl) {
          triggerEl.style.border = '';
          triggerEl.style.boxShadow = '';
        }
        
        // Check quantity
        const quantityInput = modal.querySelector(`.execute-quantity-input[data-input-name="${inputName}"]`);
        if (quantityInput) {
          const quantity = parseFloat(quantityInput.value);
          if (!quantity || isNaN(quantity) || quantity <= 0) {
            validationErrors.push(`Please enter a valid quantity for "${inputName}"`);
            quantityInput.style.border = '2px solid var(--error, #ef4444)';
          } else {
            quantityInput.style.border = '';
            
            // Check if quantity exceeds available inventory (use data on hidden input)
            const availableQty = parseFloat(select.dataset.quantity);
            if (!isNaN(availableQty)) {
              const inventoryUnit = select.dataset.unit || '';
              const quantityUnit = quantityInput.dataset.inventoryUnit || inventoryUnit;
              if (quantity > availableQty) {
                validationErrors.push(`Quantity for "${inputName}" (${quantity} ${quantityUnit}) exceeds available inventory (${availableQty} ${inventoryUnit})`);
                quantityInput.style.border = '2px solid var(--error, #ef4444)';
              }
            }
          }
        }
      }
    });
    
    // VALIDATION: Check required execution prompts (text/number/date/select)
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

    // VALIDATION: Check required evidence (source of truth: modal.evidenceByStepId, not only dataset)
    const evidenceSections = modal.querySelectorAll('.execute-prompt-section[data-prompt-type="evidence"][data-prompt-required="true"]');
    evidenceSections.forEach(section => {
      const uploadZone = section.querySelector('.execute-evidence-upload');
      const label = section.dataset.promptLabel || 'Evidence';
      const stepId = uploadZone && uploadZone.dataset.stepId;
      const list = (modal.evidenceByStepId && stepId && modal.evidenceByStepId.get(stepId)) || [];
      const count = list.length;
      if (count < 1) {
        validationErrors.push(`Please upload at least one file for "${label}"`);
        if (uploadZone) uploadZone.style.borderColor = 'var(--error, #ef4444)';
      } else if (uploadZone) {
        uploadZone.style.borderColor = '';
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
        const triggerEl = select.closest('.execute-input-section') && select.closest('.execute-input-section').querySelector('.execute-inventory-picker-trigger');
        if (triggerEl) triggerEl.style.border = '2px solid var(--error, #ef4444)';
      }
    }
    
    if (missingSelections.length > 0) {
      const missingList = missingSelections.map(name => `"${name}"`).join(', ');
      showNotification('error', 'Validation Error', `Please select inventory for all required inputs: ${missingList}.`);
      const firstMissing = modal.querySelector('.execute-inventory-select[data-required="true"]');
      if (firstMissing && (!firstMissing.value || firstMissing.value === '')) {
        const trigger = firstMissing.closest('.execute-input-section') && firstMissing.closest('.execute-input-section').querySelector('.execute-inventory-picker-trigger');
        if (trigger) {
          trigger.scrollIntoView({ behavior: 'smooth', block: 'center' });
          trigger.focus();
        }
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
          const unit = select.dataset.unit || '';
          
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
    var notesEl = document.getElementById('untracked-output-notes');
    if (notesEl) notesEl.value = '';
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
      var notesEl = form.querySelector('[name="notes"]');
      var notes = notesEl ? String(notesEl.value || '').trim() : '';
      var dateEl = document.getElementById('untracked-output-date');
      var recordedDate = dateEl ? dateEl.value : null;
      if (!name || !unit || isNaN(quantity) || quantity < 0) {
        if (typeof showNotification === 'function') showNotification('error', 'Validation error', 'Please provide a valid name, unit, and non-negative quantity.');
        return;
      }
      if (!notes) {
        if (typeof showNotification === 'function') showNotification('error', 'Notes required', 'Please provide notes explaining why this item is being added as untracked.');
        return;
      }
      var uuidRe = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
      var metadata = recordedDate ? { recorded_date: recordedDate } : {};
      metadata.notes = notes;
      var payload = {
        name: name,
        quantity: quantity,
        unit: unit,
        inventory_type: inventoryType,
        source_execution_id: ctx.executionId || undefined,
        source_execution_step_id: ctx.executionStepId || undefined,
        untracked: true,
        metadata: metadata
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
      var hiddenInput = selects[i];
      var inputName = hiddenInput.dataset.inputName;
      if (!inputName) continue;
      var section = hiddenInput.closest('.execute-input-section');
      var cardsContainer = section ? section.querySelector('.execute-inventory-picker-cards') : null;
      var triggerLabel = section ? section.querySelector('.execute-inventory-picker-label') : null;
      var currentValue = (hiddenInput.value || '').trim();
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
      if (cardsContainer) {
        cardsContainer.innerHTML = '';
        var noneCard = document.createElement('div');
        noneCard.className = 'execute-inventory-input-card execute-reconcile-untracked-card';
        noneCard.dataset.inventoryId = '';
        noneCard.style.cssText = 'padding: 10px 14px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer;';
        noneCard.innerHTML = '<span style="color: var(--text-secondary); font-size: 13px;">— None —</span>';
        noneCard.onclick = function() {
          hiddenInput.value = '';
          hiddenInput.dataset.quantity = '';
          hiddenInput.dataset.unit = '';
          if (triggerLabel) triggerLabel.textContent = 'Select inventory item...';
          var q = section.querySelector('.execute-quantity-input');
          var u = section.querySelector('.execute-quantity-unit-display');
          if (q && u) {
            u.textContent = q.dataset.stepUnit || '';
            q.value = q.dataset.originalQuantity || '';
            q.dataset.inventoryUnit = '';
          }
          cardsContainer.querySelectorAll('.execute-inventory-input-card').forEach(function(c) {
            c.classList.remove('execute-reconcile-card-selected');
            c.style.borderColor = '';
            c.style.boxShadow = '';
          });
          noneCard.classList.add('execute-reconcile-card-selected');
          var drop = section.querySelector('.execute-inventory-picker-dropdown');
          if (drop) drop.style.display = 'none';
          var arrow = section.querySelector('.execute-inventory-picker-arrow');
          if (arrow) arrow.style.transform = 'rotate(0deg)';
        };
        cardsContainer.appendChild(noneCard);
        var safeInputName = (inputName || '').replace(/[^a-zA-Z0-9_-]/g, '_');
        matching.forEach(function(inv) {
          var id = String(inv.id);
          var card = document.createElement('div');
          card.className = 'execute-inventory-input-card card card-interactive execute-reconcile-untracked-card';
          card.dataset.inventoryId = id;
          card.style.cssText = 'margin-bottom: 0; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer; overflow: hidden;';
          var createdStr = inv.created_at ? (function() { try { return new Date(inv.created_at).toLocaleDateString(); } catch (e) { return ''; } })() : '';
          var subtitleParts = [(inv.quantity != null ? inv.quantity : '') + ' ' + (inv.unit || ''), inv.process_name].filter(Boolean);
          var subtitleLine = subtitleParts.map(function(x) { return escapeHtml(x); }).join(' · ');
          var detailsParts = [];
          if (inv.quantity != null) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Quantity</span> ' + escapeHtml(String(inv.quantity)) + ' ' + escapeHtml(inv.unit || '') + '</p>');
          if (inv.process_name) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Process</span> ' + escapeHtml(inv.process_name) + '</p>');
          if (createdStr) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Created</span> ' + escapeHtml(createdStr) + '</p>');
          if (inv.supplier) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Supplier</span> ' + escapeHtml(inv.supplier) + '</p>');
          if (inv.supplier_batch_number) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Batch</span> ' + escapeHtml(inv.supplier_batch_number) + '</p>');
          card.innerHTML = '<div class="process-card-header" style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px;"><div style="flex: 1; min-width: 0;"><h4 style="margin: 0; font-size: 14px; font-weight: 600;">' + escapeHtml(inv.name || '') + '</h4><p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-secondary);">' + subtitleLine + '</p></div></div><div class="execute-reconcile-details" style="padding: 12px 16px; border-top: 1px solid var(--border-default); background: var(--bg-secondary, #f9fafb); font-size: 13px;">' + detailsParts.join('') + '</div>';
          card.onclick = function() {
            hiddenInput.value = id;
            hiddenInput.dataset.quantity = inv.quantity != null ? String(inv.quantity) : '';
            hiddenInput.dataset.unit = inv.unit || '';
            if (triggerLabel) triggerLabel.textContent = (inv.process_name ? escapeHtml(inv.process_name) + ' - ' : '') + escapeHtml(inv.name) + ' - ' + (inv.quantity != null ? inv.quantity : '') + ' ' + (inv.unit || '');
            var q = section.querySelector('.execute-quantity-input');
            var u = section.querySelector('.execute-quantity-unit-display');
            if (q && u) {
              q.value = inv.quantity != null ? inv.quantity : q.value;
              q.dataset.inventoryUnit = inv.unit || '';
              u.textContent = inv.unit || '';
            }
            cardsContainer.querySelectorAll('.execute-inventory-input-card').forEach(function(c) {
              var sel = (c.dataset.inventoryId || '') === id;
              c.classList.toggle('execute-reconcile-card-selected', sel);
              c.style.borderColor = sel ? 'var(--primary, #2563eb)' : '';
              c.style.boxShadow = sel ? '0 0 0 2px rgba(37, 99, 235, 0.25)' : '';
            });
            var drop = section.querySelector('.execute-inventory-picker-dropdown');
            if (drop) drop.style.display = 'none';
            var arrow = section.querySelector('.execute-inventory-picker-arrow');
            if (arrow) arrow.style.transform = 'rotate(0deg)';
          };
          cardsContainer.appendChild(card);
        });
        var selectedId = (newItem && ctx.inputName && inputName === ctx.inputName && newItem.id != null) ? String(newItem.id) : (matching.some(function(inv) { return String(inv.id) === currentValue; }) ? currentValue : '');
        if (!selectedId && noneCard) noneCard.classList.add('execute-reconcile-card-selected');
      }
      var selectedId = (newItem && ctx.inputName && inputName === ctx.inputName && newItem.id != null) ? String(newItem.id) : (matching.some(function(inv) { return String(inv.id) === currentValue; }) ? currentValue : '');
      if (selectedId && matching.some(function(inv) { return String(inv.id) === selectedId; })) {
        var inv = matching.find(function(inv) { return String(inv.id) === selectedId; });
        hiddenInput.value = selectedId;
        hiddenInput.dataset.quantity = inv.quantity != null ? String(inv.quantity) : '';
        hiddenInput.dataset.unit = inv.unit || '';
        if (triggerLabel) triggerLabel.textContent = (inv.process_name ? escapeHtml(inv.process_name) + ' - ' : '') + escapeHtml(inv.name) + ' - ' + (inv.quantity != null ? inv.quantity : '') + ' ' + (inv.unit || '');
        var qtyInput = section ? section.querySelector('.execute-quantity-input') : null;
        var unitDisplay = section ? section.querySelector('.execute-quantity-unit-display') : null;
        if (qtyInput && unitDisplay) {
          qtyInput.value = inv.quantity != null ? inv.quantity : qtyInput.value;
          qtyInput.dataset.inventoryUnit = inv.unit || '';
          unitDisplay.textContent = inv.unit || '';
        }
        var noInvWarning = section ? section.querySelector('.execute-input-no-inventory-warning') : null;
        if (noInvWarning) noInvWarning.style.display = 'none';
        var triggerEl = section ? section.querySelector('.execute-inventory-picker-trigger') : null;
        if (triggerEl) { triggerEl.style.border = ''; triggerEl.style.boxShadow = ''; }
        if (cardsContainer) {
          cardsContainer.querySelectorAll('.execute-inventory-input-card').forEach(function(c) {
            var sel = (c.dataset.inventoryId || '') === selectedId;
            c.classList.toggle('execute-reconcile-card-selected', sel);
            c.style.borderColor = sel ? 'var(--primary, #2563eb)' : '';
            c.style.boxShadow = sel ? '0 0 0 2px rgba(37, 99, 235, 0.25)' : '';
          });
        }
        var drop = section ? section.querySelector('.execute-inventory-picker-dropdown') : null;
        if (drop) drop.style.display = 'none';
        var arr = section ? section.querySelector('.execute-inventory-picker-arrow') : null;
        if (arr) arr.style.transform = 'rotate(0deg)';
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
    window.addInventoryContext = null;
  };

})();
