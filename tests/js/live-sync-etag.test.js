/**
 * Node unit tests for live-sync.js's conditional-GET (ETag / If-None-Match) behaviour.
 * Run: node --test tests/js/live-sync-etag.test.js
 *
 * live-sync.js is a browser IIFE with no module.exports, so it is loaded into a vm
 * sandbox with just enough fake window/document/fetch/setTimeout to drive one poll at a
 * time. The behaviour under test (MR !201 P2): the server already answers a conditional
 * GET with 304 when nothing changed, but the client never sent `If-None-Match`, so every
 * 3s poll ran the full events query. It must now persist the response ETag and send it on
 * the next non-bootstrap poll, and leave the cursor untouched on a 304.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const vm = require('node:vm');

const SRC = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'core', 'frontend', 'js', 'live-sync.js'),
  'utf8'
);

function makeResponse({ status = 200, etag = null, body = {} }) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (name) => (name.toLowerCase() === 'etag' ? etag : null) },
    json: async () => body,
  };
}

function loadLiveSync() {
  const timers = []; // scheduled { fn }
  const fetchCalls = [];
  let fetchQueue = [];

  const noop = () => {};
  const sandbox = {
    console: { warn: noop, error: noop, log: noop },
    Date: { now: () => 1000 },
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
    setTimeout: (fn) => { timers.push({ fn }); return timers.length; },
    clearTimeout: noop,
    fetch: (url, opts) => {
      fetchCalls.push({ url, headers: (opts && opts.headers) || {} });
      const next = fetchQueue.shift();
      if (!next) throw new Error('fetch called with no queued response: ' + url);
      return Promise.resolve(next);
    },
    document: {
      visibilityState: 'visible',
      readyState: 'complete',
      addEventListener: noop,
      dispatchEvent: noop,
      getElementById: () => null,
      createElement: () => ({ style: {}, setAttribute: noop }),
      body: { appendChild: noop },
    },
  };
  sandbox.window = sandbox;
  sandbox.window.addEventListener = noop;

  vm.runInNewContext(SRC, sandbox);

  return {
    LiveSync: sandbox.window.LiveSync,
    fetchCalls,
    queueFetch: (r) => fetchQueue.push(r),
    // run the most recently scheduled callback (the poll loop schedules exactly one)
    tick: async () => {
      const t = timers.pop();
      assert.ok(t, 'expected a scheduled timer');
      await t.fn();
    },
  };
}

test('bootstrap poll sends no If-None-Match; subsequent polls carry the stored ETag', async () => {
  const h = loadLiveSync();

  // 1. bootstrap (since == null) -> head cursor 5, ETag "5"
  h.queueFetch(makeResponse({ etag: '"5"', body: { cursor: 5, has_more: false, events: [] } }));
  await h.tick();

  assert.equal(h.fetchCalls[0].url, '/api/core/changes');
  assert.equal(h.fetchCalls[0].headers['If-None-Match'], undefined, 'bootstrap must not be conditional');
  assert.equal(h.LiveSync.status().cursor, 5);

  // 2. next poll -> since=5, and it must send If-None-Match: "5"
  h.queueFetch(makeResponse({ status: 304 }));
  await h.tick();

  assert.equal(h.fetchCalls[1].url, '/api/core/changes?since=5');
  assert.equal(h.fetchCalls[1].headers['If-None-Match'], '"5"');
});

test('a 304 leaves the cursor untouched and the next poll re-sends the same ETag', async () => {
  const h = loadLiveSync();
  h.queueFetch(makeResponse({ etag: '"5"', body: { cursor: 5, has_more: false, events: [] } }));
  await h.tick(); // bootstrap

  h.queueFetch(makeResponse({ status: 304 })); // no ETag header on a 304
  await h.tick();
  assert.equal(h.LiveSync.status().cursor, 5, 'cursor must not move on 304');

  h.queueFetch(makeResponse({ status: 304 }));
  await h.tick();
  assert.equal(h.fetchCalls[2].headers['If-None-Match'], '"5"', 'still sends the last good ETag');
});

test('a 200 with new events advances the cursor and the stored ETag', async () => {
  const h = loadLiveSync();
  h.queueFetch(makeResponse({ etag: '"5"', body: { cursor: 5, has_more: false, events: [] } }));
  await h.tick(); // bootstrap

  h.queueFetch(
    makeResponse({
      etag: '"7"',
      body: { cursor: 7, has_more: false, events: [{ seq: 7, event_type: 'process.updated', keys: {} }] },
    })
  );
  await h.tick();
  assert.equal(h.LiveSync.status().cursor, 7);

  h.queueFetch(makeResponse({ status: 304 }));
  await h.tick();
  assert.equal(h.fetchCalls[2].url, '/api/core/changes?since=7');
  assert.equal(h.fetchCalls[2].headers['If-None-Match'], '"7"', 'ETag updated to the newest response');
});
