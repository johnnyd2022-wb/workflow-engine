/* Production › Costs: stock value, snapshots and the Xero bridge (live-cogs 8.1g).
   Unknown cost is never shown as $0: a total with uncosted stock says "at least". */
(function () {
  'use strict';
  var API = '/api/core/costing';
  var LABELS = { raw: 'Raw materials', in_production: 'In production', wip: 'Work in progress', finished: 'Finished goods' };
  var COMPONENTS = [
    ['cogs', 'Sold (cost of goods sold)'], ['wastage', 'Wasted'], ['samples', 'Samples and tastings'],
    ['variance', 'Stock corrections'], ['production_loss', 'Lost in production'],
    ['estimate_changes', 'Cost changes and estimates'], ['overhead_absorbed', 'Overheads added to stock'], ['other', 'Other'],
  ];

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function $(value) { return (window.BizECost && window.BizECost.money(value)) || '—'; }
  function get(url) {
    return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.error || 'Something went wrong');
        return d;
      });
    });
  }
  function day(iso) {
    var d = new Date(iso + (iso.length === 10 ? 'T12:00:00' : ''));
    return d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' });
  }
  function dayMonth(iso) {
    return new Date(iso + 'T12:00:00').toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' });
  }
  function monthName(iso) {
    return new Date(iso + 'T12:00:00').toLocaleDateString('en-NZ', { month: 'long', year: 'numeric' });
  }
  function title(snap) {
    return snap.kind === 'month_end' ? 'End of ' + monthName(snap.as_of_date) : 'Snapshot ' + day(snap.as_of_date);
  }
  /* Design review L1: a month's value is provisional until it is closed. */
  function provisionalNote(snap) {
    if (!snap.provisional) return '';
    if (snap.closes_on) return 'Provisional until you close it (closes itself on ' + dayMonth(snap.closes_on) + ')';
    return 'Provisional until the month before it is closed';
  }
  function key() { return (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()) + Math.random(); }
  function floorNote(t) {
    var parts = [];
    if (t.unknown_lots) parts.push(t.unknown_lots + (t.unknown_lots === 1 ? ' lot has' : ' lots have') + ' no cost yet');
    if (t.partial_lots) parts.push(t.partial_lots + ' only partly costed');
    return parts.length ? 'At least this much: ' + parts.join(', ') + '.' : '';
  }
  function kv(rows) {
    var dl = el('dl', 'co-kv');
    rows.forEach(function (r) {
      var row = el('div', 'co-kv__row' + (r[2] ? ' co-kv__row--total' : ''));
      row.appendChild(el('dt', '', r[0]));
      row.appendChild(el('dd', '', r[1]));
      dl.appendChild(row);
    });
    return dl;
  }

  function bind() {
    var root = document.querySelector('[data-stock]');
    if (!root || root.getAttribute('data-bound') === '1') return;
    root.setAttribute('data-bound', '1');
    var els = {
      error: root.querySelector('[data-stock-error]'),
      now: root.querySelector('[data-stock-now]'),
      list: root.querySelector('[data-stock-list]'),
      empty: root.querySelector('[data-stock-empty]'),
      take: root.querySelector('[data-stock-snapshot]'),
      sheet: document.querySelector('[data-stock-close-sheet]'),
    };
    var canManage = false;
    function fail(msg) { els.error.textContent = msg; els.error.hidden = false; }

    window.BizECost.me().then(function (who) {
      if (!who || !who.can_view) return;
      canManage = !!who.can_manage && !!els.sheet;
      root.hidden = false;
      load();
    });

    function load() {
      els.error.hidden = true;
      get(API + '/stock-value').then(renderNow).then(loadSnapshots).catch(function (e) {
        fail('Stock value couldn’t load: ' + e.message);
      });
    }

    function renderNow(s) {
      els.now.replaceChildren();
      var total = el('div', 'co-stock__total');
      total.appendChild(el('span', 'co-stock__amount', (s.complete ? '' : 'At least ') + $(s.total)));
      total.appendChild(el('span', 'cost-muted', s.lot_count + (s.lot_count === 1 ? ' lot' : ' lots') + ' on hand'));
      els.now.appendChild(total);
      var cats = el('ul', 'co-stock__cats');
      ['raw', 'in_production', 'wip', 'finished'].forEach(function (key) {
        var c = s.categories[key];
        var li = el('li', 'co-stock__cat');
        li.appendChild(el('span', 'co-stock__cat-label', LABELS[key]));
        li.appendChild(el('span', 'co-stock__cat-value', $(c.value)));
        cats.appendChild(li);
      });
      els.now.appendChild(cats);
      var split = el('p', 'co-stock__split');
      split.appendChild(el('span', '', 'Actual cost ' + $(s.split.actual)));
      split.appendChild(el('span', '', 'Estimated ' + $(s.split.estimated)));
      if (Number(s.split.partial)) split.appendChild(el('span', '', 'Partly costed ' + $(s.split.partial)));
      els.now.appendChild(split);
      var note = floorNote(s);
      if (note) els.now.appendChild(el('p', 'cost-pill cost-pill--warn', note));
    }

    function loadSnapshots() {
      return get(API + '/stock-value/snapshots').then(function (d) {
        var snaps = d.snapshots || [];
        els.list.replaceChildren();
        els.empty.hidden = snaps.length > 0;
        snaps.forEach(function (snap, i) { els.list.appendChild(row(snap, snaps[i + 1] || null)); });
      });
    }

    function row(snap, earlier) {
      var li = el('li', 'co-row');
      var head = el('button', 'co-snap__head');
      head.type = 'button';
      head.setAttribute('aria-expanded', 'false');
      var name = el('span', 'co-snap__title', title(snap));
      name.appendChild(el('span', 'co-snap__sub', 'Taken ' + day(snap.taken_at.slice(0, 10)) + (snap.automatic ? ' automatically' : '') +
        (snap.quantity_basis === 'reconstructed' ? ' · counted back to month end' : '')));
      if (snap.kind === 'month_end' && !snap.provisional && snap.closed_at) {
        name.appendChild(el('span', 'co-snap__sub', 'Closed ' + day(snap.closed_at) + (snap.closed_automatically ? ' automatically' : '')));
      }
      var note = provisionalNote(snap);
      if (note) name.appendChild(el('span', 'co-snap__state cost-pill cost-pill--warn', note));
      head.appendChild(name);
      head.appendChild(el('span', 'co-snap__value', (snap.complete ? '' : 'At least ') + $(snap.total)));
      var chevron = el('span', 'co-row__chevron');
      chevron.setAttribute('aria-hidden', 'true');
      head.appendChild(chevron);
      li.appendChild(head);
      var detail = el('div', 'co-snap__detail');
      detail.hidden = true;
      li.appendChild(detail);
      var loaded = false;
      head.addEventListener('click', function () {
        var open = head.getAttribute('aria-expanded') !== 'true';
        head.setAttribute('aria-expanded', String(open));
        detail.hidden = !open;
        if (open && !loaded) { loaded = true; showDetail(snap, earlier, detail); }
      });
      return li;
    }

    function showDetail(snap, earlier, detail) {
      detail.appendChild(el('p', 'cost-muted', 'Loading…'));
      get(API + '/stock-value/snapshots/' + snap.id).then(function (d) {
        detail.replaceChildren();
        detail.appendChild(kv(['raw', 'in_production', 'wip', 'finished'].map(function (k) {
          return [LABELS[k], $(d.categories[k].value)];
        }).concat([['Total', (d.complete ? '' : 'At least ') + $(d.total), true]])));
        var note = floorNote(d);
        if (note) detail.appendChild(el('p', 'cost-muted', note));
        if (d.provisional) {
          detail.appendChild(el('p', 'cost-muted', 'Not closed yet: these figures use today’s costs, so they change as the month’s bills and card spend are recorded. ' +
            'The stock counted at the end of the month doesn’t change.'));
        }
        var ch = d.changes_since_close;
        if (ch && Number(ch.delta) !== 0) {
          detail.appendChild(el('p', 'cost-pill cost-pill--warn',
            'Changes since close: with today’s costs this stock is ' + $(ch.total_now) + ' (' + (Number(ch.delta) > 0 ? '+' : '') + $(ch.delta) +
            '). The closed figure above stays as it was.'));
        }
        var actions = el('div', 'co-snap__actions');
        if (d.provisional && d.kind === 'month_end' && canManage) {
          var closeBtn = el('button', 'workspace-button workspace-button--primary', 'Close month');
          closeBtn.type = 'button';
          closeBtn.setAttribute('data-stock-close', d.id);
          closeBtn.addEventListener('click', function () { openClose(d, closeBtn); });
          actions.appendChild(closeBtn);
        }
        var csv = el('a', 'workspace-button', d.provisional ? 'Download provisional CSV' : 'Download CSV for your accountant');
        csv.href = API + '/stock-value/snapshots/' + d.id + '/export.csv';
        actions.appendChild(csv);
        if (earlier) {
          var compare = el('button', 'workspace-button', 'Compare with Xero');
          compare.type = 'button';
          var mount = el('div');
          compare.addEventListener('click', function () {
            compare.disabled = true;
            mount.replaceChildren(el('p', 'cost-muted', 'Loading…'));
            get(API + '/bridge?from=' + earlier.id + '&to=' + d.id).then(function (b) { renderBridge(b, mount); })
              .catch(function (e) { mount.replaceChildren(el('p', 'cost-error', 'The comparison couldn’t load: ' + e.message)); })
              .finally(function () { compare.disabled = false; });
          });
          actions.appendChild(compare);
          detail.appendChild(actions);
          detail.appendChild(mount);
        } else {
          detail.appendChild(actions);
        }
      }).catch(function (e) { detail.replaceChildren(el('p', 'cost-error', 'This snapshot couldn’t load: ' + e.message)); });
    }

    function renderBridge(b, mount) {
      mount.replaceChildren();
      var box = el('div', 'co-bridge');
      mount.appendChild(box);
      if (b.state === 'needs_snapshots') {
        box.appendChild(el('p', 'cost-muted', 'The comparison needs two snapshots.'));
        return;
      }
      box.appendChild(el('h4', '', (b.xero && b.xero.state === 'same_day') ? 'What left stock between the two snapshots'
        : 'What left stock, ' + day(b.period.from) + ' to ' + day(b.period.to)));
      if (b.provisional) {
        box.appendChild(el('p', 'co-bridge__state cost-pill cost-pill--warn', 'Provisional: the month isn’t closed, so these figures can still change.'));
      }
      var r = b.roll_forward;
      box.appendChild(kv([['Opening stock', $(r.opening)], ['Bought into stock', $(r.purchases)], ['Closing stock', $(r.closing)],
        ['Cost that left stock', $(r.cost_left), true]]));
      var lines = el('ul', 'co-bridge__lines');
      COMPONENTS.forEach(function (c) {
        var value = r.components[c[0]];
        if (value == null || (Number(value) === 0 && c[0] !== 'cogs')) return; // overhead_absorbed exists only for an org that opted in
        var li = el('li');
        li.appendChild(el('span', '', c[1]));
        li.appendChild(el('span', '', $(value)));
        lines.appendChild(li);
      });
      box.appendChild(lines);
      if (!r.balanced) box.appendChild(el('p', 'cost-pill cost-pill--warn', 'Doesn’t add up by ' + $(r.rounding) + '; check the stock records.'));
      var x = b.xero || {};
      if (x.state === 'not_connected') {
        box.appendChild(el('p', 'cost-muted', 'Xero isn’t connected, so there’s nothing to compare with. Everything above works without it.'));
      } else if (x.state === 'needs_reconnect') {
        box.appendChild(el('p', 'cost-muted', 'Reconnect Xero to let Biz-E read its profit and loss report.'));
      } else if (x.state === 'same_day') {
        box.appendChild(el('p', 'cost-muted', 'These two snapshots are on the same day. Pick snapshots on different days to compare with Xero.'));
      } else if (x.state === 'failed') {
        box.appendChild(el('p', 'cost-error', 'Xero couldn’t be read just now (ref ' + x.ref + ').'));
      } else if (b.tie_out) {
        var t = b.tie_out;
        box.appendChild(el('h4', '', 'Against Xero’s stock accounts'));
        box.appendChild(kv([['Xero stock accounts', $(t.xero_stock_total)], ['Recorded as stock in Biz-E', $(t.recorded)],
          ['Not recorded as stock', $(t.difference), true]]));
        var list = el('ul', 'co-bridge__lines');
        t.not_recorded.forEach(function (n) {
          var li = el('li');
          li.appendChild(el('span', '', day(n.date) + ' · ' + (n.payee || 'Unknown payee') + (n.description ? ' · ' + n.description : '') +
            (n.state === 'not_stock' ? ' (marked not stock)' : '')));
          li.appendChild(el('span', '', $(n.listed)));
          list.appendChild(li);
        });
        if (Number(t.other_entries) !== 0) {
          var o = el('li');
          o.appendChild(el('span', '', 'Other entries in Xero (journals)'));
          o.appendChild(el('span', '', $(t.other_entries)));
          list.appendChild(o);
        }
        box.appendChild(list);
      }
      var duty = b.duty || {};
      if (duty.xero_total != null) {
        box.appendChild(kv([['Xero excise duty', $(duty.xero_total)],
          ['Duty Biz-E worked out', duty.tracked ? (duty.computed != null ? $(duty.computed) : 'Not available') : 'Not tracked']]));
      }
      if (b.overhead && b.overhead.xero_total != null) box.appendChild(kv([['Xero overhead direct costs (not changed)', $(b.overhead.xero_total)]]));
    }

    /* Closing a month: a bottom sheet says what closing means before anything is written. */
    var closing = null;
    if (els.sheet) {
      var form = els.sheet.querySelector('[data-stock-close-form]');
      var sheetError = els.sheet.querySelector('[data-stock-close-error]');
      var confirmBtn = els.sheet.querySelector('[data-stock-close-confirm]');
      var closeKey = null;
      els.sheet.querySelector('[data-stock-close-cancel]').addEventListener('click', closeSheet);
      els.sheet.addEventListener('close', function () { if (closing && closing.opener) closing.opener.focus(); });
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        if (!closing || confirmBtn.disabled) return;
        confirmBtn.disabled = true;
        sheetError.textContent = '';
        window.BizECost.request('POST', API + '/stock-value/snapshots/' + closing.snap.id + '/close', {}, closeKey)
          .then(function () { closing.opener = null; els.sheet.close(); return loadSnapshots(); })
          .catch(function (err) { sheetError.textContent = err.message; })
          .finally(function () { confirmBtn.disabled = false; });
      });
    }
    function openClose(snap, opener) {
      closing = { snap: snap, opener: opener };
      els.sheet.querySelector('[data-stock-close-title]').textContent = 'Close ' + monthName(snap.as_of_date) + '?';
      els.sheet.querySelector('[data-stock-close-total]').textContent = (snap.complete ? '' : 'at least ') + $(snap.total);
      els.sheet.querySelector('[data-stock-close-error]').textContent = '';
      closeKey = key();
      els.sheet.showModal();
      els.sheet.querySelector('[data-stock-close-cancel]').focus();
    }
    function closeSheet() { els.sheet.close(); }

    if (els.take) {
      els.take.addEventListener('click', function () {
        els.take.disabled = true;
        els.error.hidden = true;
        window.BizECost.request('POST', API + '/stock-value/snapshot', {}, key())
          .then(loadSnapshots)
          .catch(function (e) { fail('Couldn’t take a snapshot: ' + e.message); })
          .finally(function () { els.take.disabled = false; });
      });
    }
  }

  bind();
  if (!window.__stockPageListener) {
    window.__stockPageListener = true;
    document.addEventListener('htmx:afterSettle', bind);
  }
})();
