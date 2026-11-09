/* Planner: what needs making, and when. One fetch feeds the figures, the totals and the list. */
(function () {
  'use strict';
  var DAY = 86400000;
  var SOURCES = { manual: 'Order', contract: 'Contract', forecast: 'Stock target' };

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
    var cover = null;
    var siteId = null; // the site stock cover, targets and Plan are for; null = the default site
    var synced = null;
    var status = root.querySelector('[data-planning-status]');

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
    async function api(path, method, body, extra) {
      var token = document.querySelector('meta[name="csrf-token"]');
      var headers = { 'Content-Type': 'application/json', 'X-CSRFToken': token ? token.content : '' };
      Object.keys(extra || {}).forEach(function (name) { headers[name] = extra[name]; });
      var response = await fetch(path, {
        method: method || 'GET', credentials: 'same-origin', signal: controller.signal,
        headers: headers,
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
      var what = el('p', null, 'planner-row__what');
      var badge = el('span', SOURCES[demand.source] || SOURCES.manual, 'planner-source');
      badge.dataset.source = demand.source || 'manual';
      what.appendChild(badge);
      what.appendChild(document.createTextNode(amount(demand.quantity, demand.unit) + ' · ' + (output ? output.name : 'Output no longer available')));
      main.appendChild(what);
      if (demand.source_note && open) main.appendChild(el('p', demand.source_note, 'planner-row__note'));
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

    function say(message) {
      status.textContent = message || '';
      status.hidden = !message;
    }
    function shortDate(iso) {
      return new Date(iso + 'T00:00:00').toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' });
    }
    function renderList(container, items, line) {
      var list = container.querySelector('ul');
      list.replaceChildren();
      items.forEach(function (item) { list.appendChild(el('li', line(item))); });
      container.hidden = items.length === 0;
    }
    function renderContractNotice() {
      var box = root.querySelector('[data-contract-unmapped]');
      var items = (synced && synced.unmapped) || [];
      root.querySelector('[data-contract-unmapped-title]').textContent =
        (items.length === 1 ? '1 contract order line needs a workflow output before it can be planned'
          : items.length + ' contract order lines need a workflow output before they can be planned');
      renderList(box, items, function (item) {
        return (item.order_reference ? item.order_reference + ' · ' : '') + item.product_name + ': ' + item.reason;
      });
    }

    function coverRow(product) {
      var card = el('article', null, 'planner-row planner-cover-row');
      card.dataset.outputId = product.source_output_id;
      var main = el('div', null, 'planner-row__main');
      main.appendChild(el('h3', product.name));
      main.appendChild(el('p', product.summary, 'planner-cover__sentence'));
      var facts = [];
      if (product.on_hand !== null) facts.push(amount(product.on_hand, product.unit) + ' on hand');
      if (Number(product.planned)) facts.push(amount(product.planned, product.unit) + ' planned');
      if (Number(product.ordered)) facts.push(amount(product.ordered, product.unit) + ' on order');
      if (product.seasonality) facts.push(product.seasonality);
      main.appendChild(el('p', facts.join(' · '), 'planner-row__what'));
      product.unknowns.forEach(function (reason) { main.appendChild(el('p', reason, 'planner-row__note')); });
      card.appendChild(main);

      var target = el('div', null, 'planner-target');
      if (canRecord) {
        var label = el('label');
        label.appendChild(el('span', 'Weeks of cover'));
        var input = el('input');
        input.type = 'number'; input.min = '0.5'; input.max = '104'; input.step = '0.5'; input.inputMode = 'decimal';
        input.value = product.target_weeks || '';
        input.placeholder = 'Not set';
        input.setAttribute('aria-label', 'Weeks of cover to keep: ' + product.name);
        input.addEventListener('change', async function () {
          input.disabled = true; report('');
          try {
            await api('/api/core/planner/targets', 'POST', { source_output_id: product.source_output_id, weeks_of_cover: input.value === '' ? null : input.value, site_id: siteId });
            say(input.value === '' ? 'Stock target cleared for ' + product.name + '.' : 'Keeping ' + input.value + ' weeks of ' + product.name + '.');
            await loadCover();
          } catch (err) { if (err.name !== 'AbortError') { report(err.message); input.disabled = false; } }
        });
        label.appendChild(input);
        target.appendChild(label);
      } else {
        target.appendChild(el('span', product.target_weeks ? 'Keep ' + product.target_weeks + ' weeks' : 'No stock target', 'planner-row__priority'));
      }
      card.appendChild(target);

      var action = el('div', null, 'planner-cover__action');
      if (product.suggestion && canRecord) {
        var plan = el('button', 'Plan ' + plural(product.suggestion.batches, 'batch', 'batches'), 'workspace-button planner-plan');
        plan.type = 'button';
        plan.setAttribute('aria-label', 'Plan ' + plural(product.suggestion.batches, 'batch', 'batches') + ' of ' + product.name);
        var key = 'cover-' + product.source_output_id + '-' + Date.now().toString(36);
        plan.addEventListener('click', async function () {
          plan.disabled = true; report(''); say('');
          try {
            var result = await api('/api/core/planner/cover/plan', 'POST', { source_output_id: product.source_output_id, site_id: siteId }, { 'Idempotency-Key': key });
            var count = result.batches.length;
            say(count ? 'Planned ' + plural(count, 'batch', 'batches') + ' of ' + product.name + ', starting ' + shortDate(result.batches[0].proposed_start_date) + '. They are on the production board.' : result.message);
            await load();
          } catch (err) { if (err.name !== 'AbortError') { report(err.message); plan.disabled = false; } }
        });
        action.appendChild(plan);
      }
      card.appendChild(action);
      return card;
    }

    function renderCover() {
      renderSites();
      var list = root.querySelector('[data-cover-list]');
      var errorLine = root.querySelector('[data-cover-error]');
      list.replaceChildren();
      if (!cover || cover.error) {
        errorLine.hidden = !(cover && cover.error);
        errorLine.textContent = cover && cover.error ? 'Stock cover could not load. ' + cover.error : '';
        root.querySelector('[data-cover-empty]').hidden = true;
        root.querySelector('[data-sales-unmapped]').hidden = true;
        return;
      }
      errorLine.hidden = true;
      root.querySelector('[data-cover-caption]').textContent = cover.sales_connected
        ? 'From the last ' + cover.window_weeks + ' weeks of sales' + (cover.seasonal ? ', adjusted for the season.' : '.')
        : 'Connect a sales source to see how fast each product sells.';
      root.querySelector('[data-cover-empty]').hidden = cover.products.length > 0;
      cover.products.forEach(function (product) { list.appendChild(coverRow(product)); });
      renderList(root.querySelector('[data-sales-unmapped]'), cover.unmapped_products, function (item) {
        return item.product_name + ': ' + item.reason;
      });
    }

    function coverPath() {
      return '/api/core/planner/cover' + (siteId ? '?site_id=' + encodeURIComponent(siteId) : '');
    }
    function renderSites() {
      var label = root.querySelector('[data-cover-site]');
      var select = root.querySelector('[data-cover-site-select]');
      var sites = (cover && cover.sites) || [];
      label.hidden = sites.length < 2;
      if (label.hidden) return;
      select.replaceChildren();
      sites.forEach(function (site) {
        var option = el('option', site.name); option.value = site.id; select.appendChild(option);
      });
      select.value = cover.site_id || sites[0].id;
    }
    async function loadCover() {
      try { cover = await api(coverPath()); }
      catch (err) { if (err.name === 'AbortError') return; cover = { error: err.message || '' }; }
      renderCover();
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
      caption.textContent = 'Orders and contract orders, soonest due first.';
      open.forEach(function (item) { list.appendChild(row(item, outputs)); });
      if (open.length === 0 && cache.demands.length > 0) list.appendChild(el('p', 'No open demand. Everything here has been met or cancelled.', 'workspace-empty'));

      renderContractNotice();
      renderCover();

      closedList.replaceChildren();
      root.querySelector('[data-closed]').hidden = closed.length === 0;
      set('[data-closed-summary]', 'Closed demand (' + closed.length + ')');
      closed.forEach(function (item) { closedList.appendChild(row(item, outputs)); });
    }

    async function load() {
      layout.setAttribute('aria-busy', 'true');
      try {
        if (canRecord) {
          // Contract orders become demand here too, in case a save's own sync didn't run.
          try { synced = await api('/api/core/planner/demand/sync', 'POST'); }
          catch (err) { if (err.name === 'AbortError') throw err; synced = null; }
          // Stock and sales change elsewhere: keep planned batches right before showing them.
          try { await api('/api/core/planner/replan', 'POST'); }
          catch (err) { if (err.name === 'AbortError') throw err; }
        }
        var results = await Promise.all([
          api('/api/core/planner/demands'),
          api(coverPath()).catch(function (err) { if (err.name === 'AbortError') throw err; return { error: err.message || '' }; })
        ]);
        cache = results[0];
        cover = results[1];
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
    async function onSite(event) {
      if (!event.target.matches('[data-cover-site-select]')) return;
      siteId = event.target.value || null;
      say('');
      await loadCover();
    }
    root.addEventListener('change', onSite);
    root.addEventListener('click', onClick);
    if (form) form.addEventListener('submit', onSubmit);
    load();
    return function () {
      controller.abort();
      root.removeEventListener('click', onClick);
      root.removeEventListener('change', onSite);
      if (form) form.removeEventListener('submit', onSubmit);
    };
  }

  window.bize.onPage('[data-planning-root]', init);
}());
