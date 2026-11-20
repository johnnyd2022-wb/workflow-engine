(function() {
  'use strict';

  // Get outputs from steps already created in this editing session.
  function getPreviousStepOutputs(createdSteps) {
    const previousOutputs = [];
    const sortedSteps = [...createdSteps].sort((a, b) => (a.step_number || 0) - (b.step_number || 0));

    sortedSteps.forEach(step => {
      if (step.outputs && step.outputs.length > 0) {
        step.outputs.forEach(output => {
          if (output.name) {
            const stepNumber = step.step_number || 0;
            previousOutputs.push({
              id: output.id || null,
              name: output.name,
              quantity: output.quantity !== null && output.quantity !== undefined ? output.quantity : null,
              unit: output.unit || '',
              inventory_type: output.inventory_type || null,
              step_number: stepNumber,
              is_previous_output: true,
              displayName: `Step ${stepNumber}: ${output.name}`
            });
          }
        });
      }
    });

    console.log('getPreviousStepOutputs: found', previousOutputs.length, 'outputs from', sortedSteps.length, 'steps');
    console.log('Step numbers:', sortedSteps.map(s => s.step_number));

    return previousOutputs;
  }

  window.ProcessModalPreviousOutputs = Object.freeze({ getPreviousStepOutputs });
})();
