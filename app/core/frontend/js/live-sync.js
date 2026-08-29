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

  var POLL_VISIBLE_MS = 3000;
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

  function now() { return Date.now(); }

  function schedule(ms) {
    if (timer) { clearTimeout(timer); timer = null; }
    if (document.visibilityState === 'hidden') return;   // paused while hidden
    timer = setTimeout(runPoll, ms);
  }

  function api() { return window.CoreAPI; }

  async function fetchChanges(since) {
    var url = '/api/core/changes' + (since == null ? '' : '?since=' + encodeURIComponent(since));
    var res = await fetch(url, { method: 'GET', credentials: 'same-origin', headers: { 'Accept': 'application/json' } });
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
      if (cursor == null) { await bootstrap(); }
      else {
        var data = await fetchChanges(cursor);
        if (!data.notModified) {
          var events = (data && Array.isArray(data.events)) ? data.events : [];
          if (typeof data.cursor === 'number') cursor = data.cursor;
          if (events.length) dispatch(events);
          // drain a backlog in the same wake-up rather than waiting a full interval
          if (data.has_more) { polling = false; return runPoll(); }
        }
      }
      lastError = null;
      backoff = BACKOFF_MIN_MS;
      try {
        document.dispatchEvent(new CustomEvent('live-sync:tick', { detail: { cursor: cursor } }));
      } catch (e) { /* no-op */ }
      schedule(POLL_VISIBLE_MS);
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
    schedule(0);
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') pokeNow();
    else if (timer) { clearTimeout(timer); timer = null; }
  });
  window.addEventListener('online', pokeNow);
  window.addEventListener('focus', function () { if (started) schedule(POLL_VISIBLE_MS); });

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
})();
