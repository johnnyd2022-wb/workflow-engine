(() => {
  const customer = document.querySelector('[data-material-customer]');
  if (!customer) return;
  const error = document.querySelector('[data-material-error]');
  const list = document.querySelector('[data-material-list]');
  let key = crypto.randomUUID();
  let submittedBody = null;
  async function request(url, options = {}) {
    const response = await fetch(url, {credentials: 'same-origin', ...options});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to save materials');
    return data;
  }
  function showError(message) { error.textContent = message; error.hidden = !message; }
  async function load() {
    list.replaceChildren();
    if (!customer.value) return;
    const data = await request(`/api/core/contract-customers/${customer.value}/materials`);
    if (!data.materials.length) list.textContent = 'No raw materials received yet.';
    for (const item of data.materials) {
      const row = document.createElement('p');
      row.textContent = `${item.name} · ${item.quantity} ${item.unit} · Customer-owned${item.supplier_batch_number ? ` · Batch ${item.supplier_batch_number}` : ''}`;
      list.append(row);
    }
  }
  customer.addEventListener('change', () => { showError(''); load().catch(e => showError(e.message)); });
  const form = document.querySelector('[data-material-receipt]');
  form?.addEventListener('submit', async event => {
    event.preventDefault(); showError('');
    if (!customer.value) return showError('Choose a customer');
    const body = Object.fromEntries(new FormData(form));
    const serialized = JSON.stringify({customer: customer.value, body});
    if (submittedBody !== serialized) { key = crypto.randomUUID(); submittedBody = serialized; }
    const button = form.querySelector('button[type="submit"]'); button.disabled = true;
    try {
      await request(`/api/core/contract-customers/${customer.value}/material-receipts`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content, 'Idempotency-Key': key}, body: JSON.stringify(body)});
      form.reset(); submittedBody = null; await load();
    } catch (e) { showError(e.message); } finally { button.disabled = false; }
  });
})();
