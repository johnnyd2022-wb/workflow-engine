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
    __RUM_CONFIG__: {
      enabled: true,
      grafanaDataEnabled: true,
      sampleRate,
      collectorUrl: '/telemetry',
    },
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

function runPosthog(maskInputs) {
  const inits = [];
  const window = {
    __RUM_CONFIG__: {
      enabled: true,
      posthogDataEnabled: true,
      posthogApiKey: 'phc_test',
      sampleRate: 1,
      collectorUrl: '/telemetry',
      maskInputs,
    },
    location: { origin: 'https://app.example.test', pathname: '/core/people' },
    localStorage: { getItem: () => null, setItem: () => {} },
    addEventListener: () => {},
    posthog: { init: (key, options) => inits.push(options) },
  };
  const document = { body: { addEventListener: () => {} }, addEventListener: () => {}, referrer: '' };
  const math = Object.create(Math);
  math.random = () => 0.5;
  vm.runInNewContext(rumSource, { window, document, Math: math, Number, String, RegExp, Uint8Array });
  return inits[0];
}

test('session replay masks page text as well as inputs (GL-S04)', () => {
  const options = runPosthog(true);
  assert.equal(options.session_recording.maskAllInputs, true);
  assert.equal(options.session_recording.maskTextSelector, '*');
});

test('turning masking off is explicit and turns both off', () => {
  const options = runPosthog(false);
  assert.equal(options.session_recording.maskAllInputs, false);
  assert.equal(options.session_recording.maskTextSelector, null);
});

test('invite links and token parameters never reach an event (GL-S04)', () => {
  const scrub = runPosthog(true).sanitize_properties;
  const props = scrub({
    $current_url: 'https://app.example.test/invite/abc123SECRET?next=/core',
    $referrer: 'https://app.example.test/auth/google/callback?code=4/0Ab&state=xyz',
    $pathname: '/invite/abc123SECRET',
    title: 'People',
  });
  assert.equal(props.$current_url, 'https://app.example.test/invite/[redacted]?next=/core');
  assert.equal(props.$referrer, 'https://app.example.test/auth/google/callback?code=[redacted]&state=[redacted]');
  assert.equal(props.$pathname, '/invite/[redacted]');
  assert.equal(props.title, 'People');
});

test('Faro events never carry an invite token, from the referrer or anywhere else (GL-S04)', () => {
  // Codex on !572: rum.pageview sent document.referrer raw, and beforeSend only scrubbed meta.page.url.
  const events = [];
  let beforeSend = null;
  const window = {
    __RUM_CONFIG__: { enabled: true, grafanaDataEnabled: true, sampleRate: 1, collectorUrl: '/telemetry' },
    location: { origin: 'https://app.test', pathname: '/core/dashboard' },
    localStorage: { getItem: () => null, setItem: () => {} },
    addEventListener: () => {},
    GrafanaFaroWebSdk: {
      getWebInstrumentations: () => [],
      initializeFaro: (config) => {
        beforeSend = config.beforeSend;
        return { api: { pushEvent: (name, attributes) => events.push({ name, attributes }) } };
      },
    },
  };
  const document = {
    body: { addEventListener: () => {} },
    addEventListener: () => {},
    referrer: 'https://app.test/auth/invite/SECRET_INVITE_TOKEN',
    visibilityState: 'visible',
  };
  const math = Object.create(Math);
  math.random = () => 0.5;
  vm.runInNewContext(rumSource, { window, document, Math: math, Number, String, RegExp, Uint8Array, Date, Object, Array, JSON });

  const pageview = events.find((e) => e.name === 'rum.pageview');
  assert.ok(pageview, 'a pageview is sent on load');
  const item = beforeSend({
    meta: { page: { url: 'https://app.test/invite/SECRET_INVITE_TOKEN?token=SECRET2' } },
    payload: { name: 'rum.pageview', attributes: { ...pageview.attributes, from_path: '/invite/SECRET3' } },
  });
  const sent = JSON.stringify([events, item]);
  assert.ok(!/SECRET/.test(sent), sent);
  assert.match(sent, /\/invite\/\[redacted\]/);
});
