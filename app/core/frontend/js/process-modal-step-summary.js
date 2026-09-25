(function() {
  'use strict';

  function createStepSummaryRenderer(helpers) {
    async function updateStepSummaries() {
      let createdSteps = helpers.getCreatedSteps();
      const summariesList = document.getElementById('step-summaries-list');
      const summariesContainer = document.getElementById('step-summaries-container');
      if (!summariesList || !summariesContainer) return;

      const sessionSnap = helpers.loadWizardSessionMergeBase();
      const hasPendingSessionStep = helpers.wizardSessionHasDraftStepData(sessionSnap);

      if (createdSteps.length === 0 && !hasPendingSessionStep) {
        summariesContainer.style.display = 'none';
        const panel = document.getElementById('flow-compliance-panel');
        if (panel) {
          panel.style.display = 'none';
          panel.innerHTML = '';
        }
        const summarySticky = document.getElementById('flow-wizard-summary-sticky');
        if (summarySticky) summarySticky.style.display = 'none';
        const heading = document.getElementById('step-summaries-heading');
        if (heading) {
          heading.textContent = 'Created Steps';
          heading.style.marginTop = '0';
        }
        return;
      }
    
      summariesContainer.style.display = 'block';
      summariesList.innerHTML = '';

      const sortedSteps = helpers.sortStepsForDisplay(createdSteps);
      await window.ProcessModalSummary.renderCompliancePanel(sortedSteps, {
        isProcessFlowSummaryPage: helpers.isProcessFlowSummaryPage,
        resolveCurrentStepForSummary: helpers.resolveCurrentStepForSummary,
        enrichStepForSummaryFromSession: helpers.enrichStepForSummaryFromSession
      });
      if (helpers.isProcessFlowSummaryPage()) {
        summariesList.style.display = 'none';
        const summarySticky = document.getElementById('flow-wizard-summary-sticky');
        if (summarySticky) summarySticky.style.display = createdSteps.length > 0 || hasPendingSessionStep ? '' : 'none';
        return;
      }
      summariesList.style.display = '';

      const spaPage = document.body && (document.body.getAttribute('data-page') === 'process-flow-spa' || document.body.getAttribute('data-page') === 'process-flow-wizard');
      // Drag/drop reorder state (HTML5 DnD)
      let dragStepId = null;

      function onDragStart(e) {
        const card = e.currentTarget;
        dragStepId = card && card.dataset ? card.dataset.stepId : null;
        try {
          e.dataTransfer.effectAllowed = 'move';
          e.dataTransfer.setData('text/plain', dragStepId || '');
        } catch (err) {}
        card.classList.add('step-summary-dragging');
      }

      function onDragEnd(e) {
        const card = e.currentTarget;
        if (card) card.classList.remove('step-summary-dragging');
        dragStepId = null;
      }

      async function onDropOnCard(e) {
        e.preventDefault();
        const targetCard = e.currentTarget;
        const targetId = targetCard && targetCard.dataset ? targetCard.dataset.stepId : null;
        const srcId = dragStepId || (function() { try { return e.dataTransfer.getData('text/plain'); } catch (err) { return null; } })();
        if (!srcId || !targetId || srcId === targetId) return;

        const srcIdx = createdSteps.findIndex(function(s) { return s && String(s.id) === String(srcId); });
        const dstIdx = createdSteps.findIndex(function(s) { return s && String(s.id) === String(targetId); });
        if (srcIdx < 0 || dstIdx < 0) return;

        const moving = createdSteps[srcIdx];
        createdSteps.splice(srcIdx, 1);
        createdSteps.splice(dstIdx, 0, moving);

        // Server will normalize positions; we only persist the new order.
        createdSteps = [...createdSteps].map(function(s) { return { ...s }; });
        helpers.setCreatedSteps(createdSteps);
        if (typeof window.persistSpaWizardState === 'function') window.persistSpaWizardState();
        await helpers.persistStepOrderIfPossible();
        await helpers.updateStepSummaries();
      }

      function onDragOver(e) {
        e.preventDefault();
        try { e.dataTransfer.dropEffect = 'move'; } catch (err) {}
      }

      sortedSteps.forEach((step, index) => {
        const displayNumber = index + 1;
        const stepId = `step-summary-${step.id || index}`;
        const summaryCard = document.createElement('div');
        summaryCard.id = stepId;
        summaryCard.dataset.expanded = 'false';
        if (step && step.id) summaryCard.dataset.stepId = step.id;
        // Enable drag/drop reorder for persisted steps (have IDs).
        if (step && step.id) {
          summaryCard.setAttribute('draggable', 'true');
          summaryCard.addEventListener('dragstart', onDragStart);
          summaryCard.addEventListener('dragend', onDragEnd);
          summaryCard.addEventListener('dragover', onDragOver);
          summaryCard.addEventListener('drop', onDropOnCard);
        }
        if (spaPage) {
          summaryCard.style.cssText =
            'padding: 14px 0; border: none; border-radius: 0; background: transparent; overflow: hidden;' +
            (index > 0 ? 'border-top: 1px solid var(--border-default, #e5e7eb);' : '');
        } else {
          summaryCard.style.cssText = 'background: var(--bg-card, #ffffff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md); padding: 16px; overflow: hidden;';
        }
      
        // Header (clickable to expand/collapse)
        const stepHeader = document.createElement('div');
        stepHeader.style.cssText = 'display: flex; align-items: center; gap: 12px; cursor: pointer;';
        stepHeader.onclick = () => window.ProcessModalStepSummaryUi.toggleStepSummary(stepId);

        // Drag handle hint (clickable header still works; drag anywhere on card).
        if (step && step.id) {
          const dragHint = document.createElement('div');
          dragHint.setAttribute('aria-hidden', 'true');
          dragHint.style.cssText = 'color: var(--text-tertiary, #9ca3af); font-size: 16px; line-height: 1; user-select: none;';
          dragHint.textContent = '⋮⋮';
          stepHeader.appendChild(dragHint);
        }
      
        const expandIcon = document.createElement('svg');
        expandIcon.className = 'step-summary-expand-icon';
        expandIcon.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        expandIcon.setAttribute('width', '16');
        expandIcon.setAttribute('height', '16');
        expandIcon.setAttribute('viewBox', '0 0 24 24');
        expandIcon.setAttribute('fill', 'none');
        expandIcon.setAttribute('stroke', 'currentColor');
        expandIcon.setAttribute('stroke-width', '2');
        expandIcon.setAttribute('stroke-linecap', 'round');
        expandIcon.setAttribute('stroke-linejoin', 'round');
        expandIcon.style.cssText = 'transition: transform 0.2s; transform: rotate(0deg); color: var(--text-tertiary, #9ca3af); flex-shrink: 0;';
        expandIcon.innerHTML = '<polyline points="6 9 12 15 18 9"></polyline>';
        stepHeader.appendChild(expandIcon);
      
        const stepNumber = document.createElement('div');
        stepNumber.style.cssText = 'width: 32px; height: 32px; border-radius: 50%; background: var(--primary, #3b82f6); color: white; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 14px; flex-shrink: 0;';
        stepNumber.textContent = displayNumber;
        stepHeader.appendChild(stepNumber);
      
        const stepInfo = document.createElement('div');
        stepInfo.style.cssText = 'flex: 1;';
      
        const stepName = document.createElement('h4');
        stepName.style.cssText = 'font-size: 16px; font-weight: 600; color: var(--text-primary); margin: 0 0 4px 0;';
        stepName.textContent = step.name;
        stepInfo.appendChild(stepName);
      
        if (step.description) {
          const stepDesc = document.createElement('p');
          stepDesc.style.cssText = 'font-size: 13px; color: var(--text-secondary); margin: 0;';
          stepDesc.textContent = step.description;
          stepInfo.appendChild(stepDesc);
        }
      
        stepHeader.appendChild(stepInfo);
        summaryCard.appendChild(stepHeader);
      
        // Collapsed summary (always visible)
        const collapsedSummary = document.createElement('div');
        collapsedSummary.className = 'step-summary-collapsed';
        collapsedSummary.style.cssText = 'margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-light, #e5e7eb); font-size: 12px; color: var(--text-secondary);';
      
        const details = [];
        if (step.inputs && step.inputs.length > 0) {
          details.push(`${step.inputs.length} input${step.inputs.length > 1 ? 's' : ''}`);
        }
        if (step.outputs && step.outputs.length > 0) {
          details.push(`${step.outputs.length} output${step.outputs.length > 1 ? 's' : ''}`);
        }
        if (step.execution_prompts && step.execution_prompts.length > 0) {
          details.push(`${step.execution_prompts.length} prompt${step.execution_prompts.length > 1 ? 's' : ''}`);
        }
      
        if (details.length > 0) {
          collapsedSummary.textContent = details.join(' • ');
          summaryCard.appendChild(collapsedSummary);
        }
      
        // Expanded details (hidden by default)
        const expandedDetails = document.createElement('div');
        expandedDetails.className = 'step-summary-expanded';
        expandedDetails.style.cssText = 'margin-top: 16px; padding-top: 16px; border-top: 2px solid var(--border-default, #e5e7eb); display: none;';
      
        // Inputs
        if (step.inputs && step.inputs.length > 0) {
          const inputsSection = document.createElement('div');
          inputsSection.style.cssText = 'margin-bottom: 16px;';
          const inputsTitle = document.createElement('h5');
          inputsTitle.style.cssText = 'font-size: 13px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0;';
          inputsTitle.textContent = 'Inputs:';
          inputsSection.appendChild(inputsTitle);
        
          step.inputs.forEach(input => {
            const inputItem = document.createElement('div');
            inputItem.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); margin-bottom: 4px; font-size: 12px; color: var(--text-secondary);';
            const quantity = input.quantity !== null && input.quantity !== undefined ? input.quantity : '';
            const unit = input.unit || '';
            inputItem.textContent = `• ${input.name}${quantity ? ` (${quantity} ${unit})` : unit ? ` (${unit})` : ''}`;
            inputsSection.appendChild(inputItem);
          });
          expandedDetails.appendChild(inputsSection);
        }
      
        // Outputs
        if (step.outputs && step.outputs.length > 0) {
          const outputsSection = document.createElement('div');
          outputsSection.style.cssText = 'margin-bottom: 16px;';
          const outputsTitle = document.createElement('h5');
          outputsTitle.style.cssText = 'font-size: 13px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0;';
          outputsTitle.textContent = 'Outputs:';
          outputsSection.appendChild(outputsTitle);
        
          step.outputs.forEach(output => {
            const outputItem = document.createElement('div');
            outputItem.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); margin-bottom: 4px; font-size: 12px; color: var(--text-secondary);';
            const quantity = output.quantity !== null && output.quantity !== undefined ? output.quantity : '';
            const unit = output.unit || '';
            outputItem.textContent = `• ${output.name}${quantity ? ` (${quantity} ${unit})` : unit ? ` (${unit})` : ''}`;
            outputsSection.appendChild(outputItem);
          });
          expandedDetails.appendChild(outputsSection);
        }
      
        // Prompts
        if (step.execution_prompts && step.execution_prompts.length > 0) {
          const promptsSection = document.createElement('div');
          const promptsTitle = document.createElement('h5');
          promptsTitle.style.cssText = 'font-size: 13px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0;';
          promptsTitle.textContent = 'Prompts:';
          promptsSection.appendChild(promptsTitle);
        
          step.execution_prompts.forEach(prompt => {
            const promptItem = document.createElement('div');
            promptItem.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); margin-bottom: 4px; font-size: 12px; color: var(--text-secondary);';
            const unit = prompt.unit ? ` (${prompt.unit})` : '';
            const required = prompt.required !== false ? 'Required' : 'Optional';
            promptItem.textContent = `• ${prompt.label} - ${prompt.type}${unit} - ${required}`;
            promptsSection.appendChild(promptItem);
          });
          expandedDetails.appendChild(promptsSection);
        }

        if (step.documentation_summary) {
          const docSection = document.createElement('div');
          docSection.style.cssText = 'margin-bottom: 16px;';
          const docTitle = document.createElement('h5');
          docTitle.style.cssText = 'font-size: 13px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0;';
          docTitle.textContent = 'Documentation:';
          docSection.appendChild(docTitle);
          const docItem = document.createElement('div');
          docItem.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); font-size: 12px; color: var(--text-secondary);';
          docItem.textContent = step.documentation_summary;
          docSection.appendChild(docItem);
          expandedDetails.appendChild(docSection);
        }

        if (step.batch_number_mode || step.evidence_mode) {
          const traceSection = document.createElement('div');
          traceSection.style.cssText = 'margin-bottom: 16px;';
          const traceTitle = document.createElement('h5');
          traceTitle.style.cssText = 'font-size: 13px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0;';
          traceTitle.textContent = 'Traceability:';
          traceSection.appendChild(traceTitle);
          if (step.batch_number_mode) {
            const row = document.createElement('div');
            row.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); margin-bottom: 4px; font-size: 12px; color: var(--text-secondary);';
            row.textContent = '• Batch / run ID: ' + helpers.formatStep4ModeLabel(step.batch_number_mode);
            traceSection.appendChild(row);
          }
          if (step.evidence_mode) {
            const row2 = document.createElement('div');
            row2.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); margin-bottom: 4px; font-size: 12px; color: var(--text-secondary);';
            row2.textContent = '• Evidence capture: ' + helpers.formatStep4ModeLabel(step.evidence_mode);
            traceSection.appendChild(row2);
          }
          expandedDetails.appendChild(traceSection);
        }

        summaryCard.appendChild(expandedDetails);
        summariesList.appendChild(summaryCard);
      });
    }
    return { updateStepSummaries };
  }

  window.ProcessModalStepSummary = Object.freeze({ create: createStepSummaryRenderer });
})();
