/**
 * Execution prompts and evidence upload UI for execute-step.
 * Depends on CoreAPI (listEvidence, getEvidenceConfig, …), escapeHtml, showNotification on root.
 * Load before execution-modal.js — exposes window.ExecutionRenderPrompts.
 */
(function (root) {
  'use strict';

  function throwIfAborted(signal) {
    if (signal && signal.aborted) {
      var err = typeof DOMException !== 'undefined' ? new DOMException('Aborted', 'AbortError') : new Error('Aborted');
      if (!(err instanceof DOMException)) err.name = 'AbortError';
      throw err;
    }
  }

  async function renderExecutionPrompts(ctx) {
    var modal = ctx.modal;
    var ses = ctx.ses;
    var promptsContainer = ctx.promptsContainer;
    var stepDefinition = ctx.stepDefinition;
    var escapeHtml = ctx.escapeHtml;
    var signal = ctx.signal;
    var CoreAPI = root.CoreAPI;
    var showNotification = root.showNotification;
    var executionPrompts = (stepDefinition && stepDefinition.execution_prompts) || [];
    var currentStepId = stepDefinition && stepDefinition.id ? String(stepDefinition.id) : null;
    if (executionPrompts.length > 0 && promptsContainer) {
      var executionIdForEvidence = modal.dataset.executionId || '';
      let evidenceListForStep = [];
      // Client-staged files (draft mode): do NOT create execution until Record step.
      if (!ses.pendingEvidenceFilesByStepId) ses.pendingEvidenceFilesByStepId = new Map();
      if (CoreAPI && typeof CoreAPI.listEvidence === 'function' && executionIdForEvidence && currentStepId) {
        try {
          const res = await CoreAPI.listEvidence(executionIdForEvidence, { signal: signal });
          const allEvidence = res.evidence || [];
          var byStepDef = new Map();
          var byExecStep = new Map();
          allEvidence.forEach(function(e) {
            if (e.step_definition_id) {
              var list = byStepDef.get(e.step_definition_id) || [];
              list.push(e);
              byStepDef.set(e.step_definition_id, list);
            }
            if (e.execution_step_id) {
              var list2 = byExecStep.get(e.execution_step_id) || [];
              list2.push(e);
              byExecStep.set(e.execution_step_id, list2);
            }
          });
          var stepList = (byStepDef.get(currentStepId) || []).concat(byExecStep.get(currentStepId) || []);
          var seenIds = new Set();
          evidenceListForStep = [];
          stepList.forEach(function(e) {
            if (!e || e.id == null) return;
            var id = e.id;
            if (seenIds.has(id)) return;
            seenIds.add(id);
            evidenceListForStep.push(e);
          });
        } catch (e) {
          if (e && e.name === 'AbortError') throw e;
          evidenceListForStep = [];
        }
      }
      throwIfAborted(signal);
      if (!ses.evidenceByStepId) ses.evidenceByStepId = new Map();
      ses.evidenceByStepId.set(currentStepId, evidenceListForStep);
      var maxEvidenceBytes = 10 * 1024 * 1024;
      if (CoreAPI && typeof CoreAPI.getEvidenceConfig === 'function') {
        try {
          var evidenceCfg = await CoreAPI.getEvidenceConfig({ signal: signal });
          if (evidenceCfg && evidenceCfg.max_file_size_bytes != null) maxEvidenceBytes = evidenceCfg.max_file_size_bytes;
        } catch (e) {
          if (e && e.name === 'AbortError') throw e;
        }
      }
      throwIfAborted(signal);
      executionPrompts.forEach(prompt => {
        const promptSection = document.createElement('div');
        promptSection.className = 'execute-prompt-section';
        promptSection.style.cssText = 'margin-bottom: 16px;';
        promptSection.dataset.promptLabel = prompt.label || '';
        promptSection.dataset.promptRequired = prompt.required !== false ? 'true' : 'false';
        promptSection.dataset.promptType = prompt.type || 'text';

        let inputHtml = '';
        if (prompt.type === 'evidence') {
          inputHtml = `
            <div class="execute-evidence-upload" data-step-id="${currentStepId || ''}" style="border: 2px dashed var(--border-default); border-radius: var(--radius-lg); padding: 16px; background: var(--bg-secondary, #f9fafb);">
              <p style="margin: 0 0 8px 0; font-size: 13px; color: var(--text-secondary);">Photos or PDFs (JPEG, PNG, PDF, max 10MB)</p>
              <input type="file" class="execute-evidence-file-input" accept="image/jpeg,image/png,application/pdf" multiple style="display: block; margin-bottom: 8px;">
              <div class="execute-evidence-error" style="display:none; margin-top: 8px; padding: 10px 12px; background: hsl(0, 93%, 94%); border: 1px solid var(--error, #ef4444); border-radius: var(--radius-md); color: #b91c1c; font-size: 13px; font-weight: 500;" role="alert"></div>
              <div class="execute-evidence-list" style="margin-top: 12px;"></div>
            </div>
          `;
        } else if (prompt.type === 'text') {
          inputHtml = `<input type="text" class="spa-inp execute-prompt-input" data-prompt-label="${escapeHtml(prompt.label)}" ${prompt.required !== false ? 'data-required="true"' : ''}>`;
        } else if (prompt.type === 'number') {
          inputHtml = `<input type="number" class="spa-inp execute-prompt-input" data-prompt-label="${escapeHtml(prompt.label)}" ${prompt.required !== false ? 'data-required="true"' : ''} step="0.01">`;
        } else if (prompt.type === 'date') {
          inputHtml = `<input type="date" class="spa-inp execute-prompt-input" data-prompt-label="${escapeHtml(prompt.label)}" ${prompt.required !== false ? 'data-required="true"' : ''}>`;
        } else if (prompt.type === 'select') {
          inputHtml = `<select class="spa-inp execute-prompt-input" data-prompt-label="${escapeHtml(prompt.label)}" ${prompt.required !== false ? 'data-required="true"' : ''}><option value="">Select...</option></select>`;
        }

        promptSection.innerHTML = `
          <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
            ${escapeHtml(prompt.label)}${prompt.required !== false ? ' <span style="color: var(--error);">*</span>' : ''}${prompt.unit ? ` (${escapeHtml(prompt.unit)})` : ''}
          </label>
          ${inputHtml}
        `;

        if (prompt.type === 'evidence') {
          const uploadZone = promptSection.querySelector('.execute-evidence-upload');
          const listEl = promptSection.querySelector('.execute-evidence-list');
          const fileInput = promptSection.querySelector('.execute-evidence-file-input');
          const errEl = promptSection.querySelector('.execute-evidence-error');
          function renderEvidenceList(items) {
            if (!listEl) return;
            listEl.innerHTML = items.length === 0 ? '' : items.map(function(item) {
              var viewUrl = typeof CoreAPI.getEvidenceViewUrl === 'function' ? CoreAPI.getEvidenceViewUrl(item.id) : '#';
              var downloadUrl = typeof CoreAPI.getEvidenceDownloadUrl === 'function' ? CoreAPI.getEvidenceDownloadUrl(item.id) : '#';
              var id = (item.id && escapeHtml(item.id)) || '';
              return (
                '<div class="execute-evidence-row" data-evidence-id="' + id + '" style="display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: var(--bg-card); border-radius: var(--radius-md); margin-bottom: 6px; font-size: 13px;">' +
                  '<span>' + escapeHtml(item.file_name || 'File') + '</span>' +
                  '<div style="display: flex; gap: 8px; align-items: center;">' +
                    '<a class="btn btn-secondary btn-sm" href="' + escapeHtml(viewUrl) + '" target="_blank" rel="noopener" style="text-decoration:none;">View</a>' +
                    '<a class="btn btn-secondary btn-sm" href="' + escapeHtml(downloadUrl) + '" target="_blank" rel="noopener" style="text-decoration:none;">Download</a>' +
                    '<button type="button" class="btn btn-secondary btn-sm execute-evidence-remove-btn" data-evidence-id="' + id + '">Remove</button>' +
                  '</div>' +
                '</div>'
              );
            }).join('');
          }

          function renderPendingFiles() {
            if (!listEl) return;
            var pending = (ses.pendingEvidenceFilesByStepId && ses.pendingEvidenceFilesByStepId.get(currentStepId)) || [];
            if (!pending.length) return;
            var html = pending.map(function(f, idx) {
              var nm = escapeHtml(f && f.name ? f.name : ('File ' + (idx + 1)));
              var sz = (f && f.size != null) ? (' · ' + Math.round(f.size / 1024) + ' KB') : '';
              return (
                '<div class="execute-evidence-row" data-pending-idx="' + idx + '" style="display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); margin-bottom: 6px; font-size: 13px; border: 1px dashed var(--border-default, #e5e7eb);">' +
                  '<span>' + nm + '<span style="color: var(--text-tertiary,#9ca3af); font-size:12px;">' + sz + '</span></span>' +
                  '<div style="display:flex; gap:8px; align-items:center;">' +
                    '<span style="color: var(--text-secondary,#6b7280); font-size:12px;">Pending upload</span>' +
                    '<button type="button" class="btn btn-secondary btn-sm execute-evidence-pending-remove-btn" data-pending-idx="' + idx + '">Remove</button>' +
                  '</div>' +
                '</div>'
              );
            }).join('');
            listEl.insertAdjacentHTML('beforeend', html);
          }
          listEl.addEventListener('click', async function(ev) {
            var pbtn = ev.target && ev.target.closest && ev.target.closest('.execute-evidence-pending-remove-btn');
            if (pbtn && pbtn.dataset && pbtn.dataset.pendingIdx != null) {
              ev.preventDefault();
              ev.stopPropagation();
              var idx = parseInt(pbtn.dataset.pendingIdx, 10);
              var pending = (ses.pendingEvidenceFilesByStepId && ses.pendingEvidenceFilesByStepId.get(currentStepId)) || [];
              if (!isNaN(idx)) {
                pending.splice(idx, 1);
                if (ses.pendingEvidenceFilesByStepId) ses.pendingEvidenceFilesByStepId.set(currentStepId, pending);
              }
              renderEvidenceList(evidenceListForStep);
              renderPendingFiles();
              if (uploadZone) uploadZone.dataset.evidenceCount = String((evidenceListForStep.length || 0) + (pending.length || 0));
              return;
            }
            var btn = ev.target && ev.target.closest && ev.target.closest('.execute-evidence-remove-btn');
            if (!btn || !btn.dataset || !btn.dataset.evidenceId) return;
            var evidenceId = btn.dataset.evidenceId;
            if (!evidenceId || typeof CoreAPI.deleteEvidence !== 'function') return;
            btn.disabled = true;
            try {
              await CoreAPI.deleteEvidence(evidenceId);
              evidenceListForStep = evidenceListForStep.filter(function(e) { return e.id !== evidenceId; });
              if (ses.evidenceByStepId) ses.evidenceByStepId.set(currentStepId, evidenceListForStep);
              if (uploadZone) uploadZone.dataset.evidenceCount = String(evidenceListForStep.length);
              renderEvidenceList(evidenceListForStep);
              if (typeof showNotification === 'function') showNotification('success', 'Evidence removed', '');
            } catch (err) {
              if (typeof showNotification === 'function') showNotification('error', 'Remove failed', err && err.message ? err.message : 'Could not remove evidence.');
            }
            btn.disabled = false;
          });
          renderEvidenceList(evidenceListForStep);
          renderPendingFiles();
          var pending0 = (ses.pendingEvidenceFilesByStepId && ses.pendingEvidenceFilesByStepId.get(currentStepId)) || [];
          uploadZone.dataset.evidenceCount = String((evidenceListForStep.length || 0) + (pending0.length || 0));
          if (fileInput) {
            fileInput.addEventListener('change', async function() {
              if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
              var files = this.files;
              if (!files || !files.length || !currentStepId) return;
              var pending = (ses.pendingEvidenceFilesByStepId && ses.pendingEvidenceFilesByStepId.get(currentStepId)) || [];
              for (var i = 0; i < files.length; i++) {
                var file = files[i];
                if (file.size > maxEvidenceBytes) {
                  if (typeof showNotification === 'function') showNotification('error', 'File too large', 'Max ' + Math.round(maxEvidenceBytes / (1024 * 1024)) + 'MB. Choose a smaller file.');
                  continue;
                }
                pending.push(file);
              }
              if (ses.pendingEvidenceFilesByStepId) ses.pendingEvidenceFilesByStepId.set(currentStepId, pending);
              renderEvidenceList(evidenceListForStep);
              renderPendingFiles();
              if (uploadZone) uploadZone.dataset.evidenceCount = String((evidenceListForStep.length || 0) + (pending.length || 0));
              this.value = '';
            });
          }
        } else {
          const promptInput = promptSection.querySelector('.execute-prompt-input');
          if (promptInput) {
            promptInput.addEventListener('input', function() {
              if (this.value.trim()) this.style.border = '';
            });
            promptInput.addEventListener('change', function() {
              if (this.value.trim()) this.style.border = '';
            });
          }
        }

        promptsContainer.appendChild(promptSection);
      });
    } else if (promptsContainer) {
      promptsContainer.innerHTML = '<p style="color: var(--text-secondary); font-size: 14px; padding: 16px;">No execution prompts for this step.</p>';
    }

  }

  root.ExecutionRenderPrompts = {
    renderExecutionPrompts: renderExecutionPrompts,
  };
})(typeof window !== 'undefined' ? window : this);
