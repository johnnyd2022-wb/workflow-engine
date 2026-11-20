(function() {
  'use strict';

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
      explanation.innerHTML = '<strong>At execution:</strong> Quantity and unit are populated with these values and the operator confirms when this step is run.';
    } else if (value === 'static') {
      explanation.innerHTML = '<strong>Fixed:</strong> The same quantity and unit are used every execution. Operators will not be prompted to confirm when this step runs.';
    } else {
      explanation.innerHTML = '<strong>Prompt:</strong> Operators are prompted to enter quantity and unit each time this step runs. This option is useful when the quantity and/or unit might be variable from batch to batch.';
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
      { value: 'variable', label: 'Operator to confirm' },
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

  window.updateStep4SummaryBar = updateStep4SummaryBar;
  window.ProcessModalControls = Object.freeze({
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
  });
})();
