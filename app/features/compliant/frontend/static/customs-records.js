// Customs → Records: for each thing Customs can ask to see, is the proof current, and adding
// more. The server works out each check's state (/api/compliant/overview) and validates every
// record; this page lays them out: a row per check, and a page per check.
(function () {
  'use strict';

  var FRAMEWORK = 'customs-alcohol';
  var BASE = '/compliant/nz-alcohol/customs/records';
  // Plain names for Customs' five checks: what each one proves, not its catalogue id.
  var NAMES = {
    'product-mapping': 'Products mapped to Customs items',
    'period-lodgement': "Each period's entry lodged",
    'reconciliation': 'Stock reconciled each period',
    'movement-evidence': 'Movement evidence kept',
    'record-retention': 'Records kept 7 years, in NZ',
  };
  // What a Customs officer would ask to see for each (customs.govt.nz record-keeping obligations).
  var ASKS = {
    'product-mapping': ['Every product with its excise item, strength and pack size', 'How each product reaches its rate'],
    'period-lodgement': ["Each period's excise entry: its number, the period and what was declared", 'Proof of payment by the due date'],
    'reconciliation': ['Production, stock, wastage and removals reviewed for the period', 'The litres of alcohol declared, and how they tie back'],
    'movement-evidence': ['Dispatch and delivery records for alcohol leaving the licensed area', 'Confirmation of receipt for moves between licensed areas'],
    'record-retention': ['Records kept for at least 7 years', 'Held in New Zealand, or Customs approval to store them offshore'],
  };
  // Checks the app keeps current on its own, and where that happens.
  var AUTOMATIC = {
    'product-mapping': ['Kept current by each product’s Customs setup.', '/compliant/nz-alcohol/customs/settings#products', 'Products in Settings'],
    'period-lodgement': ['Filed for you when you record an entry as lodged.', '/compliant/nz-alcohol/customs', 'Excise entry'],
  };
  // An example of where the proof might live, per check.
  var EXAMPLES = {
    'product-mapping': 'e.g. Settings → Products, or Drive / Customs / Product list',
    'period-lodgement': 'e.g. Excise entry EX-26-1007',
    'reconciliation': 'e.g. Drive / Customs / Reconciliations / 2026-09',
    'movement-evidence': 'e.g. Delivery docket DD-4411, or Drive / Customs / Movements',
    'record-retention': 'e.g. Google Workspace (NZ), nightly backup',
  };
  var TYPES = { attestation: 'Attestation', reading: 'Reading', lodgement: 'Lodgement', competency: 'Training', incident: 'Incident' };

  function init() {
    var page = document.querySelector('[data-customs-records-root]') || document.querySelector('[data-customs-record-check-root]');
    if (!page || page.dataset.bound === '1' || !window.CustomsUI) return;
    page.dataset.bound = '1';
    var U = window.CustomsUI;
    var el = U.el, api = U.api, fmtDate = U.fmtDate;
    var fail = U.failer(page);
    var isList = page.hasAttribute('data-customs-records-root');
    var state = { controls: [], records: [] };

    function name(id) { return NAMES[id] || String(id || '').replace(/-/g, ' '); }
    function status(control) {
      if (control.state === 'compliant') return { key: 'good', text: 'Current' };
      if (control.state === 'attention') return { key: 'bad', text: 'Needs attention' };
      return { key: 'warn', text: 'Needs evidence' };
    }
    function recordsFor(id) { return state.records.filter(function (r) { return r.control_id === id; }); }
    function periodText(r) {
      if (!r.period_start) return '';
      var s = new Date(r.period_start + 'T00:00:00'); var e = r.period_end ? new Date(r.period_end + 'T00:00:00') : null;
      if (e && s.getDate() === 1 && s.getMonth() === e.getMonth() && s.getFullYear() === e.getFullYear()) {
        return s.toLocaleDateString('en-NZ', { month: 'long', year: 'numeric' });
      }
      return fmtDate(r.period_start) + (r.period_end ? ' – ' + fmtDate(r.period_end) : '');
    }
    function added(r) { return r.created_at ? fmtDate(String(r.created_at).slice(0, 10)) : ''; }
    function tag(st) { return el('span', { className: 'customs-chip customs-chip--' + ({ good: 'complete', bad: 'failed', warn: 'open' }[st.key]), text: st.text }); }

    // One record as a row: what it is, for which period, and the reference Customs would ask for.
    function recordRow(r) {
      var meta = [TYPES[r.record_type] || r.record_type, periodText(r), r.evidence_reference ? 'Ref ' + r.evidence_reference : null,
        (r.source_refs || []).length ? U.plural(r.source_refs.length, 'production record') + ' linked' : null].filter(Boolean).join(' · ');
      return el('li', { className: 'customs-rec-row' }, [
        el('div', { className: 'customs-rec-row__main' }, [el('strong', { text: r.title }), el('span', { text: meta })]),
        el('span', { className: 'customs-rec-row__date', text: added(r) }),
        el('span', { className: 'customs-chip customs-chip--' + (r.status === 'complete' ? 'complete' : r.status === 'failed' ? 'failed' : 'open'), text: r.status.charAt(0).toUpperCase() + r.status.slice(1) }),
      ]);
    }

    // --- the form: only what this check needs -------------------------------------------------
    function field(label, input, hint) {
      return el('label', { className: 'customs-field' }, [el('span', { className: 'customs-field__label', text: label }), input, hint ? el('span', { className: 'customs-field__hint', text: hint }) : null]);
    }
    function lastMonth() {
      var d = new Date(); var s = new Date(d.getFullYear(), d.getMonth() - 1, 1); var e = new Date(d.getFullYear(), d.getMonth(), 0);
      function iso(x) { return x.getFullYear() + '-' + String(x.getMonth() + 1).padStart(2, '0') + '-' + String(x.getDate()).padStart(2, '0'); }
      return [iso(s), iso(e), s.toLocaleDateString('en-NZ', { month: 'long', year: 'numeric' })];
    }
    function evidenceForm(control, onSaved) {
      var cap = control.capture || {};
      var id = 'rec-' + control.control_id;
      var form = el('form', { className: 'customs-rec-form', 'hx-boost': 'false' });
      var month = lastMonth();
      var title = el('input', { name: 'title', id: id + '-title', required: 'required', maxlength: '255' });
      title.value = name(control.control_id) + (cap.period ? ': ' + month[2] : '');
      form.append(field('What this proves', title));
      var types = cap.record_types || [];
      var type;
      if (types.length > 1) {
        type = el('select', { name: 'record_type', id: id + '-type' });
        types.forEach(function (t) { type.append(el('option', { value: t, text: TYPES[t] || t })); });
        form.append(field('Kind of record', type));
      } else {
        type = el('input', { type: 'hidden', name: 'record_type', value: types[0] || 'attestation' });
        form.append(type);
      }
      var start, end, lal, ref, due, picked = new Map();
      if (cap.period) {
        start = el('input', { type: 'date', name: 'period_start', id: id + '-start', required: 'required' }); start.value = month[0];
        end = el('input', { type: 'date', name: 'period_end', id: id + '-end', required: 'required' }); end.value = month[1];
        form.append(el('div', { className: 'customs-rec-form__row' }, [field('Period from', start), field('to', end)]));
      }
      if ((cap.fields || []).indexOf('declared_litres_of_alcohol') !== -1) {
        lal = el('input', { type: 'number', name: 'declared_litres_of_alcohol', id: id + '-lal', min: '0', step: '0.001', required: 'required' });
        form.append(field('Litres of alcohol declared', lal, 'As lodged for this period.'));
      }
      ref = el('input', { name: 'evidence_reference', id: id + '-ref', maxlength: '1024', placeholder: EXAMPLES[control.control_id] || 'A file location or reference' });
      if (cap.evidence) ref.required = true;
      form.append(field('Where the proof is', ref, 'A file location, entry number or signed record a Customs officer could open.'));
      if (cap.due_date) {
        due = el('input', { type: 'date', name: 'due_date', id: id + '-due', required: 'required' });
        form.append(field('Review or expiry date', due));
      }
      if (cap.source_refs) form.append(productionPicker(picked));
      // Everything else, for the rare record that needs it.
      var more = el('details', { className: 'customs-rec-form__more' }, [el('summary', { text: 'More details' })]);
      var statusSel = el('select', { name: 'status', id: id + '-status' });
      [['complete', 'Complete'], ['open', 'Open: still being worked on'], ['failed', 'Failed']].forEach(function (o) { statusSel.append(el('option', { value: o[0], text: o[1] })); });
      var review = el('select', { name: 'review_interval_months', id: id + '-review' });
      [['', 'No recurring review'], ['1', 'Every month'], ['3', 'Every 3 months'], ['6', 'Every 6 months'], ['12', 'Every year']].forEach(function (o) { review.append(el('option', { value: o[0], text: o[1] })); });
      more.append(el('div', { className: 'customs-rec-form__row' }, [field('Status', statusSel), field('Review again', review)]));
      if (!cap.due_date) {
        due = el('input', { type: 'date', name: 'due_date', id: id + '-due' });
        more.append(field('Review or expiry date', due));
      }
      form.append(more);
      var save = el('button', { type: 'submit', className: 'workspace-button workspace-button--primary', text: 'Save evidence' });
      form.append(save);
      form.addEventListener('submit', async function (e) {
        e.preventDefault(); fail(''); save.disabled = true;
        var dueDate = due && due.value ? due.value : null;
        var months = Number(review.value || 0);
        if (!dueDate && months) { var n = new Date(); n.setMonth(n.getMonth() + months); dueDate = n.toISOString().slice(0, 10); }
        try {
          await api('POST', '/api/compliant/records', {
            framework_slug: FRAMEWORK, control_id: control.control_id, record_type: type.value, status: statusSel.value,
            title: title.value, period_start: start ? start.value : null, period_end: end ? end.value : null, due_date: dueDate,
            declared_litres_of_alcohol: lal ? lal.value : null, evidence_reference: ref.value || null,
            source_refs: Array.from(picked.keys()), details: months ? { review_interval_months: months } : {},
          });
          await onSaved();
        } catch (err) { fail(err.message); save.disabled = false; }
      });
      return form;
    }

    // Production records that prove a movement: search, tick, and they're linked to the record.
    function productionPicker(picked) {
      var wrap = el('fieldset', { className: 'customs-rec-form__picker' }, [el('legend', { text: 'Production records' })]);
      var kind = el('select', { 'aria-label': 'Kind of production record' });
      [['movement', 'Inventory movements'], ['execution', 'Batches'], ['execution-step', 'Completed steps'], ['file', 'Files']].forEach(function (o) { kind.append(el('option', { value: o[0], text: o[1] })); });
      var q = el('input', { type: 'search', placeholder: 'Find by name', maxlength: '100', 'aria-label': 'Find production records' });
      var results = el('div', { className: 'customs-rec-form__results' });
      var chosen = el('p', { className: 'excise-hint', text: 'None linked yet.' });
      async function find() {
        try {
          var data = await api('GET', '/api/compliant/core-sources?kind=' + encodeURIComponent(kind.value) + '&q=' + encodeURIComponent(q.value.trim()) + '&offset=0');
          results.replaceChildren();
          (data.sources || []).slice(0, 8).forEach(function (s) {
            var box = el('input', { type: 'checkbox', value: s.id });
            box.checked = picked.has(s.id);
            box.addEventListener('change', function () {
              if (box.checked) picked.set(s.id, s); else picked.delete(s.id);
              chosen.textContent = picked.size ? U.plural(picked.size, 'record') + ' linked' : 'None linked yet.';
            });
            results.append(el('label', { className: 'customs-rec-form__result' }, [box, document.createTextNode(' ' + s.title)]));
          });
          if (!results.children.length) results.append(el('p', { className: 'excise-hint', text: 'Nothing found.' }));
        } catch (err) { fail(err.message); }
      }
      var go = el('button', { type: 'button', className: 'workspace-button', text: 'Find' });
      go.addEventListener('click', find);
      q.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); find(); } });
      wrap.append(el('div', { className: 'customs-rec-form__search' }, [kind, q, go]), results, chosen);
      return wrap;
    }

    // --- one check: about, evidence we have, record evidence, history -------------------------
    function checkView(control, onSaved) {
      var mine = recordsFor(control.control_id);
      var st = status(control);
      var about = el('section', { className: 'workspace-card customs-card' }, [
        el('div', { className: 'customs-rec-head' }, [el('h2', { text: name(control.control_id) }), tag(st)]),
        el('p', { className: 'workspace-caption', text: control.description }),
        el('h3', { className: 'customs-sub', text: 'What Customs can ask to see' }),
        el('ul', { className: 'customs-plain-list' }, (ASKS[control.control_id] || []).map(function (a) { return el('li', { text: a }); })),
      ]);
      var auto = AUTOMATIC[control.control_id];
      if (auto) about.append(el('p', { className: 'customs-note' }, [document.createTextNode(auto[0] + ' '), el('a', { href: auto[1], text: auto[2] + ' →' })]));
      var latest = mine[0];
      var evidence = el('section', { className: 'workspace-card customs-card' }, [el('h2', { text: 'Evidence we have' })]);
      var facts = el('dl', { className: 'customs-rec-facts' });
      function fact(k, v) { facts.append(el('dt', { text: k }), el('dd', { text: v })); }
      fact('Status', st.text + (control.reason ? ' · ' + control.reason : ''));
      fact('Latest', latest ? latest.title + ' · ' + added(latest) : 'Nothing recorded yet');
      fact('Records', U.plural(mine.length, 'record'));
      evidence.append(facts);
      var record = el('section', { className: 'workspace-card customs-card' }, [el('h2', { text: 'Record evidence' }), evidenceForm(control, onSaved)]);
      var history = el('section', { className: 'workspace-card customs-card' }, [el('h2', { text: 'History' })]);
      history.append(mine.length ? el('ul', { className: 'customs-rec-list' }, mine.map(recordRow)) : el('p', { className: 'excise-hint', text: 'Nothing recorded for this check yet.' }));
      return [about, evidence, record, history];
    }

    async function load() {
      var overview = await api('GET', '/api/compliant/overview');
      var fw = (overview.frameworks || []).find(function (f) { return f.slug === FRAMEWORK; }) || { controls: [] };
      state.controls = fw.controls || [];
      state.records = (await api('GET', '/api/compliant/records?framework=' + FRAMEWORK)).records || [];
    }

    // --- the check's own page ----------------------------------------------------------------
    if (!isList) {
      var target = page.querySelector('[data-records-check]');
      var wanted = page.dataset.controlId;
      var renderCheck = async function () {
        await load();
        var control = state.controls.find(function (c) { return c.control_id === wanted; });
        if (!control) { fail('This Customs check is not available for your organisation.'); return; }
        var leaf = document.querySelector('[data-breadcrumb-leaf]');
        if (leaf) leaf.textContent = name(wanted);
        target.replaceChildren.apply(target, checkView(control, renderCheck));
      };
      renderCheck().catch(function (err) { fail(err.message); }).finally(function () { page.setAttribute('aria-busy', 'false'); });
      return;
    }

    // --- the Records view: one row per check, each opening its own page --------------------------
    var checksEl = page.querySelector('[data-records-checks]');
    var summaryEl = page.querySelector('[data-records-summary]');

    function checkRow(control) {
      var mine = recordsFor(control.control_id);
      var latest = mine[0];
      var line = latest ? 'Latest: ' + latest.title + ' · ' + added(latest) : (control.reason || 'Nothing recorded yet');
      return el('a', { className: 'customs-rec-check', href: BASE + '/' + encodeURIComponent(control.control_id), 'data-control-id': control.control_id }, [
        el('span', { className: 'customs-rec-check__main' }, [el('strong', { text: name(control.control_id) }), el('span', { text: line })]),
        el('span', { className: 'customs-rec-check__count', text: AUTOMATIC[control.control_id] && !mine.length ? 'Automatic' : U.plural(mine.length, 'record') }),
        tag(status(control)),
      ]);
    }

    function render() {
      if (!state.controls.length) {
        summaryEl.removeAttribute('data-loading');
        summaryEl.textContent = 'Switch on the NZ Alcohol module in Compliance settings to keep records for Customs.';
        checksEl.replaceChildren();
        return;
      }
      var current = state.controls.filter(function (c) { return c.state === 'compliant'; }).length;
      summaryEl.removeAttribute('data-loading');
      summaryEl.textContent = current + ' of ' + state.controls.length + ' checks have current proof · ' + U.plural(state.records.length, 'record') + ' kept';
      checksEl.replaceChildren.apply(checksEl, state.controls.map(checkRow));
    }

    load().then(render).catch(function (err) { fail(err.message); }).finally(function () { page.setAttribute('aria-busy', 'false'); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  document.addEventListener('htmx:afterSwap', init);
})();
