(function () {
  'use strict';
  function init(root) {
    if (!root || root.dataset.bound) return;
    root.dataset.bound = '1';
    var message = root.querySelector('[data-sites-message]');
    var toggle = root.querySelector('[data-sites-toggle]');
    var list = root.querySelector('[data-sites-list]');
    var create = root.querySelector('[data-sites-create]');
    var state;
    async function api(method, path, body) {
      var headers = { Accept: 'application/json' };
      if (body !== undefined) {
        headers['Content-Type'] = 'application/json';
        var token = document.querySelector('meta[name="csrf-token"]');
        headers['X-CSRFToken'] = token ? token.content : '';
      }
      var result = await fetch(path, { method: method, credentials: 'same-origin', headers: headers,
        body: body === undefined ? undefined : JSON.stringify(body) });
      var data = await result.json();
      if (!result.ok) throw new Error(data.error || 'Unable to save sites');
      return data;
    }
    function say(text) { message.textContent = text; message.hidden = !text; }
    function kinds(select, chosen) {
      Object.entries(state.kinds).forEach(function (pair) {
        var option = document.createElement('option'); option.value = pair[0]; option.textContent = pair[1];
        option.selected = pair[0] === chosen; select.appendChild(option);
      });
    }
    async function load() {
      state = await api('GET', '/api/core/sites');
      root.querySelector('[data-sites-state]').textContent = state.enabled ? 'On. Existing stock and batches belong to the default site.' : 'Off. Your current production and stock workflows continue as usual.';
      toggle.textContent = state.enabled ? 'Switch off' : 'Switch on'; toggle.disabled = false;
      root.querySelector('[data-sites-register]').hidden = !state.enabled;
      list.replaceChildren();
      state.sites.forEach(function (site) {
        var card = document.createElement('section'); card.className = 'sites-card';
        var title = document.createElement('h2'); title.textContent = site.name + (site.is_default ? ' · Default' : '') + (site.is_active ? '' : ' · Archived'); card.appendChild(title);
        var form = document.createElement('form'); form.setAttribute('hx-boost', 'false');
        var fields = document.createElement('div'); fields.className = 'sites-fields';
        ['name', 'address', 'kind'].forEach(function (key) {
          var label = document.createElement('label'); label.textContent = key[0].toUpperCase() + key.slice(1);
          var input = document.createElement(key === 'kind' ? 'select' : 'input'); input.name = key;
          if (key === 'kind') kinds(input, site.kind);
          else { input.value = site[key] || ''; input.maxLength = key === 'name' ? 120 : 500; input.required = key === 'name'; }
          label.appendChild(input); fields.appendChild(label);
        });
        form.appendChild(fields);
        var save = document.createElement('button'); save.type = 'submit'; save.className = 'btn btn-secondary'; save.textContent = 'Save site'; form.appendChild(save);
        if (!site.is_default) {
          var use = document.createElement('button'); use.type = 'button'; use.className = 'btn btn-secondary'; use.textContent = 'Make default';
          use.addEventListener('click', function () { mutate('PATCH', '/api/core/sites/' + site.id, { is_default: true, is_active: true }); }); form.appendChild(use);
          var archive = document.createElement('button'); archive.type = 'button'; archive.className = 'btn btn-secondary'; archive.textContent = site.is_active ? 'Archive site' : 'Restore site';
          archive.addEventListener('click', function () { mutate('PATCH', '/api/core/sites/' + site.id, { is_active: !site.is_active }); }); form.appendChild(archive);
        }
        form.addEventListener('submit', function (event) { event.preventDefault(); mutate('PATCH', '/api/core/sites/' + site.id, Object.fromEntries(new FormData(form))); });
        card.appendChild(form); list.appendChild(card);
      });
      var select = root.querySelector('[data-sites-kinds]'); select.replaceChildren(); kinds(select, 'manufacturing');
    }
    async function mutate(method, path, data) {
      try { await api(method, path, data); await load(); say('Saved.'); return true; }
      catch (error) { say(error.message); return false; }
    }
    toggle.addEventListener('click', async function () {
      toggle.disabled = true; await mutate('PUT', '/api/core/sites/settings', { enabled: !state.enabled }); toggle.disabled = false;
    });
    create.addEventListener('submit', async function (event) {
      event.preventDefault(); if (await mutate('POST', '/api/core/sites', Object.fromEntries(new FormData(create)))) create.reset();
    });
    load().catch(function (error) { say(error.message); });
  }
  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  bize.onPage('[data-sites-root]', init);
}());
