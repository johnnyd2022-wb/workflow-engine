(() => {
  'use strict';
  const root = document.querySelector('[data-transfers-root]');
  if (!root) return;
  const message = root.querySelector('[data-transfers-message]');
  const state = root.querySelector('[data-transfers-state]');
  const list = root.querySelector('[data-transfers-list]');
  const form = root.querySelector('[data-transfer-dispatch]');
  let options, available = false;
  const today = () => new Date().toLocaleDateString('en-CA');
  const node = (tag, text, cls) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (cls) element.className = cls;
    return element;
  };
  const showError = error => { message.hidden = false; message.textContent = error.message; };
  async function api(path, init = {}) {
    const token = document.querySelector('meta[name="csrf-token"]')?.content;
    const response = await fetch(path, {credentials: 'same-origin', ...init,
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': token || '', ...init.headers}});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Unable to save this transfer');
    return result;
  }
  function selectOptions(select, rows, label, blank) {
    select.replaceChildren();
    if (blank !== undefined) select.append(new Option(blank, ''));
    rows.forEach(row => select.append(new Option(label(row), row.id)));
  }
  function approvalFields() {
    const group = node('div', undefined, 'transfers-fields');
    group.dataset.approvalFields = '';
    for (const field of options.requirements.fields) {
      if (!['select', 'text', 'date'].includes(field.type) || !/^[a-z_]+$/.test(field.name)) continue;
      const label = node('label', field.label);
      const input = node(field.type === 'select' ? 'select' : 'input');
      if (field.type === 'select') {
        input.append(new Option('Choose…', ''));
        for (const option of field.options || []) input.append(new Option(option.label, option.value));
      } else { input.type = field.type; input.maxLength = 500; }
      input.name = `approval.${field.name}`;
      input.required = field.required === true;
      label.append(input); group.append(label);
    }
    return group;
  }
  function bindSubmission(target, path, payload, done) {
    let request;
    target.addEventListener('input', () => { request = null; });
    target.addEventListener('change', () => { request = null; });
    target.addEventListener('submit', async event => {
      event.preventDefault();
      const button = target.querySelector('[type="submit"]');
      if (button.disabled) return;
      button.disabled = true; message.hidden = true;
      try {
        const body = payload(new FormData(target));
        const json = JSON.stringify(body);
        if (!request || request.json !== json) request = {key: crypto.randomUUID(), json};
        await api(path(), {method: 'POST', headers: {'Idempotency-Key': request.key}, body: request.json});
        request = null;
        done();
        await load();
      } catch (error) { showError(error); }
      finally { button.disabled = false; }
    });
  }
  function receiptForm(transfer) {
    const receipt = node('form'); receipt.setAttribute('hx-boost', 'false');
    const fields = node('div', undefined, 'transfers-fields');
    for (const [name, label, type] of [['quantity', 'Good quantity received', 'number'],
      ['damaged_quantity', 'Confirmed damaged quantity', 'number'], ['short_quantity', 'Confirmed short quantity', 'number'],
      ['occurred_on', 'Receipt date', 'date'], ['loss_reason', 'Reason for confirmed loss', 'text']]) {
      const wrapper = node('label', label), input = node('input');
      input.name = name; input.type = type;
      if (type === 'number') { input.min = '0'; input.step = '0.0001'; input.value = '0'; }
      if (type === 'date') { input.value = today(); input.required = true; }
      if (type === 'text') input.maxLength = 500;
      wrapper.append(input); fields.append(wrapper);
    }
    const confirmation = node('label', 'Confirm the recorded damaged or short quantities as losses');
    const check = node('input'); check.type = 'checkbox'; check.name = 'confirm_loss'; confirmation.prepend(check);
    const submit = node('button', 'Record receipt', 'btn btn-primary'); submit.type = 'submit';
    receipt.append(fields, confirmation, node('p', 'Unconfirmed differences remain in transit. Overages need review.'), submit);
    bindSubmission(receipt, () => `/api/core/site-transfers/${transfer.id}/receipts`, data => ({
      quantity: data.get('quantity'), damaged_quantity: data.get('damaged_quantity'), short_quantity: data.get('short_quantity'),
      occurred_on: data.get('occurred_on'), loss_reason: data.get('loss_reason'), confirm_loss: data.get('confirm_loss') === 'on'
    }), () => receipt.reset());
    return receipt;
  }
  async function load() {
    const [position, choices] = await Promise.all([api('/api/core/site-transfers'), api('/api/core/site-transfers/options')]);
    options = choices; available = position.operations_available;
    state.textContent = available ? (position.transfers.length ? '' : 'No stock in transit.') : 'Transfers are awaiting operational release. Existing records remain available.';
    const siteNames = new Map(options.sites.map(site => [site.id, site.name]));
    if (form) {
      root.querySelector('[data-transfer-create]').hidden = !available || !options.requirements.can_authorise;
      if (available && !options.requirements.can_authorise) state.textContent = 'Movement authority requires a permitted compliance operator. Authorised transfers can still be received.';
      selectOptions(form.elements.source_item_id, options.stock, row => `${row.name} · ${row.quantity} ${row.unit} · ${siteNames.get(row.site_id) || 'Site'}${row.batch ? ' · '+row.batch : ''}`);
      selectOptions(form.elements.destination_site_id, options.sites, row => row.name);
      const places = () => selectOptions(form.elements.destination_location_id,
        options.locations.filter(row => row.site_id === form.elements.destination_site_id.value), row => row.name, 'No specific place');
      form.elements.destination_site_id.onchange = places; places();
      form.elements.occurred_on.value = today();
      form.querySelector('[data-approval-fields]')?.remove();
      form.insertBefore(approvalFields(), form.querySelector('[type="submit"]'));
    }
    list.replaceChildren();
    for (const transfer of position.transfers) {
      const card = node('article', undefined, 'transfers-card');
      card.append(node('h2', `${transfer.product_name} · ${transfer.consignment_reference}`),
        node('p', `${siteNames.get(transfer.source_site_id) || 'Source site'} → ${siteNames.get(transfer.destination_site_id) || 'Destination site'} · ${transfer.carrier}`),
        node('p', `Dispatched ${transfer.quantity} ${transfer.unit} · Received ${transfer.received_quantity} · Transit ${transfer.transit_quantity} · Confirmed loss ${transfer.confirmed_loss_quantity}`));
      const docket = node('a', 'Print transfer docket'); docket.href = `/core/site-transfers/${transfer.id}/docket`;
      docket.target = '_blank'; docket.rel = 'noopener'; docket.setAttribute('hx-boost', 'false'); card.append(docket);
      if (available && list.dataset.canAdjust === 'true' && Number(transfer.transit_quantity) > 0) {
        const details = node('details'), summary = node('summary', 'Record receipt'); details.append(summary, receiptForm(transfer)); card.append(details);
      }
      list.append(card);
    }
  }
  if (form) bindSubmission(form, () => '/api/core/site-transfers', data => {
    const result = Object.fromEntries([...data.entries()].filter(([key]) => !key.startsWith('approval.')));
    result.approval = Object.fromEntries([...data.entries()].filter(([key, value]) => key.startsWith('approval.') && value).map(([key, value]) => [key.slice(9), value]));
    return result;
  }, () => form.reset());
  load().catch(showError);
})();
