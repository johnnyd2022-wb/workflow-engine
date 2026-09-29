(() => {
  'use strict';
  const error = (message) => { const target = document.querySelector('.contract-error'); target.textContent = message; target.hidden = false; };
  const send = async (path, method, body, upload = false) => {
    const headers = {'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content};
    if (!upload) headers['Content-Type'] = 'application/json';
    const response = await fetch(path, {method, credentials: 'same-origin', headers, body: body ? (upload ? body : JSON.stringify(body)) : undefined});
    const result = response.status === 204 ? {} : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'Unable to save.');
    return result;
  };
  document.querySelectorAll('form[data-sharing-api]').forEach((form) => {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('button'); button.disabled = true;
      try {
        const data = new FormData(form);
        const body = form.hasAttribute('data-upload') ? data : Object.fromEntries(data);
        if (form.hasAttribute('data-publication')) body.document_ids = data.getAll('document_ids');
        const result = await send(form.dataset.sharingApi, 'POST', body, form.hasAttribute('data-upload'));
        if (form.hasAttribute('data-invite')) {
          const target = document.querySelector('[data-invite-result]');
          target.textContent = `Invitation: ${location.origin}${result.invite_link}`; target.hidden = false; button.disabled = false;
        } else location.reload();
      } catch (failure) { error(failure.message); button.disabled = false; }
    });
  });
  document.querySelectorAll('[data-sharing-delete]').forEach((button) => {
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { await send(button.dataset.sharingDelete, 'DELETE'); location.reload(); }
      catch (failure) { error(failure.message); button.disabled = false; }
    });
  });
})();
