(function() {
  'use strict';

  const { countLabeledExecutionPrompts } = window.ProcessModalUtils;
  const { countNamedStepInputs, countNamedStepOutputs } = window.ProcessModalStepData;

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
        inventory_type: (outputEl.dataset && outputEl.dataset.outputInventoryType) ? outputEl.dataset.outputInventoryType : 'work_in_progress',
        is_variable: true,
        requires_execution_confirmation: true
      };
      if (Object.keys(extra_data).length > 0) outObj.extra_data = extra_data;
      outputs.push(outObj);
    });
    return outputs;
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


  function createStateSerializer(helpers) {
    function serializeSpaWizardState() {
      const merge = helpers.shouldMergePersistSpaFormFields();
      const prev = merge ? (helpers.loadWizardSessionMergeBase() || {}) : null;

      const nameEl = document.getElementById('guided-step-name');
      const descEl = document.getElementById('guided-step-description');
      const stepName = nameEl ? (nameEl.value || '') : (merge ? (prev.stepName || '') : '');
      const stepDescription = descEl ? (descEl.value || '') : (merge ? (prev.stepDescription || '') : '');

      let inputs;
      if (document.getElementById('guided-inputs-list-unified')) {
        inputs = [];
        helpers.getAllGuidedInputElements().forEach(inputEl => {
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
          const expectedInventoryType = inputEl.dataset.expectedInventoryType || null;
          inputs.push({
            inputType,
            name,
            quantity: quantity ? parseFloat(quantity) : null,
            unit,
            executionType,
            source_output_id: sourceOutputId || undefined,
            previousOutputDisplayName: previousOutputDisplayName || undefined,
            expected_inventory_type: expectedInventoryType || undefined,
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
        prompts = helpers.collectCurrentPrompts();
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

      let createdStepsOut = JSON.parse(JSON.stringify(helpers.getCreatedSteps()));
      if (merge && prev) {
        createdStepsOut = preserveCreatedStepsIoFromPrev(prev, createdStepsOut);
      }

      const slug = helpers.getFlowWizardPageSlug();
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
      const pendingGuidedDocFileUpload = helpers.getPendingGuidedDocFileUpload();
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
        editingStepId: helpers.getEditingStepId() || null,
        createdSteps: createdStepsOut,
        docInlineTitle,
        docInlineContent,
        processId: processIdPersist,
        docFileUpload
      };
    }
    return serializeSpaWizardState;
  }


  function buildClearedDraftPayload(prev, processId, createdSteps) {
    return {
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
      processId: processId,
      docFileUpload: null
    };
  }


  window.ProcessModalSpaPayloads = Object.freeze({
    collectSpaWizardOutputsPayload,
    preserveCreatedStepsIoFromPrev,
    createStateSerializer,
    buildClearedDraftPayload
  });
})();
