(function() {
  'use strict';
  
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
  let pendingDeleteDoc = null; // { docId, row } when delete-doc-confirm modal is open
  /** SOP file chosen on evidence page, kept for Save step after navigating to summary (small files only). */
  let pendingGuidedDocFileUpload = null;

  // Get draft key for current process
  function getDraftKey() {
    const urlParams = new URLSearchParams(window.location.search);
    const processId = urlParams.get('id');
    return `process-draft-${processId || 'new'}`;
  }

  function isProcessFlowSpaPage() {
    const p = document.body && document.body.getAttribute('data-page');
    return p === 'process-flow-spa' || p === 'process-flow-wizard';
  }

  function isProcessFlowWizardPage() {
    return document.body && document.body.getAttribute('data-page') === 'process-flow-wizard';
  }

  function getFlowWizardPageSlug() {
    return (document.body && document.body.getAttribute('data-flow-wizard-page')) || '';
  }

  /** When true, serializeSpaWizardState merges missing DOM fields from session (summary page has no wizard form). */
  function shouldMergePersistSpaFormFields() {
    if (isProcessFlowWizardPage()) return true;
    const slug = document.body && document.body.getAttribute('data-flow-wizard-page');
    return slug === 'summary' || slug === 'process-overview';
  }

  function loadWizardSessionMergeBase() {
    try {
      const raw = sessionStorage.getItem(getProcessFlowSpaStorageKey());
      if (!raw) return null;
      const d = JSON.parse(raw);
      return d && d.v === 1 ? d : null;
    } catch (e) {
      return null;
    }
  }

  function applyProcessFlowWizardFreshStart() {
    if (!isProcessFlowWizardPage()) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get('fresh') !== '1') return;
    const id = params.get('id');
    sessionStorage.removeItem('process-flow-spa-wizard-v1-new');
    if (id) {
      sessionStorage.removeItem('process-flow-spa-wizard-v1-' + id);
    }
    params.delete('fresh');
    const qs = params.toString();
    window.history.replaceState({}, '', window.location.pathname + (qs ? '?' + qs : ''));
  }

  function getProcessFlowSpaStorageKey() {
    const processId = new URLSearchParams(window.location.search).get('id');
    return 'process-flow-spa-wizard-v1-' + (processId || 'new');
  }

  function migrateProcessFlowSpaStorage() {
    const id = new URLSearchParams(window.location.search).get('id');
    if (!id) return;
    const newKey = 'process-flow-spa-wizard-v1-' + id;
    if (sessionStorage.getItem(newKey)) return;
    const legacy = sessionStorage.getItem('process-flow-spa-wizard-v1-new');
    if (legacy) {
      sessionStorage.setItem(newKey, legacy);
    }
  }

  function collectSpaWizardOutputsPayload() {
    const outputs = [];
    const outputElements = document.querySelectorAll('#guided-outputs-list > div');
    outputElements.forEach(outputEl => {
      const name = outputEl.querySelector('.guided-output-name')?.value.trim();
      const unitSelect = outputEl.querySelector('.guided-output-unit');
      const unit = unitSelect ? (unitSelect.value || '').trim() : '';
      const quantityInput = outputEl.querySelector('.guided-output-quantity');
      const quantity = quantityInput ? (quantityInput.value || '').trim() : '';
      if (!name || !unit) return;
      const existingId = outputEl.dataset.outputId || null;
      const outputId = existingId || (typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : 'out-' + Date.now() + '-' + Math.random().toString(36).slice(2, 11));
      const expiryModeEl = outputEl.querySelector('.guided-output-expiry-mode');
      const expiryValueEl = outputEl.querySelector('.guided-output-expiry-value');
      const expiryUnitEl = outputEl.querySelector('.guided-output-expiry-unit');
      const warningValueEl = outputEl.querySelector('.guided-output-expiry-warning-value');
      const warningUnitEl = outputEl.querySelector('.guided-output-expiry-warning-unit');
      const readyDateModeEl = outputEl.querySelector('.guided-output-ready-date-mode');
      const readyDateValueEl = outputEl.querySelector('.guided-output-ready-date-value');
      const readyDateUnitEl = outputEl.querySelector('.guided-output-ready-date-unit');
      const readyDateWarnValueEl = outputEl.querySelector('.guided-output-ready-date-warning-value');
      const readyDateWarnUnitEl = outputEl.querySelector('.guided-output-ready-date-warning-unit');
      const expiryMode = expiryModeEl ? expiryModeEl.value : 'none';
      const readyDateMode = readyDateModeEl ? readyDateModeEl.value : 'none';
      const expiryValueRaw = expiryValueEl && expiryMode === 'fixed_duration' ? expiryValueEl.value.trim() : '';
      const expiryValue = expiryValueRaw !== '' ? parseInt(expiryValueRaw, 10) : null;
      const expiryUnit = expiryUnitEl && expiryMode === 'fixed_duration' ? ((expiryUnitEl.value || 'days') + '').trim() : 'days';
      const warningValueRaw = warningValueEl && expiryMode === 'fixed_duration' ? warningValueEl.value.trim() : '';
      const warningValue = warningValueRaw !== '' ? parseInt(warningValueRaw, 10) : 7;
      const warningUnit = warningUnitEl && expiryMode === 'fixed_duration' ? ((warningUnitEl.value || 'days') + '').trim() : 'days';
      const extra_data = {};
      if (expiryMode === 'fixed_duration' && expiryValue > 0) {
        extra_data.custom_expiry = {
          enabled: true,
          mode: 'fixed_duration',
          duration_value: expiryValue,
          duration_unit: (expiryUnit || 'days').trim(),
          warning_value: (typeof warningValue === 'number' && !isNaN(warningValue) && warningValue >= 0) ? warningValue : 7,
          warning_unit: (warningUnit || 'days').trim(),
          expiry_at: null,
          rule_type: 'custom_output_expiry'
        };
      } else if (expiryMode === 'set_at_execution') {
        extra_data.custom_expiry = {
          enabled: true,
          mode: 'set_at_execution',
          duration_value: null,
          duration_unit: null,
          warning_value: null,
          warning_unit: null,
          expiry_at: null,
          rule_type: 'custom_output_expiry'
        };
      }
      if (readyDateMode === 'fixed_duration' && readyDateValueEl && readyDateValueEl.value.trim()) {
        const rdVal = parseInt(readyDateValueEl.value, 10);
        if (!isNaN(rdVal) && rdVal > 0) {
          const rdUnit = (readyDateUnitEl && readyDateUnitEl.value) ? readyDateUnitEl.value.trim() : 'days';
          const rdWarnVal = (readyDateWarnValueEl && readyDateWarnValueEl.value.trim() !== '') ? parseInt(readyDateWarnValueEl.value, 10) : 0;
          const rdWarnUnit = (readyDateWarnUnitEl && readyDateWarnUnitEl.value) ? readyDateWarnUnitEl.value.trim() : 'days';
          extra_data.ready_date = {
            enabled: true,
            mode: 'fixed_duration',
            duration_value: rdVal,
            duration_unit: rdUnit,
            warning_value: (typeof rdWarnVal === 'number' && !isNaN(rdWarnVal) && rdWarnVal >= 0) ? rdWarnVal : 0,
            warning_unit: rdWarnUnit,
            rule_type: 'custom_ready_date'
          };
        }
      } else if (readyDateMode === 'set_at_execution') {
        extra_data.ready_date = {
          enabled: true,
          mode: 'set_at_execution',
          duration_value: null,
          duration_unit: null,
          warning_value: null,
          warning_unit: null,
          rule_type: 'custom_ready_date'
        };
      }
      const outObj = {
        id: outputId,
        name: name,
        unit: unit,
        quantity: quantity ? parseFloat(quantity) : null,
        is_variable: true,
        requires_execution_confirmation: true
      };
      if (Object.keys(extra_data).length > 0) outObj.extra_data = extra_data;
      outputs.push(outObj);
    });
    return outputs;
  }

  /** Summary / API rows may use alternate keys (inventory, legacy). */
  function summaryInputDisplayName(row) {
    if (!row) return '';
    return String(row.name || row.input_name || row.material_name || row.item_name || '').trim();
  }

  function summaryOutputDisplayName(row) {
    if (!row) return '';
    return String(row.name || row.output_name || '').trim();
  }

  function isCustomExecutionPrompt(p) {
    if (!p || !(p.label || '').trim()) return false;
    const l = (p.label || '').trim().toLowerCase();
    if (l === 'batch number' || l === 'evidence') return false;
    if (p.type === 'evidence') return false;
    return true;
  }

  /**
   * After GET /process merges into createdSteps, persist must not wipe nested I/O that
   * still exists in the previous session snapshot (common on summary route).
   */
  function preserveCreatedStepsIoFromPrev(prev, createdStepsSnapshot) {
    if (!prev || !Array.isArray(prev.createdSteps) || !Array.isArray(createdStepsSnapshot)) {
      return createdStepsSnapshot;
    }
    const prevById = new Map();
    prev.createdSteps.forEach(function (s) {
      if (s && s.id != null) prevById.set(String(s.id), s);
    });
    return createdStepsSnapshot.map(function (s) {
      if (!s || s.id == null) return s;
      const p = prevById.get(String(s.id));
      if (!p) return s;
      const o = { ...s };
      if (countNamedStepInputs(o.inputs) === 0 && countNamedStepInputs(p.inputs) > 0) {
        o.inputs = JSON.parse(JSON.stringify(p.inputs));
      }
      if (countNamedStepOutputs(o.outputs) === 0 && countNamedStepOutputs(p.outputs) > 0) {
        o.outputs = JSON.parse(JSON.stringify(p.outputs));
      }
      const cpl = countLabeledExecutionPrompts(o.execution_prompts);
      const ppl = countLabeledExecutionPrompts(p.execution_prompts);
      if (cpl === 0 && ppl > 0) {
        o.execution_prompts = JSON.parse(JSON.stringify(p.execution_prompts));
      }
      if (o.batch_number_mode == null && p.batch_number_mode != null) o.batch_number_mode = p.batch_number_mode;
      if (o.evidence_mode == null && p.evidence_mode != null) o.evidence_mode = p.evidence_mode;
      if (!(o.documentation_summary || '').trim() && (p.documentation_summary || '').trim()) {
        o.documentation_summary = p.documentation_summary;
      }
      return o;
    });
  }

  function countLabeledExecutionPrompts(prompts) {
    if (!Array.isArray(prompts)) return 0;
    return prompts.filter(function (p) {
      return p && (p.label || '').trim();
    }).length;
  }

  function serializeSpaWizardState() {
    const merge = shouldMergePersistSpaFormFields();
    const prev = merge ? (loadWizardSessionMergeBase() || {}) : null;

    const nameEl = document.getElementById('guided-step-name');
    const descEl = document.getElementById('guided-step-description');
    const stepName = nameEl ? (nameEl.value || '') : (merge ? (prev.stepName || '') : '');
    const stepDescription = descEl ? (descEl.value || '') : (merge ? (prev.stepDescription || '') : '');

    let inputs;
    if (document.getElementById('guided-inputs-list-unified')) {
      inputs = [];
      getAllGuidedInputElements().forEach(inputEl => {
        const inputType = inputEl.dataset.inputType || 'new';
        const nameInput = inputEl.querySelector('.guided-input-name');
        let name = '';
        if (nameInput) {
          name = nameInput.classList.contains('searchable-dropdown-input') ? nameInput.value.trim() : nameInput.value.trim();
        }
        const quantityInput = inputEl.querySelector('.guided-input-quantity');
        const quantity = quantityInput ? (quantityInput.value || '').trim() : '';
        const unitSelect = inputEl.querySelector('.guided-input-unit');
        const unit = unitSelect ? unitSelect.value : '';
        const executionTypeSelect = inputEl.querySelector('.guided-input-execution-type');
        const executionType = executionTypeSelect ? executionTypeSelect.value : 'variable';
        const sourceOutputId = inputEl.dataset.sourceOutputId || null;
        const previousOutputDisplayName = inputEl.dataset.previousOutputDisplayName || null;
        const inventoryPreselected = inputType === 'inventory' && nameInput && nameInput.type === 'hidden';
        const isPreviousOutput = !executionTypeSelect;
        const isVariable = isPreviousOutput ? true : (executionType === 'variable' || executionType === 'prompt');
        const requiresInventorySelection = isPreviousOutput ? true : (executionType === 'variable');
        inputs.push({
          inputType,
          name,
          quantity: quantity ? parseFloat(quantity) : null,
          unit,
          executionType,
          source_output_id: sourceOutputId || undefined,
          previousOutputDisplayName: previousOutputDisplayName || undefined,
          inventoryPreselected,
          is_variable: isVariable,
          requires_inventory_selection: requiresInventorySelection
        });
      });
    } else {
      inputs = merge ? (prev.inputs || []) : [];
    }

    let outputs;
    if (document.getElementById('guided-outputs-list')) {
      outputs = collectSpaWizardOutputsPayload();
    } else {
      outputs = merge ? (prev.outputs || []) : [];
    }

    let prompts;
    if (document.getElementById('guided-prompts-list')) {
      prompts = collectCurrentPrompts();
    } else {
      prompts = merge ? (prev.prompts || []) : [];
    }

    const batchEl = document.getElementById('guided-prompt-batch-number-mode');
    const evEl = document.getElementById('guided-prompt-evidence-mode');
    const batchNumberMode = batchEl ? batchEl.value : (merge ? (prev.batchNumberMode || 'optional') : 'optional');
    const evidenceMode = evEl ? evEl.value : (merge ? (prev.evidenceMode || 'optional') : 'optional');

    let inputTab = 'inventory';
    const activeTab = document.querySelector('.flow-mode-segment[data-input-tab].flow-mode-segment--active');
    if (activeTab && activeTab.dataset.inputTab) {
      inputTab = activeTab.dataset.inputTab;
    } else if (merge && prev.inputTab) {
      inputTab = prev.inputTab;
    }

    const docInlineTitleEl = document.getElementById('guided-doc-inline-title');
    const docInlineContentEl = document.getElementById('guided-doc-inline-content');
    const docInlineTitle = docInlineTitleEl
      ? docInlineTitleEl.value
      : merge
        ? prev.docInlineTitle || ''
        : '';
    const docInlineContent = docInlineContentEl
      ? docInlineContentEl.value
      : merge
        ? prev.docInlineContent || ''
        : '';

    const urlPid = new URLSearchParams(window.location.search || '').get('id');
    const processIdPersist = urlPid || (merge ? prev.processId || null : null) || null;

    const workflowNameEl = document.getElementById('guided-process-workflow-name');
    let workflowProcessName = workflowNameEl
      ? (workflowNameEl.value || '').trim()
      : merge && prev
        ? (prev.workflowProcessName || '').trim()
        : '';

    let createdStepsOut = JSON.parse(JSON.stringify(createdSteps));
    if (merge && prev) {
      createdStepsOut = preserveCreatedStepsIoFromPrev(prev, createdStepsOut);
    }

    const slug = getFlowWizardPageSlug();
    if (merge && prev) {
      if (slug !== 'inputs' && inputs.length === 0 && (prev.inputs || []).length > 0) {
        inputs = JSON.parse(JSON.stringify(prev.inputs));
      }
      if (slug !== 'outputs' && (!outputs || outputs.length === 0) && (prev.outputs || []).length > 0) {
        outputs = JSON.parse(JSON.stringify(prev.outputs));
      }
      if (slug !== 'evidence-and-prompts' && (!prompts || prompts.length === 0) && (prev.prompts || []).length > 0) {
        prompts = JSON.parse(JSON.stringify(prev.prompts));
      }
    }

    let docFileUpload = null;
    if (pendingGuidedDocFileUpload && pendingGuidedDocFileUpload.base64) {
      docFileUpload = {
        fileName: pendingGuidedDocFileUpload.fileName,
        mime: pendingGuidedDocFileUpload.mime,
        base64: pendingGuidedDocFileUpload.base64
      };
    } else if (merge && prev && prev.docFileUpload && prev.docFileUpload.base64) {
      docFileUpload = JSON.parse(JSON.stringify(prev.docFileUpload));
    }

    return {
      v: 1,
      stepName,
      stepDescription,
      workflowProcessName,
      inputs,
      outputs,
      prompts,
      batchNumberMode,
      evidenceMode,
      inputTab,
      editingStepId: editingStepId || null,
      createdSteps: createdStepsOut,
      docInlineTitle,
      docInlineContent,
      processId: processIdPersist,
      docFileUpload
    };
  }

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
      const payload = {
        v: 1,
        stepName: '',
        stepDescription: '',
        workflowProcessName: (prev.workflowProcessName != null ? String(prev.workflowProcessName) : '').trim(),
        inputs: [],
        outputs: [],
        prompts: [],
        batchNumberMode: 'optional',
        evidenceMode: 'optional',
        inputTab: prev.inputTab || 'inventory',
        editingStepId: null,
        createdSteps: Array.isArray(createdSteps) ? JSON.parse(JSON.stringify(createdSteps)) : [],
        docInlineTitle: '',
        docInlineContent: '',
        processId: pid,
        docFileUpload: null
      };
      sessionStorage.setItem(getProcessFlowSpaStorageKey(), JSON.stringify(payload));
    } catch (e) {
      console.warn('persistClearedWizardDraftState failed', e);
    }
  }

  async function applyOutputPayloadToLastContainer(output) {
    const outputContainers = document.querySelectorAll('#guided-outputs-list > div');
    const lastOutputContainer = outputContainers[outputContainers.length - 1];
    if (!lastOutputContainer || !output) return;
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
        if (warningValueEl) warningValueEl.value = '';
        if (warningUnitEl) warningUnitEl.value = 'days';
      }
    }
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
    const rdEnabled = !!(rd && rd.enabled);
    let rdMode = rdEnabled ? (rd.mode || null) : null;
    if (rdEnabled && !rdMode) {
      rdMode = (rd.set_at_execution || rd.set_during_execution) ? 'set_at_execution' : 'fixed_duration';
    }
    if (readyDateModeEl) {
      readyDateModeEl.value = rdEnabled ? (rdMode || 'fixed_duration') : 'none';
      const rm = readyDateModeEl.value;
      if (readyDateFieldsEl) readyDateFieldsEl.style.display = rm !== 'none' ? 'block' : 'none';
      if (readyDateFixedEl) readyDateFixedEl.style.display = rm === 'fixed_duration' ? 'block' : 'none';
      if (readyDateExecHintEl) readyDateExecHintEl.style.display = rm === 'set_at_execution' ? 'block' : 'none';
      if (readyDateWarnWrapEl) readyDateWarnWrapEl.style.display = rm === 'fixed_duration' ? 'block' : 'none';
    }
    if (rdEnabled && rdMode === 'fixed_duration') {
      const rdVal = rd.duration_value != null ? rd.duration_value : null;
      const rdUnit = rd.duration_unit || 'days';
      if (readyDateValueEl && rdVal != null) readyDateValueEl.value = String(rdVal);
      if (readyDateUnitEl && rdUnit) readyDateUnitEl.value = rdUnit;
      const rwVal = rd.warning_value != null ? rd.warning_value : 0;
      const rwUnit = rd.warning_unit || 'days';
      if (readyDateWarnValueEl) readyDateWarnValueEl.value = String(rwVal);
      if (readyDateWarnUnitEl) readyDateWarnUnitEl.value = rwUnit;
    }
    const complianceWrapEl = lastOutputContainer.querySelector('.guided-output-compliance-wrap');
    if (complianceWrapEl) {
      const expNone = !enabled || (expiryModeEl && expiryModeEl.value === 'none');
      const rdNone = !rdEnabled || (readyDateModeEl && readyDateModeEl.value === 'none');
      const open = !(expNone && rdNone);
      setTimeout(function() {
        if (window.Alpine && typeof Alpine.$data === 'function') {
          try {
            const d = Alpine.$data(complianceWrapEl);
            if (d && typeof d.advancedOpen !== 'undefined') {
              d.advancedOpen = open;
            }
          } catch (e) {}
        }
      }, 0);
    }
    syncOutputExpiryModeSegments(lastOutputContainer);
    syncOutputReadyDateModeSegments(lastOutputContainer);
  }

  window.restoreSpaWizardState = async function() {
    if (!isProcessFlowSpaPage()) return;
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
    if (Array.isArray(data.createdSteps)) {
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
    pendingGuidedDocFileUpload = null;
    if (data.docFileUpload && data.docFileUpload.base64) {
      pendingGuidedDocFileUpload = {
        fileName: data.docFileUpload.fileName,
        mime: data.docFileUpload.mime,
        base64: data.docFileUpload.base64
      };
    }
    const listEl = getGuidedInputListElement('inventory');
    if (listEl) {
      listEl.innerHTML = '';
      selectedInventoryItems.clear();
      selectedPreviousOutputs.clear();
      for (const inp of data.inputs || []) {
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
              const lastIn = getAllGuidedInputElements().slice(-1)[0];
              const typeSelect = lastIn && lastIn.querySelector('.guided-input-execution-type.form-select');
              if (typeSelect && inp.executionType && !((item.inventory_type || item.category) === 'raw_material')) {
                typeSelect.value = inp.executionType;
              }
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
        await window.addGuidedOutput();
        await applyOutputPayloadToLastContainer(out);
      }
    }
    const promptsList = document.getElementById('guided-prompts-list');
    if (promptsList) {
      promptsList.innerHTML = '';
      for (const p of data.prompts || []) {
        window.addGuidedPrompt();
        const promptEls = document.querySelectorAll('#guided-prompts-list > div');
        const lastP = promptEls[promptEls.length - 1];
        if (lastP) {
          const labelIn = lastP.querySelector('.guided-prompt-label');
          const typeSel = lastP.querySelector('.guided-prompt-type');
          const unitSel = lastP.querySelector('.guided-prompt-unit');
          const reqSel = lastP.querySelector('.guided-prompt-required');
          if (labelIn) labelIn.value = p.label || '';
          if (typeSel) typeSel.value = p.type || 'text';
          if (unitSel) unitSel.value = p.unit || '';
          if (reqSel) reqSel.value = p.required ? 'true' : 'false';
        }
      }
    }
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
            if (typeSelect && prompt.type) typeSelect.value = prompt.type;
            const unitSelect = lastPromptContainer.querySelector('.guided-prompt-unit');
            if (unitSelect && prompt.unit) unitSelect.value = prompt.unit;
            const requiredSelect = lastPromptContainer.querySelector('.guided-prompt-required');
            if (requiredSelect) requiredSelect.value = prompt.required !== false ? 'true' : 'false';
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
  function getGuidedInputListElement(type) {
    return document.getElementById('guided-inputs-list-unified');
  }
  
  // All input rows from the unified list (order preserved)
  function getAllGuidedInputElements() {
    const list = document.getElementById('guided-inputs-list-unified');
    return list ? Array.from(list.querySelectorAll(':scope > div')) : [];
  }
  
  // Collect current inputs from form (from both tabs); include requires_inventory_selection so draft restore puts them in the correct tab
  function collectCurrentInputs() {
    const inputs = [];
    const inputElements = getAllGuidedInputElements();
    inputElements.forEach(inputEl => {
      const nameInput = inputEl.querySelector('.guided-input-name');
      let name = '';
      if (nameInput) {
        if (nameInput.classList.contains('searchable-dropdown-input')) {
          name = nameInput.value.trim();
        } else {
          name = nameInput.value.trim();
        }
      }
      
      const quantityInput = inputEl.querySelector('.guided-input-quantity');
      const quantity = quantityInput ? (quantityInput.value || '').trim() : '';
      
      const unitSelect = inputEl.querySelector('.guided-input-unit');
      const unit = unitSelect ? unitSelect.value : '';
      
      const executionTypeSelect = inputEl.querySelector('.guided-input-execution-type');
      const executionType = executionTypeSelect ? executionTypeSelect.value : 'prompt';
      const inputType = inputEl.dataset.inputType || (inputEl.getAttribute && inputEl.getAttribute('data-input-type')) || '';
      const requiresInventorySelection = (inputType === 'inventory' || inputType === 'previous_output') ? true : (executionType === 'variable');
      const isVariable = executionType === 'variable' || executionType === 'prompt';
      
      if (name && unit) {
        inputs.push({
          name: name,
          quantity: quantity ? parseFloat(quantity) : null,
          unit: unit,
          executionType: executionType,
          requires_inventory_selection: requiresInventorySelection,
          is_variable: isVariable
        });
      }
    });
    return inputs;
  }
  
  // Collect current outputs from form
  function collectCurrentOutputs() {
    const outputs = [];
    const outputElements = document.querySelectorAll('#guided-outputs-list > div');
    outputElements.forEach(outputEl => {
      const name = outputEl.querySelector('.guided-output-name')?.value.trim();
      const unitSelect = outputEl.querySelector('.guided-output-unit');
      const unit = unitSelect ? unitSelect.value : '';
      const quantityInput = outputEl.querySelector('.guided-output-quantity');
      const quantity = quantityInput ? (quantityInput.value || '').trim() : '';
      
      if (name && unit) {
        outputs.push({
          name: name,
          unit: unit,
          quantity: quantity ? parseFloat(quantity) : null
        });
      }
    });
    return outputs;
  }
  
  // Collect current prompts from form
  function collectCurrentPrompts() {
    const prompts = [];
    const promptElements = document.querySelectorAll('#guided-prompts-list > div');
    promptElements.forEach(promptEl => {
      const label = promptEl.querySelector('.guided-prompt-label')?.value.trim();
      const typeSelect = promptEl.querySelector('.guided-prompt-type');
      const type = typeSelect ? typeSelect.value : 'text';
      const unitSelect = promptEl.querySelector('.guided-prompt-unit');
      const unit = unitSelect ? (unitSelect.value || '').trim() : null;
      const requiredSelect = promptEl.querySelector('.guided-prompt-required');
      const required = requiredSelect ? requiredSelect.value === 'true' : true;
      
      if (label) {
        prompts.push({
          label: label,
          type: type,
          unit: unit || null,
          required: required
        });
      }
    });
    return prompts;
  }
  
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
        modalDescription.textContent = 'You can expand existing steps to edit them, or use this interactive editor to add additional steps.';
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
          execution_prompts: step.execution_prompts || []
        }));
        
        // Store all steps for summaries (excluding the one we'll restore for editing)
        // We'll restore the most recent step into the form, so don't include it in summaries yet
        const stepsForSummaries = allSteps.slice(0, -1); // All except the last one
        createdSteps = stepsForSummaries;
        
        // Show step summaries (for steps other than the one being edited)
        if (stepsForSummaries.length > 0) {
          updateStepSummaries();
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
                console.log(`Step ${currentStep} display style:`, stepDiv.style.display);
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
                execution_prompts: step.execution_prompts || []
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
          modalDescription.textContent = 'You can expand existing steps to edit them, or use this interactive editor to add additional steps.';
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
    pendingGuidedDocFileUpload = null;
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
  function showExistingStepsView() {
    const existingView = document.getElementById('existing-steps-list-view');
    const existingList = document.getElementById('existing-steps-list');
    const indicators = document.getElementById('create-process-step-indicators');
    if (!existingView || !existingList) return;
    // Hide step flow UI
    if (indicators) indicators.style.display = 'none';
    document.querySelectorAll('.create-process-step').forEach(el => { el.style.display = 'none'; });
    const postCreationOptions = document.getElementById('post-creation-options');
    if (postCreationOptions) postCreationOptions.style.display = 'none';
    const summariesContainer = document.getElementById('step-summaries-container');
    if (summariesContainer) summariesContainer.style.display = 'none';
    // Populate list: step name + Edit button. Use 1-based index for display (same fix as flows2) so single step shows "1" not stored step_number.
    existingList.innerHTML = '';
    const sortedSteps = [...createdSteps].sort((a, b) => (a.step_number || 0) - (b.step_number || 0));
    const spaExisting = document.body && (document.body.getAttribute('data-page') === 'process-flow-spa' || document.body.getAttribute('data-page') === 'process-flow-wizard');
    sortedSteps.forEach((step, index) => {
      const displayNumber = index + 1;
      const row = document.createElement('div');
      if (spaExisting) {
        row.style.cssText =
          'display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 0; background: transparent; border: none; border-radius: 0;' +
          (index > 0 ? 'border-top: 1px solid var(--border-default, #e5e7eb);' : '');
      } else {
        row.style.cssText = 'display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; background: var(--bg-card, #ffffff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md);';
      }
      const left = document.createElement('div');
      left.style.cssText = 'display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0;';
      const stepNum = document.createElement('span');
      stepNum.style.cssText = 'width: 28px; height: 28px; border-radius: 50%; background: var(--primary, #3b82f6); color: white; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 13px; flex-shrink: 0;';
      stepNum.textContent = displayNumber;
      const name = document.createElement('span');
      name.style.cssText = 'font-size: 15px; font-weight: 600; color: var(--text-primary);';
      name.textContent = step.name || 'Unnamed step';
      left.appendChild(stepNum);
      left.appendChild(name);
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'btn btn-secondary btn-sm';
      editBtn.textContent = 'Edit';
      editBtn.onclick = () => window.startEditingStep(step.id);
      row.appendChild(left);
      row.appendChild(editBtn);
      existingList.appendChild(row);
    });
    existingView.style.display = 'block';
  }
  
  // Update step display
  function updateStepDisplay() {
    console.log('updateStepDisplay called, currentStep:', currentStep, 'isRestoringDraft:', isRestoringDraft);
    // When showing the step flow, hide the existing-steps list view and show indicators
    const existingView = document.getElementById('existing-steps-list-view');
    const indicators = document.getElementById('create-process-step-indicators');
    if (existingView) existingView.style.display = 'none';
    if (indicators) indicators.style.display = 'flex';
    
    // If we're restoring a draft and currentStep is 1, but we should be on a different step,
    // don't update (something else will set it correctly)
    // BUT: if isRestoringDraft is true and currentStep is already set to something other than 1, allow it
    if (isRestoringDraft && currentStep === 1) {
      console.warn('updateStepDisplay called with currentStep=1 during draft restoration, skipping to prevent reset');
      return;
    }
    
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
    
    // Show/hide steps - use !important to override inline styles
    for (let i = 1; i <= totalSteps; i++) {
      const stepDiv = document.getElementById(`create-process-step-${i}`);
      if (stepDiv) {
        if (i === currentStep) {
          stepDiv.style.display = 'block';
          console.log(`Showing step ${i}`);
        } else {
          stepDiv.style.display = 'none';
          console.log(`Hiding step ${i}`);
        }
      } else {
        console.warn(`Step div not found: create-process-step-${i}`);
      }
    }
    
    // On inputs step (2): show "Outputs from previous steps" tab only if there is at least one previous step; populate lists
    if (currentStep === 2) {
      if (typeof window.updatePreviousOutputTabVisibility === 'function') window.updatePreviousOutputTabVisibility();
      if (typeof window.renderInventoryItemCards === 'function') window.renderInventoryItemCards();
      if (typeof window.renderPreviousOutputsList === 'function') window.renderPreviousOutputsList();
      updateInputButtonsText();
    }
    
    // On outputs step (3): if no outputs yet, add one so the first output is ready and expanded
    if (currentStep === 3) {
      const outputsList = document.getElementById('guided-outputs-list');
      if (outputsList && outputsList.children.length === 0 && typeof window.addGuidedOutput === 'function') {
        window.addGuidedOutput();
      }
      updateOutputButtonText();
    }

    // On step 4: show attached docs when editing a step; load list and enable delete. Disable inline fields when file is selected.
    const attachedDocsSection = document.getElementById('guided-step-attached-docs-section');
    const attachedDocsList = document.getElementById('guided-step-docs-list');
    if (attachedDocsSection && attachedDocsList) {
      if (editingStepId) {
        attachedDocsSection.style.display = 'block';
        loadAttachedStepDocs(editingStepId);
      } else {
        attachedDocsSection.style.display = 'none';
        attachedDocsList.innerHTML = '';
      }
    }
    if (currentStep === 4) {
      ensureDocFileListener();
      syncDocInlineDisabledState();
      syncStep4ModeSegments();
      updateStep4SummaryBar();
    }
  }

  function formatStep4ModeLabel(value) {
    if (value === 'required') return 'Required';
    if (value === 'optional') return 'Optional';
    return 'Off';
  }

  function buildOutputModeSegmentRow(modeKind, spec) {
    const wrap = document.createElement('div');
    wrap.className = 'flow-mode-segmented';
    wrap.setAttribute('role', 'group');
    if (spec.ariaLabel) wrap.setAttribute('aria-label', spec.ariaLabel);
    spec.options.forEach(function(opt) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'flow-mode-segment';
      b.setAttribute('data-output-mode-kind', modeKind);
      b.setAttribute('data-value', opt.value);
      b.textContent = opt.label;
      wrap.appendChild(b);
    });
    return wrap;
  }

  function syncOutputExpiryModeSegments(outputRow) {
    if (!outputRow) return;
    const sel = outputRow.querySelector('.guided-output-expiry-mode');
    if (!sel) return;
    outputRow.querySelectorAll('.flow-mode-segment[data-output-mode-kind="expiry"]').forEach(function(btn) {
      const on = btn.getAttribute('data-value') === sel.value;
      btn.classList.toggle('flow-mode-segment--active', !!on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function syncOutputReadyDateModeSegments(outputRow) {
    if (!outputRow) return;
    const sel = outputRow.querySelector('.guided-output-ready-date-mode');
    if (!sel) return;
    outputRow.querySelectorAll('.flow-mode-segment[data-output-mode-kind="ready_date"]').forEach(function(btn) {
      const on = btn.getAttribute('data-value') === sel.value;
      btn.classList.toggle('flow-mode-segment--active', !!on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function initGuidedOutputsListModeSegments() {
    const list = document.getElementById('guided-outputs-list');
    if (!list || list.dataset.flowModeOutputInit === '1') return;
    list.dataset.flowModeOutputInit = '1';
    list.addEventListener('click', function(ev) {
      const btn = ev.target.closest('.flow-mode-segment[data-output-mode-kind]');
      if (!btn || !list.contains(btn)) return;
      ev.preventDefault();
      const row = btn.closest('[id^="guided-output-"]');
      if (!row) return;
      const kind = btn.getAttribute('data-output-mode-kind');
      const val = btn.getAttribute('data-value');
      const sel = kind === 'expiry'
        ? row.querySelector('.guided-output-expiry-mode')
        : row.querySelector('.guided-output-ready-date-mode');
      if (sel && val != null) {
        sel.value = val;
        sel.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
  }

  function applyNewMaterialExecutionExplanation(explanationEl, inputId, value) {
    const explanation = (explanationEl && explanationEl.nodeType === 1)
      ? explanationEl
      : document.getElementById('guided-input-explanation-' + inputId);
    if (!explanation) return;
    if (value === 'variable') {
      explanation.innerHTML = '<strong>At execution:</strong> Quantity and unit are confirmed when this step is run.';
    } else if (value === 'static') {
      explanation.innerHTML = '<strong>Fixed:</strong> The same quantity and unit are used every execution.';
    } else {
      explanation.innerHTML = '<strong>Prompt:</strong> Operators enter quantity (and unit if needed) each time.';
    }
  }

  function syncGuidedNewInputExecutionSegments(container) {
    if (!container || container.dataset.inputType !== 'new') return;
    const hidden = container.querySelector('.guided-input-execution-type');
    const inputId = container.id || '';
    const v = hidden && hidden.value ? hidden.value : 'variable';
    container.querySelectorAll('.flow-mode-segment[data-guided-input-exec]').forEach(function(btn) {
      const on = btn.getAttribute('data-value') === v;
      btn.classList.toggle('flow-mode-segment--active', !!on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    const explanationDiv = container.querySelector('[id^="guided-input-explanation-"]');
    applyNewMaterialExecutionExplanation(explanationDiv, inputId, v);
  }

  function buildNewMaterialExecutionTypeField(inputId) {
    const typeField = document.createElement('div');
    const typeLabel = document.createElement('label');
    typeLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    typeLabel.textContent = 'How quantities are captured';
    typeField.appendChild(typeLabel);

    const hiddenType = document.createElement('input');
    hiddenType.type = 'hidden';
    hiddenType.className = 'guided-input-execution-type';
    hiddenType.value = 'variable';
    typeField.appendChild(hiddenType);

    const segWrap = document.createElement('div');
    segWrap.className = 'flow-mode-segmented guided-input-exec-segmented';
    segWrap.setAttribute('role', 'group');
    segWrap.setAttribute('aria-label', 'How quantities are captured');
    [
      { value: 'variable', label: 'At execution' },
      { value: 'static', label: 'Fixed' },
      { value: 'prompt', label: 'Prompt' }
    ].forEach(function(opt) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'flow-mode-segment';
      b.setAttribute('data-guided-input-exec', '1');
      b.setAttribute('data-value', opt.value);
      b.textContent = opt.label;
      segWrap.appendChild(b);
    });
    typeField.appendChild(segWrap);

    const explanationDiv = document.createElement('div');
    explanationDiv.style.cssText = 'margin-top: 8px; padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); font-size: 12px; color: var(--text-secondary); line-height: 1.4;';
    explanationDiv.id = 'guided-input-explanation-' + inputId;
    typeField.appendChild(explanationDiv);

    hiddenType.addEventListener('change', function() {
      applyNewMaterialExecutionExplanation(explanationDiv, inputId, hiddenType.value);
    });
    applyNewMaterialExecutionExplanation(explanationDiv, inputId, hiddenType.value);

    return typeField;
  }

  function initGuidedNewInputExecutionSegments() {
    const list = document.getElementById('guided-inputs-list-unified');
    if (!list || list.dataset.guidedNewExecInit === '1') return;
    list.dataset.guidedNewExecInit = '1';
    list.addEventListener('click', function(ev) {
      const btn = ev.target.closest('.flow-mode-segment[data-guided-input-exec]');
      if (!btn || !list.contains(btn)) return;
      const row = btn.closest('[id^="guided-input-"]');
      if (!row || row.dataset.inputType !== 'new') return;
      ev.preventDefault();
      const hidden = row.querySelector('.guided-input-execution-type');
      const val = btn.getAttribute('data-value');
      if (hidden && val != null) {
        hidden.value = val;
        hidden.dispatchEvent(new Event('change', { bubbles: true }));
      }
      syncGuidedNewInputExecutionSegments(row);
    });
  }

  function syncStep4ModeSegments() {
    const batchSel = document.getElementById('guided-prompt-batch-number-mode');
    const evSel = document.getElementById('guided-prompt-evidence-mode');
    document.querySelectorAll('#create-process-step-4 .flow-mode-segment[data-step4-mode-target="batch"]').forEach(function(btn) {
      const on = batchSel && btn.getAttribute('data-value') === batchSel.value;
      btn.classList.toggle('flow-mode-segment--active', !!on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    document.querySelectorAll('#create-process-step-4 .flow-mode-segment[data-step4-mode-target="evidence"]').forEach(function(btn) {
      const on = evSel && btn.getAttribute('data-value') === evSel.value;
      btn.classList.toggle('flow-mode-segment--active', !!on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function updateStep4SummaryBar() {
    const batchEl = document.getElementById('guided-prompt-batch-number-mode');
    const evEl = document.getElementById('guided-prompt-evidence-mode');
    if (!batchEl || !evEl) return;
    const b = formatStep4ModeLabel(batchEl.value);
    const e = formatStep4ModeLabel(evEl.value);
    const preview = document.getElementById('step4-trace-collapsed-preview');
    if (preview) preview.textContent = 'Batch: ' + b + ' • Evidence: ' + e;
    const n = document.querySelectorAll('#guided-prompts-list > div').length;
    const hint = document.getElementById('step4-prompts-section-hint');
    if (hint) hint.textContent = n + (n === 1 ? ' prompt' : ' prompts') + ' configured';
  }
  window.updateStep4SummaryBar = updateStep4SummaryBar;

  function initStep4SegmentControls() {
    const root = document.getElementById('create-process-step-4');
    if (!root || root.dataset.step4UiInit === '1') return;
    root.dataset.step4UiInit = '1';
    root.addEventListener('click', function(ev) {
      const btn = ev.target.closest('.flow-mode-segment[data-step4-mode-target]');
      if (!btn || !root.contains(btn)) return;
      ev.preventDefault();
      const target = btn.getAttribute('data-step4-mode-target');
      const val = btn.getAttribute('data-value');
      const selId = target === 'batch' ? 'guided-prompt-batch-number-mode' : 'guided-prompt-evidence-mode';
      const sel = document.getElementById(selId);
      if (sel && val) {
        sel.value = val;
        sel.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
    ['guided-prompt-batch-number-mode', 'guided-prompt-evidence-mode'].forEach(function(id) {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('change', function() {
          syncStep4ModeSegments();
          updateStep4SummaryBar();
        });
      }
    });
    syncStep4ModeSegments();
    updateStep4SummaryBar();
  }

  // When a file is selected for step docs, disable inline title/content so file wins and UX is clear (no silent ignore).
  function syncDocInlineDisabledState() {
    const docFileInput = document.getElementById('guided-doc-file');
    const docInlineTitle = document.getElementById('guided-doc-inline-title');
    const docInlineContent = document.getElementById('guided-doc-inline-content');
    const hasFile = docFileInput && docFileInput.files && docFileInput.files.length > 0;
    if (docInlineTitle) docInlineTitle.disabled = !!hasFile;
    if (docInlineContent) docInlineContent.disabled = !!hasFile;
  }
  function ensureDocFileListener() {
    const docFileInput = document.getElementById('guided-doc-file');
    if (!docFileInput || docFileInput.dataset.flowWizardDocListener === '1') return;
    docFileInput.dataset.flowWizardDocListener = '1';
    docFileInput.addEventListener('change', function() {
      syncDocInlineDisabledState();
      pendingGuidedDocFileUpload = null;
      const f = docFileInput.files && docFileInput.files[0];
      if (!f) {
        if (typeof window.persistSpaWizardState === 'function') window.persistSpaWizardState();
        return;
      }
      const maxB64 = 1.5 * 1024 * 1024;
      if (f.size > maxB64) {
        if (window.showNotification) {
          window.showNotification(
            'warning',
            'File too large',
            'Only files up to 1.5MB can be carried to the summary step in the browser. Use inline instructions instead, or split the document.'
          );
        }
        docFileInput.value = '';
        syncDocInlineDisabledState();
        return;
      }
      const reader = new FileReader();
      reader.onload = function() {
        const dataUrl = reader.result;
        const s = String(dataUrl);
        const comma = s.indexOf(',');
        const b64 = comma >= 0 ? s.slice(comma + 1) : '';
        pendingGuidedDocFileUpload = {
          fileName: f.name,
          mime: f.type || 'application/octet-stream',
          base64: b64
        };
        if (typeof window.persistSpaWizardState === 'function') window.persistSpaWizardState();
      };
      reader.onerror = function() {
        pendingGuidedDocFileUpload = null;
      };
      reader.readAsDataURL(f);
    });
  }
  window.ensureGuidedDocFileListener = ensureDocFileListener;

  // Expose for SPA page so it can sync step display without opening the modal
  window.updateStepDisplay = updateStepDisplay;

  // Load attached documentation for the current step (step 4) and render list with delete
  async function loadAttachedStepDocs(stepId) {
    const container = document.getElementById('guided-step-docs-list');
    if (!container) return;
    container.innerHTML = 'Loading…';
    try {
      const res = await CoreAPI.getStepDocumentation(stepId);
      const docs = (res && res.documents) ? res.documents : [];
      container.innerHTML = '';
      if (docs.length === 0) {
        const empty = document.createElement('p');
        empty.style.cssText = 'color: var(--text-tertiary, #9ca3af); margin: 0; font-size: 13px;';
        empty.textContent = 'No documentation attached.';
        container.appendChild(empty);
      } else {
        docs.forEach(function(doc) {
          const row = document.createElement('div');
          row.style.cssText = 'display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 12px; background: var(--bg-card, #fff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md); margin-bottom: 6px;';
          const label = document.createElement('span');
          label.textContent = doc.title || (doc.content_markdown ? 'Inline doc' : 'File');
          label.style.cssText = 'flex: 1; min-width: 0; font-size: 13px; color: var(--text-primary);';
            const delBtn = document.createElement('button');
            delBtn.type = 'button';
            delBtn.className = 'btn btn-secondary btn-sm';
            delBtn.textContent = 'Delete';
            delBtn.onclick = function() {
              if (typeof window.showDeleteDocConfirmModal === 'function') {
                window.showDeleteDocConfirmModal(doc.id, row);
              } else {
                if (confirm('Remove this documentation from the step?')) {
                  CoreAPI.deleteProcessDoc(doc.id).then(function() {
                    row.remove();
                    if (window.showNotification) window.showNotification('success', 'Removed', 'Documentation removed.');
                  }).catch(function(e) {
                    if (window.showNotification) window.showNotification('error', 'Error', e.message || 'Could not delete.');
                  });
                }
              }
            };
          row.appendChild(label);
          row.appendChild(delBtn);
          container.appendChild(row);
        });
      }
    } catch (e) {
      container.innerHTML = '';
      const err = document.createElement('p');
      err.style.cssText = 'color: var(--error, #dc2626); margin: 0; font-size: 13px;';
      err.textContent = 'Could not load documentation.';
      container.appendChild(err);
    }
  }

  // Delete-doc confirmation modal (in-app, not browser confirm). Lazy-init listeners when modal is first shown so DOM is ready.
  let deleteDocModalInitialized = false;
  function ensureDeleteDocModalListeners() {
    if (deleteDocModalInitialized) return;
    const modalEl = document.getElementById('delete-doc-confirm-modal');
    const cancelBtn = document.getElementById('delete-doc-confirm-cancel');
    const removeBtn = document.getElementById('delete-doc-confirm-remove');
    if (!modalEl || !cancelBtn || !removeBtn) return;
    deleteDocModalInitialized = true;
    cancelBtn.addEventListener('click', function() {
      modalEl.style.display = 'none';
      pendingDeleteDoc = null;
    });
    removeBtn.addEventListener('click', async function() {
      if (!pendingDeleteDoc) return;
      const { docId, row } = pendingDeleteDoc;
      pendingDeleteDoc = null;
      modalEl.style.display = 'none';
      try {
        await CoreAPI.deleteProcessDoc(docId);
        if (row && row.parentNode) row.remove();
        if (window.showNotification) window.showNotification('success', 'Removed', 'Documentation removed.');
      } catch (e) {
        if (window.showNotification) window.showNotification('error', 'Error', e.message || 'Could not delete.');
      }
    });
  }
  window.showDeleteDocConfirmModal = function(docId, row) {
    const modalEl = document.getElementById('delete-doc-confirm-modal');
    if (!modalEl) return;
    ensureDeleteDocModalListeners();
    pendingDeleteDoc = { docId, row };
    modalEl.style.display = 'flex';
  };

  // Validate inventory inputs (quantity & unit required, quantity must be > 0)
  function validateInventoryInputs() {
    const list = document.getElementById('guided-inputs-list-unified');
    if (!list) return { valid: true };
    const rows = list.querySelectorAll(':scope > div[data-input-type="inventory"], :scope > div[data-input-type="previous_output"]');
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      const quantityInput = row.querySelector('.guided-input-quantity');
      const unitSelect = row.querySelector('.guided-input-unit');
      if (!quantityInput && !unitSelect) continue;
      const quantityStr = quantityInput ? (quantityInput.value || '').trim() : '';
      const unit = unitSelect ? (unitSelect.value || '').trim() : '';
      if (quantityStr === '' || unit === '') {
        return {
          valid: false,
          message: 'Please fill Quantity and Unit for all inventory items. Both are required.'
        };
      }
      const quantityNum = parseFloat(quantityStr);
      if (isNaN(quantityNum) || quantityNum <= 0) {
        return {
          valid: false,
          message: 'Quantity must be greater than 0 for all inventory items.'
        };
      }
    }
    return { valid: true };
  }

  // Validate fixed-duration outputs: warning must not exceed expiry. Shared helper (single source of truth).
  function validateFixedExpiryWarning(outputs) {
    try {
      if (window.CustomExpiryValidation && typeof window.CustomExpiryValidation.validateFixedExpiryWarning === 'function') {
        return window.CustomExpiryValidation.validateFixedExpiryWarning(outputs);
      }
    } catch (e) {}
    return { valid: true };
  }
  
  /** First wizard screen (process overview): require process name, then go to step-name. */
  window.goFromProcessOverviewToStepName = function() {
    const el = document.getElementById('guided-process-workflow-name');
    const name = el ? String(el.value || '').trim() : '';
    if (!name) {
      if (window.showNotification) {
        window.showNotification('error', 'Process name required', 'Enter a name for this process workflow.');
      } else {
        alert('Please enter a process name.');
      }
      return;
    }
    if (typeof window.persistSpaWizardState === 'function') {
      window.persistSpaWizardState();
    }
    window.location.href = '/core/flows/create/step-name' + (window.location.search || '');
  };

  // Navigate to next step
  window.createProcessNextStep = function() {
    if (currentStep === 1) {
      // Validate step 1
      const stepName = document.getElementById('guided-step-name').value.trim();
      if (!stepName) {
        if (window.showNotification) {
          window.showNotification('error', 'Step name required', 'Please enter a step name.');
        } else {
          alert('Please enter a step name');
        }
        return;
      }
    }
    if (currentStep === 2) {
      const result = validateInventoryInputs();
      if (!result.valid) {
        if (window.showNotification) {
          window.showNotification('error', 'Inventory inputs required', result.message);
        } else {
          alert(result.message);
        }
        return;
      }
    }
    if (currentStep === 3) {
      // Validate per-output custom expiry: warn-before must not exceed fixed expiry duration
      const outputElements = document.querySelectorAll('#guided-outputs-list > div');
      const outputsForValidation = [];
      outputElements.forEach(function(outputEl) {
        const name = outputEl.querySelector('.guided-output-name')?.value.trim() || '';
        const expiryModeEl = outputEl.querySelector('.guided-output-expiry-mode');
        const expiryValueEl = outputEl.querySelector('.guided-output-expiry-value');
        const expiryUnitEl = outputEl.querySelector('.guided-output-expiry-unit');
        const warningValueEl = outputEl.querySelector('.guided-output-expiry-warning-value');
        const warningUnitEl = outputEl.querySelector('.guided-output-expiry-warning-unit');
        const expiryMode = expiryModeEl ? expiryModeEl.value : 'none';
        const expiryValueRaw = expiryValueEl && expiryMode === 'fixed_duration' ? expiryValueEl.value.trim() : '';
        const expiryValue = expiryValueRaw !== '' ? parseInt(expiryValueRaw, 10) : null;
        const expiryUnit = expiryUnitEl && expiryMode === 'fixed_duration' ? ((expiryUnitEl.value || 'days') + '').trim() : 'days';
        const warningValueRaw = warningValueEl && expiryMode !== 'none' ? warningValueEl.value.trim() : '';
        const warningValue = warningValueRaw !== '' ? parseInt(warningValueRaw, 10) : 7;
        const warningUnit = warningUnitEl && expiryMode !== 'none' ? ((warningUnitEl.value || 'days') + '').trim() : 'days';
        const outObj = { name: name };
        if (expiryMode === 'fixed_duration' && expiryValue > 0) {
          outObj.extra_data = {
            custom_expiry: {
              enabled: true,
              mode: 'fixed_duration',
              duration_value: expiryValue,
              duration_unit: (expiryUnit || 'days').trim(),
              warning_value: (typeof warningValue === 'number' && !isNaN(warningValue) && warningValue >= 0) ? warningValue : 7,
              warning_unit: (warningUnit || 'days').trim(),
              expiry_at: null,
              rule_type: 'custom_output_expiry'
            }
          };
        }
        outputsForValidation.push(outObj);
      });

      const expiryValidation = validateFixedExpiryWarning(outputsForValidation);
      if (!expiryValidation.valid) {
        if (window.showNotification) {
          window.showNotification('error', 'Invalid expiry settings', expiryValidation.message);
        } else {
          alert(expiryValidation.message);
        }
        // Expand + scroll to the problematic output to guide the user
        try {
          const match = Array.from(outputElements).find(function(el) {
            const n = el.querySelector('.guided-output-name')?.value.trim() || '';
            return expiryValidation.outputName && n === expiryValidation.outputName;
          });
          if (match) {
            if (match.dataset && match.dataset.expanded === 'false' && typeof toggleOutputExpand === 'function') {
              toggleOutputExpand(match.id);
            }
            match.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        } catch (e) {}
        return;
      }
      // Validate ready date: fixed_duration requires duration > 0 and warn <= ready period
      const readyDateValidation = window.ReadyDateValidation;
      const validateFixedReadyDateWarning = (readyDateValidation && typeof readyDateValidation.validateFixedReadyDateWarning === 'function')
        ? readyDateValidation.validateFixedReadyDateWarning
        : function () { return { valid: true }; };
      const outputsWithReadyDate = [];
      outputElements.forEach(function (outputEl) {
        const name = outputEl.querySelector('.guided-output-name')?.value.trim() || '';
        const readyDateModeEl = outputEl.querySelector('.guided-output-ready-date-mode');
        const readyDateValueEl = outputEl.querySelector('.guided-output-ready-date-value');
        const readyDateUnitEl = outputEl.querySelector('.guided-output-ready-date-unit');
        const readyDateWarnValueEl = outputEl.querySelector('.guided-output-ready-date-warning-value');
        const readyDateWarnUnitEl = outputEl.querySelector('.guided-output-ready-date-warning-unit');
        const mode = readyDateModeEl ? readyDateModeEl.value : 'none';
        const durationValue = (readyDateValueEl && mode === 'fixed_duration') ? parseInt(readyDateValueEl.value, 10) : null;
        const durationUnit = (readyDateUnitEl && mode === 'fixed_duration') ? (readyDateUnitEl.value || 'days').trim() : 'days';
        const warningValue = (readyDateWarnValueEl && mode === 'fixed_duration') ? parseInt(readyDateWarnValueEl.value, 10) : 0;
        const warningUnit = (readyDateWarnUnitEl && mode === 'fixed_duration') ? (readyDateWarnUnitEl.value || 'days').trim() : 'days';
        const outObj = { name: name };
        if (mode === 'fixed_duration' && durationValue > 0) {
          outObj.extra_data = {
            ready_date: {
              enabled: true,
              mode: 'fixed_duration',
              duration_value: durationValue,
              duration_unit: durationUnit,
              warning_value: (typeof warningValue === 'number' && !isNaN(warningValue) && warningValue >= 0) ? warningValue : 0,
              warning_unit: warningUnit,
              rule_type: 'custom_ready_date'
            }
          };
        }
        outputsWithReadyDate.push(outObj);
      });
      const rdValidation = validateFixedReadyDateWarning(outputsWithReadyDate);
      if (!rdValidation.valid) {
        if (window.showNotification) {
          window.showNotification('error', 'Invalid ready date settings', rdValidation.message);
        } else {
          alert(rdValidation.message);
        }
        try {
          const match = Array.from(outputElements).find(function (el) {
            const n = el.querySelector('.guided-output-name')?.value.trim() || '';
            return rdValidation.outputName && n === rdValidation.outputName;
          });
          if (match) {
            if (match.dataset && match.dataset.expanded === 'false' && typeof toggleOutputExpand === 'function') {
              toggleOutputExpand(match.id);
            }
            match.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        } catch (e) {}
        return;
      }
      for (let i = 0; i < outputElements.length; i++) {
        const outputEl = outputElements[i];
        const readyDateModeEl = outputEl.querySelector('.guided-output-ready-date-mode');
        const readyDateValueEl = outputEl.querySelector('.guided-output-ready-date-value');
        const mode = readyDateModeEl ? readyDateModeEl.value : 'none';
        if (mode === 'fixed_duration') {
          if (!readyDateValueEl || !readyDateValueEl.value.trim() || parseInt(readyDateValueEl.value, 10) <= 0) {
            const outputName = outputEl.querySelector('.guided-output-name')?.value.trim() || '';
            if (window.showNotification) {
              window.showNotification('error', 'Ready date required', 'Output "' + outputName + '" has fixed ready date; please set a positive period.');
            } else {
              alert('Output "' + outputName + '" has fixed ready date; please set a positive period.');
            }
            try {
              if (outputEl.dataset && outputEl.dataset.expanded === 'false' && typeof toggleOutputExpand === 'function') {
                toggleOutputExpand(outputEl.id);
              }
              outputEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            } catch (e) {}
            return;
          }
        }
      }
      // When both expiry and ready date are set (fixed duration), expiry cannot be before ready date (shared config)
      const outputsWithBothExpiryAndReady = [];
      outputElements.forEach(function (outputEl) {
        const name = outputEl.querySelector('.guided-output-name')?.value.trim() || '';
        const expiryModeEl = outputEl.querySelector('.guided-output-expiry-mode');
        const expiryValueEl = outputEl.querySelector('.guided-output-expiry-value');
        const expiryUnitEl = outputEl.querySelector('.guided-output-expiry-unit');
        const expiryWarningValueEl = outputEl.querySelector('.guided-output-expiry-warning-value');
        const expiryWarningUnitEl = outputEl.querySelector('.guided-output-expiry-warning-unit');
        const readyDateModeEl = outputEl.querySelector('.guided-output-ready-date-mode');
        const readyDateValueEl = outputEl.querySelector('.guided-output-ready-date-value');
        const readyDateUnitEl = outputEl.querySelector('.guided-output-ready-date-unit');
        const readyDateWarnValueEl = outputEl.querySelector('.guided-output-ready-date-warning-value');
        const readyDateWarnUnitEl = outputEl.querySelector('.guided-output-ready-date-warning-unit');
        const expiryMode = expiryModeEl ? expiryModeEl.value : 'none';
        const readyMode = readyDateModeEl ? readyDateModeEl.value : 'none';
        if (expiryMode !== 'fixed_duration' || readyMode !== 'fixed_duration') return;
        const expiryValue = (expiryValueEl && expiryValueEl.value.trim()) ? parseInt(expiryValueEl.value, 10) : 0;
        if (!expiryValue || isNaN(expiryValue)) return;
        const expiryUnit = (expiryUnitEl && expiryUnitEl.value) || 'days';
        const expiryWarningValue = (expiryWarningValueEl && expiryWarningValueEl.value.trim() !== '') ? parseInt(expiryWarningValueEl.value, 10) : 0;
        const expiryWarningUnit = (expiryWarningUnitEl && expiryWarningUnitEl.value) || 'days';
        const readyValue = (readyDateValueEl && readyDateValueEl.value.trim()) ? parseInt(readyDateValueEl.value, 10) : 0;
        const readyUnit = (readyDateUnitEl && readyDateUnitEl.value) || 'days';
        const readyWarningValue = (readyDateWarnValueEl && readyDateWarnValueEl.value.trim() !== '') ? parseInt(readyDateWarnValueEl.value, 10) : 0;
        const readyWarningUnit = (readyDateWarnUnitEl && readyDateWarnUnitEl.value) || 'days';
        outputsWithBothExpiryAndReady.push({
          name: name,
          extra_data: {
            custom_expiry: { enabled: true, mode: 'fixed_duration', duration_value: expiryValue, duration_unit: expiryUnit, warning_value: isNaN(expiryWarningValue) ? 0 : expiryWarningValue, warning_unit: expiryWarningUnit },
            ready_date: { enabled: true, mode: 'fixed_duration', duration_value: readyValue, duration_unit: readyUnit, warning_value: isNaN(readyWarningValue) ? 0 : readyWarningValue, warning_unit: readyWarningUnit }
          }
        });
      });
      if (outputsWithBothExpiryAndReady.length > 0 && window.ExpiryReadyDateValidation && typeof window.ExpiryReadyDateValidation.validateExpiryAfterReadyDuration === 'function') {
        const erResult = window.ExpiryReadyDateValidation.validateExpiryAfterReadyDuration(outputsWithBothExpiryAndReady);
        if (!erResult.valid) {
          if (window.showNotification) {
            window.showNotification('error', 'Expiry and ready date', erResult.message);
          } else {
            alert(erResult.message);
          }
          try {
            const match = Array.from(outputElements).find(function (el) {
              const n = el.querySelector('.guided-output-name')?.value.trim() || '';
              return erResult.outputName && n === erResult.outputName;
            });
            if (match) {
              if (match.dataset && match.dataset.expanded === 'false' && typeof toggleOutputExpand === 'function') {
                toggleOutputExpand(match.id);
              }
              match.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
          } catch (e) {}
          return;
        }
      }
    }
    
    if (isProcessFlowSpaPage()) {
      if (typeof window.persistSpaWizardState === 'function') {
        window.persistSpaWizardState();
      }
      if (currentStep < totalSteps) {
        const nextSlug = { 1: 'inputs', 2: 'outputs', 3: 'evidence-and-prompts' }[currentStep];
        if (nextSlug) {
          window.location.href = '/core/flows/create/' + nextSlug + (window.location.search || '');
        }
      }
      return;
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
      
      // Always try to load all inventory types to give users full selection
      // 1. Try loading with processId (if available)
      if (processId) {
        try {
          const inventoryData = await CoreAPI.getInventory(null, processId);
          const processItems = inventoryData.inventory_items || [];
          items.push(...processItems);
          console.log('Loaded inventory with processId:', processItems.length);
        } catch (err) {
          console.warn('Failed to load inventory with processId:', err);
        }
      }
      
      // 2. Always load raw materials (these are commonly used)
      try {
        const rawMaterialsData = await CoreAPI.getInventory('raw_material');
        const rawItems = rawMaterialsData.inventory_items || [];
        items.push(...rawItems);
        console.log('Loaded raw materials:', rawItems.length);
      } catch (err) {
        console.warn('Failed to load raw materials:', err);
      }
      
      // 3. Try loading all inventory without filters (catch-all)
      try {
        const allInventoryData = await CoreAPI.getInventory();
        const allItems = allInventoryData.inventory_items || [];
        items.push(...allItems);
        console.log('Loaded all inventory:', allItems.length);
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
    
    dropdownContainer.innerHTML = `
      <input 
        type="text" 
        class="form-input guided-input-name searchable-dropdown-input" 
        placeholder="${placeholder}"
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
  function collapseAllInputs(exceptId = null) {
    const allInputs = getAllGuidedInputElements();
    allInputs.forEach(inputEl => {
      if (inputEl.id !== exceptId) {
        const contentArea = inputEl.querySelector('.guided-input-content');
        const expandIcon = inputEl.querySelector('.guided-input-expand-icon');
        const expandHint = inputEl.querySelector('.guided-input-expand-hint');
        if (contentArea && expandIcon) {
          contentArea.style.display = 'none';
          expandIcon.style.transform = 'rotate(0deg)';
          inputEl.dataset.expanded = 'false';
          if (expandHint) expandHint.textContent = '(click to expand)';
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
        const expandHint = outputEl.querySelector('.guided-output-expand-hint');
        if (contentArea && expandIcon) {
          contentArea.style.display = 'none';
          expandIcon.style.transform = 'rotate(0deg)';
          outputEl.dataset.expanded = 'false';
          if (expandHint) expandHint.textContent = '(click to expand)';
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
    const expandHint = inputEl.querySelector('.guided-input-expand-hint');
    if (!contentArea || !expandIcon) return;
    
    const isExpanded = inputEl.dataset.expanded === 'true';
    if (isExpanded) {
      contentArea.style.display = 'none';
      expandIcon.style.transform = 'rotate(0deg)';
      inputEl.dataset.expanded = 'false';
      if (expandHint) expandHint.textContent = '(click to expand)';
    } else {
      contentArea.style.display = 'block';
      expandIcon.style.transform = 'rotate(180deg)';
      inputEl.dataset.expanded = 'true';
      if (expandHint) expandHint.textContent = '(click to collapse)';
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
    const expandHint = outputEl.querySelector('.guided-output-expand-hint');
    if (!contentArea || !expandIcon) return;
    
    const isExpanded = outputEl.dataset.expanded === 'true';
    if (isExpanded) {
      contentArea.style.display = 'none';
      expandIcon.style.transform = 'rotate(0deg)';
      outputEl.dataset.expanded = 'false';
      if (expandHint) expandHint.textContent = '(click to expand)';
    } else {
      contentArea.style.display = 'block';
      expandIcon.style.transform = 'rotate(180deg)';
      outputEl.dataset.expanded = 'true';
      if (expandHint) expandHint.textContent = '(click to collapse)';
      // Collapse all other outputs
      collapseAllOutputs(outputId);
    }
  }
  
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
      if (data.requires_inventory_selection) executionTypeSelect.value = 'variable';
      else if (data.is_variable === false) executionTypeSelect.value = 'static';
      else executionTypeSelect.value = 'prompt';
      executionTypeSelect.dispatchEvent(new Event('change'));
    }
    if (type === 'new') syncGuidedNewInputExecutionSegments(container);
    if (data.source_output_id) container.dataset.sourceOutputId = data.source_output_id;
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
      // Pre-selected item (e.g. from inventory cards): show quantity, unit, execution type only; no dropdown
      if (type === 'inventory' && preSelectedItem && preSelectedItem.name) {
        nameDisplay.textContent = preSelectedItem.name;
        nameDisplay.style.display = 'inline';
        titleSpan.style.display = 'none';
        selectedInventoryItems.add(preSelectedItem.name);
        
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
        const isRaw = (preSelectedItem.inventory_type || preSelectedItem.category) === 'raw_material';
        // Raw materials: hide Execution type, show helper only. Intermediate/final: show "Select inventory at execution" dropdown.
        if (isRaw) {
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
        } else {
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
          staticOption.textContent = 'Use exact input every execution';
          typeSelect.appendChild(staticOption);
          typeField.appendChild(typeSelect);
          const explanationDiv = document.createElement('div');
          explanationDiv.style.cssText = 'margin-top: 8px; padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); font-size: 12px; color: var(--text-secondary); line-height: 1.4;';
          explanationDiv.id = `guided-input-explanation-${inputId}`;
          explanationDiv.textContent = inventoryExecutionHelperText(preSelectedItem);
          typeField.appendChild(explanationDiv);
          typeSelect.addEventListener('change', function() {
            const explanation = document.getElementById(`guided-input-explanation-${inputId}`);
            if (explanation) {
              explanation.textContent = this.value === 'variable'
                ? inventoryExecutionHelperText(preSelectedItem)
                : 'Use this exact input every execution: The system will use the same quantity and unit for every execution without prompting.';
            }
          });
          if (preSelectedItem.executionType === 'variable' || preSelectedItem.executionType === 'static') {
            typeSelect.value = preSelectedItem.executionType;
          }
        }
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
            quantity: output.quantity
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
          } else {
            selectedInventoryItems.add(item.name);
          }
          // Update the dropdown to exclude this item from other inputs
          updateInventoryDropdowns();
          // Update name display in header directly with the item name (not displayName)
          if (item.name) {
            nameDisplay.textContent = item.name;
            nameDisplay.style.display = 'inline';
            titleSpan.style.display = 'none';
          }
          // Raw materials only: hide Execution type box, show only helper. Intermediate/final: keep "Select inventory at execution" visible.
          if (type === 'inventory') {
            const typeSelect = inputContainer.querySelector('.guided-input-execution-type.form-select');
            const isRaw = (item.inventory_type || item.category) === 'raw_material';
            if (typeSelect && isRaw) {
              const typeField = typeSelect.parentElement;
              if (typeField) {
                const label = typeField.querySelector('label');
                if (label) label.style.display = 'none';
                typeSelect.style.display = 'none';
                const hiddenType = document.createElement('input');
                hiddenType.type = 'hidden';
                hiddenType.className = 'guided-input-execution-type';
                hiddenType.value = 'variable';
                typeField.appendChild(hiddenType);
                const explanation = document.getElementById('guided-input-explanation-' + inputId);
                if (explanation) {
                  explanation.style.marginTop = '0';
                  explanation.textContent = inventoryExecutionHelperText(item);
                }
              }
            } else if (typeSelect && !isRaw) {
              typeSelect.value = 'variable';
              const explanation = document.getElementById('guided-input-explanation-' + inputId);
              if (explanation) explanation.textContent = inventoryExecutionHelperText(item);
            }
          }
        },
        inputContainer,
        type === 'previous_output' ? 'Search previous step outputs...' : null
      );
      nameField.appendChild(nameDropdown);
      contentArea.appendChild(nameField);
      
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
      
      // Execution type dropdown (only for inventory, not for previous_output)
      if (type === 'inventory') {
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
        
        // Update explanation when type changes (use explanationDiv from closure; getElementById can be null if container not in DOM yet, e.g. during restoreStepIntoForm)
        typeSelect.addEventListener('change', function() {
          const explanation = document.getElementById(`guided-input-explanation-${inputId}`) || explanationDiv;
          if (!explanation) return;
          if (this.value === 'variable') {
            explanation.innerHTML = '<strong>Select inventory at execution:</strong> You will choose which supplier batch is consumed when this step runs. This allows you to track specific batches through your process.';
          } else {
            explanation.innerHTML = '<strong>Use this exact input every execution:</strong> The system will use the same quantity and unit for every execution without prompting. Use this for consistent inputs that don\'t vary between batches.';
          }
        });
        
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
  function inventoryCardSummary(item) {
    const isRaw = (item.inventory_type || item.category) === 'raw_material';
    if (isRaw) return '';
    const parts = [];
    if (item.process_name) parts.push('process name: ' + escapeHtmlForText(item.process_name));
    if (item.unit) parts.push('unit: ' + escapeHtmlForText(item.unit));
    return parts.join(', ');
  }

  // Helper text for execution-time selection: raw vs intermediate/final.
  function inventoryExecutionHelperText(item) {
    const isRaw = (item.inventory_type || item.category) === 'raw_material';
    return isRaw
      ? 'You will select which batch or supplier to use when this step runs.'
      : 'You will select which inventory item in stock to use when this step runs.';
  }
  
  // Build full metadata block. Raw: type + helper. Intermediate/final: type, unit, process, step, variable inputs + helper (no execution metadata: supplier/batch/dates/prompts/variable_output/previous_steps).
  function inventoryCardMetadataHtml(item) {
    const lines = [];
    const cat = item.inventory_type || item.category;
    if (cat) {
      const label = cat === 'raw_material' ? 'Raw material' : cat === 'work_in_progress' ? 'Intermediate' : 'Final product';
      lines.push('<div class="meta-line"><span class="meta-label">Type:</span> ' + escapeHtmlForText(label) + '</div>');
    }
    const isRaw = cat === 'raw_material';
    if (!isRaw && item.unit != null && item.unit !== '') {
      lines.push('<div class="meta-line"><span class="meta-label">Unit:</span> ' + escapeHtmlForText(String(item.unit)) + '</div>');
    }
    if (!isRaw && item.process_name) {
      lines.push('<div class="meta-line"><span class="meta-label">Process:</span> ' + escapeHtmlForText(item.process_name) + '</div>');
    }
    if (!isRaw && item.source_step_name) {
      lines.push('<div class="meta-line"><span class="meta-label">Step:</span> ' + escapeHtmlForText(item.source_step_name) + '</div>');
    }
    const ed = item.extra_data;
    if (ed && typeof ed === 'object' && ed.variable_inputs && Array.isArray(ed.variable_inputs) && ed.variable_inputs.length > 0) {
      lines.push('<div class="meta-line"><span class="meta-label">Variable inputs:</span></div>');
      ed.variable_inputs.forEach(function(inp, idx) {
        const n = inp && inp.name ? inp.name : 'Input ' + (idx + 1);
        const q = inp && inp.quantity != null ? inp.quantity : '';
        const u = inp && inp.unit ? inp.unit : '';
        lines.push('<div class="meta-line" style="padding-left: 12px;">' + escapeHtmlForText(n) + (q !== '' ? ' — ' + escapeHtmlForText(String(q)) + (u ? ' ' + escapeHtmlForText(u) : '') : '') + '</div>');
      });
    }
    lines.push('<div class="meta-line" style="font-style: italic;">' + escapeHtmlForText(inventoryExecutionHelperText(item)) + '</div>');
    return lines.join('');
  }
  
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
      const invIsRaw = (item.inventory_type || item.category) === 'raw_material';
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

      let execSel = null;
      if (!invIsRaw) {
        execSel = document.createElement('select');
        execSel.className = 'form-select';
        execSel.style.cssText = 'width:100%;padding:8px 12px;border-radius:var(--radius-md);border:1px solid var(--border-default);background:var(--bg-card);font-size:13px;margin-bottom:10px;box-sizing:border-box;';
        [['variable', 'Select inventory at execution'], ['static', 'Use exact input every execution']].forEach(function(opt) {
          const o = document.createElement('option');
          o.value = opt[0];
          o.textContent = opt[1];
          execSel.appendChild(o);
        });
      }

      const confirmBtn = document.createElement('button');
      confirmBtn.type = 'button';
      confirmBtn.className = 'btn btn-primary btn-sm';
      confirmBtn.style.cssText = 'width:100%;margin-top:4px;';
      confirmBtn.textContent = 'Click to add';

      inlineWrap.appendChild(qtyLab);
      inlineWrap.appendChild(qtyIn);
      inlineWrap.appendChild(unitLab);
      inlineWrap.appendChild(unitSel);
      if (!invIsRaw && execSel) {
        const execLab = document.createElement('label');
        execLab.style.cssText = 'display:block;font-size:12px;color:var(--text-secondary);margin-bottom:4px;';
        execLab.textContent = 'Execution type';
        inlineWrap.appendChild(execLab);
        inlineWrap.appendChild(execSel);
      }
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
        const exec = invIsRaw ? 'variable' : (execSel ? execSel.value : 'variable');
        (async function() {
          await window.addGuidedInput('inventory', true, Object.assign({}, item, { quantity: q, unit: u, executionType: exec }));
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
  
  function escapeHtmlForText(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
  
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
  
  // Add guided execution prompt
  window.addGuidedPrompt = function() {
    // Collapse all existing prompts before adding a new one
    collapseAllPrompts();
    
    const promptId = `guided-prompt-${Date.now()}`;
    const promptContainer = document.createElement('div');
    promptContainer.id = promptId;
    promptContainer.dataset.expanded = 'true'; // New prompt starts expanded
    promptContainer.style.cssText = 'background: var(--bg-card, #ffffff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md); margin-bottom: 12px; overflow: hidden;';
    
    // Create header with expand/collapse
    const header = document.createElement('div');
    header.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 12px; cursor: pointer; background: var(--bg-secondary, #f9fafb);';
    header.onclick = () => togglePromptExpand(promptId);
    
    const headerLeft = document.createElement('div');
    headerLeft.style.cssText = 'display: flex; align-items: center; gap: 8px;';
    
    const expandIcon = document.createElement('svg');
    expandIcon.className = 'guided-prompt-expand-icon';
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
    titleSpan.className = 'guided-prompt-title';
    titleSpan.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary);';
    titleSpan.textContent = 'Execution Prompt';
    headerLeft.appendChild(titleSpan);
    
    // Add label display that will show when collapsed
    const labelDisplay = document.createElement('span');
    labelDisplay.className = 'guided-prompt-label-display';
    labelDisplay.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary); display: none;';
    labelDisplay.textContent = '';
    headerLeft.appendChild(labelDisplay);
    
    // Add expand/collapse hint text
    const expandHint = document.createElement('span');
    expandHint.className = 'guided-prompt-expand-hint';
    expandHint.style.cssText = 'font-size: 11px; color: var(--text-tertiary, #9ca3af); margin-left: 8px; font-style: italic;';
    expandHint.textContent = '(click to collapse)';
    headerLeft.appendChild(expandHint);
    
    header.appendChild(headerLeft);
    
    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.onclick = (e) => {
      e.stopPropagation();
      window.removeGuidedPrompt(promptId);
    };
    removeButton.style.cssText = 'padding: 4px 8px; border: none; background: transparent; color: var(--error, #ef4444); cursor: pointer; font-size: 12px;';
    removeButton.textContent = 'Remove';
    header.appendChild(removeButton);
    
    promptContainer.appendChild(header);
    
    // Create content area
    const contentArea = document.createElement('div');
    contentArea.className = 'guided-prompt-content';
    contentArea.style.cssText = 'padding: 12px; display: block;';
    
    // Function to update label display
    const updateLabelDisplay = () => {
      const labelInput = promptContainer.querySelector('.guided-prompt-label');
      const label = labelInput ? labelInput.value.trim() : '';
      
      if (label) {
        labelDisplay.textContent = label;
        labelDisplay.style.display = 'inline';
        titleSpan.style.display = 'none';
      } else {
        labelDisplay.style.display = 'none';
        titleSpan.style.display = 'inline';
      }
    };
    
    // Label field
    const labelField = document.createElement('div');
    labelField.style.marginBottom = '12px';
    const labelLabel = document.createElement('label');
    labelLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    labelLabel.textContent = 'Label';
    labelField.appendChild(labelLabel);
    const labelInput = document.createElement('input');
    labelInput.type = 'text';
    labelInput.className = 'guided-prompt-label';
    labelInput.placeholder = 'e.g., Temperature, Operator name';
    labelInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
    labelInput.addEventListener('input', updateLabelDisplay);
    labelInput.addEventListener('blur', updateLabelDisplay);
    labelField.appendChild(labelInput);
    contentArea.appendChild(labelField);
    
    // Type field
    const typeField = document.createElement('div');
    typeField.style.marginBottom = '12px';
    const typeLabel = document.createElement('label');
    typeLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    typeLabel.textContent = 'Type';
    typeField.appendChild(typeLabel);
    const typeSelect = document.createElement('select');
    typeSelect.className = 'guided-prompt-type form-select';
    typeSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
    const textOption = document.createElement('option');
    textOption.value = 'text';
    textOption.textContent = 'Text';
    typeSelect.appendChild(textOption);
    const numberOption = document.createElement('option');
    numberOption.value = 'number';
    numberOption.textContent = 'Number';
    typeSelect.appendChild(numberOption);
    const dateOption = document.createElement('option');
    dateOption.value = 'date';
    dateOption.textContent = 'Date';
    typeSelect.appendChild(dateOption);
    const selectOption = document.createElement('option');
    selectOption.value = 'select';
    selectOption.textContent = 'Select';
    typeSelect.appendChild(selectOption);
    typeField.appendChild(typeSelect);
    contentArea.appendChild(typeField);
    
    // Unit field (optional)
    const unitField = document.createElement('div');
    unitField.style.marginBottom = '12px';
    const unitLabel = document.createElement('label');
    unitLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    unitLabel.textContent = 'Unit (optional)';
    unitField.appendChild(unitLabel);
    const unitSelect = document.createElement('select');
    unitSelect.className = 'guided-prompt-unit form-select';
    unitSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
    // Add empty option for "no unit"
    const emptyUnitOption = document.createElement('option');
    emptyUnitOption.value = '';
    emptyUnitOption.textContent = 'No unit';
    unitSelect.appendChild(emptyUnitOption);
    // Add unit options from unitGroups (same as inputs/outputs)
    [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
      const option = document.createElement('option');
      option.value = unit;
      option.textContent = unit;
      unitSelect.appendChild(option);
    });
    unitField.appendChild(unitSelect);
    contentArea.appendChild(unitField);
    
    // Required field
    const requiredField = document.createElement('div');
    const requiredLabel = document.createElement('label');
    requiredLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    requiredLabel.textContent = 'Required';
    requiredField.appendChild(requiredLabel);
    const requiredSelect = document.createElement('select');
    requiredSelect.className = 'guided-prompt-required form-select';
    requiredSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px; margin-bottom: 4px;';
    const requiredOption = document.createElement('option');
    requiredOption.value = 'true';
    requiredOption.textContent = 'Required';
    requiredSelect.appendChild(requiredOption);
    const optionalOption = document.createElement('option');
    optionalOption.value = 'false';
    optionalOption.textContent = 'Optional';
    requiredSelect.appendChild(optionalOption);
    requiredField.appendChild(requiredSelect);
    contentArea.appendChild(requiredField);
    
    promptContainer.appendChild(contentArea);
    document.getElementById('guided-prompts-list').appendChild(promptContainer);
    if (typeof updateStep4SummaryBar === 'function') updateStep4SummaryBar();
  };
  
  // Collapse all prompts except the specified one
  function collapseAllPrompts(exceptId = null) {
    const allPrompts = document.querySelectorAll('#guided-prompts-list > div');
    allPrompts.forEach(promptEl => {
      if (promptEl.id !== exceptId) {
        const contentArea = promptEl.querySelector('.guided-prompt-content');
        const expandIcon = promptEl.querySelector('.guided-prompt-expand-icon');
        const expandHint = promptEl.querySelector('.guided-prompt-expand-hint');
        if (contentArea && expandIcon) {
          contentArea.style.display = 'none';
          expandIcon.style.transform = 'rotate(0deg)';
          promptEl.dataset.expanded = 'false';
          if (expandHint) expandHint.textContent = '(click to expand)';
        }
      }
    });
  }
  
  // Toggle prompt expand/collapse
  function togglePromptExpand(promptId) {
    const promptEl = document.getElementById(promptId);
    if (!promptEl) return;
    
    const contentArea = promptEl.querySelector('.guided-prompt-content');
    const expandIcon = promptEl.querySelector('.guided-prompt-expand-icon');
    const expandHint = promptEl.querySelector('.guided-prompt-expand-hint');
    if (!contentArea || !expandIcon) return;
    
    const isExpanded = promptEl.dataset.expanded === 'true';
    if (isExpanded) {
      contentArea.style.display = 'none';
      expandIcon.style.transform = 'rotate(0deg)';
      promptEl.dataset.expanded = 'false';
      if (expandHint) expandHint.textContent = '(click to expand)';
    } else {
      contentArea.style.display = 'block';
      expandIcon.style.transform = 'rotate(180deg)';
      promptEl.dataset.expanded = 'true';
      if (expandHint) expandHint.textContent = '(click to collapse)';
      // Collapse all other prompts
      collapseAllPrompts(promptId);
    }
  }
  
  // Remove guided prompt
  window.removeGuidedPrompt = function(promptId) {
    const promptElement = document.getElementById(promptId);
    if (promptElement) {
      promptElement.remove();
      if (typeof updateStep4SummaryBar === 'function') updateStep4SummaryBar();
    }
  };

  function base64ToBlob(b64, mime) {
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new Blob([arr], { type: mime || 'application/octet-stream' });
  }

  function mapSessionInputsToApiPayloadFromRows(rows) {
    const inputs = [];
    (rows || []).forEach(function(inputRow) {
      const name = (inputRow.name || '').trim();
      const unit = (inputRow.unit || '').trim();
      if (!name || !unit) return;
      const executionType = inputRow.executionType || 'variable';
      const isPreviousOutput =
        inputRow.inputType === 'previous_output' ||
        (inputRow.executionType == null && inputRow.inputType !== 'inventory' && inputRow.inputType !== 'new');
      const isVariable = isPreviousOutput ? true : executionType === 'variable' || executionType === 'prompt';
      const requiresInventorySelection = isPreviousOutput ? true : executionType === 'variable';
      const inputObj = {
        name: name,
        quantity:
          inputRow.quantity !== null && inputRow.quantity !== undefined && inputRow.quantity !== ''
            ? parseFloat(inputRow.quantity)
            : null,
        unit: unit,
        is_variable: isVariable,
        requires_inventory_selection: requiresInventorySelection
      };
      const sourceOutputId = inputRow.source_output_id || inputRow.sourceOutputId || null;
      if (sourceOutputId) inputObj.source_output_id = sourceOutputId;
      inputs.push(inputObj);
    });
    return inputs;
  }

  function validateInventoryInputsFromSession(session) {
    const rows = session && Array.isArray(session.inputs) ? session.inputs : [];
    const invRows = rows.filter(function(r) {
      return r && (r.inputType === 'inventory' || r.inputType === 'previous_output');
    });
    for (let i = 0; i < invRows.length; i++) {
      const row = invRows[i];
      const q = row.quantity;
      const u = (row.unit || '').trim();
      if (u === '' || q === null || q === undefined || q === '') {
        return {
          valid: false,
          message: 'Please fill Quantity and Unit for all inventory items. Both are required.'
        };
      }
      const qn = typeof q === 'number' ? q : parseFloat(String(q));
      if (isNaN(qn) || qn <= 0) {
        return { valid: false, message: 'Quantity must be greater than 0 for all inventory items.' };
      }
    }
    return { valid: true };
  }

  function buildExecutionPromptsForApiFromSession(session) {
    const collected = [];
    (session.prompts || []).forEach(function(p) {
      if (!p || !(p.label || '').trim()) return;
      const label = (p.label || '').toLowerCase();
      const isEvidence = p.type === 'evidence' || label === 'evidence';
      if (label === 'batch number' || isEvidence) return;
      collected.push({
        label: p.label,
        type: p.type || 'text',
        unit: p.unit || null,
        required: p.required !== false
      });
    });
    const batchNumberMode = session.batchNumberMode || 'dont_ask';
    const evidenceMode = session.evidenceMode || 'dont_ask';
    const filtered = collected.filter(function(p) {
      const label = (p.label || '').toLowerCase();
      const isEvidence = p.type === 'evidence' || label === 'evidence';
      return label !== 'batch number' && !isEvidence;
    });
    if (batchNumberMode === 'required' || batchNumberMode === 'optional') {
      filtered.unshift({
        label: 'Batch number',
        type: 'text',
        unit: null,
        required: batchNumberMode === 'required'
      });
    }
    if (evidenceMode === 'required' || evidenceMode === 'optional') {
      filtered.push({
        label: 'Evidence',
        type: 'evidence',
        unit: null,
        required: evidenceMode === 'required'
      });
    }
    return filtered;
  }

  function wizardSessionHasDraftStepData(session) {
    if (!session || session.v !== 1) return false;
    const name = (session.stepName || '').trim();
    const hasBody =
      (session.inputs || []).length > 0 ||
      (session.outputs || []).length > 0 ||
      (session.prompts || []).length > 0;
    return !!(name || hasBody);
  }

  function hasPendingUnsavedWizardStepForFinish() {
    if (getFlowWizardPageSlug() === 'next-steps') {
      return false;
    }
    if (editingStepId) return false;
    return wizardSessionHasDraftStepData(loadWizardSessionMergeBase());
  }

  function buildVirtualSummaryStepFromWizardSession(session) {
    if (!session || session.v !== 1) return null;
    const execution_prompts = buildExecutionPromptsForApiFromSession(session);
    const docTitle = (session.docInlineTitle || '').trim();
    const docContent = (session.docInlineContent || '').trim();
    const hasInline = docTitle && docContent;
    const hasFileMeta = !!(session.docFileUpload && session.docFileUpload.base64);
    let documentation_summary;
    if (hasFileMeta) documentation_summary = 'SOP file attached (pending upload)';
    else if (hasInline) documentation_summary = 'Instructions: ' + docTitle;
    const inputsRaw = mapSessionInputsToSummaryRows(session.inputs || []);
    return {
      id: '__pending__',
      step_number: null,
      name: (session.stepName || '').trim() || 'Untitled step',
      description: (session.stepDescription || '').trim(),
      inputs: inputsRaw.map(function(row) {
        return { name: row.name, quantity: row.quantity, unit: row.unit };
      }),
      outputs: JSON.parse(JSON.stringify(session.outputs || [])),
      execution_prompts: execution_prompts,
      batch_number_mode: session.batchNumberMode || 'optional',
      evidence_mode: session.evidenceMode || 'optional',
      documentation_summary: documentation_summary
    };
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
      processId = newProcess.id;
      const newUrl = new URL(window.location.href);
      newUrl.searchParams.set('id', processId);
      window.history.replaceState({}, '', newUrl);
    }

    let stepCount = 1;
    // Match modal draft save: only update an existing row when explicitly editing it (in-memory id).
    // Do not use session.editingStepId here — stale session + reconcile() could point at the wrong step
    // and turn an "add another step" save into updateStep(step1).
    const eid =
      editingStepId != null && editingStepId !== '' ? editingStepId : null;
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
      saved = await CoreAPI.updateStep(processId, eid, stepData);
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
    pendingGuidedDocFileUpload = null;

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
            execution_prompts: s.execution_prompts || []
          }));
        }
      } catch (err) {
        console.warn('Could not reload process steps after save:', err);
      }
    }

    return stepSummary;
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
      await commitGuidedStepToProcessApiFromSessionSnapshot(session);
      persistClearedWizardDraftState();
      if (typeof updateStepSummaries === 'function') updateStepSummaries();
      window.location.href = '/core/flows/create/next-steps' + (window.location.search || '');
      return;
    } catch (e) {
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

  function deriveTraceabilityModes(step) {
    let batch = step.batch_number_mode;
    let ev = step.evidence_mode;
    if (batch && ev) return { batch, evidence: ev };
    const prompts = step.execution_prompts || [];
    if (!batch) {
      const bn = prompts.find(p => (p.label || '').toLowerCase() === 'batch number');
      if (bn) batch = bn.required !== false ? 'required' : 'optional';
      else batch = 'dont_ask';
    }
    if (!ev) {
      const evp = prompts.find(
        p => p.type === 'evidence' || (p.label || '').toLowerCase() === 'evidence'
      );
      if (evp) ev = evp.required !== false ? 'required' : 'optional';
      else ev = 'dont_ask';
    }
    return { batch: batch || 'optional', evidence: ev || 'optional' };
  }

  function formatTraceabilityModeLabel(mode) {
    if (mode === 'required') return 'Required';
    if (mode === 'optional') return 'Optional';
    return 'Off';
  }

  function formatOutputExpirySummary(output) {
    const ce = (output.extra_data || {}).custom_expiry;
    if (!ce || !ce.enabled) return 'None';
    const mode =
      ce.mode ||
      (ce.set_at_execution || ce.set_during_execution ? 'set_at_execution' : 'fixed_duration');
    if (mode === 'set_at_execution') return 'Operator defined';
    const dv = ce.duration_value != null ? ce.duration_value : ce.expiry_days;
    const du = (ce.duration_unit || 'days').toLowerCase();
    if (dv != null && du) return `${dv} ${dv === 1 ? du.replace(/s$/, '') : du}`;
    return 'Configured';
  }

  function formatOutputReadySummary(output) {
    const rd = (output.extra_data || {}).ready_date;
    if (!rd || !rd.enabled) return 'None';
    const mode = rd.mode || 'fixed_duration';
    if (mode === 'set_at_execution') return 'Operator defined';
    const dv = rd.duration_value;
    const du = (rd.duration_unit || 'hours').toLowerCase();
    if (dv != null && du) return `${dv} ${dv === 1 ? du.replace(/s$/, '') : du}`;
    return 'Configured';
  }

  /**
   * Summary page: unsaved in-progress step comes only from session; saved steps from createdSteps / API.
   */
  function resolveCurrentStepForSummary(sortedSteps) {
    const session = loadWizardSessionMergeBase();
    const sorted = Array.isArray(sortedSteps) ? sortedSteps : [];
    if (!editingStepId && wizardSessionHasDraftStepData(session)) {
      const vs = buildVirtualSummaryStepFromWizardSession(session);
      if (vs) {
        const displayNumber = sorted.length + 1;
        return { step: vs, displayNumber: displayNumber, isFinalStep: true };
      }
    }
    if (sorted.length === 0) {
      return { step: null, displayNumber: 0, isFinalStep: false };
    }
    let idx = sorted.length - 1;
    if (editingStepId) {
      const found = sorted.findIndex(function (s) {
        return String(s.id) === String(editingStepId);
      });
      if (found >= 0) idx = found;
    }
    const step = sorted[idx];
    return {
      step,
      displayNumber: idx + 1,
      isFinalStep: idx === sorted.length - 1
    };
  }

  /** Session persist stores full I/O on createdSteps[] — more reliable than top-level inputs/outputs alone. */
  function findSessionDraftStepForSummaryStep(session, step) {
    if (!session || !step || step.id == null) return null;
    const list = session.createdSteps;
    if (!Array.isArray(list) || list.length === 0) return null;
    const hit = list.find(function (s) {
      return s && s.id != null && String(s.id) === String(step.id);
    });
    return hit || null;
  }

  function sessionTopLevelIoAppliesToStep(step, sortedSteps) {
    const session = loadWizardSessionMergeBase();
    if (!session || !step) return false;
    if (String(step.id) === '__pending__') return true;
    if (!step.id) return false;
    if (session.editingStepId != null && session.editingStepId !== '') {
      return String(session.editingStepId) === String(step.id);
    }
    const sorted = [...sortedSteps].sort(function (a, b) {
      return (a.step_number || 0) - (b.step_number || 0);
    });
    const last = sorted[sorted.length - 1];
    return !!(last && String(last.id) === String(step.id));
  }

  function mapSessionInputsToSummaryRows(raw) {
    if (!Array.isArray(raw)) return [];
    const out = [];
    raw.forEach(function (i) {
      if (!i) return;
      const name = summaryInputDisplayName(i);
      if (!name) return;
      out.push({
        name: name,
        quantity: i.quantity != null ? i.quantity : null,
        unit: i.unit || ''
      });
    });
    return out;
  }

  /**
   * Summary route has no wizard DOM; GET /process may lag. Prefer session.createdSteps (full step
   * snapshot from persist) then top-level session inputs/outputs from merge-serialize.
   */
  function enrichStepForSummaryFromSession(step, sortedSteps) {
    if (!step) return step;
    const session = loadWizardSessionMergeBase();
    if (!session) return step;

    const next = { ...step };
    const draft = findSessionDraftStepForSummaryStep(session, step);

    const inputsApi = Array.isArray(step.inputs) ? step.inputs : [];
    let inputsNamed = inputsApi.filter(function (i) {
      return i && summaryInputDisplayName(i);
    });
    const outputsApi = Array.isArray(step.outputs) ? step.outputs : [];
    let outputsNamed = outputsApi.filter(function (o) {
      return o && summaryOutputDisplayName(o);
    });
    const promptsApi = Array.isArray(step.execution_prompts) ? step.execution_prompts : [];
    let promptsLabeled = promptsApi.filter(function (p) {
      return p && (p.label || '').trim();
    });

    if (draft) {
      const di = Array.isArray(draft.inputs)
        ? draft.inputs.filter(function (i) {
            return i && summaryInputDisplayName(i);
          })
        : [];
      const dout = Array.isArray(draft.outputs)
        ? draft.outputs.filter(function (o) {
            return o && summaryOutputDisplayName(o);
          })
        : [];
      const dp = Array.isArray(draft.execution_prompts)
        ? draft.execution_prompts.filter(function (p) {
            return p && (p.label || '').trim();
          })
        : [];
      if (inputsNamed.length === 0 && di.length > 0) {
        next.inputs = JSON.parse(JSON.stringify(di));
        inputsNamed = next.inputs;
      }
      if (outputsNamed.length === 0 && dout.length > 0) {
        next.outputs = JSON.parse(JSON.stringify(dout));
        outputsNamed = next.outputs.filter(function (o) {
          return o && summaryOutputDisplayName(o);
        });
      }
      if (promptsLabeled.length === 0 && dp.length > 0) {
        next.execution_prompts = JSON.parse(JSON.stringify(dp));
        promptsLabeled = next.execution_prompts;
      }
      if (next.batch_number_mode == null && draft.batch_number_mode != null) {
        next.batch_number_mode = draft.batch_number_mode;
      }
      if (next.evidence_mode == null && draft.evidence_mode != null) {
        next.evidence_mode = draft.evidence_mode;
      }
    }

    if (!sessionTopLevelIoAppliesToStep(step, sortedSteps)) {
      return next;
    }

    const sin = mapSessionInputsToSummaryRows(session.inputs || []);
    inputsNamed = (next.inputs || []).filter(function (i) {
      return i && summaryInputDisplayName(i);
    });
    if (inputsNamed.length === 0 && sin.length > 0) {
      next.inputs = sin;
    }

    const sout = (session.outputs || []).filter(function (o) {
      return o && summaryOutputDisplayName(o);
    });
    outputsNamed = (next.outputs || []).filter(function (o) {
      return o && summaryOutputDisplayName(o);
    });
    if (outputsNamed.length === 0 && sout.length > 0) {
      next.outputs = JSON.parse(JSON.stringify(sout));
    }

    promptsLabeled = (next.execution_prompts || []).filter(function (p) {
      return p && (p.label || '').trim();
    });
    const sp = (session.prompts || []).filter(function (p) {
      return p && (p.label || '').trim();
    });
    if (promptsLabeled.length === 0 && sp.length > 0) {
      next.execution_prompts = JSON.parse(JSON.stringify(sp));
    }

    if (next.batch_number_mode == null && session.batchNumberMode != null) {
      next.batch_number_mode = session.batchNumberMode;
    }
    if (next.evidence_mode == null && session.evidenceMode != null) {
      next.evidence_mode = session.evidenceMode;
    }

    return next;
  }

  /** Derived issues only — scoped to the current step (no filler when empty). */
  function buildStepSummaryWarnings(step, isFinalStep) {
    const warnings = [];
    if (!step) return warnings;
    const outputs = (step.outputs || []).filter(function (o) {
      return o && summaryOutputDisplayName(o);
    });
    if (outputs.length > 0) {
      const anyNoExpiry = outputs.some(function (o) {
        return formatOutputExpirySummary(o) === 'None';
      });
      if (anyNoExpiry) warnings.push('Output has no expiry rule');
    }
    const tm = deriveTraceabilityModes(step);
    if (isFinalStep && tm.batch === 'dont_ask') {
      warnings.push('No batch / run ID tracking on final step');
    }
    return warnings;
  }

  function renderCompliancePanel(sortedSteps) {
    const panel = document.getElementById('flow-compliance-panel');
    const heading = document.getElementById('step-summaries-heading');
    if (!panel) return;
    if (!isProcessFlowSummaryPage()) {
      panel.style.display = 'none';
      panel.innerHTML = '';
      if (heading) {
        heading.style.display = '';
        heading.textContent = 'Created Steps';
        heading.style.marginTop = '0';
      }
      return;
    }
    if (heading) {
      heading.style.display = 'none';
      heading.style.marginTop = '0';
    }
    panel.style.display = 'block';

    const escHtml = function (s) {
      return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    };

    let { step, displayNumber, isFinalStep } = resolveCurrentStepForSummary(sortedSteps);
    if (!step) {
      panel.innerHTML =
        '<p style="font-size:0.875rem;color:var(--text-tertiary);margin:0;">No step data to review.</p>';
      return;
    }
    step = enrichStepForSummaryFromSession(step, sortedSteps);

    const stepName = escHtml(step.name || 'Untitled step');
    const tm = deriveTraceabilityModes(step);
    const batchLabel = escHtml(formatTraceabilityModeLabel(tm.batch));
    const evidenceLabel = escHtml(formatTraceabilityModeLabel(tm.evidence));

    const purposeText = (step.description || '').trim();
    const hasStepDocumentation = !!(step.documentation_summary && String(step.documentation_summary).trim());

    const inputs = (step.inputs || []).filter(function (i) {
      return i && summaryInputDisplayName(i);
    });
    const outputs = (step.outputs || []).filter(function (o) {
      return o && summaryOutputDisplayName(o);
    });
    const customPrompts = (step.execution_prompts || []).filter(isCustomExecutionPrompt);

    let html = '';
    html +=
      '<div class="flow-step-summary-page"><p class="flow-step-summary-kicker" style="font-size:0.75rem;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:var(--text-secondary);margin:0 0 12px 0;">Step summary</p>';
    html += `<div class="flow-step-summary-header" style="display:flex;align-items:center;gap:12px;margin:0 0 22px 0;flex-wrap:wrap;">`;
    html += `<span class="flow-step-num-badge" aria-hidden="true">${displayNumber}</span>`;
    html += `<span style="font-size:1.125rem;font-weight:600;color:var(--text-primary);line-height:1.3;">Step ${displayNumber} \u2014 ${stepName}</span>`;
    html += '</div>';

    html +=
      '<section class="flow-compliance__section flow-step-summary-section" style="margin-bottom:18px;"><h3 style="font-size:0.9375rem;font-weight:600;color:var(--text-primary);margin:0 0 10px 0;">Step function</h3>';

    html += '<div style="font-size:0.875rem;font-weight:600;color:var(--text-secondary);margin:0 0 6px 0;">Inputs</div>';
    if (inputs.length === 0) {
      html +=
        '<p style="font-size:0.875rem;color:var(--text-tertiary);margin:0 0 12px 0;">None</p>';
    } else {
      html += '<ul class="flow-compliance-step-list" style="margin-bottom:12px;">';
      inputs.forEach(function (input) {
        const q =
          input.quantity !== null && input.quantity !== undefined ? input.quantity : '';
        const u = input.unit || '';
        const bit = q ? ` (${q}${u ? ' ' + u : ''})` : u ? ` (${u})` : '';
        html += `<li><span class="flow-compliance-row__text">${escHtml(summaryInputDisplayName(input) + bit)}</span></li>`;
      });
      html += '</ul>';
    }

    html += '<div style="font-size:0.875rem;font-weight:600;color:var(--text-secondary);margin:0 0 6px 0;">Outputs</div>';
    if (outputs.length === 0) {
      html +=
        '<p style="font-size:0.875rem;color:var(--text-tertiary);margin:0 0 12px 0;">None</p>';
    } else {
      html += '<ul class="flow-compliance-step-list" style="margin-bottom:12px;">';
      outputs.forEach(function (output) {
        const q =
          output.quantity !== null && output.quantity !== undefined ? output.quantity : '';
        const u = output.unit || '';
        const bit = q ? ` (${q}${u ? ' ' + u : ''})` : u ? ` (${u})` : '';
        html += `<li><span class="flow-compliance-row__text">${escHtml(summaryOutputDisplayName(output) + bit)}</span></li>`;
      });
      html += '</ul>';
    }

    if (purposeText) {
      html +=
        '<div style="font-size:0.875rem;font-weight:600;color:var(--text-secondary);margin:0 0 6px 0;">Purpose</div>';
      html += `<p style="font-size:0.875rem;color:var(--text-primary);margin:0;line-height:1.55;">${escHtml(purposeText)}</p>`;
    }
    html += '</section>';

    html +=
      '<section class="flow-compliance__section flow-step-summary-section" style="margin-bottom:18px;border-top:1px solid var(--border-default,#e5e7eb);padding-top:16px;"><h3 style="font-size:0.9375rem;font-weight:600;color:var(--text-primary);margin:0 0 10px 0;">Traceability &amp; compliance</h3>';
    html +=
      '<div style="font-size:0.875rem;line-height:1.65;color:var(--text-primary);"><div><span style="color:var(--text-secondary);font-weight:500;">Batch:</span> ' +
      batchLabel +
      '</div><div><span style="color:var(--text-secondary);font-weight:500;">Evidence:</span> ' +
      evidenceLabel +
      '</div></div></section>';

    html +=
      '<section class="flow-compliance__section flow-step-summary-section" style="margin-bottom:18px;border-top:1px solid var(--border-default,#e5e7eb);padding-top:16px;"><h3 style="font-size:0.9375rem;font-weight:600;color:var(--text-primary);margin:0 0 10px 0;">Output rules</h3>';
    if (outputs.length === 0) {
      html +=
        '<p style="font-size:0.875rem;color:var(--text-tertiary);margin:0;">No outputs — rules apply when outputs exist.</p>';
    } else if (outputs.length === 1) {
      const o = outputs[0];
      html +=
        '<div style="font-size:0.875rem;line-height:1.65;color:var(--text-primary);"><div><span style="color:var(--text-secondary);font-weight:500;">Expiry:</span> ' +
        escHtml(formatOutputExpirySummary(o)) +
        '</div><div><span style="color:var(--text-secondary);font-weight:500;">Ready date:</span> ' +
        escHtml(formatOutputReadySummary(o)) +
        '</div></div>';
    } else {
      html += '<ul class="flow-compliance-step-list">';
      outputs.forEach(function (o) {
        const on = escHtml(summaryOutputDisplayName(o) || 'Output');
        const ex = escHtml(formatOutputExpirySummary(o));
        const rd = escHtml(formatOutputReadySummary(o));
        html += `<li style="margin-bottom:8px;"><span class="flow-compliance-row__text"><strong>${on}</strong> — Expiry: ${ex}; Ready: ${rd}</span></li>`;
      });
      html += '</ul>';
    }
    html += '</section>';

    html +=
      '<section class="flow-compliance__section flow-step-summary-section" style="margin-bottom:18px;border-top:1px solid var(--border-default,#e5e7eb);padding-top:16px;"><h3 style="font-size:0.9375rem;font-weight:600;color:var(--text-primary);margin:0 0 10px 0;">Documentation and Custom prompts</h3>';
    html +=
      '<p style="font-size:0.875rem;color:var(--text-primary);margin:0 0 12px 0;line-height:1.55;"><span style="color:var(--text-secondary);font-weight:500;">Step documentation:</span> ' +
      (hasStepDocumentation ? 'Yes' : 'No') +
      '</p>';
    if (customPrompts.length > 0) {
      html +=
        '<div style="font-size:0.875rem;font-weight:600;color:var(--text-secondary);margin:0 0 6px 0;">Custom prompts</div>';
      html += '<ul class="flow-compliance-step-list">';
      customPrompts.forEach(function (p) {
        const req = p.required !== false ? 'Required' : 'Optional';
        const unit = p.unit ? `, ${escHtml(p.unit)}` : '';
        const line = `${escHtml(p.label || '')} (${escHtml(p.type || '')}${unit}) — ${req}`;
        html += `<li><span class="flow-compliance-row__text">${line}</span></li>`;
      });
      html += '</ul>';
    }
    html += '</section>';

    const warns = buildStepSummaryWarnings(step, isFinalStep);
    html +=
      '<section class="flow-compliance__section flow-step-summary-section" style="margin-bottom:0;border-top:1px solid var(--border-default,#e5e7eb);padding-top:16px;"><h3 style="font-size:0.9375rem;font-weight:600;color:var(--text-primary);margin:0 0 10px 0;">Warnings</h3>';
    if (warns.length === 0) {
      html +=
        '<p style="font-size:0.875rem;color:var(--text-tertiary);margin:0;">No issues flagged for this step.</p>';
    } else {
      html +=
        '<ul class="flow-compliance-warnings" style="margin:0;padding-left:0;list-style:none;font-size:0.875rem;line-height:1.65;">';
      warns.forEach(function (w) {
        html += `<li style="margin-bottom:6px;"><span aria-hidden="true">\u26A0 </span>${escHtml(w)}</li>`;
      });
      html += '</ul>';
    }
    html += '</section></div>';

    panel.innerHTML = html;
  }

  const PROCESS_FLOW_PENDING_NEW_STEP_KEY = 'processFlowWizardPendingNewStep';

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
    if (editingStepId && createdSteps.some(s => s.id === editingStepId)) {
      return;
    }
    const session = loadWizardSessionMergeBase();
    // User is composing a new unsaved step (modal draft save always uses createStep for that case).
    // Do not default to "last saved step" — that made Save on summary call updateStep on step N−1.
    // When editing an existing step, editingStepId is already set from restoreSpaWizardState above.
    if (wizardSessionHasDraftStepData(session)) {
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
  function countNamedStepInputs(inputs) {
    if (!Array.isArray(inputs)) return 0;
    return inputs.filter(function (i) {
      return i && summaryInputDisplayName(i);
    }).length;
  }

  function countNamedStepOutputs(outputs) {
    if (!Array.isArray(outputs)) return 0;
    return outputs.filter(function (o) {
      return o && summaryOutputDisplayName(o);
    }).length;
  }

  function mergeDraftCreatedStepsIntoApiSteps(apiSteps, draftSteps) {
    if (!Array.isArray(apiSteps) || apiSteps.length === 0) return apiSteps;
    const draftById = new Map();
    (draftSteps || []).forEach(function (s) {
      if (s && s.id) draftById.set(String(s.id), s);
    });
    return apiSteps.map(function (api) {
      const d = draftById.get(String(api.id));
      if (!d) return { ...api };
      const merged = { ...api };
      const draftOut = countNamedStepOutputs(d.outputs);
      const apiOut = countNamedStepOutputs(merged.outputs);
      if (apiOut === 0 && draftOut > 0) {
        merged.outputs = JSON.parse(JSON.stringify(d.outputs));
      }
      const draftIn = countNamedStepInputs(d.inputs);
      const apiIn = countNamedStepInputs(merged.inputs);
      if (apiIn === 0 && draftIn > 0) {
        merged.inputs = JSON.parse(JSON.stringify(d.inputs));
      }
      const draftPrompts = Array.isArray(d.execution_prompts)
        ? d.execution_prompts.filter(function (p) {
            return p && (p.label || '').trim();
          }).length
        : 0;
      const apiPrompts = Array.isArray(merged.execution_prompts)
        ? merged.execution_prompts.filter(function (p) {
            return p && (p.label || '').trim();
          }).length
        : 0;
      if (apiPrompts === 0 && draftPrompts > 0) {
        merged.execution_prompts = JSON.parse(JSON.stringify(d.execution_prompts));
      }
      if (merged.batch_number_mode == null && d.batch_number_mode != null) merged.batch_number_mode = d.batch_number_mode;
      if (merged.evidence_mode == null && d.evidence_mode != null) merged.evidence_mode = d.evidence_mode;
      return merged;
    });
  }

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
  async function mergeProcessStepsFromApiForCurrentProcess() {
    const pid = new URLSearchParams(window.location.search).get('id');
    if (!pid || typeof CoreAPI === 'undefined' || !CoreAPI.getProcess) return;
    try {
      const proc = await CoreAPI.getProcess(pid);
      if (!proc || !Array.isArray(proc.steps)) return;
      if (proc.steps.length === 0) return;

      const memorySnapshot = Array.isArray(createdSteps) ? createdSteps.map(function (s) {
        return { ...s };
      }) : [];
      const sessionSnap = loadWizardSessionMergeBase();
      const sessionCreated =
        sessionSnap && Array.isArray(sessionSnap.createdSteps) ? sessionSnap.createdSteps : [];

      let merged = proc.steps.map(function (s) {
        return { ...s };
      });
      merged = mergeDraftCreatedStepsIntoApiSteps(merged, memorySnapshot);
      merged = mergeDraftCreatedStepsIntoApiSteps(merged, sessionCreated);
      merged = overlaySessionWizardOutputsOntoSteps(merged);
      merged = overlaySessionWizardInputsOntoSteps(merged);

      createdSteps = merged;
      reconcileEditingStepIdAfterStepsSync();
    } catch (e) {
      console.warn('mergeProcessStepsFromApiForCurrentProcess', e);
    }
  }

  async function mergeProcessStepsFromApiForSummary() {
    if (!isProcessFlowSummaryPage()) return;
    await mergeProcessStepsFromApiForCurrentProcess();
  }

  // Update step summaries display with expand/collapse
  function updateStepSummaries() {
    const summariesList = document.getElementById('step-summaries-list');
    const summariesContainer = document.getElementById('step-summaries-container');
    if (!summariesList || !summariesContainer) return;

    const sessionSnap = loadWizardSessionMergeBase();
    const hasPendingSessionStep = wizardSessionHasDraftStepData(sessionSnap);

    if (createdSteps.length === 0 && !hasPendingSessionStep) {
      summariesContainer.style.display = 'none';
      const panel = document.getElementById('flow-compliance-panel');
      if (panel) {
        panel.style.display = 'none';
        panel.innerHTML = '';
      }
      const summarySticky = document.getElementById('flow-wizard-summary-sticky');
      if (summarySticky) summarySticky.style.display = 'none';
      const heading = document.getElementById('step-summaries-heading');
      if (heading) {
        heading.textContent = 'Created Steps';
        heading.style.marginTop = '0';
      }
      return;
    }
    
    summariesContainer.style.display = 'block';
    summariesList.innerHTML = '';

    const sortedSteps = [...createdSteps].sort((a, b) => (a.step_number || 0) - (b.step_number || 0));
    renderCompliancePanel(sortedSteps);
    if (isProcessFlowSummaryPage()) {
      summariesList.style.display = 'none';
      const summarySticky = document.getElementById('flow-wizard-summary-sticky');
      if (summarySticky) summarySticky.style.display = createdSteps.length > 0 || hasPendingSessionStep ? '' : 'none';
      return;
    }
    summariesList.style.display = '';

    const spaPage = document.body && (document.body.getAttribute('data-page') === 'process-flow-spa' || document.body.getAttribute('data-page') === 'process-flow-wizard');
    sortedSteps.forEach((step, index) => {
      const displayNumber = index + 1;
      const stepId = `step-summary-${step.id || index}`;
      const summaryCard = document.createElement('div');
      summaryCard.id = stepId;
      summaryCard.dataset.expanded = 'false';
      if (spaPage) {
        summaryCard.style.cssText =
          'padding: 14px 0; border: none; border-radius: 0; background: transparent; overflow: hidden;' +
          (index > 0 ? 'border-top: 1px solid var(--border-default, #e5e7eb);' : '');
      } else {
        summaryCard.style.cssText = 'background: var(--bg-card, #ffffff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md); padding: 16px; overflow: hidden;';
      }
      
      // Header (clickable to expand/collapse)
      const stepHeader = document.createElement('div');
      stepHeader.style.cssText = 'display: flex; align-items: center; gap: 12px; cursor: pointer;';
      stepHeader.onclick = () => toggleStepSummary(stepId);
      
      const expandIcon = document.createElement('svg');
      expandIcon.className = 'step-summary-expand-icon';
      expandIcon.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
      expandIcon.setAttribute('width', '16');
      expandIcon.setAttribute('height', '16');
      expandIcon.setAttribute('viewBox', '0 0 24 24');
      expandIcon.setAttribute('fill', 'none');
      expandIcon.setAttribute('stroke', 'currentColor');
      expandIcon.setAttribute('stroke-width', '2');
      expandIcon.setAttribute('stroke-linecap', 'round');
      expandIcon.setAttribute('stroke-linejoin', 'round');
      expandIcon.style.cssText = 'transition: transform 0.2s; transform: rotate(0deg); color: var(--text-tertiary, #9ca3af); flex-shrink: 0;';
      expandIcon.innerHTML = '<polyline points="6 9 12 15 18 9"></polyline>';
      stepHeader.appendChild(expandIcon);
      
      const stepNumber = document.createElement('div');
      stepNumber.style.cssText = 'width: 32px; height: 32px; border-radius: 50%; background: var(--primary, #3b82f6); color: white; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 14px; flex-shrink: 0;';
      stepNumber.textContent = displayNumber;
      stepHeader.appendChild(stepNumber);
      
      const stepInfo = document.createElement('div');
      stepInfo.style.cssText = 'flex: 1;';
      
      const stepName = document.createElement('h4');
      stepName.style.cssText = 'font-size: 16px; font-weight: 600; color: var(--text-primary); margin: 0 0 4px 0;';
      stepName.textContent = step.name;
      stepInfo.appendChild(stepName);
      
      if (step.description) {
        const stepDesc = document.createElement('p');
        stepDesc.style.cssText = 'font-size: 13px; color: var(--text-secondary); margin: 0;';
        stepDesc.textContent = step.description;
        stepInfo.appendChild(stepDesc);
      }
      
      stepHeader.appendChild(stepInfo);
      summaryCard.appendChild(stepHeader);
      
      // Collapsed summary (always visible)
      const collapsedSummary = document.createElement('div');
      collapsedSummary.className = 'step-summary-collapsed';
      collapsedSummary.style.cssText = 'margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-light, #e5e7eb); font-size: 12px; color: var(--text-secondary);';
      
      const details = [];
      if (step.inputs && step.inputs.length > 0) {
        details.push(`${step.inputs.length} input${step.inputs.length > 1 ? 's' : ''}`);
      }
      if (step.outputs && step.outputs.length > 0) {
        details.push(`${step.outputs.length} output${step.outputs.length > 1 ? 's' : ''}`);
      }
      if (step.execution_prompts && step.execution_prompts.length > 0) {
        details.push(`${step.execution_prompts.length} prompt${step.execution_prompts.length > 1 ? 's' : ''}`);
      }
      
      if (details.length > 0) {
        collapsedSummary.textContent = details.join(' • ');
        summaryCard.appendChild(collapsedSummary);
      }
      
      // Expanded details (hidden by default)
      const expandedDetails = document.createElement('div');
      expandedDetails.className = 'step-summary-expanded';
      expandedDetails.style.cssText = 'margin-top: 16px; padding-top: 16px; border-top: 2px solid var(--border-default, #e5e7eb); display: none;';
      
      // Inputs
      if (step.inputs && step.inputs.length > 0) {
        const inputsSection = document.createElement('div');
        inputsSection.style.cssText = 'margin-bottom: 16px;';
        const inputsTitle = document.createElement('h5');
        inputsTitle.style.cssText = 'font-size: 13px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0;';
        inputsTitle.textContent = 'Inputs:';
        inputsSection.appendChild(inputsTitle);
        
        step.inputs.forEach(input => {
          const inputItem = document.createElement('div');
          inputItem.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); margin-bottom: 4px; font-size: 12px; color: var(--text-secondary);';
          const quantity = input.quantity !== null && input.quantity !== undefined ? input.quantity : '';
          const unit = input.unit || '';
          inputItem.textContent = `• ${input.name}${quantity ? ` (${quantity} ${unit})` : unit ? ` (${unit})` : ''}`;
          inputsSection.appendChild(inputItem);
        });
        expandedDetails.appendChild(inputsSection);
      }
      
      // Outputs
      if (step.outputs && step.outputs.length > 0) {
        const outputsSection = document.createElement('div');
        outputsSection.style.cssText = 'margin-bottom: 16px;';
        const outputsTitle = document.createElement('h5');
        outputsTitle.style.cssText = 'font-size: 13px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0;';
        outputsTitle.textContent = 'Outputs:';
        outputsSection.appendChild(outputsTitle);
        
        step.outputs.forEach(output => {
          const outputItem = document.createElement('div');
          outputItem.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); margin-bottom: 4px; font-size: 12px; color: var(--text-secondary);';
          const quantity = output.quantity !== null && output.quantity !== undefined ? output.quantity : '';
          const unit = output.unit || '';
          outputItem.textContent = `• ${output.name}${quantity ? ` (${quantity} ${unit})` : unit ? ` (${unit})` : ''}`;
          outputsSection.appendChild(outputItem);
        });
        expandedDetails.appendChild(outputsSection);
      }
      
      // Prompts
      if (step.execution_prompts && step.execution_prompts.length > 0) {
        const promptsSection = document.createElement('div');
        const promptsTitle = document.createElement('h5');
        promptsTitle.style.cssText = 'font-size: 13px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0;';
        promptsTitle.textContent = 'Prompts:';
        promptsSection.appendChild(promptsTitle);
        
        step.execution_prompts.forEach(prompt => {
          const promptItem = document.createElement('div');
          promptItem.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); margin-bottom: 4px; font-size: 12px; color: var(--text-secondary);';
          const unit = prompt.unit ? ` (${prompt.unit})` : '';
          const required = prompt.required !== false ? 'Required' : 'Optional';
          promptItem.textContent = `• ${prompt.label} - ${prompt.type}${unit} - ${required}`;
          promptsSection.appendChild(promptItem);
        });
        expandedDetails.appendChild(promptsSection);
      }

      if (step.documentation_summary) {
        const docSection = document.createElement('div');
        docSection.style.cssText = 'margin-bottom: 16px;';
        const docTitle = document.createElement('h5');
        docTitle.style.cssText = 'font-size: 13px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0;';
        docTitle.textContent = 'Documentation:';
        docSection.appendChild(docTitle);
        const docItem = document.createElement('div');
        docItem.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); font-size: 12px; color: var(--text-secondary);';
        docItem.textContent = step.documentation_summary;
        docSection.appendChild(docItem);
        expandedDetails.appendChild(docSection);
      }

      if (step.batch_number_mode || step.evidence_mode) {
        const traceSection = document.createElement('div');
        traceSection.style.cssText = 'margin-bottom: 16px;';
        const traceTitle = document.createElement('h5');
        traceTitle.style.cssText = 'font-size: 13px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0;';
        traceTitle.textContent = 'Traceability:';
        traceSection.appendChild(traceTitle);
        if (step.batch_number_mode) {
          const row = document.createElement('div');
          row.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); margin-bottom: 4px; font-size: 12px; color: var(--text-secondary);';
          row.textContent = '• Batch / run ID: ' + formatStep4ModeLabel(step.batch_number_mode);
          traceSection.appendChild(row);
        }
        if (step.evidence_mode) {
          const row2 = document.createElement('div');
          row2.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); margin-bottom: 4px; font-size: 12px; color: var(--text-secondary);';
          row2.textContent = '• Evidence capture: ' + formatStep4ModeLabel(step.evidence_mode);
          traceSection.appendChild(row2);
        }
        expandedDetails.appendChild(traceSection);
      }

      summaryCard.appendChild(expandedDetails);
      summariesList.appendChild(summaryCard);
    });
  }
  
  // Toggle step summary expand/collapse
  function toggleStepSummary(stepId) {
    const summaryCard = document.getElementById(stepId);
    if (!summaryCard) return;
    
    const expandedDetails = summaryCard.querySelector('.step-summary-expanded');
    const collapsedSummary = summaryCard.querySelector('.step-summary-collapsed');
    const expandIcon = summaryCard.querySelector('.step-summary-expand-icon');
    
    if (!expandedDetails || !expandIcon) return;
    
    const isExpanded = summaryCard.dataset.expanded === 'true';
    if (isExpanded) {
      expandedDetails.style.display = 'none';
      if (collapsedSummary) collapsedSummary.style.display = 'block';
      expandIcon.style.transform = 'rotate(0deg)';
      summaryCard.dataset.expanded = 'false';
    } else {
      expandedDetails.style.display = 'block';
      if (collapsedSummary) collapsedSummary.style.display = 'none';
      expandIcon.style.transform = 'rotate(180deg)';
      summaryCard.dataset.expanded = 'true';
    }
  }
  
  // Start editing an existing step (from the "existing steps" view when editing a non-draft process)
  window.startEditingStep = async function(stepId) {
    const step = createdSteps.find(s => s.id === stepId);
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
    if (modalDescription) modalDescription.textContent = 'You can expand existing steps to edit them, or use this interactive editor to add additional steps.';
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
    applyProcessFlowWizardFreshStart();
    const slug = document.body.getAttribute('data-flow-wizard-page');
    const slugToStep = { 'step-name': 1, 'inputs': 2, 'outputs': 3, 'evidence-and-prompts': 4 };
    if (slug && slugToStep[slug]) {
      currentStep = slugToStep[slug];
    }
    if (slug === 'process-overview') {
      if (typeof window.restoreSpaWizardState === 'function') {
        await window.restoreSpaWizardState();
      }
      const pidOv = new URLSearchParams(window.location.search || '').get('id');
      if (pidOv && typeof CoreAPI !== 'undefined' && CoreAPI.getProcess) {
        try {
          const proc = await CoreAPI.getProcess(pidOv);
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
        await window.restoreSpaWizardState();
      }
      const pidNs = new URLSearchParams(window.location.search || '').get('id');
      if (pidNs) {
        await mergeProcessStepsFromApiForCurrentProcess();
        if (typeof window.persistSpaWizardState === 'function') {
          window.persistSpaWizardState();
        }
      }
    } else if (slug === 'summary') {
      if (typeof window.restoreSpaWizardState === 'function') {
        await window.restoreSpaWizardState();
      }
      await mergeProcessStepsFromApiForSummary();
      if (typeof window.persistSpaWizardState === 'function') {
        window.persistSpaWizardState();
      }
      const emptyEl = document.getElementById('process-flow-summary-empty');
      const postCreationOptions = document.getElementById('post-creation-options');
      const summarySticky = document.getElementById('flow-wizard-summary-sticky');
      const hasPending = wizardSessionHasDraftStepData(loadWizardSessionMergeBase());
      if (createdSteps.length > 0 || hasPending) {
        if (emptyEl) emptyEl.style.display = 'none';
        updateStepSummaries();
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
      if (typeof window.restoreSpaWizardState === 'function') {
        await window.restoreSpaWizardState();
      }
      const pid = new URLSearchParams(window.location.search || '').get('id');
      if (pid) {
        await mergeProcessStepsFromApiForCurrentProcess();
        if (typeof window.persistSpaWizardState === 'function') {
          window.persistSpaWizardState();
        }
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
        const sorted = [...createdSteps].sort((a, b) => (a.step_number || 0) - (b.step_number || 0));
        const idx = sorted.findIndex(function(s) { return s.id === editingStepId; });
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
