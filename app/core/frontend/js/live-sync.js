/**
 * LiveSync — the SPA's near-real-time backbone.
 *
 * Polls GET /api/core/changes (a cursor feed over entity_events) and dispatches new
 * events to subscribers, so any page can reflect org-wide mutations without a reload.
 *
 * Transport-agnostic on purpose: the poll can be swapped for SSE/WebSocket later without
 * touching a single subscriber. Subscribers only ever see `subscribe()` / `onChange`.
 *
 *   const off = LiveSync.subscribe({
 *     key: 'flows2:' + processId,          // optional; a re-subscribe with the same key replaces
 *     match: (evt) => evt.keys.process_id === processId || evt.entity_id === processId,
 *     onChange: (evts) => { ...refetch and re-render... },   // called once per poll, batched
 *   });
 *   // later: off();
 *
 * Event shape: { seq, event_type, entity_type, entity_id, at, keys:{process_id?,execution_id?,...} }
 */
(function () {
  'use strict';

  if (window.LiveSync) return;

  var POLL_VISIBLE_MS = 3000;    // cadence right after an event / user action
  var POLL_IDLE_MAX_MS = 15000;  // cadence ceiling once the feed has gone quiet
  var IDLE_GROWTH_AFTER = 3;     // consecutive no-change polls before the interval grows
  var BACKOFF_MIN_MS = 5000;
  var BACKOFF_MAX_MS = 60000;

  var subscribers = [];          // { id, key, match, onChange }
  var subSeq = 0;
  var cursor = null;             // last seq we've processed; null until bootstrap
  var started = false;
  var polling = false;
  var timer = null;
  var backoff = BACKOFF_MIN_MS;
  var lastError = null;
  var lastEtag = null;           // ETag of the most recent /api/core/changes response
  var idleStreak = 0;            // consecutive polls that delivered nothing

  function now() { return Date.now(); }

  // 3s while things are happening; after IDLE_GROWTH_AFTER empty polls, ramp 6s, 9s, 12s,
  // 15s and hold. A delivered event, poke(), focus or `online` resets idleStreak -> 3s.
  // Cuts steady-state request volume on a quiet org ~5x with no added latency for the
  // cases a user notices (their own mutations already poke()).
  function nextInterval() {
    if (idleStreak <= IDLE_GROWTH_AFTER) return POLL_VISIBLE_MS;
    var grown = POLL_VISIBLE_MS * (idleStreak - IDLE_GROWTH_AFTER + 1);
    return grown < POLL_IDLE_MAX_MS ? grown : POLL_IDLE_MAX_MS;
  }

  function schedule(ms) {
    if (timer) { clearTimeout(timer); timer = null; }
    if (document.visibilityState === 'hidden') return;   // paused while hidden
    timer = setTimeout(runPoll, ms);
  }

  function api() { return window.CoreAPI; }

  async function fetchChanges(since) {
    var url = '/api/core/changes' + (since == null ? '' : '?since=' + encodeURIComponent(since));
    var headers = { 'Accept': 'application/json' };
    // Conditional GET: when nothing has changed since the last response's ETag the server
    // returns 304 and skips the events query entirely. Never sent on the bootstrap
    // (since == null) — that must always fetch the current head.
    if (since != null && lastEtag) headers['If-None-Match'] = lastEtag;
    var res = await fetch(url, { method: 'GET', credentials: 'same-origin', headers: headers });
    var etag = res.headers.get('ETag');
    if (etag) lastEtag = etag;
    if (res.status === 304) return { notModified: true };
    if (!res.ok) throw new Error('changes ' + res.status);
    return res.json();
  }

  async function bootstrap() {
    var data = await fetchChanges(null);
    cursor = (data && typeof data.cursor === 'number') ? data.cursor : 0;
  }

  function dispatch(events) {
    if (!events.length || !subscribers.length) return;
    // Snapshot: an onChange handler may (re)subscribe/unsubscribe.
    subscribers.slice().forEach(function (sub) {
      var hit = [];
      for (var i = 0; i < events.length; i++) {
        try { if (sub.match(events[i])) hit.push(events[i]); }
        catch (e) { /* a bad matcher must not break the loop */ }
      }
      if (hit.length) {
        try { sub.onChange(hit); }
        catch (e) { if (window.console) console.error('[LiveSync] subscriber onChange failed', e); }
      }
    });
  }

  async function runPoll() {
    if (polling) return;
    if (document.visibilityState === 'hidden') return;
    polling = true;
    try {
      if (cursor == null) { await bootstrap(); idleStreak = 0; }
      else {
        var data = await fetchChanges(cursor);
        if (data.notModified) {
          idleStreak++;
        } else {
          var events = (data && Array.isArray(data.events)) ? data.events : [];
          if (typeof data.cursor === 'number') cursor = data.cursor;
          if (events.length) { dispatch(events); idleStreak = 0; }
          else idleStreak++;
          // drain a backlog in the same wake-up rather than waiting a full interval
          if (data.has_more) { polling = false; return runPoll(); }
        }
      }
      lastError = null;
      backoff = BACKOFF_MIN_MS;
      try {
        document.dispatchEvent(new CustomEvent('live-sync:tick', { detail: { cursor: cursor } }));
      } catch (e) { /* no-op */ }
      schedule(nextInterval());
    } catch (err) {
      lastError = err;
      if (window.console) console.warn('[LiveSync] poll failed, backing off', err && err.message);
      schedule(backoff);
      backoff = Math.min(backoff * 2, BACKOFF_MAX_MS);
    } finally {
      polling = false;
    }
  }

  function pokeNow() {
    if (!started) return;
    backoff = BACKOFF_MIN_MS;
    idleStreak = 0;              // snap back to the fast cadence
    schedule(0);
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') pokeNow();
    else if (timer) { clearTimeout(timer); timer = null; }
  });
  window.addEventListener('online', pokeNow);
  window.addEventListener('focus', function () { if (started) { idleStreak = 0; schedule(POLL_VISIBLE_MS); } });

  window.LiveSync = {
    start: function () {
      if (started) return;
      started = true;
      schedule(0);
    },

    /** Register interest. Returns an unsubscribe function. */
    subscribe: function (opts) {
      opts = opts || {};
      if (typeof opts.match !== 'function' || typeof opts.onChange !== 'function') {
        throw new Error('LiveSync.subscribe requires { match, onChange }');
      }
      if (opts.key) {
        subscribers = subscribers.filter(function (s) { return s.key !== opts.key; });
      }
      var id = ++subSeq;
      var sub = { id: id, key: opts.key || null, match: opts.match, onChange: opts.onChange };
      subscribers.push(sub);
      this.start();
      return function unsubscribe() {
        subscribers = subscribers.filter(function (s) { return s.id !== id; });
      };
    },

    /** Force an immediate poll (e.g. right after the local user mutates something). */
    poke: pokeNow,

    /** Current cursor + health, for debugging / status chips. */
    status: function () {
      return { cursor: cursor, started: started, subscribers: subscribers.length, lastError: lastError ? String(lastError) : null };
    },
  };

  // Autostart once CoreAPI/base_spa are ready; harmless if called again.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { window.LiveSync.start(); });
  } else {
    window.LiveSync.start();
  }

  /**
   * A subtle bottom-right "Updated just now" pill. Shared by every LiveSync subscriber
   * that re-renders in place, so a silent swap of on-screen data isn't disorienting.
   */
  window.liveSyncFlash = function (message) {
    var host = document.getElementById('live-sync-flash');
    if (!host) {
      host = document.createElement('div');
      host.id = 'live-sync-flash';
      host.setAttribute('role', 'status');
      host.style.cssText =
        'position:fixed;bottom:16px;right:16px;background:var(--surface,#111);color:#fff;' +
        'padding:8px 14px;border-radius:999px;font-size:12px;opacity:0;transition:opacity .2s;' +
        'z-index:1200;pointer-events:none;box-shadow:0 2px 12px rgba(0,0,0,.18);';
      document.body.appendChild(host);
    }
    host.textContent = message || 'Updated just now';
    host.style.opacity = '1';
    clearTimeout(host._t);
    host._t = setTimeout(function () { host.style.opacity = '0'; }, 1800);
  };
})();
