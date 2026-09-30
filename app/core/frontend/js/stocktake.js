// Stocktake (plan 2.6): stock position, count, and a reason for every difference. The
// server does the stock movements and validation; this page collects counts and reasons.
(function () {
  'use strict';

  var REASONS = {
    found_elsewhere: 'Found elsewhere (rep, event, other store)',
    removed_unrecorded: 'Removed but not recorded (tasting, samples, gift, missed sale)',
    broken: 'Broken, damaged or faulty',
    investigating: 'Still looking (hold open 14 days)',
    unexplained_loss: "Can't explain (confirmed loss)",
    returned: 'Came back from a rep or event',
    removal_not_happened: "A recorded removal didn't happen",
    under_recorded: 'Production was under-recorded',
    unexplained_gain: "Can't explain (adjustment)"
  };
  var SHORT = ['found_elsewhere', 'removed_unrecorded', 'broken', 'investigating', 'unexplained_loss'];
  var OVER = ['returned', 'removal_not_happened', 'under_recorded', 'unexplained_gain'];
  var NEEDS_PLACE = { found_elsewhere: true, returned: true };

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  async function api(method, url, body) {
    var headers = { 'Accept': 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET') headers['X-CSRFToken'] = csrfToken();
    var resp = await fetch(url, { method: method, credentials: 'include', headers: headers,
      body: body === undefined ? undefined : JSON.stringify(body) });
    var data = {};
    try { data = await resp.json(); } catch (_) { /* empty */ }
    if (!resp.ok) throw new Error(data.error || ('Request failed (' + resp.status + ')'));
    return data;
  }

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
    if (!iso) return '';
    var d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function signed(v) { return (v && v.charAt(0) !== '-' && v !== '0' ? '+' : '') + v; }

  function init(root) {
    if (!root || root.dataset.stBound === '1') return;
    root.dataset.stBound = '1';
    var $ = function (sel) { return root.querySelector(sel); };
    var canAdjust = root.dataset.canAdjust === '1';
    var canManage = root.dataset.canManage === '1';
    var current = null;
    var labels = {};

    function applyLabels(next) {
      labels = next || {};
      var visit = $('[data-st-start="customs_visit"]');
      visit.textContent = labels.authority ? labels.authority + ' is here' : 'Inspector is here';
      $('[data-st-position-hint]').textContent = 'Finished goods and work in progress by place and batch' +
        (labels.measure_long ? ', with ' + labels.measure_long + '. The download adds your ' + labels.declared_long + '.' : '.');
    }

    function say(text, ok) {
      var m = $('[data-st-message]');
      m.textContent = text;
      m.className = 'st-message ' + (ok ? 'st-message--ok' : 'st-message--error');
      m.hidden = !text;
    }
    function fail(err) { console.error(err); say(err.message || String(err), false); }

    function showHome(show) {
      root.querySelectorAll('[data-st-home]').forEach(function (n) { n.hidden = !show; });
      $('[data-st-count-view]').hidden = show;
      $('[data-st-recon-view]').hidden = show;
    }

    // --- home -----------------------------------------------------------------------------
    async function loadHome() {
      showHome(true);
      var list = await api('GET', '/api/core/stocktakes');
      applyLabels(list.labels);
      var s = list.schedule;
      var text = 'Count every ' + { monthly: 'month', quarterly: 'quarter', six_monthly: 'six months', annual: 'year' }[s.frequency] + '. ';
      text += s.last_completed_on ? 'Last finished ' + fmtDate(s.last_completed_on) + '. ' : 'No stocktake finished yet. ';
      if (s.next_due) text += (s.overdue ? 'Overdue since ' : 'Next due ') + fmtDate(s.next_due) + '.';
      $('[data-st-schedule-text]').textContent = text;
      $('[data-st-frequency]').value = s.frequency;
      $('[data-st-schedule-form]').hidden = !canManage;
      $('[data-st-start-actions]').hidden = !canAdjust;

      var variances = $('[data-st-variances]');
      variances.replaceChildren();
      list.open_variances.forEach(function (v) {
        var money = v.measure ? ' · ' + v.measure + ' ' + labels.measure + (v.cost ? ', $' + v.cost + ' ' + labels.cost : '') : '';
        var state = v.status === 'investigating' ? 'investigating until ' + fmtDate(v.investigate_until) : 'not resolved';
        var a = el('a', { href: '?id=' + v.stocktake_id, text: v.product + (v.batch ? ' (' + v.batch + ')' : '') });
        a.addEventListener('click', function (e) { e.preventDefault(); openStocktake(v.stocktake_id); });
        variances.append(el('li', {}, [a, ' ' + signed(v.variance) + ' ' + v.unit + money + ' · ' + state,
          v.overdue ? el('span', { className: 'st-chip st-chip--bad', text: 'Overdue' }) : null]));
      });
      $('[data-st-variances-wrap]').hidden = !list.open_variances.length;

      var historyList = $('[data-st-history]');
      historyList.replaceChildren();
      list.stocktakes.forEach(function (st) {
        var a = el('a', { href: '?id=' + st.id, text: fmtDate(st.counted_on) + (st.kind === 'customs_visit' ? ' · ' + (labels.authority || 'Inspector') + ' visit' : '') });
        a.addEventListener('click', function (e) { e.preventDefault(); openStocktake(st.id); });
        historyList.append(el('li', {}, [a, ' ', el('span', { className: 'st-chip' + (st.status === 'done' ? ' st-chip--ok' : ' st-chip--warn'),
          text: st.status === 'done' ? 'Finished' : 'In progress' })]));
      });
      $('[data-st-history-wrap]').hidden = !list.stocktakes.length;
      loadPosition().catch(fail);
    }

    async function loadPosition() {
      var pos = await api('GET', '/api/core/stock-position');
      var wrap = $('[data-st-position]');
      wrap.replaceChildren();
      if (!pos.places.length) { wrap.append(el('p', { className: 'st-hint', text: 'No finished goods or work in progress on hand.' })); return; }
      pos.places.forEach(function (place) {
        var area = labels.controlled_area || 'controlled area';
        wrap.append(el('h3', { text: place.name + (place.inside_licensed_area ? '' : ' (outside the ' + area + ')') +
          (labels.measure ? ' · ' + place.total_measure + ' ' + labels.measure : '') }));
        var body = el('tbody');
        place.lots.forEach(function (lot) {
          body.append(el('tr', {}, [
            el('td', { text: lot.name }), el('td', { text: lot.batch || '—' }), el('td', { text: lot.stage }),
            el('td', { className: 'st-num', text: lot.quantity + ' ' + lot.unit }),
            labels.measure ? el('td', { text: lot.detail || '—' }) : null,
            labels.measure ? el('td', { className: 'st-num', text: lot.measure || '—' }) : null
          ]));
        });
        wrap.append(el('div', { className: 'st-table-wrap' }, [el('table', { className: 'st-table' }, [
          el('thead', {}, [el('tr', {}, [el('th', { text: 'Product' }), el('th', { text: 'Batch' }), el('th', { text: 'Stage' }),
            el('th', { className: 'st-num', text: 'Quantity' }),
            labels.measure ? el('th', { text: 'Detail' }) : null,
            labels.measure ? el('th', { className: 'st-num', text: labels.measure }) : null])]),
          body])]));
      });
    }

    // --- counting -------------------------------------------------------------------------
    async function openStocktake(id) {
      say('');
      current = await api('GET', '/api/core/stocktakes/' + encodeURIComponent(id));
      applyLabels(current.labels);
      history.replaceState(null, '', '?id=' + encodeURIComponent(id));
      showHome(false);
      renderCount();
      loadRecon().catch(fail);
    }

    function lineSummary(sum) {
      var parts = [sum.lines + ' lines'];
      if (sum.not_counted) parts.push(sum.not_counted + ' to count');
      if (sum.to_resolve) parts.push(sum.to_resolve + ' to resolve');
      if (sum.investigating) parts.push(sum.investigating + ' under investigation');
      if (sum.raise_with_customs) parts.push(sum.raise_with_customs + ' to raise with ' + (labels.authority || 'the regulator'));
      return parts.join(' · ');
    }

    function renderCount() {
      var st = current;
      $('[data-st-count-title]').textContent = (st.kind === 'customs_visit' ? (labels.authority || 'Inspector') + ' visit count, ' : 'Stocktake, ') + fmtDate(st.counted_on);
      $('[data-st-count-summary]').textContent = lineSummary(st.summary) + (st.status === 'done' ? ' · Finished' : '');
      var wrap = $('[data-st-lines]');
      wrap.replaceChildren();
      var lastPlace = null;
      st.lines.forEach(function (line) {
        if (line.place !== lastPlace) {
          wrap.append(el('div', { className: 'st-place', text: line.place + (line.inside_licensed_area ? '' : ' (outside)') }));
          lastPlace = line.place;
        }
        wrap.append(renderLine(line));
      });
      var finished = st.status === 'done';
      $('[data-st-complete-wrap]').hidden = finished || !canAdjust || st.summary.not_counted > 0 || st.summary.to_resolve > 0;
      applyFind();
    }

    function toResolve(line) { return line.status === 'open' && line.counted !== null && line.variance !== '0'; }

    function statusChip(line) {
      if (line.counted === null) return el('span', { className: 'st-chip', text: 'Not counted' });
      if (line.status === 'matched') return el('span', { className: 'st-chip st-chip--ok', text: 'Matches' });
      if (line.status === 'resolved') return el('span', { className: 'st-chip st-chip--ok', text: 'Resolved' });
      if (line.status === 'investigating') return el('span', { className: 'st-chip st-chip--warn', text: 'Investigating until ' + fmtDate(line.investigate_until) });
      return el('span', { className: 'st-chip st-chip--bad', text: 'Difference to resolve' });
    }

    function renderLine(line) {
      var box = el('div', { className: 'st-line' + (toResolve(line) ? ' st-line--open' : ''), 'data-line-id': line.id,
        'data-find': (line.name + ' ' + (line.batch || '')).toLowerCase() });
      var variance = '';
      if (line.variance !== null && line.variance !== '0') {
        variance = ' · difference ' + signed(line.variance) + ' ' + line.unit;
        if (line.variance_measure) variance += ' (' + signed(line.variance_measure) + ' ' + labels.measure +
          (line.variance_cost ? ', $' + line.variance_cost.replace('-', '') + ' ' + labels.cost : '') + ')';
      }
      box.append(el('div', {}, [
        el('div', { className: 'st-line-name', text: line.name + (line.batch ? ' · ' + line.batch : '') }),
        el('div', { className: 'st-line-meta' }, ['Expected ' + line.expected + ' ' + line.unit + variance + ' ', statusChip(line)])
      ]));
      var editable = canAdjust && (current.status !== 'done' || line.status === 'investigating') && line.status !== 'resolved';
      if (editable) {
        var input = el('input', { type: 'number', min: '0', step: line.whole_units ? '1' : 'any', inputmode: line.whole_units ? 'numeric' : 'decimal',
          'aria-label': 'Counted ' + line.name + (line.batch ? ' ' + line.batch : ''), value: line.counted === null ? '' : line.counted });
        var save = el('button', { type: 'button', className: 'btn btn-secondary', text: line.counted === null ? 'Save' : 'Recount' });
        async function submit() {
          if (input.value === '') return;
          save.disabled = true;
          try {
            current = await api('PUT', '/api/core/stocktakes/' + current.id + '/lines/' + line.id, { counted: input.value });
            renderCount();
            loadRecon().catch(fail);
            var next = root.querySelector('.st-line[data-line-id="' + line.id + '"]');
            var after = next && next.nextElementSibling;
            while (after && !after.querySelector('input[type="number"]')) after = after.nextElementSibling;
            if (after) after.querySelector('input[type="number"]').focus();
            say('');
          } catch (err) { fail(err); save.disabled = false; }
        }
        save.addEventListener('click', submit);
        input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); submit(); } });
        box.append(el('div', { className: 'st-count' }, [input, save]));
      } else {
        box.append(el('div', { className: 'st-count', text: line.counted === null ? '' : 'Counted ' + line.counted }));
      }
      if (line.resolutions.length) {
        var ul = el('ul', { className: 'st-done-list' });
        line.resolutions.forEach(function (r) {
          var bits = [r.quantity + ' ' + line.unit + ': ' + (REASONS[r.reason] || r.reason)];
          if (r.place) bits.push(r.place);
          if (r.dutiable) bits.push('dutiable removal');
          if (r.raise_with_customs) bits.push(r.reason === 'broken' ? 'claim remission' : 'raise with ' + (labels.authority || 'the regulator'));
          if (r.note) bits.push(r.note);
          ul.append(el('li', { text: bits.join(' · ') }));
        });
        box.append(el('div', { className: 'st-resolve' }, [ul]));
      }
      if (toResolve(line) && canAdjust) box.append(renderResolve(line));
      return box;
    }

    function reasonOrder(line) {
      var short = line.variance.charAt(0) === '-';
      var list = (short ? SHORT : OVER).slice();
      var hasPlaces = current.places.length > 0;
      if (!hasPlaces) list = list.filter(function (r) { return !NEEDS_PLACE[r]; });
      if (!short && !hasPlaces) list.unshift(list.splice(list.indexOf('under_recorded'), 1)[0]);
      return list;
    }

    function renderResolve(line) {
      var wrap = el('div', { className: 'st-resolve' });
      var total = line.variance.replace('-', '');
      wrap.append(el('div', { className: 'st-line-meta', text: 'Explain the ' + total + ' ' + line.unit + (line.variance.charAt(0) === '-' ? ' short' : ' over') +
        '. Split it across reasons if you need to.' }));
      var partsBox = el('div');
      wrap.append(partsBox);
      var order = reasonOrder(line);
      function addPart(qty) {
        var reason = el('select', { 'aria-label': 'Reason' }, order.map(function (r) { return el('option', { value: r, text: REASONS[r] }); }));
        var quantity = el('input', { type: 'number', min: '0', step: line.whole_units ? '1' : 'any', value: qty || '', 'aria-label': 'Quantity' });
        var place = el('select', { 'aria-label': 'Place' }, [el('option', { value: '', text: 'Where?' })].concat(current.places
          .filter(function (p) { return p.id !== line.place_id; })
          .map(function (p) { return el('option', { value: p.id, text: p.name + (p.inside_licensed_area ? '' : ' (outside)') }); })));
        var when = el('input', { type: 'date', 'aria-label': 'Date it happened', max: new Date().toISOString().slice(0, 10) });
        var note = el('input', { type: 'text', maxlength: '500', placeholder: 'Note', 'aria-label': 'Note' });
        var remove = el('button', { type: 'button', className: 'st-remove', 'aria-label': 'Remove this reason', text: '×' });
        var row = el('div', { className: 'st-part' }, [
          el('label', { className: 'st-field' }, ['Reason', reason]),
          el('label', { className: 'st-field' }, ['Qty', quantity]),
          el('label', { className: 'st-field' }, ['Place', place]),
          el('label', { className: 'st-field' }, ['Date', when]),
          el('label', { className: 'st-field' }, ['Note', note]),
          remove]);
        function syncPlace() { place.parentNode.hidden = !NEEDS_PLACE[reason.value]; }
        reason.addEventListener('change', syncPlace);
        remove.addEventListener('click', function () { if (partsBox.children.length > 1) row.remove(); });
        syncPlace();
        row._value = function () {
          var v = { reason: reason.value, quantity: quantity.value, note: note.value };
          if (NEEDS_PLACE[reason.value]) v.location_id = place.value;
          if (when.value) v.occurred_on = when.value;
          return v;
        };
        partsBox.append(row);
      }
      addPart(total);
      var more = el('button', { type: 'button', className: 'st-link-btn', text: 'Split across another reason' });
      more.addEventListener('click', function () { addPart(''); });
      var go = el('button', { type: 'button', className: 'btn btn-primary', text: 'Resolve' });
      go.addEventListener('click', async function () {
        go.disabled = true;
        try {
          var reasons = Array.prototype.map.call(partsBox.children, function (r) { return r._value(); });
          current = await api('POST', '/api/core/stocktakes/' + current.id + '/lines/' + line.id + '/resolve', { reasons: reasons });
          renderCount();
          loadRecon().catch(fail);
          say('Recorded.', true);
        } catch (err) { fail(err); go.disabled = false; }
      });
      wrap.append(el('div', { className: 'st-row' }, [more, go]));
      return wrap;
    }

    function applyFind() {
      var q = ($('[data-st-find]').value || '').trim().toLowerCase();
      root.querySelectorAll('.st-line').forEach(function (n) { n.hidden = q && n.dataset.find.indexOf(q) === -1; });
    }

    async function loadRecon() {
      var rec = await api('GET', '/api/core/stocktakes/' + current.id + '/reconciliation');
      $('[data-st-recon-hint]').textContent = (rec.since ? 'Since the stocktake on ' + fmtDate(rec.since) : 'Since tracking began') +
        '. Opening + produced and in − removed − losses = expected.' + (rec.labels.flows ? ' ' + rec.labels.flows + '.' : '');
      $('[data-st-recon-declared]').textContent = rec.labels.declared || '';
      $('[data-st-recon-declared]').hidden = !rec.labels.declared;
      var body = $('[data-st-recon-rows]');
      body.replaceChildren();
      rec.products.forEach(function (p) {
        var diff = p.variance === null ? 'counting' : signed(p.variance);
        body.append(el('tr', {}, [el('td', { text: p.product }),
          el('td', { className: 'st-num', text: p.opening === null ? '—' : p.opening }),
          el('td', { className: 'st-num', text: p.produced_and_in === null ? '—' : p.produced_and_in }),
          el('td', { className: 'st-num', text: p.removed }), el('td', { className: 'st-num', text: p.losses }),
          el('td', { className: 'st-num', text: p.expected + ' ' + p.unit }),
          el('td', { className: 'st-num', text: p.counted === null ? '—' : p.counted }),
          el('td', { className: 'st-num', text: diff }),
          el('td', { className: 'st-num', text: p.variance === null || p.variance === '0' ? '—' : signed(p.explained) }),
          rec.labels.declared ? el('td', { className: 'st-num', text: p.declared || '—' }) : null]));
      });
    }

    // --- actions --------------------------------------------------------------------------
    root.querySelectorAll('[data-st-start]').forEach(function (b) {
      b.addEventListener('click', async function () {
        b.disabled = true;
        try {
          var st = await api('POST', '/api/core/stocktakes', { kind: b.dataset.stStart });
          await openStocktake(st.id);
        } catch (err) { fail(err); } finally { b.disabled = false; }
      });
    });
    $('[data-st-save-schedule]').addEventListener('click', async function () {
      try {
        var body = { frequency: $('[data-st-frequency]').value };
        if ($('[data-st-tolerance]').value !== '') body.bulk_tolerance_percent = $('[data-st-tolerance]').value;
        await api('PUT', '/api/core/stocktake-settings', body);
        say('Schedule saved.', true);
        loadHome().catch(fail);
      } catch (err) { fail(err); }
    });
    $('[data-st-back]').addEventListener('click', function () {
      current = null;
      history.replaceState(null, '', location.pathname);
      say('');
      loadHome().catch(fail);
    });
    $('[data-st-find]').addEventListener('input', applyFind);
    $('[data-st-find]').addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      var hit = Array.prototype.find.call(root.querySelectorAll('.st-line'), function (n) { return !n.hidden; });
      var input = hit && hit.querySelector('input[type="number"]');
      if (input) input.focus();
    });
    $('[data-st-complete]').addEventListener('click', async function () {
      try {
        current = await api('POST', '/api/core/stocktakes/' + current.id + '/complete');
        renderCount();
        say('Stocktake finished.', true);
      } catch (err) { fail(err); }
    });

    var id = new URLSearchParams(location.search).get('id');
    (id ? openStocktake(id) : loadHome()).catch(fail);
  }

  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  bize.onPage('[data-stocktake-root]', init);
})();
