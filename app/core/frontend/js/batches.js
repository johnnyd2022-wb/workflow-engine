// Batches (/core/executions/live): every batch under way, the step it is at, and how long it
// has waited there. Reads the same lists the old production board did (processes, plus
// in-progress and pending executions, paginated); nothing here writes. See
// docs/batches-redesign-plan.md.
(function () {
  'use strict';

  var WAITING_MS = 48 * 3600 * 1000; // no step recorded for this long: the batch is Waiting
  var DAY_MS = 24 * 3600 * 1000;

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === 'text') node.textContent = value;
      else if (key === 'className') node.className = value;
      else node.setAttribute(key, value === true ? '' : value);
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined || child === false) return;
      node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    });
    return node;
  }

  function toDate(raw) {
    if (!raw) return null;
    var dt = new Date(raw);
    return Number.isNaN(dt.getTime()) ? null : dt;
  }

  // Only strings and numbers are displayable; an object must never become "[object Object]".
  function scalarText(value) {
    if (typeof value === 'string') return value.trim();
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
    return '';
  }

  function plural(count, one, many) {
    return count + ' ' + (count === 1 ? one : (many || one + 's'));
  }

  function formatDateTime(dt) {
    if (!dt) return 'an unknown time';
    return dt.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
  }

  // "40 minutes", "5 hours", "3 days": the one unit a person would say.
  function formatSpan(ms) {
    var mins = Math.floor(Math.max(0, ms) / 60000);
    if (mins < 1) return 'under a minute';
    if (mins < 60) return plural(mins, 'minute');
    var hours = Math.floor(mins / 60);
    if (hours < 48) return plural(hours, 'hour');
    return plural(Math.floor(hours / 24), 'day');
  }

  function sortSteps(steps) {
    return (steps || []).slice().sort(function (a, b) {
      return Number(a && a.step_number || 0) - Number(b && b.step_number || 0);
    });
  }

  function batchLabel(execution) {
    var steps = execution.execution_steps || [];
    for (var i = 0; i < steps.length; i += 1) {
      var outputs = Array.isArray(steps[i] && steps[i].actual_outputs) ? steps[i].actual_outputs : [];
      for (var j = 0; j < outputs.length; j += 1) {
        var out = outputs[j];
        if (!out || typeof out !== 'object') continue;
        var code = scalarText(out.batch_id || out.batchId || out.lot_id || out.lotId || out.lot);
        if (code) return code;
      }
    }
    return '';
  }

  function operatorOf(step) {
    var data = step && step.execution_data;
    return data && typeof data === 'object' ? (scalarText(data.completed_by) || scalarText(data.completed_by_email)) : '';
  }

  // One batch as the page reads it. "At this step since" is when the step before it was
  // recorded, or when the batch started if nothing has been recorded yet.
  function describe(execution, processName, now) {
    var steps = sortSteps(execution.execution_steps);
    var done = steps.filter(function (s) { return String(s.status || '').toLowerCase() === 'completed'; });
    var currentIndex = steps.findIndex(function (s) {
      var st = String(s.status || '').toLowerCase();
      return st === 'ready' || st === 'in_progress';
    });
    var current = currentIndex >= 0 ? steps[currentIndex] : null;
    var started = toDate(execution.started_at) || toDate(execution.created_at);
    var lastDone = done.length ? done[done.length - 1] : null;
    var since = (lastDone && toDate(lastDone.completed_at)) || started || now;
    var age = Math.max(0, now.getTime() - since.getTime());
    var summary = execution.event_summary;
    var label = batchLabel(execution);
    return {
      id: String(execution.id || ''),
      processId: String(execution.process_id || ''),
      workflow: processName || 'Untitled workflow',
      title: label || (started ? 'Batch from ' + formatDateTime(started) : 'Untitled batch'),
      steps: steps,
      total: steps.length || Number(execution.total_steps || 0),
      done: done.length,
      stepNumber: currentIndex >= 0 ? currentIndex + 1 : null,
      stepName: current ? (scalarText(current.step_name) || 'Step ' + (currentIndex + 1)) : 'Next step',
      since: since,
      age: age,
      waiting: age >= WAITING_MS,
      started: started,
      lastBy: (lastDone && operatorOf(lastDone)) || (summary && typeof summary === 'object' ? scalarText(summary.created_by) : ''),
    };
  }

  function ageText(batch) {
    if (batch.age < 60000) return 'Just started';
    return batch.waiting ? 'Waiting ' + formatSpan(batch.age) : formatSpan(batch.age) + ' at this step';
  }

  function stepText(batch) {
    return batch.stepNumber ? 'Step ' + batch.stepNumber + ' of ' + batch.total + ' · ' + batch.stepName : batch.stepName;
  }

  function init(root) {
    var page = root.closest('.workspace-page') || document;
    var controller = new AbortController();
    var on = function (target, type, fn) { if (target) target.addEventListener(type, fn, { signal: controller.signal }); };
    var $ = function (sel) { return page.querySelector(sel); };

    var params = new URLSearchParams(location.search);
    var state = {
      processes: [],
      executions: [],
      loaded: false,
      search: params.get('q') || '',
      workflow: params.get('workflow') || '',
      show: params.get('show') === 'waiting' ? 'waiting' : 'all',
      view: params.get('view') === 'timeline' ? 'timeline' : 'pipeline',
    };
    var request = 0;
    var loadedAt = 0;

    var board = $('#core2-active-pipeline-grid');
    var timeline = $('#core2-active-timeline');
    var overlay = document.getElementById('core2-active-detail-overlay');

    function writeUrl() {
      var next = new URLSearchParams(location.search);
      [['q', state.search.trim()], ['workflow', state.workflow], ['show', state.show === 'waiting' ? 'waiting' : ''],
        ['view', state.view === 'timeline' ? 'timeline' : '']].forEach(function (pair) {
        if (pair[1]) next.set(pair[0], pair[1]); else next.delete(pair[0]);
      });
      var query = next.toString();
      history.replaceState(history.state, '', location.pathname + (query ? '?' + query : ''));
    }

    function processName(id) {
      var match = state.processes.find(function (p) { return p.id === id; });
      return match ? match.name : '';
    }

    function allBatches() {
      var now = new Date();
      return state.executions.map(function (execution) {
        return describe(execution, processName(String(execution.process_id)), now);
      });
    }

    function inScope(batches) {
      return state.workflow ? batches.filter(function (b) { return b.processId === state.workflow; }) : batches;
    }

    function matches(batch) {
      if (state.show === 'waiting' && !batch.waiting) return false;
      var query = state.search.trim().toLowerCase();
      if (!query) return true;
      return [batch.title, batch.workflow, batch.stepName, batch.lastBy].join(' ').toLowerCase().indexOf(query) !== -1;
    }

    function byWait(a, b) { return b.age - a.age; }

    // ── Figures and the one-line brief ────────────────────────────────────────────────
    function finishedThisWeek() {
      var rows = ((window.__core2HubOverview || {}).workflows || {}).throughput_7d;
      if (!Array.isArray(rows)) return null;
      return rows.reduce(function (sum, row) {
        if (!row || (state.workflow && String(row.process_id) !== state.workflow)) return sum;
        return sum + Number(row.count || 0);
      }, 0);
    }

    function renderFigures(scoped) {
      var waiting = scoped.filter(function (b) { return b.waiting; });
      var finished = finishedThisWeek();
      var set = function (sel, value) { var node = $(sel); if (node) node.textContent = value; };
      set('[data-core2-inflight-count]', String(scoped.length));
      set('[data-batches-waiting-count]', String(waiting.length));
      set('[data-core2-completed7d-count]', finished === null ? '–' : String(finished));
      var waitingFigure = $('[data-batches-waiting-figure]');
      if (waitingFigure) waitingFigure.setAttribute('data-state', waiting.length ? 'warn' : 'ok');

    }

    // ── Shared pieces ────────────────────────────────────────────────────────────────
    function ageTag(batch) {
      return el('span', { className: 'batches-age' + (batch.waiting ? ' batches-age--waiting' : ''), text: ageText(batch) });
    }

    function recordHref(batch) {
      return '/core/flows/batches/start?id=' + encodeURIComponent(batch.processId) + '&execution_id=' + encodeURIComponent(batch.id);
    }

    // A batch card: what it is, how long it has waited, and who last touched it.
    function card(batch) {
      return el('button', { type: 'button', className: 'core2-active-card batches-item' + (batch.waiting ? ' is-waiting' : ''), 'data-core2-execution-id': batch.id, 'aria-label': 'Open ' + batch.title }, [
        el('span', { className: 'core2-active-card-id batches-item__title', text: batch.title }),
        ageTag(batch),
        batch.lastBy ? el('span', { className: 'batches-item__meta', text: 'Last by ' + batch.lastBy }) : null,
      ]);
    }

    function groupByWorkflow(batches) {
      var groups = {};
      var order = [];
      batches.forEach(function (b) {
        if (!groups[b.processId]) { groups[b.processId] = []; order.push(b.processId); }
        groups[b.processId].push(b);
      });
      return order.map(function (id) { return { id: id, name: groups[id][0].workflow, batches: groups[id] }; })
        .sort(function (a, b) { return a.name.localeCompare(b.name); });
    }

    // The steps a workflow has: from any of its batches (every batch carries all its steps),
    // so drawing every lane needs no extra request.
    function stepsOf(group) {
      var widest = group.batches.reduce(function (best, b) { return b.steps.length > best.length ? b.steps : best; }, []);
      return widest.map(function (s, i) { return { number: i + 1, name: scalarText(s.step_name) || 'Step ' + (i + 1) }; });
    }

    // ── Lanes: a lane per workflow, a column per step ──────────────────────────────
    function renderLanes(batches) {
      var frag = document.createDocumentFragment();
      groupByWorkflow(batches).forEach(function (group) {
        var steps = stepsOf(group);
        // A batch whose workflow has no steps (or none left to record) still needs a place.
        if (group.batches.some(function (b) { return !b.stepNumber; })) steps.push({ number: null, name: 'No step to record' });
        var waiting = group.batches.filter(function (b) { return b.waiting; }).length;
        var columns = steps.map(function (step) {
          var here = group.batches.filter(function (b) { return (b.stepNumber || null) === step.number; }).sort(byWait);
          return { step: step, here: here };
        });
        var track = el('ol', { className: 'batches-lane__steps' });
        track.style.gridTemplateColumns = columns.map(function (c) { return c.here.length ? 'minmax(0, 1fr)' : 'minmax(0, .55fr)'; }).join(' ');
        columns.forEach(function (c) {
          track.appendChild(el('li', { className: 'batches-step' + (c.here.length ? '' : ' is-empty') }, [
            el('div', { className: 'batches-step__head' }, [
              el('span', { className: 'batches-step__num', text: c.step.number ? String(c.step.number) : '–' }),
              el('span', { className: 'batches-step__name', text: c.step.name }),
              el('span', { className: 'batches-step__count', text: c.here.length ? String(c.here.length) : 'None' }),
            ]),
            c.here.length ? el('div', { className: 'batches-step__cards' }, c.here.map(function (b) { return card(b); })) : null,
          ]));
        });
        frag.appendChild(el('section', { className: 'batches-lane', 'aria-label': group.name }, [
          el('header', { className: 'batches-lane__head' }, [
            el('h3', { text: group.name }),
            el('span', { className: 'batches-lane__meta', text: plural(group.batches.length, 'batch', 'batches') + ' under way' + (waiting ? ' · ' + waiting + ' waiting' : '') }),
          ]),
          track,
        ]));
      });
      return frag;
    }

    // ── Timeline: each batch's time per step, across every workflow ─────────────────
    function renderTimeline(batches) {
      timeline.textContent = '';
      if (!batches.length) return;
      var now = new Date();
      var earliest = now.getTime();
      batches.forEach(function (b) { if (b.started && b.started.getTime() < earliest) earliest = b.started.getTime(); });
      var start = new Date(earliest);
      start.setHours(0, 0, 0, 0);
      var range = Math.max(1, now.getTime() - start.getTime());
      var pct = function (ms) { return ((Math.min(now.getTime(), Math.max(start.getTime(), ms)) - start.getTime()) / range) * 100; };

      // A tick at midnight every `step` days, so each label names one whole day and none is skipped.
      var width = timeline.clientWidth || window.innerWidth || 1024;
      var days = Math.ceil(range / DAY_MS);
      // A phone's bar area is narrow: the first day and Now are all that fit.
      var step = width < 640 ? days : Math.max(1, Math.ceil(days / 7));
      var marks = el('div', { className: 'core2-tl-head-right' });
      for (var d = 0; d < days; d += step) {
        var tick = new Date(start.getTime());
        tick.setDate(start.getDate() + d);
        var at = tick.getTime();
        // Leave room for the "Now" label at the right edge.
        if (pct(at) > 88) break;
        marks.appendChild(el('span', { className: 'core2-tl-grid-line', style: 'left:' + pct(at) + '%' }));
        marks.appendChild(el('span', { className: 'core2-tl-date-mark' + (d === 0 ? ' core2-tl-date-mark--start' : ''), style: 'left:' + pct(at) + '%', text: tick.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) }));
      }
      marks.appendChild(el('span', { className: 'core2-tl-now-label', text: 'Now' }));
      marks.appendChild(el('span', { className: 'core2-tl-now-line' }));
      timeline.appendChild(el('div', { className: 'core2-tl-head' }, [el('div', { className: 'core2-tl-head-left', text: 'Batch' }), marks]));

      batches.slice().sort(function (a, b) { return (a.started ? a.started.getTime() : 0) - (b.started ? b.started.getTime() : 0); }).forEach(function (b) {
        var lane = el('div', { className: 'core2-tl-right' });
        var cursor = (b.started || now).getTime();
        b.steps.forEach(function (s, idx) {
          var completed = toDate(s.completed_at);
          var status = String(s.status || '').toLowerCase();
          var end = completed ? completed.getTime() : ((status === 'ready' || status === 'in_progress') ? now.getTime() : null);
          if (end === null || end <= cursor) return;
          var name = scalarText(s.step_name) || 'Step ' + (idx + 1);
          var text = name + ' · ' + formatSpan(end - cursor);
          lane.appendChild(el('div', { className: 'core2-tl-segment core2-tl-segment--step' + (idx % 5), style: 'left:' + pct(cursor) + '%;width:' + Math.max(0.8, pct(end) - pct(cursor)) + '%', title: text, text: text }));
          cursor = end;
        });
        timeline.appendChild(el('button', { type: 'button', className: 'core2-tl-row', 'data-core2-execution-id': b.id, 'aria-label': 'Open ' + b.title }, [
          el('div', { className: 'core2-tl-left' }, [
            el('p', { className: 'core2-tl-batch-name', text: b.title }),
            el('p', { className: 'core2-tl-batch-meta', text: b.workflow + ' · ' + ageText(b) }),
          ]),
          lane,
        ]));
      });
    }

    // ── Detail sheet ─────────────────────────────────────────────────────────────────
    function openDetail(id) {
      var batch = allBatches().find(function (b) { return b.id === id; });
      if (!batch || !overlay) return;
      var set = function (sel, text) { var node = document.getElementById(sel); if (node) node.textContent = text; };
      set('core2-active-detail-id', batch.title);
      set('core2-active-detail-process', batch.workflow + ' · ' + stepText(batch));
      set('core2-active-detail-started', ['Started ' + formatDateTime(batch.started), batch.done + ' of ' + batch.total + ' steps done', ageText(batch)].join(' · '));
      var host = document.getElementById('core2-active-detail-steps');
      host.textContent = '';
      batch.steps.forEach(function (s, idx) {
        var status = String(s.status || '').toLowerCase();
        var state = status === 'completed' ? 'done' : ((status === 'ready' || status === 'in_progress') ? 'current' : 'upcoming');
        var meta = [];
        if (state === 'done' && s.completed_at) meta.push('Recorded ' + formatDateTime(toDate(s.completed_at)));
        if (state === 'done' && operatorOf(s)) meta.push('by ' + operatorOf(s));
        if (state === 'current') meta.push(ageText(batch));
        var outputs = (Array.isArray(s.actual_outputs) ? s.actual_outputs : []).map(function (o) {
          if (!o || typeof o !== 'object') return 'Output recorded';
          var parts = [scalarText(o.name) || scalarText(o.output_name) || 'Output'];
          var qty = (scalarText(o.quantity) + ' ' + scalarText(o.unit)).trim();
          if (qty) parts.push(qty);
          var code = scalarText(o.batch_id || o.batchId || o.lot_id || o.lotId || o.lot);
          if (code) parts.push('batch ' + code);
          return parts.join(' · ');
        });
        host.appendChild(el('article', { className: 'core2-active-detail-step core2-active-detail-step--' + state }, [
          el('div', { className: 'core2-active-detail-step-head' }, [
            el('h4', { text: (idx + 1) + '. ' + (scalarText(s.step_name) || 'Step ' + (idx + 1)) }),
            el('span', { className: 'core2-active-detail-pill core2-active-detail-pill--' + state, text: state === 'done' ? 'Done' : (state === 'current' ? 'Next to record' : 'Up next') }),
          ]),
          meta.length ? el('p', { text: meta.join(' · ') }) : null,
          outputs.length ? el('ul', { className: 'core2-active-detail-output-list' }, outputs.map(function (t) { return el('li', { text: t }); })) : null,
        ]));
      });
      var action = document.getElementById('core2-active-detail-next-step');
      if (action) {
        action.href = recordHref(batch);
        action.textContent = 'Record ' + batch.stepName;
      }
      overlay.hidden = false;
      document.body.classList.add('core2-active-detail-open');
      var close = overlay.querySelector('.core2-active-detail-close');
      if (close) close.focus();
    }

    function closeDetail() {
      if (!overlay || overlay.hidden) return;
      overlay.hidden = true;
      document.body.classList.remove('core2-active-detail-open');
    }

    // ── Render ───────────────────────────────────────────────────────────────────────
    function message(text, actions) {
      var box = $('[data-batches-message]');
      if (!box) return;
      box.hidden = !text;
      var p = box.querySelector('[data-batches-message-text]');
      if (p) p.textContent = text || '';
      ['clear', 'retry', 'start'].forEach(function (name) {
        var btn = box.querySelector('[data-batches-' + name + ']');
        if (btn) btn.hidden = !(actions || []).includes(name);
      });
    }

    function renderControls() {
      var search = $('#core2-active-search');
      if (search && search.value !== state.search) search.value = state.search;
      var select = $('#core2-active-process-select');
      if (select) {
        var withBatches = {};
        state.executions.forEach(function (e) { withBatches[String(e.process_id)] = (withBatches[String(e.process_id)] || 0) + 1; });
        select.textContent = '';
        select.appendChild(el('option', { value: '', text: 'All workflows' }));
        state.processes.filter(function (p) { return withBatches[p.id] || p.id === state.workflow; }).forEach(function (p) {
          select.appendChild(el('option', { value: p.id, text: p.name + ' (' + (withBatches[p.id] || 0) + ')' }));
        });
        select.value = state.workflow;
      }
      page.querySelectorAll('[data-core2-active-status]').forEach(function (chip) {
        var active = chip.getAttribute('data-core2-active-status') === state.show;
        chip.classList.toggle('is-active', active);
        chip.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      page.querySelectorAll('[data-core2-active-view]').forEach(function (btn) {
        var active = btn.getAttribute('data-core2-active-view') === state.view;
        btn.classList.toggle('is-active', active);
        btn.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      var pipelineView = $('#core2-active-pipeline-view');
      var timelineView = $('#core2-active-timeline-view');
      if (pipelineView) pipelineView.hidden = state.view !== 'pipeline';
      if (timelineView) timelineView.hidden = state.view !== 'timeline';
    }

    function render() {
      if (!state.loaded) return;
      renderControls();
      var scoped = inScope(allBatches());
      var shown = scoped.filter(matches);
      renderFigures(scoped);
      board.textContent = '';
      root.setAttribute('data-state', state.executions.length ? 'ready' : 'empty');

      if (!state.executions.length) {
        message(state.processes.length ? 'Nothing is under way. A batch shows here from the moment it starts.' : 'No product workflows yet. Create a workflow, then start a batch on it.', ['start']);
        timeline.textContent = '';
        return;
      }
      if (!shown.length) {
        message(state.show === 'waiting' && !state.search.trim() ? 'No batch has waited more than 2 days.' : 'No batches match these filters.', ['clear']);
        timeline.textContent = '';
        return;
      }
      message('');
      board.appendChild(renderLanes(shown));
      renderTimeline(shown);
    }

    // ── Load ─────────────────────────────────────────────────────────────────────────
    async function allFor(status) {
      var rows = [];
      var cursor = null;
      // Full records, paginated: the timeline needs real step timestamps, and a busy
      // organisation must not be cut off at the first page.
      do {
        var result = await window.CoreAPI.getExecutions(null, status, { limit: 100, cursor: cursor });
        rows = rows.concat((result && result.executions) || []);
        cursor = result && result.has_more ? result.next_cursor : null;
      } while (cursor);
      return rows;
    }

    async function load() {
      var id = ++request;
      try {
        if (!window.CoreAPI) throw new Error('CoreAPI is not loaded');
        var results = await Promise.all([window.CoreAPI.getProcesses(), allFor('in_progress'), allFor('pending')]);
        if (id !== request) return;
        state.processes = ((results[0] && results[0].processes) || []).map(function (p) {
          return { id: String(p.id), name: p.name || 'Untitled workflow' };
        });
        state.executions = results[1].concat(results[2]);
        if (state.workflow && !state.processes.some(function (p) { return p.id === state.workflow; })) state.workflow = '';
        state.loaded = true;
        loadedAt = Date.now();
        render();
      } catch (err) {
        if (id !== request) return;
        if (window.console) console.warn('Batches could not load', err);
        root.setAttribute('data-state', 'error');
        board.textContent = '';
        message('Batches could not load. Check your connection and try again.', ['retry']);
      }
    }

    // ── Wiring ───────────────────────────────────────────────────────────────────────
    on($('#core2-active-search'), 'input', function (e) { state.search = e.target.value || ''; writeUrl(); render(); });
    on($('#core2-active-process-select'), 'change', function (e) { state.workflow = e.target.value || ''; writeUrl(); render(); });
    page.querySelectorAll('[data-core2-active-status]').forEach(function (chip) {
      on(chip, 'click', function () { state.show = chip.getAttribute('data-core2-active-status'); writeUrl(); render(); });
    });
    page.querySelectorAll('[data-core2-active-view]').forEach(function (btn) {
      on(btn, 'click', function () { state.view = btn.getAttribute('data-core2-active-view'); writeUrl(); render(); });
    });
    on($('[data-batches-clear]'), 'click', function () {
      state.search = ''; state.workflow = ''; state.show = 'all'; writeUrl(); render();
      var search = $('#core2-active-search'); if (search) search.focus();
    });
    on($('[data-batches-retry]'), 'click', function () { message('Loading batches…'); load(); });
    on(page, 'click', function (e) {
      var item = e.target.closest && e.target.closest('[data-core2-execution-id]');
      if (item && !e.target.closest('a')) openDetail(item.getAttribute('data-core2-execution-id'));
    });
    if (overlay) {
      on(overlay, 'click', function (e) { if (e.target === overlay || e.target.closest('[data-core2-detail-close]')) closeDetail(); });
    }
    on(document, 'keydown', function (e) { if (e.key === 'Escape') closeDetail(); });
    // The hub script on this page fetches the overview (it carries the 7-day finished count)
    // and refetches it when a colleague records a step; follow it.
    // The overview that arrives with the page only fills the figures; one that arrives later
    // means someone recorded a step, so the batches are read again.
    on(document, 'core2:hub-overview', function () {
      if (state.loaded && Date.now() - loadedAt > 3000) load(); else render();
    });
    // The age on every batch moves with the clock.
    var tick = window.setInterval(render, 60000);

    load();

    return function teardown() {
      request += 1;
      controller.abort();
      window.clearInterval(tick);
      closeDetail();
    };
  }

  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  if (window.bize && window.bize.onPage) window.bize.onPage('[data-batches-root]', init);
})();
