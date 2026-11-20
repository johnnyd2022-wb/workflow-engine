(function() {
  'use strict';

  function createRestoreControls(helpers) {
    function refresh() {
      if (typeof helpers.syncStep4ModeSegments === 'function') {
        helpers.syncStep4ModeSegments();
      }
      if (typeof helpers.updateStep4SummaryBar === 'function') {
        helpers.updateStep4SummaryBar();
      }
    }

    return function restoreControls(data) {
      const batchEl = document.getElementById('guided-prompt-batch-number-mode');
      if (batchEl) {
        const mode = data.batchNumberMode;
        if (mode === 'required' || mode === 'optional' || mode === 'dont_ask') {
          batchEl.value = mode;
        }
      }

      const evidenceEl = document.getElementById('guided-prompt-evidence-mode');
      if (evidenceEl) {
        const mode = data.evidenceMode;
        if (mode === 'required' || mode === 'optional' || mode === 'dont_ask') {
          evidenceEl.value = mode;
        }
      }

      if (data.inputTab) {
        const tabButton = document.querySelector(
          '.flow-mode-segment[data-input-tab="' + data.inputTab + '"]'
        );
        if (tabButton) tabButton.click();
      }

      helpers.updateInputButtonsText();
      helpers.updateOutputButtonText();
      refresh();
      requestAnimationFrame(refresh);
    };
  }

  window.ProcessModalRestoreControls = Object.freeze({ create: createRestoreControls });
})();
