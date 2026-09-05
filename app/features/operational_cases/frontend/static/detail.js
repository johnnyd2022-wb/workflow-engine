/**
 * Case detail (/core/cases/<id>): state-appropriate action, source facts, resolution/
 * verification and timeline. LiveSync-refreshed; dirty forms are protected from being
 * silently overwritten (spec UX contract).
 */
(function () {
  'use strict';

  var caseId = null;
  var caseData = null;
  var formDirty = false;
  var timelineCursor = null;
  var timelineEvents = [];
  var pendingLiveRefresh = false;

  var CAUSE_OPTIONS = [
    ['data_entry', 'Data entry'],
    ['process_deviation', 'Process deviation'],
    ['equipment', 'Equipment'],
    ['material', 'Material'],
    ['unknown', 'Unknown'],
    ['other', 'Other'],
  ];

  function api() { return window.CoreAPI; }

  function fmtDate(iso) {
    if (!iso) return '—';
    try {
      var d = new Date(iso);
      if (Number.isNaN(d.getTime())) return '—';
      return d.toLocaleString();
    } catch (e) { return '—'; }
  }

  function setError(message) {
    var el = document.querySelector('[data-oc-error]');
    if (!el) return;
    el.hidden = !message;
    el.textContent = message || '';
  }

  function setConflict(show) {
    var el = document.querySelector('[data-oc-conflict]');
    if (el) el.hidden = !show;
  }

  function markDirty(isDirty) {
    formDirty = isDirty;
  }

  window.addEventListener('beforeunload', function (ev) {
    if (!formDirty) return;
    ev.preventDefault();
    ev.returnValue = '';
  });

  function statusLabel(status) {
    var labels = {
      open: 'Open', acknowledged: 'Acknowledged', in_progress: 'In progress',
      resolved: 'Resolved — awaiting verification', verified: 'Verified', dismissed: 'Dismissed'
    };
    return labels[status] || status;
  }

  function isOverdue(data) {
    var activeSet = ['open', 'acknowledged', 'in_progress', 'resolved'];
    if (activeSet.indexOf(data.status) === -1) return false;
    return new Date(data.due_at).getTime() < Date.now();
  }

  function renderHeader(data) {
    document.querySelector('[data-oc-status-badge]').textContent = statusLabel(data.status);
    document.querySelector('[data-oc-overdue-badge]').hidden = !isOverdue(data);
    document.querySelector('[data-oc-title]').textContent = data.title;
    document.querySelector('[data-oc-owner]').textContent = data.owner_email || data.owner_id;
    document.querySelector('[data-oc-due-utc]').textContent = data.due_at ? data.due_at.replace('+00:00', 'Z') : '—';
    document.querySelector('[data-oc-due-local]').textContent = fmtDate(data.due_at);
    document.querySelector('[data-oc-next-action]').textContent = data.next_action;
    var freshness = document.querySelector('[data-oc-freshness]');
    if (!data.owner_active) {
      freshness.textContent = 'Owner unavailable — reassign';
    } else {
      freshness.textContent = '';
    }
  }

  function renderSource(data) {
    var obs = document.querySelector('[data-oc-source-observation]');
    var state = data.source_observation && data.source_observation.state;
    var observedAt = data.source_observation && data.source_observation.observed_at;
    obs.textContent = 'Last known source state: ' + (state || 'unknown') + (observedAt ? ' (observed ' + fmtDate(observedAt) + ')' : '') + '.';

    var fields = document.querySelector('[data-oc-source-fields]');
    fields.innerHTML = '';
    var snap = data.source_snapshot || {};
    var nav = document.createElement('nav'); nav.setAttribute('aria-label', 'Correct source');
    [['Review stock', '/core/inventory/view?item_id=' + encodeURIComponent(snap.source_entity_id || '')],
     ['Trace source', '/core/sourcemap?show=check-needed'],
     ['Reconcile in process step', '/core/notifications?category=traceability']].forEach(function (entry) {
      var a = document.createElement('a'); a.textContent = entry[0]; a.href = entry[1]; a.setAttribute('hx-boost', 'false'); a.style.marginRight = '1rem'; nav.appendChild(a);
    });
    fields.appendChild(nav);
    if (state === 'deleted') { var recovery = document.createElement('p'); recovery.textContent = 'Source deleted. Restore it in its workspace or ask an administrator to dismiss this case with a reason.'; fields.appendChild(recovery); }
    var rows = [
      ['Item', snap.item_name],
      ['Quantity', snap.quantity + ' ' + (snap.unit || '')],
      ['Remaining balance to reconcile', snap.remaining_balance_to_reconcile],
      ['Observed at', snap.observed_at ? fmtDate(snap.observed_at) : null],
    ];
    rows.forEach(function (row) {
      if (row[1] == null || row[1] === '') return;
      var p = document.createElement('p');
      p.textContent = row[0] + ': ' + row[1];
      fields.appendChild(p);
    });
  }

  function clearActionForm() {
    var host = document.querySelector('[data-oc-action-form]');
    if (host) host.innerHTML = '';
    markDirty(false);
  }

  function utcIsoFromInputs(dateStr, timeStr) {
    if (!dateStr || !timeStr) return null;
    return dateStr + 'T' + timeStr + ':00.000Z';
  }

  function splitIsoToInputs(iso) {
    try {
      var d = new Date(iso);
      var pad = function (n) { return String(n).padStart(2, '0'); };
      return {
        date: d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()),
        time: pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()),
      };
    } catch (e) {
      return { date: '', time: '' };
    }
  }

  function buildFormShell(title) {

    var host = document.querySelector('[data-oc-action-form]');
    host.innerHTML = '';
    var wrap = document.createElement('section');
    wrap.className = 'oc-section';
    var h = document.createElement('h2');
    h.textContent = title;
    wrap.appendChild(h);
    var errorP = document.createElement('p');
    errorP.className = 'oc-form-error';
    errorP.hidden = true;
    wrap.appendChild(errorP);
    var form = document.createElement('form');
    form.className = 'oc-form';
    wrap.appendChild(form);
    host.appendChild(wrap);
    return { form: form, errorEl: errorP };
  }

  function fieldTextarea(form, name, label, required) {
    var l = document.createElement('label');
    l.textContent = label;
    l.htmlFor = 'oc-field-' + name;
    var t = document.createElement('textarea');
    t.id = 'oc-field-' + name;
    t.name = name;
    t.rows = 3;
    t.maxLength = 2000;
    if (required) t.required = true;
    t.addEventListener('input', function () { markDirty(true); });
    form.appendChild(l);
    form.appendChild(t);
    return t;
  }

  function submitButtons(form, label) {
    var actions = document.createElement('div');
    actions.className = 'oc-form-actions';
    var submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.className = 'oc-btn--primary';
    submitBtn.textContent = label;
    var cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', function () { if (!formDirty || window.confirm('Discard unsaved changes?')) clearActionForm(); });
    actions.appendChild(submitBtn);
    actions.appendChild(cancelBtn);
    form.appendChild(actions);
  }

  var commandPending = false;
  async function runCommand(fn, errorEl) {
    if (commandPending) return;
    commandPending = true;
    document.querySelectorAll('[data-oc-action-form] button').forEach(function (b) { b.disabled = true; });
    try {
      await fn();
      markDirty(false);
      await loadCase();
    } catch (e) {
      var body = e && e.body;
      if (body && body.error_code === 'stale_version') {
        setConflict(true);
        return;
      }
      errorEl.hidden = false;
      errorEl.textContent = (e && e.message) || 'That action could not be completed.';
    } finally { commandPending = false; document.querySelectorAll('[data-oc-action-form] button').forEach(function (b) { b.disabled = false; }); }
  }

  function renderEditForm() {
    var f = buildFormShell('Edit case');
    var dueParts = splitIsoToInputs(caseData.due_at);

    var ownerLabel = document.createElement('label');
    ownerLabel.textContent = 'Owner';
    var ownerSelect = document.createElement('select');
    ownerSelect.disabled = true; // enabled below only if reassign is permitted
    f.form.appendChild(ownerLabel);
    f.form.appendChild(ownerSelect);
    if ((caseData.permitted_actions || []).indexOf('reassign') !== -1) {
      ownerSelect.disabled = false;
      fetch('/org/users', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (data) {
        var users = (data && Array.isArray(data.users)) ? data.users : [];
        ownerSelect.innerHTML = '';
        users.filter(function (u) { return u.is_active; }).forEach(function (u) {
          var opt = document.createElement('option');
          opt.value = u.id;
          opt.textContent = u.display_name || u.email;
          if (u.id === caseData.owner_id) opt.selected = true;
          ownerSelect.appendChild(opt);
        });
      }).catch(function () {});
    } else {
      var opt = document.createElement('option');
      opt.textContent = caseData.owner_email || caseData.owner_id;
      ownerSelect.appendChild(opt);
    }
    ownerSelect.addEventListener('change', function () { markDirty(true); });

    var dateLabel = document.createElement('label');
    dateLabel.textContent = 'Due date (UTC)';
    var dateInput = document.createElement('input');
    dateInput.type = 'date'; dateInput.id = 'oc-edit-date'; dateLabel.htmlFor = dateInput.id;
    dateInput.value = dueParts.date;
    var timeLabel = document.createElement('label');
    timeLabel.textContent = 'Due time (UTC)';
    var timeInput = document.createElement('input');
    timeInput.type = 'time'; timeInput.id = 'oc-edit-time'; timeLabel.htmlFor = timeInput.id;
    timeInput.value = dueParts.time;
    [dateInput, timeInput].forEach(function (el) { el.addEventListener('input', function () { markDirty(true); }); });
    f.form.appendChild(dateLabel);
    f.form.appendChild(dateInput);
    f.form.appendChild(timeLabel);
    f.form.appendChild(timeInput);

    var nextAction = fieldTextarea(f.form, 'next_action', 'Next action', true);
    nextAction.value = caseData.next_action;

    submitButtons(f.form, 'Save changes');
    f.form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var fields = {};
      if (!ownerSelect.disabled && ownerSelect.value && ownerSelect.value !== caseData.owner_id) {
        fields.owner_id = ownerSelect.value;
      }
      var newDue = utcIsoFromInputs(dateInput.value, timeInput.value);
      if (newDue && new Date(newDue).getTime() !== new Date(caseData.due_at).getTime()) fields.due_at = newDue;
      if (nextAction.value.trim() !== caseData.next_action) fields.next_action = nextAction.value.trim();
      if (!Object.keys(fields).length) { clearActionForm(); return; }
      runCommand(function () { return api().patchCase(caseId, Object.assign({}, fields, { expected_version: caseData.version })); }, f.errorEl);
    });
  }

  function renderSimpleTransitionForm(action, targetStatus, label) {
    var f = buildFormShell(label);
    submitButtons(f.form, label);
    f.form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      runCommand(function () {
        return api().transitionCase(caseId, { target_status: targetStatus, expected_version: caseData.version });
      }, f.errorEl);
    });
  }

  function renderResolveForm() {
    var f = buildFormShell('Resolve case');
    var causeLabel = document.createElement('label');
    causeLabel.textContent = 'Cause';
    var causeSelect = document.createElement('select');
    causeSelect.required = true; causeSelect.id = 'oc-resolve-cause'; causeLabel.htmlFor = causeSelect.id;
    var placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select a cause';
    causeSelect.appendChild(placeholder);
    CAUSE_OPTIONS.forEach(function (pair) {
      var opt = document.createElement('option');
      opt.value = pair[0];
      opt.textContent = pair[1];
      causeSelect.appendChild(opt);
    });
    causeSelect.addEventListener('change', function () { markDirty(true); causeDetail.hidden = causeSelect.value !== 'other'; });
    f.form.appendChild(causeLabel);
    f.form.appendChild(causeSelect);

    var causeDetail = fieldTextarea(f.form, 'cause_detail', 'Explain "other"', false);
    causeDetail.hidden = true;

    var actionTaken = fieldTextarea(f.form, 'action_taken', 'Action taken', true);
    var outcome = fieldTextarea(f.form, 'outcome', 'Outcome', true);

    submitButtons(f.form, 'Record resolution');
    f.form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var payload = {
        target_status: 'resolved',
        expected_version: caseData.version,
        cause: causeSelect.value,
        action_taken: actionTaken.value.trim(),
        outcome: outcome.value.trim(),
      };
      if (causeSelect.value === 'other') payload.cause_detail = causeDetail.value.trim();
      runCommand(function () { return api().transitionCase(caseId, payload); }, f.errorEl);
    });
  }

  function renderNoteForm(title, fieldName, fieldLabel, targetStatus, buttonLabel) {
    var f = buildFormShell(title);
    var note = fieldTextarea(f.form, fieldName, fieldLabel, true);
    submitButtons(f.form, buttonLabel);
    f.form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var payload = { target_status: targetStatus, expected_version: caseData.version };
      payload[fieldName] = note.value.trim();
      runCommand(function () { return api().transitionCase(caseId, payload); }, f.errorEl);
    });
  }

  function renderRefreshSource() {
    runCommand(function () { return api().refreshCaseSource(caseId, caseData.version); }, { hidden: true });
  }

  function renderActionForm(action) {
    if (action === 'edit') return renderEditForm();
    if (action === 'acknowledge') return renderSimpleTransitionForm(action, 'acknowledged', 'Acknowledge case');
    if (action === 'start') return renderSimpleTransitionForm(action, 'in_progress', 'Start work');
    if (action === 'resolve') return renderResolveForm();
    if (action === 'verify') return renderNoteForm('Verify case', 'verification_note', 'Verification note', 'verified', 'Record verification');
    if (action === 'reopen') return renderNoteForm('Reopen case', 'reopen_reason', 'Reopen reason', 'in_progress', 'Reopen');
    if (action === 'dismiss') return renderNoteForm('Dismiss case', 'reason', 'Dismissal reason', 'dismissed', 'Dismiss');
    if (action === 'refresh_source') return renderRefreshSource();
  }

  var ACTION_LABELS = {
    edit: 'Edit', reassign: null, acknowledge: 'Acknowledge', start: 'Start work',
    resolve: 'Resolve', verify: 'Verify', reopen: 'Reopen', dismiss: 'Dismiss',
    refresh_source: 'Refresh source',
  };

  function renderActions(data) {
    var host = document.querySelector('[data-oc-actions]');
    host.innerHTML = '';
    (data.permitted_actions || []).forEach(function (action) {
      var label = ACTION_LABELS[action];
      if (!label) return; // 'reassign' folds into the Edit form, not its own button
      var btn = document.createElement('button');
      btn.type = 'button';
      if (action === 'dismiss') btn.className = 'oc-btn--danger';
      btn.textContent = label;
      btn.addEventListener('click', function () { if (!formDirty || window.confirm('Discard unsaved changes?')) { clearActionForm(); renderActionForm(action); } });
      host.appendChild(btn);
    });
  }

  function renderTimelineEvent(evt) {
    var li = document.createElement('li');
    var time = document.createElement('time');
    time.textContent = fmtDate(evt.occurred_at);
    var type = document.createElement('div');
    type.className = 'oc-timeline__type';
    type.textContent = evt.event_type.replace('operational_case.', '').replaceAll('_', ' ') + (evt.actor_label ? ' — ' + evt.actor_label : '');
    li.appendChild(time);
    li.appendChild(type);
    var payload = evt.payload || {};
    ['cause', 'cause_detail', 'action_taken', 'outcome', 'verification_note', 'reason', 'reopen_reason', 'recurrence_reason', 'source_state'].forEach(function (key) {
      if (payload[key]) { var p = document.createElement('p'); p.textContent = key.replaceAll('_', ' ') + ': ' + payload[key]; li.appendChild(p); }
    });
    if (payload.changes) Object.keys(payload.changes).forEach(function (key) {
      var p = document.createElement('p'); var change = payload.changes[key];
      p.textContent = key.replaceAll('_', ' ') + ': ' + change.from + ' → ' + change.to; li.appendChild(p);
    });
    (payload.evidence_refs || []).forEach(function (ref) {
      var a = document.createElement('a'); a.textContent = 'View evidence';
      a.href = ref.entity_type === 'execution_evidence' ? '/api/core/evidence/' + encodeURIComponent(ref.entity_id) + '/download' : ref.entity_type === 'execution' ? '/core/flows?execution_id=' + encodeURIComponent(ref.entity_id) : '/core/inventory/view?item_id=' + encodeURIComponent(ref.entity_id);
      a.setAttribute('hx-boost', 'false'); li.appendChild(a);
    });
    return li;
  }

  async function loadTimeline(reset) {
    if (reset) { timelineEvents = []; timelineCursor = null; }
    var params = {};
    if (!reset && timelineCursor) params.before_version = timelineCursor;
    var data = await api().getCaseEvents(caseId, params);
    var events = (data && Array.isArray(data.events)) ? data.events : [];
    timelineEvents = reset ? events : timelineEvents.concat(events);
    timelineCursor = data && data.next_cursor;
    var list = document.querySelector('[data-oc-timeline]');
    list.innerHTML = '';
    timelineEvents.forEach(function (evt) { list.appendChild(renderTimelineEvent(evt)); });
    var pagination = document.querySelector('[data-oc-timeline-pagination]');
    if (pagination) pagination.hidden = !timelineCursor;
  }

  async function loadCase(preserveForm) {
    setError(null);
    setConflict(false);
    try {
      caseData = await api().getCase(caseId);
      document.querySelector('[data-oc-loading]').hidden = true;
      document.querySelector('[data-oc-content]').hidden = false;
      renderHeader(caseData);
      renderSource(caseData);
      renderActions(caseData);
      if (!preserveForm) clearActionForm();
      if (document.querySelector('[data-oc-timeline-details]').open) await loadTimeline(true);
      if (pendingLiveRefresh) {
        pendingLiveRefresh = false;
        if (typeof window.liveSyncFlash === 'function') window.liveSyncFlash('Case updated');
      }
    } catch (e) {
      setError((e && e.message) || 'Could not load this case.');
    }
  }

  function bindReloadLatest() {
    var btn = document.querySelector('[data-oc-reload-latest]');
    if (btn) btn.addEventListener('click', function () { loadCase(true); });
  }

  function bindTimelinePagination() {
    var btn = document.querySelector('[data-oc-timeline-load-more]');
    if (btn) btn.addEventListener('click', function () { loadTimeline(false); });
  }

  function bindLiveSync() {
    if (!window.LiveSync) return;
    window.LiveSync.subscribe({
      key: 'operational-case-detail-' + caseId,
      match: function (evt) {
        return evt.entity_type === 'operational_case' && evt.keys && evt.keys.case_id === caseId;
      },
      onChange: function () {
        if (document.hidden || !document.querySelector('[data-oc-detail-root]')) return;
        if (formDirty) {
          setConflict(true);
          return;
        }
        pendingLiveRefresh = true;
        loadCase();
      },
    });
  }

  function init() {
    var history = document.querySelector('[data-oc-timeline-details]');
    if (history) history.addEventListener('toggle', function () { if (history.open) loadTimeline(true).catch(function (e) { setError(e.message); }); });
    document.addEventListener('visibilitychange', function () { if (!document.hidden && caseId && !formDirty) loadCase(); });
    var root = document.querySelector('[data-oc-detail-root]');
    if (!root) return;
    caseId = root.getAttribute('data-case-id');
    var back = document.querySelector('[data-oc-back]');
    var returnTo = new URLSearchParams(location.search).get('return_to');
    if (back && returnTo && /^\/core\/cases(?:\?|$)/.test(returnTo) && !returnTo.includes('\\')) back.href = returnTo;
    bindReloadLatest();
    bindTimelinePagination();
    bindLiveSync();
    loadCase();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
