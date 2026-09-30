(function() {
  'use strict';

  function buildSpaWizardSessionPayloadFromApiStep(step, opts, helpers) {
    const urlPid = opts && opts.processId != null ? opts.processId : null;
    const workflowProcessName =
      opts && opts.workflowProcessName != null ? String(opts.workflowProcessName).trim() : '';
    const tm = helpers.deriveTraceabilityModes(step);
    const inputs = (step.inputs || []).map(helpers.mapApiInputToWizardSessionInput);
    const outputs = (step.outputs || []).map(helpers.mapApiOutputToWizardSessionOutput);
    const prompts = (step.execution_prompts || []).filter(helpers.isCustomExecutionPrompt).map(function(p) {
      return {
        label: (p.label || '').trim(),
        type: p.type || 'text',
        unit: (p.unit || '').trim(),
        required: p.required !== false,
        ...(p.type === 'select' ? { options: helpers.normalisePromptOptions(p.options) } : {})
      };
    });
    return {
      v: 1,
      stepName: step.name || '',
      stepDescription: step.description || '',
      workflowProcessName,
      inputs,
      outputs,
      prompts,
      batchNumberMode: tm.batch,
      evidenceMode: tm.evidence,
      inputTab: 'inventory',
      editingStepId: step.id || null,
      createdSteps: JSON.parse(JSON.stringify(helpers.createdSteps)),
      docInlineTitle: '',
      docInlineContent: '',
      processId: urlPid,
      docFileUpload: null
    };
  }

  window.ProcessModalApiSession = Object.freeze({
    buildSpaWizardSessionPayloadFromApiStep
  });
})();
