/**
 * Node unit tests for execution-session (WeakMap-backed session store).
 * Run: node --test tests/js/execution-session.test.js
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const sessionPath = path.join(
  __dirname,
  '..',
  '..',
  'app',
  'core',
  'frontend',
  'js',
  'execution-session.js'
);
const SessionAPI = require(sessionPath);

test('get returns stable maps until reset', () => {
  const el = {};
  const a = SessionAPI.get(el);
  const b = SessionAPI.get(el);
  assert.equal(a, b);
  a.inputStateByKey.set('x', 1);
  assert.equal(SessionAPI.get(el).inputStateByKey.get('x'), 1);
});

test('resetForOpen clears staging state', () => {
  const el = {};
  SessionAPI.get(el).pendingEvidenceFilesByStepId.set('s1', [1]);
  SessionAPI.resetForOpen(el);
  assert.equal(SessionAPI.get(el).pendingEvidenceFilesByStepId.size, 0);
});

test('new session has expected shape', () => {
  const el = {};
  SessionAPI.resetForOpen(el);
  const s = SessionAPI.get(el);
  assert.ok(s.inputStateByKey instanceof Map);
  assert.ok(s.pendingEvidenceFilesByStepId instanceof Map);
  assert.ok(s.evidenceByStepId instanceof Map);
  // No shared "editing row" field: each material's own input section tracks its active
  // row locally now (execution-render-inputs.js) -- a shared one here caused one
  // material's confirm click to silently apply to another's row.
  assert.equal('editingInputRow' in s, false);
});
