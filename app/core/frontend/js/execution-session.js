/**
 * Transient execution-step UI state (inventory picker, evidence staging, etc.).
 * Identity fields stay on modal.dataset (executionId, …); this holds Maps/refs only.
 *
 * Load before execution-modal.js — exposes window.ExecutionSessionAPI.
 */
(function (root) {
  'use strict';

  var sessions = new WeakMap();

  function emptySession() {
    return {
      inputStateByKey: new Map(),
      editingInputRow: null,
      inventoryForSubmit: null,
      closeInventoryDropdown: null,
      pendingEvidenceFilesByStepId: new Map(),
      evidenceByStepId: new Map(),
    };
  }

  /**
   * @param {HTMLElement | null} el execute-step root (#execute-step-modal)
   */
  function get(el) {
    if (!el) return null;
    var s = sessions.get(el);
    if (!s) {
      s = emptySession();
      sessions.set(el, s);
    }
    return s;
  }

  /** Call when opening the execution UI for a step (clears staging Maps). */
  function resetForOpen(el) {
    if (!el) return;
    sessions.set(el, emptySession());
  }

  var api = {
    get: get,
    resetForOpen: resetForOpen,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.ExecutionSessionAPI = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
