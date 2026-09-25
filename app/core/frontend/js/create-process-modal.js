(function() {
  'use strict';

  const {
    summaryInputDisplayName,
    summaryOutputDisplayName,
    isCustomExecutionPrompt,
    countLabeledExecutionPrompts,
    normalisePromptOptions,
    base64ToBlob,
    escapeHtmlForText
  } = window.ProcessModalUtils;
  const {
    mapSessionInputsToApiPayloadFromRows,
    validateInventoryInputsFromSession,
    buildExecutionPromptsForApiFromSession,
    wizardSessionHasDraftStepData,
    mapSessionInputsToSummaryRows,
    mapApiInputToWizardSessionInput,
    mapApiOutputToWizardSessionOutput
  } = window.ProcessModalMappers;
  const {
    applyProcessFlowWizardFreshStart,
    bindProcessFlowWizardExitCleanup,
    clearProcessFlowWizardRecoveryState,
    getDraftKey,
    getFlowWizardPageSlug,
    getProcessFlowSpaStorageKey,
    isProcessFlowSpaPage,
    isProcessFlowWizardPage,
    loadWizardSessionMergeBase,
    migrateProcessFlowSpaStorage,
    shouldMergePersistSpaFormFields,
    PROCESS_FLOW_PENDING_NEW_STEP_KEY
  } = window.ProcessModalSession;
  const {
    formatStep4ModeLabel,
    buildOutputModeSegmentRow,
    syncOutputExpiryModeSegments,
    syncOutputReadyDateModeSegments,
    initGuidedOutputsListModeSegments,
    applyNewMaterialExecutionExplanation,
    syncGuidedNewInputExecutionSegments,
    buildNewMaterialExecutionTypeField,
    initGuidedNewInputExecutionSegments,
    syncStep4ModeSegments,
    updateStep4SummaryBar,
    initStep4SegmentControls
  } = window.ProcessModalControls;
  const {
    syncDocInlineDisabledState,
    ensureDocFileListener,
    loadAttachedStepDocs,
    getPendingGuidedDocFileUpload,
    setPendingGuidedDocFileUpload
  } = window.ProcessModalDocs;
  const {
    deriveTraceabilityModes,
    formatTraceabilityModeLabel,
    formatOutputExpirySummary,
    formatOutputReadySummary,
    buildStepSummaryWarnings
  } = window.ProcessModalSummaryUtils;
  const {
    countNamedStepInputs,
    countNamedStepOutputs,
    mergeDraftCreatedStepsIntoApiSteps,
    stepSortKey,
    sortStepsForDisplay
  } = window.ProcessModalStepData;
  const {
    getGuidedInputListElement,
    getAllGuidedInputElements,
    collectCurrentInputs,
    collectCurrentOutputs,
    collectCurrentPrompts,
    collapseAllInputs,
    collapseAllOutputs,
    toggleInputExpand,
    toggleOutputExpand
  } = window.ProcessModalRows;
  const restorePromptList = window.ProcessModalPromptRestore.create({ normalisePromptOptions });
  const {
    inventoryCardSummary,
    inventoryExecutionHelperText,
    inventoryCardMetadataHtml
  } = window.ProcessModalInventoryCards;
  const {
    collectSpaWizardOutputsPayload,
    preserveCreatedStepsIoFromPrev
  } = window.ProcessModalSpaPayloads;
  
  let currentStep = 1;
  const totalSteps = 4;
  let guidedInputs = [];
  let guidedOutputs = [];
  let guidedPrompts = [];
  let selectedInventoryItems = new Set(); // Track selected inventory items to prevent duplicates
  let selectedPreviousOutputs = new Set(); // Track selected previous step outputs (by displayName) to prevent duplicates
  let createdSteps = []; // Track steps created in this session
  let editingStepId = null; // Track which step is being edited (if resuming draft)
  let isRestoringDraft = false; // Flag to prevent step reset during draft restoration
  let isEditingExistingProcess = false; // True when modal was opened for a non-draft process with steps (show list + Edit / Add new step)
  let isStartNewOverwriteDraft = false; // True when user chose "Start New" on resume draft — save/finish should overwrite old draft steps
  let startNewOldStepIds = []; // Step IDs that existed when user clicked Start New; we delete these on save draft or finish
  let processFlowWizardInitGeneration = 0;

  // Get draft key for current process




  /** When true, serializeSpaWizardState merges missing DOM fields from session (summary page has no wizard form). */








  const serializeSpaWizardState = window.ProcessModalSpaPayloads.createStateSerializer({
    shouldMergePersistSpaFormFields,
    loadWizardSessionMergeBase,
    getAllGuidedInputElements,
    collectCurrentPrompts,
    getCreatedSteps: function() { return createdSteps; },
    getEditingStepId: function() { return editingStepId; },
    getFlowWizardPageSlug,
    getPendingGuidedDocFileUpload
  });

  window.persistSpaWizardState = function() {
    if (!isProcessFlowSpaPage()) return;
    try {
      const payload = serializeSpaWizardState();
      sessionStorage.setItem(getProcessFlowSpaStorageKey(), JSON.stringify(payload));
    } catch (e) {
      console.warn('persistSpaWizardState failed', e);
    }
  };

  /**
   * Persist without an in-progress step draft (empty step fields, no doc file payload).
   * Keeps process id, workflowProcessName, and createdSteps.
   * Required when the current route has no wizard DOM (e.g. next-steps): plain persistSpaWizardState
   * would merge the previous session snapshot back in and repopulate the next step.
   * Also call after saving a step so session does not still look like an unsaved draft (blocks Finish).
   */
  function persistClearedWizardDraftState() {
    if (!isProcessFlowSpaPage()) return;
    try {
      const prev = loadWizardSessionMergeBase() || {};
      const pid =
        new URLSearchParams(window.location.search || '').get('id') || prev.processId || null;
      const payload = window.ProcessModalSpaPayloads.buildClearedDraftPayload(
        prev,
        pid,
        createdSteps
      );
      sessionStorage.setItem(getProcessFlowSpaStorageKey(), JSON.stringify(payload));
    } catch (e) {
      console.warn('persistClearedWizardDraftState failed', e);
    }
  }

  const applyOutputPayloadToLastContainer = window.ProcessModalOutputRestore.create({
    syncOutputExpiryModeSegments,
    syncOutputReadyDateModeSegments
  });

  window.restoreSpaWizardState = async function(options) {
    if (!isProcessFlowSpaPage()) return;
    const isCurrent = options && typeof options.isCurrent === 'function' ? options.isCurrent : function() { return true; };
    if (!isCurrent()) return;
    migrateProcessFlowSpaStorage();
    const raw = sessionStorage.getItem(getProcessFlowSpaStorageKey());
    if (!raw) return;
    let data;
    try {
      data = JSON.parse(raw);
    } catch (e) {
      return;
    }
    if (!data || data.v !== 1) return;
    isRestoringDraft = true;
    const stepNameInput = document.getElementById('guided-step-name');
    const stepDescInput = document.getElementById('guided-step-description');
    if (stepNameInput) stepNameInput.value = data.stepName || '';
    if (stepDescInput) stepDescInput.value = data.stepDescription || '';
    const workflowNameInput = document.getElementById('guided-process-workflow-name');
    if (workflowNameInput && Object.prototype.hasOwnProperty.call(data, 'workflowProcessName')) {
      workflowNameInput.value = data.workflowProcessName != null ? data.workflowProcessName : '';
    }
    // Server data is authoritative once a process exists. Session storage only
    // protects the form currently being composed between wizard pages.
    const hasPersistedProcess = !!new URLSearchParams(window.location.search || '').get('id');
    if (!hasPersistedProcess && Array.isArray(data.createdSteps)) {
      createdSteps = data.createdSteps;
    }
    if (Object.prototype.hasOwnProperty.call(data, 'editingStepId')) {
      editingStepId = data.editingStepId || null;
    }
    if (data.processId && typeof data.processId === 'string' && !new URLSearchParams(window.location.search || '').get('id')) {
      try {
        const u = new URL(window.location.href);
        u.searchParams.set('id', data.processId);
        window.history.replaceState({}, '', u);
      } catch (e) {}
    }
    const docInlineTitleRestore = document.getElementById('guided-doc-inline-title');
    const docInlineContentRestore = document.getElementById('guided-doc-inline-content');
    if (docInlineTitleRestore) {
      docInlineTitleRestore.value = data.docInlineTitle != null ? data.docInlineTitle : '';
    }
    if (docInlineContentRestore) {
      docInlineContentRestore.value = data.docInlineContent != null ? data.docInlineContent : '';
    }
    if (typeof syncDocInlineDisabledState === 'function') syncDocInlineDisabledState();
    setPendingGuidedDocFileUpload(null);
    if (data.docFileUpload && data.docFileUpload.base64) {
      setPendingGuidedDocFileUpload({
        fileName: data.docFileUpload.fileName,
        mime: data.docFileUpload.mime,
        base64: data.docFileUpload.base64
      });
    }
    const listEl = getGuidedInputListElement('inventory');
    if (listEl) {
      listEl.innerHTML = '';
      selectedInventoryItems.clear();
      selectedPreviousOutputs.clear();
      for (const inp of data.inputs || []) {
        if (!isCurrent()) return;
        try {
          if (inp.inputType === 'inventory' && inp.inventoryPreselected && inp.name) {
            const categorized = await loadInventoryItems();
            const allItems = [
              ...(categorized.raw_material || []),
              ...(categorized.work_in_progress || []),
              ...(categorized.final_product || [])
            ];
            const item = allItems.find(i => i.name === inp.name);
            if (item) {
              await window.addGuidedInput('inventory', true, {
                ...item,
                quantity: inp.quantity,
                unit: inp.unit,
                executionType: inp.executionType
              }, undefined);
              if (!isCurrent()) return;
              continue;
            }
          }
          const apiShape = {
            name: inp.name,
            quantity: inp.quantity,
            unit: inp.unit,
            is_variable: inp.is_variable,
            requires_inventory_selection: inp.requires_inventory_selection,
            source_output_id: inp.source_output_id
          };
          const container = await window.addGuidedInput(inp.inputType || 'new', true, undefined, apiShape);
          if (!isCurrent()) return;
          if (container && listEl) listEl.appendChild(container);
        } catch (err) {
          console.warn('restore input failed', err);
        }
      }
    }
    const outputsList = document.getElementById('guided-outputs-list');
    if (outputsList) {
      outputsList.innerHTML = '';
      for (const out of data.outputs || []) {
        if (!isCurrent()) return;
        await window.addGuidedOutput();
        if (!isCurrent()) return;
        await applyOutputPayloadToLastContainer(out);
      }
    }
    restorePromptList(data.prompts || []);
    const batchEl = document.getElementById('guided-prompt-batch-number-mode');
    if (batchEl) {
      const bm = data.batchNumberMode;
      if (bm === 'required' || bm === 'optional' || bm === 'dont_ask') {
        batchEl.value = bm;
      }
    }
    const evEl = document.getElementById('guided-prompt-evidence-mode');
    if (evEl) {
      const evm = data.evidenceMode;
      if (evm === 'required' || evm === 'optional' || evm === 'dont_ask') {
        evEl.value = evm;
      }
    }
    if (data.inputTab) {
      const tabBtn = document.querySelector('.flow-mode-segment[data-input-tab="' + data.inputTab + '"]');
      if (tabBtn) tabBtn.click();
    }
    updateInputButtonsText();
    updateOutputButtonText();
    syncStep4ModeSegments();
    if (typeof updateStep4SummaryBar === 'function') updateStep4SummaryBar();
    requestAnimationFrame(function() {
      syncStep4ModeSegments();
      if (typeof updateStep4SummaryBar === 'function') updateStep4SummaryBar();
    });
    isRestoringDraft = false;
  };
  
  // Restore a step's data into the form (name, description, inputs, outputs, execution_prompts). Caller sets editingStepId.
  async function restoreStepIntoForm(step) {
    const stepNameInput = document.getElementById('guided-step-name');
    const stepDescInput = document.getElementById('guided-step-description');
    if (stepNameInput) stepNameInput.value = step.name || '';
    if (stepDescInput) stepDescInput.value = step.description || '';
    
    if (step.inputs && step.inputs.length > 0) {
      const inputContainers = await Promise.all(step.inputs.map(input => {
        const inputType = input.source_output_id ? 'previous_output' : (input.requires_inventory_selection ? 'inventory' : 'new');
        return window.addGuidedInput(inputType, true, undefined, input);
      }));
      const listEl = getGuidedInputListElement('inventory');
      if (listEl) {
        inputContainers.forEach(c => listEl.appendChild(c));
      }
      updateInputButtonsText();
    }
    
    if (step.outputs && step.outputs.length > 0) {
      for (const output of step.outputs) {
        await window.addGuidedOutput();
        const outputContainers = document.querySelectorAll('#guided-outputs-list > div');
        const lastOutputContainer = outputContainers[outputContainers.length - 1];
        if (lastOutputContainer) {
          if (output.inventory_type === 'work_in_progress' || output.inventory_type === 'final_product') {
            lastOutputContainer.dataset.outputInventoryType = output.inventory_type;
          } else if (!lastOutputContainer.dataset.outputInventoryType) {
            lastOutputContainer.dataset.outputInventoryType = 'work_in_progress';
          }
          const nameInput = lastOutputContainer.querySelector('.guided-output-name');
          if (nameInput) {
            nameInput.value = output.name || '';
            nameInput.dispatchEvent(new Event('input'));
            nameInput.dispatchEvent(new Event('blur'));
          }
          const quantityInput = lastOutputContainer.querySelector('.guided-output-quantity');
          if (quantityInput && output.quantity !== null && output.quantity !== undefined) {
            quantityInput.value = output.quantity;
          }
          const unitSelect = lastOutputContainer.querySelector('.guided-output-unit');
          if (unitSelect && output.unit) unitSelect.value = output.unit;
          if (output.id) lastOutputContainer.dataset.outputId = output.id;
          const nameDisplay = lastOutputContainer.querySelector('.guided-output-name-display');
          const titleSpan = lastOutputContainer.querySelector('.guided-output-title');
          if (nameDisplay && titleSpan && output.name) {
            nameDisplay.textContent = output.name;
            nameDisplay.style.display = 'inline';
            titleSpan.style.display = 'none';
          }
          // Restore custom expiry sub-pane for this output
          const ce = (output.extra_data || {}).custom_expiry;
          const expiryModeEl = lastOutputContainer.querySelector('.guided-output-expiry-mode');
          const expiryValueEl = lastOutputContainer.querySelector('.guided-output-expiry-value');
          const expiryUnitEl = lastOutputContainer.querySelector('.guided-output-expiry-unit');
          const warningValueEl = lastOutputContainer.querySelector('.guided-output-expiry-warning-value');
          const warningUnitEl = lastOutputContainer.querySelector('.guided-output-expiry-warning-unit');
          const expiryFieldsWrap = lastOutputContainer.querySelector('.guided-output-expiry-fields');
          const fixedWrap = lastOutputContainer.querySelector('.guided-output-expiry-fixed-fields');
          const execHint = lastOutputContainer.querySelector('.guided-output-expiry-exec-hint');
          const enabled = !!(ce && ce.enabled);
          let mode = enabled ? (ce.mode || null) : null;
          if (enabled && !mode) {
            mode = (ce.set_at_execution || ce.set_during_execution) ? 'set_at_execution' : 'fixed_duration';
            if (ce.expiry_days != null) mode = 'fixed_duration';
          }
          if (expiryModeEl) {
            expiryModeEl.value = enabled ? (mode || 'fixed_duration') : 'none';
            const m = expiryModeEl.value;
            if (expiryFieldsWrap) expiryFieldsWrap.style.display = m !== 'none' ? 'block' : 'none';
            if (fixedWrap) fixedWrap.style.display = m === 'fixed_duration' ? 'block' : 'none';
            if (execHint) execHint.style.display = m === 'set_at_execution' ? 'block' : 'none';
          }
          if (enabled) {
            const durVal = ce.duration_value != null ? ce.duration_value : ce.expiry_days;
            const durUnit = ce.duration_unit || 'days';
            if (expiryValueEl && durVal != null) expiryValueEl.value = String(durVal);
            if (expiryUnitEl && durUnit) expiryUnitEl.value = durUnit;
            if (mode === 'fixed_duration') {
              const warnVal = ce.warning_value != null ? ce.warning_value : ce.warning_days;
              const warnUnit = ce.warning_unit || 'days';
              if (warningValueEl && warnVal != null) warningValueEl.value = String(warnVal);
              if (warningUnitEl && warnUnit) warningUnitEl.value = warnUnit;
            } else {
              // For set_at_execution, warning is set during execution (do not show / restore here)
              if (warningValueEl) warningValueEl.value = '';
              if (warningUnitEl) warningUnitEl.value = 'days';
            }
          }
          // Restore ready date sub-pane for this output (mode: none | fixed_duration | set_at_execution)
          const rd = (output.extra_data || {}).ready_date;
          const readyDateModeEl = lastOutputContainer.querySelector('.guided-output-ready-date-mode');
          const readyDateValueEl = lastOutputContainer.querySelector('.guided-output-ready-date-value');
          const readyDateUnitEl = lastOutputContainer.querySelector('.guided-output-ready-date-unit');
          const readyDateWarnValueEl = lastOutputContainer.querySelector('.guided-output-ready-date-warning-value');
          const readyDateWarnUnitEl = lastOutputContainer.querySelector('.guided-output-ready-date-warning-unit');
          const readyDateFieldsEl = lastOutputContainer.querySelector('.guided-output-ready-date-fields');
          const readyDateFixedEl = lastOutputContainer.querySelector('.guided-output-ready-date-fixed-fields');
          const readyDateExecHintEl = lastOutputContainer.querySelector('.guided-output-ready-date-exec-hint');
          const readyDateWarnWrapEl = lastOutputContainer.querySelector('.guided-output-ready-date-warning-wrap');
          if (readyDateModeEl) {
            const mode = (rd && rd.enabled && rd.mode) ? rd.mode : 'none';
            readyDateModeEl.value = mode;
            if (readyDateFieldsEl) readyDateFieldsEl.style.display = mode !== 'none' ? 'block' : 'none';
            if (readyDateFixedEl) readyDateFixedEl.style.display = mode === 'fixed_duration' ? 'block' : 'none';
            if (readyDateExecHintEl) readyDateExecHintEl.style.display = mode === 'set_at_execution' ? 'block' : 'none';
            if (readyDateWarnWrapEl) readyDateWarnWrapEl.style.display = mode === 'fixed_duration' ? 'block' : 'none';
          }
          if (rd && (rd.mode === 'fixed_duration' || (rd.enabled && rd.duration_value != null))) {
            if (readyDateValueEl && rd.duration_value != null) readyDateValueEl.value = String(rd.duration_value);
            if (readyDateUnitEl && rd.duration_unit) readyDateUnitEl.value = rd.duration_unit;
            if (readyDateWarnValueEl && rd.warning_value != null) readyDateWarnValueEl.value = String(rd.warning_value);
            if (readyDateWarnUnitEl && rd.warning_unit) readyDateWarnUnitEl.value = rd.warning_unit;
          }
          if (expiryModeEl) expiryModeEl.dispatchEvent(new Event('change', { bubbles: true }));
          if (readyDateModeEl) readyDateModeEl.dispatchEvent(new Event('change', { bubbles: true }));
        }
      }
    }
    
    if (step.execution_prompts && step.execution_prompts.length > 0) {
      const batchNumberModeEl = document.getElementById('guided-prompt-batch-number-mode');
      const evidenceModeEl = document.getElementById('guided-prompt-evidence-mode');
      if (batchNumberModeEl) batchNumberModeEl.value = 'dont_ask';
      if (evidenceModeEl) evidenceModeEl.value = 'dont_ask';
      for (const prompt of step.execution_prompts) {
        const isBatchNumber = (prompt.label || '').toLowerCase() === 'batch number';
        const isEvidence = prompt.type === 'evidence' || (prompt.label || '').toLowerCase() === 'evidence';
        if (isBatchNumber && batchNumberModeEl) {
          batchNumberModeEl.value = prompt.required !== false ? 'required' : 'optional';
          continue;
        }
        if (isEvidence && evidenceModeEl) {
          evidenceModeEl.value = prompt.required !== false ? 'required' : 'optional';
          continue;
        }
        if (!isBatchNumber && !isEvidence) {
          window.addGuidedPrompt();
          const promptContainers = document.querySelectorAll('#guided-prompts-list > div');
          const lastPromptContainer = promptContainers[promptContainers.length - 1];
          if (lastPromptContainer) {
            const labelInput = lastPromptContainer.querySelector('.guided-prompt-label');
            if (labelInput) {
              labelInput.value = prompt.label || '';
              labelInput.dispatchEvent(new Event('input'));
              labelInput.dispatchEvent(new Event('blur'));
            }
            const typeSelect = lastPromptContainer.querySelector('.guided-prompt-type');
            if (typeSelect && prompt.type) {
              typeSelect.value = prompt.type;
              typeSelect.dispatchEvent(new Event('change'));
            }
            const unitSelect = lastPromptContainer.querySelector('.guided-prompt-unit');
            if (unitSelect && prompt.unit) unitSelect.value = prompt.unit;
            const requiredSelect = lastPromptContainer.querySelector('.guided-prompt-required');
            if (requiredSelect) requiredSelect.value = prompt.required !== false ? 'true' : 'false';
            const optionsInput = lastPromptContainer.querySelector('.guided-prompt-options');
            if (optionsInput) optionsInput.value = normalisePromptOptions(prompt.options).join('\n');
            const labelDisplay = lastPromptContainer.querySelector('.guided-prompt-label-display');
            const titleSpan = lastPromptContainer.querySelector('.guided-prompt-title');
            if (labelDisplay && titleSpan && prompt.label) {
              labelDisplay.textContent = prompt.label;
              labelDisplay.style.display = 'inline';
              titleSpan.style.display = 'none';
            }
          }
        }
      }
    }
    syncStep4ModeSegments();
    updateStep4SummaryBar();
  }
  
  // Save draft to database
  window.saveDraft = async function() {
    if (isProcessFlowSpaPage() && typeof window.persistSpaWizardState === 'function') {
      window.persistSpaWizardState();
    }
    const stepName = document.getElementById('guided-step-name')?.value.trim() || '';
    const stepDescription = document.getElementById('guided-step-description')?.value.trim() || '';
    
    // Get process ID from URL
    const urlParams = new URLSearchParams(window.location.search);
    let processId = urlParams.get('id');
    if (!processId) {
      try {
        const snap = loadWizardSessionMergeBase();
        if (snap && snap.processId) processId = snap.processId;
      } catch (e) {}
    }
    
    try {
      // If no process ID, create a new draft process
      if (!processId) {
        // Create a draft process with a temporary name
        const processName = stepName || 'Untitled Process';
        const newProcess = await CoreAPI.createProcess({
          name: processName,
          description: stepDescription || '',
          is_draft: true
        });
        processId = newProcess.id;
        
        // Update URL to include the new process ID
        const newUrl = new URL(window.location);
        newUrl.searchParams.set('id', processId);
        window.history.replaceState({}, '', newUrl);
      } else {
        // Mark existing process as draft
        await CoreAPI.updateProcess(processId, { is_draft: true });
      }
      
      // If user chose "Start New", overwrite old draft: remove existing steps before saving
      if (isStartNewOverwriteDraft && startNewOldStepIds.length > 0) {
        for (const stepId of startNewOldStepIds) {
          try {
            await CoreAPI.deleteStep(processId, stepId);
          } catch (err) {
            console.warn('Could not delete old draft step:', stepId, err);
          }
        }
        startNewOldStepIds = [];
        isStartNewOverwriteDraft = false;
      }
      
      // Collect current form data
      const inputs = collectCurrentInputs();
      const outputs = collectCurrentOutputs();
      const prompts = collectCurrentPrompts();
      
      // If we have a step name and form data, save the current step as a draft
      if (stepName && (inputs.length > 0 || outputs.length > 0 || prompts.length > 0)) {
        // Calculate step number (after possible deletion of old steps)
        let stepCount = createdSteps.length + 1;
        try {
          const processData = await CoreAPI.getProcess(processId);
          if (processData && processData.steps) {
            stepCount = processData.steps.length + 1;
          }
        } catch (err) {
          console.warn('Could not fetch process data to determine step count:', err);
        }
        
        const currentStepData = {
          step_number: stepCount,
          name: stepName,
          description: stepDescription,
          inputs: inputs || [],
          outputs: outputs || [],
          execution_prompts: prompts || []
        };
        
        // Create the step
        await CoreAPI.createStep(processId, currentStepData);
      }
      
      // Show success notification and close modal
      if (window.showNotification) {
        window.showNotification(
          'success',
          'Draft Saved',
          'Your progress has been saved as a draft. You can resume later from any device.'
        );
      }
      
      // Close modal
      closeModal();
      
      // Reload process data to show draft status
      if (window.loadProcessData) {
        await window.loadProcessData();
      }
    } catch (error) {
      console.error('Error saving draft:', error);
      const errorMessage = error.message || 'Unknown error';
      if (window.showNotification) {
        window.showNotification(
          'error',
          'Failed to Save Draft',
          `Failed to save draft: ${errorMessage}`
        );
      } else {
        alert('Failed to save draft: ' + errorMessage);
      }
    }
  };
  
  // Single unified list: all inputs visible from both tabs; type stored on each card (data-input-type) for DB
  
  // All input rows from the unified list (order preserved)
  
  // Collect current inputs from form (from both tabs); include requires_inventory_selection so draft restore puts them in the correct tab
  
  // Collect current outputs from form
  
  // Collect current prompts from form
  
  // Show resume draft confirmation modal (returns a promise)
  function showResumeDraftModal() {
    return new Promise((resolve) => {
      // Store the resolve function globally so buttons can call it
      window._resumeDraftResolve = resolve;
      
      // Show the modal
      const modal = document.getElementById('resume-draft-confirmation-modal');
      if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
      }
    });
  }
  
  // Confirm resume draft
  window.confirmResumeDraft = function() {
    // Hide the modal
    const modal = document.getElementById('resume-draft-confirmation-modal');
    if (modal) {
      modal.style.display = 'none';
    }
    document.body.style.overflow = 'auto';
    
    // Resolve the promise with true
    if (window._resumeDraftResolve) {
      window._resumeDraftResolve(true);
      window._resumeDraftResolve = null;
    }
  };
  
  // Cancel resume draft (user chose "Start New" — we will overwrite old draft on save/finish)
  window.cancelResumeDraft = function() {
    window._userChoseStartNew = true;
    const modal = document.getElementById('resume-draft-confirmation-modal');
    if (modal) {
      modal.style.display = 'none';
    }
    document.body.style.overflow = 'auto';
    
    if (window._resumeDraftResolve) {
      window._resumeDraftResolve(false);
      window._resumeDraftResolve = null;
    }
  };
  
  // Check for and load draft from database
  async function loadDraft() {
    const urlParams = new URLSearchParams(window.location.search);
    const processId = urlParams.get('id');
    
    console.log('loadDraft called, processId:', processId);
    
    if (!processId) {
      console.log('No processId, returning false');
      return false;
    }
    
    try {
      // Get process data
      const processData = await CoreAPI.getProcess(processId);
      
      console.log('Process data loaded:', processData?.is_draft, 'steps:', processData?.steps?.length);
      
      if (!processData || !processData.is_draft) {
        console.log('Not a draft or no process data, returning false');
        return false;
      }
      
      // Show resume prompt using modal (returns a promise)
      const resume = await showResumeDraftModal();
      
      console.log('User chose to resume:', resume);
      
      if (!resume) {
        return false;
      }
      
      // Set flag IMMEDIATELY after user confirms
      isRestoringDraft = true;
      console.log('Set isRestoringDraft = true');
      
      // Update modal title if editing
      const modalTitle = document.getElementById('modal-title');
      const modalDescription = document.getElementById('modal-description');
      if (modalTitle) {
        modalTitle.textContent = 'Edit Process - Add Step';
      }
      if (modalDescription) {
        modalDescription.textContent = '';
      }
      
      // Flag is already set above, but ensure it's still true
      console.log('About to restore steps, isRestoringDraft:', isRestoringDraft);
      
      // Load existing steps
      if (processData.steps && processData.steps.length > 0) {
        // Convert steps to createdSteps format
        const allSteps = processData.steps.map(step => ({
          id: step.id,
          step_number: step.step_number,
          name: step.name,
          description: step.description,
          inputs: step.inputs || [],
          outputs: step.outputs || [],
          execution_prompts: step.execution_prompts || [],
          updated_at: step.updated_at
        }));
        
        // Store all steps for summaries (excluding the one we'll restore for editing)
        // We'll restore the most recent step into the form, so don't include it in summaries yet
        const stepsForSummaries = allSteps.slice(0, -1); // All except the last one
        createdSteps = stepsForSummaries;
        
        // Show step summaries (for steps other than the one being edited)
        if (stepsForSummaries.length > 0) {
          await updateStepSummaries();
        }
        
        // Restore the most recent step's data into the form for editing
        const mostRecentStep = allSteps[allSteps.length - 1];
        if (mostRecentStep) {
          // Clear form and lists first so we don't append to leftover DOM (fixes duplicate inputs/steps on resume)
          resetForm(true);
          editingStepId = mostRecentStep.id;
          await restoreStepIntoForm(mostRecentStep);
          
          // Navigate to the appropriate step based on what data exists
          // Determine which step to show based on what was filled in
          let targetStep = 1;
          if (mostRecentStep.inputs && mostRecentStep.inputs.length > 0) {
            targetStep = 2; // Go to inputs step
          } else if (mostRecentStep.outputs && mostRecentStep.outputs.length > 0) {
            targetStep = 3; // Go to outputs step
          } else if (mostRecentStep.execution_prompts && mostRecentStep.execution_prompts.length > 0) {
            targetStep = 4; // Go to prompts step
          }
          
          console.log('Draft restoration complete, setting currentStep to:', targetStep, 'isRestoringDraft:', isRestoringDraft);
          
          // Set currentStep immediately (don't wait for animation frames)
          currentStep = targetStep;
          console.log('Immediately set currentStep to:', currentStep);
          
          // Update display immediately (don't wait for animation frames)
          updateStepDisplay();
          console.log('Called updateStepDisplay immediately after setting currentStep');
          
          // Also update display after all restoration is complete (double-check)
          // Use multiple animation frames to ensure modal is fully rendered
          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              // Set the step again to ensure it wasn't reset (use closure variable)
              const stepToShow = targetStep;
              currentStep = stepToShow;
              console.log('In requestAnimationFrame, setting currentStep to:', currentStep, 'before updateStepDisplay');
              updateStepDisplay();
              console.log('Step display updated, currentStep:', currentStep);
              
              // Double-check that the correct step is visible
              const stepDiv = document.getElementById(`create-process-step-${currentStep}`);
              if (stepDiv) {
        console.log('Step display style:', { step: currentStep, display: stepDiv.style.display });
                if (stepDiv.style.display !== 'block') {
                  console.warn(`Step ${currentStep} is not visible, forcing display`);
                  stepDiv.style.display = 'block';
                }
              }
              
              // Also hide step 1 explicitly to prevent it from showing
              const step1Div = document.getElementById('create-process-step-1');
              if (step1Div && currentStep !== 1) {
                step1Div.style.display = 'none';
                console.log('Explicitly hid step 1');
              }
              
              // Clear restoration flag AFTER display is updated
              isRestoringDraft = false;
              console.log('Cleared isRestoringDraft flag');
            });
          });
        }
      }
      
      // Only clear restoration flag if we didn't restore a step (no steps to restore)
      if (!processData.steps || processData.steps.length === 0) {
        isRestoringDraft = false;
      }
      
      return true;
    } catch (error) {
      console.error('Error loading draft:', error);
      return false;
    }
  }
  
  // Open the create process modal
  window.openCreateProcessModal = async function() {
    const modal = document.getElementById('create-process-modal');
    if (modal) {
      modal.style.display = 'flex';
      document.body.style.overflow = 'hidden';
      
      // Clear inventory cache to get fresh data
      inventoryCache = null;
      selectedInventoryItems.clear();
      
      // Reset restoration flag before loading
      isRestoringDraft = false;
      console.log('openCreateProcessModal: Reset isRestoringDraft to false');
      
      // Try to load draft from database
      const draftLoaded = await loadDraft();
      
      console.log('openCreateProcessModal: draftLoaded =', draftLoaded, 'isRestoringDraft =', isRestoringDraft);
      
      if (!draftLoaded) {
        // Check if we're editing a non-draft process with existing steps — show steps list with Edit / Add new step
        const urlParams = new URLSearchParams(window.location.search);
        const processIdForEdit = urlParams.get('id');
        if (processIdForEdit) {
          try {
            const processData = await CoreAPI.getProcess(processIdForEdit);
            if (processData && !processData.is_draft && processData.steps && processData.steps.length > 0) {
              // Load existing steps into createdSteps and show the "existing steps" view
              createdSteps = processData.steps.map(step => ({
                id: step.id,
                step_number: step.step_number,
                name: step.name,
                description: step.description,
                inputs: step.inputs || [],
                outputs: step.outputs || [],
                execution_prompts: step.execution_prompts || [],
                updated_at: step.updated_at
              }));
              isEditingExistingProcess = true;
              showExistingStepsView();
              const modalTitle = document.getElementById('modal-title');
              const modalDescription = document.getElementById('modal-description');
              if (modalTitle) modalTitle.textContent = 'Edit Process';
              if (modalDescription) modalDescription.textContent = 'Edit an existing step or add a new one.';
              return;
            }
          } catch (err) {
            console.warn('Could not load process for edit view:', err);
          }
        }
        // If user chose "Start New" on resume draft, remember existing step IDs so we overwrite them on save/finish
        if (window._userChoseStartNew && processIdForEdit) {
          try {
            const processData = await CoreAPI.getProcess(processIdForEdit);
            if (processData && processData.steps && processData.steps.length > 0) {
              startNewOldStepIds = processData.steps.map(s => s.id);
              isStartNewOverwriteDraft = true;
            }
          } catch (err) {
            console.warn('Could not fetch process steps for Start New overwrite:', err);
          }
          window._userChoseStartNew = false;
        }
        // Only reset if we're not restoring a draft
        if (!isRestoringDraft) {
          console.log('openCreateProcessModal: No draft loaded and not restoring, resetting to step 1');
          currentStep = 1;
          guidedInputs = [];
          guidedOutputs = [];
          updateStepDisplay();
          resetForm();
        } else {
          console.log('openCreateProcessModal: No draft loaded but isRestoringDraft is true, skipping reset');
        }
        
        // Reset modal title
        const modalTitle = document.getElementById('modal-title');
        const modalDescription = document.getElementById('modal-description');
        if (modalTitle) {
          modalTitle.textContent = 'Create Process Step';
        }
        if (modalDescription) {
          modalDescription.textContent = '';
        }
      } else {
        // If draft loaded, loadDraft() already set currentStep to the appropriate step
        // and will call updateStepDisplay() after restoration completes
        // We don't need to do anything here - just wait for loadDraft() to finish
        // The step will be set and displayed by loadDraft()
        // DO NOT call updateStepDisplay() or resetForm() here as it will override loadDraft()
        console.log('Draft loaded, waiting for loadDraft() to set step and update display');
      }
    }
  };
  
  // Close modal and refresh process steps in parent page so new/saved steps appear without reload
  function closeModal() {
    const modal = document.getElementById('create-process-modal');
    if (modal) {
      modal.style.display = 'none';
      document.body.style.overflow = 'auto';
      isEditingExistingProcess = false;
      isStartNewOverwriteDraft = false;
      startNewOldStepIds = [];
    }
    if (typeof window.loadProcessData === 'function') {
      window.loadProcessData();
    } else if (typeof window.loadSteps === 'function') {
      window.loadSteps();
    }
  }
  
  // Hide the "Save as draft or discard?" confirmation modal
  function hideSaveDraftOrDiscardModal() {
    const confirmModal = document.getElementById('save-draft-or-discard-modal');
    if (confirmModal) {
      confirmModal.style.display = 'none';
    }
  }
  
  // Show "Save as draft or discard?" when user clicks Cancel or X (instead of closing immediately)
  function requestCloseCreateProcessModal() {
    const confirmModal = document.getElementById('save-draft-or-discard-modal');
    if (confirmModal) {
      confirmModal.style.display = 'flex';
      document.body.style.overflow = 'hidden';
    }
  }
  
  // Reset form (but keep created steps)
  function resetForm(keepSteps = false) {
    const gsn = document.getElementById('guided-step-name');
    if (gsn) gsn.value = '';
    const gsd = document.getElementById('guided-step-description');
    if (gsd) gsd.value = '';
    const unifiedList = document.getElementById('guided-inputs-list-unified');
    if (unifiedList) unifiedList.innerHTML = '';
    const gOut = document.getElementById('guided-outputs-list');
    if (gOut) gOut.innerHTML = '';
    const gPrompts = document.getElementById('guided-prompts-list');
    if (gPrompts) gPrompts.innerHTML = '';
    const batchNumberMode = document.getElementById('guided-prompt-batch-number-mode');
    if (batchNumberMode) batchNumberMode.value = 'optional';
    const evidenceMode = document.getElementById('guided-prompt-evidence-mode');
    if (evidenceMode) evidenceMode.value = 'optional';
    if (typeof syncStep4ModeSegments === 'function') syncStep4ModeSegments();
    if (typeof updateStep4SummaryBar === 'function') updateStep4SummaryBar();
    guidedInputs = [];
    guidedOutputs = [];
    guidedPrompts = [];
    selectedInventoryItems.clear();
    selectedPreviousOutputs.clear();

    // Reset button text to initial state
    updateInputButtonsText();
    updateOutputButtonText();
    
    // Hide post-creation options
    const postCreationOptions = document.getElementById('post-creation-options');
    if (postCreationOptions) {
      postCreationOptions.style.display = 'none';
    }

    const guidedDocFile = document.getElementById('guided-doc-file');
    if (guidedDocFile) guidedDocFile.value = '';
    setPendingGuidedDocFileUpload(null);
    const guidedDocTitle = document.getElementById('guided-doc-inline-title');
    const guidedDocContent = document.getElementById('guided-doc-inline-content');
    if (guidedDocTitle) guidedDocTitle.value = '';
    if (guidedDocContent) guidedDocContent.value = '';
    if (typeof syncDocInlineDisabledState === 'function') syncDocInlineDisabledState();
    
    // Reset to step 1 (unless we're restoring a draft)
    if (!isRestoringDraft) {
      currentStep = 1;
      updateStepDisplay();
    }
    
    // Clear created steps if not keeping them
    if (!keepSteps) {
      createdSteps = [];
      editingStepId = null;
      isEditingExistingProcess = false;
      const summariesContainer = document.getElementById('step-summaries-container');
      if (summariesContainer) {
        summariesContainer.style.display = 'none';
      }
      const summariesList = document.getElementById('step-summaries-list');
      if (summariesList) {
        summariesList.innerHTML = '';
      }
    }
  }
  
  // Show the "existing steps" view when editing a non-draft process (list steps with Edit + Add new step)
  const showExistingStepsView = window.ProcessModalExistingSteps.create({
    getCreatedSteps: function() { return createdSteps; }
  });

  // Update step display
  const updateStepDisplay = window.ProcessModalNavigation.createStepDisplayUpdater({
    getCurrentStep: function() { return currentStep; },
    isRestoringDraft: function() { return isRestoringDraft; },
    getEditingStepId: function() { return editingStepId; },
    totalSteps,
    updateInputButtonsText,
    updateOutputButtonText,
    loadAttachedStepDocs,
    ensureDocFileListener,
    syncDocInlineDisabledState,
    syncStep4ModeSegments,
    updateStep4SummaryBar
  });
  window.updateStepDisplay = updateStepDisplay;











  // Expose for SPA page so it can sync step display without opening the modal
  window.updateStepDisplay = updateStepDisplay;



  const { validateInventoryInputs, validateFixedExpiryWarning } = window.ProcessModalValidation;

  const processModalNavigationActions = window.ProcessModalNavigationActions.create({
    getCurrentStep: function() { return currentStep; },
    setCurrentStep: function(step) { currentStep = step; },
    totalSteps,
    validateInventoryInputs,
    validateFixedExpiryWarning,
    toggleOutputExpand,
    isProcessFlowSpaPage,
    updateStepDisplay
  });
  window.goFromProcessOverviewToStepName = processModalNavigationActions.goFromProcessOverviewToStepName;
  window.createProcessNextStep = processModalNavigationActions.createProcessNextStep;
  window.createProcessPreviousStep = processModalNavigationActions.createProcessPreviousStep;
  // Unit groups (matching flows2.html)
  const unitGroups = {
    weight: ['kg', 'g'],
    volume: ['L', 'mL'],
    count: ['pcs', 'units']
  };
  
  // Load inventory items (all types)
  let inventoryCache = null;
  // Get previous step outputs for current step
  function getPreviousStepOutputs() {
    const previousOutputs = [];
    
    // Get outputs from all previously created steps
    // createdSteps contains steps that have been created in this session
    // Sort by step_number to ensure correct order
    const sortedSteps = [...createdSteps].sort((a, b) => (a.step_number || 0) - (b.step_number || 0));
    
    sortedSteps.forEach(step => {
      if (step.outputs && step.outputs.length > 0) {
        step.outputs.forEach(output => {
          if (output.name) {
            // Ensure step_number is valid (should be from step.step_number)
            const stepNumber = step.step_number || 0;
            previousOutputs.push({
              id: output.id || null,
              name: output.name,
              quantity: output.quantity !== null && output.quantity !== undefined ? output.quantity : null,
              unit: output.unit || '',
              inventory_type: output.inventory_type || null,
              step_number: stepNumber,
              is_previous_output: true,
              displayName: `Step ${stepNumber}: ${output.name}`
            });
          }
        });
      }
    });
    
    console.log('getPreviousStepOutputs: found', previousOutputs.length, 'outputs from', sortedSteps.length, 'steps');
    console.log('Step numbers:', sortedSteps.map(s => s.step_number));
    
    return previousOutputs;
  }
  
  async function loadInventoryItems() {
    if (inventoryCache) {
      return inventoryCache;
    }
    
    try {
      // Load all inventory types - collect from multiple sources
      let items = [];
      // Get process ID from URL params (same way as flows2.html)
      const urlParams = new URLSearchParams(window.location.search);
      const processId = urlParams.get('id') || null;
      
      console.log('Loading inventory items, processId:', processId);
      
      // This is a name/unit/type picker -- view=compact drops the per-item enrichment
      // (system findings, producing-step hydration, audit history), ~10x smaller.
      // 1. Process-scoped items first (surfaces outputs of earlier steps in this workflow).
      if (processId) {
        try {
          const inventoryData = await CoreAPI.getInventory(null, processId, { compact: true });
          const processItems = inventoryData.inventory_items || [];
          items.push(...processItems);
        } catch (err) {
          console.warn('Failed to load inventory with processId:', err);
        }
      }

      // 2. All inventory (already includes raw materials; the dedupe below handles overlap).
      try {
        const allInventoryData = await CoreAPI.getInventory(null, null, { compact: true });
        const allItems = allInventoryData.inventory_items || [];
        items.push(...allItems);
      } catch (err) {
        console.warn('Failed to load all inventory:', err);
      }
      
      // Get unique inventory items by name and category (preserve category info)
      // Group by category first, then deduplicate within each category
      const categorizedItems = {
        raw_material: [],
        work_in_progress: [],
        final_product: []
      };
      const seenNamesByCategory = {
        raw_material: new Set(),
        work_in_progress: new Set(),
        final_product: new Set()
      };
      
      items.forEach(item => {
        if (item && item.name) {
          // Determine category - default to raw_material if not specified
          const category = item.inventory_type || 'raw_material';
          const categoryKey = category === 'work_in_progress' ? 'work_in_progress' : 
                             category === 'final_product' ? 'final_product' : 
                             'raw_material';
          
          // Only add if we haven't seen this name in this category; preserve full item (supplier, process_name, extra_data)
          if (!seenNamesByCategory[categoryKey].has(item.name)) {
            seenNamesByCategory[categoryKey].add(item.name);
            categorizedItems[categoryKey].push({
              ...item,
              name: item.name,
              unit: item.unit || '',
              category: categoryKey
            });
          }
        }
      });
      
      // Return categorized items
      console.log('Total inventory items by category:', {
        raw_material: categorizedItems.raw_material.length,
        work_in_progress: categorizedItems.work_in_progress.length,
        final_product: categorizedItems.final_product.length
      });
      
      inventoryCache = categorizedItems;
      return categorizedItems;
    } catch (error) {
      console.error('Failed to load inventory items:', error);
      console.error('Error details:', error.message, error.stack);
      // Return empty categorized structure on error
      return {
        raw_material: [],
        work_in_progress: [],
        final_product: []
      };
    }
  }
  
  // Create searchable dropdown for inventory with category grouping
  function createInventorySearchableDropdown(categorizedItems, onSelect, container, placeholderText = null) {
    const uniqueId = `guided-dropdown-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const dropdownContainer = document.createElement('div');
    dropdownContainer.className = 'searchable-dropdown-container';
    dropdownContainer.style.position = 'relative';
    dropdownContainer.style.width = '100%';
    
    // Determine placeholder based on whether we have previous outputs only or inventory items
    let placeholder = placeholderText;
    if (!placeholder) {
      const hasPreviousOutputs = categorizedItems.previous_outputs && categorizedItems.previous_outputs.length > 0;
      const hasInventory = (categorizedItems.raw_material?.length || 0) + 
                          (categorizedItems.work_in_progress?.length || 0) + 
                          (categorizedItems.final_product?.length || 0) > 0;
      if (hasPreviousOutputs && !hasInventory) {
        placeholder = 'Search previous step outputs...';
      } else {
        placeholder = 'Search inventory items...';
      }
    }
    
    // nosemgrep: innerhtml-template-literal -- audited: all dynamic values here go through escapeHtml()
    dropdownContainer.innerHTML = `
      <input
        type="text"
        class="form-input guided-input-name searchable-dropdown-input"
        placeholder="${escapeHtml(placeholder)}"
        autocomplete="off"
        style="width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 13px;"
        data-dropdown-id="${uniqueId}"
      />
      <div 
        class="searchable-dropdown-list" 
        id="${uniqueId}"
        style="display: none; position: absolute; top: 100%; left: 0; right: 0; z-index: 1000; max-height: 300px; overflow-y: auto; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); margin-top: 4px; box-shadow: var(--shadow-lg, 0 8px 24px rgba(0, 0, 0, 0.12));"
      ></div>
    `;
    
    const input = dropdownContainer.querySelector('.searchable-dropdown-input');
    const dropdown = dropdownContainer.querySelector('.searchable-dropdown-list');
    let filteredItems = [];
    let selectedIndex = -1;
    
    // Flatten categorized items into a single array for easier filtering
    function flattenItems(categorized) {
      const allItems = [];
      if (categorized.raw_material) {
        allItems.push(...categorized.raw_material);
      }
      if (categorized.work_in_progress) {
        allItems.push(...categorized.work_in_progress);
      }
      if (categorized.final_product) {
        allItems.push(...categorized.final_product);
      }
      if (categorized.previous_outputs) {
        allItems.push(...categorized.previous_outputs);
      }
      return allItems;
    }
    
    // Get all items as flat array
    const allItems = flattenItems(categorizedItems);
    
    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }
    
    function getAvailableItems() {
      // Filter out already selected items (except the one currently selected in this input)
      return allItems.filter(item => {
        const isSelected = selectedInventoryItems.has(item.name);
        const isCurrentSelection = input.value.trim() === item.name;
        return !isSelected || isCurrentSelection;
      });
    }
    
    // Group items by category
    function groupByCategory(items) {
      const grouped = {
        raw_material: [],
        work_in_progress: [],
        final_product: [],
        previous_outputs: []
      };
      items.forEach(item => {
        const category = item.category || 'raw_material';
        if (grouped[category]) {
          grouped[category].push(item);
        }
      });
      return grouped;
    }
    
    // Initialize filteredItems
    filteredItems = getAvailableItems();
    
    function renderDropdown() {
      const availableItems = getAvailableItems();
      
      if (availableItems.length === 0) {
        dropdown.innerHTML = '<div style="padding: 12px; color: var(--text-secondary); text-align: center; font-size: 13px;">No items available (all items may already be selected)</div>';
        dropdown.style.display = 'block';
        return;
      }
      
      // Apply search filter if there's a search term
      let itemsToShow = availableItems;
      const searchTerm = input.value.trim().toLowerCase();
      if (searchTerm) {
        itemsToShow = availableItems.filter(item => item.name.toLowerCase().includes(searchTerm));
      }
      
      // Group filtered items by category
      const grouped = groupByCategory(itemsToShow);
      
      // Category labels
      const categoryLabels = {
        raw_material: 'Raw Materials',
        work_in_progress: 'Intermediate',
        final_product: 'Final Products',
        previous_outputs: 'Previous Step Outputs'
      };
      
      // Category order - previous outputs first so they're easy to find
      const categoryOrder = ['previous_outputs', 'raw_material', 'work_in_progress', 'final_product'];
      
      // Build flat array in the same order as rendering (for index mapping)
      const flatItemsForIndex = [];
      categoryOrder.forEach(category => {
        const categoryItems = grouped[category] || [];
        flatItemsForIndex.push(...categoryItems);
      });
      
      // Store flat items for click/keyboard handlers
      filteredItems = flatItemsForIndex;
      
      let html = '';
      let itemIndex = 0;
      
      categoryOrder.forEach(category => {
        const categoryItems = grouped[category] || [];
        if (categoryItems.length > 0) {
          // Category header
          html += `
            <div style="padding: 8px 12px; background: var(--bg-secondary, #f9fafb); border-bottom: 1px solid var(--border-default); font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; position: sticky; top: 0; z-index: 10;">
              ${escapeHtml(categoryLabels[category])}
            </div>
          `;
          
          // Category items
          categoryItems.forEach(item => {
            const isSelected = itemIndex === selectedIndex;
            // Use displayName if available (for previous outputs), otherwise use name
            const displayText = item.displayName || item.name;
            html += `
              <div 
                class="dropdown-item ${isSelected ? 'selected' : ''}"
                data-index="${itemIndex}"
                data-category="${category}"
                style="padding: 10px 12px 10px 24px; cursor: pointer; border-bottom: 1px solid var(--border-light); transition: background 0.15s; ${isSelected ? 'background: var(--bg-hover, rgba(0, 0, 0, 0.05));' : ''}"
                onmouseover="this.style.background='var(--bg-hover, rgba(0, 0, 0, 0.05))'"
                onmouseout="if (!this.classList.contains('selected')) this.style.background='transparent'"
              >
                <div style="font-weight: 500; color: var(--text-primary); font-size: 13px;">${escapeHtml(displayText)}</div>
                ${item.is_previous_output ? `<div style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">From previous step</div>` : ''}
              </div>
            `;
            itemIndex++;
          });
        }
      });
      
      dropdown.innerHTML = html;
      dropdown.style.display = 'block';
    }
    
    function filterItems(searchTerm) {
      selectedIndex = -1;
      renderDropdown(); // renderDropdown handles filtering internally
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
      // Use the actual name (not displayName) for the input value
      input.value = item.name;
      // Mark this item as selected
      selectedInventoryItems.add(item.name);
      dropdown.style.display = 'none';
    }
    
    // Get flat array of all filtered items for selection (matches renderDropdown order)
    function getFilteredItemsFlat() {
      return filteredItems; // filteredItems is set by renderDropdown in the correct order
    }
    
    input.addEventListener('input', (e) => {
      filterItems(e.target.value);
    });
    
    input.addEventListener('focus', () => {
      // Re-filter to exclude newly selected items
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
        const flatItems = getFilteredItemsFlat();
        if (flatItems[index]) {
          const itemToSelect = flatItems[index];
          selectItem(itemToSelect);
        }
      }
    });
    
    // Keyboard navigation
    input.addEventListener('keydown', (e) => {
      const flatItems = getFilteredItemsFlat();
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIndex = Math.min(selectedIndex + 1, flatItems.length - 1);
        renderDropdown();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIndex = Math.max(selectedIndex - 1, -1);
        renderDropdown();
      } else if (e.key === 'Enter' && selectedIndex >= 0 && flatItems[selectedIndex]) {
        e.preventDefault();
        const itemToSelect = flatItems[selectedIndex];
        selectItem(itemToSelect);
      }
    });
    
    return dropdownContainer;
  }
  
  // Collapse all inputs except the specified one
  
  // Collapse all outputs except the specified one
  
  // Toggle input expand/collapse
  
  // Toggle output expand/collapse
  
  // Populate a guided input container from saved step data (used when loading a step or when adding in parallel with load data).
  async function populateGuidedInputFromLoadData(container, data, type) {
    if (!container || !data || !data.name) return;
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

  // Add guided input (startCollapsed: when true, input row starts collapsed; preSelectedItem: when set, item is pre-selected; loadInputData: when set, populate and return container without appending)
  window.addGuidedInput = async function(type, startCollapsed, preSelectedItem, loadInputData) {
    // Collapse all existing inputs before adding a new one
    collapseAllInputs();
    
    const inputId = `guided-input-${Date.now()}`;
    const inputContainer = document.createElement('div');
    inputContainer.id = inputId;
    inputContainer.dataset.inputType = type; // inventory | new | previous_output — for DB and collectCurrentInputs
    inputContainer.dataset.expanded = startCollapsed ? 'false' : 'true';
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
    expandIcon.style.cssText = 'transition: transform 0.2s; transform: ' + (startCollapsed ? 'rotate(0deg)' : 'rotate(180deg)') + ';';
    expandIcon.innerHTML = '<polyline points="6 9 12 15 18 9"></polyline>';
    headerLeft.appendChild(expandIcon);
    
    const titleSpan = document.createElement('span');
    titleSpan.className = 'guided-input-title';
    titleSpan.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary);';
    if (type === 'inventory') {
      titleSpan.textContent = 'Inventory Input';
    } else if (type === 'previous_output') {
      titleSpan.textContent = 'Previous Output Input';
    } else {
      titleSpan.textContent = 'New Input';
    }
    headerLeft.appendChild(titleSpan);
    
    // Add name display that will show when collapsed (replaces title when name is entered)
    const nameDisplay = document.createElement('span');
    nameDisplay.className = 'guided-input-name-display';
    nameDisplay.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary); display: none;';
    nameDisplay.textContent = '';
    headerLeft.appendChild(nameDisplay);
    
    // Add expand/collapse hint text
    const expandHint = document.createElement('span');
    expandHint.className = 'guided-input-expand-hint';
    expandHint.style.cssText = 'font-size: 11px; color: var(--text-tertiary, #9ca3af); margin-left: 8px; font-style: italic;';
    expandHint.textContent = startCollapsed ? '(click to expand)' : '(click to collapse)';
    headerLeft.appendChild(expandHint);
    
    // Function to update name display
    const updateNameDisplay = () => {
      let name = '';
      if (type === 'inventory' || type === 'previous_output') {
        const nameInput = inputContainer.querySelector('.guided-input-name.searchable-dropdown-input');
        if (nameInput) {
          name = nameInput.value.trim();
        }
      } else {
        const nameInput = inputContainer.querySelector('.guided-input-name:not(.searchable-dropdown-input)');
        if (nameInput) {
          name = nameInput.value.trim();
        }
      }
      
      if (name) {
        nameDisplay.textContent = name;
        nameDisplay.style.display = 'inline';
        titleSpan.style.display = 'none';
      } else {
        nameDisplay.style.display = 'none';
        titleSpan.style.display = 'inline';
      }
    };
    
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
    contentArea.style.cssText = 'padding: 12px; display: ' + (startCollapsed ? 'none' : 'block') + ';';
    
    if (type === 'inventory' || type === 'previous_output') {
      // Pre-selected previous step output (from "Outputs from previous steps" tab): show quantity, unit only; no execution type
      if (type === 'previous_output' && preSelectedItem && preSelectedItem.name) {
        const displayName = preSelectedItem.displayName || ('Step ' + (preSelectedItem.step_number || '') + ': ' + preSelectedItem.name);
        selectedPreviousOutputs.add(displayName);
        inputContainer.dataset.previousOutputDisplayName = displayName;
        nameDisplay.textContent = preSelectedItem.name;
        nameDisplay.style.display = 'inline';
        titleSpan.style.display = 'none';
        const hiddenName = document.createElement('input');
        hiddenName.type = 'hidden';
        hiddenName.className = 'guided-input-name searchable-dropdown-input';
        hiddenName.value = preSelectedItem.name;
        contentArea.appendChild(hiddenName);
        const quantityField = document.createElement('div');
        quantityField.style.marginBottom = '12px';
        const quantityLabel = document.createElement('label');
        quantityLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
        quantityLabel.innerHTML = 'Quantity <span style="color: var(--error, #ef4444);">*</span>';
        quantityField.appendChild(quantityLabel);
        const quantityInput = document.createElement('input');
        quantityInput.type = 'number';
        quantityInput.className = 'guided-input-quantity';
        quantityInput.placeholder = 'e.g. 1';
        quantityInput.step = '0.01';
        quantityInput.min = '0.01';
        quantityInput.required = true;
        quantityInput.setAttribute('data-inventory-required', 'true');
        quantityInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
        if (preSelectedItem.quantity != null && preSelectedItem.quantity !== '') quantityInput.value = preSelectedItem.quantity;
        quantityField.appendChild(quantityInput);
        contentArea.appendChild(quantityField);
        const unitField = document.createElement('div');
        unitField.style.marginBottom = '12px';
        const unitLabel = document.createElement('label');
        unitLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
        unitLabel.innerHTML = 'Unit <span style="color: var(--error, #ef4444);">*</span>';
        unitField.appendChild(unitLabel);
        const unitSelect = document.createElement('select');
        unitSelect.className = 'guided-input-unit form-select';
        unitSelect.required = true;
        unitSelect.setAttribute('data-inventory-required', 'true');
        unitSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
        const emptyUnitOption = document.createElement('option');
        emptyUnitOption.value = '';
        emptyUnitOption.textContent = 'Select unit';
        unitSelect.appendChild(emptyUnitOption);
        [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
          const option = document.createElement('option');
          option.value = unit;
          option.textContent = unit;
          unitSelect.appendChild(option);
        });
        if (preSelectedItem.unit) unitSelect.value = preSelectedItem.unit;
        unitField.appendChild(unitSelect);
        contentArea.appendChild(unitField);
        inputContainer.appendChild(contentArea);
        const listEl = getGuidedInputListElement(type);
        if (listEl) listEl.appendChild(inputContainer);
        updateInputButtonsText();
        if (typeof window.renderPreviousOutputsList === 'function') window.renderPreviousOutputsList();
        return;
      }
      // Pre-selected item (e.g. from inventory cards): show quantity, unit + hidden execution (variable); no execution dropdown
      if (type === 'inventory' && preSelectedItem && preSelectedItem.name) {
        nameDisplay.textContent = preSelectedItem.name;
        nameDisplay.style.display = 'inline';
        titleSpan.style.display = 'none';
        selectedInventoryItems.add(preSelectedItem.name);
        const preCat = preSelectedItem.inventory_type || preSelectedItem.category;
        if (preCat === 'raw_material' || preCat === 'work_in_progress' || preCat === 'final_product') {
          inputContainer.dataset.expectedInventoryType = preCat;
        }

        const hiddenName = document.createElement('input');
        hiddenName.type = 'hidden';
        hiddenName.className = 'guided-input-name searchable-dropdown-input';
        hiddenName.value = preSelectedItem.name;
        contentArea.appendChild(hiddenName);
        
        const quantityField = document.createElement('div');
        quantityField.style.marginBottom = '12px';
        const quantityLabel = document.createElement('label');
        quantityLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
        quantityLabel.innerHTML = 'Quantity <span style="color: var(--error, #ef4444);">*</span>';
        quantityField.appendChild(quantityLabel);
        const quantityInput = document.createElement('input');
        quantityInput.type = 'number';
        quantityInput.className = 'guided-input-quantity';
        quantityInput.placeholder = 'e.g. 1';
        quantityInput.step = '0.01';
        quantityInput.min = '0.01';
        quantityInput.required = true;
        quantityInput.setAttribute('data-inventory-required', 'true');
        quantityInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
        if (preSelectedItem.quantity != null && preSelectedItem.quantity !== '') {
          quantityInput.value = preSelectedItem.quantity;
        }
        quantityField.appendChild(quantityInput);
        contentArea.appendChild(quantityField);
        
        const unitField = document.createElement('div');
        unitField.style.marginBottom = '12px';
        const unitLabel = document.createElement('label');
        unitLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
        unitLabel.innerHTML = 'Unit <span style="color: var(--error, #ef4444);">*</span>';
        unitField.appendChild(unitLabel);
        const unitSelect = document.createElement('select');
        unitSelect.className = 'guided-input-unit form-select';
        unitSelect.required = true;
        unitSelect.setAttribute('data-inventory-required', 'true');
        unitSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
        const emptyUnitOption = document.createElement('option');
        emptyUnitOption.value = '';
        emptyUnitOption.textContent = 'Select unit';
        unitSelect.appendChild(emptyUnitOption);
        [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
          const option = document.createElement('option');
          option.value = unit;
          option.textContent = unit;
          unitSelect.appendChild(option);
        });
        if (preSelectedItem.unit) unitSelect.value = preSelectedItem.unit;
        unitField.appendChild(unitSelect);
        contentArea.appendChild(unitField);
        
        const typeField = document.createElement('div');
        const hiddenType = document.createElement('input');
        hiddenType.type = 'hidden';
        hiddenType.className = 'guided-input-execution-type';
        hiddenType.value = 'variable';
        typeField.appendChild(hiddenType);
        const explanationDiv = document.createElement('div');
        explanationDiv.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); font-size: 12px; color: var(--text-secondary); line-height: 1.4;';
        explanationDiv.id = `guided-input-explanation-${inputId}`;
        explanationDiv.textContent = inventoryExecutionHelperText(preSelectedItem);
        typeField.appendChild(explanationDiv);
        contentArea.appendChild(typeField);
        
        inputContainer.appendChild(contentArea);
        const listEl = getGuidedInputListElement(type);
        if (listEl) listEl.appendChild(inputContainer);
        updateInputButtonsText();
        return;
      }
      
      // For 'previous_output' type, only show previous outputs
      // For 'inventory' type, show inventory items (but not previous outputs)
      let allCategorizedItems;
      
      if (type === 'previous_output') {
        // Only get previous step outputs
        const previousOutputs = getPreviousStepOutputs();
        
        if (previousOutputs.length === 0) {
          const messageDiv = document.createElement('div');
          messageDiv.style.cssText = 'padding: 12px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); color: var(--text-secondary); font-size: 13px;';
          messageDiv.textContent = 'No previous step outputs available. Create a step with outputs first.';
          contentArea.appendChild(messageDiv);
          inputContainer.appendChild(contentArea);
          const listEl = getGuidedInputListElement(type);
          if (listEl) listEl.appendChild(inputContainer);
          return;
        }
        
        allCategorizedItems = {
          raw_material: [],
          work_in_progress: [],
          final_product: [],
          previous_outputs: previousOutputs.map(output => ({
            name: output.name,
            unit: output.unit || '',
            category: 'previous_outputs',
            displayName: output.displayName || output.name,
            is_previous_output: true,
            step_number: output.step_number,
            quantity: output.quantity,
            inventory_type: output.inventory_type || null
          }))
        };
      } else {
        // Load inventory items (now returns categorized object)
        const categorizedItems = await loadInventoryItems();
        allCategorizedItems = {
          ...categorizedItems,
          previous_outputs: [] // Don't include previous outputs in inventory dropdown
        };
        
        // Check if we have any items at all
        const totalItems = (allCategorizedItems.raw_material?.length || 0) + 
                          (allCategorizedItems.work_in_progress?.length || 0) + 
                          (allCategorizedItems.final_product?.length || 0);
        
        if (totalItems === 0) {
          // Show a message if no inventory items are available
          const messageDiv = document.createElement('div');
          messageDiv.style.cssText = 'padding: 12px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); color: var(--text-secondary); font-size: 13px;';
          messageDiv.textContent = 'No inventory items available. Please add inventory items first.';
          contentArea.appendChild(messageDiv);
          inputContainer.appendChild(contentArea);
          const listEl = getGuidedInputListElement(type);
          if (listEl) listEl.appendChild(inputContainer);
          return;
        }
      }
      
      // Name field with searchable dropdown
      const nameField = document.createElement('div');
      nameField.style.marginBottom = '12px';
      const nameLabel = document.createElement('label');
      nameLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      nameLabel.textContent = type === 'previous_output' ? 'Previous Step Output' : 'Inventory Item';
      nameField.appendChild(nameLabel);
      
      // Filter out already selected items from each category
      const filteredCategorized = {
        raw_material: (allCategorizedItems.raw_material || []).filter(item => !selectedInventoryItems.has(item.name)),
        work_in_progress: (allCategorizedItems.work_in_progress || []).filter(item => !selectedInventoryItems.has(item.name)),
        final_product: (allCategorizedItems.final_product || []).filter(item => !selectedInventoryItems.has(item.name)),
        previous_outputs: (allCategorizedItems.previous_outputs || []).filter(item => !selectedPreviousOutputs.has(item.displayName || item.name))
      };
      
      const nameDropdown = createInventorySearchableDropdown(
        filteredCategorized,
        (item) => {
          // When item is selected, update unit if available
          const unitSelect = inputContainer.querySelector('.guided-input-unit');
          if (unitSelect && item.unit) {
            unitSelect.value = item.unit;
          }
          // If it's a previous output, also auto-fill quantity
          if (item.is_previous_output && item.quantity !== null && item.quantity !== undefined) {
            const quantityInput = inputContainer.querySelector('.guided-input-quantity');
            if (quantityInput) {
              quantityInput.value = item.quantity;
            }
          }
          // Mark this item as selected (use the actual name, not displayName)
          if (item.is_previous_output) {
            const displayName = item.displayName || item.name;
            selectedPreviousOutputs.add(displayName);
            inputContainer.dataset.previousOutputDisplayName = displayName;
            if (item.id) inputContainer.dataset.sourceOutputId = item.id;
            // Previous outputs carry an explicit type (intermediate/final) from the output definition.
            if (item.inventory_type === 'work_in_progress' || item.inventory_type === 'final_product') {
              inputContainer.dataset.expectedInventoryType = item.inventory_type;
              if (typeof inputContainer._applyExpectedTypeUI === 'function') {
                inputContainer._applyExpectedTypeUI();
              }
            } else if (type === 'previous_output') {
              // Default previous outputs to Intermediate when not specified.
              inputContainer.dataset.expectedInventoryType = 'work_in_progress';
              if (typeof inputContainer._applyExpectedTypeUI === 'function') {
                inputContainer._applyExpectedTypeUI();
              }
            }
          } else {
            selectedInventoryItems.add(item.name);
            if (type === 'inventory' && item.category && item.category !== 'previous_outputs') {
              inputContainer.dataset.expectedInventoryType = item.category;
              if (typeof inputContainer._applyExpectedTypeUI === 'function') {
                inputContainer._applyExpectedTypeUI();
              }
            }
          }
          // Update the dropdown to exclude this item from other inputs
          updateInventoryDropdowns();
          // Update name display in header directly with the item name (not displayName)
          if (item.name) {
            nameDisplay.textContent = item.name;
            nameDisplay.style.display = 'inline';
            titleSpan.style.display = 'none';
          }
          if (type === 'inventory') {
            const explanation = document.getElementById('guided-input-explanation-' + inputId);
            if (explanation) explanation.textContent = inventoryExecutionHelperText(item);
          }
        },
        inputContainer,
        type === 'previous_output' ? 'Search previous step outputs...' : null
      );
      nameField.appendChild(nameDropdown);
      contentArea.appendChild(nameField);

      // Inventory type hint (raw / intermediate / final) persisted on the step input.
      // Needed so execution can default the correct picker tab even when inventory is missing.
      if (type === 'inventory') {
        const typeField = document.createElement('div');
        typeField.style.marginBottom = '12px';
        const typeLabel = document.createElement('label');
        typeLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 6px;';
        typeLabel.textContent = 'Inventory type';
        typeField.appendChild(typeLabel);

        const seg = document.createElement('div');
        seg.className = 'flow-mode-segmented';
        seg.setAttribute('role', 'group');
        seg.setAttribute('aria-label', 'Inventory type');
        seg.style.marginBottom = '0';

        function normalizeInvCat(v) {
          v = String(v || '').toLowerCase().trim();
          if (v === 'intermediate' || v === 'wip') return 'work_in_progress';
          if (v === 'final') return 'final_product';
          if (!v) return 'raw_material';
          return v;
        }

        function applyExpectedTypeUI() {
          const current = normalizeInvCat(inputContainer.dataset.expectedInventoryType || 'raw_material');
          seg.querySelectorAll('.flow-mode-segment[data-inventory-cat]').forEach(function(btn) {
            const on = btn.getAttribute('data-inventory-cat') === current;
            btn.classList.toggle('flow-mode-segment--active', !!on);
            btn.setAttribute('aria-pressed', on ? 'true' : 'false');
          });
        }

        [
          { key: 'raw_material', label: 'Raw materials' },
          { key: 'work_in_progress', label: 'Intermediate' },
          { key: 'final_product', label: 'Final products' }
        ].forEach(function(opt) {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'flow-mode-segment';
          btn.setAttribute('data-inventory-cat', opt.key);
          btn.setAttribute('aria-pressed', 'false');
          btn.textContent = opt.label;
          btn.addEventListener('click', function() {
            inputContainer.dataset.expectedInventoryType = opt.key;
            applyExpectedTypeUI();
          });
          seg.appendChild(btn);
        });

        typeField.appendChild(seg);
        contentArea.appendChild(typeField);
        inputContainer._applyExpectedTypeUI = applyExpectedTypeUI;
        applyExpectedTypeUI();
      }
      
      // Listen for changes to the name input
      const nameInput = nameDropdown.querySelector('.searchable-dropdown-input');
      if (nameInput) {
        nameInput.addEventListener('input', updateNameDisplay);
        nameInput.addEventListener('blur', updateNameDisplay);
      }
      
      // Quantity field (required for inventory items)
      const quantityField = document.createElement('div');
      quantityField.style.marginBottom = '12px';
      const quantityLabel = document.createElement('label');
      quantityLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      quantityLabel.innerHTML = 'Quantity <span style="color: var(--error, #ef4444);">*</span>';
      quantityField.appendChild(quantityLabel);
      const quantityInput = document.createElement('input');
      quantityInput.type = 'number';
      quantityInput.className = 'guided-input-quantity';
      quantityInput.placeholder = 'e.g. 1';
      quantityInput.step = '0.01';
      quantityInput.min = '0.01';
      quantityInput.required = true;
      quantityInput.setAttribute('data-inventory-required', 'true');
      quantityInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
      quantityField.appendChild(quantityInput);
      contentArea.appendChild(quantityField);
      
      // Unit dropdown (required for inventory items)
      const unitField = document.createElement('div');
      unitField.style.marginBottom = '12px';
      const unitLabel = document.createElement('label');
      unitLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      unitLabel.innerHTML = 'Unit <span style="color: var(--error, #ef4444);">*</span>';
      unitField.appendChild(unitLabel);
      const unitSelect = document.createElement('select');
      unitSelect.className = 'guided-input-unit form-select';
      unitSelect.required = true;
      unitSelect.setAttribute('data-inventory-required', 'true');
      unitSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
      const emptyUnitOption = document.createElement('option');
      emptyUnitOption.value = '';
      emptyUnitOption.textContent = 'Select unit';
      unitSelect.appendChild(emptyUnitOption);
      [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
        const option = document.createElement('option');
        option.value = unit;
        option.textContent = unit;
        unitSelect.appendChild(option);
      });
      unitField.appendChild(unitSelect);
      contentArea.appendChild(unitField);
      
      // Inventory: always select from stock at execution (same as raw materials); no execution-type dropdown.
      if (type === 'inventory') {
        const typeField = document.createElement('div');
        const hiddenType = document.createElement('input');
        hiddenType.type = 'hidden';
        hiddenType.className = 'guided-input-execution-type';
        hiddenType.value = 'variable';
        typeField.appendChild(hiddenType);
        const explanationDiv = document.createElement('div');
        explanationDiv.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); font-size: 12px; color: var(--text-secondary); line-height: 1.4;';
        explanationDiv.id = `guided-input-explanation-${inputId}`;
        explanationDiv.textContent = inventoryExecutionHelperText(null);
        typeField.appendChild(explanationDiv);
        contentArea.appendChild(typeField);
      }
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
      nameInput.addEventListener('input', updateNameDisplay);
      nameInput.addEventListener('blur', updateNameDisplay);
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
      quantityInput.className = 'guided-input-quantity';
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
      unitSelect.className = 'guided-input-unit form-select';
      unitSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
      [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
        const option = document.createElement('option');
        option.value = unit;
        option.textContent = unit;
        unitSelect.appendChild(option);
      });
      unitField.appendChild(unitSelect);
      contentArea.appendChild(unitField);
      
      const typeField = buildNewMaterialExecutionTypeField(inputId);
      contentArea.appendChild(typeField);
    }
    
    inputContainer.appendChild(contentArea);
    if (type === 'new') syncGuidedNewInputExecutionSegments(inputContainer);
    const listEl = getGuidedInputListElement(type);
    if (loadInputData) {
      await populateGuidedInputFromLoadData(inputContainer, loadInputData, type);
      return inputContainer;
    }
    if (listEl) listEl.appendChild(inputContainer);
    updateInputButtonsText();
  };
  
  function updateInputsStickySummaryBar() {
    const countEl = document.getElementById('guided-inputs-sticky-count');
    const clearBtn = document.getElementById('guided-inputs-sticky-clear');
    if (!countEl) return;
    const n = getAllGuidedInputElements().length;
    countEl.textContent = n === 1 ? '1 input' : n + ' inputs';
    if (clearBtn) {
      clearBtn.disabled = n === 0;
      clearBtn.setAttribute('aria-disabled', n === 0 ? 'true' : 'false');
    }
  }

  window.clearAllGuidedInputs = function() {
    const ids = getAllGuidedInputElements().map(function(el) { return el.id; }).filter(Boolean);
    ids.forEach(function(id) { window.removeGuidedInput(id); });
    selectedInventoryItems.clear();
    selectedPreviousOutputs.clear();
    updateInputButtonsText();
    if (typeof window.renderInventoryItemCards === 'function') window.renderInventoryItemCards();
    if (typeof window.renderPreviousOutputsList === 'function') window.renderPreviousOutputsList();
  };

  // Update input button text based on number of inputs in unified list
  function updateInputButtonsText() {
    const unifiedList = document.getElementById('guided-inputs-list-unified');
    const totalCount = unifiedList ? unifiedList.querySelectorAll(':scope > div').length : 0;
    const label = totalCount > 0 ? '+ Add another' : '+ Add input';
    
    const inventoryBtnText = document.getElementById('add-another-inventory-text');
    const newBtnText = document.getElementById('add-another-new-text');
    if (inventoryBtnText) inventoryBtnText.textContent = label;
    if (newBtnText) newBtnText.textContent = label;
    updateInputsStickySummaryBar();
  }
  
  // Summary under item name. Raw: none (user selects at execution). Intermediate/final: process name, unit.
  // Inventory category (Raw / Intermediate / Final): same flow-mode-segmented control as outputs expiry / Ready date
  window.applyGuidedInventoryCategoryUI = function() {
    const cat = window._guidedInventoryCat || 'raw_material';
    document.querySelectorAll('#guided-inventory-category-tabs .flow-mode-segment[data-inventory-cat]').forEach(function(btn) {
      const on = btn.getAttribute('data-inventory-cat') === cat;
      btn.classList.toggle('flow-mode-segment--active', !!on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    document.querySelectorAll('#guided-inventory-cards-container .guided-inventory-cat-panel').forEach(function(el) {
      el.style.display = el.getAttribute('data-inventory-cat') === cat ? '' : 'none';
    });
  };

  // Render inventory cards by category (one visible panel at a time); each card expandable with full metadata.
  window.renderInventoryItemCards = async function() {
    const container = document.getElementById('guided-inventory-cards-container');
    const catTabsWrap = document.getElementById('guided-inventory-category-tabs');
    if (!container) return;
    container.innerHTML = '';
    if (catTabsWrap) catTabsWrap.style.display = 'none';

    const categorized = await loadInventoryItems();
    const sections = [
      { key: 'raw_material', items: categorized.raw_material || [] },
      { key: 'work_in_progress', items: categorized.work_in_progress || [] },
      { key: 'final_product', items: categorized.final_product || [] }
    ];

    const availableByKey = { raw_material: 0, work_in_progress: 0, final_product: 0 };
    let totalAvailable = 0;
    sections.forEach(function(sec) {
      const available = (sec.items || []).filter(function(item) { return item && item.name && !selectedInventoryItems.has(item.name); });
      availableByKey[sec.key] = available.length;
      totalAvailable += available.length;
    });

    const totalItems = (categorized.raw_material || []).length + (categorized.work_in_progress || []).length + (categorized.final_product || []).length;
    if (totalAvailable === 0) {
      const msg = document.createElement('p');
      msg.style.cssText = 'font-size: 13px; color: var(--text-secondary); margin: 0; padding: 8px 0;';
      msg.textContent = totalItems === 0
        ? 'No inventory items available. Add inventory items first.'
        : 'All available items have been added. Expand an input above to edit.';
      container.appendChild(msg);
      return;
    }

    if (catTabsWrap) catTabsWrap.style.display = '';

    const order = ['raw_material', 'work_in_progress', 'final_product'];
    let resolvedCat = window._guidedInventoryCat;
    if (!resolvedCat || availableByKey[resolvedCat] === 0) {
      resolvedCat = null;
      for (let i = 0; i < order.length; i++) {
        if (availableByKey[order[i]] > 0) {
          resolvedCat = order[i];
          break;
        }
      }
      if (!resolvedCat) resolvedCat = 'raw_material';
    }
    window._guidedInventoryCat = resolvedCat;

    function emptyCategoryMessage(secKey, totalInCat, availLen) {
      const p = document.createElement('p');
      p.style.cssText = 'font-size: 13px; color: var(--text-secondary); margin: 0; padding: 8px 0;';
      if (totalInCat === 0) {
        if (secKey === 'raw_material') p.textContent = 'No raw materials in inventory yet.';
        else if (secKey === 'work_in_progress') p.textContent = 'No intermediate items in inventory yet.';
        else p.textContent = 'No final products in inventory yet.';
      } else if (availLen === 0) {
        p.textContent = 'All items in this category have been added.';
      }
      return p;
    }

    function buildInventoryCard(item) {
      const card = document.createElement('div');
      card.className = 'guided-inventory-card';
      const summary = inventoryCardSummary(item);
      const metaHtml = inventoryCardMetadataHtml(item);

      const headerRow = document.createElement('div');
      headerRow.className = 'card-header-row';
      // audited: item.name goes through escapeHtmlForText(); summary is pre-escaped by
      // inventoryCardSummary() then additionally quote-escaped for the title attribute context
      // nosemgrep: innerhtml-string-concat
      headerRow.innerHTML =
        '<div class="card-header-text">' +
          '<span class="card-name">' + escapeHtmlForText(item.name) + '</span>' +
          (summary ? '<span class="card-summary" title="' + summary.replace(/"/g, '&quot;') + '">' + summary + '</span>' : '') +
        '</div>' +
        '<button type="button" class="card-expand-btn" aria-label="Toggle details"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg></button>';

      const metaBlock = document.createElement('div');
      metaBlock.className = 'card-meta-block';
      metaBlock.style.display = 'none';
      const metaContent = document.createElement('div');
      metaContent.innerHTML = metaHtml;
      metaBlock.appendChild(metaContent);

      const addFooter = document.createElement('div');
      addFooter.className = 'card-add-footer';
      const openBtn = document.createElement('button');
      openBtn.type = 'button';
      openBtn.className = 'card-add-btn btn btn-primary btn-sm';
      openBtn.textContent = 'Add as input';

      const inlineWrap = document.createElement('div');
      inlineWrap.className = 'guided-inv-inline-add';
      inlineWrap.style.cssText = 'display: none; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-light, #eee);';
      const qtyLab = document.createElement('label');
      qtyLab.style.cssText = 'display:block;font-size:12px;color:var(--text-secondary);margin-bottom:4px;';
      qtyLab.innerHTML = 'Quantity <span style="color:var(--error,#ef4444)">*</span>';
      const qtyIn = document.createElement('input');
      qtyIn.type = 'number';
      qtyIn.step = '0.01';
      qtyIn.min = '0.01';
      qtyIn.placeholder = 'e.g. 1';
      qtyIn.style.cssText = 'width:100%;padding:8px 12px;border-radius:var(--radius-md);border:1px solid var(--border-default);font-size:13px;margin-bottom:10px;box-sizing:border-box;';
      const unitLab = document.createElement('label');
      unitLab.style.cssText = 'display:block;font-size:12px;color:var(--text-secondary);margin-bottom:4px;';
      unitLab.innerHTML = 'Unit <span style="color:var(--error,#ef4444)">*</span>';
      const unitSel = document.createElement('select');
      unitSel.className = 'form-select';
      unitSel.style.cssText = 'width:100%;padding:8px 12px;border-radius:var(--radius-md);border:1px solid var(--border-default);background:var(--bg-card);font-size:13px;margin-bottom:10px;box-sizing:border-box;';
      const emptyU = document.createElement('option');
      emptyU.value = '';
      emptyU.textContent = 'Select unit';
      unitSel.appendChild(emptyU);
      [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(function(unit) {
        const o = document.createElement('option');
        o.value = unit;
        o.textContent = unit;
        unitSel.appendChild(o);
      });
      if (item.unit) unitSel.value = item.unit;

      const confirmBtn = document.createElement('button');
      confirmBtn.type = 'button';
      confirmBtn.className = 'btn btn-primary btn-sm';
      confirmBtn.style.cssText = 'width:100%;margin-top:4px;';
      confirmBtn.textContent = 'Click to add';

      inlineWrap.appendChild(qtyLab);
      inlineWrap.appendChild(qtyIn);
      inlineWrap.appendChild(unitLab);
      inlineWrap.appendChild(unitSel);
      inlineWrap.appendChild(confirmBtn);

      openBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        openBtn.style.display = 'none';
        inlineWrap.style.display = 'block';
      });
      confirmBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        const q = parseFloat(qtyIn.value, 10);
        const u = unitSel.value;
        if (!q || q <= 0 || isNaN(q)) {
          if (window.showNotification) window.showNotification('error', 'Quantity required', 'Enter a positive quantity.');
          else alert('Enter a positive quantity.');
          return;
        }
        if (!u) {
          if (window.showNotification) window.showNotification('error', 'Unit required', 'Select a unit.');
          else alert('Select a unit.');
          return;
        }
        (async function() {
          await window.addGuidedInput('inventory', true, Object.assign({}, item, { quantity: q, unit: u, executionType: 'variable' }));
          window.renderInventoryItemCards();
          updateInputButtonsText();
          const unified = document.getElementById('guided-inputs-list-unified');
          if (unified && unified.firstElementChild) {
            unified.firstElementChild.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        })();
      });

      addFooter.appendChild(openBtn);
      addFooter.appendChild(inlineWrap);
      metaBlock.appendChild(addFooter);

      const expandBtn = headerRow.querySelector('.card-expand-btn');

      function toggleExpand() {
        const open = card.classList.toggle('expanded');
        metaBlock.style.display = open ? 'block' : 'none';
      }
      headerRow.addEventListener('click', function(e) {
        if (e.target.closest('.card-expand-btn')) return;
        toggleExpand();
      });
      expandBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        toggleExpand();
      });

      card.appendChild(headerRow);
      card.appendChild(metaBlock);
      return card;
    }

    sections.forEach(function(sec) {
      const available = (sec.items || []).filter(function(item) { return item && item.name && !selectedInventoryItems.has(item.name); });
      const totalInCat = (sec.items || []).filter(function(item) { return item && item.name; }).length;

      const panel = document.createElement('div');
      panel.className = 'guided-inventory-cat-panel';
      panel.setAttribute('data-inventory-cat', sec.key);

      if (available.length === 0) {
        panel.appendChild(emptyCategoryMessage(sec.key, totalInCat, available.length));
      } else {
        available.forEach(function(item) {
          panel.appendChild(buildInventoryCard(item));
        });
      }
      container.appendChild(panel);
    });

    if (typeof window.applyGuidedInventoryCategoryUI === 'function') window.applyGuidedInventoryCategoryUI();
  };
  
  // Render list of previous step outputs in "Outputs from previous steps" tab; click to add as input.
  window.renderPreviousOutputsList = function() {
    const container = document.getElementById('guided-previous-outputs-container');
    if (!container) return;
    container.innerHTML = '';
    const outputs = getPreviousStepOutputs();
    const available = outputs.filter(function(item) {
      const displayName = item.displayName || ('Step ' + (item.step_number || '') + ': ' + item.name);
      return !selectedPreviousOutputs.has(displayName);
    });
    if (available.length === 0) {
      const msg = document.createElement('p');
      msg.style.cssText = 'font-size: 13px; color: var(--text-secondary); margin: 0; padding: 8px 0;';
      msg.textContent = outputs.length === 0
        ? 'No previous step outputs available. Create a step with outputs first, then add another step.'
        : 'All available outputs have been added. Expand an input above to edit.';
      container.appendChild(msg);
      return;
    }
    available.forEach(function(item) {
      const displayName = item.displayName || ('Step ' + (item.step_number || '') + ': ' + item.name);
      const row = document.createElement('button');
      row.type = 'button';
      row.style.cssText = 'display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; padding: 12px 14px; border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md); background: var(--bg-card, #fff); color: var(--text-primary); font-size: 13px; text-align: left; cursor: pointer; transition: background 0.15s, border-color 0.15s;';
      // nosemgrep: innerhtml-string-concat -- audited: all dynamic values here go through escapeHtmlForText()
      row.innerHTML = '<span style="font-weight: 600;">' + escapeHtmlForText(displayName) + '</span>' +
        (item.unit ? '<span style="font-size: 11px; color: var(--text-tertiary);">' + escapeHtmlForText(item.unit) + '</span>' : '');
      row.onmouseenter = function() { row.style.background = 'var(--bg-secondary, #f9fafb)'; row.style.borderColor = 'var(--primary, #3b82f6)'; };
      row.onmouseleave = function() { row.style.background = 'var(--bg-card, #fff)'; row.style.borderColor = 'var(--border-default, #e5e7eb)'; };
      row.onclick = async function() {
        await window.addGuidedInput('previous_output', false, item);
        window.renderPreviousOutputsList();
        updateInputButtonsText();
      };
      container.appendChild(row);
    });
  };
  
  // Update all inventory dropdowns to exclude selected items
  function updateInventoryDropdowns() {
    const allInputs = getAllGuidedInputElements();
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
      const wasInventory = inputElement.dataset.inputType === 'inventory';
      const wasPreviousOutput = inputElement.dataset.inputType === 'previous_output';
      const nameInput = inputElement.querySelector('.guided-input-name.searchable-dropdown-input');
      if (nameInput && nameInput.value && wasInventory) {
        selectedInventoryItems.delete(nameInput.value.trim());
      }
      if (wasPreviousOutput && inputElement.dataset.previousOutputDisplayName) {
        selectedPreviousOutputs.delete(inputElement.dataset.previousOutputDisplayName);
      }
      inputElement.remove();
      updateInputButtonsText();
      if (wasInventory && typeof window.renderInventoryItemCards === 'function') {
        window.renderInventoryItemCards();
      }
      if (wasPreviousOutput && typeof window.renderPreviousOutputsList === 'function') {
        window.renderPreviousOutputsList();
      }
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
    titleSpan.className = 'guided-output-title';
    titleSpan.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary);';
    titleSpan.textContent = 'Output';
    headerLeft.appendChild(titleSpan);
    
    // Add name display that will show when collapsed (replaces title when name is entered)
    const nameDisplay = document.createElement('span');
    nameDisplay.className = 'guided-output-name-display';
    nameDisplay.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary); display: none;';
    nameDisplay.textContent = '';
    headerLeft.appendChild(nameDisplay);
    
    // Add expand/collapse hint text
    const expandHint = document.createElement('span');
    expandHint.className = 'guided-output-expand-hint';
    expandHint.style.cssText = 'font-size: 11px; color: var(--text-tertiary, #9ca3af); margin-left: 8px; font-style: italic;';
    expandHint.textContent = '(click to collapse)';
    headerLeft.appendChild(expandHint);
    
    // Function to update name display
    const updateNameDisplay = () => {
      const nameInput = outputContainer.querySelector('.guided-output-name');
      const name = nameInput ? nameInput.value.trim() : '';
      
      if (name) {
        nameDisplay.textContent = name;
        nameDisplay.style.display = 'inline';
        titleSpan.style.display = 'none';
      } else {
        nameDisplay.style.display = 'none';
        titleSpan.style.display = 'inline';
      }
    };
    
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
    nameInput.addEventListener('input', updateNameDisplay);
    nameInput.addEventListener('blur', updateNameDisplay);
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

    // Output inventory type (Intermediate / Final). Stored on output JSON so "previous output" inputs can infer the type even when inventory is missing.
    // Defaults to Intermediate to match most workflows.
    outputContainer.dataset.outputInventoryType = outputContainer.dataset.outputInventoryType || 'work_in_progress';
    const outTypePane = document.createElement('div');
    outTypePane.style.cssText = 'position: relative; margin-top: 12px; margin-bottom: 0; padding: 16px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-lg); border: 1px solid var(--border-light, #e5e7eb);';
    const outTypeLabel = document.createElement('label');
    outTypeLabel.style.cssText = 'display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 6px;';
    outTypeLabel.textContent = 'Output type';
    outTypePane.appendChild(outTypeLabel);
    const outTypeDesc = document.createElement('p');
    outTypeDesc.style.cssText = 'font-size: 12px; color: var(--text-secondary); margin: 0 0 10px 0; line-height: 1.45;';
    outTypeDesc.textContent = 'Intermediate outputs can be used in later steps. Final outputs are finished goods.';
    outTypePane.appendChild(outTypeDesc);
    const outTypeSeg = document.createElement('div');
    outTypeSeg.className = 'flow-mode-segmented';
    outTypeSeg.setAttribute('role', 'group');
    outTypeSeg.setAttribute('aria-label', 'Output type');
    function applyOutputTypeUI() {
      const current = String(outputContainer.dataset.outputInventoryType || 'work_in_progress');
      outTypeSeg.querySelectorAll('.flow-mode-segment[data-output-type]').forEach(function(btn) {
        const on = btn.getAttribute('data-output-type') === current;
        btn.classList.toggle('flow-mode-segment--active', !!on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    }
    [
      { key: 'work_in_progress', label: 'Intermediate' },
      { key: 'final_product', label: 'Final product' }
    ].forEach(function(opt) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'flow-mode-segment';
      btn.setAttribute('data-output-type', opt.key);
      btn.setAttribute('aria-pressed', 'false');
      btn.textContent = opt.label;
      btn.addEventListener('click', function() {
        outputContainer.dataset.outputInventoryType = opt.key;
        applyOutputTypeUI();
      });
      outTypeSeg.appendChild(btn);
    });
    outTypePane.appendChild(outTypeSeg);
    contentArea.appendChild(outTypePane);
    applyOutputTypeUI();
    
    // Custom output expiry — sub-pane inside this output (same visual style as Batch number / Evidence on step 4)
    const expiryPane = document.createElement('div');
    expiryPane.className = 'guided-output-expiry-pane';
    expiryPane.style.cssText = 'position: relative; margin-top: 12px; margin-bottom: 0; padding: 16px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-lg); border: 1px solid var(--border-light, #e5e7eb);';
    const expiryLabel = document.createElement('label');
    expiryLabel.style.cssText = 'display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 6px;';
    expiryLabel.textContent = 'Custom output expiry';
    expiryPane.appendChild(expiryLabel);
    const expiryDesc = document.createElement('p');
    expiryDesc.style.cssText = 'font-size: 12px; color: var(--text-secondary); margin: 0 0 10px 0; line-height: 1.45;';
    expiryDesc.textContent = 'Choose a fixed expiry period (e.g. 30 days) or have the operator set expiry when the step runs (duration or specific date/time).';
    expiryPane.appendChild(expiryDesc);
    const EXPIRY_MODES = window.EXPIRY_MODES || { NONE: 'none', FIXED: 'fixed_duration', EXECUTION: 'set_at_execution' };
    const expirySegRow = buildOutputModeSegmentRow('expiry', {
      ariaLabel: 'Custom output expiry mode',
      options: [
        { value: EXPIRY_MODES.NONE, label: 'None' },
        { value: EXPIRY_MODES.FIXED, label: 'Fixed period' },
        { value: EXPIRY_MODES.EXECUTION, label: 'Operator defined' }
      ]
    });
    expiryPane.appendChild(expirySegRow);
    const expiryModeSelect = document.createElement('select');
    expiryModeSelect.className = 'guided-output-expiry-mode flow-mode-select-native';
    expiryModeSelect.setAttribute('aria-hidden', 'true');
    expiryModeSelect.setAttribute('tabindex', '-1');
    const noExpiryOpt = document.createElement('option');
    noExpiryOpt.value = EXPIRY_MODES.NONE;
    noExpiryOpt.textContent = 'No custom expiry — output has no use-by rule';
    expiryModeSelect.appendChild(noExpiryOpt);
    const fixedExpiryOpt = document.createElement('option');
    fixedExpiryOpt.value = EXPIRY_MODES.FIXED;
    fixedExpiryOpt.textContent = 'Fixed expiry period — output must be consumed within X time';
    expiryModeSelect.appendChild(fixedExpiryOpt);
    const execExpiryOpt = document.createElement('option');
    execExpiryOpt.value = EXPIRY_MODES.EXECUTION;
    execExpiryOpt.textContent = 'Operator defined';
    expiryModeSelect.appendChild(execExpiryOpt);
    expiryPane.appendChild(expiryModeSelect);
    const expiryFieldsWrap = document.createElement('div');
    expiryFieldsWrap.className = 'guided-output-expiry-fields';
    expiryFieldsWrap.style.cssText = 'margin-top: 12px; padding: 12px; background: var(--bg-card, #fff); border-radius: var(--radius-md); border: 1px solid var(--border-default); display: none;';
    const timeUnits = [
      { value: 'hours', label: 'Hours' },
      { value: 'days', label: 'Days' },
      { value: 'weeks', label: 'Weeks' },
      { value: 'months', label: 'Months' }
    ];
    const fixedWrap = document.createElement('div');
    fixedWrap.className = 'guided-output-expiry-fixed-fields';
    fixedWrap.style.cssText = 'display: none; margin-bottom: 12px;';
    const expiryDurationLabel = document.createElement('label');
    expiryDurationLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 6px;';
    expiryDurationLabel.textContent = 'Expiry period';
    fixedWrap.appendChild(expiryDurationLabel);
    const expiryDurationRow = document.createElement('div');
    expiryDurationRow.className = 'guided-duration-row';
    const expiryValueInput = document.createElement('input');
    expiryValueInput.type = 'number';
    expiryValueInput.className = 'guided-output-expiry-value guided-duration-value-input';
    expiryValueInput.min = '1';
    expiryValueInput.placeholder = '30';
    expiryValueInput.setAttribute('inputmode', 'numeric');
    expiryValueInput.style.cssText = 'border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
    expiryDurationRow.appendChild(expiryValueInput);
    const expiryUnitSelect = document.createElement('select');
    expiryUnitSelect.className = 'guided-output-expiry-unit form-select guided-duration-unit-select';
    expiryUnitSelect.style.cssText = 'border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
    timeUnits.forEach(u => {
      const opt = document.createElement('option');
      opt.value = u.value;
      opt.textContent = u.label;
      expiryUnitSelect.appendChild(opt);
    });
    expiryUnitSelect.value = 'days';
    expiryDurationRow.appendChild(expiryUnitSelect);
    fixedWrap.appendChild(expiryDurationRow);
    expiryFieldsWrap.appendChild(fixedWrap);
    const execHint = document.createElement('p');
    execHint.className = 'guided-output-expiry-exec-hint';
    execHint.style.cssText = 'display: none; margin: 0 0 12px 0; font-size: 12px; color: var(--text-secondary); line-height: 1.4;';
    execHint.textContent = 'Operator will set expiry when this step runs (duration or specific date/time).';
    expiryFieldsWrap.appendChild(execHint);

    // Warning threshold (fixed_duration only — for set_at_execution we collect warning during execution)
    const warningWrap = document.createElement('div');
    warningWrap.className = 'guided-output-expiry-warning-wrap';
    warningWrap.style.cssText = 'display: none;';

    const warningLabel = document.createElement('label');
    warningLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 6px;';
    warningLabel.textContent = 'Warn before expiry';
    warningWrap.appendChild(warningLabel);

    const warningRow = document.createElement('div');
    warningRow.className = 'guided-duration-row';
    const warningValueInput = document.createElement('input');
    warningValueInput.type = 'number';
    warningValueInput.className = 'guided-output-expiry-warning-value guided-duration-value-input';
    warningValueInput.min = '0';
    warningValueInput.placeholder = '7';
    warningValueInput.setAttribute('inputmode', 'numeric');
    warningValueInput.title = 'Start showing amber warning when this amount of time remains until expiry (e.g. 7 days, 2 days, 12 hours). Must be the same or less than the expiry period.';
    warningValueInput.style.cssText = 'border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
    warningRow.appendChild(warningValueInput);
    const warningUnitSelect = document.createElement('select');
    warningUnitSelect.className = 'guided-output-expiry-warning-unit form-select guided-duration-unit-select';
    warningUnitSelect.style.cssText = 'border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
    timeUnits.forEach(u => {
      const opt = document.createElement('option');
      opt.value = u.value;
      opt.textContent = u.label;
      warningUnitSelect.appendChild(opt);
    });
    warningUnitSelect.value = 'days';
    warningRow.appendChild(warningUnitSelect);
    warningWrap.appendChild(warningRow);
    expiryFieldsWrap.appendChild(warningWrap);
    const expiryWarningError = document.createElement('div');
    expiryWarningError.className = 'guided-output-expiry-warning-error';
    expiryWarningError.style.cssText = 'display: none; margin-top: 8px; font-size: 12px; color: var(--danger, #dc2626); line-height: 1.4;';
    expiryWarningError.setAttribute('role', 'alert');
    expiryWarningError.setAttribute('aria-live', 'polite');
    warningWrap.appendChild(expiryWarningError);
    const validator = window.CustomExpiryValidation;
    function syncExpiryWarningValidation() {
      const mode = expiryModeSelect.value;
      const fixedMode = (window.EXPIRY_MODES && window.EXPIRY_MODES.FIXED) || 'fixed_duration';
      if (mode !== fixedMode) {
        expiryWarningError.style.display = 'none';
        expiryWarningError.textContent = '';
        warningValueInput.style.borderColor = '';
        warningUnitSelect.style.borderColor = '';
        return;
      }
      const expVal = parseInt(expiryValueInput.value, 10);
      const expUnit = (expiryUnitSelect.value || 'days').trim();
      const warnVal = parseInt(warningValueInput.value, 10);
      const warnUnit = (warningUnitSelect.value || 'days').trim();
      const expHours = validator && typeof validator.durationToHours === 'function'
        ? validator.durationToHours(isNaN(expVal) ? null : expVal, expUnit)
        : null;
      const result = validator && typeof validator.validateWarnNotLongerThanExpiry === 'function'
        ? validator.validateWarnNotLongerThanExpiry({
            warnValue: isNaN(warnVal) ? null : warnVal,
            warnUnit: warnUnit,
            expiryHours: expHours,
            expiryLabel: (expVal != null ? expVal : '') + ' ' + expUnit,
          })
        : { valid: true };
      if (!result.valid) {
        expiryWarningError.textContent = result.message || 'Warning period must not exceed expiry period.';
        expiryWarningError.style.display = 'block';
        warningValueInput.style.borderColor = 'var(--danger, #dc2626)';
        warningUnitSelect.style.borderColor = 'var(--danger, #dc2626)';
      } else {
        expiryWarningError.style.display = 'none';
        expiryWarningError.textContent = '';
        warningValueInput.style.borderColor = '';
        warningUnitSelect.style.borderColor = '';
      }
    }
    [expiryValueInput, expiryUnitSelect, warningValueInput, warningUnitSelect].forEach(el => {
      el.addEventListener('input', syncExpiryWarningValidation);
      el.addEventListener('change', syncExpiryWarningValidation);
    });
    expiryModeSelect.addEventListener('change', function () {
      const mode = expiryModeSelect.value;
      const EXP = window.EXPIRY_MODES || { NONE: 'none', FIXED: 'fixed_duration', EXECUTION: 'set_at_execution' };
      expiryFieldsWrap.style.display = mode !== (EXP.NONE || 'none') ? 'block' : 'none';
      fixedWrap.style.display = mode === (EXP.FIXED || 'fixed_duration') ? 'block' : 'none';
      execHint.style.display = mode === (EXP.EXECUTION || 'set_at_execution') ? 'block' : 'none';
      warningWrap.style.display = mode === (EXP.FIXED || 'fixed_duration') ? 'block' : 'none';
      syncExpiryWarningValidation();
      syncOutputExpiryModeSegments(outputContainer);
    });
    expiryPane.appendChild(expiryFieldsWrap);

    // Ready date — sub-pane (same pattern as custom expiry: none | fixed_duration | set_at_execution)
    const READY_DATE_MODES = window.READY_DATE_MODES || { NONE: 'none', FIXED: 'fixed_duration', EXECUTION: 'set_at_execution' };
    const readyDatePane = document.createElement('div');
    readyDatePane.className = 'guided-output-ready-date-pane';
    readyDatePane.style.cssText = 'position: relative; margin-top: 12px; margin-bottom: 0; padding: 16px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-lg); border: 1px solid var(--border-light, #e5e7eb);';
    const readyDateLabel = document.createElement('label');
    readyDateLabel.style.cssText = 'display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 6px;';
    readyDateLabel.textContent = 'Ready date';
    readyDatePane.appendChild(readyDateLabel);
    const readyDateDesc = document.createElement('p');
    readyDateDesc.style.cssText = 'font-size: 12px; color: var(--text-secondary); margin: 0 0 10px 0; line-height: 1.45;';
    readyDateDesc.textContent = 'When can this output be used? No restriction, a fixed period after completion, or set by the operator at execution.';
    readyDatePane.appendChild(readyDateDesc);
    const readyDateSegRow = buildOutputModeSegmentRow('ready_date', {
      ariaLabel: 'Ready date mode',
      options: [
        { value: READY_DATE_MODES.NONE, label: 'None' },
        { value: READY_DATE_MODES.FIXED, label: 'Fixed period' },
        { value: READY_DATE_MODES.EXECUTION, label: 'Operator defined' }
      ]
    });
    readyDatePane.appendChild(readyDateSegRow);
    const readyDateModeSelect = document.createElement('select');
    readyDateModeSelect.className = 'guided-output-ready-date-mode flow-mode-select-native';
    readyDateModeSelect.setAttribute('aria-hidden', 'true');
    readyDateModeSelect.setAttribute('tabindex', '-1');
    const noReadyOpt = document.createElement('option');
    noReadyOpt.value = READY_DATE_MODES.NONE;
    noReadyOpt.textContent = 'No ready date needed — product is available for use immediately';
    readyDateModeSelect.appendChild(noReadyOpt);
    const fixedReadyOpt = document.createElement('option');
    fixedReadyOpt.value = READY_DATE_MODES.FIXED;
    fixedReadyOpt.textContent = 'Fixed ready date — cannot be consumed for a fixed period';
    readyDateModeSelect.appendChild(fixedReadyOpt);
    const execReadyOpt = document.createElement('option');
    execReadyOpt.value = READY_DATE_MODES.EXECUTION;
    execReadyOpt.textContent = 'Operator defined';
    readyDateModeSelect.appendChild(execReadyOpt);
    readyDatePane.appendChild(readyDateModeSelect);
    const readyDateFieldsWrap = document.createElement('div');
    readyDateFieldsWrap.className = 'guided-output-ready-date-fields';
    readyDateFieldsWrap.style.cssText = 'margin-top: 12px; padding: 12px; background: var(--bg-card, #fff); border-radius: var(--radius-md); border: 1px solid var(--border-default); display: none;';
    const readyDateTimeUnits = [
      { value: 'days', label: 'Days' },
      { value: 'weeks', label: 'Weeks' },
      { value: 'months', label: 'Months' },
      { value: 'years', label: 'Years' }
    ];
    const readyDateFixedWrap = document.createElement('div');
    readyDateFixedWrap.className = 'guided-output-ready-date-fixed-fields';
    readyDateFixedWrap.style.cssText = 'display: none; margin-bottom: 12px;';
    const readyDateDurationLabel = document.createElement('label');
    readyDateDurationLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 6px;';
    readyDateDurationLabel.textContent = 'Ready after (period from step completion)';
    readyDateFixedWrap.appendChild(readyDateDurationLabel);
    const readyDateDurationRow = document.createElement('div');
    readyDateDurationRow.className = 'guided-duration-row';
    const readyDateValueInput = document.createElement('input');
    readyDateValueInput.type = 'number';
    readyDateValueInput.className = 'guided-output-ready-date-value guided-duration-value-input';
    readyDateValueInput.min = '1';
    readyDateValueInput.placeholder = '7';
    readyDateValueInput.setAttribute('inputmode', 'numeric');
    readyDateValueInput.style.cssText = 'border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
    readyDateDurationRow.appendChild(readyDateValueInput);
    const readyDateUnitSelect = document.createElement('select');
    readyDateUnitSelect.className = 'guided-output-ready-date-unit form-select guided-duration-unit-select';
    readyDateUnitSelect.style.cssText = 'border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
    readyDateTimeUnits.forEach(u => {
      const opt = document.createElement('option');
      opt.value = u.value;
      opt.textContent = u.label;
      readyDateUnitSelect.appendChild(opt);
    });
    readyDateUnitSelect.value = 'days';
    readyDateDurationRow.appendChild(readyDateUnitSelect);
    readyDateFixedWrap.appendChild(readyDateDurationRow);
    readyDateFieldsWrap.appendChild(readyDateFixedWrap);
    const readyDateExecHint = document.createElement('p');
    readyDateExecHint.className = 'guided-output-ready-date-exec-hint';
    readyDateExecHint.style.cssText = 'display: none; margin: 0 0 12px 0; font-size: 12px; color: var(--text-secondary); line-height: 1.4;';
    readyDateExecHint.textContent = 'Operator will set ready date when this step runs (duration or specific date/time).';
    readyDateFieldsWrap.appendChild(readyDateExecHint);
    const readyDateWarnWrap = document.createElement('div');
    readyDateWarnWrap.className = 'guided-output-ready-date-warning-wrap';
    readyDateWarnWrap.style.cssText = 'display: none;';
    const readyDateWarnLabel = document.createElement('label');
    readyDateWarnLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 6px;';
    readyDateWarnLabel.textContent = 'Warn before ready';
    readyDateWarnLabel.title = 'Alert the user ahead of time that their output will be ready in X period (e.g. 1 day, 1 week). Must be the same or less than the ready period.';
    readyDateWarnWrap.appendChild(readyDateWarnLabel);
    const readyDateWarnRow = document.createElement('div');
    readyDateWarnRow.className = 'guided-duration-row';
    const readyDateWarnValueInput = document.createElement('input');
    readyDateWarnValueInput.type = 'number';
    readyDateWarnValueInput.className = 'guided-output-ready-date-warning-value guided-duration-value-input';
    readyDateWarnValueInput.min = '0';
    readyDateWarnValueInput.placeholder = '1';
    readyDateWarnValueInput.setAttribute('inputmode', 'numeric');
    readyDateWarnValueInput.style.cssText = 'border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
    readyDateWarnRow.appendChild(readyDateWarnValueInput);
    const readyDateWarnUnitSelect = document.createElement('select');
    readyDateWarnUnitSelect.className = 'guided-output-ready-date-warning-unit form-select guided-duration-unit-select';
    readyDateWarnUnitSelect.style.cssText = 'border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
    readyDateTimeUnits.forEach(u => {
      const opt = document.createElement('option');
      opt.value = u.value;
      opt.textContent = u.label;
      readyDateWarnUnitSelect.appendChild(opt);
    });
    readyDateWarnUnitSelect.value = 'days';
    readyDateWarnRow.appendChild(readyDateWarnUnitSelect);
    readyDateWarnWrap.appendChild(readyDateWarnRow);
    readyDateFieldsWrap.appendChild(readyDateWarnWrap);
    const readyDateWarnError = document.createElement('div');
    readyDateWarnError.className = 'guided-output-ready-date-warning-error';
    readyDateWarnError.style.cssText = 'display: none; margin-top: 8px; font-size: 12px; color: var(--danger, #dc2626); line-height: 1.4;';
    readyDateWarnError.setAttribute('role', 'alert');
    readyDateWarnError.setAttribute('aria-live', 'polite');
    readyDateWarnWrap.appendChild(readyDateWarnError);
    const readyDateValidator = window.ReadyDateValidation;
    function syncReadyDateWarnValidation() {
      const mode = readyDateModeSelect.value;
      const fixedMode = READY_DATE_MODES.FIXED || 'fixed_duration';
      if (mode !== fixedMode) {
        readyDateWarnError.style.display = 'none';
        readyDateWarnError.textContent = '';
        readyDateWarnValueInput.style.borderColor = '';
        readyDateWarnUnitSelect.style.borderColor = '';
        return;
      }
      const readyVal = parseInt(readyDateValueInput.value, 10);
      const readyUnit = (readyDateUnitSelect.value || 'days').trim();
      const warnVal = parseInt(readyDateWarnValueInput.value, 10);
      const warnUnit = (readyDateWarnUnitSelect.value || 'days').trim();
      const readyHours = readyDateValidator && typeof readyDateValidator.durationToHours === 'function'
        ? readyDateValidator.durationToHours(isNaN(readyVal) ? null : readyVal, readyUnit)
        : null;
      const result = readyDateValidator && typeof readyDateValidator.validateWarnNotLongerThanReadyPeriod === 'function'
        ? readyDateValidator.validateWarnNotLongerThanReadyPeriod({
            warnValue: isNaN(warnVal) ? null : warnVal,
            warnUnit: warnUnit,
            readyHours: readyHours,
            readyLabel: (readyVal != null ? readyVal : '') + ' ' + readyUnit,
          })
        : { valid: true };
      if (!result.valid) {
        readyDateWarnError.textContent = result.message || 'Warn period must not be longer than the ready period.';
        readyDateWarnError.style.display = 'block';
        readyDateWarnValueInput.style.borderColor = 'var(--danger, #dc2626)';
        readyDateWarnUnitSelect.style.borderColor = 'var(--danger, #dc2626)';
      } else {
        readyDateWarnError.style.display = 'none';
        readyDateWarnError.textContent = '';
        readyDateWarnValueInput.style.borderColor = '';
        readyDateWarnUnitSelect.style.borderColor = '';
      }
    }
    [readyDateValueInput, readyDateUnitSelect, readyDateWarnValueInput, readyDateWarnUnitSelect].forEach(el => {
      el.addEventListener('input', syncReadyDateWarnValidation);
      el.addEventListener('change', syncReadyDateWarnValidation);
    });
    readyDateModeSelect.addEventListener('change', function () {
      const mode = readyDateModeSelect.value;
      readyDateFieldsWrap.style.display = mode !== (READY_DATE_MODES.NONE || 'none') ? 'block' : 'none';
      readyDateFixedWrap.style.display = mode === (READY_DATE_MODES.FIXED || 'fixed_duration') ? 'block' : 'none';
      readyDateExecHint.style.display = mode === (READY_DATE_MODES.EXECUTION || 'set_at_execution') ? 'block' : 'none';
      readyDateWarnWrap.style.display = mode === (READY_DATE_MODES.FIXED || 'fixed_duration') ? 'block' : 'none';
      syncReadyDateWarnValidation();
      syncOutputReadyDateModeSegments(outputContainer);
    });
    readyDatePane.appendChild(readyDateFieldsWrap);
    expiryModeSelect.dispatchEvent(new Event('change', { bubbles: true }));
    readyDateModeSelect.dispatchEvent(new Event('change', { bubbles: true }));

    const complianceWrap = document.createElement('div');
    complianceWrap.className = 'guided-output-compliance-wrap';
    complianceWrap.setAttribute('x-data', '{ advancedOpen: false }');

    const complianceToggle = document.createElement('button');
    complianceToggle.type = 'button';
    complianceToggle.className = 'spa-advanced-toggle';
    complianceToggle.setAttribute('x-on:click', 'advancedOpen = !advancedOpen');
    const compLabel = document.createElement('span');
    compLabel.className = 'spa-advanced-toggle__label spa-form-section-title';
    compLabel.textContent = 'Compliance & Traceability';
    const compTrack = document.createElement('span');
    compTrack.className = 'spa-advanced-toggle__track';
    compTrack.setAttribute(':class', "{ 'spa-advanced-toggle__track--on': advancedOpen }");
    const compThumb = document.createElement('span');
    compThumb.className = 'spa-advanced-toggle__thumb';
    compTrack.appendChild(compThumb);
    complianceToggle.appendChild(compLabel);
    complianceToggle.appendChild(compTrack);
    complianceWrap.appendChild(complianceToggle);

    const complianceInner = document.createElement('div');
    complianceInner.className = 'spa-advanced-fields spa-form-section guided-output-compliance-fields';
    complianceInner.setAttribute('x-show', 'advancedOpen');
    complianceInner.setAttribute('x-cloak', '');
    complianceInner.style.marginTop = '10px';
    complianceInner.appendChild(expiryPane);
    complianceInner.appendChild(readyDatePane);
    complianceWrap.appendChild(complianceInner);

    contentArea.appendChild(complianceWrap);

    setTimeout(function() {
      if (window.Alpine && typeof Alpine.initTree === 'function') {
        Alpine.initTree(complianceWrap);
      }
    }, 0);

    // Inline warning: when both expiry and ready date are fixed duration, expiry must be >= ready (show before Next)
    const expiryReadyErrorEl = document.createElement('div');
    expiryReadyErrorEl.className = 'guided-output-expiry-ready-validation-error';
    expiryReadyErrorEl.style.cssText = 'display: none; margin-top: 12px; padding: 10px 12px; background: hsl(0, 93%, 94%); border: 1px solid var(--error, #ef4444); border-radius: var(--radius-md); color: #b91c1c; font-size: 13px; font-weight: 500; line-height: 1.4;';
    expiryReadyErrorEl.setAttribute('role', 'alert');
    expiryReadyErrorEl.setAttribute('aria-live', 'polite');
    contentArea.appendChild(expiryReadyErrorEl);

    function syncExpiryReadyValidation() {
      expiryReadyErrorEl.style.display = 'none';
      expiryReadyErrorEl.textContent = '';
      expiryPane.style.borderColor = '';
      expiryPane.style.boxShadow = '';
      readyDatePane.style.borderColor = '';
      readyDatePane.style.boxShadow = '';
      const expiryMode = expiryModeSelect.value;
      const readyMode = readyDateModeSelect.value;
      const fixedExpiry = (window.EXPIRY_MODES && window.EXPIRY_MODES.FIXED) || 'fixed_duration';
      const fixedReady = (window.READY_DATE_MODES && window.READY_DATE_MODES.FIXED) || 'fixed_duration';
      if (expiryMode !== fixedExpiry || readyMode !== fixedReady) return;
      const nameEl = outputContainer.querySelector('.guided-output-name');
      const outName = (nameEl && nameEl.value && nameEl.value.trim()) ? nameEl.value.trim() : 'this output';
      const expiryVal = parseInt(expiryValueInput.value, 10);
      const expiryUnit = (expiryUnitSelect.value || 'days').trim();
      const readyVal = parseInt(readyDateValueInput.value, 10);
      const readyUnit = (readyDateUnitSelect.value || 'days').trim();
      if ((!expiryVal || isNaN(expiryVal)) && (!readyVal || isNaN(readyVal))) return;
      const payload = [{
        name: outName,
        extra_data: {
          custom_expiry: { enabled: true, mode: 'fixed_duration', duration_value: expiryVal || 0, duration_unit: expiryUnit },
          ready_date: { enabled: true, mode: 'fixed_duration', duration_value: readyVal || 0, duration_unit: readyUnit }
        }
      }];
      if (window.ExpiryReadyDateValidation && typeof window.ExpiryReadyDateValidation.validateExpiryAfterReadyDuration === 'function') {
        const res = window.ExpiryReadyDateValidation.validateExpiryAfterReadyDuration(payload);
        if (!res.valid) {
          expiryReadyErrorEl.textContent = res.message || 'Expiry must be on or after the ready date.';
          expiryReadyErrorEl.style.display = 'block';
          expiryPane.style.borderColor = 'var(--error, #ef4444)';
          expiryPane.style.boxShadow = '0 0 0 1px var(--error, #ef4444)';
          readyDatePane.style.borderColor = 'var(--error, #ef4444)';
          readyDatePane.style.boxShadow = '0 0 0 1px var(--error, #ef4444)';
        }
      }
    }
    [expiryModeSelect, readyDateModeSelect, expiryValueInput, expiryUnitSelect, readyDateValueInput, readyDateUnitSelect].forEach(function (el) {
      if (el) {
        el.addEventListener('input', syncExpiryReadyValidation);
        el.addEventListener('change', syncExpiryReadyValidation);
      }
    });
    
    outputContainer.appendChild(contentArea);
    document.getElementById('guided-outputs-list').appendChild(outputContainer);
    
    // Update button text after adding output
    updateOutputButtonText();
  };
  
  function updateOutputsStickySummaryBar() {
    const countEl = document.getElementById('guided-outputs-sticky-count');
    const clearBtn = document.getElementById('guided-outputs-sticky-clear');
    if (!countEl) return;
    const n = document.querySelectorAll('#guided-outputs-list > div').length;
    countEl.textContent = n === 1 ? '1 output' : n + ' outputs';
    if (clearBtn) {
      clearBtn.disabled = n === 0;
      clearBtn.setAttribute('aria-disabled', n === 0 ? 'true' : 'false');
    }
  }

  window.clearAllGuidedOutputs = function() {
    const list = document.getElementById('guided-outputs-list');
    if (!list) return;
    list.innerHTML = '';
    updateOutputButtonText();
    if (typeof window.addGuidedOutput === 'function') {
      window.addGuidedOutput();
    }
  };

  // Update output button text based on number of outputs
  function updateOutputButtonText() {
    const outputCount = document.querySelectorAll('#guided-outputs-list > div').length;
    const outputBtn = document.getElementById('add-output-btn');
    
    if (outputBtn) {
      outputBtn.textContent = outputCount > 0 
        ? '+ Add another output' 
        : '+ Add output';
    }
    updateOutputsStickySummaryBar();
  }
  
  // Remove guided output
  window.removeGuidedOutput = function(outputId) {
    const outputElement = document.getElementById(outputId);
    if (outputElement) {
      outputElement.remove();
      
      // Update button text after removing output
      updateOutputButtonText();
    }
  };
  
  const processModalPromptActions = window.ProcessModalPrompts.create({
    unitGroups,
    updateStep4SummaryBar
  });
  window.addGuidedPrompt = processModalPromptActions.addGuidedPrompt;
  window.removeGuidedPrompt = processModalPromptActions.removeGuidedPrompt;



  function hasPendingUnsavedWizardStepForFinish() {
    if (getFlowWizardPageSlug() === 'next-steps') {
      return false;
    }
    if (editingStepId) return false;
    return wizardSessionHasDraftStepData(loadWizardSessionMergeBase());
  }



  async function navigateProcessFlowSpaEvidenceToSummary() {
    if (typeof window.persistSpaWizardState === 'function') window.persistSpaWizardState();
    const session = loadWizardSessionMergeBase();
    if (!session || session.v !== 1) {
      if (window.showNotification) window.showNotification('error', 'Nothing to review', 'Could not read wizard state.');
      return;
    }
    const stepName = (session.stepName || '').trim();
    if (!stepName) {
      if (window.showNotification) {
        window.showNotification('error', 'Step name required', 'Enter a step name on the first page.');
      }
      return;
    }
    const invResult = validateInventoryInputsFromSession(session);
    if (!invResult.valid) {
      if (window.showNotification) window.showNotification('error', 'Inventory inputs required', invResult.message);
      return;
    }
    const outputs = session.outputs || [];
    const expiryValidation = validateFixedExpiryWarning(outputs);
    if (!expiryValidation.valid) {
      if (window.showNotification) window.showNotification('error', 'Invalid expiry settings', expiryValidation.message);
      return;
    }
    window.location.href = '/core/flows/create/summary' + (window.location.search || '');
  }

  async function commitGuidedStepToProcessApiFromSessionSnapshot(session) {
    const stepName = (session.stepName || '').trim();
    const stepDescription = (session.stepDescription || '').trim();
    if (!stepName) throw new Error('Step name required');

    const inputs = mapSessionInputsToApiPayloadFromRows(session.inputs || []);
    const outputs = JSON.parse(JSON.stringify(session.outputs || []));
    const executionPrompts = buildExecutionPromptsForApiFromSession(session);

    const invResult = validateInventoryInputsFromSession(session);
    if (!invResult.valid) throw new Error(invResult.message);

    const expiryValidation = validateFixedExpiryWarning(outputs);
    if (!expiryValidation.valid) throw new Error(expiryValidation.message);

    const batchNumberMode = session.batchNumberMode || 'optional';
    const evidenceMode = session.evidenceMode || 'optional';

    let processId = new URLSearchParams(window.location.search || '').get('id');
    if (!processId && session.processId) processId = session.processId;

    if (!processId) {
      const wfTitle = (session.workflowProcessName || '').trim();
      const newProcess = await CoreAPI.createProcess({
        name: wfTitle || stepName || 'Untitled Process',
        description: stepDescription || '',
        is_draft: true
      });
      processId = (newProcess && (newProcess.id || newProcess.process_id || newProcess.processId)) || null;
      if (!processId) throw new Error('Could not create process (missing id)');
      const newUrl = new URL(window.location.href);
      newUrl.searchParams.set('id', processId);
      window.history.replaceState({}, '', newUrl);
    }

    let stepCount = 1;
    // Match modal draft save: only update an existing row when explicitly editing it (in-memory id).
    // If in-memory id was lost (e.g. id type mismatch), session.editingStepId is safe only when it
    // matches a step that exists in createdSteps — never for a blank "new step" draft.
    let eid =
      editingStepId != null && editingStepId !== '' ? editingStepId : null;
    if (!eid && session && session.editingStepId != null && session.editingStepId !== '') {
      const cand = session.editingStepId;
      if (createdSteps.some(s => String(s.id) === String(cand))) {
        eid = cand;
      }
    }
    const stepBeingEdited = eid ? createdSteps.find(s => String(s.id) === String(eid)) : null;

    if (stepBeingEdited) {
      stepCount = stepBeingEdited.step_number ?? 1;
    } else {
      if (createdSteps.length > 0) {
        stepCount = Math.max(...createdSteps.map(s => s.step_number || 0)) + 1;
      }
      try {
        const processData = await CoreAPI.getProcess(processId);
        if (processData && processData.steps && processData.steps.length > 0) {
          const maxDbStepNumber = Math.max(...processData.steps.map(s => s.step_number || 0));
          stepCount = Math.max(stepCount, maxDbStepNumber + 1);
        }
      } catch (err) {
        console.warn('Could not fetch process data to determine step count:', err);
      }
    }

    const stepData = {
      step_number: stepCount,
      name: stepName,
      description: stepDescription,
      inputs: inputs,
      outputs: outputs,
      execution_prompts: executionPrompts
    };

    const wasEditingStepId = eid;
    let saved;
    if (eid) {
      // If-Match guards against a colleague editing this step while the wizard held it.
      const expectedUpdatedAt = stepBeingEdited && stepBeingEdited.updated_at;
      saved = await CoreAPI.updateStep(processId, eid, stepData, expectedUpdatedAt);
    } else {
      saved = await CoreAPI.createStep(processId, stepData);
    }

    if (!saved || !saved.id) throw new Error('Save failed');

    const savedStepNumber = saved.step_number || stepCount;

    const docInlineTitle = (session.docInlineTitle || '').trim();
    const docInlineContent = (session.docInlineContent || '').trim();
    const hasInline = docInlineTitle && docInlineContent;
    const du = session.docFileUpload;

    if (typeof CoreAPI.uploadProcessDoc === 'function' && typeof CoreAPI.createProcessDocInline === 'function') {
      try {
        if (du && du.base64) {
          const blob = base64ToBlob(du.base64, du.mime || 'application/octet-stream');
          const fd = new FormData();
          fd.append('process_id', processId);
          fd.append('step_id', saved.id);
          fd.append('file', blob, du.fileName || 'document');
          if (docInlineTitle) fd.append('title', docInlineTitle);
          await CoreAPI.uploadProcessDoc(fd);
        } else if (hasInline) {
          await CoreAPI.createProcessDocInline(processId, saved.id, docInlineTitle, docInlineContent);
        }
      } catch (docErr) {
        console.warn('Could not add step documentation:', docErr);
        if (window.showNotification) {
          window.showNotification('warning', 'Step saved', 'Documentation could not be added. ' + (docErr.message || ''));
        }
      }
    }

    const hasFile = !!(du && du.base64);
    const documentation_summary = hasFile ? 'SOP file attached' : hasInline ? 'Instructions: ' + docInlineTitle : undefined;

    const stepSummary = {
      id: saved.id,
      step_number: savedStepNumber,
      name: stepName,
      description: stepDescription,
      inputs: inputs,
      outputs: outputs,
      execution_prompts: executionPrompts,
      documentation_summary: documentation_summary,
      batch_number_mode: batchNumberMode,
      evidence_mode: evidenceMode
    };

    if (wasEditingStepId) {
      const stepIndex = createdSteps.findIndex(s => s.id === wasEditingStepId);
      if (stepIndex !== -1) {
        createdSteps[stepIndex] = stepSummary;
      } else {
        createdSteps.push(stepSummary);
      }
    } else {
      createdSteps.push(stepSummary);
    }

    // After creating a new step, clear editing id so the next wizard round (add another step)
    // does not treat the saved step as "being edited" and overwrite it via updateStep.
    editingStepId = wasEditingStepId ? saved.id : null;
    setPendingGuidedDocFileUpload(null);

    if (isEditingExistingProcess) {
      isEditingExistingProcess = false;
      try {
        const processData = await CoreAPI.getProcess(processId);
        if (processData && processData.steps && processData.steps.length > 0) {
          createdSteps = processData.steps.map(s => ({
            id: s.id,
            step_number: s.step_number,
            name: s.name,
            description: s.description,
            inputs: s.inputs || [],
            outputs: s.outputs || [],
            execution_prompts: s.execution_prompts || [],
            updated_at: s.updated_at
          }));
        }
      } catch (err) {
        console.warn('Could not reload process steps after save:', err);
      }
    }

    return { processId: processId, step: stepSummary };
  }

  // Create step from guided flow — SPA evidence: review only (session). Persist to API via Save step on summary.
  window.createProcessFromGuidedFlow = async function() {
    await navigateProcessFlowSpaEvidenceToSummary();
  };

  window.savePendingStepFromFlowWizard = async function() {
    if (!isProcessFlowSummaryPage()) return;
    if (typeof window.persistSpaWizardState === 'function') window.persistSpaWizardState();
    const session = loadWizardSessionMergeBase();
    if (!session || session.v !== 1) {
      if (window.showNotification) window.showNotification('error', 'Nothing to save', 'No wizard data found.');
      return;
    }
    try {
      const commitResult = await commitGuidedStepToProcessApiFromSessionSnapshot(session);
      persistClearedWizardDraftState();
      if (typeof updateStepSummaries === 'function') await updateStepSummaries();
      // Do not reuse window.location.search here: it can be "?id=" (empty) which causes the
      // server wizard enforcement to bounce the user back to process-overview.
      const pid =
        (commitResult && commitResult.processId) ||
        new URLSearchParams(window.location.search || '').get('id') ||
        (session && session.processId) ||
        '';
      const qs = pid ? ('?id=' + encodeURIComponent(String(pid))) : '';
      window.location.href = '/core/flows/create/next-steps' + qs;
      return;
    } catch (e) {
      if (typeof CoreAPI !== 'undefined' && CoreAPI.isStaleWrite && CoreAPI.isStaleWrite(e)) {
        if (window.showNotification) {
          window.showNotification(
            'warning',
            'Changed elsewhere',
            'Someone else edited this step while you had it open. Reload the page to get the latest, then re-apply your change.'
          );
        }
        return;
      }
      console.error(e);
      if (window.showNotification) {
        window.showNotification('error', 'Could not save step', e.message || 'Unknown error');
      } else {
        alert(e.message || 'Failed to save step');
      }
    }
  };
  
  function isProcessFlowSummaryPage() {
    return document.body && document.body.getAttribute('data-flow-wizard-page') === 'summary';
  }





  /**
   * Summary page: unsaved in-progress step comes only from session; saved steps from createdSteps / API.
   */
  const summarySessionHelpers = window.ProcessModalSummarySession.create({
    loadWizardSessionMergeBase,
    getEditingStepId: function() { return editingStepId; },
    wizardSessionHasDraftStepData,
    buildVirtualSummaryStepFromWizardSession: function(session) {
      return window.ProcessModalSessionSummary.buildVirtualSummaryStepFromWizardSession(
        session,
        { buildExecutionPromptsForApiFromSession, mapSessionInputsToSummaryRows }
      );
    },
    summaryInputDisplayName,
    summaryOutputDisplayName,
    mapSessionInputsToSummaryRows,
    buildExecutionPromptsForApiFromSession
  });
  const { resolveCurrentStepForSummary, enrichStepForSummaryFromSession } = summarySessionHelpers;

  /** Derived issues only — scoped to the current step (no filler when empty). */



  function setPendingNewStepIntent() {
    try {
      sessionStorage.setItem(PROCESS_FLOW_PENDING_NEW_STEP_KEY, '1');
    } catch (e) {}
  }

  function consumePendingNewStepIntent() {
    try {
      if (sessionStorage.getItem(PROCESS_FLOW_PENDING_NEW_STEP_KEY) === '1') {
        sessionStorage.removeItem(PROCESS_FLOW_PENDING_NEW_STEP_KEY);
        return true;
      }
    } catch (e) {}
    return false;
  }

  function reconcileEditingStepIdAfterStepsSync() {
    if (consumePendingNewStepIntent()) {
      editingStepId = null;
      return;
    }
    if (!Array.isArray(createdSteps) || createdSteps.length === 0) {
      editingStepId = null;
      return;
    }
    if (editingStepId != null && editingStepId !== '' && createdSteps.some(s => String(s.id) === String(editingStepId))) {
      return;
    }
    const session = loadWizardSessionMergeBase();
    // User is composing a new unsaved step (modal draft save always uses createStep for that case).
    // Do not default to "last saved step" — that made Save on summary call updateStep on step N−1.
    // When editing an existing step, editingStepId is already set from restoreSpaWizardState above.
    if (wizardSessionHasDraftStepData(session)) {
      // Editing an existing step fills the session with I/O rows too — must not clear editingStepId or
      // commitGuidedStepToProcessApiFromSessionSnapshot would create a new step instead of updateStep.
      const sid =
        session && session.editingStepId != null && session.editingStepId !== ''
          ? session.editingStepId
          : null;
      if (sid != null && createdSteps.some(s => String(s.id) === String(sid))) {
        editingStepId = sid;
        return;
      }
      editingStepId = null;
      return;
    }
    const sorted = [...createdSteps].sort((a, b) => (a.step_number || 0) - (b.step_number || 0));
    const last = sorted[sorted.length - 1];
    editingStepId = last && last.id ? last.id : null;
  }

  /**
   * API GET may lag unsaved wizard work. Fill empty step.outputs/inputs/prompts from draft snapshots.
   */



  /**
   * Wizard session stores current outputs under `outputs` (DOM snapshot), not always copied onto createdSteps[].
   * Apply to the step being edited when that step still has no outputs on the server.
   */
  function resolveWizardSessionTargetStepId(steps) {
    const session = loadWizardSessionMergeBase();
    if (!session || !Array.isArray(steps) || steps.length === 0) return null;
    if (session.editingStepId != null && session.editingStepId !== '') {
      return String(session.editingStepId);
    }
    const sorted = [...steps].sort(function (a, b) {
      return (a.step_number || 0) - (b.step_number || 0);
    });
    const last = sorted[sorted.length - 1];
    return last && last.id ? String(last.id) : null;
  }

  function overlaySessionWizardOutputsOntoSteps(steps) {
    const session = loadWizardSessionMergeBase();
    if (!session || !Array.isArray(steps) || steps.length === 0) return steps;

    const targetId = resolveWizardSessionTargetStepId(steps);
    if (!targetId) return steps;

    const draft = (session.createdSteps || []).find(function (s) {
      return s && String(s.id) === targetId;
    });
    const draftOut =
      draft && Array.isArray(draft.outputs)
        ? draft.outputs.filter(function (o) {
            return o && summaryOutputDisplayName(o);
          })
        : [];
    const wo =
      draftOut.length > 0
        ? draftOut
        : (session.outputs || []).filter(function (o) {
            return o && summaryOutputDisplayName(o);
          });
    if (!Array.isArray(wo) || wo.length === 0) return steps;

    return steps.map(function (s) {
      if (String(s.id) !== targetId) return s;
      const has = (s.outputs || []).filter(function (o) {
        return o && summaryOutputDisplayName(o);
      });
      if (has.length > 0) return s;
      return { ...s, outputs: JSON.parse(JSON.stringify(wo)) };
    });
  }

  /** Prefer createdSteps[].inputs, then top-level session.inputs. */
  function overlaySessionWizardInputsOntoSteps(steps) {
    const session = loadWizardSessionMergeBase();
    if (!session || !Array.isArray(steps) || steps.length === 0) return steps;

    const targetId = resolveWizardSessionTargetStepId(steps);
    if (!targetId) return steps;

    const draft = (session.createdSteps || []).find(function (s) {
      return s && String(s.id) === targetId;
    });
    const fromDraft =
      draft && Array.isArray(draft.inputs)
        ? mapSessionInputsToSummaryRows(draft.inputs)
        : [];
    const wi = fromDraft.length > 0 ? fromDraft : mapSessionInputsToSummaryRows(session.inputs || []);
    if (wi.length === 0) return steps;

    return steps.map(function (s) {
      if (String(s.id) !== targetId) return s;
      const named = (s.inputs || []).filter(function (i) {
        return i && summaryInputDisplayName(i);
      });
      if (named.length > 0) return s;
      return { ...s, inputs: JSON.parse(JSON.stringify(wi)) };
    });
  }

  /**
   * Replace createdSteps from API when the URL has a process id (summary + wizard routes).
   * Keeps editingStepId valid via reconcileEditingStepIdAfterStepsSync.
   */
  async function mergeProcessStepsFromApiForCurrentProcess(isCurrent) {
    const pid = new URLSearchParams(window.location.search).get('id');
    if (!pid || typeof CoreAPI === 'undefined' || !CoreAPI.getProcess) return;
    const current = typeof isCurrent === 'function' ? isCurrent : function() { return true; };
    try {
      const proc = await CoreAPI.getProcess(pid);
      if (!current()) return;
      if (!proc || !Array.isArray(proc.steps)) return;
      if (proc.steps.length === 0) return;

      // Do not let an old browser session shadow the process definition. The
      // session still holds only the uncommitted form while the server remains
      // the source of truth for every saved step.
      const merged = proc.steps.map(function (s) {
        return { ...s };
      });

      createdSteps = merged;
      reconcileEditingStepIdAfterStepsSync();
    } catch (e) {
      console.warn('mergeProcessStepsFromApiForCurrentProcess', e);
    }
  }



  const persistStepOrder = window.ProcessModalStepOrder.create({
    getCoreApi: function() { return typeof CoreAPI === 'undefined' ? null : CoreAPI; },
    getCreatedSteps: function() { return createdSteps; },
    sortStepsForDisplay,
    reloadSteps: function() { return mergeProcessStepsFromApiForCurrentProcess(function() { return true; }); },
    refreshSummaries: function() { return updateStepSummaries(); }
  });

  async function persistStepOrderIfPossible() {
    return persistStepOrder();
  }

  async function mergeProcessStepsFromApiForSummary(isCurrent) {
    if (!isProcessFlowSummaryPage()) return;
    await mergeProcessStepsFromApiForCurrentProcess(isCurrent);
  }

  const processStepSummaryRenderer = window.ProcessModalStepSummary.create({
    getCreatedSteps: function() { return createdSteps; },
    setCreatedSteps: function(steps) { createdSteps = steps; },
    loadWizardSessionMergeBase,
    wizardSessionHasDraftStepData,
    sortStepsForDisplay,
    isProcessFlowSummaryPage,
    resolveCurrentStepForSummary,
    enrichStepForSummaryFromSession,
    formatStep4ModeLabel,
    persistStepOrderIfPossible,
    updateStepSummaries: function() { return updateStepSummaries(); }
  });

  async function updateStepSummaries() {
    return processStepSummaryRenderer.updateStepSummaries();
  }

  // Start editing an existing step (from the "existing steps" view when editing a non-draft process)
  window.startEditingStep = async function(stepId) {
    const step = createdSteps.find(s => String(s.id) === String(stepId));
    if (!step) return;
    editingStepId = step.id;
    resetForm(true);
    await restoreStepIntoForm(step);
    const existingView = document.getElementById('existing-steps-list-view');
    if (existingView) existingView.style.display = 'none';
    const indicators = document.getElementById('create-process-step-indicators');
    if (indicators) indicators.style.display = 'flex';
    currentStep = 1;
    updateStepDisplay();
  };

  /**
   * Deep-link / resume: ?edit=<stepId> on step wizard SPA pages (after mergeProcessStepsFromApiForCurrentProcess).
   * Each route mounts partial DOM; seed session from the API step then restore so inputs/outputs/evidence load correctly.
   */
  const applyEditStepFromUrl = window.ProcessModalDeepLinkEdit.create({
    getCoreApi: function() { return typeof CoreAPI === 'undefined' ? null : CoreAPI; },
    getCreatedSteps: function() { return createdSteps; },
    setEditingStepId: function(stepId) { editingStepId = stepId; },
    resetForm,
    buildSessionPayload: function(step, opts) {
      return window.ProcessModalApiSession.buildSpaWizardSessionPayloadFromApiStep(step, opts, {
        createdSteps,
        deriveTraceabilityModes,
        mapApiInputToWizardSessionInput,
        mapApiOutputToWizardSessionOutput,
        isCustomExecutionPrompt,
        normalisePromptOptions
      });
    },
    getProcessFlowSpaStorageKey,
    setCurrentStep: function(step) { currentStep = step; },
    updateStepDisplay
  });
  window.applyEditStepFromUrl = applyEditStepFromUrl;
  
  // Add new step from the "existing steps" view (when editing a non-draft process)
  window.addNewStepFromEditView = function() {
    editingStepId = null;
    const existingView = document.getElementById('existing-steps-list-view');
    if (existingView) existingView.style.display = 'none';
    const indicators = document.getElementById('create-process-step-indicators');
    if (indicators) indicators.style.display = 'flex';
    resetForm(true);
    if (createdSteps.length > 0) {
      updateStepSummaries();
      const summariesContainer = document.getElementById('step-summaries-container');
      if (summariesContainer) summariesContainer.style.display = 'block';
    }
    updateInputButtonsText();
    currentStep = 1;
    updateStepDisplay();
  };

  // Start new process from the "existing steps" view (when editing a saved/complete process — replaces all steps)
  window.startNewFromEditView = async function() {
    const urlParams = new URLSearchParams(window.location.search);
    const processId = urlParams.get('id');
    if (processId) {
      try {
        const processData = await CoreAPI.getProcess(processId);
        if (processData && processData.steps && processData.steps.length > 0) {
          startNewOldStepIds = processData.steps.map(function(s) { return s.id; });
          isStartNewOverwriteDraft = true;
        }
      } catch (err) {
        console.warn('Could not fetch process steps for Start new overwrite:', err);
      }
    }
    createdSteps = [];
    isEditingExistingProcess = false;
    editingStepId = null;
    const existingView = document.getElementById('existing-steps-list-view');
    if (existingView) existingView.style.display = 'none';
    const indicators = document.getElementById('create-process-step-indicators');
    if (indicators) indicators.style.display = 'flex';
    const summariesContainer = document.getElementById('step-summaries-container');
    if (summariesContainer) summariesContainer.style.display = 'none';
    const postCreationOptions = document.getElementById('post-creation-options');
    if (postCreationOptions) postCreationOptions.style.display = 'none';
    resetForm(true);
    updateInputButtonsText();
    currentStep = 1;
    updateStepDisplay();
    const modalTitle = document.getElementById('modal-title');
    const modalDescription = document.getElementById('modal-description');
    if (modalTitle) modalTitle.textContent = 'Create Process Step';
    if (modalDescription) modalDescription.textContent = '';
  };
  
  // Add another step
  window.addAnotherStep = function() {
    editingStepId = null;
    setPendingNewStepIntent();
    const summarySticky = document.getElementById('flow-wizard-summary-sticky');
    if (summarySticky) summarySticky.style.display = 'none';
    const postCreationOptions = document.getElementById('post-creation-options');
    if (postCreationOptions) {
      postCreationOptions.style.display = 'none';
    }

    if (isProcessFlowWizardPage()) {
      resetForm(true);
      persistClearedWizardDraftState();
      window.location.href = '/core/flows/create/step-name' + (window.location.search || '');
      return;
    }

    if (isProcessFlowSpaPage() && document.body.getAttribute('data-flow-wizard-page') === 'summary') {
      resetForm(true);
      persistClearedWizardDraftState();
      window.location.href = '/core/flows/create/step-name' + (window.location.search || '');
      return;
    }

    // Show step summaries
    if (createdSteps.length > 0) {
      updateStepSummaries();
    }
    
    // Reset form but keep created steps
    resetForm(true);
    
    // Update button visibility (previous output button should now be visible)
    updateInputButtonsText();
    
    // Show step 1 again
    currentStep = 1;
    updateStepDisplay();
  };
  
  // Finish process (SPA: no confirmation modal — finalize draft and open flows2)
  window.finishProcess = function() {
    void window.confirmFinishProcess();
  };

  // Confirm finish process (also used by legacy modal "Finish creating process" where present)
  window.confirmFinishProcess = async function() {
    const confirmationModal = document.getElementById('finish-process-confirmation-modal');
    if (confirmationModal) {
      confirmationModal.style.display = 'none';
    }

    if (typeof window.persistSpaWizardState === 'function') window.persistSpaWizardState();
    if (hasPendingUnsavedWizardStepForFinish()) {
      if (window.showNotification) {
        window.showNotification(
          'warning',
          'Save your step first',
          'Use Save step on the summary page to store the current step before finishing the process.'
        );
      }
      return;
    }
    
    const urlParams = new URLSearchParams(window.location.search);
    const processId = urlParams.get('id');
    if (processId) {
      // If user chose "Start New", remove old draft steps so only the new steps remain
      if (isStartNewOverwriteDraft && startNewOldStepIds.length > 0) {
        for (const stepId of startNewOldStepIds) {
          try {
            await CoreAPI.deleteStep(processId, stepId);
          } catch (err) {
            console.warn('Could not delete old draft step on finish:', stepId, err);
          }
        }
        startNewOldStepIds = [];
        isStartNewOverwriteDraft = false;
      }
      try {
        await CoreAPI.updateProcess(processId, { is_draft: false });
      } catch (error) {
        console.error('Error updating process draft status:', error);
      }
    }

    const finishedStepCount = createdSteps.length;
    if (window.showNotification) {
      window.showNotification(
        'success',
        'Process created',
        `Your process is ready with ${finishedStepCount} step${finishedStepCount > 1 ? 's' : ''}.`
      );
    }

    resetForm(false);
    closeModal();
  };
  
  async function initProcessFlowWizardFromDom() {
    if (!isProcessFlowSpaPage()) return;
    bindProcessFlowWizardExitCleanup();
    applyProcessFlowWizardFreshStart();
    const slug = document.body.getAttribute('data-flow-wizard-page');
    const initGeneration = ++processFlowWizardInitGeneration;
    const isCurrent = function() {
      return processFlowWizardInitGeneration === initGeneration &&
        isProcessFlowSpaPage() &&
        document.body.getAttribute('data-flow-wizard-page') === slug;
    };
    const slugToStep = { 'step-name': 1, 'inputs': 2, 'outputs': 3, 'evidence-and-prompts': 4 };
    if (slug && slugToStep[slug]) {
      currentStep = slugToStep[slug];
    }
    if (slug === 'process-overview') {
      if (typeof window.restoreSpaWizardState === 'function') {
        await window.restoreSpaWizardState({ isCurrent: isCurrent });
      }
      if (!isCurrent()) return;
      const pidOv = new URLSearchParams(window.location.search || '').get('id');
      if (pidOv && typeof CoreAPI !== 'undefined' && CoreAPI.getProcess) {
        try {
          const proc = await CoreAPI.getProcess(pidOv);
          if (!isCurrent()) return;
          if (proc && proc.name) {
            const wf = document.getElementById('guided-process-workflow-name');
            if (wf && !(wf.value || '').trim()) {
              wf.value = proc.name;
            }
          }
        } catch (e) {
          console.warn('process-overview: could not load process', e);
        }
      }
      if (typeof window.persistSpaWizardState === 'function') {
        window.persistSpaWizardState();
      }
    } else if (slug === 'next-steps') {
      if (typeof window.restoreSpaWizardState === 'function') {
        await window.restoreSpaWizardState({ isCurrent: isCurrent });
      }
      if (!isCurrent()) return;
      const pidNs = new URLSearchParams(window.location.search || '').get('id');
      if (pidNs) {
        await mergeProcessStepsFromApiForCurrentProcess(isCurrent);
        if (!isCurrent()) return;
        if (typeof window.persistSpaWizardState === 'function') {
          window.persistSpaWizardState();
        }
      }
    } else if (slug === 'summary') {
      if (typeof window.restoreSpaWizardState === 'function') {
        await window.restoreSpaWizardState({ isCurrent: isCurrent });
      }
      if (!isCurrent()) return;
      await mergeProcessStepsFromApiForSummary(isCurrent);
      if (!isCurrent()) return;
      if (typeof window.persistSpaWizardState === 'function') {
        window.persistSpaWizardState();
      }
      const emptyEl = document.getElementById('process-flow-summary-empty');
      const postCreationOptions = document.getElementById('post-creation-options');
      const summarySticky = document.getElementById('flow-wizard-summary-sticky');
      const hasPending = wizardSessionHasDraftStepData(loadWizardSessionMergeBase());
      if (createdSteps.length > 0 || hasPending) {
        if (emptyEl) emptyEl.style.display = 'none';
        await updateStepSummaries();
        const summariesContainer = document.getElementById('step-summaries-container');
        if (summariesContainer) summariesContainer.style.display = 'block';
        if (postCreationOptions) postCreationOptions.style.display = 'none';
        if (summarySticky) summarySticky.style.display = '';
      } else {
        if (emptyEl) emptyEl.style.display = 'block';
        if (postCreationOptions) postCreationOptions.style.display = 'none';
        if (summarySticky) summarySticky.style.display = 'none';
        const summariesContainer = document.getElementById('step-summaries-container');
        if (summariesContainer) summariesContainer.style.display = 'none';
      }
    } else {
      const qsInit = new URLSearchParams(window.location.search || '');
      const pid = qsInit.get('id');
      const urlEditStepId = qsInit.get('edit');
      const slugAllowsEditFromUrl = ['step-name', 'inputs', 'outputs', 'evidence-and-prompts'].indexOf(slug) !== -1;
      const existingSession = loadWizardSessionMergeBase();
      const sessionHasSameEdit =
        !!(
          existingSession &&
          existingSession.v === 1 &&
          urlEditStepId &&
          existingSession.editingStepId != null &&
          String(existingSession.editingStepId) === String(urlEditStepId) &&
          // Only treat the session as "already seeded" if it has real wizard data.
          // A stale/empty session would otherwise block loading the DB step into the form.
          wizardSessionHasDraftStepData(existingSession)
        );
      // Only seed from API when starting an edit, not on every wizard page navigation.
      // Otherwise we'd wipe unsaved edits each time (the URL keeps ?edit=... across pages).
      const shouldApplyEditFromUrl = !!(urlEditStepId && slugAllowsEditFromUrl && !sessionHasSameEdit);
      if (shouldApplyEditFromUrl && typeof sessionStorage !== 'undefined' && pid) {
        sessionStorage.removeItem('process-flow-spa-wizard-v1-' + pid);
      }
      if (typeof window.restoreSpaWizardState === 'function') {
        await window.restoreSpaWizardState({ isCurrent: isCurrent });
      }
      if (!isCurrent()) return;
      if (pid) {
        await mergeProcessStepsFromApiForCurrentProcess(isCurrent);
      }
      if (!isCurrent()) return;
      if (
        shouldApplyEditFromUrl &&
        urlEditStepId &&
        typeof window.applyEditStepFromUrl === 'function'
      ) {
        await window.applyEditStepFromUrl(urlEditStepId, isCurrent);
      }
      if (!isCurrent()) return;
      if (pid && typeof window.persistSpaWizardState === 'function') {
        window.persistSpaWizardState();
      }
      if (typeof window.updateStepDisplay === 'function') {
        window.updateStepDisplay();
      }
      if (slug === 'evidence-and-prompts') {
        if (typeof window.ensureGuidedDocFileListener === 'function') {
          window.ensureGuidedDocFileListener();
        }
        if (typeof syncDocInlineDisabledState === 'function') {
          syncDocInlineDisabledState();
        }
      }
    }
    if (typeof window.spaSyncBannerBack === 'function') {
      window.spaSyncBannerBack();
    }
    initGuidedNewInputExecutionSegments();
    document.querySelectorAll('#guided-inputs-list-unified > div[data-input-type="new"]').forEach(function(row) {
      syncGuidedNewInputExecutionSegments(row);
    });
  }
  window.initProcessFlowWizardFromDom = initProcessFlowWizardFromDom;

  // Close modal on overlay click or close button — show "Save as draft or discard?" first
  // Use data-create-step-close so the global [data-modal-close] handler (e.g. on flows2) does not run and close the modal before our prompt appears
  document.addEventListener('DOMContentLoaded', async function() {
    if (isProcessFlowSpaPage()) {
      await initProcessFlowWizardFromDom();
    }

    const modal = document.getElementById('create-process-modal');
    if (modal) {
      const closeButtons = modal.querySelectorAll('[data-create-step-close]');
      closeButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
          e.preventDefault();
          e.stopPropagation();
          requestCloseCreateProcessModal();
        });
      });
    }
    
    // Save as draft or discard confirmation modal buttons
    const saveDraftSaveBtn = document.getElementById('save-draft-save-btn');
    const saveDraftDiscardBtn = document.getElementById('save-draft-discard-btn');
    const saveDraftContinueBtn = document.getElementById('save-draft-continue-btn');
    if (saveDraftSaveBtn) {
      saveDraftSaveBtn.addEventListener('click', function() {
        hideSaveDraftOrDiscardModal();
        window.saveDraft();
      });
    }
    if (saveDraftDiscardBtn) {
      saveDraftDiscardBtn.addEventListener('click', function() {
        hideSaveDraftOrDiscardModal();
        resetForm(false);
        closeModal();
      });
    }
    if (saveDraftContinueBtn) {
      saveDraftContinueBtn.addEventListener('click', function() {
        hideSaveDraftOrDiscardModal();
        // Keep create-process-modal open; user continues creating steps
      });
    }
    
    // Define Inputs step 2: tab switching (Inventory | Outputs from previous steps | Other materials)
    const inputTabInventory = document.getElementById('input-tab-inventory');
    const inputTabPreviousOutput = document.getElementById('input-tab-previous-output');
    const inputTabNew = document.getElementById('input-tab-new');
    const panelInventory = document.getElementById('guided-inputs-panel-inventory');
    const panelPreviousOutput = document.getElementById('guided-inputs-panel-previous-output');
    const panelNew = document.getElementById('guided-inputs-panel-new');
    function switchInputTab(tab) {
      const isInventory = tab === 'inventory';
      const isPreviousOutput = tab === 'previous_output';
      const isNew = tab === 'new';
      if (inputTabInventory) {
        inputTabInventory.classList.toggle('flow-mode-segment--active', isInventory);
        inputTabInventory.setAttribute('aria-pressed', isInventory ? 'true' : 'false');
      }
      if (inputTabPreviousOutput) {
        inputTabPreviousOutput.classList.toggle('flow-mode-segment--active', isPreviousOutput);
        inputTabPreviousOutput.setAttribute('aria-pressed', isPreviousOutput ? 'true' : 'false');
      }
      if (inputTabNew) {
        inputTabNew.classList.toggle('flow-mode-segment--active', isNew);
        inputTabNew.setAttribute('aria-pressed', isNew ? 'true' : 'false');
      }
      if (panelInventory) panelInventory.style.display = isInventory ? 'block' : 'none';
      if (panelPreviousOutput) panelPreviousOutput.style.display = isPreviousOutput ? 'block' : 'none';
      if (panelNew) panelNew.style.display = isNew ? 'block' : 'none';
      if (isInventory && typeof window.renderInventoryItemCards === 'function') window.renderInventoryItemCards();
      if (isPreviousOutput && typeof window.renderPreviousOutputsList === 'function') window.renderPreviousOutputsList();
    }
    if (inputTabInventory) inputTabInventory.addEventListener('click', function() { switchInputTab('inventory'); });
    if (inputTabPreviousOutput) inputTabPreviousOutput.addEventListener('click', function() { switchInputTab('previous_output'); });
    if (inputTabNew) inputTabNew.addEventListener('click', function() { switchInputTab('new'); });

    const invCatTabs = document.getElementById('guided-inventory-category-tabs');
    if (invCatTabs && !invCatTabs.dataset.guidedInvCatBound) {
      invCatTabs.dataset.guidedInvCatBound = '1';
      invCatTabs.addEventListener('click', function(e) {
        const btn = e.target && e.target.closest ? e.target.closest('.flow-mode-segment[data-inventory-cat]') : null;
        if (!btn || !invCatTabs.contains(btn)) return;
        const cat = btn.getAttribute('data-inventory-cat');
        if (!cat) return;
        window._guidedInventoryCat = cat;
        if (typeof window.applyGuidedInventoryCategoryUI === 'function') window.applyGuidedInventoryCategoryUI();
      });
    }
    
    // Show "Outputs from previous steps" tab only when there is at least one previous (saved/finished) step
    window.updatePreviousOutputTabVisibility = function() {
      const tab = document.getElementById('input-tab-previous-output');
      const panel = document.getElementById('guided-inputs-panel-previous-output');
      if (!tab || !panel) return;
      let hasPreviousSteps = false;
      if (editingStepId) {
        const sorted = sortStepsForDisplay(createdSteps);
        const idx = sorted.findIndex(function(s) { return String(s.id) === String(editingStepId); });
        hasPreviousSteps = idx > 0;
      } else {
        hasPreviousSteps = createdSteps.length >= 1;
      }
      if (hasPreviousSteps) {
        tab.style.display = '';
        tab.removeAttribute('aria-hidden');
      } else {
        tab.style.display = 'none';
        tab.setAttribute('aria-hidden', 'true');
        if (tab.classList.contains('flow-mode-segment--active')) {
          switchInputTab('inventory');
        }
        panel.style.display = 'none';
      }
    };

    initStep4SegmentControls();
    initGuidedOutputsListModeSegments();
    initGuidedNewInputExecutionSegments();
  });

  window.addEventListener('pagehide', function() {
    if (!isProcessFlowSpaPage()) return;
    if (typeof window.persistSpaWizardState === 'function') {
      try {
        window.persistSpaWizardState();
      } catch (e) {}
    }
  });
})();
