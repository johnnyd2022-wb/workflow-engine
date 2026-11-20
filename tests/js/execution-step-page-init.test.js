'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const controller = fs.readFileSync(
  path.join(__dirname, '../../app/core/frontend/js/execution-step-page.js'),
  'utf8'
);

function startPage() {
  let now = 1_000;
  const requests = [];
  const rendered = [];
  const subtitle = { textContent: '' };
  const elements = { 'execute-step-modal': {}, 'exec-step-subtitle': subtitle };
  const window = {
    location: { pathname: '/core/flows/batches/start' },
    ExecutionStepPageContext: { processId: 'process', executionId: 'first' },
    addEventListener() {},
    CoreAPI: {
      getExecution() {},
      getExecutionWithProcess(id) {
        return new Promise(resolve => requests.push({ id, resolve }));
      }
    },
    openExecutionModal(id) { rendered.push(id); }
  };
  const document = {
    readyState: 'complete',
    getElementById: id => elements[id],
    addEventListener() {},
    body: { addEventListener() {} }
  };
  vm.runInNewContext(controller, { window, document, Date: { now: () => now }, queueMicrotask, console });
  return {
    requests,
    rendered,
    subtitle,
    initializeAgain(id) {
      now += 60;
      if (id) window.ExecutionStepPageContext = { processId: 'process', executionId: id };
      window.initExecutionStepScreen();
    }
  };
}

function resolveExecution(request, name) {
  request.resolve({
    meta: { bundle: 'execution_with_process', minimal: true },
    execution: { execution_steps: [{ status: 'ready', step_id: 'step' }] },
    process: { steps: [{ id: 'step', name }] }
  });
}

const settle = () => new Promise(setImmediate);

test('repeat initialization shares the in-flight execution load', async () => {
  const page = startPage();
  await settle();
  page.initializeAgain();
  await settle();
  resolveExecution(page.requests[0], 'First step');
  await settle();

  assert.deepEqual(page.requests.map(request => request.id), ['first']);
  assert.deepEqual(page.rendered, ['first']);
  assert.equal(page.subtitle.textContent, 'Step: First step');
});

test('a changed execution context reruns as soon as the stale load finishes', async () => {
  const page = startPage();
  await settle();
  page.initializeAgain('second');
  await settle();
  resolveExecution(page.requests[0], 'Stale step');
  await settle();

  assert.deepEqual(page.requests.map(request => request.id), ['first', 'second']);
  assert.deepEqual(page.rendered, []);
  resolveExecution(page.requests[1], 'Current step');
  await settle();
  assert.deepEqual(page.rendered, ['second']);
  assert.equal(page.subtitle.textContent, 'Step: Current step');
});
