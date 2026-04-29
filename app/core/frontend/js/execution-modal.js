// ============================================================
// SHARED EXECUTION MODAL FUNCTIONS
// ============================================================
// This file provides openExecutionModal and submitExecution functions
// that can be used in both flows2.html and core2.html
//
// Configuration:
// Set window.ExecutionModalConfig before loading this script:
//   window.ExecutionModalConfig = {
//     onStepCompleted: async function() {
//       // Called after step is completed successfully
//       // e.g., await loadExecutions(); await loadInventory();
//       // or: await loadInventoryV2();
//     }
//   };
//
// Dependencies:
// - execution-shared-utils.js, execution-session.js, execution-security-utils.js, execution-doc-overlay.js, execution-render-docs.js,
//   execution-render-prompts.js, execution-render-inputs.js, execution-render-outputs.js,
//   execution-submit.js, execution-modal-secondary.js, execution-open-step.js (must be loaded before this script)
// - CoreAPI (must be loaded before this script)
// - escapeHtml function (must be defined globally)
// - getCurrentUser function (must be defined globally)
// - showNotification function (must be defined globally)
// ============================================================

(function() {
  'use strict';
  // Safety: this file is used in multiple shells; ensure notifications never crash execution.
  // Prefer the app's global showNotification (from core.js) when available.
  if (typeof window.showNotification !== 'function') {
    window.showNotification = function(type, title, message) {
      try {
        var t = (title || '').toString();
        var m = (message || '').toString();
        var line = (t ? (t + (m ? ': ' : '')) : '') + (m || '');
        if (typeof console !== 'undefined' && console.warn) console.warn('Notification:', type, line);
        // Keep it non-blocking where possible; fall back to alert for visibility.
        if (type === 'error' && typeof console !== 'undefined' && console.warn) {
          console.warn('Notification:', line || 'An error occurred.');
        }
      } catch (e) {}
    };
  }

  // Safety: execution submit uses getCurrentUser() for audit fields.
  if (typeof window.getCurrentUser !== 'function') {
    window.getCurrentUser = async function() {
      const resp = await fetch('/auth/me', { credentials: 'same-origin', cache: 'no-store' });
      const data = await resp.json();
      const u = data && data.user ? data.user : null;
      if (!u) return { id: '', username: '', email: '' };
      const name = [u.first_name, u.last_name].filter(Boolean).join(' ').trim();
      return { id: u.id || '', username: name || u.email || '', email: u.email || '' };
    };
  }

  var ESU = window.ExecutionSharedUtils;
  if (!ESU || typeof ESU.convertUnit !== 'function') {
    throw new Error('execution-shared-utils.js must be loaded before execution-modal.js');
  }
  var convertUnit = ESU.convertUnit;
  var prettyLabel = ESU.prettyLabel;
  var loadOrgUsersMap = ESU.loadOrgUsersMap;

  var SessionAPI = window.ExecutionSessionAPI;
  if (!SessionAPI || typeof SessionAPI.get !== 'function') {
    throw new Error('execution-session.js must be loaded before execution-modal.js');
  }
  if (!window.ExecutionRenderDocs || typeof window.ExecutionRenderDocs.renderStepDocumentation !== 'function') {
    throw new Error('execution-render-docs.js must be loaded before execution-modal.js');
  }
  if (!window.ExecutionRenderPrompts || typeof window.ExecutionRenderPrompts.renderExecutionPrompts !== 'function') {
    throw new Error('execution-render-prompts.js must be loaded before execution-modal.js');
  }
  if (!window.ExecutionRenderInputs || typeof window.ExecutionRenderInputs.renderVariableInventoryInputs !== 'function' || typeof window.ExecutionRenderInputs.renderConfirmExecutionInputs !== 'function') {
    throw new Error('execution-render-inputs.js must be loaded before execution-modal.js');
  }
  if (!window.ExecutionRenderOutputs || typeof window.ExecutionRenderOutputs.renderVariableOutputs !== 'function') {
    throw new Error('execution-render-outputs.js must be loaded before execution-modal.js');
  }
  if (!window.ExecutionSubmit || typeof window.ExecutionSubmit.submitExecution !== 'function') {
    throw new Error('execution-submit.js must be loaded before execution-modal.js');
  }
  if (!window.ExecutionModalSecondary || typeof window.ExecutionModalSecondary.install !== 'function') {
    throw new Error('execution-modal-secondary.js must be loaded before execution-modal.js');
  }
  if (!window.ExecutionOpenStep || typeof window.ExecutionOpenStep.openExecutionModal !== 'function') {
    throw new Error('execution-open-step.js must be loaded before execution-modal.js');
  }
  if (!window.ExecutionSecurityUtils || typeof window.ExecutionSecurityUtils.isSameOriginEmbedUrl !== 'function') {
    throw new Error('execution-security-utils.js must be loaded before execution-modal.js');
  }

  // Get configuration or use defaults
  const config = window.ExecutionModalConfig || {
    onStepCompleted: async function() {
      console.warn('ExecutionModalConfig.onStepCompleted not configured. Set window.ExecutionModalConfig before loading this script.');
    }
  };

  window.ExecutionModalSecondary.install({
    config: config,
    CoreAPI: window.CoreAPI,
  });

  // ============================================================
  // OPEN EXECUTION MODAL
  // ============================================================
  window.openExecutionModal = async function(executionId, executionStep, stepDefinition, options) {
    return window.ExecutionOpenStep.openExecutionModal(
      {
        SessionAPI: SessionAPI,
        convertUnit: convertUnit,
        prettyLabel: prettyLabel,
        loadOrgUsersMap: loadOrgUsersMap,
        CoreAPI: window.CoreAPI,
      },
      executionId,
      executionStep,
      stepDefinition,
      options
    );
  };

  
  // ============================================================
  // SUBMIT EXECUTION (Complete Step with Data)
  // ============================================================
  window.submitExecution = async function() {
    return window.ExecutionSubmit.submitExecution({
      SessionAPI: SessionAPI,
      convertUnit: convertUnit,
      config: config,
      CoreAPI: window.CoreAPI,
      showNotification: window.showNotification,
      getCurrentUser: window.getCurrentUser,
    });
  };

  /**
   * Run the same client-side checks as submit (inventory, prompts, evidence, confirm inputs,
   * set_at_execution output expiry/ready date). Async: fetches step definition outputs when needed.
   * Returns true if valid; on false, shows the same validation toast/scroll as submit.
   * Does not create a draft execution — safe to call before the record-step confirmation modal.
   */
  window.validateExecutionStepForm = async function() {
    if (!window.ExecutionSubmit || typeof window.ExecutionSubmit.validateExecutionStepForm !== 'function') {
      return false;
    }
    return await window.ExecutionSubmit.validateExecutionStepForm({
      SessionAPI: SessionAPI,
      convertUnit: convertUnit,
      showNotification: window.showNotification,
      CoreAPI: window.CoreAPI,
    });
  };



})();
