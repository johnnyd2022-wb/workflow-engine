// Shared helpers for the three Customs pages (entry, stock, settings). Pure functions only:
// each page script binds to its own root, so a boosted visit re-binds without a window flag.
(function () {
  'use strict';

  function csrf() { var m = document.querySelector('meta[name="csrf-token"]'); return m ? m.getAttribute('content') : ''; }

  async function api(method, url, body) {
    var headers = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET') headers['X-CSRFToken'] = csrf();
    var res = await fetch(url, { method: method, credentials: 'include', headers: headers, body: body === undefined ? undefined : JSON.stringify(body) });
    var data = {}; try { data = await res.json(); } catch (_) {}
    if (!res.ok) throw new Error(data.error || ('Request failed (' + res.status + ')'));
    return data;
  }

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (attrs[k] == null) return;
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'className') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (k) { if (k) n.append(k); });
    return n;
  }

  function fmtDate(iso) { if (!iso) return '—'; var d = new Date(iso + 'T00:00:00'); return isNaN(d) ? iso : d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' }); }
  function shortDate(iso) { if (!iso) return '—'; var d = new Date(iso + 'T00:00:00'); return isNaN(d) ? iso : d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' }); }
  function money(v) { return v == null ? '—' : '$' + Number(v).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function wholeMoney(v) { return v == null ? '—' : '$' + Number(v).toLocaleString('en-NZ', { maximumFractionDigits: 0 }); }
  function num(v, dp) { return v == null ? '—' : Number(v).toLocaleString('en-NZ', { minimumFractionDigits: dp, maximumFractionDigits: dp }); }
  function qty(v) { return v == null ? '—' : Number(v).toLocaleString('en-NZ', { maximumFractionDigits: 3 }); }
  function todayIso() { var d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
  function daysUntil(iso) { return Math.round((new Date(iso + 'T00:00:00') - new Date(todayIso() + 'T00:00:00')) / 86400000); }
  // "12 Oct" this year, "12 Oct 2027" otherwise: a date without its year can read as the wrong one.
  function dayMonth(iso) {
    if (!iso) return '—';
    return String(iso).slice(0, 4) === todayIso().slice(0, 4) ? shortDate(iso) : fmtDate(iso);
  }
  // "1 bottle", "2 bottles": the stock unit, singular for one.
  function amount(q, unit) {
    var n = Number(q); var u = unit || '';
    if (n === 1 && /s$/.test(u)) u = u.slice(0, -1);
    return qty(q) + (u ? ' ' + u : '');
  }
  function plural(n, word, many) { return n + ' ' + (n === 1 ? word : (many || word + 's')); }
  function slug(text) { return String(text || '').replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase(); }

  // Errors go to the page's one error line; console too, so the screenshot harness sees them.
  // A "Loading…" placeholder ([data-loading]) still on the page when something fails never
  // finished: it says so, rather than spinning beside the error (GL-U04).
  function failer(page) {
    var box = page.querySelector('[data-compliant-error]');
    return function (msg) {
      // Leaving the page cuts its requests off; that is not an error to show or log.
      if (msg && window.__coreApiPageUnloading) return;
      if (msg) console.error('[customs]', msg);
      if (box) { box.textContent = msg || ''; box.hidden = !msg; }
      if (msg) markNotLoaded(page);
    };
  }
  function markNotLoaded(scope) {
    scope.querySelectorAll('[data-loading]').forEach(function (node) {
      node.textContent = 'Not loaded. Reload the page to try again.';
      node.removeAttribute('data-loading');
      node.setAttribute('data-not-loaded', '');
    });
  }

  // A small "fact" for summary strips and cards: a label, a value, and a line of context.
  function fact(label, value, note, tone) {
    return el('div', { className: 'customs-fact' + (tone ? ' customs-fact--' + tone : '') }, [
      el('span', { className: 'customs-fact__label', text: label }),
      el('strong', { className: 'customs-fact__value', text: value }),
      note ? el('span', { className: 'customs-fact__note', text: note }) : null,
    ]);
  }

  window.CustomsUI = {
    api: api, el: el, fmtDate: fmtDate, shortDate: shortDate, money: money, wholeMoney: wholeMoney, num: num,
    qty: qty, amount: amount, dayMonth: dayMonth, todayIso: todayIso, daysUntil: daysUntil, plural: plural, slug: slug, failer: failer, markNotLoaded: markNotLoaded, fact: fact,
  };
})();
