/* Planner: what needs making, and when. One fetch feeds the figures, the totals and the list. */
(function () {
  'use strict';
  var DAY = 86400000;

  function init(root) {
    var canRecord = root.dataset.canRecord === 'true';
    var layout = root.querySelector('[data-planner-layout]');
    var error = root.querySelector('[data-planning-error]');
    var retry = root.querySelector('[data-planning-retry]');
    var list = root.querySelector('[data-demand-list]');
    var closedList = root.querySelector('[data-closed-list]');
    var form = root.querySelector('[data-demand-form]');
    var addCard = root.querySelector('#planner-add');
    var addToggle = root.querySelector('.workspace-header [data-add-toggle]');
    var controller = new AbortController();
    var cache = null;

    function el(tag, text, className) {
      var node = document.createElement(tag);
      if (text != null) node.textContent = text;
      if (className) node.className = className;
      return node;
    }
    function set(selector, text) { root.querySelector(selector).textContent = text; }
    function report(message, canRetry) {
      root.querySelector('[data-planning-error-text]').textContent = message || '';
      error.hidden = !message;
      retry.hidden = !canRetry;
    }
    async function api(path, method, body) {
      var token = document.querySelector('meta[name="csrf-token"]');
      var response = await fetch(path, {
        method: method || 'GET', credentials: 'same-origin', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token ? token.content : '' },
        body: body === undefined ? undefined : JSON.stringify(body)
      });
      var data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not update production demand.');
      return data;
    }

    // Whole calendar days from today to an ISO date, in the viewer's own timezone.
    function daysUntil(iso) {
      var match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
      if (!match) return null;
      var due = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
      var now = new Date();
      return Math.round((due - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / DAY);
    }
    function dueWords(iso) {
      var days = daysUntil(iso);
      if (days === null) return { label: 'No due date', state: 'later' };
      if (days < 0) return { label: -days + ' day' + (days === -1 ? '' : 's') + ' overdue', state: 'overdue' };
      if (days === 0) return { label: 'Due today', state: 'soon' };
      if (days === 1) return { label: 'Due tomorrow', state: 'soon' };
      if (days <= 7) return { label: 'Due in ' + days + ' days', state: 'soon' };
      var date = new Date(iso + 'T00:00:00');
      return { label: 'Due ' + date.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' }), state: 'later' };
    }
    function amount(quantity, unit) {
      var number = Number(quantity);
      var shown = Number.isFinite(number) ? number.toLocaleString('en-NZ', { maximumFractionDigits: 4 }) : String(quantity);
      return shown + ' ' + unit;
    }
    function plural(count, one, many) { return count + ' ' + (count === 1 ? one : many); }

    function row(demand, outputs) {
      var open = demand.status === 'open';
      var card = el('article', null, 'planner-row');
      card.dataset.status = demand.status;
      var main = el('div', null, 'planner-row__main');
      main.appendChild(el('h3', demand.reference));
      var from = { contract: 'Contract order', forecast: 'From the forecast' }[demand.source];
      if (from) main.appendChild(el('span', from, 'planner-source'));
      var output = outputs.get(demand.source_output_id);
      main.appendChild(el('p', amount(demand.quantity, demand.unit) + ' · ' + (output ? output.name : 'Output no longer available'), 'planner-row__what'));
      card.appendChild(main);
      var due = dueWords(demand.due_date);
      var when = el('span', open ? due.label : demand.status === 'cancelled' ? 'Cancelled' : 'Fulfilled', 'planner-due');
      when.dataset.state = open ? due.state : 'closed';
      when.title = demand.due_date;
      card.appendChild(when);
      card.appendChild(el('span', 'Priority ' + demand.priority, 'planner-row__priority'));
      if (open && canRecord) {
        var cancel = el('button', 'Cancel', 'planner-cancel');
        cancel.type = 'button';
        cancel.setAttribute('aria-label', 'Cancel demand: ' + demand.reference);
        cancel.addEventListener('click', async function () {
          cancel.disabled = true; report('');
          try { await api('/api/core/planner/demands/' + encodeURIComponent(demand.id) + '/cancel', 'POST'); await load(); }
          catch (err) { if (err.name !== 'AbortError') { report(err.message); cancel.disabled = false; } }
        });
        card.appendChild(cancel);
      }
      return card;
    }

    // ── Stock cover (GL-P07 B3) ─────────────────────────────────────────────────────────
    var forecast = null;
    function shortDay(iso) { return new Date(iso + 'T00:00:00').toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' }); }
    function planLabel(item) {
      var s = item.suggestion;
      if (s.batches) return 'Plan ' + plural(s.batches, 'batch', 'batches');
      return 'Plan ' + amount(s.quantity, item.unit);
    }
    function planButton(item, className) {
      var button = el('button', planLabel(item), className || 'workspace-button workspace-button--primary planner-primary planner-plan');
      button.type = 'button';
      button.setAttribute('aria-label', planLabel(item) + ' of ' + item.name);
      button.addEventListener('click', async function () {
        button.disabled = true; report('');
        try {
          var result = await api('/api/core/planner/forecast/' + encodeURIComponent(item.output_id) + '/plan', 'POST', {});
          report('');
          await load();
          announce(plural(result.batches.length, 'batch', 'batches') + ' of ' + item.name + ' planned. ' + (result.batches.length === 1 ? 'It is' : 'They are') + ' on the production board.');
        } catch (err) { if (err.name !== 'AbortError') { report(err.message); button.disabled = false; } }
      });
      return button;
    }
    function targetEditor(item) {
      var wrap = el('form', null, 'planner-target');
      wrap.setAttribute('hx-boost', 'false');
      var label = el('label');
      label.appendChild(el('span', 'Keep'));
      var input = el('input'); input.type = 'number'; input.min = '0.5'; input.max = '104'; input.step = '0.5'; input.inputMode = 'decimal';
      input.value = item.target_weeks || ''; input.placeholder = '—';
      input.setAttribute('aria-label', 'Weeks of cover to keep of ' + item.name);
      label.appendChild(input);
      label.appendChild(el('span', 'weeks'));
      wrap.appendChild(label);
      var save = el('button', 'Save', 'planner-target__save'); save.type = 'submit'; save.hidden = true;
      wrap.appendChild(save);
      input.addEventListener('input', function () { save.hidden = input.value === (item.target_weeks || ''); });
      wrap.addEventListener('submit', async function (event) {
        event.preventDefault(); save.disabled = true; report('');
        try { await api('/api/core/planner/targets/' + encodeURIComponent(item.output_id), 'POST', { weeks: input.value }); await loadForecast(); }
        catch (err) { if (err.name !== 'AbortError') { report(err.message); save.disabled = false; } }
      });
      if (!canRecord) { input.disabled = true; }
      return wrap;
    }
    function coverWords(item) {
      if (item.weeks_of_cover == null) return 'No recent sales';
      var weeks = Number(item.weeks_of_cover);
      return (weeks >= 52 ? 'Over a year' : Math.floor(weeks) + ' weeks') + ' of cover';
    }
    function coverMeter(item) {
      var meter = el('div', null, 'planner-meter');
      var weeks = Number(item.weeks_of_cover || 0), target = Number(item.target_weeks || 0);
      var scale = Math.max(weeks, target, 1) * 1.15;
      var fill = el('span', null, 'planner-meter__fill');
      fill.style.width = Math.min(100, (weeks / scale) * 100) + '%';
      fill.dataset.state = target && weeks < target ? 'short' : 'ok';
      meter.appendChild(fill);
      if (target) { var mark = el('span', null, 'planner-meter__target'); mark.style.left = (target / scale) * 100 + '%'; mark.title = 'Target: ' + target + ' weeks'; meter.appendChild(mark); }
      meter.setAttribute('role', 'img');
      meter.setAttribute('aria-label', coverWords(item) + (target ? ', target ' + target + ' weeks' : ''));
      return meter;
    }
    function renderMakeNext(host, rows) {
      rows.forEach(function (item) {
        var line = el('article', null, 'planner-cover__row');
        line.dataset.state = item.suggestion ? (item.suggestion.late ? 'late' : 'plan') : 'ok';
        var main = el('div', null, 'planner-cover__main');
        main.appendChild(el('h3', item.name));
        // The heading names the product; the line under it starts with what happens to it.
        var detail = item.sentence.indexOf(item.name + ' ') === 0 ? item.sentence.slice(item.name.length + 1) : item.sentence;
        main.appendChild(el('p', detail.charAt(0).toUpperCase() + detail.slice(1), 'planner-cover__sentence'));
        line.appendChild(main);
        var gauge = el('div', null, 'planner-cover__gauge');
        gauge.appendChild(el('span', coverWords(item), 'planner-cover__weeks'));
        gauge.appendChild(coverMeter(item));
        line.appendChild(gauge);
        line.appendChild(targetEditor(item));
        var act = el('div', null, 'planner-cover__act');
        if (item.suggestion && canRecord) act.appendChild(planButton(item));
        else if (item.suggestion) act.appendChild(el('span', planLabel(item), 'planner-cover__todo'));
        line.appendChild(act);
        host.appendChild(line);
      });
    }
    function renderProjection(host, rows) {
      var wrap = el('div', null, 'planner-projection');
      var table = el('table'); var head = el('thead'); var hr = el('tr');
      hr.appendChild(el('th', 'Product'));
      (rows[0] ? rows[0].projection : []).forEach(function (week, index) { var th = el('th', index === 0 ? 'This wk' : shortDay(week.week_ending)); th.scope = 'col'; hr.appendChild(th); });
      hr.appendChild(el('th', ''));
      head.appendChild(hr); table.appendChild(head);
      var body = el('tbody');
      rows.forEach(function (item) {
        var tr = el('tr');
        var name = el('th'); name.scope = 'row'; name.appendChild(el('span', item.name, 'planner-projection__name'));
        name.appendChild(el('span', item.weekly_rate + ' ' + item.unit + '/wk', 'planner-projection__rate'));
        tr.appendChild(name);
        var target = Number(item.target_weeks || 0);
        item.projection.forEach(function (week) {
          var level = Number(week.stock);
          var td = el('td', level < 0 ? 'Short' : level.toLocaleString('en-NZ'));
          // Amber: by then, what's left lasts less than the target, the same runway the plan suggestion uses.
          var runway = item.runs_out ? (new Date(item.runs_out) - new Date(week.week_ending)) / (7 * DAY) : Infinity;
          td.dataset.state = level < 0 ? 'short' : target && runway < target ? 'low' : 'ok';
          td.title = shortDay(week.week_ending) + ': ' + (level < 0 ? 'short by ' + (-level) : level) + ' ' + item.unit;
          tr.appendChild(td);
        });
        var act = el('td', null, 'planner-projection__act');
        if (item.suggestion && canRecord) act.appendChild(planButton(item, 'workspace-button planner-plan'));
        tr.appendChild(act);
        body.appendChild(tr);
      });
      table.appendChild(body); wrap.appendChild(table); host.appendChild(wrap);
      host.appendChild(el('p', 'Stock expected at the end of each week: on hand, plus batches ready by then, less sales at the current pace. Amber: from then, it lasts less than the weeks you keep.', 'workspace-caption planner-projection__key'));
    }
    function renderBriefing(host, rows) {
      var list = el('ul', null, 'planner-briefing');
      rows.forEach(function (item) {
        var li = el('li');
        li.dataset.state = item.suggestion ? (item.suggestion.late ? 'late' : 'plan') : 'ok';
        li.appendChild(el('p', item.sentence));
        var row = el('div', null, 'planner-briefing__actions');
        if (item.suggestion && canRecord) row.appendChild(planButton(item, 'planner-link-button'));
        row.appendChild(targetEditor(item));
        li.appendChild(row);
        list.appendChild(li);
      });
      host.appendChild(list);
    }
    function renderCover() {
      var host = root.querySelector('[data-cover-list]');
      if (!host || !forecast) return;
      host.replaceChildren();
      var rows = forecast.products;
      root.querySelector('[data-cover-empty]').hidden = rows.length > 0;
      var toPlan = rows.filter(function (item) { return item.suggestion; });
      var late = toPlan.filter(function (item) { return item.suggestion.late; });
      set('[data-cover-basis]', rows.length ? 'Last ' + (rows[0].window_weeks || 12) + ' weeks of sales' : '');
      var first = toPlan.slice().sort(function (a, b) { return a.suggestion.plan_by < b.suggestion.plan_by ? -1 : 1; })[0];
      var brief = toPlan.length
        ? plural(toPlan.length, 'product needs', 'products need') + ' planning' + (late.length ? ', ' + late.length + ' already late' : '') + '. ' +
          (first.suggestion.late ? first.name + ' should be planned now.' : first.name + ' first, by ' + shortDay(first.suggestion.plan_by) + '.')
        : rows.some(function (item) { return item.target_weeks; }) ? 'Every product with a target has its cover, counting batches already planned.' : rows.length ? 'Set how many weeks of stock to keep, and this says when to make more.' : '';
      set('[data-cover-brief]', brief);
      var style = root.dataset.plannerStyle;
      if (style === '2') renderProjection(host, rows);
      else if (style === '3') renderBriefing(host, rows);
      else renderMakeNext(host, rows);
    }
    function announce(message) { var live = root.querySelector('[data-cover-brief]'); if (live) live.textContent = message; }
    async function loadForecast() {
      try { forecast = await api('/api/core/planner/forecast'); renderCover(); }
      catch (err) { if (err.name !== 'AbortError') report('Stock cover could not load. ' + (err.message || '')); }
    }
    /* CONCEPT ONLY: the layout switch. */
    function applyStyle(style) {
      root.dataset.plannerStyle = style;
      root.querySelectorAll('[data-style-pick]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.stylePick === style)); });
      renderCover();
    }
    (function () {
      var from = new URLSearchParams(window.location.search).get('style'), saved = null;
      try { saved = window.localStorage.getItem('planner-style'); } catch (e) { saved = null; }
      applyStyle(['1', '2', '3'].indexOf(from) >= 0 ? from : ['1', '2', '3'].indexOf(saved) >= 0 ? saved : '1');
    }());

    function render() {
      if (!cache) return;
      var outputs = new Map(cache.outputs.map(function (item) { return [item.id, item]; }));
      var open = cache.demands.filter(function (item) { return item.status === 'open'; });
      var closed = cache.demands.filter(function (item) { return item.status !== 'open'; });
      var overdue = open.filter(function (item) { return daysUntil(item.due_date) < 0; });
      var week = open.filter(function (item) { var days = daysUntil(item.due_date); return days >= 0 && days <= 7; });
      var later = open.filter(function (item) { return daysUntil(item.due_date) > 7; });

      set('[data-figure-open]', String(open.length));
      set('[data-figure-overdue]', String(overdue.length));
      set('[data-figure-week]', String(week.length));
      root.querySelector('[data-figure-overdue-tile]').dataset.state = overdue.length ? 'overdue' : 'clear';
      set('[data-figure-overdue-note]', overdue.length ? 'past their due date' : 'nothing is late');
      set('[data-demand-count]', open.length ? plural(open.length, 'open', 'open') : '');

      // What to make: open quantities added up by product output, in the order demand falls due.
      var totals = new Map();
      open.forEach(function (item) {
        var key = item.source_output_id + '|' + item.unit;
        var entry = totals.get(key) || { name: (outputs.get(item.source_output_id) || {}).name || 'Output no longer available', unit: item.unit, total: 0, count: 0 };
        entry.total += Number(item.quantity) || 0; entry.count += 1; totals.set(key, entry);
      });
      var make = root.querySelector('[data-make-list]');
      make.replaceChildren();
      root.querySelector('[data-make-empty]').hidden = totals.size > 0;
      totals.forEach(function (entry) {
        var line = el('li');
        line.appendChild(el('span', entry.name, 'planner-make__name'));
        line.appendChild(el('strong', amount(entry.total, entry.unit)));
        line.appendChild(el('span', plural(entry.count, 'demand', 'demands'), 'planner-make__count'));
        make.appendChild(line);
      });

      list.replaceChildren();
      root.dataset.state = cache.demands.length ? 'ready' : 'empty';
      root.querySelector('[data-planning-empty]').hidden = cache.demands.length > 0;
      var caption = root.querySelector('[data-demand-caption]');
      caption.hidden = !open.length;
      caption.textContent = 'Open demand, soonest due first.';
      open.forEach(function (item) { list.appendChild(row(item, outputs)); });
      if (open.length === 0 && cache.demands.length > 0) list.appendChild(el('p', 'No open demand. Everything here has been met or cancelled.', 'workspace-empty'));

      closedList.replaceChildren();
      root.querySelector('[data-closed]').hidden = closed.length === 0;
      set('[data-closed-summary]', 'Closed demand (' + closed.length + ')');
      closed.forEach(function (item) { closedList.appendChild(row(item, outputs)); });
    }

    async function load() {
      layout.setAttribute('aria-busy', 'true');
      try {
        // Confirmed contract orders become demand once; a stale one is harmless here.
        if (canRecord) await api('/api/core/planner/contract-demand/sync', 'POST', {}).catch(function () {});
        var both = await Promise.all([api('/api/core/planner/demands'), api('/api/core/planner/forecast').catch(function () { return null; })]);
        cache = both[0];
        if (both[1]) forecast = both[1];
        report('');
        if (form) {
          var select = form.querySelector('[data-output-select]');
          var previous = select.value;
          select.replaceChildren();
          var first = el('option', 'Choose a product output'); first.value = ''; select.appendChild(first);
          cache.outputs.forEach(function (item) {
            var option = el('option', item.name + ' (' + item.unit + ')'); option.value = item.id; select.appendChild(option);
          });
          select.value = previous;
        }
        root.dataset.loaded = 'true';
        render();
        renderCover();
      } catch (err) {
        if (err.name === 'AbortError') return;
        // A failed load is not an empty planner: say so and keep the figures blank.
        if (!cache) { root.dataset.state = 'error'; report('Production demand could not load. ' + (err.message || ''), true); }
        else report(err.message);
      } finally {
        layout.setAttribute('aria-busy', 'false');
      }
    }

    function showForm(show) {
      if (!addCard) return;
      addCard.hidden = !show;
      addToggle.setAttribute('aria-expanded', String(show));
      if (show) addCard.querySelector('[name="reference"]').focus();
      else addToggle.focus();
    }
    function onClick(event) {
      if (event.target.closest('[data-add-toggle]')) { showForm(addCard.hidden); return; }
      if (event.target.closest('[data-add-close]')) { showForm(false); return; }
      if (event.target.closest('[data-planning-retry]')) load();
      var pick = event.target.closest('[data-style-pick]');
      if (pick) { applyStyle(pick.dataset.stylePick); try { window.localStorage.setItem('planner-style', pick.dataset.stylePick); } catch (e) { /* per viewer only */ } }
    }
    async function onSubmit(event) {
      event.preventDefault(); report('');
      var button = form.querySelector('button[type="submit"]'); button.disabled = true;
      var fields = new FormData(form);
      try {
        await api('/api/core/planner/demands', 'POST', {
          reference: fields.get('reference'), source_output_id: fields.get('source_output_id'),
          quantity: fields.get('quantity'), due_date: fields.get('due_date'), priority: Number(fields.get('priority'))
        });
        form.reset(); showForm(false); await load();
      } catch (err) { if (err.name !== 'AbortError') report(err.message); } finally { button.disabled = false; }
    }
    root.addEventListener('click', onClick);
    if (form) form.addEventListener('submit', onSubmit);
    load();
    return function () {
      controller.abort();
      root.removeEventListener('click', onClick);
      if (form) form.removeEventListener('submit', onSubmit);
    };
  }

  window.bize.onPage('[data-planning-root]', init);
}());
