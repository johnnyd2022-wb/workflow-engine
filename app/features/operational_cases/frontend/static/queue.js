/**
 * Cases queue (/core/cases): the default needs-attention work list, with My cases,
 * Needs owner, Overdue, Awaiting verification and All filters. LiveSync-refreshed.
 */
(function () {
  'use strict';

  var currentFilter = new URLSearchParams(location.search).get('filter') || 'needs_attention';
  var nextCursor = null;
  var loadedCases = [];
  var lastGoodCases = null;
  var loading = false;

  function api() { return window.CoreAPI; }

  function filterParams(filter) {
    switch (filter) {
      case 'me': return { owner: 'me' };
      case 'needs_owner': return { owner: 'needs_owner' };
      case 'overdue': return { status: 'overdue' };
      case 'awaiting_verification': return { status: 'awaiting_verification' };
      case 'all': return { status: 'all' };
      case 'needs_attention':
      default: return {};
    }
  }

  function emptyMessage(filter) {
    switch (filter) {
      case 'me': return 'No cases are assigned to you right now.';
      case 'needs_owner': return 'Every active case has an active owner.';
      case 'overdue': return 'Nothing is overdue right now.';
      case 'awaiting_verification': return 'No cases are waiting on independent verification.';
      case 'all': return 'No cases exist for this organisation yet.';
      case 'needs_attention':
      default: return 'Nothing needs attention right now.';
    }
  }

  function fmtDate(iso) {
    if (!iso) return '—';
    try {
      var d = new Date(iso);
      if (Number.isNaN(d.getTime())) return '—';
      return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    } catch (e) { return '—'; }
  }

  function isOverdue(caseRow) {
    if (!caseRow.due_at) return false;
    if (caseRow.status !== 'open' && caseRow.status !== 'acknowledged' && caseRow.status !== 'in_progress' && caseRow.status !== 'resolved') return false;
    return new Date(caseRow.due_at).getTime() < Date.now();
  }

  function statusLabel(status) {
    var labels = {
      open: 'Open', acknowledged: 'Acknowledged', in_progress: 'In progress',
      resolved: 'Resolved — awaiting verification', verified: 'Verified', dismissed: 'Dismissed'
    };
    return labels[status] || status;
  }

  function renderCase(caseRow) {
    var li = document.createElement('li');
    li.className = 'oc-card' + (isOverdue(caseRow) ? ' oc-card--overdue' : '');

    var a = document.createElement('a');
    a.className = 'oc-card__link';
    a.href = '/core/cases/' + encodeURIComponent(caseRow.id) + '?return_to=' + encodeURIComponent('/core/cases?filter=' + currentFilter);
    a.setAttribute('hx-boost', 'false');

    var top = document.createElement('div');
    top.className = 'oc-card__top';
    var sev = document.createElement('span');
    sev.className = 'oc-badge oc-badge--critical';
    sev.textContent = 'Critical';
    var status = document.createElement('span');
    status.className = 'oc-badge oc-badge--status oc-badge--status-' + caseRow.status;
    status.textContent = statusLabel(caseRow.status);
    top.appendChild(sev);
    top.appendChild(status);
    if (isOverdue(caseRow)) {
      var overdueBadge = document.createElement('span');
      overdueBadge.className = 'oc-badge oc-badge--overdue';
      overdueBadge.textContent = 'Overdue';
      top.appendChild(overdueBadge);
    }

    var title = document.createElement('h3');
    title.className = 'oc-card__title';
    title.textContent = caseRow.title;

    var meta = document.createElement('div');
    meta.className = 'oc-card__meta';
    meta.appendChild(document.createTextNode('Owner: ' + (caseRow.owner_active ? (caseRow.owner_email || caseRow.owner_id) : 'Owner unavailable — reassign')));
    var dueSpan = document.createElement('span');
    dueSpan.textContent = 'Due: ' + fmtDate(caseRow.due_at);
    meta.appendChild(dueSpan);

    var nextAction = document.createElement('p');
    nextAction.className = 'oc-card__next-action';
    nextAction.textContent = caseRow.next_action;

    a.appendChild(top);
    a.appendChild(title);
    a.appendChild(meta);
    a.appendChild(nextAction);
    li.appendChild(a);
    return li;
  }

  function render() {
    var list = document.querySelector('[data-oc-list]');
    var empty = document.querySelector('[data-oc-empty]');
    var pagination = document.querySelector('[data-oc-pagination]');
    if (!list) return;
    list.innerHTML = '';
    loadedCases.forEach(function (c) { list.appendChild(renderCase(c)); });
    if (empty) {
      empty.hidden = loadedCases.length !== 0;
      empty.textContent = emptyMessage(currentFilter);
    }
    if (pagination) pagination.hidden = !nextCursor;
  }

  function setLoading(isLoading) {
    loading = isLoading;
    var el = document.querySelector('[data-oc-loading]');
    if (el) el.hidden = !isLoading;
  }

  function setError(message) {
    var el = document.querySelector('[data-oc-error]');
    if (!el) return;
    el.hidden = !message;
    el.textContent = message || '';
  }

  function setStale(isStale) {
    var el = document.querySelector('[data-oc-stale]');
    if (el) el.hidden = !isStale;
  }

  async function load(reset) {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      var params = filterParams(currentFilter);
      if (!reset && nextCursor) params.cursor = nextCursor;
      var data = await api().listCases(params);
      var cases = (data && Array.isArray(data.cases)) ? data.cases : [];
      loadedCases = reset ? cases : loadedCases.concat(cases);
      loadedCases = Array.from(new Map(loadedCases.map(function (c) { return [c.id, c]; })).values());
      lastGoodCases = loadedCases.slice();
      nextCursor = data && data.next_cursor ? data.next_cursor : null;
      setStale(false);
      render();
    } catch (e) {
      if (lastGoodCases) {
        loadedCases = lastGoodCases.slice();
        render();
        setStale(true);
      } else {
        setError((e && e.message) || 'Could not load cases. Please retry.');
      }
    } finally {
      setLoading(false);
    }
  }

  function bindTabs() {
    var wrap = document.querySelector('[data-oc-filter-tabs]');
    if (!wrap) return;
    wrap.addEventListener('click', function (ev) {
      var btn = ev.target && ev.target.closest('[data-oc-filter]');
      if (!btn) return;
      var filter = btn.getAttribute('data-oc-filter');
      if (filter === currentFilter) return;
      currentFilter = filter; history.replaceState(null, '', '/core/cases?filter=' + encodeURIComponent(filter));
      nextCursor = null;
      var tabs = wrap.querySelectorAll('[data-oc-filter]');
      tabs.forEach(function (t) { t.setAttribute('aria-selected', t === btn ? 'true' : 'false'); });
      load(true);
    });
  }

  function bindRetry() {
    var retryBtn = document.querySelector('[data-oc-retry]');
    if (retryBtn) retryBtn.addEventListener('click', function () { load(true); });
    var loadMoreBtn = document.querySelector('[data-oc-load-more]');
    if (loadMoreBtn) loadMoreBtn.addEventListener('click', function () { load(false); });
  }

  function bindLiveSync() {
    if (!window.LiveSync) return;
    window.LiveSync.subscribe({
      key: 'operational-cases-queue',
      match: function (evt) { return evt.entity_type === 'operational_case'; },
      onChange: function () {
        if (document.hidden || !document.querySelector('[data-oc-queue-root]')) return;
        load(true);
        if (typeof window.liveSyncFlash === 'function') window.liveSyncFlash('Cases updated');
      },
    });
  }

  function init() {
    if (!document.querySelector('[data-oc-queue-root]')) return;
    document.addEventListener('visibilitychange', function () { if (!document.hidden && document.querySelector('[data-oc-queue-root]')) load(true); });
    bindTabs();
    bindRetry();
    bindLiveSync();
    load(true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
