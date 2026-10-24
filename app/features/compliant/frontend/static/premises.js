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

    // CONCEPT ONLY: ?style=1|2|3, then the last one picked, then Style 1.
    var STYLE_KEY = 'premises-style';
    function setStyle(style) {
      root.dataset.premisesStyle = style;
      root.querySelectorAll('[data-style-pick]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.stylePick === style)); });
      try { window.localStorage.setItem(STYLE_KEY, style); } catch (_) { /* private mode */ }
    }
    (function () {
      var asked = new URLSearchParams(window.location.search).get('style');
      var kept = null;
      try { kept = window.localStorage.getItem(STYLE_KEY); } catch (_) { /* private mode */ }
      setStyle(['1', '2', '3'].indexOf(asked) >= 0 ? asked : (['1', '2', '3'].indexOf(kept) >= 0 ? kept : '1'));
    })();
    root.querySelectorAll('[data-style-pick]').forEach(function (b) {
      b.addEventListener('click', function () { setStyle(b.dataset.stylePick); });
    });

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
        el('p', { className: 'prem-licence__count', text: plural(covers.filter(live).length, 'area covered today', 'areas covered today') }),
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

    function areaRow(area) {
      var cover = currentCover(area);
      var past = coverageFor(area).filter(function (c) { return !live(c) || !live(licenceById(c.licence_id) || c); });
      var note;
      if (cover) {
        var lic = licenceById(cover.licence_id);
        var until = [cover.valid_until, lic.valid_until].filter(Boolean).sort()[0];
        note = lic.number + ' · ' + state.kinds[lic.kind] + (until ? ' · until ' + fmt(until) : '');
      } else if (past.length) {
        var last = past.slice().sort(function (a, b) { return (a.valid_until || '') < (b.valid_until || '') ? 1 : -1; })[0];
        note = 'Was under ' + (licenceById(last.licence_id) || { number: 'a licence' }).number + (last.valid_until ? ' until ' + fmt(last.valid_until) : '');
      } else {
        note = 'Never in a licensed area';
      }
      var s;
      if (cover) {
        var ends = [cover.valid_until, licenceById(cover.licence_id).valid_until].filter(Boolean).sort()[0];
        s = ends && daysFrom(ends) <= SOON_DAYS ? { code: 'soon', label: 'Licensed · ends in ' + plural(daysFrom(ends), 'day', 'days') } : { code: 'current', label: 'Licensed' };
      } else {
        s = { code: 'outside', label: 'Outside' };
      }
      return el('li', { className: 'prem-row prem-row--area' }, [
        el('div', { className: 'prem-row__main' }, [el('strong', { text: area.name }), el('span', { text: note })]),
        chip(s)
      ]);
    }

    function renderAreas(list) {
      var host = $('[data-areas]');
      host.replaceChildren();
      if (!list.length) { host.append(el('p', { className: 'prem-empty', text: 'No stock areas yet. Add them under Settings, Sites.' })); return; }
      state.sites.forEach(function (site) {
        var rows = list.filter(function (a) { return a.site.id === site.id; });
        if (!rows.length) return;
        host.append(el('section', { className: 'prem-site' }, [
          el('h3', { text: site.name }),
          el('ul', { className: 'prem-rows' }, rows.map(areaRow))
        ]));
      });
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

    // Style 3: a bar per coverage record across the months, with today marked.
    function renderTimeline(list) {
      var host = $('[data-timeline]');
      host.replaceChildren();
      if (!state.coverage.length) { host.append(el('p', { className: 'prem-empty', text: 'Nothing to chart yet: assign an area to a licence.' })); return; }
      var today = todayIso();
      var starts = state.coverage.map(function (c) { return c.valid_from; }).concat([today]);
      var start = day(starts.sort()[0]);
      start = new Date(start.getFullYear(), start.getMonth() < 6 ? 0 : 6, 1);
      var ends = state.coverage.map(function (c) { return c.valid_until || today; });
      var endDate = new Date(Math.max(day(ends.sort().reverse()[0]).getTime(), day(today).getTime()) + 180 * DAY);
      var span = endDate - start;
      function pct(iso) { return Math.max(0, Math.min(100, ((day(iso) - start) / span) * 100)); }
      var axis = el('div', { className: 'prem-axis' });
      for (var t = new Date(start); t < endDate; t = new Date(t.getFullYear(), t.getMonth() + 6, 1)) {
        var left = ((t - start) / span) * 100;
        axis.append(el('span', { className: 'prem-axis__tick', style: 'left:' + left.toFixed(2) + '%', text: t.toLocaleDateString('en-NZ', { month: 'short', year: 'numeric' }) }));
      }
      var todayLeft = pct(today).toFixed(2);
      host.append(el('div', { className: 'prem-tl-row prem-tl-row--axis' }, [el('span', { className: 'prem-tl-label' }), axis]));
      list.forEach(function (area) {
        var track = el('div', { className: 'prem-track' }, [el('span', { className: 'prem-today', style: 'left:' + todayLeft + '%', title: 'Today' })]);
        if (!coverageFor(area).length) track.append(el('span', { className: 'prem-track__none', text: 'Never in a licensed area' }));
        coverageFor(area).forEach(function (c) {
          var lic = licenceById(c.licence_id);
          var s = standing(c.valid_from, c.valid_until);
          var from = pct(c.valid_from);
          var to = c.valid_until ? pct(c.valid_until) : 100;
          track.append(el('span', {
            className: 'prem-bar prem-bar--' + s.code + (c.valid_until ? '' : ' prem-bar--open'),
            style: 'left:' + from.toFixed(2) + '%;width:' + Math.max(1, to - from).toFixed(2) + '%',
            title: (lic ? lic.number : 'Licence') + ': ' + fmt(c.valid_from) + ' to ' + (c.valid_until ? fmt(c.valid_until) : 'ongoing')
          }, [el('span', { text: lic ? lic.number : '' })]));
        });
        host.append(el('div', { className: 'prem-tl-row' }, [
          el('span', { className: 'prem-tl-label' }, [el('strong', { text: area.name }), el('small', { text: area.site.name })]),
          track
        ]));
      });
      host.append(el('p', { className: 'prem-tl-key' }, [el('span', { className: 'prem-today-key' }), ' Today · bars run from the date an area was covered to its end date; an open end means ongoing']));
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
      renderAreas(list);
      renderOutside(list);
      renderTimeline(list);
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
