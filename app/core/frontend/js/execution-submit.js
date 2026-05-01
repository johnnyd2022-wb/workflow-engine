/**
 * Complete-step submission: validation + CoreAPI.completeStep.
 * execution-modal.js delegates window.submitExecution with dependency ctx.
 */
(function (root) {
  'use strict';

  /**
   * Client-side checks only (inventory, prompts, evidence attachments, confirm qty/unit).
   * Does not require execution id — safe to run before the record-step confirmation modal.
   * Mutates field borders like submit (same UX as direct Complete step).
   */
  function collectClientValidationErrors(modal, ses, convertUnit) {
    const validationErrors = [];

    const inputRows = modal.querySelectorAll('.execute-input-row');
    inputRows.forEach(function (row) {
      const select = row.querySelector('.execute-inventory-select');
      const quantityInput = row.querySelector('.execute-quantity-input');
      if (!select || !quantityInput) return;
      const inventoryId = select.value;
      const inputName = select.dataset.inputName;
      if (!inventoryId || inventoryId === '') return;
      const quantity = parseFloat(quantityInput.value);
      if (!quantity || isNaN(quantity) || quantity <= 0) {
        validationErrors.push('Please enter a valid quantity for "' + inputName + '" (selected row)');
        quantityInput.style.border = '2px solid var(--error, #ef4444)';
      } else {
        quantityInput.style.border = '';
        const availableQty = parseFloat(select.dataset.quantity);
        if (!isNaN(availableQty) && quantity > availableQty) {
          const inventoryUnit = select.dataset.unit || '';
          const stepUnit = (quantityInput.dataset.stepUnit || '').trim();
          var qtyInInvUnit = quantity;
          if (stepUnit && inventoryUnit && stepUnit.toLowerCase() !== inventoryUnit.toLowerCase()) {
            const conv = convertUnit(quantity, stepUnit, inventoryUnit);
            if (conv !== quantity || stepUnit.toLowerCase() === inventoryUnit.toLowerCase()) {
              qtyInInvUnit = conv;
            } else {
              qtyInInvUnit = NaN;
            }
          }
          if (!isNaN(qtyInInvUnit) && qtyInInvUnit > availableQty) {
            const qtyLabel = stepUnit ? quantity + ' ' + stepUnit : String(quantity);
            const availLabel = stepUnit
              ? Number(convertUnit(availableQty, inventoryUnit, stepUnit).toFixed(3)) + ' ' + stepUnit
              : String(availableQty) + ' ' + inventoryUnit;
            validationErrors.push('Quantity for "' + inputName + '" (' + qtyLabel + ') exceeds available inventory (' + availLabel + ')');
            quantityInput.style.border = '2px solid var(--error, #ef4444)';
          }
        }
      }
    });

    modal.querySelectorAll('.execute-input-rows-container').forEach(function (container) {
      var inputName = container.dataset.inputName || '';
      var rows = container.querySelectorAll('.execute-input-row');
      if (!inputName || !rows.length) return;
      var ok = false;
      rows.forEach(function (row) {
        var sel = row.querySelector('.execute-inventory-select');
        var qtyEl = row.querySelector('.execute-quantity-input');
        var stateKey = row.dataset.stateKey;
        var invId = sel && sel.value ? String(sel.value).trim() : '';
        if (!invId && stateKey && ses.inputStateByKey && ses.inputStateByKey.has(stateKey)) {
          var st = ses.inputStateByKey.get(stateKey);
          if (st && st.inventory_item_id) invId = String(st.inventory_item_id);
        }
        var q = qtyEl ? parseFloat(qtyEl.value) : NaN;
        if ((isNaN(q) || q <= 0) && stateKey && ses.inputStateByKey && ses.inputStateByKey.has(stateKey)) {
          var stQty = ses.inputStateByKey.get(stateKey);
          if (stQty && stQty.quantity != null) q = parseFloat(stQty.quantity);
        }
        if (invId && !isNaN(q) && q > 0) ok = true;
      });
      if (!ok) {
        validationErrors.push('Please select inventory and a valid quantity for "' + inputName + '".');
        rows.forEach(function (row) {
          var qtyEl = row.querySelector('.execute-quantity-input');
          var sel = row.querySelector('.execute-inventory-select');
          var sk = row.dataset.stateKey;
          var id = sel && sel.value ? String(sel.value).trim() : '';
          if (!id && sk && ses.inputStateByKey && ses.inputStateByKey.has(sk)) {
            var st2 = ses.inputStateByKey.get(sk);
            if (st2 && st2.inventory_item_id) id = String(st2.inventory_item_id);
          }
          if (!id && qtyEl) qtyEl.style.border = '2px solid var(--error, #ef4444)';
          else if (id && qtyEl) {
            var qq = parseFloat(qtyEl.value);
            if (isNaN(qq) || qq <= 0) qtyEl.style.border = '2px solid var(--error, #ef4444)';
          }
        });
      }
    });

    modal.querySelectorAll('.execute-prompt-input[data-required="true"]').forEach(function (input) {
      const label = input.dataset.promptLabel;
      const value = input.value.trim();
      if (!value) {
        validationErrors.push('Please fill in required field: "' + label + '"');
        input.style.border = '2px solid var(--error, #ef4444)';
      } else {
        input.style.border = '';
      }
    });

    modal.querySelectorAll('.execute-prompt-section[data-prompt-type="evidence"][data-prompt-required="true"]').forEach(function (section) {
      const uploadZone = section.querySelector('.execute-evidence-upload');
      const label = section.dataset.promptLabel || 'Evidence';
      const stepId = uploadZone && uploadZone.dataset.stepId;
      const list = (ses.evidenceByStepId && stepId && ses.evidenceByStepId.get(stepId)) || [];
      const pending = (ses.pendingEvidenceFilesByStepId && stepId && ses.pendingEvidenceFilesByStepId.get(stepId)) || [];
      const count = (list.length || 0) + (pending.length || 0);
      if (count < 1) {
        validationErrors.push('Please upload at least one file for "' + label + '"');
        if (uploadZone) uploadZone.style.borderColor = 'var(--error, #ef4444)';
      } else if (uploadZone) {
        uploadZone.style.borderColor = '';
      }
    });

    modal.querySelectorAll('.execute-confirm-quantity-input[data-required="true"]').forEach(function (input) {
      const quantity = parseFloat(input.value);
      const inputName = input.dataset.inputName;
      const confirmUnitSelects = modal.querySelectorAll('.execute-confirm-unit-input[data-required="true"]');
      const unitSelect = Array.from(confirmUnitSelects).find(function (sel) {
        return sel.dataset.inputName === inputName;
      });
      const unit = unitSelect ? unitSelect.value : '';
      if (isNaN(quantity) || quantity <= 0) {
        validationErrors.push('Please enter a valid quantity for "' + inputName + '"');
        input.style.border = '2px solid var(--error, #ef4444)';
      } else {
        input.style.border = '';
      }
      if (!unit) {
        validationErrors.push('Please select a unit for "' + inputName + '"');
        if (unitSelect) unitSelect.style.border = '2px solid var(--error, #ef4444)';
      } else if (unitSelect) {
        unitSelect.style.border = '';
      }
    });

    return validationErrors;
  }

  async function fetchAllStepOutputsForModal(modal, CoreAPI) {
    if (!CoreAPI || typeof CoreAPI.getProcess !== 'function') return null;
    var processId = (modal.dataset && modal.dataset.processId) ? String(modal.dataset.processId).trim() : '';
    var stepDefId = (modal.dataset && modal.dataset.stepDefinitionId) ? String(modal.dataset.stepDefinitionId).trim() : '';
    try {
      if (root.ExecutionStepPageContext) {
        if (!processId && root.ExecutionStepPageContext.processId) processId = String(root.ExecutionStepPageContext.processId);
        if (!stepDefId && root.ExecutionStepPageContext.stepId) stepDefId = String(root.ExecutionStepPageContext.stepId);
      }
    } catch (e) {}
    var executionId = modal.dataset && modal.dataset.executionId ? String(modal.dataset.executionId).trim() : '';
    if ((!processId || !stepDefId) && executionId && typeof CoreAPI.getExecution === 'function') {
      try {
        var ex = await CoreAPI.getExecution(executionId);
        if (ex && ex.process_id && !processId) processId = String(ex.process_id);
        if (!stepDefId && modal.dataset.executionStepId && ex.execution_steps) {
          var es = (ex.execution_steps || []).find(function (s) {
            return String(s.id) === String(modal.dataset.executionStepId);
          });
          if (es && es.step_id != null) stepDefId = String(es.step_id);
        }
      } catch (e) {}
    }
    if (!processId || !stepDefId) return null;
    try {
      var processData = await CoreAPI.getProcess(processId);
      var steps = (processData && processData.steps) ? processData.steps : [];
      var stepDef = steps.find(function (s) {
        return String(s.id) === String(stepDefId);
      });
      if (!stepDef) return null;
      return stepDef.outputs && stepDef.outputs.length ? stepDef.outputs : [];
    } catch (e) {
      return null;
    }
  }

  /**
   * set_at_execution custom expiry + ready date + cross-check (same rules as submit body).
   */
  function collectOutputSetAtExecutionValidationErrors(modal, allStepOutputs) {
    var errs = [];
    if (!allStepOutputs || !allStepOutputs.length) return errs;
    var expiryValidator = window.CustomExpiryValidation || {};
    var durationToHours =
      typeof expiryValidator.durationToHours === 'function'
        ? expiryValidator.durationToHours
        : function () {
            return null;
          };
    var getOutputId =
      window.getExecutionOutputId ||
      function (o) {
        return o && o.id ? String(o.id) : 'out-' + (o && o.name ? String(o.name).replace(/\s+/g, '-') : 'unknown');
      };

    (allStepOutputs || []).forEach(function (outputDef) {
      var ce = (outputDef.extra_data || {}).custom_expiry;
      if (!ce || !ce.enabled || (ce.mode || '') !== 'set_at_execution') return;
      var outName = (outputDef.name || '').trim();
      var outId = getOutputId(outputDef);
      var box = Array.from(modal.querySelectorAll('.execute-output-expiry-input')).find(function (b) {
        return (b.dataset.outputId || '').trim() === outId;
      });
      if (!box) return;
      var modeSel = box.querySelector('.execute-output-expiry-input-mode');
      var inputMode = modeSel ? modeSel.value || 'duration' : 'duration';
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
        errs.push('Output "' + outName + '": expiry date and time must be in the future.');
        return;
      }
      if (typeof expiryValidator.validateWarnNotLongerThanExpiry === 'function') {
        var res = expiryValidator.validateWarnNotLongerThanExpiry({
          outputName: outName,
          warnValue: isNaN(warnVal) ? null : warnVal,
          warnUnit: warnUnit,
          expiryHours: expiryHours,
          expiryLabel: inputMode === 'datetime' ? 'the time remaining until expiry' : 'the expiry period',
        });
        if (res && res.valid === false) {
          errs.push(res.message || 'Output "' + outName + '": invalid warn-before-expiry setting.');
        }
      }
    });

    (allStepOutputs || []).forEach(function (outputDef) {
      var rd = (outputDef.extra_data || {}).ready_date;
      if (!rd || !rd.enabled || (rd.mode || '') !== 'set_at_execution') return;
      var outName = (outputDef.name || '').trim();
      var outputId = getOutputId(outputDef);
      var payload =
        typeof window.collectExecutionOutputReadyDatePayload === 'function'
          ? window.collectExecutionOutputReadyDatePayload(modal, outputId)
          : null;
      if (!payload || !payload.date) {
        errs.push('Output "' + outName + '": set the date when this output can be used.');
      }
    });

    if (
      typeof window.ExpiryReadyDateValidation !== 'undefined' &&
      typeof window.ExpiryReadyDateValidation.validateExpiryAfterReadyDates === 'function'
    ) {
      for (var ei = 0; ei < (allStepOutputs || []).length; ei++) {
        var od = allStepOutputs[ei];
        var rd2 = (od.extra_data || {}).ready_date;
        var ce2 = (od.extra_data || {}).custom_expiry;
        if (!rd2 || !rd2.enabled || (rd2.mode || '') !== 'set_at_execution') continue;
        if (!ce2 || !ce2.enabled || (ce2.mode || '') !== 'set_at_execution') continue;
        var oid = getOutputId(od);
        var readyPayload =
          typeof window.collectExecutionOutputReadyDatePayload === 'function'
            ? window.collectExecutionOutputReadyDatePayload(modal, oid)
            : null;
        var expiryPayload =
          typeof window.collectExecutionOutputExpiryPayload === 'function'
            ? window.collectExecutionOutputExpiryPayload(modal, oid)
            : null;
        var readyIso = readyPayload && readyPayload.date ? readyPayload.date : null;
        var expiryIso =
          expiryPayload && expiryPayload.mode === 'datetime' && expiryPayload.expiry_at ? expiryPayload.expiry_at : null;
        if (readyIso && expiryIso) {
          var oname = (od.name || '').trim();
          var erResult = window.ExpiryReadyDateValidation.validateExpiryAfterReadyDates(oname, readyIso, expiryIso);
          if (!erResult.valid) errs.push(erResult.message || 'Output "' + oname + '": expiry must be after ready date.');
        }
      }
    }

    return errs;
  }

  async function mergeOutputValidationErrors(modal, CoreAPI) {
    var outputs = await fetchAllStepOutputsForModal(modal, CoreAPI);
    if (!outputs || !outputs.length) return [];
    return collectOutputSetAtExecutionValidationErrors(modal, outputs);
  }

  async function validateExecutionStepForm(ctx) {
    var showNotification =
      typeof ctx.showNotification === 'function' ? ctx.showNotification : root.showNotification;
    var SessionAPI = ctx.SessionAPI;
    var convertUnit = ctx.convertUnit;
    var CoreAPI = ctx.CoreAPI != null ? ctx.CoreAPI : root.CoreAPI;
    var modal = document.getElementById('execute-step-modal');
    if (!modal) return false;
    var ses = SessionAPI.get(modal);
    var validationErrors = collectClientValidationErrors(modal, ses, convertUnit);
    var outputErrs = await mergeOutputValidationErrors(modal, CoreAPI);
    validationErrors = validationErrors.concat(outputErrs || []);
    if (validationErrors.length > 0) {
      if (typeof showNotification === 'function') {
        showNotification('error', 'Validation Error', validationErrors.join('. ') + '.');
      }
      var firstError = modal.querySelector('[style*="border: 2px solid var(--error"]');
      if (!firstError) {
        firstError = modal.querySelector('.execute-output-ready-date-input, .execute-output-expiry-input');
      }
      if (firstError) {
        firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
        if (typeof firstError.focus === 'function') firstError.focus();
      }
      return false;
    }
    return true;
  }

  async function submitExecution(ctx) {
    var SessionAPI = ctx.SessionAPI;
    var convertUnit = ctx.convertUnit;
    var config = ctx.config || {};
    var CoreAPI = ctx.CoreAPI != null ? ctx.CoreAPI : root.CoreAPI;
    var showNotification =
      typeof ctx.showNotification === 'function' ? ctx.showNotification : root.showNotification;
    var getCurrentUser =
      typeof ctx.getCurrentUser === 'function' ? ctx.getCurrentUser : root.getCurrentUser;

    const modal = document.getElementById('execute-step-modal');
    if (!modal) return;
    if (modal._submitExecutionInFlight) return;
    modal._submitExecutionInFlight = true;
    try {
    var ses = SessionAPI.get(modal);
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

    var validationErrors = collectClientValidationErrors(modal, ses, convertUnit);
    var outputValErrs = await mergeOutputValidationErrors(modal, CoreAPI);
    validationErrors = validationErrors.concat(outputValErrs || []);
    if (validationErrors.length > 0) {
      showNotification('error', 'Validation Error', validationErrors.join('. ') + '.');
      var firstErrEl = modal.querySelector('[style*="border: 2px solid var(--error"]');
      if (!firstErrEl) {
        firstErrEl = modal.querySelector('.execute-output-ready-date-input, .execute-output-expiry-input');
      }
      if (firstErrEl) {
        firstErrEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        if (typeof firstErrEl.focus === 'function') firstErrEl.focus();
      }
      return;
    }

    // Upload staged evidence (draft flow uploads happen only on Record step) — after validation passes.
    try {
      if (!ses.pendingEvidenceFilesByStepId) ses.pendingEvidenceFilesByStepId = new Map();
      var stepIdForEvidence = modal.dataset.executionStepId || modal.dataset.executionStepDefinitionId || '';
      // We keyed pending by step definition id earlier (currentStepId).
      var pendingStepKeys = Array.from(ses.pendingEvidenceFilesByStepId.keys());
      var anyPending = pendingStepKeys.some(function(k) {
        var arr = ses.pendingEvidenceFilesByStepId.get(k) || [];
        return arr && arr.length;
      });
      if (anyPending) {
        // Ensure we have a real execution (draft).
        if (draftProcessId && (!executionId || !executionStepId)) {
          var createResult = await CoreAPI.createExecution(draftProcessId);
          executionId = createResult.id || createResult.execution_id || (createResult.execution && createResult.execution.id);
          if (!executionId) throw new Error('Could not create execution for evidence upload.');
          var executionData2 = await CoreAPI.getExecution(executionId);
          var steps2 = executionData2.execution_steps || [];
          var readyStep2 = steps2.find(function(es) { return es.status === 'ready' || es.status === 'READY'; });
          if (readyStep2 && readyStep2.id) executionStepId = readyStep2.id;
          modal.dataset.executionId = String(executionId);
          modal.dataset.executionStepId = String(executionStepId || '');
          modal.dataset.draftProcessId = '';
          draftProcessId = '';
        }
        // Upload pending files per step definition id.
        for (var pk = 0; pk < pendingStepKeys.length; pk++) {
          var stepDefId = pendingStepKeys[pk];
          var files = ses.pendingEvidenceFilesByStepId.get(stepDefId) || [];
          if (!files.length) continue;
          var added = [];
          for (var fi = 0; fi < files.length; fi++) {
            var fd = new FormData();
            fd.append('file', files[fi]);
            fd.append('execution_id', String(executionId));
            fd.append('step_id', String(stepDefId));
            var res = await CoreAPI.uploadEvidence(fd);
            if (res && res.id) added.push(res);
          }
          // Merge into evidence list cache
          if (!ses.evidenceByStepId) ses.evidenceByStepId = new Map();
          var existing = (ses.evidenceByStepId.get(stepDefId) || []);
          var merged = existing.concat(added);
          var seen = new Set();
          merged = merged.filter(function(e) {
            if (!e || !e.id) return false;
            if (seen.has(e.id)) return false;
            seen.add(e.id);
            return true;
          });
          ses.evidenceByStepId.set(stepDefId, merged);
          ses.pendingEvidenceFilesByStepId.set(stepDefId, []);
        }
      }
    } catch (e) {
      showNotification('error', 'Evidence upload failed', e && e.message ? e.message : String(e));
      return;
    }

    var invList = ses.inventoryForSubmit || [];
    var invById = new Map();
    invList.forEach(function(i) { if (i && i.id != null) invById.set(String(i.id), i); });
    var notReadyUsed = [];
    var stateIter = (ses.inputStateByKey && ses.inputStateByKey.size > 0)
      ? Array.from(ses.inputStateByKey.values())
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
      if (ses.inputStateByKey && ses.inputStateByKey.size > 0) {
        Array.from(ses.inputStateByKey.values()).forEach(function(st) {
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

      // set_at_execution expiry / ready date / cross-validation runs earlier with collectOutputSetAtExecutionValidationErrors.

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
      executionData.completed_by_user_id = user.id || '';
      executionData.completed_at = new Date().toISOString();

      // Complete the step (send allow_consumption_override when user confirmed "Use anyway" for not-ready items)
      const completeResult = await CoreAPI.completeStep(executionId, executionStepId, {
        actual_inputs: actualInputs,
        actual_outputs: actualOutputs,
        execution_data: executionData,
        allow_consumption_override: allowConsumptionOverride || undefined
      });
      
      // Close modal (clean up dropdown listener first)
      if (ses.closeInventoryDropdown) {
        try { ses.closeInventoryDropdown(); } finally { ses.closeInventoryDropdown = null; }
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

    } finally {
      modal._submitExecutionInFlight = false;
    }

  }

  root.ExecutionSubmit = {
    submitExecution: submitExecution,
    validateExecutionStepForm: validateExecutionStepForm,
    collectClientValidationErrors: collectClientValidationErrors,
  };
})(typeof window !== 'undefined' ? window : this);
