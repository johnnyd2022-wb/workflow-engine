/* Where stock and batches are recorded (GL-P07 A3).

   window.BizeSite is the one place pages ask about sites:
   - choices()  the active sites (and their stock areas) and whether more than one can be chosen,
                fetched once per page view from /api/core/sites/choices;
   - current()  the site this person last worked at, else the default site;
   - mount(el)  a "Site" control inside el, already set to current(); it is never shown while
                multiple sites are off, so a single-site business sees nothing new;
   - remember() makes a site the one the next form opens on.

   Nobody normally has to choose: the control opens on where they were last. */
(function () {
  'use strict';

  var KEY = 'bize.site.last';
  var pending = null;
  var loaded = null;

  function read() { try { return window.localStorage.getItem(KEY); } catch (_) { return null; } }
  function write(id) { try { if (id) window.localStorage.setItem(KEY, id); } catch (_) { /* private mode */ } }

  function choices() {
    if (loaded) return Promise.resolve(loaded);
    if (!pending) {
      pending = fetch('/api/core/sites/choices', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : { on: false, sites: [], default_id: null }; })
        .catch(function () { return { on: false, sites: [], default_id: null }; })
        .then(function (data) { loaded = data; pending = null; return data; });
    }
    return pending;
  }

  function find(id) {
    return loaded && loaded.sites ? loaded.sites.filter(function (s) { return s.id === id; })[0] || null : null;
  }

  /** The remembered site if it is still active, else the default; null while sites are off. */
  function current() {
    if (!loaded || !loaded.on) return null;
    var last = read();
    return find(last) ? last : loaded.default_id;
  }

  function remember(id) { if (find(id)) write(id); }

  /**
   * A labelled site select inside `container`. Returns a handle whose value() is the chosen
   * site id, or null while sites are off (callers then send no site at all).
   * opts.label (default "Site"), opts.hint (a line under it), opts.onChange(id).
   */
  function mount(container, opts) {
    opts = opts || {};
    var handle = { value: function () { return null; }, ready: null };
    if (!container) { handle.ready = Promise.resolve(handle); return handle; }
    container.hidden = true;
    handle.ready = choices().then(function (data) {
      container.replaceChildren();
      if (!data.on || !data.sites.length) return handle;
      var id = 'site-pick-' + Math.random().toString(36).slice(2, 8);
      var label = document.createElement('label');
      label.className = 'site-pick';
      label.setAttribute('for', id);
      var text = document.createElement('span');
      text.className = 'site-pick__label';
      text.textContent = opts.label || 'Site';
      var select = document.createElement('select');
      select.id = id;
      select.name = 'site_id';
      select.className = 'site-pick__select';
      select.setAttribute('data-site-select', '');
      data.sites.forEach(function (site) {
        var option = document.createElement('option');
        option.value = site.id;
        option.textContent = site.name + (site.is_default ? ' (default)' : '');
        select.appendChild(option);
      });
      select.value = current() || data.default_id;
      select.addEventListener('change', function () {
        remember(select.value);
        if (opts.onChange) opts.onChange(select.value);
      });
      label.append(text, select);
      container.appendChild(label);
      if (opts.hint) {
        var hint = document.createElement('span');
        hint.className = 'site-pick__hint';
        hint.textContent = opts.hint;
        container.appendChild(hint);
      }
      container.hidden = false;
      handle.value = function () { return select.value || null; };
      handle.select = select;
      return handle;
    });
    return handle;
  }

  /** Adds `site_id` to a request body when a site was chosen; leaves it out otherwise. */
  function into(body, handle) {
    var id = handle && handle.value ? handle.value() : null;
    if (id) { body.site_id = id; remember(id); }
    return body;
  }

  function siteName(id) { var site = find(id); return site ? site.name : ''; }

  window.BizeSite = { choices: choices, current: current, remember: remember, mount: mount, into: into, siteName: siteName };
})();
