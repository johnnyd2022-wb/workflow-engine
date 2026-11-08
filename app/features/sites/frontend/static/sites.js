(function () {
  'use strict';

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'className') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.append(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function plural(n, word, many) { return n + ' ' + (n === 1 ? word : (many || word + 's')); }

  function init(root) {
    if (!root || root.dataset.bound) return;
    root.dataset.bound = '1';
    var $ = function (sel) { return root.querySelector(sel); };
    var message = $('[data-sites-message]');
    var loadError = $('[data-sites-load-error]');
    var register = $('[data-sites-register]');
    var siteDialog = $('[data-site-dialog]');
    var siteForm = $('[data-sites-create]');
    var siteError = $('[data-site-error]');
    var areaDialog = $('[data-area-dialog]');
    var areaForm = $('[data-area-create]');
    var areaError = $('[data-area-error]');
    var state = null;
    var editing = null;
    var areaSite = null;
    var selected = null;

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

    function active() { return state.sites.filter(function (s) { return s.is_active; }); }
    function defaultSite() { return state.sites.filter(function (s) { return s.is_default; })[0] || null; }
    function kindLabel(site) { return state.kinds[site.kind] || site.kind; }

    /** What is left to do, in order; done steps stay listed so progress reads at a glance. */
    function steps() {
      var live = active();
      var dflt = defaultSite();
      var bare = live.filter(function (s) { return !(s.areas || []).length; });
      var list = [
        { key: 'sites', title: 'Add your other sites', done: live.length > 1,
          detail: live.length > 1 ? plural(live.length, 'active site') + ': ' + live.map(function (s) { return s.name; }).join(', ') + '.'
            : 'Only ' + (dflt ? dflt.name : 'one site') + ' so far. Add the bond store, cellar door or warehouse you also use.',
          action: { label: 'Add a site', run: function () { openSite(null); } } },
        { key: 'default', title: 'Choose the default', done: !!dflt,
          detail: dflt ? 'Anything recorded without a site goes to ' + dflt.name + '.' : 'Pick where unplaced stock and batches go.' },
        { key: 'areas', title: 'Name the stock areas', done: bare.length === 0, optional: true,
          detail: bare.length === 0 ? 'Every site has its areas.'
            : 'Optional. ' + bare.map(function (s) { return s.name; }).join(', ') + (bare.length === 1 ? ' has' : ' have') + ' no areas yet (a tank bay, a dry store). Stock can still sit at the site itself.',
          action: bare.length ? { label: 'Add an area at ' + bare[0].name, run: function () { openArea(bare[0]); } } : null }
      ];
      // The compliance module words its own step; core never names the regime.
      var rule = state.compliance && state.compliance.step;
      if (rule) list.push({ key: 'licences', title: rule.title, done: !!rule.done, detail: rule.detail, href: rule.href, hrefLabel: rule.href_label });
      return list;
    }

    function renderIntro() {
      var intro = $('[data-sites-intro]');
      var toggle = $('[data-sites-toggle]');
      var points = $('[data-sites-intro-points]');
      points.replaceChildren();
      if (!state.entitled) {
        $('[data-sites-intro-title]').textContent = 'One site';
        $('[data-sites-intro-text]').textContent = 'Everything is recorded at one place. Working across several sites (a bond store, a cellar door, a warehouse) is not part of your plan; ask us to add it.';
        toggle.hidden = true;
      } else {
        $('[data-sites-intro-title]').textContent = 'Multiple sites are off';
        $('[data-sites-intro-text]').textContent = 'Everything is recorded at one place. Switch on to keep stock and batches at each of your sites:';
        ['Each site keeps its own stock; moving stock between them is recorded with a docket.',
          'Your current stock, batches and areas stay where they are, at your first site.',
          'Anything recorded without a site goes to the default site.'].forEach(function (t) { points.append(el('li', { text: t })); });
        toggle.hidden = false;
        toggle.textContent = 'Switch on';
      }
      intro.hidden = false;
    }

    function renderSetup() {
      var list = steps();
      var left = list.filter(function (s) { return !s.done && !s.optional; }).length;
      var card = $('[data-sites-setup]');
      // Once nothing required is left the steps step aside; the cards say the rest.
      card.hidden = left === 0;
      $('[data-sites-setup-summary]').textContent = left ? plural(left, 'step') + ' left.' : 'All set. Revisit any step below.';
      var ol = $('[data-sites-steps]');
      ol.replaceChildren();
      list.forEach(function (s, i) {
        var li = el('li', { className: 'st-step' + (s.done ? ' st-step--done' : ''), 'data-step': s.key });
        var mark = el('span', { className: 'st-step__mark', 'aria-hidden': 'true', text: s.done ? '✓' : String(i + 1) });
        var body = el('div', { className: 'st-step__body' });
        var title = el('strong', { className: 'st-step__title', text: s.title + (s.optional ? ' (optional)' : '') });
        body.append(title, el('span', { className: 'st-sr', text: s.done ? ' (done)' : ' (to do)' }), el('p', { className: 'st-step__detail', text: s.detail }));
        if (s.action && !s.done) {
          var b = el('button', { type: 'button', className: 'workspace-button', text: s.action.label });
          b.addEventListener('click', s.action.run);
          body.append(b);
        }
        if (s.href) body.append(el('a', { className: 'st-link', href: s.href, text: s.hrefLabel + ' →' }));
        li.append(mark, body);
        ol.append(li);
      });
    }

    /** A compliance note as a pill, linking to where it is managed. */
    function note(n) {
      if (!n) return null;
      var attrs = { className: 'st-note st-note--' + n.tone, text: n.text };
      if (n.href) attrs.href = n.href;
      return el(n.href ? 'a' : 'span', attrs);
    }

    function actionLinks(site) {
      var wrap = el('div', { className: 'st-actions' });
      function add(text, handler, extra) {
        var b = el('button', { type: 'button', className: 'st-link' + (extra || ''), text: text, 'aria-label': text + ': ' + site.name });
        b.addEventListener('click', handler);
        wrap.append(b);
      }
      add('Edit', function () { openSite(site); }, ' st-edit');
      if (site.is_active) add('Add an area', function () { openArea(site); });
      if (!site.is_default && site.is_active) add('Make default', function () { mutate('PATCH', '/api/core/sites/' + site.id, { is_default: true, is_active: true }, site.name + ' is now the default: anything recorded without a site goes there.'); });
      if (!site.is_default) add(site.is_active ? 'Archive' : 'Restore', function () { mutate('PATCH', '/api/core/sites/' + site.id, { is_active: !site.is_active }, site.name + (site.is_active ? ' archived.' : ' restored.')); }, site.is_active ? ' st-link--danger' : '');
      return wrap;
    }

    function figures(site) {
      return el('p', { className: 'st-figures' }, [
        el('span', {}, [el('strong', { text: String(site.stock_lines || 0) }), ' stock ' + ((site.stock_lines || 0) === 1 ? 'line' : 'lines')]),
        el('span', {}, [el('strong', { text: String(site.batches_under_way || 0) }), ' ' + ((site.batches_under_way || 0) === 1 ? 'batch' : 'batches') + ' under way'])
      ]);
    }
    function tags(site) {
      var t = el('span', { className: 'st-tags' });
      if (site.is_default) t.append(el('span', { className: 'st-tag st-tag--default', text: 'Default' }));
      if (!site.is_active) t.append(el('span', { className: 'st-tag', text: 'Archived' }));
      return t;
    }
    function areaList(site) {
      var ul = el('ul', { className: 'st-areas', 'aria-label': 'Stock areas at ' + site.name });
      (site.areas || []).forEach(function (a) {
        var li = el('li', { className: 'st-area' }, [el('span', { className: 'st-area__name', text: a.name })]);
        if (a.note) li.append(el('span', { className: 'st-area__note st-note--' + a.note.tone, text: a.note.text }));
        ul.append(li);
      });
      if (!(site.areas || []).length) ul.append(el('li', { className: 'st-area st-area--none', text: 'No areas: stock sits at the site itself' }));
      return ul;
    }

    // A card per site, everything about it in one place.
    function renderCards() {
      var grid = el('div', { className: 'st-grid' });
      state.sites.forEach(function (site) {
        var card = el('article', { className: 'st-site-card' + (site.is_active ? '' : ' st-site--archived'), 'data-site-id': site.id });
        card.append(
          el('div', { className: 'st-site-card__head' }, [
            el('h3', {}, [site.name, tags(site)]),
            el('p', { className: 'st-kind', text: kindLabel(site) + (site.address ? ' · ' + site.address : '') })
          ]),
          figures(site)
        );
        (site.notes || []).forEach(function (n) { card.append(note(n)); });
        card.append(el('h4', { className: 'st-subhead', text: 'Stock areas' }), areaList(site), actionLinks(site));
        grid.append(card);
      });
      return grid;
    }

    function render() {
      $('[data-sites-intro]').hidden = true;
      $('[data-sites-setup]').hidden = true;
      $('[data-sites-body]').hidden = true;
      $('[data-sites-foot]').hidden = true;
      $('[data-sites-add]').hidden = true;
      if (!state.entitled || !state.enabled) { renderIntro(); return; }
      $('[data-sites-add]').hidden = false;
      renderSetup();
      $('[data-sites-body]').hidden = false;
      register.replaceChildren(renderCards());
      var live = active().length;
      var archived = state.sites.length - live;
      $('[data-sites-summary]').textContent = plural(live, 'active site') + (archived ? ' · ' + archived + ' archived' : '') + '.';
      $('[data-sites-foot]').hidden = false;
    }

    async function load() {
      root.setAttribute('aria-busy', 'true');
      try {
        state = await api('GET', '/api/core/sites');
        loadError.hidden = true;
        render();
      } catch (error) {
        // Nothing half-loaded stays on screen to act on.
        ['[data-sites-intro]', '[data-sites-setup]', '[data-sites-body]', '[data-sites-foot]'].forEach(function (s) { $(s).hidden = true; });
        $('[data-sites-load-text]').textContent = error.message;
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
      siteForm.reset();
      siteError.hidden = true;
      var select = siteForm.kind;
      select.replaceChildren();
      Object.keys(state.kinds).forEach(function (key) {
        var option = el('option', { value: key, text: state.kinds[key] });
        option.selected = key === (site ? site.kind : 'storage');
        select.append(option);
      });
      siteForm.name.value = site ? site.name : '';
      siteForm.address.value = site ? (site.address || '') : '';
      $('[data-site-dialog-title]').textContent = site ? 'Edit ' + site.name : 'Add a site';
      $('[data-site-submit]').textContent = site ? 'Save site' : 'Add site';
      siteDialog.showModal();
      setTimeout(function () { siteForm.name.focus(); }, 0);
    }
    function openArea(site) {
      areaSite = site;
      areaForm.reset();
      areaError.hidden = true;
      $('[data-area-dialog-title]').textContent = 'Add a stock area at ' + site.name;
      $('[data-area-dialog-hint]').textContent = 'A place inside the site where stock sits: a tank bay, a dry store, a cool room.';
      areaDialog.showModal();
      setTimeout(function () { areaForm.name.focus(); }, 0);
    }

    async function toggle(on) {
      await mutate('PUT', '/api/core/sites/settings', { enabled: on }, on ? 'Multiple sites are on. Your existing stock and batches are at ' + 'your first site.' : 'Multiple sites switched off.');
    }
    $('[data-sites-toggle]').addEventListener('click', function () { toggle(true); });
    $('[data-sites-toggle-off]').addEventListener('click', function () { toggle(false); });
    $('[data-sites-add]').addEventListener('click', function () { openSite(null); });
    $('[data-site-cancel]').addEventListener('click', function () { siteDialog.close(); });
    $('[data-area-cancel]').addEventListener('click', function () { areaDialog.close(); });
    $('[data-sites-retry]').addEventListener('click', load);
    siteForm.addEventListener('submit', async function (event) {
      event.preventDefault();
      siteError.hidden = true;
      var body = Object.fromEntries(new FormData(siteForm));
      if (!body.name.trim()) { siteError.textContent = 'Give the site a name.'; siteError.hidden = false; return; }
      try {
        if (editing) await api('PATCH', '/api/core/sites/' + editing.id, body);
        else await api('POST', '/api/core/sites', body);
        siteDialog.close();
        await load();
        say(editing ? 'Saved.' : body.name + ' added.', true);
      } catch (error) {
        // A refused save stays in the dialog, next to what caused it.
        siteError.textContent = error.message;
        siteError.hidden = false;
      }
    });
    areaForm.addEventListener('submit', async function (event) {
      event.preventDefault();
      areaError.hidden = true;
      var name = areaForm.name.value.trim();
      if (!name) { areaError.textContent = 'Give the area a name.'; areaError.hidden = false; return; }
      try {
        await api('POST', '/api/core/stock-locations', { name: name, site_id: areaSite.id });
        areaDialog.close();
        await load();
        say(name + ' added at ' + areaSite.name + '.', true);
      } catch (error) {
        // Area names are unique across the business for now, so say where the clash is.
        var clash = state.sites.filter(function (s) { return (s.areas || []).some(function (a) { return a.name.toLowerCase() === name.toLowerCase(); }); })[0];
        areaError.textContent = clash ? clash.name + ' already has an area called ' + name + '. Give this one a name of its own, such as ' + name + ' (' + areaSite.name + ').' : error.message;
        areaError.hidden = false;
      }
    });

    load();
  }
  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  bize.onPage('[data-sites-root]', init);
}());
