(() => {
  'use strict';
  let inviteToken = '';
  const inviteForm = document.querySelector('[data-invite]');
  if (inviteForm) {
    inviteToken = location.hash.slice(1);
    history.replaceState(null, '', location.pathname);
  }
  const key = document.querySelector('[name="customer_id"]');
  if (key) key.value = new URLSearchParams(location.search).get('customer') || key.value;
  const error = (message) => {
    const target = document.querySelector('[data-error]');
    target.textContent = message;
    target.hidden = false;
  };
  const post = async (path, body) => {
    const response = await fetch(path, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content}, body: JSON.stringify(body)}); // nosemgrep: raw-fetch-post, sequential-independent-awaits -- explicit CSRF; response body depends on fetch
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'Unable to continue.');
    location.assign(result.redirect || location.pathname);
  };
  document.querySelectorAll('form[data-portal-api], form[data-approval-api]').forEach((form) => {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('button');
      button.disabled = true;
      try {
        const body = Object.fromEntries(new FormData(form));
        if (form.hasAttribute('data-invite')) body.token = inviteToken;
        if (form.hasAttribute('data-approval-api')) body.decision = event.submitter.value;
        await post(form.dataset.portalApi || form.dataset.approvalApi, body);
      } catch (failure) { error(failure.message); button.disabled = false; }
    });
  });
  document.querySelector('[data-portal-logout]')?.addEventListener('click', async () => {
    try { await post('/portal/api/logout', {}); } catch (failure) { error(failure.message); }
  });
})();
