/**
 * Opens execute-step UI (modal or page): loads data, delegates to render modules.
 * execution-modal.js assigns window.openExecutionModal with ctx deps.
 */
(function (root) {
  "use strict";

  var openExecutionModalGeneration = 0;

  async function openExecutionModal(ctx, executionId, executionStep, stepDefinition, options) {
    var SessionAPI = ctx.SessionAPI;
    var convertUnit = ctx.convertUnit;
    var prettyLabel = ctx.prettyLabel;
    var loadOrgUsersMap = ctx.loadOrgUsersMap;
    var CoreAPI = ctx.CoreAPI != null ? ctx.CoreAPI : root.CoreAPI;
    var escapeHtml =
      typeof root.escapeHtml === "function"
        ? root.escapeHtml
        : function (x) {
            return String(x == null ? "" : x);
          };

    const modal = document.getElementById('execute-step-modal');
    if (!modal) {
      console.error('Execution modal not found');
      return;
    }
    var openGen = ++openExecutionModalGeneration;
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
        var s = SessionAPI.get(modal);
        if (s && s.closeInventoryDropdown) {
          try { s.closeInventoryDropdown(); } finally { s.closeInventoryDropdown = null; }
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
    SessionAPI.resetForOpen(modal);
    var ses = SessionAPI.get(modal);

    // Load inventory, expired/flagged, untracked, and step documentation in parallel
    const stepId = stepDefinition && stepDefinition.id ? String(stepDefinition.id) : null;
    const docsPromise = (stepId && typeof CoreAPI.getStepDocumentation === 'function')
      ? CoreAPI.getStepDocumentation(stepId).catch(function() { return { documents: [] }; })
      : Promise.resolve({ documents: [] });
    
    const [inventoryData, expiredData, untrackedData, docsData, orgUsersMap] = await Promise.all([
      CoreAPI.getInventory(),
      CoreAPI.getExpiredMaterials().catch(function() { return { expired_raw_materials: [], impacted_items: [] }; }),
      CoreAPI.getUntrackedItems().catch(function() { return { untracked_items: [] }; }),
      docsPromise,
      loadOrgUsersMap()
    ]);

    if (openGen !== openExecutionModalGeneration) {
      return;
    }

    // Render step documentation (SOP) – read-only
    const documents = (docsData && docsData.documents) ? docsData.documents : [];
    window.ExecutionRenderDocs.renderStepDocumentation(docsSection, docsContainer, documents);
    const allInventory = inventoryData.inventory_items || [];
    ses.inventoryForSubmit = allInventory;
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
    
    // convertUnit is defined at module scope (used by submit validation too).
    
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
      window.ExecutionRenderInputs.renderVariableInventoryInputs({
        modal: modal,
        ses: ses,
        inputsContainer: inputsContainer,
        variableInputs: variableInputs,
        allInventory: allInventory,
        getExpiredReason: getExpiredReason,
        escapeHtml: escapeHtml,
        prettyLabel: prettyLabel,
        convertUnit: convertUnit,
        orgUsersMap: orgUsersMap,
      });
    }

    if (confirmInputs.length > 0 && inputsContainer) {
      window.ExecutionRenderInputs.renderConfirmExecutionInputs({
        inputsContainer: inputsContainer,
        confirmInputs: confirmInputs,
        escapeHtml: escapeHtml,
      });
    }

    if (inputsContainer && variableInputs.length === 0 && confirmInputs.length === 0) {
      inputsContainer.innerHTML = '<p style="color: var(--text-secondary); font-size: 14px; padding: 16px;">No variable inputs for this step.</p>';
    }
    
    await window.ExecutionRenderPrompts.renderExecutionPrompts({
      modal: modal,
      ses: ses,
      promptsContainer: promptsContainer,
      stepDefinition: stepDefinition,
      escapeHtml: escapeHtml,
    });

    if (openGen !== openExecutionModalGeneration) {
      return;
    }

    await window.ExecutionRenderOutputs.renderVariableOutputs({
      modal: modal,
      outputsContainer: outputsContainer,
      stepDefinition: stepDefinition,
      untrackedItems: untrackedItems,
      escapeHtml: escapeHtml,
    });

    if (openGen !== openExecutionModalGeneration) {
      return;
    }

    // Submit button is always enabled; we do not enforce strict quantity or require every input to have a selection
    const submitButton = modal.querySelector('#execute-step-submit-btn');
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.style.opacity = '1';
      submitButton.style.cursor = 'pointer';
      submitButton.title = '';
    }

    if (openGen !== openExecutionModalGeneration) {
      return;
    }

    // Show modal
    showModal();

  }

  root.ExecutionOpenStep = {
    openExecutionModal: openExecutionModal,
  };
})(typeof window !== "undefined" ? window : this);
