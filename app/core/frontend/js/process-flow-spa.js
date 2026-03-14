/**
 * Process Flow SPA — full-page create/edit process step flow.
 * Reuses create-process-modal.js; this script only handles SPA-specific behavior:
 * - Back link, redirect on close/finish, and loadProcessData override.
 */
(function() {
  'use strict';

  if (!document.body || !document.body.hasAttribute('data-page') || document.body.getAttribute('data-page') !== 'process-flow-spa') {
    return;
  }

  var processId = new URLSearchParams(window.location.search).get('id');

  // Back link
  var backLink = document.getElementById('process-flow-spa-back-link');
  var backText = document.getElementById('process-flow-spa-back-text');
  if (backLink) {
    backLink.href = processId ? '/core/flows?id=' + encodeURIComponent(processId) : '/core';
    if (backText) {
      backText.textContent = processId ? 'Back to process' : 'Back to Process Hub';
    }
  }

  // When modal logic calls loadProcessData (after close, save draft, or finish), redirect instead of refreshing in place.
  window.loadProcessData = function() {
    var id = new URLSearchParams(window.location.search).get('id');
    window.location.href = id ? '/core/flows?id=' + encodeURIComponent(id) : '/core';
  };

  // Ensure step display is in sync when SPA loads (e.g. after navigation). Step 1 is already visible in HTML; modal script may have set currentStep.
  if (typeof window.updateStepDisplay === 'function') {
    window.updateStepDisplay();
  }
})();
