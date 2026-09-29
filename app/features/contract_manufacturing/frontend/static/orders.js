(() => {
  'use strict';
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const showError = (message) => {
    const target = document.querySelector('.contract-error');
    if (target) {
      target.textContent = message;
      target.hidden = false;
      target.scrollIntoView({ block: 'center' });
    }
  };
  const request = async (url, method, body) => {
    const response = await fetch(url, {
      method,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, Accept: 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = response.status === 204 ? {} : await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to save. Please try again.');
    return data;
  };
  const mapping = (record) => {
    if (record.product_mapping) {
      const [version, output] = record.product_mapping.split('|');
      record.process_id = null;
      record.process_version_id = version;
      record.source_output_id = output;
    }
    delete record.product_mapping;
    return record;
  };
  document.querySelectorAll('form[data-contract-api]').forEach((form) => {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      try {
        const body = {};
        const line = {};
        new FormData(form).forEach((value, name) => {
          if (name.startsWith('line.')) line[name.slice(5)] = value;
          else body[name] = value;
        });
        if ('is_active' in body) body.is_active = body.is_active === 'true';
        if (form.hasAttribute('data-create-order')) body.lines = [mapping(line)];
        mapping(body);
        const saved = await request(form.dataset.contractApi, form.dataset.method, body);
        if (form.hasAttribute('data-create-order')) {
          window.location.assign('/core/contracts/' + encodeURIComponent(saved.order.id));
        } else window.location.reload();
      } catch (error) {
        showError(error.message);
        button.disabled = false;
      }
    });
  });
  document.querySelectorAll('[data-contract-delete]').forEach((button) => {
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await request(button.dataset.contractDelete, 'DELETE');
        window.location.reload();
      } catch (error) {
        showError(error.message);
        button.disabled = false;
      }
    });
  });
})();
