(function() {
  'use strict';

  function createApplyEditStepFromUrl(helpers) {
    async function applyEditStepFromUrl(stepId, isCurrent) {
      const api = helpers.getCoreApi();
      const current = typeof isCurrent === 'function' ? isCurrent : function() { return true; };
      if (!current()) return;
      const step = helpers.getCreatedSteps().find(function (s) {
        return s && String(s.id) === String(stepId);
      });
      if (!step) {
        console.warn('applyEditStepFromUrl: step not in createdSteps', stepId);
        return;
      }
      const urlPid = new URLSearchParams(window.location.search || '').get('id');
      let workflowProcessName = '';
      if (urlPid && api && api.getProcess) {
        try {
          const proc = await api.getProcess(urlPid);
          if (!current()) return;
          if (proc && proc.name != null) workflowProcessName = String(proc.name).trim();
        } catch (e) {}
      }

      helpers.setEditingStepId(step.id);
      helpers.resetForm(true);

      const payload = helpers.buildSessionPayload(step, { processId: urlPid, workflowProcessName });
      try {
        sessionStorage.setItem(helpers.getProcessFlowSpaStorageKey(), JSON.stringify(payload));
      } catch (e) {
        console.warn('applyEditStepFromUrl session seed failed', e);
      }

      if (typeof window.restoreSpaWizardState === 'function') {
        await window.restoreSpaWizardState({ isCurrent: current });
      }
      if (!current()) return;

      const indicators = document.getElementById('create-process-step-indicators');
      if (indicators) indicators.style.display = 'flex';
      const slug = document.body.getAttribute('data-flow-wizard-page');
      const slugToStep = { 'step-name': 1, inputs: 2, outputs: 3, 'evidence-and-prompts': 4 };
      if (slug && slugToStep[slug]) {
        helpers.setCurrentStep(slugToStep[slug]);
      }
      helpers.updateStepDisplay();
    }
    return applyEditStepFromUrl;
  }

  window.ProcessModalDeepLinkEdit = Object.freeze({ create: createApplyEditStepFromUrl });
})();
