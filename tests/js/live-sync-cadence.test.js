/**
 * Node unit tests for live-sync.js's adaptive poll cadence.
 * Run: node --test tests/js/live-sync-cadence.test.js
 *
 * !206 made a no-change poll cheap on the server (304, no events query) but the client
 * still schedule()d a fixed 3s. This tests the follow-on: after IDLE_GROWTH_AFTER (3)
 * consecutive no-change polls the interval ramps 6s, 9s, 12s, 15s and holds; a delivered
 * event or poke() snaps it back to 3s.
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

function res({ status = 200, body = {} }) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: () => null },
    json: async () => body,
  };
}

function load() {
  const timers = []; // { fn, ms }
  let fetchQueue = [];
  const noop = () => {};
  const sandbox = {
    console: { warn: noop, error: noop, log: noop },
    Date: { now: () => 1000 },
    CustomEvent: class { constructor(t, i) { this.type = t; this.detail = i && i.detail; } },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    clearTimeout: noop,
    fetch: () => {
      const next = fetchQueue.shift();
      if (!next) throw new Error('fetch with no queued response');
      return Promise.resolve(next);
    },
    document: {
      visibilityState: 'visible', readyState: 'complete',
      addEventListener: noop, dispatchEvent: noop,
      getElementById: () => null, createElement: () => ({ style: {}, setAttribute: noop }),
      body: { appendChild: noop },
    },
  };
  sandbox.window = sandbox;
  sandbox.window.addEventListener = noop;
  vm.runInNewContext(SRC, sandbox);

  return {
    LiveSync: sandbox.window.LiveSync,
    queue: (r) => fetchQueue.push(r),
    lastMs: () => timers[timers.length - 1].ms,
    tick: async () => { await timers.pop().fn(); },
  };
}

const NOCHANGE = () => res({ status: 304 });
const EVENT = () => res({ body: { cursor: 9, has_more: false, events: [{ seq: 9, event_type: 'x', keys: {} }] } });

test('interval ramps 3,3,3,6,9,12,15 and holds at 15s over consecutive no-change polls', async () => {
  const h = load();
  h.queue(res({ body: { cursor: 5, has_more: false, events: [] } })); // bootstrap
  await h.tick();

  const seen = [];
  for (let i = 0; i < 8; i++) {
    h.queue(NOCHANGE());
    await h.tick();
    seen.push(h.lastMs());
  }
  assert.deepEqual(seen, [3000, 3000, 3000, 6000, 9000, 12000, 15000, 15000]);
});

test('a delivered event snaps the interval back to 3s', async () => {
  const h = load();
  h.queue(res({ body: { cursor: 5, has_more: false, events: [] } }));
  await h.tick();

  for (let i = 0; i < 6; i++) { h.queue(NOCHANGE()); await h.tick(); }
  assert.ok(h.lastMs() > 3000, 'should have ramped up while idle');

  h.queue(EVENT());
  await h.tick();
  assert.equal(h.lastMs(), 3000, 'an event resets to the fast cadence');
});

test('poke() resets the idle streak', async () => {
  const h = load();
  h.queue(res({ body: { cursor: 5, has_more: false, events: [] } }));
  await h.tick();

  for (let i = 0; i < 6; i++) { h.queue(NOCHANGE()); await h.tick(); }
  assert.ok(h.lastMs() > 3000);

  h.LiveSync.poke(); // schedules an immediate poll
  h.queue(NOCHANGE());
  await h.tick();
  assert.equal(h.lastMs(), 3000, 'after poke() the next scheduled interval is fast again');
});
