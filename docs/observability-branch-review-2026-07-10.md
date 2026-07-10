# Observability branch review — 2026-07-10

## Scope and verdict

Reviewed `main...otel-instrumentation` (13 commits; 63 files). This is a
well-structured, substantial observability rollout: structured application
logs, OpenTelemetry tracing and metrics, core/CRM spans and counters, a local
Grafana/Alloy stack, PostHog/Faro browser instrumentation, supporting docs,
and focused tests.

The backend tracing foundation is coherent, and the configuration defaults are
sensible for local, test, and production environments. At the time of the
review, the branch should **not have been deployed with RUM enabled**: the
telemetry ingress did not function for browser SDKs, and its original proxy
design exposed an SSRF risk.

## Remediation update — 2026-07-10

All code and configuration findings below have now been addressed in this
branch:

- Telemetry now uses CSRF-exempt, rate-limited fixed/allowlisted endpoints;
  absolute URLs and arbitrary upstream paths are rejected.
- Application logs are exported over OTLP with the same resource identity as
  traces and metrics. Loki labels retain only bounded resource fields.
- RUM sampling gates Faro and PostHog initialisation, including PostHog replay;
  console capture is disabled and trace propagation is same-origin only.
- Metrics now share the trace resource. OTLP/HTTP derives the standard
  signal-specific endpoint paths.
- Floating Grafana/PostHog images are locked to resolved digests. The native
  Alloy parser now starts successfully with the configured experimental metric
  conversion processor.
- Ruff is clean, and focused observability tests cover the new ingress and
  shared-resource helpers.

The remaining release gates are operational rather than code changes: start
the complete pinned stack, create the PostHog project/secrets, and complete the
documented browser privacy and end-to-end collector smoke test.

## What is in good shape

- `configure_tracing()` establishes a service resource, W3C propagation,
  parent-based sampling, OTLP export, and Flask instrumentation. Manual spans
  use the same current context, so the core and CRM spans should nest correctly
  under an HTTP request span.
- Logging has a useful common shape: request context, trace/span IDs, JSON in
  production, readable console output locally, and a recursive sensitive-key
  redactor. The explicit event names and business counters are a good base for
  dashboards and alerting.
- Tenant context is registered before the observability request hook, so the
  request log context correctly sees `user_id` and `org_id` for authenticated
  routes.
- The configuration is intentionally disabled in tests, avoiding accidental
  collector traffic. Local and production configuration are explicit rather
  than relying on environment-variable magic.
- The Compose files parse successfully, and the local-PostHog secret file is
  correctly ignored by Git.

## Original findings and remediation record

### 1. Resolved — browser telemetry was rejected by CSRF

`/telemetry` accepts POSTs at
`app/api/app_factory.py:149`, but it is not exempted after `CSRFProtect(app)`
is enabled. Faro and PostHog do not send this application's `X-CSRFToken`.

I exercised a browser-style POST against the Flask test client with the local
RUM configuration. It returned **HTTP 400, “The CSRF token is missing”**, before
the route could forward it. Consequently, the frontend telemetry setup cannot
currently send data.

**Implemented:** fixed Faro and allowlisted PostHog handlers are CSRF-exempt,
rate-limited, and covered by integration tests.

### 2. Resolved — the planned CSRF exemption would have exposed SSRF

The proxy builds its destination with `urljoin()` from an attacker-controlled
path (`app/api/app_factory.py:157-167`). A path such as
`/telemetry/http://metadata.internal/latest` replaces the configured base URL.
With CSRF disabled for the route, I verified that this would direct the
intercepted outbound request to `http://metadata.internal/latest`.

The endpoint is also public, rate-limit exempt, permits all common HTTP
methods, and forwards most request/response headers. That is far broader than
a telemetry receiver needs to be.

**Implemented:** the broad proxy was replaced by a fixed Faro collector route
and allowlisted PostHog paths. The routes permit only required methods, apply a
dedicated rate limit, forward a minimal header set, and do not expose collector
cookies. An integration test rejects an absolute URL path.

### 3. Resolved — application logs were not delivered to Loki by this stack

The app writes structured logs to stdout. It does not configure an OpenTelemetry
logs provider/exporter, while Alloy only accepts OTLP logs at
`observability/grafana-stack/alloy/config.alloy:105-117`; it has no Docker/file
log source for the host-run Flask process. Therefore traces and metrics can
reach Alloy, and Faro logs can reach Loki, but the new Python structured logs
will remain in the process console rather than appearing in Loki.

**Implemented:** the logging configuration adds a batched OTLP log handler,
with exporter diagnostic logs filtered to avoid recursion. A full live
Loki-query smoke test remains an operational release gate.

