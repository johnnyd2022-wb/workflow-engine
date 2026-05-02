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

  function ctxBool(v) {
    return v === true || v === 'true' || v === 1 || v === '1';
  }

  function isOnExecutionStepScreen() {
    // Option B: canonical route is /core/flows/batches/start
    // (Option A alias /core/flows/executions/step redirects here).
    try {
      var p = (window.location && window.location.pathname) ? String(window.location.pathname) : '';
      return p.startsWith('/core/flows/batches/start');
    } catch (e) {
      return false;
    }
  }

  // Single-flight runner to avoid overlapping renders.
  var renderToken = 0;
  var inFlightPromise = null;
  var rerunRequested = false;
  var initScheduled = false;
  var lastInitMs = 0;

  async function loadAndRender() {
    if (!isOnExecutionStepScreen()) return;
    var myToken = ++renderToken;
    if (inFlightPromise) {
      rerunRequested = true;
      return inFlightPromise;
    }
    inFlightPromise = (async function () {
      function isStale() {
        return myToken !== renderToken;
      }
      var ctx = window.ExecutionStepPageContext || {};
      var executionId = ctx.executionId;
      var processId = ctx.processId;
      var stepId = ctx.stepId;
      var isDraft = ctxBool(ctx.draft);

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

      setSubtitle('Loading execution…');
      var executionData = null;
      var processData = null;
      var readyStep = null;

      if (!isDraft) {
        if (executionId && typeof window.CoreAPI.getExecutionWithProcess === 'function') {
          var bundle = await window.CoreAPI.getExecutionWithProcess(executionId);
          if (isStale()) return;
          if (!bundle || !bundle.execution || !bundle.process) {
            throw new Error('Invalid execution bundle response');
          }
          var bm = bundle.meta;
          if (
            !bm ||
            bm.bundle !== 'execution_with_process' ||
            typeof bm.minimal !== 'boolean'
          ) {
            throw new Error('Invalid execution bundle meta');
          }
          executionData = bundle.execution;
          processData = bundle.process;
        } else {
          executionData = await window.CoreAPI.getExecution(executionId);
          if (isStale()) return;
          processData = await window.CoreAPI.getProcess((executionData && executionData.process_id) || processId);
          if (isStale()) return;
        }
        var steps = (executionData && executionData.execution_steps) ? executionData.execution_steps : [];
        readyStep = steps.find(function (es) {
          return es && (es.status === 'ready' || es.status === 'READY');
        });
        if (!readyStep) {
          setSubtitle('No ready step found for this execution.');
          if (window.showNotification) window.showNotification('error', 'No ready step', 'There is no step ready to complete.');
          return;
        }
      } else {
        processData = await window.CoreAPI.getProcess(processId);
        if (isStale()) return;
      }

      if (!processData || !Array.isArray(processData.steps)) {
        throw new Error('Invalid process payload');
      }

      var procSteps = (processData && processData.steps) ? processData.steps : [];
      var stepMap = new Map();
      procSteps.forEach(function (s) {
        if (s && s.id != null) stepMap.set(String(s.id), s);
      });

      var stepDefinition = null;
      if (isDraft) {
        stepDefinition = stepMap.get(String(stepId));
      } else {
        stepDefinition = stepMap.get(String(readyStep.step_id));
      }

      if (!stepDefinition) {
        setSubtitle('Step definition not found.');
        if (window.showNotification) window.showNotification('error', 'Step not found', 'Step definition not found.');
        return;
      }
      if (isStale()) return;

      setSubtitle((isDraft ? 'Starting new batch · ' : 'Step: ') + (stepDefinition.name || 'Unknown'));

      if (typeof window.openExecutionModal !== 'function') {
        if (window.showNotification) window.showNotification('error', 'Missing UI', 'Execution UI renderer is not loaded.');
        return;
      }

      if (isDraft) {
        await window.openExecutionModal(null, null, stepDefinition, { processId: processId, renderMode: 'page' });
      } else {
        await window.openExecutionModal(executionId, readyStep, stepDefinition, {
          processId: processId,
          renderMode: 'page',
        });
      }
    })().catch(function (e) {
      console.error('Failed to load execution step page:', e);
      setSubtitle('Failed to load.');
      if (window.showNotification) window.showNotification('error', 'Failed to load', e && e.message ? e.message : 'Please try again.');
    }).finally(function () {
      inFlightPromise = null;
      if (rerunRequested) {
        rerunRequested = false;
        scheduleInit();
      }
    });
    return inFlightPromise;
  }

  // Expose for HTMX swaps.
  window.initExecutionStepScreen = function () {
    // Only run if the fragment is present.
    if (!qs('execute-step-modal')) return;
    scheduleInit();
  };

  function scheduleInit() {
    if (initScheduled) return;
    initScheduled = true;
    // Dedupe bursts from DOMContentLoaded / pageshow / htmx:afterSettle (microtask vs timer fragility).
    queueMicrotask(function () {
      initScheduled = false;
      var now = Date.now();
      if (now - lastInitMs < 50) return;
      lastInitMs = now;
      loadAndRender();
    });
  }

  document.addEventListener('DOMContentLoaded', function () { window.initExecutionStepScreen(); });

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

  // When this script is re-executed by an HTMX swap, DOMContentLoaded and htmx:afterSettle
  // have already fired. Call init immediately if the DOM is ready.
  if (document.readyState !== 'loading') {
    window.initExecutionStepScreen();
  }
})();
