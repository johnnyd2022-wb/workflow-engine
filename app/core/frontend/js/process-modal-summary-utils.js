(function() {
  'use strict';

  const { summaryOutputDisplayName } = window.ProcessModalUtils;

  function deriveTraceabilityModes(step) {
    let batch = step.batch_number_mode;
    let ev = step.evidence_mode;
    if (batch && ev) return { batch, evidence: ev };
    const prompts = step.execution_prompts || [];
    if (!batch) {
      const bn = prompts.find(p => (p.label || '').toLowerCase() === 'batch number');
      if (bn) batch = bn.required !== false ? 'required' : 'optional';
      else batch = 'dont_ask';
    }
    if (!ev) {
      const evp = prompts.find(
        p => p.type === 'evidence' || (p.label || '').toLowerCase() === 'evidence'
      );
      if (evp) ev = evp.required !== false ? 'required' : 'optional';
      else ev = 'dont_ask';
    }
    return { batch: batch || 'optional', evidence: ev || 'optional' };
  }

  function formatTraceabilityModeLabel(mode) {
    if (mode === 'required') return 'Required';
    if (mode === 'optional') return 'Optional';
    return 'Off';
  }

  function formatOutputExpirySummary(output) {
    const ce = (output.extra_data || {}).custom_expiry;
    if (!ce || !ce.enabled) return 'None';
    const mode =
      ce.mode ||
      (ce.set_at_execution || ce.set_during_execution ? 'set_at_execution' : 'fixed_duration');
    if (mode === 'set_at_execution') return 'Operator defined';
    const dv = ce.duration_value != null ? ce.duration_value : ce.expiry_days;
    const du = (ce.duration_unit || 'days').toLowerCase();
    if (dv != null && du) return `${dv} ${dv === 1 ? du.replace(/s$/, '') : du}`;
    return 'Configured';
  }

  function formatOutputReadySummary(output) {
    const rd = (output.extra_data || {}).ready_date;
    if (!rd || !rd.enabled) return 'None';
    const mode = rd.mode || 'fixed_duration';
    if (mode === 'set_at_execution') return 'Operator defined';
    const dv = rd.duration_value;
    const du = (rd.duration_unit || 'hours').toLowerCase();
    if (dv != null && du) return `${dv} ${dv === 1 ? du.replace(/s$/, '') : du}`;
    return 'Configured';
  }

  function buildStepSummaryWarnings(step, isFinalStep) {
    const warnings = [];
    if (!step) return warnings;
    const outputs = (step.outputs || []).filter(function (o) {
      return o && summaryOutputDisplayName(o);
    });
    if (outputs.length > 0) {
      const anyNoExpiry = outputs.some(function (o) {
        return formatOutputExpirySummary(o) === 'None';
      });
      if (anyNoExpiry) warnings.push('Output has no expiry rule');
    }
    const tm = deriveTraceabilityModes(step);
    if (isFinalStep && tm.batch === 'dont_ask') {
      warnings.push('No batch / run ID tracking on final step');
    }
    return warnings;
  }

  window.ProcessModalSummaryUtils = Object.freeze({
    deriveTraceabilityModes,
    formatTraceabilityModeLabel,
    formatOutputExpirySummary,
    formatOutputReadySummary,
    buildStepSummaryWarnings
  });
})();
