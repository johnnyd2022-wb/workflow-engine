(function () {
  'use strict';

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'className') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.append(c); });
    return n;
  }

  function init(root) {
    if (!root || root.dataset.bound) return;
    root.dataset.bound = '1';
    var message = root.querySelector('[data-sites-message]');
    var loadError = root.querySelector('[data-sites-load-error]');
    var toggle = root.querySelector('[data-sites-toggle]');
    var list = root.querySelector('[data-sites-list]');
    var addButton = root.querySelector('[data-sites-add]');
    var dialog = root.querySelector('[data-site-dialog]');
    var form = root.querySelector('[data-sites-create]');
    var formError = root.querySelector('[data-site-error]');
    var state;
    var editing = null;

    async function api(method, path, body) {
      var headers = { Accept: 'application/json' };
      if (body !== undefined) {
        headers['Content-Type'] = 'application/json';
        var token = document.querySelector('meta[name="csrf-token"]');
        headers['X-CSRFToken'] = token ? token.content : '';
      }
      var result = await fetch(path, { method: method, credentials: 'same-origin', headers: headers,
        body: body === undefined ? undefined : JSON.stringify(body) });
      var data = {};
      try { data = await result.json(); } catch (_) { /* empty body */ }
      if (!result.ok) throw new Error(data.error || 'Sites could not be saved.');
      return data;
    }
    function say(text, ok) {
      message.textContent = text || '';
      message.className = 'st-message' + (ok ? ' st-message--ok' : ' st-message--error');
      message.hidden = !text;
    }
    function kindOptions(select, chosen) {
      select.replaceChildren();
      Object.keys(state.kinds).forEach(function (key) {
        var option = el('option', { value: key, text: state.kinds[key] });
        option.selected = key === chosen;
        select.append(option);
      });
    }

    function siteActions(site) {
      var wrap = el('div', { className: 'st-actions' });
      function add(text, handler, extra) {
        var b = el('button', { type: 'button', className: 'st-link' + (extra || ''), text: text, 'aria-label': text + ': ' + site.name });
        b.addEventListener('click', handler);
        wrap.append(b);
      }
      add('Edit', function () { openSite(site); }, ' st-edit');
      if (!site.is_default && site.is_active) add('Make default', function () { mutate('PATCH', '/api/core/sites/' + site.id, { is_default: true, is_active: true }, site.name + ' is the default site.'); });
      if (!site.is_default) add(site.is_active ? 'Archive' : 'Restore', function () { mutate('PATCH', '/api/core/sites/' + site.id, { is_active: !site.is_active }, site.name + (site.is_active ? ' archived.' : ' restored.')); }, site.is_active ? ' st-link--danger' : '');
      return wrap;
    }

    function render() {
      root.querySelector('[data-sites-switch]').hidden = false;
      root.querySelector('[data-sites-state]').textContent = !state.enabled
        ? 'Off. Everything happens at one place, and your production and stock work as they do now.'
        : (state.additional_site_operations_available
          ? 'On. Stock, batches and transfers can be recorded at any active site.'
          : 'On. Stock and batches stay at the default site for now; other sites are kept ready for when recording there is switched on.');
      toggle.textContent = state.enabled ? 'Switch off' : 'Switch on';
      toggle.disabled = false;
      root.querySelector('[data-sites-register]').hidden = !state.enabled;
      addButton.hidden = !state.enabled;
      list.replaceChildren();
      var active = state.sites.filter(function (s) { return s.is_active; }).length;
      var archived = state.sites.length - active;
      root.querySelector('[data-sites-summary]').textContent = active + (active === 1 ? ' active site' : ' active sites') + (archived ? ' · ' + archived + ' archived' : '');
      state.sites.forEach(function (site) {
        var li = el('li', { className: 'st-site' + (site.is_active ? '' : ' st-site--archived'), 'data-site-id': site.id });
        var tags = el('span', { className: 'st-tags' });
        if (site.is_default) tags.append(el('span', { className: 'st-tag st-tag--default', text: 'Default' }));
        if (!site.is_active) tags.append(el('span', { className: 'st-tag', text: 'Archived' }));
        li.append(
          el('div', { className: 'st-what' }, [
            el('strong', {}, [document.createTextNode(site.name), tags]),
            el('span', { text: state.kinds[site.kind] || site.kind }),
            el('span', { className: 'st-address', text: site.address || 'No address' })
          ]),
          siteActions(site)
        );
        list.append(li);
      });

    }

    async function load() {
      root.setAttribute('aria-busy', 'true');
      try {
        state = await api('GET', '/api/core/sites');
        loadError.hidden = true;
        render();
      } catch (error) {
        // Nothing half-loaded stays on screen to act on.
        root.querySelector('[data-sites-switch]').hidden = true;
        root.querySelector('[data-sites-register]').hidden = true;
        root.querySelector('[data-sites-load-text]').textContent = error.message;
        loadError.hidden = false;
      } finally {
        root.setAttribute('aria-busy', 'false');
      }
    }
    async function mutate(method, path, data, done) {
      try {
        await api(method, path, data);
        await load();
        say(done || 'Saved.', true);
        return true;
      } catch (error) { say(error.message, false); return false; }
    }

    function openSite(site) {
      editing = site;
      form.reset();
      formError.hidden = true;
      kindOptions(form.kind, site ? site.kind : 'manufacturing');
      form.name.value = site ? site.name : '';
      form.address.value = site ? (site.address || '') : '';
      root.querySelector('[data-site-dialog-title]').textContent = site ? 'Edit ' + site.name : 'Add a site';
      root.querySelector('[data-site-submit]').textContent = site ? 'Save site' : 'Add site';
      dialog.showModal();
      setTimeout(function () { form.name.focus(); }, 0);
    }

    toggle.addEventListener('click', async function () {
      toggle.disabled = true;
      await mutate('PUT', '/api/core/sites/settings', { enabled: !state.enabled }, state.enabled ? 'Multiple sites switched off.' : 'Multiple sites switched on.');
      toggle.disabled = false;
    });
    addButton.addEventListener('click', function () { openSite(null); });
    root.querySelector('[data-site-cancel]').addEventListener('click', function () { dialog.close(); });
    root.querySelector('[data-sites-retry]').addEventListener('click', load);
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      formError.hidden = true;
      var body = Object.fromEntries(new FormData(form));
      if (!body.name.trim()) { formError.textContent = 'Give the site a name.'; formError.hidden = false; return; }
      try {
        if (editing) await api('PATCH', '/api/core/sites/' + editing.id, body);
        else await api('POST', '/api/core/sites', body);
        dialog.close();
        await load();
        say(editing ? 'Saved.' : body.name + ' added.', true);
      } catch (error) {
        // A refused save stays in the dialog, next to what caused it.
        formError.textContent = error.message;
        formError.hidden = false;
      }
    });

    load();
  }
  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  bize.onPage('[data-sites-root]', init);
}());
