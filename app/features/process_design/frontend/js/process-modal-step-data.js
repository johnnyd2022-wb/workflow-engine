(function() {
  'use strict';

  const { summaryInputDisplayName, summaryOutputDisplayName } = window.ProcessModalUtils;

  function countNamedStepInputs(inputs) {
    if (!Array.isArray(inputs)) return 0;
    return inputs.filter(function (i) {
      return i && summaryInputDisplayName(i);
    }).length;
  }

  function countNamedStepOutputs(outputs) {
    if (!Array.isArray(outputs)) return 0;
    return outputs.filter(function (o) {
      return o && summaryOutputDisplayName(o);
    }).length;
  }

  function mergeDraftCreatedStepsIntoApiSteps(apiSteps, draftSteps) {
    if (!Array.isArray(apiSteps) || apiSteps.length === 0) return apiSteps;
    const draftById = new Map();
    (draftSteps || []).forEach(function (s) {
      if (s && s.id) draftById.set(String(s.id), s);
    });
    return apiSteps.map(function (api) {
      const d = draftById.get(String(api.id));
      if (!d) return { ...api };
      const merged = { ...api };
      const draftOut = countNamedStepOutputs(d.outputs);
      const apiOut = countNamedStepOutputs(merged.outputs);
      if (apiOut === 0 && draftOut > 0) {
        merged.outputs = JSON.parse(JSON.stringify(d.outputs));
      }
      const draftIn = countNamedStepInputs(d.inputs);
      const apiIn = countNamedStepInputs(merged.inputs);
      if (apiIn === 0 && draftIn > 0) {
        merged.inputs = JSON.parse(JSON.stringify(d.inputs));
      }
      const draftPrompts = Array.isArray(d.execution_prompts)
        ? d.execution_prompts.filter(function (p) {
            return p && (p.label || '').trim();
          }).length
        : 0;
      const apiPrompts = Array.isArray(merged.execution_prompts)
        ? merged.execution_prompts.filter(function (p) {
            return p && (p.label || '').trim();
          }).length
        : 0;
      if (apiPrompts === 0 && draftPrompts > 0) {
        merged.execution_prompts = JSON.parse(JSON.stringify(d.execution_prompts));
      }
      if (merged.batch_number_mode == null && d.batch_number_mode != null) merged.batch_number_mode = d.batch_number_mode;
      if (merged.evidence_mode == null && d.evidence_mode != null) merged.evidence_mode = d.evidence_mode;
      return merged;
    });
  }

  function stepSortKey(step) {
    // Avoid JS float precision issues: treat position as a string-ish key.
    // We only need stable ordering; server normalization keeps positions simple.
    if (!step) return '';
    if (step.position !== null && step.position !== undefined && step.position !== '') {
      return String(step.position);
    }
    return String(step.step_number || '');
  }

  function sortStepsForDisplay(steps) {
    return [...(steps || [])].sort(function(a, b) {
      const ka = stepSortKey(a);
      const kb = stepSortKey(b);
      if (ka < kb) return -1;
      if (ka > kb) return 1;
      return String(a && a.id || '').localeCompare(String(b && b.id || ''));
    });
  }

  window.ProcessModalStepData = Object.freeze({
    countNamedStepInputs,
    countNamedStepOutputs,
    mergeDraftCreatedStepsIntoApiSteps,
    stepSortKey,
    sortStepsForDisplay
  });
})();