### 4. Resolved — Loki label cardinality was unsafe

Alloy promotes `trace_id`, `span_id`, `correlation_id`, `request_id`, `org_id`,
and `user_id` to Loki labels at
`observability/grafana-stack/alloy/config.alloy:43-47`. These values are
effectively unbounded and will create a new Loki stream/index entry for many
requests and users. This can cause ingestion limits, poor query performance,
and high storage cost.

**Implemented:** only resource identity fields are labels. Request, user,
organisation, span, and trace identifiers remain JSON fields and Grafana's
derived trace link continues to use the log body.

### 5. Resolved — `rum_sample_rate` did not sample PostHog

`sampledIn` gates only the custom `_capture()` path
(`app/ui/shared/observability-rum.js:26-31, 111-118`). PostHog is initialised
unconditionally with `autocapture: true` and session recording enabled
(`:282-312`). Thus a sample rate of `0` still starts PostHog autocapture and
session replay whenever an API key is configured. That conflicts with the
sampling configuration and makes the privacy posture harder to reason about.

**Implemented:** an unsampled session returns before either SDK, autocapture,
or replay is initialised. The human browser-devtools consent/masking check
remains a release gate.

### 6. Resolved — metrics lacked the service resource

The trace provider receives service name, namespace, and environment, but the
metrics `MeterProvider` is constructed without that `Resource`
(`app/observability/metrics.py:42-46`). Metrics will use the SDK default rather
than reliably identifying as `workflow-engine`, which makes multi-service
Grafana/Mimir queries ambiguous.

**Implemented:** tracing, metrics, and logs share one resource helper, with
unit coverage for the resulting service identity.

### 7. Resolved — frontend trace propagation was overly broad

Faro previously propagated trace headers to `/.*/`. It is now restricted to a
runtime-escaped same-origin regular expression, avoiding third-party propagation
and unnecessary cross-origin preflights.

### 8. Resolved — deployment artifacts were not reproducible

The previously floating Grafana and PostHog images now use resolved digests,
and the local-dev guide records the deliberate-upgrade process. Native Alloy
startup validation found and fixed a Faro map syntax error; it now loads all
components successfully.

### 9. Resolved — lint required auto-fixes

Ruff import, typing, and formatting fixes have been applied across the affected
observability-adjacent modules. `uv run ruff check app/` now passes.

## Validation performed

| Check | Result |
| --- | --- |
| `git diff --check main...HEAD` | Passed |
| Focused observability pytest files | Passed: 10/10 after remediation |
| `uv lock --check` | Passed |
| `docker compose … config -q` for Grafana and PostHog stacks | Passed |
| Ruff check | Passed |
| Native Alloy configuration startup | Passed with the pinned Alloy image |
| Full DB-backed suite / live collector smoke test | Suite start attempted, but its HTTPS tests require the CI Flask server at `localhost:8005`; run `ci/setup_server.sh` first. Complete collector smoke test remains manual. |

The existing tracing test proves Flask's instrumentation can continue an
incoming W3C trace parent, but it does not exercise this application's
`configure_tracing()` wiring or an actual collector export. Add an application
integration test for that path.

## Suggested implementation order

1. Replace the broad telemetry proxy with a constrained receiver and add CSRF,
   SSRF, method, header, and rate-limit tests in the same change.
2. Decide and implement the Python-log ingestion mechanism; remove all
   high-cardinality Loki labels before enabling it.
3. Make PostHog sampling/consent behaviour match `rum_sample_rate`; restrict
   browser trace propagation to same-origin requests.
4. Share one OpenTelemetry resource between tracing and metrics; add exporter
   tests for resource and metric attributes.
5. Pin the Compose images, run `uv run workflow fix-all`, then use the CI
   database/server setup scripts before running the full DB-backed test suite.
6. Start the local Grafana stack, then PostHog with real generated secrets and
   a real project API key. Make a logged-in browser journey and verify: a trace
   in Tempo, metrics in Mimir, one Python application log in Loki, Faro events,
   PostHog events/replay, masked telemetry payloads, and no collector cookies
   or customer values escaping the browser.

## Manual setup still required

- Create the documented KeePassXC entries, generate stable PostHog/Grafana
  values, then use `uv run workflow observability secrets` and `uv run workflow observability start` to launch the combined stack.
- Start and monitor the Grafana and PostHog stack. Store the created project's
  public PostHog API key in KeePassXC; local configuration reads it automatically.
- Set production collector/upstream URLs for the actual deployment network;
  `localhost` is only valid for the documented local setup.
- Update customer-facing privacy/terms text and complete the documented human
  verification of payload masking and session replay before setting
  `rum_enabled=true` in production.
