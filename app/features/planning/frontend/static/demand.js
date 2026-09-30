(function () {
  'use strict';
  var root = document.querySelector('[data-planning-root]');
  if (!root) return;
  var error = root.querySelector('[data-planning-error]');
  var list = root.querySelector('[data-demand-list]');
  var form = root.querySelector('[data-demand-form]');
  function report(message) { error.textContent = message || ''; error.hidden = !message; }
  async function api(path, method, body) {
    var token = document.querySelector('meta[name="csrf-token"]');
    var response = await fetch(path, {
      method: method || 'GET', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token ? token.content : '' },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not update production demand.');
    return data;
  }
  function text(parent, tag, value) {
    var element = document.createElement(tag); element.textContent = value; parent.appendChild(element); return element;
  }
  async function load() {
    var data = await api('/api/core/planner/demands');
    var outputs = new Map(data.outputs.map(function (row) { return [row.id, row]; }));
    if (form) {
      var select = form.querySelector('[data-output-select]');
      var previous = select.value; select.replaceChildren();
      text(select, 'option', 'Choose a product output').value = '';
      data.outputs.forEach(function (row) { text(select, 'option', row.name + ' (' + row.unit + ')').value = row.id; });
      select.value = previous;
    }
    list.replaceChildren();
    root.querySelector('[data-planning-empty]').hidden = data.demands.length > 0;
    data.demands.forEach(function (row) {
      var card = document.createElement('article');
      text(card, 'h2', row.reference);
      var output = outputs.get(row.source_output_id);
      text(card, 'p', row.quantity + ' ' + row.unit + ' · ' + (output ? output.name : 'Output no longer available'));
      text(card, 'p', 'Due ' + row.due_date + ' · Priority ' + row.priority + ' · ' + row.status);
      if (row.status === 'open' && list.dataset.canRecord === 'true') {
        var cancel = text(card, 'button', 'Cancel demand'); cancel.type = 'button';
        cancel.addEventListener('click', async function () {
          cancel.disabled = true; report('');
          try { await api('/api/core/planner/demands/' + encodeURIComponent(row.id) + '/cancel', 'POST'); await load(); }
          catch (err) { report(err.message); cancel.disabled = false; }
        });
      }
      list.appendChild(card);
    });
  }
  if (form) form.addEventListener('submit', async function (event) {
    event.preventDefault(); report(''); var button = form.querySelector('button[type="submit"]'); button.disabled = true;
    var fields = new FormData(form);
    try {
      await api('/api/core/planner/demands', 'POST', {
        reference: fields.get('reference'), source_output_id: fields.get('source_output_id'),
        quantity: fields.get('quantity'), due_date: fields.get('due_date'), priority: Number(fields.get('priority'))
      });
      form.reset(); await load();
    } catch (err) { report(err.message); } finally { button.disabled = false; }
  });
  load().catch(function (err) { report(err.message); });
}());
