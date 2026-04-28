// Shared helpers for execution UI (modal vs dedicated page).
(function () {
  'use strict';

  function getRenderMode(el) {
    try {
      var v = el && el.dataset ? el.dataset.renderMode : null;
      v = v ? String(v) : '';
      return v || 'modal';
    } catch (e) {
      return 'modal';
    }
  }

  function setRenderMode(el, mode) {
    try {
      if (!el || !el.dataset) return;
      el.dataset.renderMode = mode ? String(mode) : 'modal';
    } catch (e) {}
  }

  function isPageMode(el) {
    return getRenderMode(el) === 'page';
  }

  window.ExecutionUI = window.ExecutionUI || {
    getRenderMode: getRenderMode,
    setRenderMode: setRenderMode,
    isPageMode: isPageMode,
  };
})();

