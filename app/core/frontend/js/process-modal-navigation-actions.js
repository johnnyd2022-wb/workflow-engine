(function() {
  'use strict';

  function createNavigationActions(helpers) {
  /** First wizard screen (process overview): require process name, then go to step-name. */
  function goFromProcessOverviewToStepName() {
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
  }

  function createProcessNextStep() {
    if (helpers.getCurrentStep() === 1) {
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
    if (helpers.getCurrentStep() === 2) {
      const result = helpers.validateInventoryInputs();
      if (!result.valid) {
        if (window.showNotification) {
          window.showNotification('error', 'Inventory inputs required', result.message);
        } else {
          alert(result.message);
        }
        return;
      }
    }
    if (helpers.getCurrentStep() === 3) {
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

      const expiryValidation = helpers.validateFixedExpiryWarning(outputsForValidation);
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
            if (match.dataset && match.dataset.expanded === 'false' && typeof helpers.toggleOutputExpand === 'function') {
              helpers.toggleOutputExpand(match.id);
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
      const rdValidation = helpers.validateFixedReadyDateWarning(outputsWithReadyDate);
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
            if (match.dataset && match.dataset.expanded === 'false' && typeof helpers.toggleOutputExpand === 'function') {
              helpers.toggleOutputExpand(match.id);
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
              if (outputEl.dataset && outputEl.dataset.expanded === 'false' && typeof helpers.toggleOutputExpand === 'function') {
                helpers.toggleOutputExpand(outputEl.id);
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
              if (match.dataset && match.dataset.expanded === 'false' && typeof helpers.toggleOutputExpand === 'function') {
                helpers.toggleOutputExpand(match.id);
              }
              match.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
          } catch (e) {}
          return;
        }
      }
    }
    
    if (helpers.isProcessFlowSpaPage()) {
      if (typeof window.persistSpaWizardState === 'function') {
        window.persistSpaWizardState();
      }
      if (helpers.getCurrentStep() < helpers.totalSteps) {
        const nextSlug = { 1: 'inputs', 2: 'outputs', 3: 'evidence-and-prompts' }[helpers.getCurrentStep()];
        if (nextSlug) {
          window.location.href = '/core/flows/create/' + nextSlug + (window.location.search || '');
        }
      }
      return;
    }

    if (helpers.getCurrentStep() < helpers.totalSteps) {
      helpers.setCurrentStep(helpers.getCurrentStep() + 1);
      helpers.updateStepDisplay();
    }
  }
  
  function createProcessPreviousStep() {
    if (helpers.getCurrentStep() > 1) {
      helpers.setCurrentStep(helpers.getCurrentStep() - 1);
      helpers.updateStepDisplay();
    }
  }
    return { goFromProcessOverviewToStepName, createProcessNextStep, createProcessPreviousStep };
  }

  window.ProcessModalNavigationActions = Object.freeze({ create: createNavigationActions });
})();
