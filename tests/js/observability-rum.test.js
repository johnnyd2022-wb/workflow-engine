/**
 * Browser-free checks for the RUM sampling boundary and trace propagation scope.
 * Run: node --test tests/js/observability-rum.test.js
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');

const rumSource = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'ui', 'shared', 'observability-rum.js'),
  'utf8'
);

function runRum(sampleRate) {
  const calls = { faro: [] };
  const window = {
    __RUM_CONFIG__: { enabled: true, sampleRate, collectorUrl: '/telemetry' },
    location: { origin: 'https://app.example.test', pathname: '/core/dashboard' },
    localStorage: { getItem: () => null, setItem: () => {} },
    addEventListener: () => {},
    GrafanaFaroWebSdk: {
      getWebInstrumentations: () => [],
      initializeFaro: (config) => {
        calls.faro.push(config);
        return { api: { pushEvent: () => {} } };
      },
    },
    GrafanaFaroWebTracing: {
      TracingInstrumentation: class TracingInstrumentation {
        constructor(config) {
          this.config = config;
        }
      },
    },
  };
  const document = { body: { addEventListener: () => {} }, addEventListener: () => {}, referrer: '' };
  const math = Object.create(Math);
  math.random = () => 0.5;

  vm.runInNewContext(rumSource, { window, document, Math: math, Number, String, RegExp, Uint8Array });
  return { calls, window };
}

test('0% RUM sampling does not initialise a vendor SDK', () => {
  const { calls } = runRum(0);
  assert.equal(calls.faro.length, 0);
});

test('sampled RUM sessions use one sampler and same-origin trace propagation', () => {
  const { calls } = runRum(1);
  assert.equal(calls.faro.length, 1);
  assert.equal(calls.faro[0].sessionTracking.samplingRate, 1);

  const tracing = calls.faro[0].instrumentations[0];
  const propagationPattern = tracing.config.propagateTraceHeaderCorsUrls[0];
  assert.equal(propagationPattern.test('https://app.example.test/api/core/processes'), true);
  assert.equal(propagationPattern.test('https://telemetry.example.test/collect'), false);
});
