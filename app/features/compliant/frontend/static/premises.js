// Customs licences and the stock areas they cover (plan 7.1c). The server checks every date
// and overlap; this page shows, for each area, whether it is licensed today and until when.
(function () {
  'use strict';

  var DAY = 86400000;
  var SOON_DAYS = 60;

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'className') node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) node.append(typeof c === 'string' ? document.createTextNode(c) : c); });
    return node;
  }

  function todayIso() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function day(iso) { return new Date(iso + 'T00:00:00'); }
  function fmt(iso) { return iso ? day(iso).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' }) : ''; }
  function daysFrom(iso) { return Math.round((day(iso) - day(todayIso())) / DAY); }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

  // Where a dated record stands today, in words.
  function standing(from, until) {
    var today = todayIso();
    if (until && until < today) return { code: 'ended', label: 'Ended ' + fmt(until) };
    if (from > today) return { code: 'later', label: 'Starts ' + fmt(from) };
    if (until && daysFrom(until) <= SOON_DAYS) return { code: 'soon', label: 'Ends in ' + plural(daysFrom(until), 'day', 'days') };
    return { code: 'current', label: 'Current' };
  }
  function live(row) { var s = standing(row.valid_from, row.valid_until).code; return s === 'current' || s === 'soon'; }

  function chip(s) { return el('span', { className: 'prem-status prem-status--' + s.code, text: s.label }); }

  async function api(path, body) {
    var csrf = document.querySelector('meta[name="csrf-token"]');
    var response = await fetch(path, { method: body ? 'POST' : 'GET', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf ? csrf.content : '' },
      body: body ? JSON.stringify(body) : undefined });
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not save Customs premises.');
    return data;
  }

  function init(root) {
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    var $ = function (sel) { return root.querySelector(sel); };
    var error = $('[data-premises-error]');
    var state;

    function report(message) { error.textContent = message || ''; error.hidden = !message; }

    function dialog(name) { return $('[data-prem-dialog="' + name + '"]'); }
    function openDialog(name) {
      var d = dialog(name);
      if (!d) return;
      if (typeof d.showModal === 'function') d.showModal(); else d.setAttribute('open', '');
      var first = d.querySelector('input, select');
      if (first) first.focus();
    }
    function closeDialog(d) { if (typeof d.close === 'function') d.close(); else d.removeAttribute('open'); }
    root.querySelectorAll('[data-open-dialog]').forEach(function (b) {
      b.addEventListener('click', function () { openDialog(b.dataset.openDialog); });
    });
    root.querySelectorAll('[data-dialog-close]').forEach(function (b) {
      b.addEventListener('click', function () { closeDialog(b.closest('dialog')); });
    });

    function licenceById(id) { return state.licences.find(function (l) { return l.id === id; }); }
    function siteById(id) { return state.sites.find(function (s) { return s.id === id; }); }
    function locationById(id) { return state.locations.find(function (l) { return l.id === id; }); }
    function areaName(row) {
      if (!row.location_id) return 'Main area';
      var loc = locationById(row.location_id);
      return loc ? loc.name : 'Archived location';
    }

    // Every place stock can sit: each named area, plus a site's main area once it has coverage.
    function areas() {
      var out = [];
      state.sites.forEach(function (site) {
        var hasMain = state.coverage.some(function (c) { return c.site_id === site.id && !c.location_id; });
        if (hasMain) out.push({ site: site, location: null, name: 'Main area' });
        state.locations.filter(function (l) { return l.site_id === site.id; }).forEach(function (l) {
          out.push({ site: site, location: l, name: l.name });
        });
      });
      return out;
    }
    function coverageFor(area) {
      return state.coverage.filter(function (c) {
        return c.site_id === area.site.id && (c.location_id || null) === (area.location ? area.location.id : null);
      });
    }
    // The coverage that licenses the area today: its own dates and its licence's both current.
    function currentCover(area) {
      return coverageFor(area).find(function (c) { var l = licenceById(c.licence_id); return live(c) && l && live(l); });
    }

    function choices(select, rows, label) {
      if (!select) return;
      var previous = select.value;
      select.replaceChildren(el('option', { value: '', text: 'Choose ' + label }));
      rows.forEach(function (row) { select.append(el('option', { value: row.id, text: row.number ? row.number + ' · ' + row.name : row.name })); });
      if (rows.some(function (row) { return row.id === previous; })) select.value = previous;
    }
    function locations() {
      var select = $('[data-location-select]');
      var site = $('[data-site-select]');
      if (!select || !site) return;
      select.replaceChildren(el('option', { value: '', text: 'Main area (without a named stock location)' }));
      state.locations.filter(function (row) { return row.site_id === site.value; }).forEach(function (row) {
        select.append(el('option', { value: row.id, text: row.name }));
      });
    }

    function licenceCard(lic) {
      var s = standing(lic.valid_from, lic.valid_until);
      var covers = state.coverage.filter(function (c) { return c.licence_id === lic.id; });
      var list = el('ul', { className: 'prem-rows prem-licence__areas' });
      covers.forEach(function (c) {
        var site = siteById(c.site_id);
        list.append(el('li', { className: 'prem-row' }, [
          el('div', { className: 'prem-row__main' }, [
            el('strong', { text: (site ? site.name : 'Archived site') + ' · ' + areaName(c) }),
            el('span', { text: c.evidence_reference })
          ]),
          el('span', { className: 'prem-row__date', text: fmt(c.valid_from) + ' to ' + (c.valid_until ? fmt(c.valid_until) : 'ongoing') })
        ]));
      });
      if (!covers.length) list.append(el('li', { className: 'prem-empty', text: 'No areas assigned to this licence yet.' }));
      return el('article', { className: 'prem-licence prem-licence--' + s.code }, [
        el('div', { className: 'prem-licence__head' }, [
          el('h3', { text: lic.number + ' · ' + lic.name }),
          chip(s)
        ]),
        el('p', { className: 'prem-licence__facts', text: [state.kinds[lic.kind], 'Entity ' + lic.legal_entity_reference,
          fmt(lic.valid_from) + ' to ' + (lic.valid_until ? fmt(lic.valid_until) : 'ongoing')].join(' · ') }),
        el('p', { className: 'prem-licence__doc', text: lic.evidence_reference }),
        list
      ]);
    }

    function renderLicences() {
      var host = $('[data-licences]');
      var current = state.licences.filter(function (l) { return standing(l.valid_from, l.valid_until).code !== 'ended'; });
      var ended = state.licences.filter(function (l) { return standing(l.valid_from, l.valid_until).code === 'ended'; });
      host.replaceChildren();
      if (!state.licences.length) host.append(el('p', { className: 'prem-empty', text: 'No Customs licences registered. Register your CCA licence to put stock areas inside it.' }));
      current.forEach(function (l) { host.append(licenceCard(l)); });
      var box = $('[data-prem-ended]');
      box.hidden = !ended.length;
      box.querySelector('summary').textContent = 'Ended (' + ended.length + ')';
      box.querySelector('.prem-licences').replaceChildren.apply(box.querySelector('.prem-licences'), ended.map(licenceCard));
      $('[data-prem-licences-note]').textContent = current.length
        ? plural(current.length, 'current licence', 'current licences') + (ended.length ? ' · ' + ended.length + ' ended' : '')
        : 'None current';
    }

    function renderOutside(list) {
      var outside = list.filter(function (a) { return !currentCover(a); });
      $('[data-prem-outside-card]').hidden = !outside.length;
      $('[data-prem-outside]').replaceChildren.apply($('[data-prem-outside]'), outside.map(function (a) {
        return el('li', { className: 'prem-row' }, [el('div', { className: 'prem-row__main' }, [
          el('strong', { text: a.site.name + ' · ' + a.name }),
          el('span', { text: coverageFor(a).length ? 'Its coverage has ended' : 'Never in a licensed area' })
        ])]);
      }));
    }

    function render() {
      choices($('[data-licence-select]'), state.licences.filter(function (l) { return standing(l.valid_from, l.valid_until).code !== 'ended'; }), 'a licence');
      choices($('[data-site-select]'), state.sites, 'a site');
      locations();
      var list = areas();
      var covered = list.filter(currentCover).length;
      var current = state.licences.filter(live);
      var soon = current.filter(function (l) { return standing(l.valid_from, l.valid_until).code === 'soon'; });
      var parts = [plural(covered, 'area licensed', 'areas licensed') + ' under ' + plural(current.length, 'current licence', 'current licences')];
      if (soon.length) parts.push(soon[0].number + ' ' + standing(soon[0].valid_from, soon[0].valid_until).label.toLowerCase());
      if (list.length - covered) parts.push(plural(list.length - covered, 'area outside', 'areas outside'));
      $('[data-prem-summary]').textContent = state.licences.length ? parts.join(' · ') : '';
      renderLicences();
      renderOutside(list);
      root.setAttribute('aria-busy', 'false');
    }

    async function load() {
      state = await api('/api/compliant/nz-alcohol/premises');
      render();
    }

    var siteSelect = $('[data-site-select]');
    if (siteSelect) siteSelect.addEventListener('change', locations);
    function bind(selector, path) {
      var form = $(selector); if (!form) return;
      form.addEventListener('submit', async function (event) {
        event.preventDefault(); report('');
        var formError = form.querySelector('[data-form-error]');
        formError.hidden = true;
        var button = form.querySelector('button[type="submit"]'); button.disabled = true;
        var body = Object.fromEntries(new FormData(form));
        body.valid_until = body.valid_until || null;
        if (Object.hasOwn(body, 'location_id')) body.location_id = body.location_id || null;
        try { await api(path, body); form.reset(); closeDialog(form.closest('dialog')); await load(); }
        catch (err) { formError.textContent = err.message; formError.hidden = false; } finally { button.disabled = false; }
      });
    }
    bind('[data-licence-form]', '/api/compliant/nz-alcohol/cca-licences');
    bind('[data-coverage-form]', '/api/compliant/nz-alcohol/cca-coverage');
    load().catch(function (err) { report(err.message); root.classList.add('prem-failed'); root.setAttribute('aria-busy', 'false'); });
  }

  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  bize.onPage('[data-premises-root]', init);
}());
