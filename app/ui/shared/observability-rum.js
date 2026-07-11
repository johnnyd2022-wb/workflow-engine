/* Frontend RUM bootstrap for self-hosted Faro + PostHog (same-origin /telemetry). */
(function (window, document) {
  'use strict';

  if (!window || !document) {
    return;
  }

  var config = window.__RUM_CONFIG__ || {};
  var enabled = Boolean(config.enabled);
  var noop = function () {};
  var api = {
    capture: noop,
    flushDwell: noop,
    getTraceHeaders: function () {
      return {};
    },
    onVirtualNavigation: noop,
  };
  window.ObservabilityRUM = api;

  if (!enabled) {
    return;
  }

  var sampleRate = Number(config.sampleRate);
  if (!Number.isFinite(sampleRate)) {
    sampleRate = 1.0;
  }
  sampleRate = Math.max(0, Math.min(1, sampleRate));
  var sampledIn = Math.random() <= sampleRate;

  // Sampling is a privacy and cost boundary, not only a filter for the custom
  // events below. Do not initialise either vendor SDK when this session is out.
  if (!sampledIn) {
    return;
  }

  var collectorUrl = String(config.collectorUrl || '/telemetry').replace(/\/+$/, '');
  var posthogHost = collectorUrl + '/posthog';
  var userId = config.userId ? String(config.userId) : null;
  var orgId = config.orgId ? String(config.orgId) : null;
  var maskInputs = config.maskInputs !== false;
  var sessionId = _resolveSessionId();
  var pagePath = _normalizePath(window.location.pathname);
  var pageEnteredAt = Date.now();
  var lastPageviewPath = '';
  var lcpValue = 0;
  var clsValue = 0;
  var faro = null;
  var posthog = null;

  function _normalizePath(pathname) {
    var value = String(pathname || '/').trim();
    if (!value) {
      return '/';
    }
    if (value.length > 1 && value.charAt(value.length - 1) === '/') {
      return value.slice(0, -1);
    }
    return value;
  }

  function _resolveSessionId() {
    var key = 'rum-session-id';
    try {
      var existing = window.localStorage && window.localStorage.getItem(key);
      if (existing) {
        return existing;
      }
      var created = _randomId(32);
      if (window.localStorage) {
        window.localStorage.setItem(key, created);
      }
      return created;
    } catch (_err) {
      return _randomId(32);
    }
  }

  function _randomId(length) {
    var chars = 'abcdef0123456789';
    var out = '';
    if (window.crypto && window.crypto.getRandomValues) {
      var bytes = new Uint8Array(length);
      window.crypto.getRandomValues(bytes);
      for (var i = 0; i < length; i += 1) {
        out += chars.charAt(bytes[i] % chars.length);
      }
      return out;
    }
    for (var j = 0; j < length; j += 1) {
      out += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return out;
  }

  function _buildTraceparent() {
    var traceId = _randomId(32);
    var spanId = _randomId(16);
    return '00-' + traceId + '-' + spanId + '-01';
  }

  function _baseAttributes(extra) {
    var attrs = {
      session_id: sessionId,
      user_id: userId,
      org_id: orgId,
      path: pagePath,
    };
    if (!extra || typeof extra !== 'object') {
      return attrs;
    }
    for (var k in extra) {
      if (Object.prototype.hasOwnProperty.call(extra, k)) {
        attrs[k] = extra[k];
      }
    }
    return attrs;
  }

  function _captureToFaro(name, attributes) {
    try {
      if (faro && faro.api && typeof faro.api.pushEvent === 'function') {
        faro.api.pushEvent(name, attributes, 'frontend');
      }
    } catch (_err) {}
  }

  function _captureToPosthog(name, attributes) {
    try {
      if (posthog && typeof posthog.capture === 'function') {
        posthog.capture(name, attributes);
      }
    } catch (_err) {}
  }

  function _capture(name, attributes) {
    if (!sampledIn) {
      return;
    }
    var payload = _baseAttributes(attributes);
    _captureToFaro(name, payload);
    _captureToPosthog(name, payload);
  }

  function _capturePageview(attributes) {
    if (!sampledIn) {
      return;
    }
    var payload = _baseAttributes(attributes);
    _captureToFaro('rum.pageview', payload);
    _captureToPosthog('$pageview', Object.assign({}, payload, {
      $current_url: window.location.href,
    }));
  }

  function _capturePageleave(attributes) {
    if (!sampledIn) {
      return;
    }
    var payload = _baseAttributes(attributes);
    _captureToFaro('rum.dwell', payload);
    _captureToPosthog('$pageleave', Object.assign({}, payload, {
      $current_url: window.location.href,
    }));
  }

  function _flushDwell(nextPath, reason) {
    var now = Date.now();
    var dwellMs = Math.max(0, now - pageEnteredAt);
    _capturePageleave({
      from_path: pagePath,
      to_path: _normalizePath(nextPath || pagePath),
      dwell_ms: dwellMs,
      reason: reason || 'navigation',
    });
    pageEnteredAt = now;
  }

  function _trackPageview(nextPath, reason, force) {
    var normalized = _normalizePath(nextPath || window.location.pathname);
    if (!force && normalized === lastPageviewPath) {
      return;
    }
    if (normalized !== pagePath) {
      _flushDwell(normalized, reason || 'navigation');
      pagePath = normalized;
    }
    lastPageviewPath = normalized;
    _capturePageview({
      page_path: normalized,
      reason: reason || 'navigation',
      referrer: document.referrer || null,
    });
  }

  function _captureClick(event) {
    if (!event || !event.target) {
      return;
    }
    var el = event.target;
    var elementId = el.id ? String(el.id).slice(0, 120) : null;
    var className = el.className ? String(el.className).slice(0, 200) : null;
    _capture('rum.click', {
      tag_name: String((el.tagName || '').toLowerCase()),
      element_id: elementId,
      class_name: className,
    });
  }

  function _initWebVitals() {
    if (!window.PerformanceObserver) {
      return;
    }
    try {
      var lcpObserver = new PerformanceObserver(function (entryList) {
        var entries = entryList.getEntries();
        if (!entries || !entries.length) {
          return;
        }
        lcpValue = Math.max(lcpValue, entries[entries.length - 1].startTime || 0);
      });
      lcpObserver.observe({ type: 'largest-contentful-paint', buffered: true });
    } catch (_err) {}
    try {
      var clsObserver = new PerformanceObserver(function (entryList) {
        var entries = entryList.getEntries();
        for (var i = 0; i < entries.length; i += 1) {
          if (!entries[i].hadRecentInput) {
            clsValue += entries[i].value || 0;
          }
        }
      });
      clsObserver.observe({ type: 'layout-shift', buffered: true });
    } catch (_err) {}
    try {
      var fidObserver = new PerformanceObserver(function (entryList) {
        var entries = entryList.getEntries();
        if (!entries || !entries.length) {
          return;
        }
        var first = entries[0];
        var fidMs = (first.processingStart || 0) - (first.startTime || 0);
        _capture('rum.web_vital', {
          metric_name: 'FID',
          metric_value: Math.max(0, fidMs),
        });
      });
      fidObserver.observe({ type: 'first-input', buffered: true });
    } catch (_err) {}
  }

  function _emitVitalsSnapshot(reason) {
    _capture('rum.web_vital', { metric_name: 'LCP', metric_value: lcpValue || 0, reason: reason || 'snapshot' });
    _capture('rum.web_vital', { metric_name: 'CLS', metric_value: Number(clsValue.toFixed(4)), reason: reason || 'snapshot' });
  }

  function _initErrorHooks() {
    window.addEventListener('error', function (event) {
      _capture('rum.js_error', {
        message: String((event && event.message) || 'Unknown JS error'),
        source: event && event.filename ? String(event.filename).slice(0, 300) : null,
        line: event && typeof event.lineno === 'number' ? event.lineno : null,
        column: event && typeof event.colno === 'number' ? event.colno : null,
      });
    });
    window.addEventListener('unhandledrejection', function (event) {
      var reason = event && event.reason ? String(event.reason) : 'Unhandled rejection';
      _capture('rum.unhandled_rejection', {
        message: reason.slice(0, 500),
      });
    });
  }

  function _initFaro() {
    if (!window.GrafanaFaroWebSdk || typeof window.GrafanaFaroWebSdk.initializeFaro !== 'function') {
      return;
    }
    try {
      var instrumentations = [];
      if (typeof window.GrafanaFaroWebSdk.getWebInstrumentations === 'function') {
        instrumentations = window.GrafanaFaroWebSdk.getWebInstrumentations({
          // Explicit error hooks below provide actionable errors without
          // exporting arbitrary application console arguments.
          captureConsole: false,
        }) || [];
      }
      if (window.GrafanaFaroWebTracing && typeof window.GrafanaFaroWebTracing.TracingInstrumentation === 'function') {
        var escapedOrigin = String(window.location.origin || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        instrumentations.push(
          new window.GrafanaFaroWebTracing.TracingInstrumentation({
            propagateTraceHeaderCorsUrls: escapedOrigin ? [new RegExp('^' + escapedOrigin + '/')] : [],
          })
        );
      }
      faro = window.GrafanaFaroWebSdk.initializeFaro({
        url: collectorUrl,
        app: {
          name: 'workflow-engine-frontend',
          version: 'local',
          environment: 'browser',
        },
        instrumentations: instrumentations,
        sessionTracking: {
          enabled: true,
          // The outer sampledIn check is the single session-level sampler.
          samplingRate: 1.0,
        },
      });
    } catch (_err) {}
  }

  function _initPosthog() {
    var projectApiKey = String(config.posthogApiKey || '').trim();
    if (!projectApiKey) {
      return;
    }
    if (!window.posthog || typeof window.posthog.init !== 'function') {
      return;
    }
    try {
      window.posthog.init(projectApiKey, {
        api_host: posthogHost,
        capture_pageview: false,
        capture_pageleave: false,
        autocapture: true,
        // This deployment does not use PostHog feature flags. Disabling their
        // optional remote-configuration loader avoids requests for the
        // unneeded /array/<token>/config SDK dependency.
        advanced_disable_flags: true,
        disable_session_recording: false,
        mask_all_text: maskInputs,
        mask_all_element_attributes: true,
        session_recording: {
          maskAllInputs: maskInputs,
        },
        loaded: function (instance) {
          posthog = instance;
          if (userId && typeof posthog.identify === 'function') {
            posthog.identify(userId, {
              org_id: orgId,
            });
          }
        },
      });
      posthog = window.posthog;
    } catch (_err) {}
  }

  function _bindHtmxNavigationHooks() {
    var body = document.body;
    if (!body || !body.addEventListener) {
      return;
    }
    body.addEventListener('htmx:pushedIntoHistory', function () {
      _trackPageview(window.location.pathname, 'htmx:pushedIntoHistory', false);
    });
    body.addEventListener('htmx:afterSettle', function (event) {
      var target = event && event.detail && event.detail.target;
      if (!target || target.id !== 'page-content') {
        return;
      }
      _trackPageview(window.location.pathname, 'htmx:afterSettle', false);
    });
  }

  api.capture = _capture;
  api.flushDwell = _flushDwell;
  api.onVirtualNavigation = function (path, reason) {
    _trackPageview(path || window.location.pathname, reason || 'virtual_navigation', false);
  };
  api.getTraceHeaders = function () {
    if (!sampledIn) {
      return {};
    }
    return {
      traceparent: _buildTraceparent(),
    };
  };

  _initFaro();
  _initPosthog();
  _initErrorHooks();
  _initWebVitals();
  _bindHtmxNavigationHooks();
  _trackPageview(window.location.pathname, 'initial_load', true);

  document.addEventListener('click', _captureClick, true);
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') {
      _emitVitalsSnapshot('visibilitychange_hidden');
      _flushDwell(pagePath, 'visibilitychange_hidden');
    }
  });
  window.addEventListener('beforeunload', function () {
    _emitVitalsSnapshot('beforeunload');
    _flushDwell(pagePath, 'beforeunload');
  });
})(window, document);
