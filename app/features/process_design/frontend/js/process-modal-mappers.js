(function() {
  'use strict';

  const {
    summaryInputDisplayName,
    summaryOutputDisplayName,
    normalisePromptOptions
  } = window.ProcessModalUtils;

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
      const expectedInv = inputRow.expected_inventory_type || inputRow.expectedInventoryType || null;
      if (expectedInv) inputObj.expected_inventory_type = expectedInv;
      inputs.push(inputObj);
    });
    return inputs;
  }

  function validateInventoryInputsFromSession(session) {
    const rows = session && Array.isArray(session.inputs) ? session.inputs : [];
    const invRows = rows.filter(function(row) {
      return row && (row.inputType === 'inventory' || row.inputType === 'previous_output');
    });
    for (let i = 0; i < invRows.length; i++) {
      const row = invRows[i];
      const quantity = row.quantity;
      const unit = (row.unit || '').trim();
      if (unit === '' || quantity === null || quantity === undefined || quantity === '') {
        return {
          valid: false,
          message: 'Please fill Quantity and Unit for all inventory items. Both are required.'
        };
      }
      const numericQuantity = typeof quantity === 'number' ? quantity : parseFloat(String(quantity));
      if (isNaN(numericQuantity) || numericQuantity <= 0) {
        return { valid: false, message: 'Quantity must be greater than 0 for all inventory items.' };
      }
    }
    return { valid: true };
  }

  function buildExecutionPromptsForApiFromSession(session) {
    const collected = [];
    (session.prompts || []).forEach(function(prompt) {
      if (!prompt || !(prompt.label || '').trim()) return;
      const label = (prompt.label || '').toLowerCase();
      const isEvidence = prompt.type === 'evidence' || label === 'evidence';
      if (label === 'batch number' || isEvidence) return;
      collected.push({
        label: prompt.label,
        type: prompt.type || 'text',
        unit: prompt.unit || null,
        required: prompt.required !== false,
        ...(prompt.type === 'select' ? { options: normalisePromptOptions(prompt.options) } : {})
      });
    });
    const batchNumberMode = session.batchNumberMode || 'dont_ask';
    const evidenceMode = session.evidenceMode || 'dont_ask';
    const filtered = collected.filter(function(prompt) {
      const label = (prompt.label || '').toLowerCase();
      const isEvidence = prompt.type === 'evidence' || label === 'evidence';
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

  function mapSessionInputsToSummaryRows(raw) {
    if (!Array.isArray(raw)) return [];
    const out = [];
    raw.forEach(function(input) {
      if (!input) return;
      const name = summaryInputDisplayName(input);
      if (!name) return;
      out.push({
        name: name,
        quantity: input.quantity != null ? input.quantity : null,
        unit: input.unit || ''
      });
    });
    return out;
  }

  function mapApiInputToWizardSessionInput(apiIn) {
    if (!apiIn) {
      return {
        inputType: 'new',
        name: '',
        quantity: null,
        unit: '',
        executionType: 'variable',
        inventoryPreselected: false,
        is_variable: true,
        requires_inventory_selection: true
      };
    }
    const inputType = apiIn.source_output_id ? 'previous_output' : (apiIn.requires_inventory_selection ? 'inventory' : 'new');
    const name = summaryInputDisplayName(apiIn);
    let executionType = 'variable';
    if (inputType === 'previous_output') {
      executionType = apiIn.is_variable !== false ? 'variable' : 'static';
    } else if (inputType === 'inventory') {
      executionType = apiIn.requires_inventory_selection ? 'variable' : 'static';
    } else {
      executionType = apiIn.is_variable !== false ? 'variable' : 'static';
    }
    const qty = apiIn.quantity;
    let quantity = null;
    if (qty != null && qty !== '') {
      const n = typeof qty === 'number' ? qty : parseFloat(String(qty).trim());
      quantity = isNaN(n) ? null : n;
    }
    const isPreviousOutput = inputType === 'previous_output';
    const isVariable = isPreviousOutput ? true : (executionType === 'variable' || executionType === 'prompt');
    const requiresInventorySelection = isPreviousOutput ? true : executionType === 'variable';
    return {
      inputType,
      name,
      quantity,
      unit: apiIn.unit || '',
      executionType,
      source_output_id: apiIn.source_output_id || undefined,
      previousOutputDisplayName:
        apiIn.previous_output_display_name || apiIn.previousOutputDisplayName || undefined,
      expected_inventory_type: apiIn.expected_inventory_type || undefined,
      inventoryPreselected: false,
      is_variable: isVariable,
      requires_inventory_selection: requiresInventorySelection
    };
  }

  function mapApiOutputToWizardSessionOutput(apiOut) {
    if (!apiOut) {
      return {
        id: null,
        name: '',
        unit: '',
        quantity: null,
        is_variable: true,
        requires_execution_confirmation: true
      };
    }
    const qty = apiOut.quantity;
    let quantity = null;
    if (qty != null && qty !== '') {
      const n = typeof qty === 'number' ? qty : parseFloat(String(qty).trim());
      quantity = isNaN(n) ? null : n;
    }
    const out = {
      id: apiOut.id || null,
      name: summaryOutputDisplayName(apiOut),
      unit: apiOut.unit || '',
      quantity,
      is_variable: apiOut.is_variable !== false,
      requires_execution_confirmation: apiOut.requires_execution_confirmation !== false
    };
    if (apiOut.extra_data && typeof apiOut.extra_data === 'object') {
      out.extra_data = JSON.parse(JSON.stringify(apiOut.extra_data));
    }
    return out;
  }

  window.ProcessModalMappers = Object.freeze({
    mapSessionInputsToApiPayloadFromRows,
    validateInventoryInputsFromSession,
    buildExecutionPromptsForApiFromSession,
    wizardSessionHasDraftStepData,
    mapSessionInputsToSummaryRows,
    mapApiInputToWizardSessionInput,
    mapApiOutputToWizardSessionOutput
  });
})();
