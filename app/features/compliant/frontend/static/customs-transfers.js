// Customs → Transfers (GL-P08): sales that went to another business's CCA. Each needs a movement
// register row (when it left, who carried it) and the destination's acknowledgement of receipt.
// The server decides which sales are transfers and validates every change; this page lays them
// out, records the movement and the receipt, and keeps the list of CCAs you send to.
(function () {
  'use strict';

  var API = '/api/compliant/nz-alcohol/cca-transfers';
  var PLACES_API = '/api/compliant/nz-alcohol/cca-destinations';
  var STATUS = {
    needs_details: { text: 'Needs movement details', chip: 'failed' },
    receipt_overdue: { text: 'Receipt overdue', chip: 'failed' },
    awaiting_receipt: { text: 'Awaiting receipt', chip: 'open' },
    received: { text: 'Received', chip: 'complete' },
  };

  function init() {
    var page = document.querySelector('[data-customs-transfers-root]');
    if (!page || page.dataset.bound === '1' || !window.CustomsUI) return;
    page.dataset.bound = '1';
    var U = window.CustomsUI;
    var el = U.el, api = U.api, fmtDate = U.fmtDate;
    var fail = U.failer(page);
    var body = page.querySelector('[data-tr-body]');
    var summary = page.querySelector('[data-tr-summary]');
    var placesEl = page.querySelector('[data-tr-places]');
    var markBtn = page.querySelector('[data-tr-mark]');
    var markPanel = page.querySelector('[data-tr-mark-panel]');
    var state = { transfers: [], destinations: [], kinds: {}, customers: [], open: null, filter: 'action', editing: null };

    // --- small pieces --------------------------------------------------------------------------
    function when(iso) {
      if (!iso) return '—';
      var d = new Date(iso);
      return isNaN(d) ? iso : d.toLocaleString('en-NZ', { timeZone: 'Pacific/Auckland', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
    }
    function goods(t) { return t.goods.map(function (g) { return U.amount(g.quantity, g.unit) + ' ' + g.product; }).join(', '); }
    function chip(t) { var s = STATUS[t.status]; return el('span', { className: 'customs-chip customs-chip--' + s.chip, text: s.text }); }
    function sale(t) { return t.reference + ' · ' + U.dayMonth(t.invoice_date) + (t.customer ? ' · ' + t.customer : ''); }
    function moved(t) {
      var d = t.departure;
      if (!d) return 'Not recorded';
      return when(d.moved_at) + ' · ' + d.carrier + (d.consignment_note ? ' · ' + d.consignment_note : '');
    }
    function received(t) { var d = t.departure; return d && d.received_on ? U.dayMonth(d.received_on) + ' · ' + d.receipt_reference : '—'; }
    function field(label, input, hint) {
      return el('label', { className: 'customs-field' }, [el('span', { className: 'customs-field__label', text: label }), input, hint ? el('span', { className: 'customs-field__hint', text: hint }) : null]);
    }
    function nowLocal() {
      var d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
      return d.toISOString().slice(0, 16);
    }
    function isoLocal(iso) {
      // The stored time in NZ, as a datetime-local value.
      var d = new Date(iso);
      var parts = {};
      new Intl.DateTimeFormat('en-NZ', { timeZone: 'Pacific/Auckland', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
        .formatToParts(d).forEach(function (p) { parts[p.type] = p.value; });
      return parts.year + '-' + parts.month + '-' + parts.day + 'T' + parts.hour + ':' + parts.minute;
    }
    function needsAction(t) { return t.status !== 'received'; }

    // --- the forms ------------------------------------------------------------------------------
    // When it left and who carried it (para 15). The destination is the customer's, or chosen.
    function departureForm(t, onDone) {
      var id = 'tr-dep-' + (t.xero_invoice_id || 'new').replace(/[^a-z0-9]/gi, '');
      var form = el('form', { className: 'customs-rec-form tr-form', 'hx-boost': 'false', 'data-tr-departure-form': '' });
      var dest = el('select', { id: id + '-dest', required: 'required' });
      state.destinations.forEach(function (d) { dest.append(el('option', { value: d.id, text: d.name + ' (' + d.cca_code + ')' })); });
      dest.value = (t.departure && t.destination.id) || (t.destination && t.destination.id) || '';
      var at = el('input', { type: 'datetime-local', id: id + '-at', required: 'required' });
      at.value = t.departure ? isoLocal(t.departure.moved_at) : (t.invoice_date ? t.invoice_date + 'T09:00' : nowLocal());
      var carrier = el('input', { id: id + '-carrier', required: 'required', maxlength: '200', placeholder: 'e.g. Mainfreight' });
      var note = el('input', { id: id + '-note', maxlength: '200', placeholder: 'e.g. MF-882310' });
      if (t.departure) { carrier.value = t.departure.carrier; note.value = t.departure.consignment_note || ''; }
      form.append(el('div', { className: 'customs-rec-form__row tr-form__dep' }, [field('Went to', dest), field('Left on', at, 'NZ time'), field('Carrier', carrier), field('Consignment note', note, 'Optional')]));
      var save = el('button', { type: 'submit', className: 'workspace-button workspace-button--primary', text: t.departure ? 'Save changes' : 'Save movement' });
      var actions = el('div', { className: 'tr-form__actions' }, [save]);
      if (onDone.cancel) {
        var cancel = el('button', { type: 'button', className: 'workspace-button', text: 'Cancel' });
        cancel.addEventListener('click', onDone.cancel);
        actions.append(cancel);
      }
      form.append(actions);
      form.addEventListener('submit', async function (e) {
        e.preventDefault(); fail(''); save.disabled = true;
        try {
          await api('POST', API, { xero_invoice_id: t.xero_invoice_id, destination_id: dest.value, moved_at: at.value, carrier: carrier.value, consignment_note: note.value });
          await onDone();
        } catch (err) { fail(err.message); save.disabled = false; }
      });
      return form;
    }

    // The destination's written acknowledgement that the goods arrived (para 16).
    function receiptForm(t, onDone) {
      var id = 'tr-rec-' + t.departure.id;
      var form = el('form', { className: 'customs-rec-form tr-form', 'hx-boost': 'false', 'data-tr-receipt-form': '' });
      var on = el('input', { type: 'date', id: id + '-on', required: 'required' });
      on.value = U.todayIso();
      var ref = el('input', { id: id + '-ref', required: 'required', maxlength: '500', placeholder: 'e.g. Signed delivery docket DF-4471' });
      form.append(el('div', { className: 'customs-rec-form__row' }, [field('Received on', on), field('Their acknowledgement', ref, 'What they signed or sent, and where it is kept.')]));
      var save = el('button', { type: 'submit', className: 'workspace-button workspace-button--primary', text: 'Save receipt' });
      form.append(el('div', { className: 'tr-form__actions' }, [save]));
      form.addEventListener('submit', async function (e) {
        e.preventDefault(); fail(''); save.disabled = true;
        try {
          await api('PUT', t.receipt_url, { received_on: on.value, receipt_reference: ref.value });
          await onDone();
        } catch (err) { fail(err.message); save.disabled = false; }
      });
      return form;
    }

    // Everything about one sale: the register facts, the next thing to record, and corrections.
    function detail(t) {
      var wrap = el('div', { className: 'tr-detail', 'data-tr-detail': t.xero_invoice_id });
      var facts = el('dl', { className: 'customs-rec-facts' });
      function fact(k, v) { facts.append(el('dt', { text: k }), el('dd', { text: v })); }
      fact(t.kind === 'contract' ? 'Dispatch' : 'Sale', sale(t));
      fact('Went to', t.destination.name + ' · CCA ' + t.destination.cca_code);
      if (t.destination.address) fact('Address', t.destination.address);
      if (t.kind === 'contract') fact('Order', t.reference.replace(/ dispatch$/, ''));
      fact('Goods', goods(t));
      fact('Left', moved(t));
      fact('Received', received(t));
      wrap.append(facts);
      var reload = async function () { state.open = null; await load(); };
      if (t.status === 'needs_details') wrap.append(el('h3', { className: 'customs-sub', text: 'Record when it left' }), departureForm(t, reload));
      else if (t.status !== 'received') wrap.append(el('h3', { className: 'customs-sub', text: 'Record the receipt' }), receiptForm(t, reload));
      if (t.departure && t.kind !== 'contract') {
        var more = el('details', { className: 'customs-rec-form__more' }, [el('summary', { text: 'Correct the movement' })]);
        more.append(departureForm(t, reload));
        var undo = el('button', { type: 'button', className: 'workspace-button tr-undo', text: 'Not a transfer: remove the movement' });
        undo.addEventListener('click', async function () {
          if (!window.confirm('Remove the movement record for ' + t.reference + '? A sale to a linked customer stays a transfer.')) return;
          try { await api('DELETE', API + '/' + t.departure.id); await reload(); } catch (err) { fail(err.message); }
        });
        more.append(undo);
        wrap.append(more);
      }
      return wrap;
    }

    function toggle(t) { state.open = state.open === t.xero_invoice_id ? null : t.xero_invoice_id; render(); }

    // --- the register, as Customs asks for it (para 15) --------------------------------------------
    function registerView() {
      var shown = state.transfers.filter(function (t) { return state.filter === 'all' || (state.filter === 'action' ? needsAction(t) : !needsAction(t)); });
      var counts = { action: state.transfers.filter(needsAction).length, done: state.transfers.filter(function (t) { return !needsAction(t); }).length, all: state.transfers.length };
      var tabs = el('div', { className: 'tr-filter', role: 'group', 'aria-label': 'Show' });
      [['action', 'To do'], ['done', 'Received'], ['all', 'All']].forEach(function (f) {
        var b = el('button', { type: 'button', 'aria-pressed': String(state.filter === f[0]), text: f[1] + ' · ' + counts[f[0]] });
        b.addEventListener('click', function () { state.filter = f[0]; state.open = null; render(); });
        tabs.append(b);
      });
      var head = el('div', { className: 'tr-reg tr-reg--head', 'aria-hidden': 'true' }, ['Sale', 'Went to', 'Goods', 'Left', 'Received', ''].map(function (h) { return el('span', { text: h }); }));
      var list = el('div', { className: 'tr-reg-list', 'data-tr-register': '' }, [head]);
      shown.forEach(function (t) {
        var row = el('button', { type: 'button', className: 'tr-reg', 'aria-expanded': String(state.open === t.xero_invoice_id), 'data-tr-row': t.xero_invoice_id }, [
          el('span', { className: 'tr-reg__sale' }, [el('strong', { text: t.reference }), el('span', { text: U.dayMonth(t.invoice_date) + (t.customer ? ' · ' + t.customer : '') })]),
          el('span', { className: 'tr-reg__to' }, [el('strong', { text: t.destination.name }), el('span', { text: t.destination.cca_code })]),
          el('span', { className: 'tr-reg__cell', 'data-label': 'Goods', text: goods(t) }),
          el('span', { className: 'tr-reg__cell', 'data-label': 'Left', text: t.departure ? when(t.departure.moved_at) + ' · ' + t.departure.carrier : '—' }),
          el('span', { className: 'tr-reg__cell', 'data-label': 'Received', text: t.departure && t.departure.received_on ? U.dayMonth(t.departure.received_on) : '—' }),
          chip(t),
        ]);
        row.addEventListener('click', function () { toggle(t); });
        list.append(row);
        if (state.open === t.xero_invoice_id) list.append(detail(t));
      });
      if (!shown.length) list.append(el('p', { className: 'customs-empty', text: state.filter === 'action' ? 'Nothing to record: every transfer has its movement and receipt.' : 'No transfers here yet.' }));
      return [tabs, list];
    }

    // --- the CCAs you send to ---------------------------------------------------------------------
    function placeForm(d) {
      var form = el('form', { className: 'customs-rec-form tr-form', 'hx-boost': 'false', 'data-tr-place-form': '' });
      var id = 'tr-place-' + (d ? d.id.slice(0, 8) : 'new');
      var name = el('input', { id: id + '-name', required: 'required', maxlength: '200', placeholder: 'e.g. Auckland Airport duty free' });
      var code = el('input', { id: id + '-code', required: 'required', maxlength: '100', placeholder: 'Their CCA licence number' });
      var address = el('input', { id: id + '-address', required: 'required', maxlength: '500' });
      var kind = el('select', { id: id + '-kind', required: 'required' });
      Object.keys(state.kinds).forEach(function (k) { kind.append(el('option', { value: k, text: state.kinds[k] })); });
      var customer = el('select', { id: id + '-customer' });
      customer.append(el('option', { value: '', text: 'None: mark sales by hand' }));
      state.customers.forEach(function (c) { customer.append(el('option', { value: c.id, text: c.name })); });
      if (d) { name.value = d.name; code.value = d.cca_code; address.value = d.address; kind.value = d.kind; customer.value = d.contact_id || ''; }
      form.append(
        el('h3', { className: 'customs-sub', text: d ? 'Edit ' + d.name : 'Add a CCA you send to' }),
        el('div', { className: 'customs-rec-form__row' }, [field('Name', name), field('CCA code', code)]),
        field('Address', address),
        el('div', { className: 'customs-rec-form__row' }, [field('Kind', kind), field('Customer', customer, 'Every sale to this customer is then a transfer.')])
      );
      var save = el('button', { type: 'submit', className: 'workspace-button workspace-button--primary', text: d ? 'Save' : 'Add CCA' });
      var cancel = el('button', { type: 'button', className: 'workspace-button', text: 'Cancel' });
      cancel.addEventListener('click', function () { state.editing = null; render(); });
      form.append(el('div', { className: 'tr-form__actions' }, [save, cancel]));
      form.addEventListener('submit', async function (e) {
        e.preventDefault(); fail(''); save.disabled = true;
        var payload = { name: name.value, cca_code: code.value, address: address.value, kind: kind.value, contact_id: customer.value || null };
        try {
          if (d) await api('PUT', PLACES_API + '/' + d.id, payload); else await api('POST', PLACES_API, payload);
          state.editing = null; await load();
        } catch (err) { fail(err.message); save.disabled = false; }
      });
      return form;
    }

    function placesList() {
      var out = [];
      if (!state.destinations.length && state.editing !== 'new') out.push(el('p', { className: 'customs-empty', text: 'None yet. Add the duty free shops, export warehouses or customers\' licensed areas you sell into.' }));
      var ul = el('ul', { className: 'customs-rec-list' });
      state.destinations.forEach(function (d) {
        var edit = el('button', { type: 'button', className: 'tr-link', text: 'Edit' });
        edit.addEventListener('click', function () { state.editing = d.id; render(); });
        ul.append(el('li', { className: 'customs-rec-row tr-place-row', 'data-tr-place': d.id }, [
          el('div', { className: 'customs-rec-row__main' }, [el('strong', { text: d.name + ' · ' + d.cca_code }), el('span', { text: d.kind_label + ' · ' + d.address + (d.contact_name ? ' · sales to ' + d.contact_name : ' · marked by hand') })]),
          el('span'),
          edit,
        ]));
        if (state.editing === d.id) ul.append(el('li', { className: 'tr-place-edit' }, [placeForm(d)]));
      });
      if (state.destinations.length) out.push(ul);
      if (state.editing === 'new') out.push(placeForm(null));
      return out;
    }

    // --- mark any sale as a transfer --------------------------------------------------------------
    function openMark() {
      if (!state.destinations.length) { fail('Add the CCA the goods went to first.'); state.editing = 'new'; render(); return; }
      markPanel.hidden = false; markBtn.setAttribute('aria-expanded', 'true');
      var q = el('input', { type: 'search', id: 'tr-mark-q', placeholder: 'Invoice number or customer', maxlength: '100', 'aria-label': 'Find a sale' });
      var results = el('div', { className: 'tr-mark__results', 'data-tr-mark-results': '' });
      var close = el('button', { type: 'button', className: 'workspace-button', text: 'Close' });
      close.addEventListener('click', closeMark);
      async function find() {
        try {
          var data = await api('GET', API + '/sales?q=' + encodeURIComponent(q.value.trim()));
          results.replaceChildren();
          (data.sales || []).slice(0, 8).forEach(function (s) {
            var pick = el('button', { type: 'button', className: 'tr-mark__sale' }, [el('strong', { text: s.reference }), el('span', { text: U.dayMonth(s.invoice_date) + (s.customer ? ' · ' + s.customer : '') })]);
            pick.addEventListener('click', function () {
              results.replaceChildren(el('p', { className: 'tr-mark__picked', text: 'Sale ' + s.reference + ' · ' + U.dayMonth(s.invoice_date) + (s.customer ? ' · ' + s.customer : '') }), departureForm({ xero_invoice_id: s.xero_invoice_id, invoice_date: s.invoice_date, destination: state.destinations[0] }, Object.assign(async function () { closeMark(); await load(); }, { cancel: closeMark })));
            });
            results.append(pick);
          });
          if (!results.children.length) results.append(el('p', { className: 'excise-hint', text: 'No sales found that took stock and aren\'t transfers already.' }));
        } catch (err) { fail(err.message); }
      }
      var t;
      q.addEventListener('input', function () { clearTimeout(t); t = setTimeout(find, 250); });
      markPanel.replaceChildren(
        el('p', { className: 'excise-hint', text: 'For a one-off sale to another CCA. To make every sale to a customer a transfer, link the customer to its CCA instead.' }),
        el('div', { className: 'tr-mark__search' }, [q, close]),
        results
      );
      find();
      q.focus();
    }
    function closeMark() { markPanel.hidden = true; markPanel.replaceChildren(); markBtn.setAttribute('aria-expanded', 'false'); }
    markBtn.setAttribute('aria-expanded', 'false');
    markBtn.addEventListener('click', function () { if (markPanel.hidden) openMark(); else closeMark(); });
    page.querySelector('[data-tr-add-place]').addEventListener('click', function () { state.editing = 'new'; render(); });

    // --- render -------------------------------------------------------------------------------------
    function render() {
      var c = state.counts || {};
      var todo = (c.needs_details || 0) + (c.receipt_overdue || 0) + (c.awaiting_receipt || 0);
      var bits = [U.plural(state.transfers.length, 'transfer') + ' in the last year'];
      if (c.needs_details) bits.push(c.needs_details + ' without movement details');
      if (c.receipt_overdue) bits.push(U.plural(c.receipt_overdue, 'receipt') + ' overdue');
      if (c.awaiting_receipt) bits.push(c.awaiting_receipt + ' awaiting receipt');
      if (!todo && state.transfers.length) bits.push('all received');
      summary.removeAttribute('data-loading');
      summary.textContent = bits.join(' · ');
      if (!state.transfers.length) {
        body.replaceChildren(el('p', { className: 'customs-empty', text: state.destinations.length ? 'No sales to other CCAs in the last year.' : 'No sales to other CCAs yet. Add the CCAs you sell into below, and link each to its customer.' }));
      } else {
        body.replaceChildren.apply(body, registerView());
      }
      placesEl.replaceChildren.apply(placesEl, placesList());
    }

    async function load() {
      var data = await api('GET', API);
      var places = await api('GET', PLACES_API);
      state.transfers = data.transfers || [];
      state.counts = data.counts || {};
      state.destinations = places.destinations || [];
      state.kinds = places.kinds || {};
      state.customers = places.customers || [];
      render();
    }

    load().catch(function (err) { fail(err.message); }).finally(function () { page.setAttribute('aria-busy', 'false'); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  document.addEventListener('htmx:afterSwap', init);
})();
