// Compliance -> Wine (docs/wine-compliance-plan.md §3.4). Everything shown is computed on the
// server from production records; this page only renders it and saves the plan details.
(function () {
  'use strict';

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'className') node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) node.append(typeof c === 'string' ? document.createTextNode(c) : c); });
    return node;
  }
  function fmtDate(iso) {
    return iso ? new Date(iso.slice(0, 10) + 'T00:00:00').toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' }) : '';
  }
  function num(n, digits) { return Number(n || 0).toLocaleString('en-NZ', { maximumFractionDigits: digits == null ? 0 : digits }); }
  function pct(share) { return Math.round(Number(share || 0) * 100) + '%'; }
  function chip(code, text) { return el('span', { className: 'wine-chip wine-chip--' + code, text: text }); }

  var CLAIM_TEXT = { pass: 'Can name', review: 'Check', fail: 'Under 85%', unknown: 'Not recorded' };
  var ITEM_TEXT = { ok: 'Fine', declare: 'On the label', review: 'Check', missing: 'Missing' };
  var OVERALL = { ready: ['ok', 'Ready'], review: ['review', 'Check'], missing: ['missing', 'Missing records'] };

  async function api(path, body) {
    var csrf = document.querySelector('meta[name="csrf-token"]');
    var response = await fetch(path, {
      method: body ? 'PUT' : 'GET', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf ? csrf.content : '' },
      body: body ? JSON.stringify(body) : undefined,
    });
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(data.error || 'Something went wrong. Try again in a moment.');
    return data;
  }

  function renderPlan(root, plan) {
    var body = root.querySelector('[data-plan-body]');
    var chipEl = root.querySelector('[data-plan-chip]');
    body.replaceChildren();
    if (!plan.configured) {
      chipEl.className = 'wine-chip wine-chip--missing';
      chipEl.textContent = 'Not set';
      body.append(el('p', { className: 'wine-note', text: 'Tell Biz-E whether you run a registered plan or the small winemaker exemption, so it can track the right things.' }));
      if (root.dataset.canManage === '1') body.append(el('button', { type: 'button', className: 'workspace-button', 'data-open-plan': '', text: 'Add plan details' }));
      return;
    }
    if (plan.mode === 'registered') {
      var due = plan.verification_due_days;
      var soon = due != null && due <= 30;
      chipEl.className = 'wine-chip wine-chip--' + (due != null && due < 0 ? 'missing' : soon ? 'review' : 'ok');
      chipEl.textContent = due == null ? 'Registered' : due < 0 ? 'Verification overdue' : soon ? 'Verification soon' : 'Registered';
      var facts = el('dl', { className: 'wine-facts' });
      [['Plan', plan.plan_reference || 'Not recorded'], ['Verifier', plan.verifier || 'Not recorded'],
        ['Next verification', plan.next_verification ? fmtDate(plan.next_verification) + (due != null ? ' (' + (due < 0 ? Math.abs(due) + ' days ago' : 'in ' + due + ' days') + ')' : '') : 'Not recorded'],
        ['Wine made, last 2 years', num(plan.litres_made) + ' L']].forEach(function (row) {
        facts.append(el('div', {}, [el('dt', { text: row[0] }), el('dd', { text: row[1] })]));
      });
      body.append(facts);
      return;
    }
    var share = Math.min(1, Number(plan.exemption_share || 0));
    chipEl.className = 'wine-chip wine-chip--' + (plan.exemption_warning ? 'review' : 'ok');
    chipEl.textContent = plan.exemption_warning ? 'Check the exemption' : 'Exempt';
    var meter = el('div', { className: 'wine-meter' + (share >= 0.8 ? ' wine-meter--warn' : ''), role: 'meter',
      'aria-valuemin': '0', 'aria-valuemax': String(plan.exemption_limit_l), 'aria-valuenow': String(plan.litres_made),
      'aria-label': 'Wine made in the exemption period' }, [el('span')]);
    meter.firstChild.style.width = (share * 100).toFixed(1) + '%';  // CSSOM, not a style attribute: CSP allows it
    body.append(
      el('p', { className: 'wine-meter__label' }, [el('strong', { text: num(plan.litres_made) + ' L' }), ' of 20,000 L made since ' + fmtDate(plan.window_start)]),
      meter,
      el('p', { className: 'wine-note', text: 'Exemption ends ' + fmtDate(plan.exemption_expires) + (plan.exemption_days_left != null ? ' (' + plan.exemption_days_left + ' days). ' : '. ') + 'Renew with MPI or register a WSMP before then. Wine made while exempt can’t be exported.' })
    );
  }

  function claimSummary(c) {
    var parts = [];
    if (c.variety[0]) parts.push(pct(c.variety[0].share) + ' ' + c.variety[0].value);
    if (c.vintage[0]) parts.push(c.vintage[0].value + (c.vintage[0].share < 1 ? ' (' + pct(c.vintage[0].share) + ')' : ''));
    if (c.region[0]) parts.push(c.region[0].value + (c.region[0].share < 1 ? ' (' + pct(c.region[0].share) + ')' : ''));
    return parts.join(' · ') || 'No intake records traced';
  }

  function renderClaims(root, lots) {
    var list = root.querySelector('[data-claims]');
    list.replaceChildren();
    var shown = lots.filter(function (lot) { return lot.composition; });
    if (!shown.length) {
      list.append(el('li', { className: 'wine-empty-row', text: 'Wine lots appear here once a step after intake is recorded.' }));
      return;
    }
    shown.forEach(function (lot) {
      var c = lot.composition;
      var chips = el('div', { className: 'wine-row__chips' });
      ['variety', 'vintage', 'region'].forEach(function (attr) {
        var claim = c.claims[attr];
        chips.append(chip(claim.status === 'pass' ? 'ok' : claim.status === 'unknown' ? 'muted' : 'review',
          attr.charAt(0).toUpperCase() + attr.slice(1) + ': ' + CLAIM_TEXT[claim.status]));
      });
      var meta = [lot.stage, num(lot.quantity, 1) + ' ' + (lot.unit || '')];
      if (c.estimated) meta.push('partly estimated');
      list.append(el('li', { className: 'wine-row' }, [
        el('div', { className: 'wine-row__main' }, [
          el('strong', { text: lot.name }),
          el('span', { className: 'wine-row__summary', text: claimSummary(c) }),
          el('span', { className: 'wine-row__meta', text: meta.join(' · ') }),
        ]),
        chips,
      ]));
    });
  }

  function renderPreflight(root, preflight) {
    var wrap = root.querySelector('[data-preflight]');
    wrap.replaceChildren();
    if (!preflight.length) {
      wrap.append(el('p', { className: 'wine-empty-row', text: 'Bottled lots appear here with their label checklist.' }));
      return;
    }
    var order = { missing: 0, review: 1, ready: 2 };
    preflight.slice().sort(function (a, b) { return order[a.status] - order[b.status]; }).forEach(function (pf) {
      var overall = OVERALL[pf.status] || OVERALL.review;
      var items = el('ul', { className: 'wine-checks' });
      pf.items.forEach(function (item) {
        items.append(el('li', { className: 'wine-check wine-check--' + item.status }, [
          el('span', { className: 'wine-check__label', text: item.label }),
          el('span', { className: 'wine-check__detail', text: item.detail }),
          chip(item.status === 'declare' ? 'declare' : item.status, ITEM_TEXT[item.status] || item.status),
        ]));
      });
      wrap.append(el('article', { className: 'wine-preflight' }, [
        el('div', { className: 'wine-preflight__head' }, [
          el('div', {}, [el('h3', { text: pf.lot.name }), el('p', { text: num(pf.lot.quantity) + ' ' + (pf.lot.unit || '') + (pf.lot.made_at ? ' · bottled ' + fmtDate(pf.lot.made_at) : '') })]),
          chip(overall[0], overall[1]),
        ]),
        items,
      ]));
    });
  }

  function openPlan(root, plan) {
    var dialog = root.querySelector('[data-plan-dialog]');
    if (!dialog) return;
    var form = dialog.querySelector('form');
    form.reset();
    ['plan_reference', 'verifier', 'next_verification', 'exemption_start'].forEach(function (k) { if (plan && plan[k]) form.elements[k].value = plan[k]; });
    var mode = (plan && plan.mode) || 'registered';
    form.querySelector('input[name="mode"][value="' + mode + '"]').checked = true;
    syncMode(form);
    dialog.querySelector('[data-form-error]').hidden = true;
    dialog.showModal();
  }
  function syncMode(form) {
    var mode = (form.querySelector('input[name="mode"]:checked') || {}).value;
    form.querySelectorAll('[data-when]').forEach(function (g) { g.hidden = g.dataset.when !== mode; });
  }

  function init(root) {
    var state = { plan: null };
    var error = root.querySelector('[data-wine-error]');

    async function load() {
      root.setAttribute('aria-busy', 'true');
      try {
        var data = await api('/api/compliant/wine');
        error.hidden = true;
        if (!data.enabled) {
          root.classList.add('wine-off');
          error.textContent = 'Wine isn’t one of your product types. Add it in Compliance configuration to see this page.';
          error.hidden = false;
          return;
        }
        state.plan = data.plan;
        root.querySelector('[data-vintage-year]').textContent = data.vintage.year;
        Object.keys(data.vintage).forEach(function (k) {
          var dd = root.querySelector('[data-stat="' + k + '"]');
          if (!dd) return;
          var v = data.vintage[k];
          dd.textContent = k === 'intake_kg' ? (v >= 1000 ? num(v / 1000, 1) + ' t' : num(v) + ' kg') : k === 'litres_in_tank' ? num(v) + ' L' : num(v);
        });
        root.querySelector('[data-recall-note]').textContent = data.last_recall
          ? 'Last recall or drill opened ' + fmtDate(data.last_recall) + '. Run a drill at least once a year.'
          : 'No recall drill yet. Your plan expects one at least once a year: start one from Trace and recall.';
        renderPlan(root, data.plan);
        renderClaims(root, data.lots);
        renderPreflight(root, data.preflight);
        root.querySelector('[data-wine-empty]').hidden = data.steps.length > 0;
      } catch (e) {
        error.textContent = e.message;
        error.hidden = false;
      } finally {
        root.setAttribute('aria-busy', 'false');
      }
    }

    root.addEventListener('click', function (event) {
      if (event.target.closest('[data-open-plan]')) openPlan(root, state.plan);
      if (event.target.closest('[data-dialog-close]')) event.target.closest('dialog').close();
    });
    var form = root.querySelector('[data-plan-form]');
    if (form) {
      form.addEventListener('change', function () { syncMode(form); });
      form.addEventListener('submit', async function (event) {
        event.preventDefault();
        var data = {};
        new FormData(form).forEach(function (v, k) { if (String(v).trim()) data[k] = String(v).trim(); });
        var err = form.querySelector('[data-form-error]');
        try {
          await api('/api/compliant/wine/plan', data);
          form.closest('dialog').close();
          load();
        } catch (e) {
          err.textContent = e.message;
          err.hidden = false;
        }
      });
    }
    load();
  }

  window.bize.onPage('[data-wine-root]', init);
})();
