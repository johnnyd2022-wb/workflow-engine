/**
 * Create-case form (/core/cases/new?source_entity_id=...). Reached from Notifications'
 * "Create case" action. Explicit UTC due date/time inputs with a local-time preview
 * (spec: "labelled in the form, shown with local-time equivalent").
 */
(function () {
  'use strict';

  var dirty = false; var submitting = false;
  window.addEventListener('beforeunload', function (e) { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  function qs(name) {
    try { return new URLSearchParams(window.location.search || '').get(name); } catch (e) { return null; }
  }

  function pad(n) { return String(n).padStart(2, '0'); }

  function utcIsoFromInputs(dateStr, timeStr) {
    if (!dateStr || !timeStr) return null;
    return dateStr + 'T' + timeStr + ':00.000Z';
  }

  function updateLocalPreview() {
    var dateEl = document.getElementById('oc-new-due-date');
    var timeEl = document.getElementById('oc-new-due-time');
    var preview = document.querySelector('[data-oc-new-local-preview]');
    if (!dateEl || !timeEl || !preview) return;
    var iso = utcIsoFromInputs(dateEl.value, timeEl.value);
    if (!iso) { preview.textContent = ''; return; }
    var d = new Date(iso);
    if (Number.isNaN(d.getTime())) { preview.textContent = ''; return; }
    preview.textContent = 'Local time: ' + d.toLocaleString();
  }

  async function loadOwners(selectEl) {
    try {
      var res = await fetch('/org/users', { method: 'GET', credentials: 'same-origin' });
      var data = await res.json();
      var users = (data && Array.isArray(data.users)) ? data.users : (Array.isArray(data) ? data : []);
      selectEl.innerHTML = '';
      var placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = 'Choose an owner';
      selectEl.appendChild(placeholder);
      users.filter(function (u) { return u.is_active; }).forEach(function (u) {
        var opt = document.createElement('option');
        opt.value = u.id;
        opt.textContent = u.display_name || u.email;
        selectEl.appendChild(opt);
      });
    } catch (e) {
      selectEl.innerHTML = '<option value="">Could not load organisation members</option>';
    }
  }

  function setError(message) {
    var el = document.querySelector('[data-oc-new-error]');
    if (!el) return;
    el.hidden = !message;
    el.textContent = message || '';
  }

  function showRecurrencePrompt(previousCase, onConfirm) {
    var el = document.querySelector('[data-oc-new-recurrence]');
    if (!el) return;
    el.hidden = false;
    el.innerHTML = '';
    var p = document.createElement('p');
    p.textContent = 'This item was previously closed as "' + (previousCase && previousCase.status) +
      '". Create a new occurrence instead?';
    el.appendChild(p);
    var reasonLabel = document.createElement('label');
    reasonLabel.textContent = 'Recurrence reason'; reasonLabel.htmlFor = 'oc-recurrence-reason';
    var reasonInput = document.createElement('textarea');
    reasonInput.rows = 2; reasonInput.id = 'oc-recurrence-reason';
    reasonInput.maxLength = 2000;
    el.appendChild(reasonLabel);
    el.appendChild(reasonInput);
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'oc-btn--primary';
    btn.textContent = 'Create new occurrence';
    btn.addEventListener('click', function () {
      var reason = reasonInput.value.trim();
      if (!reason) { setError('Recurrence reason is required.'); return; }
      onConfirm(previousCase.id, reason);
    });
    el.appendChild(btn);
  }

  async function submit(sourceEntityId, previousCaseId, recurrenceReason) {
    setError(null);
    var form = document.querySelector('[data-oc-new-form]');
    var ownerId = form.owner_id.value;
    var dueDate = form.due_date.value;
    var dueTime = form.due_time.value;
    var nextAction = form.next_action.value.trim();

    if (!ownerId) { setError('Choose an owner.'); return; }
    var dueAt = utcIsoFromInputs(dueDate, dueTime);
    if (!dueAt) { setError('Enter a due date and time.'); return; }
    if (!nextAction) { setError('Describe the next action.'); return; }

    var payload = {
      source_entity_id: sourceEntityId,
      owner_id: ownerId,
      due_at: dueAt,
      next_action: nextAction,
    };
    if (previousCaseId) {
      payload.previous_case_id = previousCaseId;
      payload.recurrence_reason = recurrenceReason;
    }

    if (submitting) return;
    submitting = true;
    try {
      var data = await window.CoreAPI.createCaseFromFinding(payload);
      var caseId = data && data.case && data.case.id;
      if (caseId) {
        dirty = false;
        window.location.href = '/core/cases/' + encodeURIComponent(caseId);
      }
    } catch (e) {
      var body = e && e.body;
      if (body && body.error_code === 'requires_new_occurrence' && body.previous_case) {
        showRecurrencePrompt(body.previous_case, function (prevId, reason) {
          submit(sourceEntityId, prevId, reason);
        });
        return;
      }
      setError((e && e.message) || 'Could not create the case. Please try again.');
    } finally { submitting = false; }
  }

  function init() {
    var root = document.querySelector('[data-oc-new-root]');
    if (!root) return;
    var sourceEntityId = qs('source_entity_id');
    var itemName = qs('item_name');
    if (itemName) {
      var subtitle = document.querySelector('[data-oc-new-subtitle]');
      if (subtitle) subtitle.textContent = 'For untracked stock: ' + itemName;
    }
    if (!sourceEntityId) {
      setError('No source item was specified. Return to Notifications and try again.');
      var formEl = document.querySelector('[data-oc-new-form]');
      if (formEl) formEl.hidden = true;
      return;
    }

    var ownerSelect = document.getElementById('oc-new-owner');
    if (ownerSelect) loadOwners(ownerSelect);

    ['oc-new-due-date', 'oc-new-due-time'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('input', updateLocalPreview);
    });

    var form = document.querySelector('[data-oc-new-form]');
    if (form) {
      form.addEventListener('input', function () { dirty = true; });
      form.addEventListener('submit', function (ev) {
        ev.preventDefault();
        submit(sourceEntityId, null, null);
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
