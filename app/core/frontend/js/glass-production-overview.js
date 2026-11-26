/* GLASS PROTOTYPE: the Production overview (/core) drawn as mockup 22.
 *
 * Reads only what the page already loads: the hub overview that core2-page.js publishes
 * (`core2:hub-overview`), /api/core/dashboard/summary, and the signed-in user's first name
 * from the template. core2-page.js keeps filling the ids it owns (metrics, the health state,
 * the page actions); this script draws the greeting, the health ring and checks, In progress,
 * Under way and Recent activity. Bound to the page root, so a second boosted visit binds again.
 */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var STEP_COLOURS = ['var(--accent)', 'var(--warn)', 'var(--ok)', 'var(--night)', 'var(--dusk)', 'var(--dawn)'];
  var SKY = {
    night: { colour: 'var(--night)', path: '<path fill="currentColor" d="M19 15A8 8 0 0 1 9 5a8 8 0 1 0 10 10z"/>' },
    dawn: { colour: 'var(--dawn)', path: '<path fill="currentColor" d="M6.5 17a5.5 5.5 0 0 1 11 0z"/><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M2.5 20.5h19M12 3v5M9.5 5.5L12 3l2.5 2.5"/>' },
    day: { colour: 'var(--sol)', path: '<circle cx="12" cy="12" r="4" fill="currentColor"/><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/>' },
    dusk: { colour: 'var(--dusk)', path: '<path fill="currentColor" d="M6.5 17a5.5 5.5 0 0 1 11 0z"/><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M2.5 20.5h19M12 3v5M9.5 5.5L12 8l2.5-2.5"/>' },
  };
  var CHEVRON = '<svg xmlns="http://www.w3.org/2000/svg" class="gpo-go" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6"/></svg>';
  var TICK = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
  var FEED_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M9 6h11M9 12h11M9 18h11M4 6h.1M4 12h.1M4 18h.1"/></svg>';
  var CAL_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15.5" rx="2.5" fill="none" stroke="currentColor" stroke-width="2"/><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M3.5 10h17M8 3v4M16 3v4"/></svg>';

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function svgEl(tag, attrs) {
    var e = document.createElementNS(NS, tag);
    Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    return e;
  }
  // Static icon markup (constants in this file, never data) parsed into nodes.
  function svgFrom(markup) {
    var doc = new DOMParser().parseFromString(markup, 'image/svg+xml');
    return document.importNode(doc.documentElement, true);
  }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }

  // Equal arcs with a gap and round caps, as the mockup draws them.
  function ring(svg, size, r, w, colours, gap) {
    svg.replaceChildren();
    var c = size / 2;
    var C = 2 * Math.PI * r;
    svg.appendChild(svgEl('circle', { cx: c, cy: c, r: r, 'stroke-width': w, fill: 'none', stroke: 'var(--edge)' }));
    if (!colours.length) return;
    var per = C / colours.length;
    colours.forEach(function (colour, i) {
      var len = Math.max(per - gap - w, 0.01);
      svg.appendChild(svgEl('circle', {
        class: 'gpo-arc', fill: 'none', 'stroke-linecap': 'round', cx: c, cy: c, r: r, 'stroke-width': w, stroke: colour,
        'stroke-dasharray': len + ' ' + (C - len), 'stroke-dashoffset': -(i * per + (gap + w) / 2),
      }));
    });
  }

  function nzHour() {
    try {
      var parts = new Intl.DateTimeFormat('en-NZ', { timeZone: 'Pacific/Auckland', hour: 'numeric', hourCycle: 'h23' }).formatToParts(new Date());
      return Number(parts.find(function (p) { return p.type === 'hour'; }).value);
    } catch (e) {
      return new Date().getHours();
    }
  }

  function shortDate(iso) {
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d)) return '';
    return d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' });
  }

  function whenLabel(iso) {
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d)) return '';
    return d.toLocaleDateString('en-NZ', { weekday: 'short' }) + ' ' + d.toLocaleTimeString('en-NZ', { hour: 'numeric', minute: '2-digit' });
  }

  function bind(root) {
    if (root.dataset.gpoBound === '1') return;
    root.dataset.gpoBound = '1';

    var q = function (sel) { return root.querySelector(sel); };
    var state = { hub: null, summary: null, step: '', period: 'week' };
    var actions = document.getElementById('core2-journey-actions');
    var canRecord = !!actions && actions.dataset.canRecord === 'true';

    function greet() {
      var hour = nzHour();
      var name = (root.dataset.gpoFirstName || '').trim();
      var who = name ? ' ' + name : '';
      var opsToday = state.summary && state.summary.audit_log && state.summary.audit_log.day ? Number(state.summary.audit_log.day.total || 0) : 0;
      var msg;
      if (hour < 7) msg = 'Up early' + (name ? ', ' + name : '') + '. Thanks for getting a head start';
      else if (hour < 12) msg = 'Good morning' + who + ', let’s get to work';
      else if (hour < 17) msg = opsToday >= 3 ? 'Good afternoon' + who + ', looks like a productive day' : 'Good afternoon' + who + ', let’s keep things moving';
      else msg = 'Good evening' + who + ', working late I see';
      var sky = hour >= 20 || hour < 5 ? SKY.night : hour < 9 ? SKY.dawn : hour < 17 ? SKY.day : SKY.dusk;
      var icon = q('[data-gpo-sky]');
      if (icon) {
        icon.style.setProperty('--gc', sky.colour);
        icon.replaceChildren(svgFrom('<svg xmlns="' + NS + '" width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">' + sky.path + '</svg>'));
      }
      var text = q('[data-gpo-greeting]');
      if (text) text.textContent = msg;
    }

    function batches() {
      var list = (state.hub && state.hub.workflows && state.hub.workflows.active_executions) || [];
      return list.map(function (e) {
        var steps = e.steps || [];
        var total = Number(e.total_steps || steps.length || 0);
        var done = steps.filter(function (s) { return s && s.status === 'completed'; }).length;
        var started = e.started_at ? new Date(e.started_at) : null;
        if (started && isNaN(started)) started = null;
        var days = started ? Math.max(0, Math.round((Date.now() - started.getTime()) / 86400000)) : null;
        var step = e.current_step && e.current_step.name ? e.current_step.name : '';
        return {
          id: String(e.id || ''),
          name: e.process_name || 'Untitled workflow',
          started: started ? shortDate(e.started_at) : '',
          days: days,
          step: step,
          stepNumber: e.current_step ? e.current_step.step_number : Math.min(done + 1, total),
          done: done,
          total: total,
          href: '/core/flows/batches/start?id=' + encodeURIComponent(String(e.process_id || '')) + '&execution_id=' + encodeURIComponent(String(e.id || '')),
        };
      }).sort(function (a, b) { return (b.days == null ? -1 : b.days) - (a.days == null ? -1 : a.days); });
    }

    function stepColours(list) {
      var map = {};
      var i = 0;
      list.forEach(function (b) {
        var key = b.step || 'No step ready';
        if (!(key in map)) { map[key] = STEP_COLOURS[i % STEP_COLOURS.length]; i++; }
      });
      return map;
    }

    function renderHealth() {
      var hub = state.hub;
      if (!hub) return;
      var inv = hub.inventory || {};
      var expiry = inv.expiry || {};
      var ops = state.summary && state.summary.operations;
      var gaps = inv.traceability_gaps || [];
      var checks = [
        { n: Number(expiry.expired || 0), label: 'Expired stock', tone: 'bad', hint: 'Remove or assess before it is used', clear: 'None expired', href: '/core/inventory/live' },
        { n: ops ? Number(ops.stalled_active_over_48h || 0) : null, label: 'Idle over 48 hours', tone: 'warn', hint: 'Batches with no step in two days', clear: 'Every batch has moved', href: '/core/executions/live' },
        { n: Number(expiry.d0_7 || 0), label: 'Expires in 7 days', tone: 'warn', hint: 'Use, hold, or plan disposal', clear: 'Nothing due to expire', href: '/core/inventory/live' },
        { n: Number(inv.low_stock || 0), label: 'Low stock lines', tone: 'warn', hint: 'Check what needs replenishing', clear: 'None', href: '/core/inventory/live' },
        {
          n: Math.max(0, Number(inv.nonzero_lines || 0) - Number(inv.linked || 0)), label: 'Missing a trace link', tone: 'warn',
          hint: gaps.length ? gaps.slice(0, 2).map(function (g) { return g.name; }).join(', ') : 'Add a supplier batch or production link',
          clear: 'All ' + plural(Number(inv.nonzero_lines || 0), 'line') + ' linked', href: '/core/notifications',
        },
      ];
      // The idle check comes from the summary; if that could not load, leave it out rather than wait forever.
      if (state.summary && !ops) checks.splice(1, 1);
      var known = checks.filter(function (c) { return c.n !== null; });
      var clearCount = known.filter(function (c) { return !c.n; }).length;

      var host = q('[data-gpo-checks]');
      if (host) {
        host.replaceChildren();
        checks.forEach(function (c) {
          var tone = c.n === null ? 'wait' : c.n ? c.tone : 'clear';
          var a = el('a', 'gpo-check gpo-t-' + tone);
          a.href = c.href;
          var n = el('span', 'gpo-n');
          if (tone === 'clear') { n.appendChild(svgFrom(TICK)); n.appendChild(el('span', 'prod-visually-hidden', 'Clear')); }
          else n.textContent = c.n === null ? '…' : String(c.n);
          a.appendChild(n);
          var t = el('span');
          t.appendChild(el('b', null, c.label));
          t.appendChild(el('small', null, c.n === null ? 'Checking…' : c.n ? c.hint : c.clear));
          a.appendChild(t);
          a.appendChild(svgFrom(CHEVRON));
          host.appendChild(a);
        });
      }

      var svg = q('[data-gpo-halo-svg]');
      if (svg) ring(svg, 200, 84, 16, checks.map(function (c) {
        return c.n === null ? 'var(--line)' : c.n ? 'var(--' + c.tone + ')' : 'var(--ok)';
      }), 8);
      var score = q('[data-gpo-halo-score]');
      if (score) score.replaceChildren(String(clearCount), el('small', null, '/' + checks.length));
      var halo = q('[data-gpo-halo]');
      if (halo) {
        var open = known.filter(function (c) { return c.n; }).map(function (c) { return c.label.toLowerCase(); });
        halo.setAttribute('aria-label', clearCount + ' of ' + checks.length + ' health checks clear.' + (open.length ? ' Needs attention: ' + open.join(', ') + '.' : ''));
      }
    }

    function renderToday(list) {
      var count = list.length;
      var countEl = q('[data-gpo-active-count]');
      if (countEl) countEl.textContent = String(count);
      var word = q('[data-gpo-active-word]');
      if (word) word.textContent = count === 1 ? 'batch' : 'batches';
      var lede = q('[data-gpo-lede]');
      if (lede) {
        var oldest = list[0];
        lede.textContent = !count ? 'Nothing is under way. Start a batch from a product workflow when work begins.' :
          'The oldest, ' + oldest.name + (oldest.started ? ' started ' + oldest.started : '') + ', is ' +
          (oldest.step ? 'at ' + oldest.step.toLowerCase() : 'waiting for its next step') + '.';
      }
      var oldestEl = q('[data-production-oldest]');
      if (oldestEl && list[0] && list[0].days != null) {
        oldestEl.textContent = plural(list[0].days, 'day');
        oldestEl.classList.toggle('is-hot', list[0].days >= 30);
      }
      var oldestName = q('[data-production-oldest-name]');
      if (oldestName && list[0]) oldestName.textContent = list[0].name + (list[0].started ? ', started ' + list[0].started : '');

      var chips = q('[data-gpo-chips]');
      if (!chips) return;
      chips.replaceChildren();
      chips.hidden = !count;
      if (!count) return;
      var colours = stepColours(list);
      var counts = {};
      list.forEach(function (b) { var k = b.step || 'No step ready'; counts[k] = (counts[k] || 0) + 1; });
      var all = el('button', 'gpo-chip');
      all.type = 'button';
      all.dataset.step = '';
      all.append('All ');
      all.appendChild(el('b', null, String(count)));
      chips.appendChild(all);
      Object.keys(counts).forEach(function (k) {
        var b = el('button', 'gpo-chip');
        b.type = 'button';
        b.dataset.step = k;
        var dot = el('i');
        dot.setAttribute('aria-hidden', 'true');
        dot.style.setProperty('--c', colours[k]);
        b.appendChild(dot);
        b.append(k + ' ');
        b.appendChild(el('b', null, String(counts[k])));
        chips.appendChild(b);
      });
      syncChips();
    }

    function syncChips() {
      root.querySelectorAll('[data-gpo-chips] .gpo-chip').forEach(function (c) {
        c.setAttribute('aria-pressed', c.dataset.step === state.step ? 'true' : 'false');
      });
    }

    function renderRows(list) {
      var host = q('[data-gpo-rows]');
      var cap = q('[data-gpo-rows-cap]');
      if (!host) return;
      host.replaceChildren();
      if (!list.length) {
        if (cap) cap.textContent = 'No batches are under way right now.';
        return;
      }
      var colours = stepColours(list);
      var shown = 0;
      list.forEach(function (b, i) {
        var key = b.step || 'No step ready';
        var row = el('article', 'gpo-row' + (i === 0 ? ' is-first' : ''));
        row.dataset.executionId = b.id;
        row.hidden = !!state.step && state.step !== key;
        if (!row.hidden) shown++;

        var prod = el('div', 'gpo-prod');
        var mini = el('span', 'gpo-mini');
        mini.setAttribute('role', 'img');
        mini.setAttribute('aria-label', b.total ? b.done + ' of ' + b.total + ' steps done' : 'No steps yet');
        var ms = svgEl('svg', { viewBox: '0 0 44 44', 'aria-hidden': 'true' });
        var segs = [];
        for (var s = 1; s <= b.total; s++) segs.push(s <= b.done ? 'var(--accent)' : s === b.done + 1 ? colours[key] : 'var(--edge)');
        ring(ms, 44, 18, 4.5, segs, b.total > 12 ? 1 : 4);
        mini.appendChild(ms);
        var mnum = el('span', 'gpo-mini__n', b.total ? String(b.done) : '–');
        mnum.setAttribute('aria-hidden', 'true');
        mini.appendChild(mnum);
        prod.appendChild(mini);
        var pt = el('div');
        pt.appendChild(el('b', null, b.name));
        pt.appendChild(el('small', null, b.started ? 'Started ' + b.started : 'Not started'));
        prod.appendChild(pt);
        row.appendChild(prod);

        var at = el('div', 'gpo-at');
        var dot = el('i');
        dot.setAttribute('aria-hidden', 'true');
        dot.style.setProperty('--c', colours[key]);
        at.appendChild(dot);
        var att = el('div');
        att.appendChild(el('b', null, b.step || 'No step is ready to record'));
        att.appendChild(el('small', null, b.total ? 'Step ' + b.stepNumber + ' of ' + b.total : 'No steps yet'));
        at.appendChild(att);
        row.appendChild(at);

        row.appendChild(el('span', 'gpo-age' + (b.days != null && b.days >= 30 ? ' is-hot' : ''), b.days == null ? 'Not started' : plural(b.days, 'day') + ' running'));

        if (canRecord) {
          var rec = el('a', 'gpo-rec');
          rec.href = b.href;
          rec.appendChild(el('span', null, 'Record'));
          rec.appendChild(el('span', 'prod-visually-hidden', ' ' + (b.step ? b.step.toLowerCase() : 'next step') + ' for ' + b.name + (b.started ? ' started ' + b.started : '')));
          row.appendChild(rec);
        } else {
          row.appendChild(el('span'));
        }
        host.appendChild(row);
      });
      if (cap) {
        cap.textContent = state.step ?
          plural(shown, 'batch', 'batches') + ' at ' + state.step.toLowerCase() + ', longest running first.' :
          plural(list.length, 'batch', 'batches') + ', longest running first.';
      }
      var showall = q('[data-gpo-showall]');
      if (showall) showall.hidden = !state.step;
    }

    function renderPlan() {
      var plan = q('[data-gpo-plan]');
      if (!plan || !state.summary) return;
      var pw = state.summary.planned_work;
      if (!pw) { plan.hidden = true; return; }
      plan.hidden = false;
      plan.replaceChildren(svgFrom(CAL_ICON));
      var total = Number(pw.total || 0);
      var text = el('span', null, total ? plural(total, 'batch', 'batches') + ' planned for today.' : 'Nothing planned for today.');
      plan.appendChild(text);
      var a = el('a', null, 'Plan on the production board');
      a.href = '/core/planner/board';
      plan.appendChild(a);
    }

    function renderFeed() {
      var feed = q('[data-gpo-feed]');
      if (!feed) return;
      root.querySelectorAll('[data-gpo-period]').forEach(function (b) {
        b.setAttribute('aria-pressed', b.dataset.gpoPeriod === state.period ? 'true' : 'false');
      });
      feed.replaceChildren();
      var log = state.summary && state.summary.audit_log ? state.summary.audit_log[state.period] : null;
      var items = log && log.items ? log.items : [];
      if (!state.summary) {
        var w = el('li');
        w.appendChild(el('span', 'gpo-empty', 'Loading activity…'));
        feed.appendChild(w);
        return;
      }
      if (!items.length) {
        var e = el('li');
        e.appendChild(el('span', 'gpo-empty', state.period === 'day' ? 'Nothing logged yet today.' : 'Nothing logged yet this week.'));
        feed.appendChild(e);
      }
      items.forEach(function (it) {
        var li = el('li');
        var ic = el('span', 'gpo-ic');
        ic.replaceChildren(svgFrom(FEED_ICON));
        li.appendChild(ic);
        var t = el('div');
        t.appendChild(el('b', null, it.summary || it.event_type || 'Activity'));
        var meta = [];
        if (it.details && it.details.length) meta.push(it.details[0]);
        meta.push(it.actor || 'System');
        if (it.at) meta.push(whenLabel(it.at));
        t.appendChild(el('small', null, meta.join(' · ')));
        li.appendChild(t);
        feed.appendChild(li);
      });
      var total = q('[data-gpo-feed-total]');
      var ops = state.summary.operator_actions ? Number(state.summary.operator_actions.week_to_date || 0) : 0;
      if (total) total.textContent = plural(ops, 'operator action') + ' this week';
    }

    function renderFigures() {
      var s = state.summary;
      if (!s) return;
      var ops = q('[data-gpo-ops-week]');
      if (ops) ops.textContent = String(s.operator_actions ? Number(s.operator_actions.week_to_date || 0) : 0);
      var started = q('[data-gpo-started-week]');
      if (started) started.textContent = String(s.operations ? Number(s.operations.started_this_week || 0) : 0);
    }

    function renderAll() {
      greet();
      renderFigures();
      renderHealth();
      if (state.hub) {
        var list = batches();
        renderToday(list);
        renderRows(list);
      }
      renderPlan();
      renderFeed();
    }

    function onHub(event) {
      if (!root.isConnected) { document.removeEventListener('core2:hub-overview', onHub); return; }
      if (event.detail) state.hub = event.detail;
      renderAll();
    }
    document.addEventListener('core2:hub-overview', onHub);
    if (window.__core2HubOverview) state.hub = window.__core2HubOverview;

    root.addEventListener('click', function (event) {
      var chip = event.target.closest('.gpo-chip');
      if (chip) {
        state.step = chip.dataset.step || '';
        syncChips();
        renderRows(batches());
        return;
      }
      if (event.target.closest('[data-gpo-showall]')) {
        state.step = '';
        syncChips();
        renderRows(batches());
        return;
      }
      var period = event.target.closest('[data-gpo-period]');
      if (period) {
        state.period = period.dataset.gpoPeriod;
        renderFeed();
      }
    });

    renderAll();
    if (window.CoreAPI && typeof window.CoreAPI.getDashboardSummary === 'function') {
      window.CoreAPI.getDashboardSummary(7).then(function (summary) {
        if (!root.isConnected) return;
        state.summary = summary || {};
        renderAll();
      }).catch(function (err) {
        if (!root.isConnected || (err && err.name === 'AbortError')) return;
        console.warn('Production overview: could not load the dashboard summary', err);
        state.summary = {};
        renderAll();
      });
    }
  }

  function boot() {
    var root = document.querySelector('[data-gpo-root]');
    if (root) bind(root);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
