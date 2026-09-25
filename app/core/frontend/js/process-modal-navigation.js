(function() {
  'use strict';

  function createStepDisplayUpdater(helpers) {
    function updateStepDisplay() {
      const currentStep = helpers.getCurrentStep();
      const isRestoringDraft = helpers.isRestoringDraft();
      const editingStepId = helpers.getEditingStepId();
      console.log('updateStepDisplay called, currentStep:', currentStep, 'isRestoringDraft:', isRestoringDraft);
      // When showing the step flow, hide the existing-steps list view and show indicators
      const existingView = document.getElementById('existing-steps-list-view');
      const indicators = document.getElementById('create-process-step-indicators');
      if (existingView) existingView.style.display = 'none';
      if (indicators) indicators.style.display = 'flex';
    
      // If we're restoring a draft and currentStep is 1, but we should be on a different step,
      // don't update (something else will set it correctly)
      // BUT: if isRestoringDraft is true and currentStep is already set to something other than 1, allow it
      if (isRestoringDraft && currentStep === 1) {
        console.warn('updateStepDisplay called with currentStep=1 during draft restoration, skipping to prevent reset');
        return;
      }
    
      // Update step indicators
      for (let i = 1; i <= helpers.totalSteps; i++) {
        const indicator = document.querySelector(`.step-indicator[data-step="${i}"]`);
        if (indicator) {
          if (i === currentStep) {
            indicator.style.background = 'var(--primary, #3b82f6)';
            indicator.style.color = 'white';
            indicator.style.border = 'none';
          } else if (i < currentStep) {
            indicator.style.background = 'var(--success, #10b981)';
            indicator.style.color = 'white';
            indicator.style.border = 'none';
          } else {
            indicator.style.background = 'var(--bg-secondary, #f3f4f6)';
            indicator.style.color = 'var(--text-secondary)';
            indicator.style.border = '2px solid var(--border-default, #e5e7eb)';
          }
        }
      }
    
      // Show/hide steps - use !important to override inline styles
      for (let i = 1; i <= helpers.totalSteps; i++) {
        const stepDiv = document.getElementById(`create-process-step-${i}`);
        if (stepDiv) {
          if (i === currentStep) {
            stepDiv.style.display = 'block';
            console.log(`Showing step ${i}`);
          } else {
            stepDiv.style.display = 'none';
            console.log(`Hiding step ${i}`);
          }
        } else {
          console.warn(`Step div not found: create-process-step-${i}`);
        }
      }
    
      // On inputs step (2): show "Outputs from previous steps" tab only if there is at least one previous step; populate lists
      if (currentStep === 2) {
        if (typeof window.updatePreviousOutputTabVisibility === 'function') window.updatePreviousOutputTabVisibility();
        if (typeof window.renderInventoryItemCards === 'function') window.renderInventoryItemCards();
        if (typeof window.renderPreviousOutputsList === 'function') window.renderPreviousOutputsList();
        helpers.updateInputButtonsText();
      }
    
      // On outputs step (3): if no outputs yet, add one so the first output is ready and expanded
      if (currentStep === 3) {
        const outputsList = document.getElementById('guided-outputs-list');
        if (outputsList && outputsList.children.length === 0 && typeof window.addGuidedOutput === 'function') {
          window.addGuidedOutput();
        }
        helpers.updateOutputButtonText();
      }

      // On step 4: show attached docs when editing a step; load list and enable delete. Disable inline fields when file is selected.
      const attachedDocsSection = document.getElementById('guided-step-attached-docs-section');
      const attachedDocsList = document.getElementById('guided-step-docs-list');
      if (attachedDocsSection && attachedDocsList) {
        if (editingStepId) {
          attachedDocsSection.style.display = 'block';
          helpers.loadAttachedStepDocs(editingStepId);
        } else {
          attachedDocsSection.style.display = 'none';
          attachedDocsList.innerHTML = '';
        }
      }
      if (currentStep === 4) {
        helpers.ensureDocFileListener();
        helpers.syncDocInlineDisabledState();
        helpers.syncStep4ModeSegments();
        helpers.updateStep4SummaryBar();
      }
    }



    return updateStepDisplay;
  }

  window.ProcessModalNavigation = Object.freeze({ createStepDisplayUpdater });
})();
