(function () {
  'use strict';
  const batchDragType = 'application/x-bize-planned-batch';
  const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

  function init(root) {
    const canRecord = root.dataset.canRecord === 'true';
    const error = root.querySelector('[data-board-error]');
    const notice = root.querySelector('[data-board-notice]');
    const rangeForm = root.querySelector('[data-board-range]');
    const settingForm = root.querySelector('[data-setting-form]');
    const planForm = root.querySelector('[data-plan-form]');
    let workflows = [];
    let materialLots = [];
    let materialAssessment = null;
    let capacityReview = null;
    let lastBoard = null;
    let boardRequest = 0;
    let draggedBatch = null;
    let dragPending = false;
    let alive = true;
    // A card's details stay open across re-renders, so acting on a batch does not close it.
    const openCards = new Set();

    function node(tag, text, className) {
      const element = document.createElement(tag);
      if (text !== undefined && text !== null) element.textContent = text;
      if (className) element.className = className;
      return element;
    }
    function iso(value) { return value.getFullYear() + '-' + String(value.getMonth() + 1).padStart(2, '0') + '-' + String(value.getDate()).padStart(2, '0'); }
    function day(value) { const parts = value.split('-').map(Number); return new Date(parts[0], parts[1] - 1, parts[2], 12); }
    function add(value, offset) { const result = new Date(value); result.setDate(result.getDate() + offset); return result; }
    function short(value, options) { return day(value).toLocaleDateString(undefined, options || {weekday: 'short', day: 'numeric', month: 'short'}); }
    // Quantities arrive as fixed-point strings ("40.0000"); show what a person would write.
    function amount(value) { const number = Number(value); return Number.isFinite(number) ? String(Number(number.toFixed(4))) : String(value); }
    function plural(count, one, many) { return count + ' ' + (count === 1 ? one : many); }
    function fail(exc) { error.textContent = exc.message || 'Unable to update the plan'; error.hidden = false; }
    async function api(path, body, extraHeaders) {
      const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', headers: Object.assign({'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || ''}, extraHeaders || {}), body: body === undefined ? undefined : JSON.stringify(body)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Unable to update the plan');
      return result;
    }
    function option(select, value, text) { const element = node('option', text); element.value = value; select.append(element); }
    function field(form, text, name, type, value) { const label = node('label', text); const input = node('input'); input.type = type; input.name = name; input.value = value; input.required = true; label.append(input); form.append(label); return input; }

    function clearDrag() {
      draggedBatch = null;
      root.querySelectorAll('.board-drop-target').forEach(section => section.classList.remove('board-drop-target'));
    }
    function dragHandle(batch) {
      const handle = node('button', '⠿', 'board-drag-handle');
      handle.type = 'button'; handle.draggable = true;
      handle.setAttribute('aria-label', 'Drag to move');
      handle.title = 'Drag to a day, or open the details to choose a new start date';
      handle.addEventListener('dragstart', function (event) {
        if (dragPending || !event.dataTransfer) { event.preventDefault(); return; }
        draggedBatch = batch;
        event.dataTransfer.setData(batchDragType, batch.id);
        event.dataTransfer.effectAllowed = 'move';
      });
      handle.addEventListener('dragend', clearDrag);
      handle.addEventListener('click', function () { focusStartDate(handle.closest('[data-batch-id]')); });
      return handle;
    }
    function focusStartDate(card) {
      const details = card?.querySelector('.board-batch__details');
      if (details && !details.open) { details.open = true; openCards.add(card.dataset.batchId); }
      const input = card?.querySelector('[name="start_date"]');
      if (input) { input.scrollIntoView({block: 'center'}); input.focus(); }
      return input;
    }
    function dropDay(section, date) {
      section.dataset.boardDate = date;
      if (!canRecord) return;
      section.addEventListener('dragover', function (event) {
        if (!draggedBatch || dragPending || draggedBatch.proposed_start_date === date) return;
        event.preventDefault(); event.dataTransfer.dropEffect = 'move';
        section.classList.add('board-drop-target');
      });
      section.addEventListener('dragleave', function (event) {
        if (!section.contains(event.relatedTarget)) section.classList.remove('board-drop-target');
      });
      section.addEventListener('drop', async function (event) {
        const batch = draggedBatch;
        if (!batch || dragPending || !event.dataTransfer || event.dataTransfer.getData(batchDragType) !== batch.id) return;
        event.preventDefault(); clearDrag();
        if (batch.proposed_start_date === date) return;
        dragPending = true; error.hidden = true;
        try {
          await api('/api/core/planner/batches/' + batch.id + '/action', {action: 'reschedule', expected_revision: batch.revision, start_date: date});
          await loadBoard(); notice.textContent = 'Batch moved to ' + date;
        } catch (exc) {
          fail(exc);
          // A pin, cancellation or concurrent edit may have made this card stale.
          try { await loadBoard(); } catch (reloadError) { fail(reloadError); }
        } finally { dragPending = false; }
      });
    }
    function actionForm(parent, batch, action, label, name, type, value) {
      const form = node('form', undefined, 'board-batch__form board-batch__form--' + action); form.setAttribute('hx-boost', 'false');
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
      });
      parent.append(form);
      return form;
    }
    function state(batch) {
      if (batch.status === 'started') return {key: 'started', text: 'Started'};
      if (batch.status === 'cancelled') return {key: 'cancelled', text: 'Cancelled'};
      if (batch.can_start) return {key: 'ready', text: 'Ready to start'};
      const count = batch.blockers.length;
      return {key: 'blocked', text: count ? plural(count, 'check', 'checks') + ' to clear' : 'Not ready'};
    }
    function startButton(batch) {
      const start = node('button', 'Start batch', 'board-batch__start'); start.type = 'button'; start.disabled = !batch.can_start;
      if (!batch.can_start) start.title = batch.blockers.join('; ');
      start.addEventListener('click', async function () {
        start.disabled = true;
        try { await api('/api/core/planner/batches/' + batch.id + '/start', {expected_revision: batch.revision}, {'Idempotency-Key': 'planner-' + batch.id + '-' + batch.revision}); await loadBoard(); }
        catch (exc) { fail(exc); }
      });
      return start;
    }
    function batchCard(batch) {
      const live = !['started', 'cancelled'].includes(batch.status);
      const card = node('article', undefined, 'board-batch'); card.dataset.batchId = batch.id;
      const current = state(batch); card.dataset.state = current.key;
      if (batch.pinned) card.dataset.pinned = 'true';
      const top = node('div', undefined, 'board-batch__top');
      if (canRecord && live && !batch.pinned) top.append(dragHandle(batch));
      top.append(node('span', '', 'board-batch__spacer'));
      if (canRecord && live) {
        const pin = actionForm(top, batch, 'pin', batch.pinned ? 'Unpin batch' : 'Pin batch');
        const button = pin.querySelector('button');
        button.textContent = batch.pinned ? 'Pinned' : 'Pin';
        button.setAttribute('aria-label', batch.pinned ? 'Unpin batch' : 'Pin batch');
        button.setAttribute('aria-pressed', batch.pinned ? 'true' : 'false');
        button.title = batch.pinned ? 'Pinned: the planner will not move it. Select to unpin.' : 'Pin to keep it on this day';
      } else if (batch.pinned) top.append(node('span', 'Pinned', 'board-batch__pinned'));
      card.append(top);
      card.append(node('h4', batch.snapshot.demand_reference + ' · Batch ' + batch.batch_number));
      card.append(node('p', current.text, 'board-batch__state'));
      card.append(node('p', amount(batch.quantity) + ' ' + batch.unit + ' · ' + batch.snapshot.output_name, 'board-batch__what'));
      card.append(node('p', batch.snapshot.site_name + ' · Priority ' + batch.priority + (batch.pinned ? ' · Pinned' : ''), 'board-batch__meta'));
      if (canRecord && live && batch.can_start) card.append(startButton(batch));
      if (batch.execution_id) { const link = node('a', 'View started execution', 'board-batch__link'); link.href = '/core/flows/batches/start?id=' + encodeURIComponent(batch.process_id) + '&execution_id=' + encodeURIComponent(batch.execution_id); card.append(link); }

      const details = node('details', undefined, 'board-batch__details');
      details.open = openCards.has(batch.id);
      details.addEventListener('toggle', () => { if (details.open) openCards.add(batch.id); else openCards.delete(batch.id); });
      details.append(node('summary', 'Details'));
      const body = node('div', undefined, 'board-batch__body');
      body.append(node('p', 'Proposed start ' + batch.proposed_start_date));
      body.append(node('p', batch.theoretical_ready_date ? 'Timing estimate ' + batch.theoretical_ready_date : 'Ready date unknown'));
      body.append(node('p', batch.forecast_ready_date ? 'Forecast ready ' + batch.forecast_ready_date : 'Delivery estimate pending checks'));
      if (batch.blockers.length) { const list = node('ul', undefined, 'board-batch__blockers'); batch.blockers.forEach(reason => list.append(node('li', reason))); body.append(list); }
      if (batch.snapshot.timing_reason) body.append(node('p', batch.snapshot.timing_reason));
      const material = materialAssessment?.batches.find(row => row.batch_id === batch.id);
      if (material) {
        body.append(node('p', 'Materials observed ' + materialAssessment.observed_at));
        if (material.stale) body.append(node('p', 'Plan changed. Check materials again.'));
        else {
          body.append(node('p', material.material_start_date ? 'Materials available from ' + material.material_start_date : 'Material availability unresolved'));
          if (material.material_timing_estimate) body.append(node('p', 'Timing estimate with these materials ' + material.material_timing_estimate));
          (material.bindings || []).forEach(binding => {
            const fact = materialAssessment.observations.find(lot => lot.id === binding.inventory_item_id);
            if (fact) body.append(node('p', fact.name + ' · On hand observed: ' + fact.on_hand_quantity + ' ' + fact.unit));
          });
          const reasons = node('ul'); material.reasons.forEach(reason => reasons.append(node('li', reason))); body.append(reasons);
        }
      }
      if (canRecord && live) {
        const actions = node('div', undefined, 'board-batch__actions');
        actionForm(actions, batch, 'priority', 'Priority (0–100)', 'priority', 'number', batch.priority);
        if (!batch.pinned) actionForm(actions, batch, 'reschedule', 'New start date', 'start_date', 'date', batch.proposed_start_date);
        if (!batch.can_start) actions.append(startButton(batch));
        actionForm(actions, batch, 'cancel', 'Cancel batch');
        body.append(actions);
      }
      details.append(body);
      card.append(details);
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
    function rangeTitle(dates) {
      const view = rangeForm.elements.view.value;
      if (view === 'day') return dates.start.toLocaleDateString(undefined, {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'});
      if (view === 'month') return dates.start.toLocaleDateString(undefined, {month: 'long', year: 'numeric'});
      const sameMonth = dates.start.getMonth() === dates.end.getMonth();
      return dates.start.toLocaleDateString(undefined, sameMonth ? {day: 'numeric'} : {day: 'numeric', month: 'short'}) + ' – ' +
        dates.end.toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'});
    }
    function batchName(id) {
      const batch = lastBoard?.result.batches.find(row => row.id === id);
      return batch ? batch.snapshot.demand_reference + ' · Batch ' + batch.batch_number : 'batch ' + id.slice(0, 8);
    }
    function renderCapacity() {
      if (!capacityReview) return;
      const output = root.querySelector('[data-capacity-results]'); output.replaceChildren();
      const overloads = capacityReview.days.filter(row => row.overloaded);
      root.dataset.overloads = String(overloads.length);
      output.append(node('p', overloads.length ? overloads.length + ' overloaded resource-day(s) in this view.' : 'No overload in configured groups for this view. Unassigned work may still exist.', 'board-capacity__summary'));
      const list = node('ul', undefined, 'board-capacity__list');
      overloads.forEach(row => {
        const item = node('li');
        item.append(node('strong', short(row.day) + ' · ' + row.group_name));
        item.append(node('span', row.load_minutes + '/' + row.capacity_minutes + ' minutes' + (row.calendar_closed ? ' · resource closed' : ''), 'board-capacity__load'));
        item.append(node('span', row.suggest_move_batch_id ? 'Consider moving ' + batchName(row.suggest_move_batch_id) : 'All affected batches pinned', 'board-capacity__hint'));
        if (canRecord && row.suggest_move_batch_id) {
          const button = node('button', 'Review and move suggested batch'); button.type = 'button'; button.className = 'workspace-button';
          button.addEventListener('click', async function () {
            button.disabled = true; error.hidden = true;
            function findCard() { return Array.from(root.querySelectorAll('[data-batch-id]')).find(card => card.dataset.batchId === row.suggest_move_batch_id); }
            try {
              let card = findCard();
              if (!card) {
                rangeForm.elements.date.value = row.suggest_move_start_date;
                rangeForm.elements.view.value = 'day';
                await loadBoard(); card = findCard();
              }
              if (!focusStartDate(card)) { notice.textContent = 'This batch can no longer be moved. Review its current state on the board.'; return; }
              notice.textContent = 'Choose a new start date, then move the suggested batch.';
            } catch (exc) { fail(exc); }
            finally { button.disabled = false; }
          });
          item.append(button);
        }
        list.append(item);
      });
      if (overloads.length) output.append(list);
      if (capacityReview.unresolved.length) output.append(node('p', capacityReview.unresolved.length + ' batch(es) have incomplete capacity assignments or timing; no clearance can be inferred.', 'board-capacity__note'));
    }
    function currentCapacity() {
      const site = root.querySelector('[data-capacity-site]')?.value;
      return capacityReview?.settings.find(row => row.site_id === site) || {site_id: site, revision: 0, groups: [], assignments: []};
    }
    function showCapacitySettings() {
      const select = root.querySelector('[data-capacity-site]');
      if (!select || !capacityReview) return;
      const selected = select.value; select.replaceChildren();
      capacityReview.sites.forEach(site => option(select, site.id, site.name));
      if (capacityReview.sites.some(site => site.id === selected)) select.value = selected;
      const config = currentCapacity();
      const list = root.querySelector('[data-capacity-groups]'); list.replaceChildren();
      config.groups.forEach(group => {
        list.append(node('p', group.name + ' · ' + group.minutes_per_day + ' minutes per working day'));
        const form = node('form'); form.setAttribute('hx-boost', 'false'); form.dataset.capacityCalendar = group.id;
        const days = node('fieldset', undefined, 'board-calendar-days'); days.append(node('legend', group.name + ' working days'));
        DAY_NAMES.forEach((name, index) => {
          const label = node('label'); const input = node('input'); input.type = 'checkbox'; input.name = 'working_days'; input.value = index;
          input.checked = (group.working_days || [0, 1, 2, 3, 4, 5, 6]).includes(index); label.append(input, node('span', name)); days.append(label);
        });
        form.append(days);
        const label = node('label', 'Closed dates, one per line (YYYY-MM-DD)'); const dates = node('textarea');
        dates.name = 'closed_dates'; dates.rows = 3; dates.value = (group.closed_dates || []).join('\n'); label.append(dates); form.append(label);
        const button = node('button', 'Save calendar', 'workspace-button'); button.type = 'submit'; form.append(button);
        form.addEventListener('submit', async function (event) {
          event.preventDefault(); button.disabled = true; error.hidden = true; notice.textContent = '';
          const updated = {...group, working_days: Array.from(form.querySelectorAll('[name="working_days"]:checked'), input => Number(input.value)), closed_dates: dates.value.trim() ? dates.value.trim().split(/\s+/) : []};
          try {
            await saveCapacity({...config, groups: config.groups.map(item => item.id === group.id ? updated : item)});
            notice.textContent = 'Resource calendar saved';
          } catch (exc) { fail(exc); button.disabled = false; }
        });
        list.append(form);
      });
      const steps = root.querySelector('[data-capacity-step]'); const priorStep = steps.value; steps.replaceChildren();
      workflows.forEach(workflow => workflow.steps.forEach(step => option(steps, step.step_id, workflow.process_name + ' · ' + step.name)));
      if (Array.from(steps.options).some(item => item.value === priorStep)) steps.value = priorStep;
      const groups = root.querySelector('[data-capacity-group]'); groups.replaceChildren();
      config.groups.forEach(group => option(groups, group.id, group.name));
    }
    async function saveCapacity(config) {
      const result = await api('/api/core/planner/capacity/sites/' + config.site_id, {groups: config.groups, assignments: config.assignments, expected_revision: config.revision});
      const old = capacityReview.settings.findIndex(row => row.site_id === config.site_id);
      if (old < 0) capacityReview.settings.push(result.setting); else capacityReview.settings[old] = result.setting;
      showCapacitySettings(); await loadBoard();
    }
    function daysOf(dates) {
      const keys = [];
      for (let current = dates.start; current <= dates.end; current = add(current, 1)) keys.push({key: iso(current), date: current});
      return keys;
    }
    function dayHeading(entry) {
      const today = iso(new Date()) === entry.key;
      const heading = node('h3', entry.date.toLocaleDateString(undefined, {weekday: 'short', day: 'numeric', month: 'short'}));
      if (today) { heading.append(node('span', 'Today', 'board-day__today')); }
      return heading;
    }
    function renderFigures(batches) {
      const ready = batches.filter(batch => batch.can_start && batch.status !== 'started').length;
      const blocked = batches.filter(batch => !batch.can_start && !['started', 'cancelled'].includes(batch.status)).length;
      const overloads = Number(root.dataset.overloads || 0);
      const set = (name, value) => { const el = root.querySelector('[data-figure="' + name + '"]'); if (el) el.textContent = String(value); };
      set('batches', batches.length); set('ready', ready); set('blocked', blocked); set('overloaded', overloads);
      root.querySelector('[data-figure-tile="overloaded"]').dataset.state = overloads ? 'alert' : '';
      root.querySelector('[data-figure-tile="ready"]').dataset.state = ready ? 'good' : '';
      root.querySelector('[data-board-count]').textContent = '';
      root.querySelector('.board-figures').hidden = !batches.length;
    }
    function renderDays() {
      if (!lastBoard) return;
      const {dates, result} = lastBoard;
      const days = root.querySelector('[data-board-days]'); days.replaceChildren();
      const view = rangeForm.elements.view.value;
      days.dataset.view = view;
      // A week whose weekend has nothing planned gives those two days less room.
      const weekendBusy = result.batches.some(batch => [0, 6].includes(day(batch.proposed_start_date).getDay()));
      days.dataset.weekend = weekendBusy ? 'busy' : 'quiet';
      root.querySelector('[data-board-empty]').hidden = result.batches.length !== 0;
      const entries = daysOf(dates);
      entries.forEach(entry => {
        const section = node('section', undefined, 'board-day');
        const todays = result.batches.filter(batch => batch.proposed_start_date === entry.key);
        section.dataset.count = String(todays.length);
        const weekday = (entry.date.getDay() + 6) % 7;
        if (weekday >= 5) section.dataset.weekend = 'true';
        if (iso(new Date()) === entry.key) section.dataset.today = 'true';
        if (view === 'month' && entry === entries[0]) section.style.gridColumnStart = String(weekday + 1);
        dropDay(section, entry.key);
        section.append(dayHeading(entry));
        const list = node('div', undefined, 'board-day__batches');
        todays.forEach(batch => list.append(batchCard(batch)));
        if (!todays.length) list.append(node('p', 'No batches', 'board-day__empty'));
        section.append(list);
        days.append(section);
      });
    }
    async function loadBoard() {
      const requestNumber = ++boardRequest;
      try {
        const dates = range(); const [result, observed, capacity] = await Promise.all([api('/api/core/planner/batches?start=' + iso(dates.start) + '&end=' + iso(dates.end)), api('/api/core/planner/material-assessments'), api('/api/core/planner/capacity?start=' + iso(dates.start) + '&end=' + iso(dates.end))]);
        if (requestNumber !== boardRequest || !alive) return;
        materialAssessment = observed.assessment;
        lastBoard = {dates, result};
        capacityReview = capacity; renderCapacity(); showCapacitySettings();
        clearDrag();
        const title = root.querySelector('[data-board-title]');
        title.textContent = rangeTitle(dates);
        title.dataset.start = iso(dates.start); title.dataset.end = iso(dates.end);
        if (result.truncated) notice.textContent = 'Showing the first 1,000 batches. Choose a shorter period to see more.';
        renderFigures(result.batches);
        renderDays();
        root.dataset.state = 'ready';
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
        const row = node('div', undefined, 'board-step'); row.dataset.stepId = step.step_id; row.append(node('p', step.name));
        const saved = workflow.setting?.snapshot.steps.find(item => item.step_id === step.step_id);
        // A newly timed workflow supplies the defaults. When its timing changes, show the
        // new workflow value instead of silently resaving an older planning snapshot.
        const workflowTimingChanged = workflow.stale && saved && (
          (step.duration_minutes != null && step.duration_minutes !== saved.duration_minutes) ||
          (step.wait_minutes != null && step.wait_minutes !== saved.waiting_minutes)
        );
        const durationValue = workflowTimingChanged ? step.duration_minutes : saved?.duration_minutes ?? step.duration_minutes;
        const waitingValue = workflowTimingChanged ? step.wait_minutes : saved?.waiting_minutes ?? step.wait_minutes;
        const duration = field(row, 'Duration (minutes)', 'duration_minutes', 'number', durationValue ?? '');
        const waiting = field(row, 'Waiting (minutes)', 'waiting_minutes', 'number', waitingValue ?? '');
        [duration, waiting].forEach(input => { input.min = '0'; input.max = '525600'; input.step = '1'; input.required = true; }); fieldset.append(row);
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
      const [catalog, demands] = await Promise.all([api('/api/core/planner/workflows'), api('/api/core/planner/demands')]);
      if (!alive) return;
      workflows = catalog.workflows; materialLots = catalog.material_lots;
      if (catalog.material_lots_truncated) notice.textContent = 'Showing the first 500 raw lots. Existing bindings are retained when their lot is not listed.';
      if (settingForm) {
        const select = settingForm.elements.output; const selected = select.value; select.replaceChildren();
        workflows.forEach(row => option(select, row.id, row.name + ' · ' + row.process_name)); if (workflows.some(row => row.id === selected)) select.value = selected;
        showSettings(); showCapacitySettings();
      }
      if (planForm) {
        const select = planForm.elements.demand; const selectedDemand = select.value; const selectedSite = planForm.elements.site.value;
        select.replaceChildren();
        demands.demands.filter(row => row.status === 'open').forEach(row => option(select, row.id, row.reference + ' · ' + amount(row.quantity) + ' ' + row.unit));
        if (demands.demands.some(row => row.id === selectedDemand && row.status === 'open')) select.value = selectedDemand;
        planForm.elements.site.replaceChildren(); option(planForm.elements.site, '', 'Main site'); catalog.sites.forEach(site => option(planForm.elements.site, site.id, site.name));
        if (catalog.sites.some(site => site.id === selectedSite)) planForm.elements.site.value = selectedSite;
        // One site has nothing to choose between.
        root.querySelector('[data-plan-site-field]').hidden = planForm.elements.site.options.length < 2;
      }
    }
    function show() { error.hidden = true; loadBoard().catch(fail); }
    function step(direction) {
      const view = rangeForm.elements.view.value;
      const selected = day(rangeForm.elements.date.value || iso(new Date()));
      let next;
      if (view === 'month') next = new Date(selected.getFullYear(), selected.getMonth() + direction, 1, 12);
      else next = add(selected, direction * (view === 'week' ? 7 : 1));
      rangeForm.elements.date.value = iso(next); show();
    }

    root.querySelector('[data-capacity-site]')?.addEventListener('change', showCapacitySettings);
    root.querySelector('[data-capacity-group-form]')?.addEventListener('submit', async function (event) {
      event.preventDefault(); error.hidden = true;
      const form = event.currentTarget; const button = form.querySelector('button'); button.disabled = true;
      const config = currentCapacity();
      try {
        await saveCapacity({...config, groups: config.groups.concat([{id: crypto.randomUUID(), name: form.elements.name.value, minutes_per_day: Number(form.elements.minutes_per_day.value)}])});
        form.elements.name.value = ''; form.elements.minutes_per_day.value = '';
        notice.textContent = 'Resource group saved; assign steps to include their load.';
      } catch (exc) { fail(exc); } finally { button.disabled = false; }
    });
    root.querySelector('[data-capacity-assignment-form]')?.addEventListener('submit', async function (event) {
      event.preventDefault(); error.hidden = true;
      const form = event.currentTarget; const button = form.querySelector('button'); button.disabled = true;
      const config = currentCapacity(); const stepId = form.elements.step_id.value;
      try {
        await saveCapacity({...config, assignments: config.assignments.filter(row => row.step_id !== stepId).concat([{step_id: stepId, group_id: form.elements.group_id.value}])});
        notice.textContent = 'Step resource assignment saved; observed load refreshed.';
      } catch (exc) { fail(exc); } finally { button.disabled = false; }
    });
    rangeForm.elements.date.value = iso(new Date());
    rangeForm.addEventListener('submit', event => { event.preventDefault(); show(); });
    rangeForm.elements.view.addEventListener('change', show);
    root.querySelector('[data-board-today]').addEventListener('click', () => { rangeForm.elements.date.value = iso(new Date()); show(); });
    root.querySelectorAll('[data-board-step]').forEach(button => button.addEventListener('click', () => step(Number(button.dataset.boardStep))));
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
    return function () { alive = false; boardRequest += 1; };
  }

  if (window.bize && window.bize.onPage) window.bize.onPage('[data-board-root]', init);
}());
