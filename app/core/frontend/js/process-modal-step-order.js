(function() {
  'use strict';

  function createPersistStepOrder(helpers) {
    async function persistStepOrderIfPossible() {
      const pid = new URLSearchParams(window.location.search || '').get('id');
      const api = helpers.getCoreApi();
      if (!pid || !api || !api.reorderSteps) return;
      const ordered = helpers.sortStepsForDisplay(helpers.getCreatedSteps()).filter(function(s) { return s && s.id; });
      const orders = ordered.map(function(s) { return s.id; });
      // Reorder's concurrency token is the newest step updated_at across the process.
      const expectedUpdatedAt = ordered
        .map(function(s) { return s.updated_at; })
        .filter(Boolean)
        .sort()
        .pop();
      try {
        await api.reorderSteps(pid, orders, expectedUpdatedAt);
      } catch (e) {
        if (api.isStaleWrite && api.isStaleWrite(e)) {
          if (window.showNotification) {
            window.showNotification(
              'warning',
              'Changed elsewhere',
              'Someone else changed this process’s steps. Reloading the current order.'
            );
          }
          await helpers.reloadSteps();
          await helpers.refreshSummaries();
          return;
        }
        console.warn('persistStepOrderIfPossible failed', e);
      }
    }
    return persistStepOrderIfPossible;
  }

  window.ProcessModalStepOrder = Object.freeze({ create: createPersistStepOrder });
})();
