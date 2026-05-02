    async function loadExecutions() {
      if (!processId) return;
      
      try {
        const executionsData = await CoreAPI.getExecutions(processId);
        const executions = executionsData.executions || [];
        
        // Update badge
        document.getElementById('executions-badge').textContent = executions.length;
        
        // Separate active and completed
        const active = executions.filter(e => e.status === 'in_progress' || e.status === 'IN_PROGRESS');
        const completed = executions.filter(e => e.status === 'completed' || e.status === 'COMPLETED');
        
        // Update stats
        document.getElementById('process-active-count').textContent = active.length;
        document.getElementById('process-completed-count').textContent = completed.length;
        
        // Render executions
        await renderExecutions(active, completed);

        // Restore collapse/expand state after first render (so counts are already updated).
        restoreBatchesPanelCollapseState();
        
      } catch (error) {
        console.error('Failed to load executions:', error);
        showNotification('error', 'Failed to Load Executions', error.message || 'Failed to load executions');
      }
    }

    function restoreBatchesPanelCollapseState() {
      var activeDetails = document.getElementById('flows2-batches-active-details');
      var completedDetails = document.getElementById('flows2-batches-completed-details');
      if (!activeDetails || !completedDetails) return;

      function safeGet(k) {
        try { return window.localStorage ? window.localStorage.getItem(k) : null; } catch (e) { return null; }
      }
      function safeSet(k, v) {
        try { if (window.localStorage) window.localStorage.setItem(k, v); } catch (e) {}
      }

      var a = safeGet('flows2:batches:active:open');
      var c = safeGet('flows2:batches:completed:open');

      // Defaults: active open, completed collapsed.
      if (a === '0') activeDetails.open = false;
      if (a === '1') activeDetails.open = true;
      if (c === '1') completedDetails.open = true;
      if (c === '0' || c == null) completedDetails.open = false;

      if (!activeDetails._collapseBound) {
        activeDetails.addEventListener('toggle', function () {
          safeSet('flows2:batches:active:open', activeDetails.open ? '1' : '0');
        });
        activeDetails._collapseBound = true;
      }
      if (!completedDetails._collapseBound) {
        completedDetails.addEventListener('toggle', function () {
          safeSet('flows2:batches:completed:open', completedDetails.open ? '1' : '0');
        });
        completedDetails._collapseBound = true;
      }
    }
    function flows2BuildExecutionEvidenceSectionDOM(evidenceList) {
      if (!evidenceList || !evidenceList.length) return null;
      const shown = evidenceList.slice(0, FLOWS2_MAX_EVIDENCE_ITEMS);
      const section = document.createElement('div');
      section.className = 'execution-evidence-section';
      section.style.cssText =
        'margin-bottom: 12px; padding: 12px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); border: 1px solid var(--border-light, #e5e7eb);';
      const title = document.createElement('div');
      title.style.cssText =
        'font-size: 12px; color: var(--text-secondary, #6b7280); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;';
      title.textContent = `Evidence (${evidenceList.length})`;
      section.appendChild(title);
      const list = document.createElement('div');
      list.style.cssText = 'display: flex; flex-direction: column; gap: 6px;';
      shown.forEach((ev) => {
        const viewUrl =
          typeof CoreAPI !== 'undefined' && CoreAPI.getEvidenceViewUrl ? CoreAPI.getEvidenceViewUrl(ev.id) : '#';
        const downloadUrl =
          typeof CoreAPI !== 'undefined' && CoreAPI.getEvidenceDownloadUrl ? CoreAPI.getEvidenceDownloadUrl(ev.id) : '#';
        const row = document.createElement('div');
        row.style.cssText =
          'display: flex; justify-content: space-between; align-items: center; padding: 8px 10px; background: var(--bg-card, #fff); border-radius: 6px; border: 1px solid var(--border-light, #e5e7eb);';
        const span = document.createElement('span');
        span.style.cssText = 'font-size: 13px; color: var(--text-primary, #111827);';
        span.textContent = ev.file_name || 'Evidence file';
        const links = document.createElement('div');
        links.style.cssText = 'display: flex; gap: 8px;';
        const aView = document.createElement('a');
        aView.href = viewUrl;
        aView.target = '_blank';
        aView.rel = 'noopener';
        aView.style.cssText = 'font-size: 12px; color: var(--primary, #3b82f6); text-decoration: none; font-weight: 500;';
        aView.textContent = 'View';
        const aDl = document.createElement('a');
        aDl.href = downloadUrl;
        aDl.target = '_blank';
        aDl.rel = 'noopener';
        aDl.style.cssText = 'font-size: 12px; color: var(--primary, #3b82f6); text-decoration: none; font-weight: 500;';
        aDl.textContent = 'Download';
        links.appendChild(aView);
        links.appendChild(aDl);
        row.appendChild(span);
        row.appendChild(links);
        list.appendChild(row);
      });
      section.appendChild(list);
      return section;
    }

    /** One completed execution step row (inputs / outputs / metadata panes). */
    function flows2BuildCompletedExecutionStepRowDOM(es) {
      const completedDate = es.completed_at
        ? new Date(es.completed_at).toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
          })
        : 'Unknown';
      let completedByRaw = es.execution_data?.completed_by || es.execution_data?.completed_by_email || 'Unknown';
      const completedBy =
        typeof completedByRaw === 'object' && completedByRaw !== null
          ? flows2ValueForHtml(completedByRaw)
          : String(completedByRaw);
      const stepName = es.step_name || `Step ${es.step_number}`;
      const actualInputs = es.actual_inputs || [];
      const actualOutputs = es.actual_outputs || [];
      const stepInputs = es.step_inputs || [];
      const stepOutputs = es.step_outputs || [];
      const displayInputs = actualInputs.length > 0 ? actualInputs : stepInputs;
      const displayOutputs = actualOutputs.length > 0 ? actualOutputs : stepOutputs;

      const executionData = es.execution_data || {};
      const executionMetadata = [];
      const internalFields = ['completed_by', 'completed_by_email', 'completed_by_user_id', 'completed_at'];
      flows2SafeKeys(executionData)
        .filter((key) => !internalFields.includes(key))
        .slice(0, FLOWS2_MAX_EXECUTION_METADATA_KEYS)
        .forEach((key) => {
          if (executionData[key] !== null && executionData[key] !== undefined && executionData[key] !== '') {
            executionMetadata.push({ label: key, value: executionData[key] });
          }
        });

      const executionStepId =
        es.id || `step-${es.step_id}-${es.step_number}-${Math.random().toString(36).substr(2, 9)}`;
      const inputsPaneId = `inputs-${executionStepId}`;
      const outputsPaneId = `outputs-${executionStepId}`;
      const metadataPaneId = `metadata-${executionStepId}`;

      const outer = document.createElement('div');
      outer.style.cssText = 'padding: 12px 0; border-bottom: 1px solid var(--border-light, #e5e7eb);';
      const col = document.createElement('div');
      col.style.cssText = 'display: flex; flex-direction: column;';
      const headBlock = document.createElement('div');
      headBlock.style.marginBottom = '8px';
      const nameEl = document.createElement('div');
      nameEl.style.cssText = 'font-size: 13px; color: var(--text-primary, #111827); font-weight: 500;';
      nameEl.textContent = stepName;
      const subEl = document.createElement('div');
      subEl.style.cssText = 'font-size: 12px; color: var(--text-secondary, #6b7280); margin-top: 2px;';
      subEl.textContent = `Completed: ${completedDate} by ${completedBy}`;
      headBlock.appendChild(nameEl);
      headBlock.appendChild(subEl);
      col.appendChild(headBlock);

      const ioRow = document.createElement('div');
      ioRow.style.cssText = 'margin-top: 12px; display: flex; gap: 0;';

      if (displayInputs.length > 0) {
        const pane = document.createElement('div');
        pane.style.cssText =
          'flex: 1; background: var(--bg-secondary, #f9fafb); border: 1px solid var(--border-light, #e5e7eb); border-radius: 6px; margin-right: 8px; overflow: hidden;';
        const hdr = document.createElement('div');
        hdr.className = 'io-pane-header flows2-io-pane-hdr';
        hdr.setAttribute('data-io-pane-id', inputsPaneId);
        hdr.style.cssText =
          'display: flex; justify-content: space-between; align-items: center; padding: 10px; cursor: pointer; user-select: none;';
        const hLeft = document.createElement('div');
        hLeft.style.cssText =
          'font-size: 11px; color: var(--text-secondary, #6b7280); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;';
        hLeft.textContent = `Inputs (${displayInputs.length})`;
        const hToggle = document.createElement('div');
        hToggle.className = 'io-pane-toggle';
        hToggle.id = `${inputsPaneId}-toggle`;
        hToggle.style.cssText = 'transition: transform 0.2s; transform: rotate(0deg);';
        hToggle.appendChild(flows2SvgChevron14());
        hdr.appendChild(hLeft);
        hdr.appendChild(hToggle);
        const body = document.createElement('div');
        body.className = 'io-pane-content';
        body.id = inputsPaneId;
        body.style.cssText = 'display: none; padding: 0 10px 10px 10px;';
        displayInputs.slice(0, FLOWS2_MAX_IO_ROWS_PER_STEP).forEach((input) => {
          const inputName = input.name || 'Unknown';
          const inputQty = input.quantity !== null && input.quantity !== undefined ? input.quantity : '';
          const inputUnit = input.unit || '';
          const inventoryItemId = input.inventory_item_id || null;
          const row = document.createElement('div');
          row.style.cssText =
            'font-size: 12px; color: var(--text-primary, #111827); margin-top: 6px; padding: 4px 0; border-bottom: 1px solid var(--border-light, #e5e7eb);';
          const n = document.createElement('div');
          n.style.fontWeight = '500';
          n.textContent = inputName;
          row.appendChild(n);
          if (inputQty) {
            const q = document.createElement('div');
            q.style.cssText = 'font-size: 11px; color: var(--text-secondary, #6b7280); margin-top: 2px;';
            q.textContent = `${inputQty} ${inputUnit}`.trim();
            row.appendChild(q);
          }
          if (inventoryItemId) {
            const idRow = document.createElement('div');
            idRow.style.cssText = 'font-size: 10px; color: var(--text-tertiary, #9ca3af); margin-top: 2px;';
            idRow.textContent = `Inventory ID: ${inventoryItemId}`;
            row.appendChild(idRow);
          }
          body.appendChild(row);
        });
        pane.appendChild(hdr);
        pane.appendChild(body);
        ioRow.appendChild(pane);
      }

      if (displayOutputs.length > 0) {
        const pane = document.createElement('div');
        pane.style.cssText =
          'flex: 1; background: var(--bg-secondary, #f9fafb); border: 1px solid var(--border-light, #e5e7eb); border-radius: 6px; margin-left: 8px; overflow: hidden;';
        const hdr = document.createElement('div');
        hdr.className = 'io-pane-header flows2-io-pane-hdr';
        hdr.setAttribute('data-io-pane-id', outputsPaneId);
        hdr.style.cssText =
          'display: flex; justify-content: space-between; align-items: center; padding: 10px; cursor: pointer; user-select: none;';
        const hLeft = document.createElement('div');
        hLeft.style.cssText =
          'font-size: 11px; color: var(--text-secondary, #6b7280); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;';
        hLeft.textContent = `Outputs (${displayOutputs.length})`;
        const hToggle = document.createElement('div');
        hToggle.className = 'io-pane-toggle';
        hToggle.id = `${outputsPaneId}-toggle`;
        hToggle.style.cssText = 'transition: transform 0.2s; transform: rotate(0deg);';
        hToggle.appendChild(flows2SvgChevron14());
        hdr.appendChild(hLeft);
        hdr.appendChild(hToggle);
        const body = document.createElement('div');
        body.className = 'io-pane-content';
        body.id = outputsPaneId;
        body.style.cssText = 'display: none; padding: 0 10px 10px 10px;';
        displayOutputs.slice(0, FLOWS2_MAX_IO_ROWS_PER_STEP).forEach((output) => {
          const outputName = output.name || 'Unknown';
          const outputQty = output.quantity !== null && output.quantity !== undefined ? output.quantity : '';
          const outputUnit = output.unit || '';
          const row = document.createElement('div');
          row.style.cssText =
            'font-size: 12px; color: var(--text-primary, #111827); margin-top: 6px; padding: 4px 0; border-bottom: 1px solid var(--border-light, #e5e7eb);';
          const n = document.createElement('div');
          n.style.fontWeight = '500';
          n.textContent = outputName;
          row.appendChild(n);
          if (outputQty) {
            const q = document.createElement('div');
            q.style.cssText = 'font-size: 11px; color: var(--text-secondary, #6b7280); margin-top: 2px;';
            q.textContent = `${outputQty} ${outputUnit}`.trim();
            row.appendChild(q);
          }
          body.appendChild(row);
        });
        pane.appendChild(hdr);
        pane.appendChild(body);
        ioRow.appendChild(pane);
      }

      if (displayInputs.length > 0 || displayOutputs.length > 0) col.appendChild(ioRow);

      if (executionMetadata.length > 0) {
        const metaWrap = document.createElement('div');
        metaWrap.style.cssText =
          'flex: 1; background: var(--bg-secondary, #f9fafb); border: 1px solid var(--border-light, #e5e7eb); border-radius: 6px; margin-top: 8px; overflow: hidden;';
        const hdr = document.createElement('div');
        hdr.className = 'io-pane-header flows2-io-pane-hdr';
        hdr.setAttribute('data-io-pane-id', metadataPaneId);
        hdr.style.cssText =
          'display: flex; justify-content: space-between; align-items: center; padding: 10px; cursor: pointer; user-select: none;';
        const hLeft = document.createElement('div');
        hLeft.style.cssText =
          'font-size: 11px; color: var(--text-secondary, #6b7280); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;';
        hLeft.textContent = `Execution Metadata (${executionMetadata.length})`;
        const hToggle = document.createElement('div');
        hToggle.className = 'io-pane-toggle';
        hToggle.id = `${metadataPaneId}-toggle`;
        hToggle.style.cssText = 'transition: transform 0.2s; transform: rotate(0deg);';
        hToggle.appendChild(flows2SvgChevron14());
        hdr.appendChild(hLeft);
        hdr.appendChild(hToggle);
        const body = document.createElement('div');
        body.className = 'io-pane-content';
        body.id = metadataPaneId;
        body.style.cssText = 'display: none; padding: 0 10px 10px 10px;';
        executionMetadata.forEach((meta) => {
          const metaLabel = meta.label || 'Unknown';
          const metaValue = meta.value;
          const row = document.createElement('div');
          row.style.cssText =
            'font-size: 12px; color: var(--text-primary, #111827); margin-top: 6px; padding: 4px 0; border-bottom: 1px solid var(--border-light, #e5e7eb);';
          const lab = document.createElement('div');
          lab.style.fontWeight = '500';
          lab.textContent = metaLabel;
          const val = document.createElement('div');
          val.style.cssText = 'font-size: 11px; color: var(--text-secondary, #6b7280); margin-top: 2px;';
          val.textContent = flows2ValueForHtml(metaValue);
          row.appendChild(lab);
          row.appendChild(val);
          body.appendChild(row);
        });
        metaWrap.appendChild(hdr);
        metaWrap.appendChild(body);
        col.appendChild(metaWrap);
      }

      outer.appendChild(col);
      return outer;
    }

    function flows2BuildCompletedStepsSectionDOM(
      executionId,
      status,
      completedSteps,
      completedStepsCapped
    ) {
      const completedStepsSectionId = `completed-steps-${executionId}`;
      let sectionTitle =
        status === 'completed' ? `All Steps (${completedSteps.length})` : `Completed Steps (${completedSteps.length})`;
      if (completedSteps.length > FLOWS2_MAX_COMPLETED_EXECUTION_STEPS) {
        sectionTitle += ` — showing ${FLOWS2_MAX_COMPLETED_EXECUTION_STEPS}`;
      }
      const wrap = document.createElement('div');
      wrap.className = 'completed-steps-section';
      wrap.style.cssText = 'margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border-light);';
      const hdr = document.createElement('div');
      hdr.className = 'completed-steps-header flows2-completed-steps-toggle';
      hdr.setAttribute('data-completed-section-id', completedStepsSectionId);
      hdr.style.cssText =
        'display: flex; justify-content: space-between; align-items: center; cursor: pointer; user-select: none; margin-bottom: 12px;';
      const titleDiv = document.createElement('div');
      titleDiv.style.cssText = 'font-size: 12px; color: var(--text-secondary); font-weight: 500;';
      titleDiv.textContent = sectionTitle;
      const toggleWrap = document.createElement('div');
      toggleWrap.className = 'completed-steps-toggle';
      toggleWrap.id = `${completedStepsSectionId}-toggle`;
      toggleWrap.style.cssText = 'transition: transform 0.2s; transform: rotate(0deg);';
      toggleWrap.appendChild(flows2SvgChevron14());
      hdr.appendChild(titleDiv);
      hdr.appendChild(toggleWrap);
      const content = document.createElement('div');
      content.className = 'completed-steps-content';
      content.id = completedStepsSectionId;
      content.style.display = 'none';
      completedStepsCapped.forEach((es) => {
        content.appendChild(flows2BuildCompletedExecutionStepRowDOM(es));
      });
      wrap.appendChild(hdr);
      wrap.appendChild(content);
      return wrap;
    }

    function flows2BuildNextStepSectionDOM(stepDetails, compactHeaderMargin) {
      const wrap = document.createElement('div');
      wrap.className = 'next-step-section';
      wrap.style.cssText = compactHeaderMargin
        ? 'margin-top: 8px; margin-bottom: 8px;'
        : 'margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border-light);';
      const inner = document.createElement('div');
      inner.className = 'next-step-header';
      inner.style.cssText = 'display: flex; align-items: center; gap: 12px;';
      const icon = document.createElement('div');
      icon.className = 'next-step-icon';
      icon.style.flexShrink = '0';
      icon.appendChild(flows2SvgPlayTriangle16());
      const info = document.createElement('div');
      info.className = 'next-step-info';
      info.style.flex = '1';
      const lbl = document.createElement('div');
      lbl.className = 'next-step-label';
      lbl.style.cssText = 'font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      lbl.textContent = 'Next Step';
      const nm = document.createElement('div');
      nm.className = 'next-step-name';
      nm.style.cssText = 'font-weight: 500; color: var(--text-primary); font-size: 14px;';
      nm.textContent = stepDetails.name || 'Unknown';
      info.appendChild(lbl);
      info.appendChild(nm);
      if (stepDetails.description) {
        const desc = document.createElement('div');
        desc.className = 'next-step-description';
        desc.style.cssText = 'font-size: 12px; color: var(--text-secondary); margin-top: 2px;';
        desc.textContent = stepDetails.description;
        info.appendChild(desc);
      }
      inner.appendChild(icon);
      inner.appendChild(info);
      wrap.appendChild(inner);
      return wrap;
    }

    function flows2AppendExecutionProgressBlock(parent, progressColor, progressPct, opts) {
      const progWrap = document.createElement('div');
      progWrap.className = 'execution-progress';
      if (opts && opts.marginBottom != null) progWrap.style.marginBottom = opts.marginBottom;
      if (opts && opts.marginTop != null) progWrap.style.marginTop = opts.marginTop;
      const progLabel = document.createElement('div');
      progLabel.style.cssText = 'font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      progLabel.textContent = 'Progress';
      const barOuter = document.createElement('div');
      barOuter.className = 'progress-bar';
      barOuter.style.cssText = 'height: 8px; background: var(--bg-subtle); border-radius: 4px; overflow: hidden;';
      const barFill = document.createElement('div');
      barFill.className = 'progress-fill';
      barFill.style.cssText = `height: 100%; background: ${progressColor}; width: ${progressPct}%; transition: width 0.3s, background 0.3s;`;
      barOuter.appendChild(barFill);
      progWrap.appendChild(progLabel);
      progWrap.appendChild(barOuter);
      parent.appendChild(progWrap);
    }
    
    // Render executions
    async function renderExecutions(active, completed) {
      const activeContainer = document.getElementById('active-executions-container');
      const completedContainer = document.getElementById('completed-executions-container');
      const activeCountEl = document.getElementById('active-count');
      const completedCountEl = document.getElementById('completed-count');
      const activePluralEl = document.getElementById('active-count-plural');
      const completedPluralEl = document.getElementById('completed-count-plural');
      
      if (activeCountEl) activeCountEl.textContent = active.length;
      if (completedCountEl) completedCountEl.textContent = completed.length;
      if (activePluralEl) activePluralEl.textContent = active.length !== 1 ? 's' : '';
      if (completedPluralEl) completedPluralEl.textContent = completed.length !== 1 ? 's' : '';
      
      if (activeContainer) {
        activeContainer.replaceChildren();
        if (active.length === 0) {
          const p = document.createElement('p');
          p.style.cssText = 'color: var(--text-secondary); padding: 16px; text-align: center;';
          p.textContent = 'No active executions';
          activeContainer.appendChild(p);
        } else {
          for (const execution of active) {
            const card = await createExecutionCard(execution, 'active');
            activeContainer.appendChild(card);
          }
        }
      }
      
      if (completedContainer) {
        completedContainer.replaceChildren();
        if (completed.length === 0) {
          const p = document.createElement('p');
          p.style.cssText = 'color: var(--text-secondary); padding: 16px; text-align: center;';
          p.textContent = 'No completed executions';
          completedContainer.appendChild(p);
        } else {
          for (const execution of completed) {
            const card = await createExecutionCard(execution, 'completed');
            completedContainer.appendChild(card);
          }
        }
      }
    }
    
    // Create execution card
    async function createExecutionCard(execution, status) {
      const card = document.createElement('div');
      card.className = 'execution-card';
      card.setAttribute('data-execution-id', execution.id);
      
      const currentStep = execution.current_step || {};
      const nextStep = execution.next_step || {};
      // Use execution's total_steps (snapshot) from API so "X of Y" matches this execution
      const totalSteps = execution.total_steps ?? currentProcess?.steps?.length ?? 0;
      const rawStepNumber = currentStep.step_number || 0;
      // Clamp to 1..totalSteps so we never show "13 of 3" (backend now sends 1-based position; this guards stale data)
      const stepNumber = totalSteps > 0 ? Math.min(Math.max(1, rawStepNumber), totalSteps) : rawStepNumber;
      
      // Use the progress from the execution (calculated by backend based on completed steps)
      // The backend calculates: progress = (completed_steps / total_steps) * 100
      // This ensures each step completion moves the bar by (1/total_steps) * 100
      const progress = execution.progress || 0;
      
      const executionId = execution.id || '';
      
      // Format dates with time
      const startDate = execution.started_at ? new Date(execution.started_at).toLocaleString('en-US', { 
        month: 'short', 
        day: 'numeric', 
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
      }) : 'Unknown';
      const completedDate = execution.completed_at ? new Date(execution.completed_at).toLocaleString('en-US', { 
        month: 'short', 
        day: 'numeric', 
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
      }) : '';
      
      // Get current user for display
      const user = await getCurrentUser();
      
      // Determine execution display name based on status
      let executionDisplayName = '';
      if (status === 'completed') {
        // For completed executions, show process name and completion date
        const processName = currentProcess?.name || 'Process';
        executionDisplayName = `${processName} - ${completedDate || startDate}`;
      } else {
        // For active executions, show current step name
        executionDisplayName = currentStep.name || 'No step in progress';
      }
      
      // Check if current step is terminal (last step) - don't show next step if it is
      const isTerminalStep = stepNumber === totalSteps && totalSteps > 0;
      
      // Next step button (only for active executions) — shown in header next to Started/Started by
      let nextStepBtnWrap = null;
      if (status === 'active' && currentStep.step_id) {
        nextStepBtnWrap = document.createElement('div');
        nextStepBtnWrap.className = 'flows2-exec-next-step-wrap';
        nextStepBtnWrap.style.marginTop = '8px';
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-primary btn-sm flows2-exec-next-step';
        btn.style.whiteSpace = 'nowrap';
        const tri = flows2SvgPlayTriangle14();
        tri.style.marginRight = '6px';
        btn.appendChild(tri);
        btn.appendChild(document.createTextNode('Next step'));
        nextStepBtnWrap.appendChild(btn);
      }
      
      // Fetch execution details once for completed steps, evidence, and next-step header
      let executionEvidenceEl = null;
      let completedStepsSectionEl = null;
      let nextStepHeaderEl = null;
      if (status === 'active' || status === 'completed') {
        try {
          const executionData = await CoreAPI.getExecution(executionId);
          const executionSteps = executionData.execution_steps || [];
          const evidenceList = executionData.evidence || [];
          if (evidenceList.length > 0) {
            executionEvidenceEl = flows2BuildExecutionEvidenceSectionDOM(evidenceList);
          }
          
          const completedSteps = executionSteps
            .filter((es) => es.status === 'completed' || es.status === 'COMPLETED')
            .sort((a, b) => a.step_number - b.step_number);
          
          if (completedSteps.length > 0) {
            const completedStepsCapped = completedSteps.slice(0, FLOWS2_MAX_COMPLETED_EXECUTION_STEPS);
            completedStepsSectionEl = flows2BuildCompletedStepsSectionDOM(
              executionId,
              status,
              completedSteps,
              completedStepsCapped
            );
          }
          
          if (!isTerminalStep) {
            const readySteps = executionSteps.filter((es) => es.status === 'ready' || es.status === 'READY');
            if (readySteps.length > 0) {
              const nextReadyStep = readySteps[0];
              const stepDetails = currentProcess?.steps?.find((s) => s.id === nextReadyStep.step_id);
              if (stepDetails) {
                nextStepHeaderEl = flows2BuildNextStepSectionDOM(stepDetails, true);
              }
            }
          }
        } catch (error) {
          console.error('Failed to fetch execution details:', error);
        }
      }
      
      // Calculate progress bar color - blend to green starting at 75%
      let progressColor = 'var(--accent, #3b82f6)'; // Default blue
      if (progress >= 100) {
        progressColor = 'var(--success, #10b981)'; // Fully green when complete
      } else if (progress >= 75) {
        const blendFactor = (progress - 75) / 25;
        const blue = [59, 130, 246];
        const green = [16, 185, 129];
        const r = Math.round(blue[0] + (green[0] - blue[0]) * blendFactor);
        const g = Math.round(blue[1] + (green[1] - blue[1]) * blendFactor);
        const b = Math.round(blue[2] + (green[2] - blue[2]) * blendFactor);
        progressColor = `rgb(${r}, ${g}, ${b})`;
      }
      
      const execHeader = document.createElement('div');
      execHeader.className = 'execution-header flows2-exec-card-header';
      execHeader.style.cssText =
        'display: flex; justify-content: space-between; align-items: flex-start; cursor: pointer; padding: 12px; border-bottom: 1px solid var(--border-light);';
      
      const headerLeft = document.createElement('div');
      headerLeft.style.cssText = 'flex: 1; min-width: 0;';
      
      if (status === 'active') {
        if (nextStepHeaderEl) headerLeft.appendChild(nextStepHeaderEl);
        const startedEl = document.createElement('div');
        startedEl.className = 'execution-date';
        startedEl.style.cssText = `font-size: 13px; color: var(--text-secondary); margin-bottom: 2px; margin-top: ${nextStepHeaderEl ? '8px' : '0'};`;
        startedEl.textContent = `Started: ${startDate}`;
        headerLeft.appendChild(startedEl);
        const byEl = document.createElement('div');
        byEl.style.cssText = 'font-size: 13px; color: var(--text-secondary); margin-bottom: 8px;';
        byEl.textContent = `Started by: ${user.username}`;
        headerLeft.appendChild(byEl);
        if (nextStepBtnWrap) headerLeft.appendChild(nextStepBtnWrap);
        flows2AppendExecutionProgressBlock(headerLeft, progressColor, progress, { marginTop: '12px' });
      } else {
        const nameEl = document.createElement('div');
        nameEl.className = 'execution-id';
        nameEl.style.cssText = 'font-weight: 600; color: var(--text-primary); margin-bottom: 4px;';
        nameEl.textContent = executionDisplayName;
        headerLeft.appendChild(nameEl);
        const compEl = document.createElement('div');
        compEl.className = 'execution-date';
        compEl.style.cssText = 'font-size: 13px; color: var(--text-secondary); margin-bottom: 2px;';
        compEl.textContent = `Completed: ${completedDate || startDate}`;
        headerLeft.appendChild(compEl);
      }
      
      const headerRight = document.createElement('div');
      headerRight.style.cssText = 'display: flex; align-items: center; gap: 12px; flex-shrink: 0;';
      const badge = document.createElement('span');
      badge.className = `badge ${status === 'active' ? 'badge-accent' : 'badge-success'}`;
      badge.style.flexShrink = '0';
      badge.textContent = status === 'active' ? 'In Progress' : 'Completed';
      const toggleWrap = document.createElement('div');
      toggleWrap.className = 'execution-toggle';
      toggleWrap.style.cssText = 'transition: transform 0.2s; transform: rotate(0deg);';
      toggleWrap.appendChild(flows2SvgChevron16());
      headerRight.appendChild(badge);
      headerRight.appendChild(toggleWrap);
      execHeader.appendChild(headerLeft);
      execHeader.appendChild(headerRight);
      card.appendChild(execHeader);
      
      const execContent = document.createElement('div');
      execContent.className = 'execution-content';
      execContent.style.cssText = 'display: none; padding: 12px;';
      
      if (status !== 'active') {
        flows2AppendExecutionProgressBlock(execContent, progressColor, progress, { marginBottom: '12px' });
      }
      
      const detailsWrap = document.createElement('div');
      detailsWrap.className = 'execution-details';
      detailsWrap.style.marginBottom = '12px';
      if (execution.batch_id) {
        const row = document.createElement('div');
        row.className = 'execution-detail';
        row.style.cssText =
          'display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border-light);';
        const lab = document.createElement('span');
        lab.className = 'execution-detail-label';
        lab.style.cssText = 'font-size: 13px; color: var(--text-secondary);';
        lab.textContent = 'Batch ID';
        const val = document.createElement('span');
        val.className = 'execution-detail-value';
        val.style.cssText = 'font-size: 13px; color: var(--text-primary);';
        val.textContent = execution.batch_id;
        row.appendChild(lab);
        row.appendChild(val);
        detailsWrap.appendChild(row);
      }
      execContent.appendChild(detailsWrap);
      if (executionEvidenceEl) execContent.appendChild(executionEvidenceEl);
      if (completedStepsSectionEl) execContent.appendChild(completedStepsSectionEl);
      card.appendChild(execContent);

      // Clicks on .flows2-exec-next-step-wrap / .flows2-exec-next-step must not toggle card expand
      // (see stopPropagation on the wrap; do not add interactive children on the header outside that wrap without updating this).
      const execHdr = card.querySelector('.flows2-exec-card-header');
      if (execHdr) {
        execHdr.addEventListener('click', (e) => {
          if (e.target.closest('.flows2-exec-next-step-wrap')) return;
          if (typeof window.toggleExecution === 'function') window.toggleExecution(execHdr);
        });
      }
      const nextWrap = card.querySelector('.flows2-exec-next-step-wrap');
      if (nextWrap) {
        nextWrap.addEventListener('click', (e) => e.stopPropagation());
      }
      const nextBtn = card.querySelector('.flows2-exec-next-step');
      if (nextBtn && executionId) {
        nextBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (typeof window.completeCurrentStep === 'function') window.completeCurrentStep(executionId);
        });
      }
      card.querySelectorAll('.flows2-completed-steps-toggle').forEach((hdr) => {
        hdr.addEventListener('click', () => {
          const sid = hdr.getAttribute('data-completed-section-id');
          if (sid && typeof window.toggleCompletedSteps === 'function') window.toggleCompletedSteps(sid);
        });
      });
      card.querySelectorAll('.flows2-io-pane-hdr').forEach((hdr) => {
        hdr.addEventListener('click', (ev) => {
          ev.stopPropagation();
          const pid = hdr.getAttribute('data-io-pane-id');
          if (pid && typeof window.toggleIOPane === 'function') window.toggleIOPane(pid, ev);
        });
      });

      return card;
    }
    
    // ============================================================
    // COMPLETE CURRENT STEP - Dedicated SPA screen (replaces modal)
    // ============================================================
    window.completeCurrentStep = async function(executionId) {
      try {
        // Get full execution details to find the ready step
        const executionData = await CoreAPI.getExecution(executionId);
        const executionSteps = executionData.execution_steps || [];
        
        // Find the ready step (current step to complete)
        const readyStep = executionSteps.find(es => es.status === 'ready' || es.status === 'READY');
        
        if (!readyStep) {
          showNotification('error', 'No Ready Step', 'There is no step ready to complete.');
          return;
        }
        
        // Get the step definition from the process
        const processData = await CoreAPI.getProcess(executionData.process_id);
        const stepDefinition = processData.steps.find(s => s.id === readyStep.step_id);
        
        if (!stepDefinition) {
          showNotification('error', 'Step Not Found', 'Step definition not found.');
          return;
        }
        
        // Navigate to the dedicated execution-step screen.
        // Keep the legacy modal entrypoint elsewhere during transition.
        const returnTo = processId ? (`/core/flows?id=${encodeURIComponent(processId)}`) : '/core/flows';
        const url =
          `/core/flows/batches/start?execution_id=${encodeURIComponent(executionId)}` +
          `&id=${encodeURIComponent(processId)}` +
          `&return_to=${encodeURIComponent(returnTo)}`;
        window.location.href = url;
        
      } catch (error) {
        console.error('Failed to open execution modal:', error);
        const msg = error && error.message ? error.message : 'Failed to open execution modal. Please try again.';
        showNotification('error', 'Failed to Open Execution Modal', msg);
      }
    };
    
    // ============================================================
    // EXECUTION MODAL FUNCTIONS
    // ============================================================
    // openExecutionModal and submitExecution are now loaded from js/execution-modal.js
    // Configuration is set above in ExecutionModalConfig
    
    // ============================================================
    // START NEXT STEP
    // ============================================================
    window.startNextStep = async function(executionId) {
      // This is essentially the same as completing the current step
      // The backend will automatically advance to the next step
      await completeCurrentStep(executionId);
    };
