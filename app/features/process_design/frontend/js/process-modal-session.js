(function() {
  'use strict';

  const PROCESS_FLOW_PENDING_NEW_STEP_KEY = 'processFlowWizardPendingNewStep';

  function getDraftKey() {
    const urlParams = new URLSearchParams(window.location.search);
    const processId = urlParams.get('id');
    return `process-draft-${processId || 'new'}`;
  }

  function isProcessFlowSpaPage() {
    const page = document.body && document.body.getAttribute('data-page');
    return page === 'process-flow-spa' || page === 'process-flow-wizard';
  }

  function isProcessFlowWizardPage() {
    return document.body && document.body.getAttribute('data-page') === 'process-flow-wizard';
  }

  function getFlowWizardPageSlug() {
    return (document.body && document.body.getAttribute('data-flow-wizard-page')) || '';
  }

  function shouldMergePersistSpaFormFields() {
    if (isProcessFlowWizardPage()) return true;
    if (isProcessFlowSpaPage()) return true;
    const slug = document.body && document.body.getAttribute('data-flow-wizard-page');
    return slug === 'summary' || slug === 'process-overview';
  }

  function loadWizardSessionMergeBase() {
    try {
      const raw = sessionStorage.getItem(getProcessFlowSpaStorageKey());
      if (!raw) return null;
      const data = JSON.parse(raw);
      return data && data.v === 1 ? data : null;
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
    if (id) sessionStorage.removeItem('process-flow-spa-wizard-v1-' + id);
    params.delete('fresh');
    const query = params.toString();
    window.history.replaceState({}, '', window.location.pathname + (query ? '?' + query : ''));
  }

  function getProcessFlowSpaStorageKey() {
    const processId = new URLSearchParams(window.location.search).get('id');
    return 'process-flow-spa-wizard-v1-' + (processId || 'new');
  }

  function clearProcessFlowWizardRecoveryState() {
    try {
      sessionStorage.removeItem(getProcessFlowSpaStorageKey());
      sessionStorage.removeItem(PROCESS_FLOW_PENDING_NEW_STEP_KEY);
    } catch (e) {}
  }

  function bindProcessFlowWizardExitCleanup() {
    if (window._processFlowWizardExitCleanupBound) return;
    window._processFlowWizardExitCleanupBound = true;
    document.addEventListener('click', function(event) {
      if (!isProcessFlowSpaPage() || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      const anchor = event.target && event.target.closest ? event.target.closest('a[href]') : null;
      if (!anchor || anchor.target === '_blank' || anchor.hasAttribute('download')) return;
      let destination;
      try {
        destination = new URL(anchor.href, window.location.href);
      } catch (e) {
        return;
      }
      if (destination.origin !== window.location.origin) {
        clearProcessFlowWizardRecoveryState();
        return;
      }
      if (destination.pathname.indexOf('/core/flows/create/') !== 0) {
        clearProcessFlowWizardRecoveryState();
      }
    }, true);
  }

  function migrateProcessFlowSpaStorage() {
    const id = new URLSearchParams(window.location.search).get('id');
    if (!id) return;
    const newKey = 'process-flow-spa-wizard-v1-' + id;
    if (sessionStorage.getItem(newKey)) return;
    const legacy = sessionStorage.getItem('process-flow-spa-wizard-v1-new');
    if (legacy) sessionStorage.setItem(newKey, legacy);
  }

  window.ProcessModalSession = Object.freeze({
    PROCESS_FLOW_PENDING_NEW_STEP_KEY,
    getDraftKey,
    isProcessFlowSpaPage,
    isProcessFlowWizardPage,
    getFlowWizardPageSlug,
    shouldMergePersistSpaFormFields,
    loadWizardSessionMergeBase,
    applyProcessFlowWizardFreshStart,
    getProcessFlowSpaStorageKey,
    clearProcessFlowWizardRecoveryState,
    bindProcessFlowWizardExitCleanup,
    migrateProcessFlowSpaStorage
  });
})();
