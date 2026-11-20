/* Completed step correction form. All writes go through the audited Core endpoint. */
(function () {
  'use strict';
  const root = document.getElementById('execution-record');
  const initialEl = document.getElementById('record-initial-prompts');
  if (!root || !initialEl || !window.CoreAPI) return;
  const initial = JSON.parse(initialEl.textContent || '{}');
  const save = document.getElementById('record-save');
  const error = document.getElementById('record-error');

  save.addEventListener('click', async function () {
    const reason = (document.getElementById('record-reason').value || '').trim();
    const changes = {};
    let invalidAnswer = false;
    root.querySelectorAll('[data-record-prompt]').forEach(function (field) {
      if (invalidAnswer) return;
      const key = field.getAttribute('data-record-prompt');
      const oldValue = initial[key];
      const oldText = oldValue == null ? '' : (typeof oldValue === 'string' ? oldValue : JSON.stringify(oldValue));
      if (field.value === oldText) return;
      let value = field.value;
      if (typeof oldValue === 'number' && value.trim() !== '') {
        const parsed = Number(value);
        if (Number.isFinite(parsed)) value = parsed;
      } else if (typeof oldValue === 'boolean' && (value === 'true' || value === 'false')) {
        value = value === 'true';
      } else if (oldValue !== null && typeof oldValue === 'object') {
        try {
          value = JSON.parse(value);
          if (Array.isArray(value) !== Array.isArray(oldValue) || value === null || typeof value !== 'object') {
            throw new Error('The answer must remain a JSON ' + (Array.isArray(oldValue) ? 'list' : 'object') + '.');
          }
        } catch (parseError) {
          error.textContent = 'Enter valid JSON for ' + key + ': ' + parseError.message;
          error.hidden = false;
          invalidAnswer = true;
          return;
        }
      }
      changes[key] = value;
    });
    if (invalidAnswer) return;
    error.hidden = true;
    if (reason.length < 3 || Object.keys(changes).length === 0) {
      error.textContent = 'Change an answer and give a reason of at least 3 characters.';
      error.hidden = false;
      return;
    }
    save.disabled = true;
    try {
      await window.CoreAPI.request(
        '/executions/' + encodeURIComponent(root.dataset.executionId) + '/steps/' + encodeURIComponent(root.dataset.stepId) + '/record',
        { method: 'POST', body: { reason: reason, prompts: changes } }
      );
      window.location.reload();
    } catch (e) {
      error.textContent = e && e.message ? e.message : 'Could not save this correction.';
      error.hidden = false;
      save.disabled = false;
    }
  });
})();
