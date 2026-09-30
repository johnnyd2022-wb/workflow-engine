(function() {
  'use strict';

  function createOutputPayloadRestorer(helpers) {
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
    helpers.syncOutputExpiryModeSegments(lastOutputContainer);
    helpers.syncOutputReadyDateModeSegments(lastOutputContainer);
  }
    return applyOutputPayloadToLastContainer;
  }

  window.ProcessModalOutputRestore = Object.freeze({ create: createOutputPayloadRestorer });
})();
