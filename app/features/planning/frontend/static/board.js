(function () {
  'use strict';
  const root = document.querySelector('[data-board-root]');
  if (!root || root.dataset.initialised) return;
  root.dataset.initialised = 'true';
  const canRecord = root.dataset.canRecord === 'true';
  const error = root.querySelector('[data-board-error]');
  const notice = root.querySelector('[data-board-notice]');
  const rangeForm = root.querySelector('[data-board-range]');
  const settingForm = root.querySelector('[data-setting-form]');
  const planForm = root.querySelector('[data-plan-form]');
  let workflows = [];
  let materialLots = [];
  let materialAssessment = null;
  let boardRequest = 0;
  function node(tag, text) { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; return element; }
  function iso(day) { return day.getFullYear() + '-' + String(day.getMonth() + 1).padStart(2, '0') + '-' + String(day.getDate()).padStart(2, '0'); }
  function day(value) { const parts = value.split('-').map(Number); return new Date(parts[0], parts[1] - 1, parts[2], 12); }
  function add(value, offset) { const result = new Date(value); result.setDate(result.getDate() + offset); return result; }
  function fail(exc) { error.textContent = exc.message || 'Unable to update the plan'; error.hidden = false; }
  async function api(path, body, extraHeaders) {
    const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', headers: Object.assign({'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || ''}, extraHeaders || {}), body: body === undefined ? undefined : JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Unable to update the plan');
    return result;
  }
  function option(select, value, text) { const element = node('option', text); element.value = value; select.append(element); }
  function field(form, text, name, type, value) { const label = node('label', text); const input = node('input'); input.type = type; input.name = name; input.value = value; input.required = true; label.append(input); form.append(label); return input; }
  function actionForm(card, batch, action, label, name, type, value) {
    const form = node('form'); form.setAttribute('hx-boost', 'false');
    let input;
    if (name) { input = field(form, label, name, type, value); if (type === 'number') { input.min = '0'; input.max = '100'; input.step = '1'; } }
    const button = node('button', name ? (action === 'priority' ? 'Set priority' : 'Move batch') : label); button.type = 'submit'; form.append(button);
    form.addEventListener('submit', async function (event) {
      event.preventDefault(); button.disabled = true; error.hidden = true;
      const body = {action: action, expected_revision: batch.revision};
      if (name) body[name] = type === 'number' ? Number(input.value) : input.value;
      if (action === 'pin') body.pinned = !batch.pinned;
      try { await api('/api/core/planner/batches/' + batch.id + '/action', body); await loadBoard(); notice.textContent = 'Plan updated'; }
      catch (exc) { fail(exc); button.disabled = false; }
    }); card.append(form);
  }
  function batchCard(batch) {
    const card = node('article'); card.className = 'board-batch'; card.dataset.batchId = batch.id;
    card.append(node('h4', batch.snapshot.demand_reference + ' · Batch ' + batch.batch_number));
    card.append(node('p', batch.quantity + ' ' + batch.unit + ' · ' + batch.snapshot.output_name));
    card.append(node('p', batch.snapshot.site_name + ' · Priority ' + batch.priority + (batch.pinned ? ' · Pinned' : '')));
    card.append(node('p', 'Proposed start ' + batch.proposed_start_date));
    card.append(node('p', batch.theoretical_ready_date ? 'Timing estimate ' + batch.theoretical_ready_date : 'Ready date unknown'));
    card.append(node('p', batch.forecast_ready_date ? 'Forecast ready ' + batch.forecast_ready_date : 'Delivery estimate pending checks'));
    if (batch.blockers.length) { const list = node('ul'); batch.blockers.forEach(reason => list.append(node('li', reason))); card.append(list); }
    if (batch.snapshot.timing_reason) card.append(node('p', batch.snapshot.timing_reason));
    const material = materialAssessment?.batches.find(row => row.batch_id === batch.id);
    if (material) {
      card.append(node('p', 'Materials observed ' + materialAssessment.observed_at));
      if (material.stale) card.append(node('p', 'Plan changed. Check materials again.'));
      else {
        card.append(node('p', material.material_start_date ? 'Materials available from ' + material.material_start_date : 'Material availability unresolved'));
        if (material.material_timing_estimate) card.append(node('p', 'Timing estimate with these materials ' + material.material_timing_estimate));
        (material.bindings || []).forEach(binding => {
          const fact = materialAssessment.observations.find(lot => lot.id === binding.inventory_item_id);
          if (fact) card.append(node('p', fact.name + ' · On hand observed: ' + fact.on_hand_quantity + ' ' + fact.unit));
        });
        const reasons = node('ul'); material.reasons.forEach(reason => reasons.append(node('li', reason))); card.append(reasons);
      }
    }
    if (canRecord && !['started', 'cancelled'].includes(batch.status)) {
      actionForm(card, batch, 'priority', 'Priority (0–100)', 'priority', 'number', batch.priority);
      actionForm(card, batch, 'pin', batch.pinned ? 'Unpin batch' : 'Pin batch');
      if (!batch.pinned) actionForm(card, batch, 'reschedule', 'New start date', 'start_date', 'date', batch.proposed_start_date);
      actionForm(card, batch, 'cancel', 'Cancel batch');
      const start = node('button', 'Start batch'); start.type = 'button'; start.disabled = !batch.can_start;
      if (!batch.can_start) start.title = batch.blockers.join('; ');
      start.addEventListener('click', async function () {
        start.disabled = true;
        try { await api('/api/core/planner/batches/' + batch.id + '/start', {expected_revision: batch.revision}, {'Idempotency-Key': 'planner-' + batch.id + '-' + batch.revision}); await loadBoard(); }
        catch (exc) { fail(exc); }
      }); card.append(start);
    }
    if (batch.execution_id) { const link = node('a', 'View started execution'); link.href = '/core/flows/batches/start?id=' + encodeURIComponent(batch.process_id) + '&execution_id=' + encodeURIComponent(batch.execution_id); card.append(link); }
    return card;
  }
  function range() {
    const selected = day(rangeForm.elements.date.value);
    let start = selected;
    let end = selected;
    if (rangeForm.elements.view.value === 'week') { start = add(selected, -((selected.getDay() + 6) % 7)); end = add(start, 6); }
    if (rangeForm.elements.view.value === 'month') { start = new Date(selected.getFullYear(), selected.getMonth(), 1, 12); end = new Date(selected.getFullYear(), selected.getMonth() + 1, 0, 12); }
    return {start, end};
  }
  async function loadBoard() {
    const requestNumber = ++boardRequest;
    try {
      const dates = range(); const [result, observed] = await Promise.all([api('/api/core/planner/batches?start=' + iso(dates.start) + '&end=' + iso(dates.end)), api('/api/core/planner/material-assessments')]);
      if (requestNumber !== boardRequest) return;
      materialAssessment = observed.assessment;
      const days = root.querySelector('[data-board-days]'); days.replaceChildren();
      root.querySelector('[data-board-title]').textContent = iso(dates.start) + ' – ' + iso(dates.end);
      root.querySelector('[data-board-empty]').hidden = result.batches.length !== 0;
      if (result.truncated) notice.textContent = 'Showing the first 1,000 batches. Choose a shorter period to see more.';
      for (let current = dates.start; current <= dates.end; current = add(current, 1)) {
        const key = iso(current); const section = node('section'); section.className = 'board-day';
        section.append(node('h3', current.toLocaleDateString(undefined, {weekday: 'short', day: 'numeric', month: 'short'})));
        result.batches.filter(batch => batch.proposed_start_date === key).forEach(batch => section.append(batchCard(batch)));
        days.append(section);
      }
    } catch (exc) { if (requestNumber === boardRequest) throw exc; }
  }
  function showSettings() {
    if (!settingForm) return;
    const workflow = workflows.find(row => row.id === settingForm.elements.output.value);
    const fieldset = root.querySelector('[data-step-timings]'); fieldset.replaceChildren(node('legend', 'Step durations and waiting time (minutes)'));
    if (!workflow) return;
    settingForm.elements.batch_quantity.value = workflow.setting?.batch_quantity || '';
    root.querySelector('[data-setting-help]').textContent = workflow.stale ? 'Workflow changed. Review all timings before saving.' : 'Quantity in ' + workflow.unit + '. Ready-date rules are included in the timing estimate.';
    workflow.steps.forEach(step => {
      const row = node('div'); row.className = 'board-step'; row.dataset.stepId = step.step_id; row.append(node('p', step.name));
      const saved = workflow.setting?.snapshot.steps.find(item => item.step_id === step.step_id);
      const duration = field(row, 'Duration (minutes)', 'duration_minutes', 'number', saved?.duration_minutes ?? '');
      const waiting = field(row, 'Waiting (minutes)', 'waiting_minutes', 'number', saved?.waiting_minutes ?? '');
      [duration, waiting].forEach(input => { input.min = '0'; input.max = '525600'; input.step = '1'; }); fieldset.append(row);
      (step.inputs || []).forEach((input, index) => {
        if (!input || input.source_output_id != null) return;
        const label = node('label', 'Exact raw lot for ' + (input.name || 'material') + ' (' + (input.quantity || '?') + ' ' + (input.unit || '?') + ')');
        const select = node('select'); select.dataset.materialStep = step.step_id; select.dataset.materialIndex = index;
        option(select, '', 'Select a lot');
        materialLots.filter(lot => lot.unit === input.unit).forEach(lot => option(select, lot.id, lot.name + ' · Lot ' + lot.id.slice(0, 8) + ' · ' + lot.unit));
        const binding = workflow.setting?.snapshot.material_bindings?.find(entry => entry.step_id === step.step_id && entry.input_index === index);
        if (binding) {
          if (!materialLots.some(lot => lot.id === binding.inventory_item_id && lot.unit === input.unit)) option(select, binding.inventory_item_id, 'Saved lot ' + binding.inventory_item_id.slice(0, 8));
          select.value = binding.inventory_item_id;
        }
        label.append(select); row.append(label);
      });
    });
  }
  async function loadInputs() {
    const [catalog, demands] = await Promise.all([api('/api/core/planner/workflows'), api('/api/core/planner/demands')]); workflows = catalog.workflows; materialLots = catalog.material_lots;
    if (catalog.material_lots_truncated) notice.textContent = 'Showing the first 500 raw lots. Existing bindings are retained when their lot is not listed.';
    if (settingForm) {
      const select = settingForm.elements.output; const selected = select.value; select.replaceChildren();
      workflows.forEach(row => option(select, row.id, row.name + ' · ' + row.process_name)); if (workflows.some(row => row.id === selected)) select.value = selected;
      showSettings();
    }
    if (planForm) {
      const select = planForm.elements.demand; const selectedDemand = select.value; const selectedSite = planForm.elements.site.value;
      select.replaceChildren(); demands.demands.filter(row => row.status === 'open').forEach(row => option(select, row.id, row.reference + ' · ' + row.quantity + ' ' + row.unit));
      if (demands.demands.some(row => row.id === selectedDemand && row.status === 'open')) select.value = selectedDemand;
      planForm.elements.site.replaceChildren(); option(planForm.elements.site, '', 'Main site'); catalog.sites.forEach(site => option(planForm.elements.site, site.id, site.name));
      if (catalog.sites.some(site => site.id === selectedSite)) planForm.elements.site.value = selectedSite;
    }
  }
  rangeForm.elements.date.value = iso(new Date());
  rangeForm.addEventListener('submit', event => { event.preventDefault(); error.hidden = true; loadBoard().catch(fail); });
  root.querySelector('[data-board-today]').addEventListener('click', () => { rangeForm.elements.date.value = iso(new Date()); loadBoard().catch(fail); });
  if (settingForm) {
    settingForm.elements.output.addEventListener('change', showSettings);
    settingForm.addEventListener('submit', async function (event) {
      event.preventDefault(); const button = settingForm.querySelector('button'); button.disabled = true; error.hidden = true;
      const workflow = workflows.find(row => row.id === settingForm.elements.output.value);
      if (!workflow) { button.disabled = false; return; }
      const steps = Array.from(root.querySelectorAll('[data-step-id]')).map(row => ({step_id: row.dataset.stepId, duration_minutes: Number(row.querySelector('[name="duration_minutes"]').value), waiting_minutes: Number(row.querySelector('[name="waiting_minutes"]').value)}));
      const material_lots = Array.from(root.querySelectorAll('[data-material-step]')).filter(select => select.value).map(select => ({step_id: select.dataset.materialStep, input_index: Number(select.dataset.materialIndex), inventory_item_id: select.value}));
      try { await api('/api/core/planner/workflows/' + workflow.process_id + '/settings', {source_output_id: workflow.id, batch_quantity: settingForm.elements.batch_quantity.value, steps, material_lots, expected_revision: workflow.setting?.revision || 0}); await loadInputs(); notice.textContent = 'Planning settings saved'; }
      catch (exc) { fail(exc); } finally { button.disabled = false; }
    });
  }
  if (planForm) planForm.addEventListener('submit', async function (event) {
    event.preventDefault(); const button = planForm.querySelector('button'); button.disabled = true; error.hidden = true;
    const body = {}; if (planForm.elements.site.value) body.site_id = planForm.elements.site.value;
    try { const result = await api('/api/core/planner/demands/' + planForm.elements.demand.value + '/plan', body); if (result.batches.length) rangeForm.elements.date.value = result.batches[0].proposed_start_date; await loadBoard(); notice.textContent = 'Batches planned; delivery estimate pending checks'; }
    catch (exc) { fail(exc); } finally { button.disabled = false; }
  });
  root.querySelector('[data-check-materials]')?.addEventListener('click', async function (event) {
    const button = event.currentTarget; button.disabled = true; error.hidden = true;
    try { await api('/api/core/planner/material-assessments', {}); await loadBoard(); notice.textContent = 'Materials observed. Refresh after stock changes; delivery and start checks remain pending.'; }
    catch (exc) { fail(exc); } finally { button.disabled = false; }
  });
  Promise.all([loadInputs(), loadBoard()]).catch(fail);
}());
