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
  function ensureExecutionPickerStyles() {
    if (document.getElementById('execution-modal-picker-styles')) return;
    var style = document.createElement('style');
    style.id = 'execution-modal-picker-styles';
    style.textContent = `
      .exec-picker-panel { margin-top: 10px; padding: 12px; border-top: 1px solid var(--border-default, #e5e7eb); }
      .exec-picker-search { margin: 0 0 10px 0; }
      .exec-picker-cards { display: flex; flex-direction: column; gap: 10px; }
      .exec-picker-card { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; padding: 12px 14px; border-radius: var(--radius-md, 10px); border: 1px solid var(--border-default, #e5e7eb); background: var(--bg-card, #fff); color: var(--text-primary, #111827); cursor: pointer; }
      .exec-picker-card:hover { border-color: rgba(59,130,246,0.6); }
      .exec-picker-card[aria-pressed="true"] { border-color: rgba(217, 56, 75, 0.55); box-shadow: 0 0 0 2px rgba(217, 56, 75, 0.10); }
      .exec-picker-card__title { font-size: 14px; font-weight: 700; margin: 0; }
      .exec-picker-card__sub { font-size: 12px; color: var(--text-tertiary, #9ca3af); margin: 0; line-height: 1.4; }
      .exec-picker-card__meta { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px; }
      .exec-picker-card__actions { margin-top: 10px; display: flex; justify-content: flex-end; }
      /* Confirm button uses existing .btn styles (btn-sm), no custom red border. */
      .exec-picker-chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border-default, #e5e7eb); background: var(--bg-secondary, #f3f4f6); font-size: 12px; color: var(--text-secondary, #6b7280); }
      .exec-picker-chip--warn { background: hsl(42, 93%, 96%); border-color: var(--warning, #f59e0b); color: #92400e; }
      .exec-picker-chip--danger { background: hsl(0, 93%, 94%); border-color: var(--error, #ef4444); color: #b91c1c; }
    `;
    document.head.appendChild(style);
  }
  
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
  window.openExecutionModal = async function(executionId, executionStep, stepDefinition, options) {
    ensureExecutionPickerStyles();
    const modal = document.getElementById('execute-step-modal');
    if (!modal) {
      console.error('Execution modal not found');
      return;
    }
    options = options || {};
    var renderMode = (options && options.renderMode) ? String(options.renderMode) : 'modal';
    if (window.ExecutionUI && typeof window.ExecutionUI.setRenderMode === 'function') {
      window.ExecutionUI.setRenderMode(modal, renderMode);
    } else {
      modal.dataset.renderMode = renderMode;
    }
    function showModal() {
      if (window.ExecutionUI && typeof window.ExecutionUI.isPageMode === 'function') {
        if (window.ExecutionUI.isPageMode(modal)) return;
      } else if (renderMode === 'page') {
        return;
      }
      modal.style.display = 'flex';
      document.body.style.overflow = 'hidden';
    }
    function hideModal() {
      if (window.ExecutionUI && typeof window.ExecutionUI.isPageMode === 'function') {
        if (window.ExecutionUI.isPageMode(modal)) return;
      } else if (renderMode === 'page') {
        return;
      }
      modal.style.display = 'none';
      document.body.style.overflow = 'auto';
    }
    function clearModalSections() {
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
      return { inputsContainer, promptsContainer, outputsContainer, docsContainer, docsSection };
    }
    var isDraft = executionId == null || executionStep == null;
    if (isDraft && options.processId) {
      modal.dataset.draftProcessId = options.processId;
      modal.dataset.executionId = '';
      modal.dataset.executionStepId = '';
      executionStep = executionStep || (stepDefinition && { id: null, step_id: stepDefinition.id, step_number: 1 });
    } else {
      modal.dataset.draftProcessId = '';
    }
    // Store current execution context
    modal.dataset.executionId = executionId || '';
    modal.dataset.executionStepId = (executionStep && executionStep.id) ? executionStep.id : '';
    // Ensure Cancel/close removes document click listener for inventory dropdown (avoids listener leak)
    var cancelBtn = modal.querySelector('button[onclick*="execute-step-modal"]');
    if (cancelBtn && !cancelBtn._closeDropdownBound) {
      cancelBtn._closeDropdownBound = true;
      cancelBtn.addEventListener('click', function() {
        if (modal._closeInventoryDropdown) {
          try { modal._closeInventoryDropdown(); } finally { modal._closeInventoryDropdown = null; }
        }
      }, true);
    }
    // Set step name
    const stepNameEl = modal.querySelector('#execute-step-name');
    if (stepNameEl) {
      stepNameEl.textContent = stepDefinition.name || 'Unknown Step';
    }
    
    // Clear previous content
    const { inputsContainer, promptsContainer, outputsContainer, docsContainer, docsSection } = clearModalSections();
    // Reset per-open variable input state to avoid phantom submissions across modal sessions
    modal._inputStateByKey = new Map();
    
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
    modal._inventoryForSubmit = allInventory;
    const expiredRaw = (expiredData && expiredData.expired_raw_materials) ? expiredData.expired_raw_materials : [];
    const impactedItems = (expiredData && expiredData.impacted_items) ? expiredData.impacted_items : [];
    const untrackedItems = (untrackedData && untrackedData.untracked_items) ? untrackedData.untracked_items : [];
    const expiredIds = new Set(expiredRaw.map(function(m) { return String(m.id); }));
    const impactedIds = new Set(impactedItems.map(function(i) { return String(i.id); }));
    const untrackedIds = new Set(untrackedItems.map(function(i) { return String(i.id); }));
    const readyDateReasons = {};
    allInventory.forEach(function(inv) {
      var finding = (inv.system_findings || []).find(function(f) { return f && f.check_id === 'output_ready_date'; });
      if (finding) readyDateReasons[String(inv.id)] = finding.reason || 'Not ready';
    });
    function getExpiredReason(id) {
      if (readyDateReasons[String(id)]) return readyDateReasons[String(id)];
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
      variableInputs.forEach((input, inputIdx) => {
        const inputSection = document.createElement('div');
        inputSection.className = 'execute-input-section';
        // Page-style sections (no card chrome). CSS can further refine.
        inputSection.style.cssText = 'margin: 0; padding: 18px 0;' + (inputIdx === 0 ? '' : ' border-top: 1px solid var(--border-default, #e5e7eb);');
        
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
        const inventoryById = new Map();
        allInventory.forEach(function(inv) { inventoryById.set(String(inv.id), inv); });

        inputSection.innerHTML = `
          <div class="execute-input-section-header" style="margin-bottom: 12px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
              ${escapeHtml(input.name)} 
              <span style="color: var(--text-secondary); font-weight: normal;">(Expected: ${input.quantity || '0'} ${input.unit || ''})</span>
            </label>
          </div>
          <div class="execute-input-rows-container" data-input-name="${escapeHtml(input.name)}" data-safe-name="${safeInputName}"></div>
          <div class="exec-picker-panel" data-exec-picker-panel="true" style="display:block; margin-top: 10px;">
            <div class="flow-mode-segmented" role="group" aria-label="Inventory category" style="margin-bottom: 10px;">
              <button type="button" class="flow-mode-segment flow-mode-segment--active" data-exec-type="raw_material" aria-pressed="true">Raw materials</button>
              <button type="button" class="flow-mode-segment" data-exec-type="work_in_progress" aria-pressed="false">Intermediate</button>
              <button type="button" class="flow-mode-segment" data-exec-type="final_product" aria-pressed="false">Final products</button>
              <button type="button" class="flow-mode-segment" data-exec-type="all" aria-pressed="false">All</button>
            </div>
            <div class="exec-picker-search">
              <input type="search" class="spa-inp" data-exec-picker-search="true" placeholder="Search inventory…" autocomplete="off">
            </div>
            <div class="exec-picker-cards" data-exec-picker-cards="true" style="max-height: 360px; overflow-y: auto;"></div>
          </div>
          <div class="execute-add-input-pane" style="margin-top: 12px; margin-bottom: 0; padding: 16px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-lg); border: 1px solid var(--border-light, #e5e7eb);">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 6px;">Add another input</label>
            <p style="font-size: 12px; color: var(--text-secondary); margin: 0 0 10px 0; line-height: 1.45;">Add one or more inputs to meet step quantity (e.g. multiple batches) or to record an additional material when inputs are not always set per execution.</p>
            <button type="button" class="btn btn-secondary btn-sm execute-add-another-input-btn" data-input-name="${escapeHtml(input.name)}" data-safe-name="${safeInputName}" style="font-size: 13px;">+ Add another input</button>
          </div>
          <div class="execute-input-qty-expected-warning" style="display: none; margin-top: 12px; padding: 10px 12px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); color: #92400e; font-size: 13px; font-weight: 500;" role="status"></div>
          <div class="execute-input-unexpected-material-warning" style="display: none; margin-top: 8px; padding: 10px 12px; background: hsl(210, 90%, 96%); border: 1px solid var(--info, #3b82f6); border-radius: var(--radius-md); color: #1e40af; font-size: 13px; font-weight: 500;" role="status"></div>
          ${errorMessage}
          ${hasNoInventory ? `<p style="margin-top: 8px;"><button type="button" class="btn btn-secondary btn-sm add-missing-item-btn" data-input-name="${escapeHtml(input.name)}" data-input-quantity="${escapeHtml(String(input.quantity != null ? input.quantity : ''))}" data-input-unit="${escapeHtml(input.unit || '')}" data-source-output-id="${input.source_output_id ? escapeHtml(String(input.source_output_id)) : ''}" data-source-step-id="${input.source_step_id ? escapeHtml(String(input.source_step_id)) : ''}" data-source-process-id="${input.source_process_id ? escapeHtml(String(input.source_process_id)) : ''}" style="font-size: 13px;">Add Missing Item</button></p>` : ''}
        `;

        const rowsContainer = inputSection.querySelector('.execute-input-rows-container');
        const pickerPanel = inputSection.querySelector('[data-exec-picker-panel="true"]');
        const pickerCards = inputSection.querySelector('[data-exec-picker-cards="true"]');
        const pickerSearch = inputSection.querySelector('[data-exec-picker-search="true"]');

        // Ensure rows stack cleanly when adding additional inputs.
        if (rowsContainer) {
          rowsContainer.style.display = 'flex';
          rowsContainer.style.flexDirection = 'column';
          rowsContainer.style.gap = '12px';
        }
        const pickerTabs = Array.prototype.slice.call(inputSection.querySelectorAll('.flow-mode-segment'));
        let rowIndex = 0;
        if (!modal._inputStateByKey) modal._inputStateByKey = new Map();

        function getInvType(inv) {
          return inv && (inv.inventory_type || inv.type || inv.category || inv.item_type || '');
        }
        function invMatchesType(inv, selected) {
          if (!selected || selected === 'all') return true;
          var t = String(getInvType(inv) || '').toLowerCase();
          return t === selected;
        }
        function invMatchesSearch(inv, q) {
          q = (q || '').trim().toLowerCase();
          if (!q) return true;
          var hay = [
            inv && inv.name,
            inv && inv.unit,
            inv && inv.supplier,
            inv && inv.supplier_batch_number,
            inv && inv.process_name,
          ].filter(Boolean).join(' ').toLowerCase();
          return hay.indexOf(q) !== -1;
        }
        function fmtQty(inv) {
          if (!inv) return '';
          var q = (inv.quantity != null) ? String(inv.quantity) : '';
          var u = inv.unit || '';
          return (q && u) ? (q + ' ' + u) : (q || u || '');
        }
        function renderPickerCards(activeType, q) {
          if (!pickerCards) return;
          var activeRow = modal._editingInputRow;
          var selectedId = '';
          try {
            var sel = activeRow ? activeRow.querySelector('.execute-inventory-select') : null;
            selectedId = sel && sel.value ? String(sel.value) : '';
          } catch (e) {}
          var pendingId = '';
          try {
            var pSel = activeRow ? activeRow.getAttribute('data-pending-inv-id') : '';
            pendingId = pSel ? String(pSel) : '';
          } catch (e) {}
          // Hide items that are already selected in any input row (operator workflow).
          var selectedIds = new Set();
          try {
            inputSection.querySelectorAll('.execute-input-row').forEach(function(r) {
              var s = r.querySelector('.execute-inventory-select');
              if (s && s.value) selectedIds.add(String(s.value));
            });
          } catch (e) {}

          var list = sortedInventory
            .filter(function(inv) { return invMatchesType(inv, activeType); })
            .filter(function(inv) { return invMatchesSearch(inv, q); });
          list = list.filter(function(inv) {
            var id = String(inv.id);
            if (pendingId && id === pendingId) return true;
            return !selectedIds.has(id);
          });

          // Keep list stable during preview (no reordering).
          if (!list.length) {
            pickerCards.innerHTML = '<p style="margin: 0; font-size: 13px; color: var(--text-secondary); padding: 6px 2px;">No inventory matches.</p>';
            return;
          }
          pickerCards.innerHTML = list.map(function(inv) {
            var rawId = String(inv.id);
            var id = escapeHtml(rawId);
            var name = escapeHtml(inv.name || 'Unnamed');
            var sub = escapeHtml(fmtQty(inv));
            var chips = '';
            if (inv.supplier) chips += '<span class="exec-picker-chip">' + escapeHtml(inv.supplier) + '</span>';
            if (inv.supplier_batch_number) chips += '<span class="exec-picker-chip">Batch ' + escapeHtml(inv.supplier_batch_number) + '</span>';
            var reason = getExpiredReason(inv.id);
            if (reason) {
              var cls = reason.toLowerCase().indexOf('untracked') !== -1 ? 'exec-picker-chip--danger'
                : (reason.toLowerCase().indexOf('expired') !== -1 ? 'exec-picker-chip--danger' : 'exec-picker-chip--warn');
              chips += '<span class="exec-picker-chip ' + cls + '">' + escapeHtml(reason) + '</span>';
            }
            var isPending = pendingId && pendingId === rawId;
            var actions = '';
            if (isPending) {
              actions =
                '<div class="exec-picker-card__actions" style="justify-content:flex-start;">' +
                  '<button type="button" class="btn btn-secondary btn-sm exec-picker-confirm-btn" data-action="confirm-input" data-inv-id="' + id + '">Confirm input</button>' +
                '</div>';
            }
            return (
              '<div class="exec-picker-card" role="button" tabindex="0" data-inv-id="' + id + '" aria-pressed="' + (isPending ? 'true' : 'false') + '">' +
                '<p class="exec-picker-card__title">' + name + '</p>' +
                '<p class="exec-picker-card__sub">' + sub + '</p>' +
                (chips ? '<div class="exec-picker-card__meta">' + chips + '</div>' : '') +
                actions +
              '</div>'
            );
          }).join('');
        }

        var pickerState = { activeType: 'raw_material', q: '' };
        function syncTabState(next) {
          pickerState.activeType = next;
          pickerTabs.forEach(function(t) {
            var isOn = t.getAttribute('data-exec-type') === next;
            t.setAttribute('aria-pressed', isOn ? 'true' : 'false');
            t.classList.toggle('flow-mode-segment--active', isOn);
          });
          renderPickerCards(pickerState.activeType, pickerState.q);
        }
        pickerTabs.forEach(function(btn) {
          btn.addEventListener('click', function() {
            syncTabState(btn.getAttribute('data-exec-type') || 'all');
          });
        });
        if (pickerSearch) {
          pickerSearch.addEventListener('input', function() {
            pickerState.q = pickerSearch.value || '';
            renderPickerCards(pickerState.activeType, pickerState.q);
          });
        }
        if (pickerPanel) {
          // initial render
          renderPickerCards(pickerState.activeType, pickerState.q);
        }

        // Card clicks: preview for active row; confirm happens on the picker card.
        if (pickerCards && !pickerCards._boundPickerClick) {
          pickerCards._boundPickerClick = true;
          pickerCards.addEventListener('click', function(ev) {
            var confirmBtn = ev.target && ev.target.closest ? ev.target.closest('[data-action="confirm-input"]') : null;
            if (confirmBtn) {
              ev.preventDefault();
              ev.stopPropagation();
              var invId = confirmBtn.getAttribute('data-inv-id') || '';
              var targetRow = modal._editingInputRow || (rowsContainer && rowsContainer.firstElementChild);
              if (!targetRow) return;
              var locked = targetRow.getAttribute('data-selection-locked') === 'true';
              var selNow = targetRow.querySelector('.execute-inventory-select');
              if (locked && selNow && selNow.value) return;
              setRowSelection(targetRow, invId);
              targetRow.setAttribute('data-pending-inv-id', '');
              targetRow.setAttribute('data-selection-locked', 'true');
              // Once confirmed, hide picker for this row to reduce noise.
              try { if (pickerPanel) pickerPanel.style.display = 'none'; } catch (e) {}
              renderPickerCards(pickerState.activeType, pickerState.q);
              return;
            }
            var btn = ev.target && ev.target.closest ? ev.target.closest('.exec-picker-card') : null;
            if (!btn) return;
            ev.preventDefault();
            var invId = btn.getAttribute('data-inv-id') || '';
            var targetRow = modal._editingInputRow || (rowsContainer && rowsContainer.firstElementChild);
            if (!targetRow) return;
            // If already confirmed for this row, don't allow changing unless they add another input row.
            var locked = targetRow.getAttribute('data-selection-locked') === 'true';
            var selNow = targetRow.querySelector('.execute-inventory-select');
            if (locked && selNow && selNow.value) return;
            // Preview selection first; require explicit confirmation.
            targetRow.setAttribute('data-pending-inv-id', invId);
            renderPickerCards(pickerState.activeType, pickerState.q);
          });
        }

        function createInputRow(isFirst) {
          const rowId = 'execute-input-row-' + safeInputName + '-' + rowIndex++;
          const stateKey = safeInputName + '::' + rowId;
          const row = document.createElement('div');
          row.className = 'execute-input-row';
          row.id = rowId;
          row.dataset.inputName = input.name;
          row.dataset.stateKey = stateKey;
          // Ensure rows naturally stack in the document flow.
          row.style.display = 'block';
          row.style.width = '100%';
          row.style.position = 'relative';
          if (!modal._inputStateByKey.has(stateKey)) {
            modal._inputStateByKey.set(stateKey, {
              input_name: input.name,
              inventory_item_id: '',
              quantity: input.quantity != null ? Number(input.quantity) : 0,
              unit: input.unit || '',
              expired_reason: '',
            });
          }
          row.innerHTML = `
            <input type="hidden" class="execute-inventory-select" data-input-name="${escapeHtml(input.name)}" data-quantity="" data-unit="" data-expired-reason="" value="">

            <div style="display:flex; justify-content:flex-end; margin-bottom: 10px;">
              <button type="button" class="execute-remove-input-row-btn btn btn-secondary btn-sm" style="font-size: 12px;">Remove input</button>
            </div>

            <div class="execute-selected-inv-card" style="display:none; padding: 12px 14px; border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md, 10px); background: var(--bg-card, #fff);"></div>

            <div class="execute-input-expired-warning" data-input-name="${escapeHtml(input.name)}" style="display: none; margin-top: 8px; padding: 10px 12px; background: hsl(0, 93%, 94%); border: 1px solid var(--error, #ef4444); border-radius: var(--radius-md); color: #b91c1c; font-size: 13px; font-weight: 500;" role="alert"></div>
            <div class="execute-input-unexpected-row-warning" data-input-name="${escapeHtml(input.name)}" style="display: none; margin-top: 8px; padding: 10px 12px; background: hsl(210, 90%, 96%); border: 1px solid var(--info, #3b82f6); border-radius: var(--radius-md); color: #1e40af; font-size: 13px; font-weight: 500;" role="status"></div>

            <div class="execute-qty-pane" style="display:none; margin-top: 12px;">
              <label class="spa-field-label">Quantity to consume</label>
              <div style="display: flex; align-items: center; gap: 8px;">
                <input type="number" class="spa-inp execute-quantity-input" data-input-name="${escapeHtml(input.name)}" data-step-unit="${escapeHtml(input.unit || '')}" data-original-quantity="${input.quantity || ''}" placeholder="${input.quantity || '0'}" value="${input.quantity || ''}" step="0.01" min="0" style="flex: 1;">
                <span class="execute-quantity-unit-display" style="font-size: 14px; color: var(--text-secondary); min-width: 40px; text-align: left;">${input.unit || ''}</span>
              </div>
            </div>
          `;
          var qtyInput = row.querySelector('.execute-quantity-input');
          if (qtyInput) {
            // Ensure we start from a neutral border (avoid stale inline styles / bfcache).
            qtyInput.style.border = '1px solid var(--border-default, #e5e7eb)';
            qtyInput.addEventListener('input', function() {
              var st = modal._inputStateByKey.get(stateKey);
              if (!st) return;
              var q = parseFloat(qtyInput.value);
              st.quantity = isNaN(q) ? 0 : q;
            });
          }

          // Remove input: if it's the only row, clear selection + unlock; otherwise remove the row.
          var removeBtn = row.querySelector('.execute-remove-input-row-btn');
          if (removeBtn) {
            removeBtn.addEventListener('click', function(e) {
              if (e) { e.preventDefault(); e.stopPropagation(); }
              row.setAttribute('data-pending-inv-id', '');
              row.setAttribute('data-selection-locked', 'false');
              if (!rowsContainer) return;
              var rowCount = rowsContainer.querySelectorAll('.execute-input-row').length;
              if (rowCount <= 1) {
                setRowSelection(row, '');
                setActiveRow(row);
              } else {
                var stateKey = row.dataset.stateKey || '';
                if (stateKey && modal._inputStateByKey) modal._inputStateByKey.delete(stateKey);
                row.remove();
                // Ensure active row points to a remaining row.
                var next = rowsContainer.querySelector('.execute-input-row');
                if (next) setActiveRow(next);
              }
              renderPickerCards(pickerState.activeType, pickerState.q);
            });
          }
          return row;
        }

        function nameMatchesExact(invName) {
          var a = (input.name || '').trim().toLowerCase();
          var b = (invName || '').trim().toLowerCase();
          return a.length > 0 && a === b;
        }

        function itemIsOutput(inv) {
          return inv && (inv.source_output_id != null && inv.source_output_id !== '');
        }

        function inputExpectsOutput() {
          return (input.source_output_id != null && input.source_output_id !== '');
        }

        function isUnexpectedType(inv) {
          if (!inv) return false;
          var expectsOutput = inputExpectsOutput();
          var invIsOutput = itemIsOutput(inv);
          if (expectsOutput) return !invIsOutput || String(inv.source_output_id) !== String(input.source_output_id);
          return invIsOutput;
        }

        function isUnexpectedItem(inv) {
          if (!inv) return false;
          if (isUnexpectedType(inv)) return true;
          return !nameMatchesExact(inv.name);
        }

        function isExpectedItem(invId) {
          if (!invId) return false;
          var inv = invId ? inventoryById.get(String(invId)) : null;
          if (!inv) return false;
          if (inputExpectsOutput()) {
            return itemIsOutput(inv) && String(inv.source_output_id) === String(input.source_output_id) && nameMatchesExact(inv.name);
          }
          return !itemIsOutput(inv) && nameMatchesExact(inv.name);
        }

        function updateRowUnexpectedWarning(rowEl) {
          var el = rowEl ? rowEl.querySelector('.execute-input-unexpected-row-warning') : null;
          var sel = rowEl ? rowEl.querySelector('.execute-inventory-select') : null;
          var invId = sel && sel.value ? sel.value : null;
          var inv = invId ? inventoryById.get(String(invId)) : null;
          var unexpected = inv && isUnexpectedItem(inv);
          if (!el) return;
          if (!sel || !invId) {
            el.style.display = 'none';
            el.textContent = '';
            return;
          }
          if (!inv || !unexpected) {
            el.style.display = 'none';
            el.textContent = '';
            return;
          }
          el.textContent = 'Warning - this selection is not the expected input for this step';
          el.style.display = 'block';
        }

        function updateSectionQtyExpectedWarning() {
          var qtyWarningEl = inputSection.querySelector('.execute-input-qty-expected-warning');
          if (!qtyWarningEl) return;
          var expectedNum = parseFloat(input.quantity);
          if (isNaN(expectedNum) || expectedNum <= 0) {
            qtyWarningEl.style.display = 'none';
            qtyWarningEl.textContent = '';
            return;
          }
          var totalExpectedQty = 0;
          inputSection.querySelectorAll('.execute-input-row').forEach(function(row) {
            var sel = row.querySelector('.execute-inventory-select');
            var qtyInput = row.querySelector('.execute-quantity-input');
            // Compare against total selected quantity for this input (regardless of "expected vs unexpected" inventory),
            // since "unexpected selection" is already handled by a separate warning.
            if (sel && sel.value && qtyInput) {
              var v = parseFloat(qtyInput.value);
              if (!isNaN(v) && v > 0) totalExpectedQty += v;
            }
          });
          var fmt = function(n) { return Number(n.toFixed(3)); };
          var unit = (input.unit || '').trim() || 'units';
          if (totalExpectedQty < expectedNum) {
            var moreNeeded = expectedNum - totalExpectedQty;
            qtyWarningEl.textContent = fmt(moreNeeded) + ' ' + unit + ' more needed to meet expected quantity (' + fmt(expectedNum) + ' ' + unit + ') for this input.';
            qtyWarningEl.style.display = 'block';
          } else if (totalExpectedQty > expectedNum) {
            var over = totalExpectedQty - expectedNum;
            qtyWarningEl.textContent = fmt(over) + ' ' + unit + ' over expected quantity (' + fmt(expectedNum) + ' ' + unit + ') for this input.';
            qtyWarningEl.style.display = 'block';
          } else {
            qtyWarningEl.style.display = 'none';
            qtyWarningEl.textContent = '';
          }
        }

        function updateUnexpectedMaterialWarning() {
          var unexpectedEl = inputSection.querySelector('.execute-input-unexpected-material-warning');
          var hasUnexpected = false;
          inputSection.querySelectorAll('.execute-input-row').forEach(function(row) {
            var sel = row.querySelector('.execute-inventory-select');
            if (sel && sel.value) {
              var inv = sel.value ? inventoryById.get(String(sel.value)) : null;
              if (inv && isUnexpectedItem(inv)) hasUnexpected = true;
            }
            updateRowUnexpectedWarning(row);
          });
          if (unexpectedEl) {
            if (hasUnexpected) {
              unexpectedEl.textContent = 'Warning - one or more selections are not the expected input for this step';
              unexpectedEl.style.display = 'block';
            } else {
              unexpectedEl.style.display = 'none';
              unexpectedEl.textContent = '';
            }
          }
        }

        function setRowSelection(rowEl, invId) {
          if (!rowEl) return;
          const hiddenInput = rowEl.querySelector('.execute-inventory-select');
          const quantityInput = rowEl.querySelector('.execute-quantity-input');
          const unitDisplay = rowEl.querySelector('.execute-quantity-unit-display');
          const expiredWarningEl = rowEl.querySelector('.execute-input-expired-warning');
          const selectedCardEl = rowEl.querySelector('.execute-selected-inv-card');
          const qtyPane = rowEl.querySelector('.execute-qty-pane');
          if (!hiddenInput) return;
          var stateKey = rowEl.dataset.stateKey || '';
          var st = stateKey ? modal._inputStateByKey.get(stateKey) : null;
          hiddenInput.value = invId || '';
          hiddenInput.dataset.quantity = '';
          hiddenInput.dataset.unit = '';
          hiddenInput.dataset.expiredReason = '';

          // Always clear warning when changing selection; only show if the selected item needs it.
          if (expiredWarningEl) { expiredWarningEl.style.display = 'none'; expiredWarningEl.textContent = ''; }

          if (!invId) {
            if (selectedCardEl) { selectedCardEl.style.display = 'none'; selectedCardEl.innerHTML = ''; }
            if (qtyPane) qtyPane.style.display = 'none';
            if (unitDisplay && quantityInput) {
              unitDisplay.textContent = quantityInput.dataset.stepUnit || input.unit || '';
              quantityInput.value = input.quantity || '';
              quantityInput.dataset.originalQuantity = input.quantity || '';
              quantityInput.dataset.inventoryUnit = '';
            }
            if (st) {
              st.inventory_item_id = '';
              st.unit = (quantityInput && (quantityInput.dataset.stepUnit || input.unit)) || (input.unit || '');
              st.expired_reason = '';
              var qv = quantityInput ? parseFloat(quantityInput.value) : NaN;
              st.quantity = isNaN(qv) ? 0 : qv;
            }
            updateSectionQtyExpectedWarning();
            updateUnexpectedMaterialWarning();
            return;
          }
          const inv = invId ? inventoryById.get(String(invId)) : null;
          if (inv && unitDisplay && quantityInput) {
            // Prefill should follow the step definition expected quantity (operator-friendly),
            // not "available inventory quantity".
            var expectedQty = parseFloat(input.quantity);
            if (!isNaN(expectedQty) && expectedQty > 0) {
              quantityInput.value = String(expectedQty);
            } else if (!quantityInput.value) {
              quantityInput.value = input.quantity || '';
            }
            // Keep display unit as the step unit if available; inventory unit remains for validation.
            unitDisplay.textContent = (quantityInput.dataset.stepUnit || input.unit || inv.unit || '');
            quantityInput.dataset.inventoryUnit = inv.unit || '';
          }
          if (inv) {
            hiddenInput.dataset.quantity = inv.quantity != null ? String(inv.quantity) : '';
            hiddenInput.dataset.unit = inv.unit || '';
            const reason = getExpiredReason(inv.id);
            hiddenInput.dataset.expiredReason = reason || '';
            if (st) {
              st.inventory_item_id = String(inv.id);
              st.unit = (quantityInput && (quantityInput.dataset.stepUnit || input.unit)) || (input.unit || inv.unit || '');
              st.expired_reason = reason || '';
              var q = quantityInput ? parseFloat(quantityInput.value) : NaN;
              st.quantity = isNaN(q) ? 0 : q;
            }
            if (reason && expiredWarningEl) {
              expiredWarningEl.textContent = 'Check: ' + reason;
              expiredWarningEl.style.display = 'block';
            }
            if (selectedCardEl) {
              function fmtDate(raw) {
                if (!raw) return '';
                try { return new Date(raw).toLocaleDateString(); } catch (e) { return String(raw); }
              }
              var meta = [];
              if (inv.supplier) meta.push('<div><span style="color:var(--text-tertiary,#9ca3af); font-size:12px;">Supplier</span><div style="font-weight:600;">' + escapeHtml(inv.supplier) + '</div></div>');
              if (inv.supplier_batch_number) meta.push('<div><span style="color:var(--text-tertiary,#9ca3af); font-size:12px;">Batch</span><div style="font-weight:600;">' + escapeHtml(inv.supplier_batch_number) + '</div></div>');
              if (inv.purchase_date) meta.push('<div><span style="color:var(--text-tertiary,#9ca3af); font-size:12px;">Purchase date</span><div style="font-weight:600;">' + escapeHtml(fmtDate(inv.purchase_date)) + '</div></div>');
              if (inv.expiry_date) meta.push('<div><span style="color:var(--text-tertiary,#9ca3af); font-size:12px;">Expiry date</span><div style="font-weight:600;">' + escapeHtml(fmtDate(inv.expiry_date)) + '</div></div>');
              if (inv.created_at) meta.push('<div><span style="color:var(--text-tertiary,#9ca3af); font-size:12px;">Created</span><div style="font-weight:600;">' + escapeHtml(fmtDate(inv.created_at)) + '</div></div>');
              selectedCardEl.innerHTML =
                '<div style="display:flex; align-items:flex-start; justify-content:space-between; gap:12px;">' +
                  '<div style="min-width:0;">' +
                    '<div style="font-size:14px; font-weight:700; color:var(--text-primary,#111827);">' + escapeHtml(inv.name || 'Selected item') + '</div>' +
                    '<div style="font-size:12px; color:var(--text-secondary,#6b7280); margin-top:4px;">' + escapeHtml((inv.process_name ? (inv.process_name + ' · ') : '') + fmtQty(inv)) + '</div>' +
                  '</div>' +
                  (reason ? ('<div class="exec-picker-chip exec-picker-chip--warn" style="flex-shrink:0;">' + escapeHtml(reason) + '</div>') : '') +
                '</div>' +
                (meta.length ? ('<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin-top:12px;">' + meta.join('') + '</div>') : '');
              selectedCardEl.style.display = 'block';
            }
            if (qtyPane) qtyPane.style.display = 'block';
          }
          if (quantityInput) quantityInput.style.border = '1px solid var(--border-default, #e5e7eb)';
          updateSectionQtyExpectedWarning();
          updateUnexpectedMaterialWarning();
        }

        const firstRow = createInputRow(true);
        rowsContainer.appendChild(firstRow);

        const hiddenInput = firstRow.querySelector('.execute-inventory-select');
        const quantityInput = firstRow.querySelector('.execute-quantity-input');
        const unitDisplay = firstRow.querySelector('.execute-quantity-unit-display');
        const triggerLabel = firstRow.querySelector('.execute-inventory-picker-label');
        const expiredWarningEl = firstRow.querySelector('.execute-input-expired-warning');

        function getInventorySelectionLabel(invId) {
          if (!invId) return 'Select inventory item...';
          const inv = inventoryById.get(String(invId));
          if (!inv) return 'Select inventory item...';
          const productName = inv.process_name ? escapeHtml(inv.process_name) + ' - ' + escapeHtml(inv.name) : escapeHtml(inv.name);
          return productName + ' - ' + (inv.quantity != null ? inv.quantity : '') + ' ' + (inv.unit || '');
        }

        // Always-on card picker: clicking a row makes it active; clicking a card assigns selection to the active row.
        function setActiveRow(rowEl) {
          if (!rowEl) return;
          modal._editingInputRow = rowEl;
          inputSection.querySelectorAll('.execute-input-row').forEach(function(r) {
            r.classList.toggle('execute-input-row--active', r === rowEl);
          });

          // If the active row is already confirmed, keep picker hidden to reduce noise.
          try {
            var locked = rowEl.getAttribute('data-selection-locked') === 'true';
            var sel = rowEl.querySelector('.execute-inventory-select');
            var hasSel = Boolean(sel && sel.value);
            if (pickerPanel) pickerPanel.style.display = (locked && hasSel) ? 'none' : 'block';
          } catch (e) {}
        }
        function getSelectedInventoryIdsExcludingRow(excludeRowEl) {
          var ids = new Set();
          inputSection.querySelectorAll('.execute-input-row').forEach(function(row) {
            if (row === excludeRowEl) return;
            var sel = row.querySelector('.execute-inventory-select');
            if (sel && sel.value) ids.add(String(sel.value));
          });
          return ids;
        }
        function createCardForInv(inv) {
          var id = String(inv.id);
          var card = document.createElement('div');
          card.className = 'execute-inventory-input-card card card-interactive execute-reconcile-untracked-card';
          card.dataset.inventoryId = id;
          var searchParts = [inv.name, inv.process_name, inv.unit, inv.supplier, inv.supplier_batch_number].filter(Boolean);
          card.dataset.searchText = (searchParts.join(' ') || '').toLowerCase();
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
            setRowSelection(modal._editingInputRow || firstRow, id);
          };
          return card;
        }

        function appendSectionHeader(container, title) {
          var h = document.createElement('div');
          h.className = 'execute-inventory-dropdown-section-header';
          h.style.cssText = 'font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; margin: 12px 0 6px 0; padding: 0 4px;';
          h.textContent = title;
          container.appendChild(h);
        }

        function filterAddAnotherDropdown() {
          var searchEl = dropdown ? dropdown.querySelector('.execute-addanother-search') : null;
          if (!cardsContainer || !searchEl) return;
          var searchVal = (searchEl.value || '').trim().toLowerCase();
          var selectedElsewhere = modal._editingInputRow ? getSelectedInventoryIdsExcludingRow(modal._editingInputRow) : new Set();
          var children = cardsContainer.children;
          for (var i = 0; i < children.length; i++) {
            var el = children[i];
            if (el.classList.contains('execute-inventory-dropdown-section-header')) continue;
            if (el.classList.contains('execute-inventory-input-card')) {
              var id = el.dataset.inventoryId;
              if (id === '' || id === undefined) {
                el.style.display = '';
                continue;
              }
              if (selectedElsewhere.has(id)) {
                el.style.display = 'none';
                continue;
              }
              var text = (el.dataset.searchText || '');
              el.style.display = !searchVal || (text && text.indexOf(searchVal) !== -1) ? '' : 'none';
            }
          }
          for (var i = 0; i < children.length; i++) {
            var el = children[i];
            if (!el.classList.contains('execute-inventory-dropdown-section-header')) continue;
            var hasVisible = false;
            for (var j = i + 1; j < children.length; j++) {
              var next = children[j];
              if (next.classList.contains('execute-inventory-dropdown-section-header')) break;
              if (next.classList.contains('execute-inventory-input-card') && next.dataset.inventoryId && next.style.display !== 'none') {
                hasVisible = true;
                break;
              }
            }
            el.style.display = hasVisible ? '' : 'none';
          }
        }

        function ensureAddAnotherSearchRow(show) {
          var wrap = dropdown ? dropdown.querySelector('.execute-addanother-search-wrap') : null;
          if (show) {
            if (!wrap) {
              wrap = document.createElement('div');
              wrap.className = 'execute-addanother-search-wrap';
              wrap.style.cssText = 'flex-shrink: 0; padding: 0 0 8px 0; border-bottom: 1px solid var(--border-default, #e5e7eb); margin-bottom: 8px;';
              var inp = document.createElement('input');
              inp.type = 'text';
              inp.className = 'execute-addanother-search';
              inp.placeholder = 'Type to filter…';
              inp.autocomplete = 'off';
              inp.style.cssText = 'width: 100%; box-sizing: border-box; padding: 6px 10px; border: 1px solid var(--border-default); border-radius: var(--radius-md); font-size: 13px; background: var(--bg-card); color: var(--text-primary);';
              inp.addEventListener('input', filterAddAnotherDropdown);
              inp.addEventListener('click', function(e) { e.stopPropagation(); });
              wrap.appendChild(inp);
              dropdown.insertBefore(wrap, cardsContainer);
              dropdown.style.display = 'flex';
              dropdown.style.flexDirection = 'column';
              dropdown.style.height = '320px';
              dropdown.style.overflow = 'hidden';
              dropdown.style.overflowY = '';
              cardsContainer.style.flex = '1';
              cardsContainer.style.minHeight = '0';
              cardsContainer.style.overflowY = 'auto';
            }
            for (var c = 0; c < cardsContainer.children.length; c++) {
              cardsContainer.children[c].style.flexShrink = '0';
            }
            var inp = wrap.querySelector('.execute-addanother-search');
            if (inp) {
              inp.value = '';
              filterAddAnotherDropdown();
              setTimeout(function() { inp.focus(); }, 0);
            }
          } else {
            if (wrap) {
              wrap.remove();
              dropdown.style.display = 'block';
              dropdown.style.height = '';
              dropdown.style.overflowY = 'auto';
              dropdown.style.flex = '';
              dropdown.style.flexDirection = '';
              cardsContainer.style.flex = '';
              cardsContainer.style.minHeight = '';
              cardsContainer.style.overflowY = '';
            }
          }
        }

        function populateDropdownContent(rowEl) {
          if (!cardsContainer) return;
          cardsContainer.innerHTML = '';
          var isFirstRow = rowsContainer && rowsContainer.firstElementChild === rowEl;
          var noneCard = document.createElement('div');
          noneCard.className = 'execute-inventory-input-card execute-reconcile-untracked-card';
          noneCard.dataset.inventoryId = '';
          noneCard.style.cssText = 'padding: 10px 14px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s;';
          noneCard.innerHTML = '<span style="color: var(--text-secondary); font-size: 13px;">— None —</span>';
          noneCard.onclick = function(e) { e.stopPropagation(); setRowSelection(modal._editingInputRow || rowEl, ''); };
          cardsContainer.appendChild(noneCard);
          if (isFirstRow) {
            sortedInventory.forEach(function(inv) {
              cardsContainer.appendChild(createCardForInv(inv));
            });
          } else {
            var matchingName = allInventory.filter(function(inv) { return nameMatchesExact(inv.name); });
            var matchingIds = new Set(matchingName.map(function(i) { return String(i.id); }));
            var others = allInventory.filter(function(inv) { return !matchingIds.has(String(inv.id)); });
            if (matchingName.length > 0) {
              appendSectionHeader(cardsContainer, 'Expected: ' + (input.name || ''));
              matchingName.forEach(function(inv) {
                cardsContainer.appendChild(createCardForInv(inv));
              });
            }
            var raw = others.filter(function(inv) { return (inv.inventory_type || 'raw_material') === 'raw_material'; });
            var wip = others.filter(function(inv) { return inv.inventory_type === 'work_in_progress'; });
            var fin = others.filter(function(inv) { return inv.inventory_type === 'final_product'; });
            if (raw.length > 0) {
              appendSectionHeader(cardsContainer, 'Raw materials');
              raw.forEach(function(inv) { cardsContainer.appendChild(createCardForInv(inv)); });
            }
            if (wip.length > 0) {
              appendSectionHeader(cardsContainer, 'Intermediate');
              wip.forEach(function(inv) { cardsContainer.appendChild(createCardForInv(inv)); });
            }
            if (fin.length > 0) {
              appendSectionHeader(cardsContainer, 'Final products');
              fin.forEach(function(inv) { cardsContainer.appendChild(createCardForInv(inv)); });
            }
          }
        }

        // Picker is always visible; keep tab/search predictable once on init.
        if (pickerSearch) pickerSearch.value = '';
        pickerState.q = '';
        syncTabState('raw_material');

        function toggleInventoryCardDetails(cardId) {
          var details = inputSection.querySelector('#execute-inv-details-' + safeInputName + '-' + cardId);
          var arrow = inputSection.querySelector('#execute-inv-arrow-' + safeInputName + '-' + cardId);
          if (!details || !arrow) return;
          var isExpanded = details.style.display === 'block';
          details.style.display = isExpanded ? 'none' : 'block';
          arrow.style.transform = isExpanded ? 'rotate(0deg)' : 'rotate(90deg)';
        }

        // Row activation
        firstRow.addEventListener('click', function() { setActiveRow(firstRow); });
        setActiveRow(firstRow);

        // Always start with neutral borders (avoid stale validation styles).
        inputSection.querySelectorAll('.execute-quantity-input').forEach(function(inp) {
          if (inp) inp.style.border = '1px solid var(--border-default, #e5e7eb)';
        });

        if (quantityInput) {
          if (!quantityInput.dataset.originalQuantity || quantityInput.dataset.originalQuantity === '' || quantityInput.dataset.originalQuantity === 'undefined') {
            quantityInput.dataset.originalQuantity = input.quantity || quantityInput.value || '0';
          }
          quantityInput.addEventListener('input', function() {
            if (parseFloat(this.value) > 0) this.style.border = '1px solid var(--border-default, #e5e7eb)';
            updateSectionQtyExpectedWarning();
            updateUnexpectedMaterialWarning();
          });
        }

        var addAnotherBtn = inputSection.querySelector('.execute-add-another-input-btn');
        if (addAnotherBtn) {
          addAnotherBtn.addEventListener('click', function() {
            var newRow = createInputRow(false);
            rowsContainer.appendChild(newRow);
            newRow.addEventListener('click', function() { setActiveRow(newRow); });
            // Immediately activate the new row, otherwise selection remains locked to previous row.
            setActiveRow(newRow);
            var qInput = newRow.querySelector('.execute-quantity-input');
            if (qInput) {
              qInput.addEventListener('input', function() {
                if (parseFloat(this.value) > 0) this.style.border = '1px solid var(--border-default, #e5e7eb)';
                updateSectionQtyExpectedWarning();
                updateUnexpectedMaterialWarning();
              });
            }
            // remove handler already attached in createInputRow
            renderPickerCards(pickerState.activeType, pickerState.q);
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
            <input type="number" class="spa-inp execute-confirm-quantity-input" data-input-name="${escapeHtml(input.name)}" data-required="true" required placeholder="${input.quantity || '0'}" value="${input.quantity || ''}" step="0.01" min="0">
          </div>
          <div>
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">Unit <span style="color: var(--error, #ef4444);">*</span></label>
            <select class="spa-inp execute-confirm-unit-input" data-input-name="${escapeHtml(input.name)}" data-required="true" required>
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
          inputHtml = `<input type="text" class="spa-inp execute-prompt-input" data-prompt-label="${escapeHtml(prompt.label)}" ${prompt.required !== false ? 'required' : ''}>`;
        } else if (prompt.type === 'number') {
          inputHtml = `<input type="number" class="spa-inp execute-prompt-input" data-prompt-label="${escapeHtml(prompt.label)}" ${prompt.required !== false ? 'required' : ''} step="0.01">`;
        } else if (prompt.type === 'date') {
          inputHtml = `<input type="date" class="spa-inp execute-prompt-input" data-prompt-label="${escapeHtml(prompt.label)}" ${prompt.required !== false ? 'required' : ''}>`;
        } else if (prompt.type === 'select') {
          inputHtml = `<select class="spa-inp execute-prompt-input" data-prompt-label="${escapeHtml(prompt.label)}" ${prompt.required !== false ? 'required' : ''}><option value="">Select...</option></select>`;
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
        const outputId = (output.id != null && String(output.id).trim() !== '') ? String(output.id) : (output.name ? 'out-' + (output.name || '').replace(/\s+/g, '-') : 'out-unknown');
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
        var rd = (output.extra_data || {}).ready_date;
        var customExpiryHtml = '';
        var expiryInputHtml = '';
        var readyDateHtml = '';
        if (ce && ce.enabled) {
          var mode = (ce.mode || '').trim();
          if (mode !== 'fixed_duration' && mode !== 'set_at_execution') mode = '';
          if (mode === 'fixed_duration') {
            var v = (ce.duration_value != null) ? ce.duration_value : ce.expiry_days;
            var u = (ce.duration_unit || 'days');
            var msg = 'Output must be consumed in ' + String(v != null ? v : 'X') + ' ' + String(u) + '.';
            customExpiryHtml = '<div class="execute-output-expiry-warning" style="margin-bottom: 12px; padding: 10px 14px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; color: #92400e;"><strong>⚠️ Custom expiry rule applies:</strong> ' + escapeHtml(msg) + '</div>';
          } else if (mode === 'set_at_execution') {
            expiryInputHtml = (typeof window.renderExecutionExpiryUI === 'function')
              ? window.renderExecutionExpiryUI(output, escapeHtml)
              : '';
          }
        }
        if (rd && rd.enabled) {
          var rdMode = (rd.mode || '').trim();
          if (rdMode === 'fixed_duration' && rd.duration_value != null && rd.duration_unit) {
            var v = rd.duration_value;
            var u = rd.duration_unit;
            var msg = 'Status: Not ready. This output cannot be consumed for ' + String(v) + ' ' + String(u) + ' after step completion.';
            readyDateHtml = '<div class="execute-output-ready-date-warning" style="margin-bottom: 12px; padding: 10px 14px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; color: #92400e;"><strong>&#x26A0;&#xFE0F; Ready date:</strong> ' + escapeHtml(msg) + '</div>';
          } else if (rdMode === 'set_at_execution') {
            readyDateHtml = (typeof window.renderExecutionReadyDateUI === 'function')
              ? window.renderExecutionReadyDateUI(output, escapeHtml)
              : '';
          } else if (rd.date) {
            var readyDate = new Date(rd.date);
            if (!isNaN(readyDate.getTime()) && readyDate > new Date()) {
              var readyFrom = readyDate.toLocaleDateString(undefined, { dateStyle: 'long' });
              var rdMsg = (rd.prompt && rd.prompt.trim()) ? escapeHtml(rd.prompt.trim()) : ('Ready from: ' + readyFrom + '. Status: Not ready.');
              readyDateHtml = '<div class="execute-output-ready-date-warning" style="margin-bottom: 12px; padding: 10px 14px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; color: #92400e;"><strong>&#x26A0;&#xFE0F; Ready date:</strong> ' + rdMsg + '</div>';
            }
          }
        }
        var expiryReadyValidationErrorHtml = (expiryInputHtml && readyDateHtml) ? ('<div class="execute-output-expiry-ready-validation-error" data-output-id="' + escapeHtml(outputId) + '" style="display: none; margin-top: 8px; padding: 10px 12px; background: hsl(0, 93%, 94%); border: 1px solid var(--error, #ef4444); border-radius: var(--radius-md); color: #b91c1c; font-size: 13px; font-weight: 500;" role="alert" aria-live="polite"></div>') : '';
        outputSection.innerHTML = `
          ${customExpiryHtml}
          ${readyDateHtml}
          ${expiryInputHtml}
          ${expiryReadyValidationErrorHtml}
          <div style="margin-bottom: 12px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
              ${escapeHtml(output.name)}
              <span style="color: var(--text-secondary); font-weight: normal;">(Expected: ${output.quantity || '0'} ${output.unit || ''})</span>
            </label>
            <input type="number" class="spa-inp execute-output-quantity-input" data-output-id="${escapeHtml(outputId)}" placeholder="${output.quantity || '0'}" value="${output.quantity || ''}" step="0.01" min="0">
            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">Actual produced quantity (override if different from expected)</p>
            <div class="execute-reconcile-untracked-wrapper" data-output-id="${escapeHtml(outputId)}" style="display: ${hasMatch ? 'block' : 'none'}; margin-top: 12px; padding: 12px 16px; background: hsl(42, 93%, 96%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; position: relative;">
              <input type="hidden" class="execute-reconcile-untracked-value" data-output-id="${escapeHtml(outputId)}" value="${escapeHtml(defaultId)}">
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

        // Wire expiry input toggle (set_at_execution)
        try {
          var expiryBox = outputSection.querySelector('.execute-output-expiry-input');
          if (expiryBox) {
            var modeSel = outputSection.querySelector('.execute-output-expiry-input-mode');
            var durFields = outputSection.querySelector('.execute-output-expiry-duration-fields');
            var dtFields = outputSection.querySelector('.execute-output-expiry-datetime-fields');
            var warnFields = outputSection.querySelector('.execute-output-expiry-warning-fields');
            if (modeSel && durFields && dtFields) {
              var apply = function() {
                var v = modeSel.value;
                durFields.style.display = v === 'duration' ? 'block' : 'none';
                dtFields.style.display = v === 'datetime' ? 'block' : 'none';
                if (warnFields) warnFields.style.display = (v === 'duration' || v === 'datetime') ? 'block' : 'none';
              };
              modeSel.addEventListener('change', apply);
              apply();
              (function() {
                function runValidation() {
                  var v = modeSel.value;
                  var errEl = expiryBox.querySelector('.execute-output-expiry-validation-error');
                  var warnValEl = expiryBox.querySelector('.execute-output-expiry-warning-value');
                  var warnUnitEl = expiryBox.querySelector('.execute-output-expiry-warning-unit');
                  if (!errEl || !warnValEl || !warnUnitEl) return;
                  errEl.style.display = 'none';
                  errEl.textContent = '';
                  warnValEl.style.borderColor = '';
                  warnUnitEl.style.borderColor = '';
                  if (v !== 'duration' && v !== 'datetime') return;
                  var warnVal = parseInt(warnValEl.value, 10);
                  var warnUnit = (warnUnitEl.value || 'days').trim();
                  var expiryHours = null;
                  var expiryLabel = 'the expiry period';
                  var validator = (window.CustomExpiryValidation || {});
                  var durationToHours = (typeof validator.durationToHours === 'function') ? validator.durationToHours : function() { return null; };
                  if (v === 'duration') {
                    var durValEl = expiryBox.querySelector('.execute-output-expiry-duration-value');
                    var durUnitEl = expiryBox.querySelector('.execute-output-expiry-duration-unit');
                    var durVal = durValEl ? parseInt(durValEl.value, 10) : null;
                    var durUnit = (durUnitEl ? (durUnitEl.value || 'days') : 'days').trim();
                    expiryHours = durationToHours(durVal != null && !isNaN(durVal) ? durVal : null, durUnit);
                    expiryLabel = (durVal != null ? durVal : '') + ' ' + durUnit;
                  } else {
                    var dtEl = expiryBox.querySelector('.execute-output-expiry-datetime');
                    var raw = dtEl ? (dtEl.value || '').trim() : '';
                    if (raw) {
                      var expiryAt = new Date(raw);
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
                  if (typeof validator.validateWarnNotLongerThanExpiry === 'function') {
                    var res = validator.validateWarnNotLongerThanExpiry({
                      outputName: outName,
                      warnValue: isNaN(warnVal) ? null : warnVal,
                      warnUnit: warnUnit,
                      expiryHours: expiryHours,
                      expiryLabel: expiryLabel,
                    });
                    if (res && res.valid === false) {
                      errEl.textContent = res.message || 'Warn period must not be longer than the expiry period.';
                      errEl.style.display = 'block';
                      warnValEl.style.borderColor = 'var(--danger, #dc2626)';
                      warnUnitEl.style.borderColor = 'var(--danger, #dc2626)';
                    }
                  }
                }
                [expiryBox.querySelector('.execute-output-expiry-duration-value'), expiryBox.querySelector('.execute-output-expiry-duration-unit'), expiryBox.querySelector('.execute-output-expiry-warning-value'), expiryBox.querySelector('.execute-output-expiry-warning-unit'), expiryBox.querySelector('.execute-output-expiry-datetime')].forEach(function(el) {
                  if (el) { el.addEventListener('input', runValidation); el.addEventListener('change', runValidation); }
                });
                modeSel.addEventListener('change', runValidation);
              })();
            }
          }
          // When both expiry and ready date are set at execution, highlight "expiry before ready" before submit
          var readyDateBox = outputSection.querySelector('.execute-output-ready-date-input');
          if (expiryBox && readyDateBox && typeof window.ExpiryReadyDateValidation !== 'undefined' && typeof window.ExpiryReadyDateValidation.validateExpiryAfterReadyDates === 'function') {
            var expiryReadyErrEl = outputSection.querySelector('.execute-output-expiry-ready-validation-error');
            var readyDateInputEl = readyDateBox.querySelector('.execute-output-ready-date-date');
            function runExpiryReadyValidation() {
              if (!expiryReadyErrEl) return;
              expiryReadyErrEl.style.display = 'none';
              expiryReadyErrEl.textContent = '';
              expiryBox.style.borderColor = '';
              expiryBox.style.boxShadow = '';
              readyDateBox.style.borderColor = '';
              readyDateBox.style.boxShadow = '';
              var modeSel = expiryBox.querySelector('.execute-output-expiry-input-mode');
              var inputMode = modeSel ? (modeSel.value || 'duration') : 'duration';
              if (inputMode !== 'datetime') return;
              var dtEl = expiryBox.querySelector('.execute-output-expiry-datetime');
              var expiryRaw = dtEl ? (dtEl.value || '').trim() : '';
              var readyRaw = readyDateInputEl ? (readyDateInputEl.value || '').trim() : '';
              if (!expiryRaw || !readyRaw) return;
              var readyIso = readyRaw ? (new Date(readyRaw + 'T00:00:00Z')).toISOString() : null;
              var expiryIso = expiryRaw ? (new Date(expiryRaw)).toISOString() : null;
              if (!readyIso || !expiryIso) return;
              var res = window.ExpiryReadyDateValidation.validateExpiryAfterReadyDates(outName, readyIso, expiryIso);
              if (!res.valid) {
                expiryReadyErrEl.textContent = res.message || 'Expiry date cannot be before the ready date.';
                expiryReadyErrEl.style.display = 'block';
                expiryBox.style.borderColor = 'var(--error, #ef4444)';
                expiryBox.style.boxShadow = '0 0 0 1px var(--error, #ef4444)';
                readyDateBox.style.borderColor = 'var(--error, #ef4444)';
                readyDateBox.style.boxShadow = '0 0 0 1px var(--error, #ef4444)';
              }
            }
            if (readyDateInputEl) {
              readyDateInputEl.addEventListener('input', runExpiryReadyValidation);
              readyDateInputEl.addEventListener('change', runExpiryReadyValidation);
            }
            [expiryBox.querySelector('.execute-output-expiry-datetime'), expiryBox.querySelector('.execute-output-expiry-input-mode')].forEach(function(el) {
              if (el) { el.addEventListener('input', runExpiryReadyValidation); el.addEventListener('change', runExpiryReadyValidation); }
            });
          }
        } catch (e) {}

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
    
    // Submit button is always enabled; we do not enforce strict quantity or require every input to have a selection
    const submitButton = modal.querySelector('#execute-step-submit-btn');
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.style.opacity = '1';
      submitButton.style.cursor = 'pointer';
      submitButton.title = '';
    }
    
    // Show modal
    showModal();
  };
  
  // ============================================================
  // SUBMIT EXECUTION (Complete Step with Data)
  // ============================================================
  window.submitExecution = async function() {
    const modal = document.getElementById('execute-step-modal');
    if (!modal) return;
    const renderMode =
      (window.ExecutionUI && typeof window.ExecutionUI.getRenderMode === 'function')
        ? window.ExecutionUI.getRenderMode(modal)
        : ((modal.dataset && modal.dataset.renderMode) ? String(modal.dataset.renderMode) : 'modal');
    
    var executionId = modal.dataset.executionId;
    var executionStepId = modal.dataset.executionStepId;
    var draftProcessId = modal.dataset.draftProcessId;

    if (draftProcessId) {
      try {
        var createResult = await CoreAPI.createExecution(draftProcessId);
        executionId = createResult.id || createResult.execution_id || (createResult.execution && createResult.execution.id);
        if (!executionId) {
          showNotification('error', 'Error', 'Could not create execution.');
          return;
        }
        var executionData = await CoreAPI.getExecution(executionId);
        var steps = executionData.execution_steps || [];
        var readyStep = steps.find(function(es) { return es.status === 'ready' || es.status === 'READY'; });
        if (!readyStep || !readyStep.id) {
          showNotification('error', 'Error', 'Could not find step to complete.');
          return;
        }
        executionStepId = readyStep.id;
        modal.dataset.executionId = executionId;
        modal.dataset.executionStepId = executionStepId;
        modal.dataset.draftProcessId = '';
      } catch (err) {
        showNotification('error', 'Failed to start execution', err && err.message ? err.message : 'Please try again.');
        return;
      }
    }

    if (!executionId || !executionStepId) {
      showNotification('error', 'Error', 'Execution context missing.');
      return;
    }
    
    // VALIDATION: For each input row that has an inventory selected, require valid quantity (no strict match to step expected)
    const validationErrors = [];
    const inputRows = modal.querySelectorAll('.execute-input-row');
    inputRows.forEach(row => {
      const select = row.querySelector('.execute-inventory-select');
      const quantityInput = row.querySelector('.execute-quantity-input');
      if (!select || !quantityInput) return;
      const inventoryId = select.value;
      const inputName = select.dataset.inputName;
      if (!inventoryId || inventoryId === '') return;
      const quantity = parseFloat(quantityInput.value);
      if (!quantity || isNaN(quantity) || quantity <= 0) {
        validationErrors.push(`Please enter a valid quantity for "${inputName}" (selected row)`);
        quantityInput.style.border = '2px solid var(--error, #ef4444)';
      } else {
        quantityInput.style.border = '';
        const availableQty = parseFloat(select.dataset.quantity);
        if (!isNaN(availableQty) && quantity > availableQty) {
          const inventoryUnit = select.dataset.unit || '';
          const quantityUnit = quantityInput.dataset.inventoryUnit || inventoryUnit;
          validationErrors.push(`Quantity for "${inputName}" (${quantity} ${quantityUnit}) exceeds available inventory (${availableQty} ${inventoryUnit})`);
          quantityInput.style.border = '2px solid var(--error, #ef4444)';
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
    
    var invList = modal._inventoryForSubmit || [];
    var invById = new Map();
    invList.forEach(function(i) { if (i && i.id != null) invById.set(String(i.id), i); });
    var notReadyUsed = [];
    var stateIter = (modal._inputStateByKey && modal._inputStateByKey.size > 0)
      ? Array.from(modal._inputStateByKey.values())
      : null;
    if (stateIter) {
      stateIter.forEach(function(st) {
        if (!st || !st.inventory_item_id) return;
        var item = invById.get(String(st.inventory_item_id));
        if (!item || !Array.isArray(item.system_findings)) return;
        var finding = item.system_findings.find(function(f) { return f && f.check_id === 'output_ready_date'; });
        if (finding) {
          notReadyUsed.push({ inputName: st.input_name || 'Input', itemName: item.name || 'Unknown', reason: finding.reason || 'Not ready' });
        }
      });
    } else {
      modal.querySelectorAll('.execute-input-row').forEach(function(row) {
        var select = row.querySelector('.execute-inventory-select');
        if (!select) return;
        var invId = select.value;
        if (!invId) return;
        var item = invById.get(String(invId));
        if (!item || !Array.isArray(item.system_findings)) return;
        var finding = item.system_findings.find(function(f) { return f && f.check_id === 'output_ready_date'; });
        if (finding) {
          var inputName = select.dataset.inputName || 'Input';
          notReadyUsed.push({ inputName: inputName, itemName: item.name || 'Unknown', reason: finding.reason || 'Not ready' });
        }
      });
    }
    var allowConsumptionOverride = false;
    if (notReadyUsed.length > 0) {
      var confirmed = typeof window.showReadyDateConfirmModal === 'function'
        ? await window.showReadyDateConfirmModal(notReadyUsed)
        : false;
      if (!confirmed) return;
      allowConsumptionOverride = true;
    }

    try {
      // Collect variable inputs from state (preferred) or DOM (fallback)
      const actualInputs = [];
      if (modal._inputStateByKey && modal._inputStateByKey.size > 0) {
        Array.from(modal._inputStateByKey.values()).forEach(function(st) {
          if (!st || !st.inventory_item_id) return;
          actualInputs.push({
            name: st.input_name,
            inventory_item_id: st.inventory_item_id,
            quantity: st.quantity != null ? st.quantity : 0,
            unit: st.unit || ''
          });
        });
      } else {
        modal.querySelectorAll('.execute-input-row').forEach(row => {
          const select = row.querySelector('.execute-inventory-select');
          const quantityInput = row.querySelector('.execute-quantity-input');
          if (!select || !quantityInput) return;
          const inventoryId = select.value;
          if (!inventoryId) return;
          const quantity = parseFloat(quantityInput.value);
          const unit = select.dataset.unit || '';
          actualInputs.push({
            name: select.dataset.inputName,
            inventory_item_id: inventoryId,
            quantity: isNaN(quantity) ? 0 : quantity,
            unit: unit
          });
        });
      }
      
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

      // Validate set_at_execution expiry: warn must not exceed expiry period (duration or time until datetime)
      var expiryValidator = (window.CustomExpiryValidation || {});
      var durationToHours = (typeof expiryValidator.durationToHours === 'function') ? expiryValidator.durationToHours : function() { return null; };
      const expiryValidationErrors = [];
      (allStepOutputs || []).forEach(function(outputDef) {
        var ce = (outputDef.extra_data || {}).custom_expiry;
        if (!ce || !ce.enabled || (ce.mode || '') !== 'set_at_execution') return;
        var outName = (outputDef.name || '').trim();
        var getOutputId = window.getExecutionOutputId || function(o) { return (o && o.id) ? String(o.id) : ('out-' + (o && o.name ? String(o.name).replace(/\s+/g, '-') : 'unknown')); };
        var outId = getOutputId(outputDef);
        var box = Array.from(modal.querySelectorAll('.execute-output-expiry-input')).find(function(b) {
          return (b.dataset.outputId || '').trim() === outId;
        });
        if (!box) return;
        var modeSel = box.querySelector('.execute-output-expiry-input-mode');
        var inputMode = modeSel ? (modeSel.value || 'duration') : 'duration';
        var warnValEl = box.querySelector('.execute-output-expiry-warning-value');
        var warnUnitEl = box.querySelector('.execute-output-expiry-warning-unit');
        var warnVal = warnValEl ? parseInt((warnValEl.value || '').trim(), 10) : 0;
        var warnUnit = (warnUnitEl && warnUnitEl.value) || 'days';
        var expiryHours = null;
        if (inputMode === 'duration') {
          var dvEl = box.querySelector('.execute-output-expiry-duration-value');
          var duEl = box.querySelector('.execute-output-expiry-duration-unit');
          var dv = dvEl ? parseInt((dvEl.value || '').trim(), 10) : null;
          var du = (duEl && duEl.value) || 'days';
          expiryHours = durationToHours(dv != null && !isNaN(dv) ? dv : null, du);
        } else {
          var dtEl = box.querySelector('.execute-output-expiry-datetime');
          var raw = dtEl ? (dtEl.value || '').trim() : '';
          if (raw) {
            var expiryAt = new Date(raw);
            if (!isNaN(expiryAt.getTime())) expiryHours = (expiryAt.getTime() - Date.now()) / (1000 * 60 * 60);
          }
        }
        if (expiryHours != null && expiryHours <= 0 && inputMode === 'datetime') {
          expiryValidationErrors.push('Output "' + outName + '": expiry date and time must be in the future.');
          return;
        }
        if (typeof expiryValidator.validateWarnNotLongerThanExpiry === 'function') {
          var res = expiryValidator.validateWarnNotLongerThanExpiry({
            outputName: outName,
            warnValue: isNaN(warnVal) ? null : warnVal,
            warnUnit: warnUnit,
            expiryHours: expiryHours,
            expiryLabel: (inputMode === 'datetime') ? 'the time remaining until expiry' : 'the expiry period',
          });
          if (res && res.valid === false) expiryValidationErrors.push(res.message || ('Output "' + outName + '": invalid warn-before-expiry setting.'));
        }
      });
      if (expiryValidationErrors.length > 0) {
        showNotification('error', 'Invalid expiry settings', expiryValidationErrors[0]);
        var firstBox = modal.querySelector('.execute-output-expiry-input');
        if (firstBox) firstBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }

      // Validate set_at_execution ready date: date of availability must be set
      var readyDateValidationErrors = [];
      (allStepOutputs || []).forEach(function(outputDef) {
        var rd = (outputDef.extra_data || {}).ready_date;
        if (!rd || !rd.enabled || (rd.mode || '') !== 'set_at_execution') return;
        var outName = (outputDef.name || '').trim();
        var getOutputId = window.getExecutionOutputId || function(o) { return (o && o.id) ? String(o.id) : ('out-' + (o && o.name ? String(o.name).replace(/\s+/g, '-') : 'unknown')); };
        var outputId = getOutputId(outputDef);
        var payload = (typeof window.collectExecutionOutputReadyDatePayload === 'function')
          ? window.collectExecutionOutputReadyDatePayload(modal, outputId)
          : null;
        if (!payload || !payload.date) {
          readyDateValidationErrors.push('Output "' + outName + '": set the date when this output can be used.');
        }
      });
      if (readyDateValidationErrors.length > 0) {
        showNotification('error', 'Ready date required', readyDateValidationErrors[0]);
        var firstReadyBox = modal.querySelector('.execute-output-ready-date-input');
        if (firstReadyBox) firstReadyBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }

      // When both expiry and ready date are set at execution, expiry cannot be before ready date (shared config)
      var getOutputIdForValidation = window.getExecutionOutputId || function(o) { return (o && o.id) ? String(o.id) : ('out-' + (o && o.name ? String(o.name).replace(/\s+/g, '-') : 'unknown')); };
      if (typeof window.ExpiryReadyDateValidation !== 'undefined' && typeof window.ExpiryReadyDateValidation.validateExpiryAfterReadyDates === 'function') {
        for (var ei = 0; ei < (allStepOutputs || []).length; ei++) {
          var outputDef = allStepOutputs[ei];
          var rd = (outputDef.extra_data || {}).ready_date;
          var ce = (outputDef.extra_data || {}).custom_expiry;
          if (!rd || !rd.enabled || (rd.mode || '') !== 'set_at_execution') continue;
          if (!ce || !ce.enabled || (ce.mode || '') !== 'set_at_execution') continue;
          var outputId = getOutputIdForValidation(outputDef);
          var readyPayload = typeof window.collectExecutionOutputReadyDatePayload === 'function' ? window.collectExecutionOutputReadyDatePayload(modal, outputId) : null;
          var expiryPayload = typeof window.collectExecutionOutputExpiryPayload === 'function' ? window.collectExecutionOutputExpiryPayload(modal, outputId) : null;
          var readyIso = readyPayload && readyPayload.date ? readyPayload.date : null;
          var expiryIso = expiryPayload && expiryPayload.mode === 'datetime' && expiryPayload.expiry_at ? expiryPayload.expiry_at : null;
          if (readyIso && expiryIso) {
            var outName = (outputDef.name || '').trim();
            var erResult = window.ExpiryReadyDateValidation.validateExpiryAfterReadyDates(outName, readyIso, expiryIso);
            if (!erResult.valid) {
              showNotification('error', 'Expiry and ready date', erResult.message);
              var firstReadyBoxEl = modal.querySelector('.execute-output-ready-date-input');
              if (firstReadyBoxEl) firstReadyBoxEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
              return;
            }
          }
        }
      }

      // First, collect variable outputs (user-entered quantities). Always include each variable output
      // so reconciliation selection (untracked_item_id) is never dropped when quantity is empty.
      const outputInputs = modal.querySelectorAll('.execute-output-quantity-input');
      const variableOutputNames = new Set();
      const getOutputIdForPayload = window.getExecutionOutputId || function(o) { return (o && o.id) ? String(o.id) : ('out-' + (o && o.name ? String(o.name).replace(/\s+/g, '-') : 'unknown')); };
      outputInputs.forEach(input => {
        const outputId = (input.dataset.outputId || '').trim();
        if (!outputId) return;
        const outputDef = allStepOutputs.find(o => getOutputIdForPayload(o) === outputId);
        if (!outputDef) return;
        const name = outputDef.name;
        let quantity = parseFloat(input.value);
        if (isNaN(quantity) || quantity < 0) {
          quantity = outputDef && (outputDef.quantity != null) ? parseFloat(outputDef.quantity) : 0;
          if (isNaN(quantity) || quantity < 0) quantity = 0;
        }
        const reconcileInput = Array.from(modal.querySelectorAll('.execute-reconcile-untracked-value')).find(function(el) {
          return (el.dataset.outputId || '').trim() === outputId;
        });
        const untrackedItemId = (reconcileInput && reconcileInput.value && reconcileInput.value.trim()) ? reconcileInput.value.trim() : null;
        const outPayload = {
          name: name,
          quantity: quantity,
          unit: (outputDef ? (outputDef.unit || 'units') : 'units').trim()
        };
        if (untrackedItemId) outPayload.untracked_item_id = untrackedItemId;
        // If expiry is set during execution, capture operator selection for backend persistence (logic in core-api.js)
        if (typeof window.applyExecutionOutputExpiryToPayload === 'function') {
          window.applyExecutionOutputExpiryToPayload(modal, outputId, outputDef, outPayload);
        }
        if (typeof window.applyExecutionOutputReadyDateToPayload === 'function') {
          window.applyExecutionOutputReadyDateToPayload(modal, outputId, outputDef, outPayload);
        }
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

      // Complete the step (send allow_consumption_override when user confirmed "Use anyway" for not-ready items)
      const completeResult = await CoreAPI.completeStep(executionId, executionStepId, {
        actual_inputs: actualInputs,
        actual_outputs: actualOutputs,
        execution_data: executionData,
        allow_consumption_override: allowConsumptionOverride || undefined
      });
      
      // Close modal (clean up dropdown listener first)
      if (modal._closeInventoryDropdown) {
        try { modal._closeInventoryDropdown(); } finally { modal._closeInventoryDropdown = null; }
      }
      if (renderMode !== 'page') {
        modal.style.display = 'none';
        document.body.style.overflow = 'auto';
      }
      
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
