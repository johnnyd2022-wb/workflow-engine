(function() {
  'use strict';

  const {
    summaryInputDisplayName,
    summaryOutputDisplayName,
    isCustomExecutionPrompt
  } = window.ProcessModalUtils;
  const {
    deriveTraceabilityModes,
    formatTraceabilityModeLabel,
    formatOutputExpirySummary,
    formatOutputReadySummary,
    buildStepSummaryWarnings
  } = window.ProcessModalSummaryUtils;

  async function renderCompliancePanel(sortedSteps, helpers) {
    const {
      isProcessFlowSummaryPage,
      resolveCurrentStepForSummary,
      enrichStepForSummaryFromSession
    } = helpers;
    const panel = document.getElementById('flow-compliance-panel');
    const heading = document.getElementById('step-summaries-heading');
    if (!panel) return;
    if (!isProcessFlowSummaryPage()) {
      panel.style.display = 'none';
      panel.innerHTML = '';
      if (heading) {
        heading.style.display = '';
        heading.textContent = 'Created Steps';
        heading.style.marginTop = '0';
      }
      return;
    }
    if (heading) {
      heading.style.display = 'none';
      heading.style.marginTop = '0';
    }
    panel.style.display = 'block';

    const escHtml = function (s) {
      return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    };

    let { step, displayNumber, isFinalStep } = resolveCurrentStepForSummary(sortedSteps);
    if (!step) {
      panel.innerHTML =
        '<p style="font-size:0.875rem;color:var(--text-tertiary);margin:0;">No step data to review.</p>';
      return;
    }
    step = enrichStepForSummaryFromSession(step, sortedSteps);

    const stepName = escHtml(step.name || 'Untitled step');
    const tm = deriveTraceabilityModes(step);
    const batchLabel = escHtml(formatTraceabilityModeLabel(tm.batch));
    const evidenceLabel = escHtml(formatTraceabilityModeLabel(tm.evidence));

    const purposeText = (step.description || '').trim();
    let hasStepDocumentation = !!(
      step.documentation_summary && String(step.documentation_summary).trim()
    );
    const stepIdForDocs =
      step && step.id && String(step.id) !== '__pending__' ? String(step.id) : '';
    if (
      !hasStepDocumentation &&
      stepIdForDocs &&
      typeof CoreAPI !== 'undefined' &&
      typeof CoreAPI.getStepDocumentation === 'function'
    ) {
      try {
        const docRes = await CoreAPI.getStepDocumentation(stepIdForDocs);
        const docs = docRes && Array.isArray(docRes.documents) ? docRes.documents : [];
        if (docs.length > 0) {
          hasStepDocumentation = true;
        }
      } catch (err) {
        console.warn('Summary: could not verify step documentation', err);
      }
    }

    const inputs = (step.inputs || []).filter(function (i) {
      return i && summaryInputDisplayName(i);
    });
    const outputs = (step.outputs || []).filter(function (o) {
      return o && summaryOutputDisplayName(o);
    });
    const customPrompts = (step.execution_prompts || []).filter(isCustomExecutionPrompt);

    let html = '';
    html +=
      '<div class="flow-step-summary-page"><p class="flow-step-summary-kicker" style="font-size:0.75rem;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:var(--text-secondary);margin:0 0 12px 0;">Step summary</p>';
    html += `<div class="flow-step-summary-header" style="display:flex;align-items:center;gap:12px;margin:0 0 22px 0;flex-wrap:wrap;">`;
    html += `<span class="flow-step-num-badge" aria-hidden="true">${displayNumber}</span>`;
    html += `<span style="font-size:1.125rem;font-weight:600;color:var(--text-primary);line-height:1.3;">Step ${displayNumber} \u2014 ${stepName}</span>`;
    html += '</div>';

    html +=
      '<section class="flow-compliance__section flow-step-summary-section" style="margin-bottom:18px;"><h3 style="font-size:0.9375rem;font-weight:600;color:var(--text-primary);margin:0 0 10px 0;">Step function</h3>';

    html += '<div style="font-size:0.875rem;font-weight:600;color:var(--text-secondary);margin:0 0 6px 0;">Inputs</div>';
    if (inputs.length === 0) {
      html +=
        '<p style="font-size:0.875rem;color:var(--text-tertiary);margin:0 0 12px 0;">None</p>';
    } else {
      html += '<ul class="flow-compliance-step-list" style="margin-bottom:12px;">';
      inputs.forEach(function (input) {
        const q =
          input.quantity !== null && input.quantity !== undefined ? input.quantity : '';
        const u = input.unit || '';
        const bit = q ? ` (${q}${u ? ' ' + u : ''})` : u ? ` (${u})` : '';
        html += `<li><span class="flow-compliance-row__text">${escHtml(summaryInputDisplayName(input) + bit)}</span></li>`;
      });
      html += '</ul>';
    }

    html += '<div style="font-size:0.875rem;font-weight:600;color:var(--text-secondary);margin:0 0 6px 0;">Outputs</div>';
    if (outputs.length === 0) {
      html +=
        '<p style="font-size:0.875rem;color:var(--text-tertiary);margin:0 0 12px 0;">None</p>';
    } else {
      html += '<ul class="flow-compliance-step-list" style="margin-bottom:12px;">';
      outputs.forEach(function (output) {
        const q =
          output.quantity !== null && output.quantity !== undefined ? output.quantity : '';
        const u = output.unit || '';
        const bit = q ? ` (${q}${u ? ' ' + u : ''})` : u ? ` (${u})` : '';
        html += `<li><span class="flow-compliance-row__text">${escHtml(summaryOutputDisplayName(output) + bit)}</span></li>`;
      });
      html += '</ul>';
    }

    if (purposeText) {
      html +=
        '<div style="font-size:0.875rem;font-weight:600;color:var(--text-secondary);margin:0 0 6px 0;">Purpose</div>';
      html += `<p style="font-size:0.875rem;color:var(--text-primary);margin:0;line-height:1.55;">${escHtml(purposeText)}</p>`;
    }
    html += '</section>';

    html +=
      '<section class="flow-compliance__section flow-step-summary-section" style="margin-bottom:18px;border-top:1px solid var(--border-default,#e5e7eb);padding-top:16px;"><h3 style="font-size:0.9375rem;font-weight:600;color:var(--text-primary);margin:0 0 10px 0;">Traceability &amp; compliance</h3>';
    html +=
      '<div style="font-size:0.875rem;line-height:1.65;color:var(--text-primary);"><div><span style="color:var(--text-secondary);font-weight:500;">Batch:</span> ' +
      batchLabel +
      '</div><div><span style="color:var(--text-secondary);font-weight:500;">Evidence:</span> ' +
      evidenceLabel +
      '</div></div></section>';

    html +=
      '<section class="flow-compliance__section flow-step-summary-section" style="margin-bottom:18px;border-top:1px solid var(--border-default,#e5e7eb);padding-top:16px;"><h3 style="font-size:0.9375rem;font-weight:600;color:var(--text-primary);margin:0 0 10px 0;">Output rules</h3>';
    if (outputs.length === 0) {
      html +=
        '<p style="font-size:0.875rem;color:var(--text-tertiary);margin:0;">No outputs — rules apply when outputs exist.</p>';
    } else if (outputs.length === 1) {
      const o = outputs[0];
      html +=
        '<div style="font-size:0.875rem;line-height:1.65;color:var(--text-primary);"><div><span style="color:var(--text-secondary);font-weight:500;">Expiry:</span> ' +
        escHtml(formatOutputExpirySummary(o)) +
        '</div><div><span style="color:var(--text-secondary);font-weight:500;">Ready date:</span> ' +
        escHtml(formatOutputReadySummary(o)) +
        '</div></div>';
    } else {
      html += '<ul class="flow-compliance-step-list">';
      outputs.forEach(function (o) {
        const on = escHtml(summaryOutputDisplayName(o) || 'Output');
        const ex = escHtml(formatOutputExpirySummary(o));
        const rd = escHtml(formatOutputReadySummary(o));
        html += `<li style="margin-bottom:8px;"><span class="flow-compliance-row__text"><strong>${on}</strong> — Expiry: ${ex}; Ready: ${rd}</span></li>`;
      });
      html += '</ul>';
    }
    html += '</section>';

    html +=
      '<section class="flow-compliance__section flow-step-summary-section" style="margin-bottom:18px;border-top:1px solid var(--border-default,#e5e7eb);padding-top:16px;"><h3 style="font-size:0.9375rem;font-weight:600;color:var(--text-primary);margin:0 0 10px 0;">Documentation and Custom prompts</h3>';
    html +=
      '<p style="font-size:0.875rem;color:var(--text-primary);margin:0 0 12px 0;line-height:1.55;"><span style="color:var(--text-secondary);font-weight:500;">Attached step documentation:</span> ' +
      (hasStepDocumentation ? 'Yes' : 'No') +
      '</p>';
    if (customPrompts.length > 0) {
      html +=
        '<div style="font-size:0.875rem;font-weight:600;color:var(--text-secondary);margin:0 0 6px 0;">Custom prompts</div>';
      html += '<ul class="flow-compliance-step-list">';
      customPrompts.forEach(function (p) {
        const req = p.required !== false ? 'Required' : 'Optional';
        const unit = p.unit ? `, ${escHtml(p.unit)}` : '';
        const line = `${escHtml(p.label || '')} (${escHtml(p.type || '')}${unit}) — ${req}`;
        html += `<li><span class="flow-compliance-row__text">${line}</span></li>`;
      });
      html += '</ul>';
    }
    html += '</section>';

    const warns = buildStepSummaryWarnings(step, isFinalStep);
    html +=
      '<section class="flow-compliance__section flow-step-summary-section" style="margin-bottom:0;border-top:1px solid var(--border-default,#e5e7eb);padding-top:16px;"><h3 style="font-size:0.9375rem;font-weight:600;color:var(--text-primary);margin:0 0 10px 0;">Warnings</h3>';
    if (warns.length === 0) {
      html +=
        '<p style="font-size:0.875rem;color:var(--text-tertiary);margin:0;">No issues flagged for this step.</p>';
    } else {
      html +=
        '<ul class="flow-compliance-warnings" style="margin:0;padding-left:0;list-style:none;font-size:0.875rem;line-height:1.65;">';
      warns.forEach(function (w) {
        html += `<li style="margin-bottom:6px;"><span aria-hidden="true">\u26A0 </span>${escHtml(w)}</li>`;
      });
      html += '</ul>';
    }
    html += '</section></div>';

    panel.innerHTML = html;
  }

  window.ProcessModalSummary = Object.freeze({ renderCompliancePanel });
})();
