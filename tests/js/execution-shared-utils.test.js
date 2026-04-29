/**
 * Node unit tests for execution-shared-utils (no browser).
 * Run: node --test tests/js/execution-shared-utils.test.js
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const utilsPath = path.join(
  __dirname,
  '..',
  '..',
  'app',
  'core',
  'frontend',
  'js',
  'execution-shared-utils.js'
);
const { convertUnit, prettyLabel, loadOrgUsersMap } = require(utilsPath);

test('prettyLabel normalizes snake_case and capitalizes', () => {
  assert.equal(prettyLabel('raw_material'), 'Raw Material');
  assert.equal(prettyLabel('  a_b  c  '), 'A B C');
  assert.equal(prettyLabel(''), '');
  assert.equal(prettyLabel(null), '');
});

test('convertUnit returns same quantity for matching units', () => {
  assert.equal(convertUnit(5, 'kg', 'KG'), 5);
  assert.equal(convertUnit(3, 'l', 'L'), 3);
});

test('convertUnit mass kg <-> g', () => {
  assert.ok(Math.abs(convertUnit(1, 'kg', 'g') - 1000) < 1e-9);
  assert.ok(Math.abs(convertUnit(1000, 'g', 'kg') - 1) < 1e-9);
});

test('convertUnit volume L <-> mL', () => {
  assert.ok(Math.abs(convertUnit(1, 'L', 'mL') - 1000) < 1e-9);
});

test('convertUnit mixed incompatible families returns original quantity', () => {
  assert.equal(convertUnit(10, 'kg', 'L'), 10);
});

test('loadOrgUsersMap uses cached Map on globalThis when present', async () => {
  const cached = new Map([['x', 'Label']]);
  globalThis.__OrgUsersMap = cached;
  const result = await loadOrgUsersMap();
  assert.equal(result, cached);
  delete globalThis.__OrgUsersMap;
});
