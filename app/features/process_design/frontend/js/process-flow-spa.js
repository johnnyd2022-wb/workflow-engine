/**
 * Process flow wizard (full-page): loadProcessData redirect + HTMX re-init after swap.
 */
(function() {
  'use strict';

  function isProcessFlowWizardShell() {
    var p = document.body && document.body.getAttribute('data-page');
    return p === 'process-flow-wizard';
  }

  if (!isProcessFlowWizardShell()) {
    return;
  }

  window.loadProcessData = function() {
    var id = new URLSearchParams(window.location.search).get('id');
    window.location.href = id ? '/core/flows?id=' + encodeURIComponent(id) : '/core';
  };

  document.body.addEventListener('htmx:afterSwap', function(evt) {
    if (!evt.detail || !evt.detail.target || evt.detail.target.id !== 'page-content') {
      return;
    }
    var path = (window.location.pathname || '').replace(/\/$/, '') || '/';
    if (path.indexOf('/core/flows/create/') !== 0) {
      return;
    }
    if (typeof window.initProcessFlowWizardFromDom === 'function') {
      window.initProcessFlowWizardFromDom();
    }
    if (window.Alpine && typeof Alpine.initTree === 'function') {
      var step4 = document.getElementById('create-process-step-4');
      if (step4) {
        try {
          Alpine.initTree(step4);
        } catch (e) {}
      }
    }
  });
})();
