(function() {
  'use strict';

  function createSummarySessionHelpers(helpers) {
    function resolveCurrentStepForSummary(sortedSteps) {
      const session = helpers.loadWizardSessionMergeBase();
      const sorted = Array.isArray(sortedSteps) ? sortedSteps : [];
      if (!helpers.getEditingStepId() && helpers.wizardSessionHasDraftStepData(session)) {
        const vs = helpers.buildVirtualSummaryStepFromWizardSession(session);
        if (vs) {
          const displayNumber = sorted.length + 1;
          return { step: vs, displayNumber: displayNumber, isFinalStep: true };
        }
      }
      if (sorted.length === 0) {
        return { step: null, displayNumber: 0, isFinalStep: false };
      }
      let idx = sorted.length - 1;
      if (helpers.getEditingStepId()) {
        const found = sorted.findIndex(function (s) {
          return String(s.id) === String(helpers.getEditingStepId());
        });
        if (found >= 0) idx = found;
      }
      const step = sorted[idx];
      return {
        step,
        displayNumber: idx + 1,
        isFinalStep: idx === sorted.length - 1
      };
    }

    /** Session persist stores full I/O on createdSteps[] — more reliable than top-level inputs/outputs alone. */
    function findSessionDraftStepForSummaryStep(session, step) {
      if (!session || !step || step.id == null) return null;
      const list = session.createdSteps;
      if (!Array.isArray(list) || list.length === 0) return null;
      const hit = list.find(function (s) {
        return s && s.id != null && String(s.id) === String(step.id);
      });
      return hit || null;
    }

    function sessionTopLevelIoAppliesToStep(step, sortedSteps) {
      const session = helpers.loadWizardSessionMergeBase();
      if (!session || !step) return false;
      if (String(step.id) === '__pending__') return true;
      if (!step.id) return false;
      // Wizard draft lives in session.inputs / session.outputs for ONE step. When editing step 1..N−1,
      // only session.editingStepId / the active editor ID identifies it — the old "last step only" fallback was
      // wrong and caused enrichStepForSummaryFromSession to skip merging I/O for non-final steps.
      if (helpers.getEditingStepId() != null && helpers.getEditingStepId() !== '') {
        if (String(helpers.getEditingStepId()) === String(step.id)) return true;
      }
      if (session.editingStepId != null && session.editingStepId !== '') {
        return String(session.editingStepId) === String(step.id);
      }
      const sorted = [...sortedSteps].sort(function (a, b) {
        return (a.step_number || 0) - (b.step_number || 0);
      });
      const last = sorted[sorted.length - 1];
      return !!(last && String(last.id) === String(step.id));
    }


    /**
     * Summary route has no wizard DOM; GET /process may lag. Prefer session.createdSteps (full step
     * snapshot from persist) then top-level session inputs/outputs from merge-serialize.
     */
    function enrichStepForSummaryFromSession(step, sortedSteps) {
      if (!step) return step;
      const session = helpers.loadWizardSessionMergeBase();
      if (!session) return step;

      const next = { ...step };
      const draft = findSessionDraftStepForSummaryStep(session, step);

      const inputsApi = Array.isArray(step.inputs) ? step.inputs : [];
      let inputsNamed = inputsApi.filter(function (i) {
        return i && helpers.summaryInputDisplayName(i);
      });
      const outputsApi = Array.isArray(step.outputs) ? step.outputs : [];
      let outputsNamed = outputsApi.filter(function (o) {
        return o && helpers.summaryOutputDisplayName(o);
      });
      const promptsApi = Array.isArray(step.execution_prompts) ? step.execution_prompts : [];
      let promptsLabeled = promptsApi.filter(function (p) {
        return p && (p.label || '').trim();
      });

      if (draft) {
        const di = Array.isArray(draft.inputs)
          ? draft.inputs.filter(function (i) {
              return i && helpers.summaryInputDisplayName(i);
            })
          : [];
        const dout = Array.isArray(draft.outputs)
          ? draft.outputs.filter(function (o) {
              return o && helpers.summaryOutputDisplayName(o);
            })
          : [];
        const dp = Array.isArray(draft.execution_prompts)
          ? draft.execution_prompts.filter(function (p) {
              return p && (p.label || '').trim();
            })
          : [];
        if (inputsNamed.length === 0 && di.length > 0) {
          next.inputs = JSON.parse(JSON.stringify(di));
          inputsNamed = next.inputs;
        }
        if (outputsNamed.length === 0 && dout.length > 0) {
          next.outputs = JSON.parse(JSON.stringify(dout));
          outputsNamed = next.outputs.filter(function (o) {
            return o && helpers.summaryOutputDisplayName(o);
          });
        }
        if (promptsLabeled.length === 0 && dp.length > 0) {
          next.execution_prompts = JSON.parse(JSON.stringify(dp));
          promptsLabeled = next.execution_prompts;
        }
        if (next.batch_number_mode == null && draft.batch_number_mode != null) {
          next.batch_number_mode = draft.batch_number_mode;
        }
        if (next.evidence_mode == null && draft.evidence_mode != null) {
          next.evidence_mode = draft.evidence_mode;
        }
        if (!(next.documentation_summary || '').trim() && (draft.documentation_summary || '').trim()) {
          next.documentation_summary = draft.documentation_summary;
        }
      }

      if (!sessionTopLevelIoAppliesToStep(step, sortedSteps)) {
        if (
          !(next.documentation_summary || '').trim() &&
          session.editingStepId != null &&
          String(session.editingStepId) === String(step.id)
        ) {
          const du = session.docFileUpload;
          if (du && du.base64) {
            next.documentation_summary = 'SOP file attached (pending upload)';
          } else {
            const dt = (session.docInlineTitle || '').trim();
            const dc = (session.docInlineContent || '').trim();
            if (dt && dc) {
              next.documentation_summary = 'Instructions: ' + dt;
            }
          }
        }
        return next;
      }

      // When editing a DB-backed step, the wizard session is the source of truth for ALL editable fields
      // on the current step (including deletions), not a "fill if empty" helper.
      if (helpers.wizardSessionHasDraftStepData(session)) {
        if (Object.prototype.hasOwnProperty.call(session, 'stepName')) {
          const sn = (session.stepName || '').toString();
          if (sn.trim() !== '' && sn !== (next.name || '')) {
            next.name = sn;
          }
        }
        if (Object.prototype.hasOwnProperty.call(session, 'stepDescription')) {
          next.description = (session.stepDescription || '').toString();
        }

        next.inputs = helpers.mapSessionInputsToSummaryRows(session.inputs || []);
        next.outputs = JSON.parse(
          JSON.stringify(
            (session.outputs || []).filter(function (o) {
              return o && helpers.summaryOutputDisplayName(o);
            })
          )
        );
        next.execution_prompts = JSON.parse(
          JSON.stringify(helpers.buildExecutionPromptsForApiFromSession(session))
        );
        if (session.batchNumberMode != null) next.batch_number_mode = session.batchNumberMode;
        if (session.evidenceMode != null) next.evidence_mode = session.evidenceMode;

        // Docs are edited on step 4; reflect pending attachments/inline edits on summary during edit.
        const du = session.docFileUpload;
        if (du && du.base64) {
          next.documentation_summary = 'SOP file attached (pending upload)';
        } else {
          const dt = (session.docInlineTitle || '').trim();
          const dc = (session.docInlineContent || '').trim();
          if (dt && dc) {
            next.documentation_summary = 'Instructions: ' + dt;
          } else if ((next.documentation_summary || '').trim() === '') {
            next.documentation_summary = next.documentation_summary;
          }
        }
      }

      return next;
    }
    return { resolveCurrentStepForSummary, enrichStepForSummaryFromSession };
  }

  window.ProcessModalSummarySession = Object.freeze({
    create: createSummarySessionHelpers
  });
})();
