/**
 * Shell helpers for execution UI (modal vs page). Loaded before execution-modal.js on flows2 / batch-start.
 */
(function () {
  'use strict';

  window.ExecutionUI = {
    setRenderMode: function (modal, mode) {
      if (modal && modal.dataset) modal.dataset.renderMode = String(mode || 'modal');
    },
    getRenderMode: function (modal) {
      return modal && modal.dataset && modal.dataset.renderMode ? String(modal.dataset.renderMode) : 'modal';
    },
    isPageMode: function (modal) {
      return window.ExecutionUI.getRenderMode(modal) === 'page';
    },
  };
})();
