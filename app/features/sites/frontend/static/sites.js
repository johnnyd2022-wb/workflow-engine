(function () {
  'use strict';

  // CONCEPT ONLY: the style switch goes when one style is chosen.
  var STYLE_KEY = 'st-style';

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
    var panel = $('[data-sites-panel]');
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
    var step = null;
    var style = '1';

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

    // CONCEPT ONLY ─────────────────────────────────────────────────────────────────────────
    function readStyle() {
      var fromUrl = new URLSearchParams(window.location.search).get('style');
      var saved = null;
      try { saved = window.localStorage.getItem(STYLE_KEY); } catch (_) { /* private mode */ }
      setStyle(['1', '2', '3'].indexOf(fromUrl) !== -1 ? fromUrl : (['1', '2', '3'].indexOf(saved) !== -1 ? saved : '1'), false);
    }
    function setStyle(next, remember) {
      style = next;
      root.setAttribute('data-sites-style', next);
      root.querySelectorAll('[data-st-style]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.stStyle === next ? 'true' : 'false'); });
      if (remember) { try { window.localStorage.setItem(STYLE_KEY, next); } catch (_) { /* private mode */ } }
    }
    root.querySelectorAll('[data-st-style]').forEach(function (b) {
      b.addEventListener('click', function () { setStyle(b.dataset.stStyle, true); if (state) render(); });
    });
    // ────────────────────────────────────────────────────────────────────────────────────────

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
      // Style 3 keeps the steps as its rail; Styles 1 and 2 hide them once nothing required is left.
      card.hidden = style !== '3' && left === 0;
      $('[data-sites-setup-summary]').textContent = left ? plural(left, 'step') + ' left.' : 'All set. Revisit any step below.';
      var ol = $('[data-sites-steps]');
      ol.replaceChildren();
      list.forEach(function (s, i) {
        var li = el('li', { className: 'st-step' + (s.done ? ' st-step--done' : '') + (step === s.key ? ' st-step--current' : ''), 'data-step': s.key });
        var mark = el('span', { className: 'st-step__mark', 'aria-hidden': 'true', text: s.done ? '✓' : String(i + 1) });
        var body = el('div', { className: 'st-step__body' });
        var title = style === '3'
          ? el('button', { type: 'button', className: 'st-step__title st-step__pick', text: s.title + (s.optional ? ' (optional)' : '') })
          : el('strong', { className: 'st-step__title', text: s.title + (s.optional ? ' (optional)' : '') });
        if (style === '3') title.addEventListener('click', function () { step = s.key; render(); });
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

    /** A compliance note as a pill; `brief` uses the module's short form for a table cell. */
    function note(n, brief) {
      if (!n) return null;
      var attrs = { className: 'st-note st-note--' + n.tone, text: brief && n.short ? n.short : n.text };
      if (brief && n.short) attrs.title = n.text;
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

    // Style 1: a card per site, everything about it in one place.
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

    // Style 2: a compact register; the chosen site opens beside it.
    function renderTable() {
      if (!state.sites.some(function (s) { return s.id === selected; })) selected = (defaultSite() || state.sites[0] || {}).id;
      var table = el('table', { className: 'st-table' });
      var label = state.compliance && state.compliance.label;
      var head = el('tr', {}, [['Site'], ['Stock', 'st-num'], ['Batches', 'st-num'], ['Areas', 'st-num st-wide'], label ? [label, 'st-wide'] : null].filter(Boolean).map(function (h) { return el('th', { scope: 'col', text: h[0], className: h[1] || '' }); }));
      table.append(el('thead', {}, [head]));
      var body = el('tbody');
      state.sites.forEach(function (site) {
        var tr = el('tr', { className: 'st-row' + (site.id === selected ? ' st-row--selected' : '') + (site.is_active ? '' : ' st-site--archived'), 'data-site-id': site.id, tabindex: '0', 'aria-selected': site.id === selected ? 'true' : 'false' });
        var nameCell = el('td', {}, [el('strong', {}, [site.name, tags(site)]), el('span', { className: 'st-kind', text: kindLabel(site) })]);
        tr.append(nameCell, el('td', { className: 'st-num', text: String(site.stock_lines || 0) }), el('td', { className: 'st-num', text: String(site.batches_under_way || 0) }), el('td', { className: 'st-num st-wide', text: String((site.areas || []).length) }));
        if (label) tr.append(el('td', { className: 'st-wide' }, [note((site.notes || [])[0], true)]));
        function pick() { selected = site.id; render(); }
        tr.addEventListener('click', pick);
        tr.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } });
        body.append(tr);
      });
      table.append(body);
      var site = state.sites.filter(function (s) { return s.id === selected; })[0];
      panel.replaceChildren();
      if (site) {
        panel.append(el('h3', {}, [site.name, tags(site)]), el('p', { className: 'st-kind', text: kindLabel(site) + (site.address ? ' · ' + site.address : '') }), figures(site));
        (site.notes || []).forEach(function (n) { panel.append(note(n)); });
        panel.append(el('h4', { className: 'st-subhead', text: 'Stock areas' }), areaList(site), actionLinks(site));
      }
      return el('div', { className: 'st-table-wrap' }, [table]);
    }

    // Style 3: the setup steps are the page; the chosen step shows its sites below.
    function renderStepDetail() {
      var wrap = el('div', { className: 'st-step-detail' });
      var current = step || 'sites';
      var list = el('ul', { className: 'st-compact' });
      state.sites.forEach(function (site) {
        var li = el('li', { className: 'st-compact__row' + (site.is_active ? '' : ' st-site--archived'), 'data-site-id': site.id });
        var what = el('div', { className: 'st-compact__what' }, [el('strong', {}, [site.name, tags(site)]), el('span', { className: 'st-kind', text: kindLabel(site) })]);
        li.append(what);
        if (current === 'areas') li.append(areaList(site));
        else if (current === 'licences') li.append(note((site.notes || [])[0]) || el('span', { text: '' }));
        else {
          li.append(figures(site));
          (site.notes || []).forEach(function (n) { li.append(note(n)); });
        }
        li.append(actionLinks(site));
        list.append(li);
      });
      var label = (state.compliance && state.compliance.label) || 'Compliance';
      var titles = { sites: 'Your sites', default: 'The default site', areas: 'Stock areas at each site', licences: label + ' status of each site' };
      wrap.append(el('h3', { className: 'st-step-detail__title', text: titles[current] }), list);
      return wrap;
    }

    function render() {
      $('[data-sites-intro]').hidden = true;
      $('[data-sites-setup]').hidden = true;
      $('[data-sites-body]').hidden = true;
      $('[data-sites-foot]').hidden = true;
      $('[data-sites-add]').hidden = true;
      panel.hidden = true;
      if (!state.entitled || !state.enabled) { renderIntro(); return; }
      $('[data-sites-add]').hidden = false;
      renderSetup();
      $('[data-sites-body]').hidden = false;
      panel.hidden = style !== '2';
      register.replaceChildren(style === '2' ? renderTable() : (style === '3' ? renderStepDetail() : renderCards()));
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

    readStyle();
    load();
  }
  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  bize.onPage('[data-sites-root]', init);
}());
