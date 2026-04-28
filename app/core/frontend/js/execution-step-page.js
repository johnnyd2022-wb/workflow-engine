// Execution step dedicated SPA page controller.
// Loads execution + step definition and reuses the existing execution modal renderer in "page" mode.
(function () {
  'use strict';

  function qs(id) {
    return document.getElementById(id);
  }

  function setSubtitle(text) {
    var el = qs('exec-step-subtitle');
    if (!el) return;
    el.textContent = text || '';
  }

  function isOnExecutionStepScreen() {
    // Option B: canonical route is /core/flows/batches/start
    // (Option A alias /core/flows/executions/step redirects here).
    try {
      var p = (window.location && window.location.pathname) ? String(window.location.pathname) : '';
      return p.indexOf('/core/flows/batches/start') === 0;
    } catch (e) {
      return false;
    }
  }

  // Prevent overlapping renders (can cause duplicated sections / remembered unsaved UI).
  var renderToken = 0;
  var renderInFlight = false;
  var renderQueued = false;

  async function loadAndRender() {
    if (!isOnExecutionStepScreen()) return;
    var myToken = ++renderToken;
    if (renderInFlight) {
      renderQueued = true;
      return;
    }
    renderInFlight = true;
    var ctx = window.ExecutionStepPageContext || {};
    var executionId = ctx.executionId;
    var processId = ctx.processId;
    var stepId = ctx.stepId;
    var isDraft = ctx.draft === true || ctx.draft === 'true' || ctx.draft === 1 || ctx.draft === '1';
    if (!processId) {
      setSubtitle('Missing process context.');
      if (window.showNotification) window.showNotification('error', 'Missing context', 'Process ID is missing.');
      return;
    }
    if (!executionId && !(isDraft && stepId)) {
      setSubtitle('Missing execution context.');
      if (window.showNotification) window.showNotification('error', 'Missing context', 'Execution ID is missing.');
      return;
    }

    if (!window.CoreAPI || typeof window.CoreAPI.getExecution !== 'function') {
      setSubtitle('Core API not available.');
      return;
    }

    try {
      setSubtitle('Loading execution…');
      var executionData = null;
      var readyStep = null;
      if (!isDraft) {
        executionData = await window.CoreAPI.getExecution(executionId);
        if (myToken !== renderToken) return;
        var steps = (executionData && executionData.execution_steps) ? executionData.execution_steps : [];
        readyStep = steps.find(function (es) {
          return es && (es.status === 'ready' || es.status === 'READY');
        });
        if (!readyStep) {
          setSubtitle('No ready step found for this execution.');
          if (window.showNotification) window.showNotification('error', 'No ready step', 'There is no step ready to complete.');
          return;
        }
      }

      setSubtitle('Loading step definition…');
      var processData = await window.CoreAPI.getProcess((executionData && executionData.process_id) || processId);
      if (myToken !== renderToken) return;
      var procSteps = (processData && processData.steps) ? processData.steps : [];
      var stepDefinition = null;
      if (isDraft) {
        stepDefinition = procSteps.find(function (s) { return s && String(s.id) === String(stepId); });
      } else {
        stepDefinition = procSteps.find(function (s) { return s && String(s.id) === String(readyStep.step_id); });
      }
      if (!stepDefinition) {
        setSubtitle('Step definition not found.');
        if (window.showNotification) window.showNotification('error', 'Step not found', 'Step definition not found.');
        return;
      }

      setSubtitle((isDraft ? 'Starting new batch · ' : 'Step: ') + (stepDefinition.name || 'Unknown'));

      if (typeof window.openExecutionModal !== 'function') {
        if (window.showNotification) window.showNotification('error', 'Missing UI', 'Execution UI renderer is not loaded.');
        return;
      }

      // Render into the existing DOM, but suppress overlay/body locking.
      if (isDraft) {
        await window.openExecutionModal(null, null, stepDefinition, { processId: processId, renderMode: 'page' });
      } else {
        await window.openExecutionModal(executionId, readyStep, stepDefinition, { renderMode: 'page' });
      }
    } catch (e) {
      console.error('Failed to load execution step page:', e);
      setSubtitle('Failed to load.');
      if (window.showNotification) window.showNotification('error', 'Failed to load', e && e.message ? e.message : 'Please try again.');
    } finally {
      renderInFlight = false;
      if (renderQueued) {
        renderQueued = false;
        // Re-run once with latest token/context.
        loadAndRender();
      }
    }
  }

  // Expose for HTMX swaps.
  window.initExecutionStepScreen = function () {
    // Only run if the fragment is present.
    if (!qs('execute-step-modal')) return;
    loadAndRender();
  };

  document.addEventListener('DOMContentLoaded', function () {
    window.initExecutionStepScreen();
  });

  // Back/forward cache: ensure we re-render and do not keep unsaved UI state.
  window.addEventListener('pageshow', function () {
    window.initExecutionStepScreen();
  });

  // HTMX boosted navigation swaps #page-content without reloading scripts.
  document.body.addEventListener('htmx:afterSettle', function (evt) {
    var tgt = evt && evt.detail && evt.detail.target;
    if (tgt && tgt.id === 'page-content') {
      window.initExecutionStepScreen();
    }
  });
})();

