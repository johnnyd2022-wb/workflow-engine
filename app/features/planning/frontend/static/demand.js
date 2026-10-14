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
        cache = await api('/api/core/planner/demands');
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
