(function() {
  'use strict';

  function buildVirtualSummaryStepFromWizardSession(session, helpers) {
    if (!session || session.v !== 1) return null;
    const execution_prompts = helpers.buildExecutionPromptsForApiFromSession(session);
    const docTitle = (session.docInlineTitle || '').trim();
    const docContent = (session.docInlineContent || '').trim();
    const hasInline = docTitle && docContent;
    const hasFileMeta = !!(session.docFileUpload && session.docFileUpload.base64);
    let documentation_summary;
    if (hasFileMeta) documentation_summary = 'SOP file attached (pending upload)';
    else if (hasInline) documentation_summary = 'Instructions: ' + docTitle;
    const inputsRaw = helpers.mapSessionInputsToSummaryRows(session.inputs || []);
    return {
      id: '__pending__',
      step_number: null,
      name: (session.stepName || '').trim() || 'Untitled step',
      description: (session.stepDescription || '').trim(),
      inputs: inputsRaw.map(function(row) {
        return { name: row.name, quantity: row.quantity, unit: row.unit };
      }),
      outputs: JSON.parse(JSON.stringify(session.outputs || [])),
      execution_prompts: execution_prompts,
      batch_number_mode: session.batchNumberMode || 'optional',
      evidence_mode: session.evidenceMode || 'optional',
      documentation_summary: documentation_summary
    };
  }

  window.ProcessModalSessionSummary = Object.freeze({
    buildVirtualSummaryStepFromWizardSession
  });
})();
