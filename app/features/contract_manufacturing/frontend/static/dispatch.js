// Contract order → Dispatch (GL-P08 part 2). Every departure from the CCA is a transfer to the
// customer's CCA or a removal for duty; the server decides which from the order and takes the
// stock off. This lists the dispatches, records a new one, and records the customer's receipt.
(() => {
  'use strict';

  const STATUS = {
    removed: ['Removed for duty', 'complete'],
    awaiting_receipt: ['Awaiting receipt', 'open'],
    receipt_overdue: ['Receipt overdue', 'failed'],
    received: ['Received', 'complete'],
  };

  function init() {
    const root = document.querySelector('[data-contract-dispatch]');
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    const base = `/api/core/contract-orders/${root.dataset.orderId}/dispatches`;
    const canDispatch = root.dataset.canDispatch === 'true';
    const canReceipt = root.dataset.canReceipt === 'true';
    const list = root.querySelector('[data-dispatch-list]');
    const form = root.querySelector('[data-dispatch-form]');
    const lots = root.querySelector('[data-dispatch-lots]');
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const errorBox = document.querySelector('.contract-error');

    const el = (tag, attrs = {}, kids = []) => {
      const node = document.createElement(tag);
      Object.entries(attrs).forEach(([k, v]) => {
        if (v == null) return;
        if (k === 'text') node.textContent = v; else if (k === 'className') node.className = v; else node.setAttribute(k, v);
      });
      kids.forEach((kid) => kid && node.append(kid));
      return node;
    };
    const fail = (message) => {
      if (!errorBox) return;
      errorBox.textContent = message || '';
      errorBox.hidden = !message;
    };
    const api = async (method, url, body) => {
      const response = await fetch(url, {
        method,
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, Accept: 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      let data = {};
      try { data = await response.json(); } catch (_) { /* an empty body */ }
      if (!response.ok) throw new Error(data.error || 'Unable to save. Please try again.');
      return data;
    };
    const when = (iso) => new Date(iso).toLocaleString('en-NZ', { timeZone: 'Pacific/Auckland', day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' });
    const day = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' });
    const nowLocal = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
    const today = () => nowLocal().slice(0, 10);

    function receiptForm(d) {
      const f = el('form', { className: 'contract-dispatch__receipt', 'hx-boost': 'false', 'data-dispatch-receipt': d.id });
      const on = el('input', { type: 'date', name: 'received_on', required: 'required', value: today() });
      const ref = el('input', { name: 'receipt_reference', maxlength: '500', required: 'required', placeholder: 'e.g. Signed delivery docket' });
      f.append(
        el('label', {}, [document.createTextNode('Received on'), on]),
        el('label', {}, [document.createTextNode('Their acknowledgement'), ref]),
        el('button', { type: 'submit', className: 'btn', text: 'Save receipt' }),
      );
      f.addEventListener('submit', async (e) => {
        e.preventDefault(); fail('');
        try { await api('PUT', `${base}/${d.id}/receipt`, { received_on: on.value, receipt_reference: ref.value }); await load(); } catch (err) { fail(err.message); }
      });
      return f;
    }

    function row(d) {
      const [label, tone] = STATUS[d.status] || [d.status, 'open'];
      const goods = d.lines.map((l) => `${l.quantity} ${l.unit} ${l.product_name}`).join(', ');
      const meta = [`Left ${when(d.moved_at)}`, d.carrier, d.consignment_note, d.destination_cca ? `to CCA ${d.destination_cca}` : null,
        d.received_on ? `received ${day(d.received_on)} · ${d.receipt_reference}` : null].filter(Boolean).join(' · ');
      const li = el('li', { className: 'contract-dispatch__item', 'data-dispatch-id': d.id }, [
        el('div', { className: 'contract-dispatch__what' }, [el('strong', { text: goods }), el('span', { text: meta })]),
        el('span', { className: `contract-dispatch__chip contract-dispatch__chip--${tone}`, text: label }),
      ]);
      if (canReceipt && (d.status === 'awaiting_receipt' || d.status === 'receipt_overdue')) li.append(receiptForm(d));
      return li;
    }

    function renderLots(available) {
      lots.replaceChildren(el('legend', { text: 'What is leaving' }));
      available.forEach((lot) => {
        const qty = el('input', { type: 'number', min: '0', step: 'any', max: lot.available, placeholder: 'How many', name: `qty-${lot.inventory_item_id}`, 'data-lot': lot.inventory_item_id, 'aria-label': `Quantity from ${lot.batch || lot.product_name}` });
        lots.append(el('div', { className: 'contract-dispatch__lot' }, [
          el('span', { text: `${lot.product_name}${lot.batch ? ` · batch ${lot.batch}` : ''}` }),
          el('span', { className: 'contract-dispatch__hint', text: `${lot.available} ${lot.unit} on hand` }),
          qty,
        ]));
      });
    }

    async function load() {
      const data = await api('GET', base);
      const done = data.dispatches || [];
      list.replaceChildren(done.length
        ? el('ul', { className: 'contract-dispatch__list' }, done.map(row))
        : el('p', { className: 'contract-dispatch__hint', text: 'Nothing dispatched yet.' }));
      const available = data.dispatchable || [];
      if (canDispatch && available.length) {
        renderLots(available);
        form.hidden = false;
        if (!form.moved_at.value) form.moved_at.value = nowLocal();
      } else {
        form.hidden = true;
        if (canDispatch) list.append(el('p', { className: 'contract-dispatch__hint', text: 'No finished stock from this order’s batches is left to dispatch.' }));
      }
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault(); fail('');
      const picks = [...lots.querySelectorAll('input[data-lot]')]
        .filter((input) => Number(input.value) > 0)
        .map((input) => ({ inventory_item_id: input.dataset.lot, quantity: input.value }));
      if (!picks.length) { fail('Enter how much of at least one batch is leaving.'); return; }
      const button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      try {
        await api('POST', base, { moved_at: form.moved_at.value, carrier: form.carrier.value, consignment_note: form.consignment_note.value, lines: picks });
        form.carrier.value = ''; form.consignment_note.value = '';
        await load();
      } catch (err) { fail(err.message); } finally { button.disabled = false; }
    });

    load().catch((err) => fail(err.message));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  document.addEventListener('htmx:afterSwap', init);
})();
