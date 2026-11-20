(function() {
  'use strict';

  function createExistingStepsRenderer(helpers) {
  function showExistingStepsView() {
    const createdSteps = helpers.getCreatedSteps();
    const existingView = document.getElementById('existing-steps-list-view');
    const existingList = document.getElementById('existing-steps-list');
    const indicators = document.getElementById('create-process-step-indicators');
    if (!existingView || !existingList) return;
    // Hide step flow UI
    if (indicators) indicators.style.display = 'none';
    document.querySelectorAll('.create-process-step').forEach(el => { el.style.display = 'none'; });
    const postCreationOptions = document.getElementById('post-creation-options');
    if (postCreationOptions) postCreationOptions.style.display = 'none';
    const summariesContainer = document.getElementById('step-summaries-container');
    if (summariesContainer) summariesContainer.style.display = 'none';
    // Populate list: step name + Edit button. Use 1-based index for display (same fix as flows2) so single step shows "1" not stored step_number.
    existingList.innerHTML = '';
    const sortedSteps = [...createdSteps].sort((a, b) => (a.step_number || 0) - (b.step_number || 0));
    const spaExisting = document.body && (document.body.getAttribute('data-page') === 'process-flow-spa' || document.body.getAttribute('data-page') === 'process-flow-wizard');
    sortedSteps.forEach((step, index) => {
      const displayNumber = index + 1;
      const row = document.createElement('div');
      if (spaExisting) {
        row.style.cssText =
          'display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 0; background: transparent; border: none; border-radius: 0;' +
          (index > 0 ? 'border-top: 1px solid var(--border-default, #e5e7eb);' : '');
      } else {
        row.style.cssText = 'display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; background: var(--bg-card, #ffffff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md);';
      }
      const left = document.createElement('div');
      left.style.cssText = 'display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0;';
      const stepNum = document.createElement('span');
      stepNum.style.cssText = 'width: 28px; height: 28px; border-radius: 50%; background: var(--primary, #3b82f6); color: white; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 13px; flex-shrink: 0;';
      stepNum.textContent = displayNumber;
      const name = document.createElement('span');
      name.style.cssText = 'font-size: 15px; font-weight: 600; color: var(--text-primary);';
      name.textContent = step.name || 'Unnamed step';
      left.appendChild(stepNum);
      left.appendChild(name);
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'btn btn-secondary btn-sm';
      editBtn.textContent = 'Edit';
      editBtn.onclick = () => window.startEditingStep(step.id);
      row.appendChild(left);
      row.appendChild(editBtn);
      existingList.appendChild(row);
    });
    existingView.style.display = 'block';
  }
    return showExistingStepsView;
  }

  window.ProcessModalExistingSteps = Object.freeze({ create: createExistingStepsRenderer });
})();
