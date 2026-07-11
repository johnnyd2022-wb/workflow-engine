# Observability Overhaul — Logging, Tracing, Frontend RUM & Ingest Platform

**Status:** Draft — not started
**Priority:** Platform foundation (pre-launch is the right time)
**Owner:** Platform (Johnny)
**Branch:** `otel-instrumentation`

---

## 0. Reading Guide

This plan covers four parts the owner asked for, plus the cross-cutting concerns (privacy, retention, testing, rollout) that make them safe to ship:

| Part | Outcome |
|---|---|
| **Part 1 — Structured Logging** | structlog + JSON everywhere, `feature` tag per blueprint, semgrep enforcement, and a clear **events-vs-logs** split (incl. closing CRM audit gaps) |
| **Part 2 — OpenTelemetry** | Distributed traces + metrics for every key flow, W3C `traceparent` propagation, one tunable sample-rate per environment |
| **Part 3 — Frontend RUM** | Per-session user journey, time-on-page, click/heatmap, **content-masked** so we see behaviour not values |
| **Part 4 — Ingest Platform** | OSS recommendation to receive logs + traces + metrics + RUM, with deployment topology |
| **Part 5 — Cross-cutting** | Privacy/PII governance, retention, testing, phased rollout, dashboards & alerts |

Each section ends with a `[ ]` checklist. Work top-to-bottom: Part 0 scaffolding → Part 1 → Part 2 → Part 3 in parallel with platform stand-up (Part 4).

---

## 0.1 Execution Protocol for Automated Agents

If an automated coding agent is executing this plan, follow this protocol. It exists because parts of this work have a strong automated feedback loop (tests) and parts do **not** (privacy and infra correctness need a human to eyeball them).

**Before writing any code**
- **§13 is locked — there are no platform/tooling decisions to make.** The stack is **Grafana LGTM + Alloy** + **Grafana Faro** + **PostHog**. Do **not** evaluate, suggest, or mention alternatives (no SigNoz, no OpenReplay). The only owner-confirm item (`audit_logs`) has a safe default and blocks nothing.
- Do the dependency-lock spike (§4.3) as the very first commit: add deps, run `uv lock`, confirm `uv lock --check` passes against Flask 2.3.3 / pinned Werkzeug *before* building anything on top.

**While executing**
- **One phase = one PR/branch** (phases in §12). Don't start a phase until the previous phase's *Definition of Done* is green.
- **Run the test suite at the end of every phase** (use the project's pytest command). A phase is done only when tests pass **and** that phase's *Verify* steps succeed.
- Keep telemetry inert in `test` (`otel_enabled=false`, `rum_enabled=false`) — never make the suite depend on a live collector.

**Marker legend**
- **🚦 HUMAN GATE** — stop and prompt the human with the specific question/artifact named; do **not** proceed on a guess.
- **⚠️ HUMAN REVIEW** — write the code, but request review before merging; it's a correctness footgun, not a decision.

**Autonomy map**

| Phase / Part | Mode |
|---|---|
| Phase A–C (Parts 1–2, backend) | **Mostly autonomous** — strong test loop; pause only at the ⚠️ spots below |
| Phase D (Part 4, platform stand-up) | **🚦 Human-gated** — stack is fixed (Grafana + PostHog); the human only confirms "is data actually flowing" |
| Phase E (Part 3, frontend RUM) | **🚦 Human-gated** — the privacy/masking property and replay cannot be self-verified by an agent |

**⚠️ HUMAN REVIEW spots inside the otherwise-autonomous backend work**
1. **Logging context ordering (§5.2)** — the `before_request` context-bind must run *after* `tenant_context` populates `g`, or `feature`/`org_id`/`user_id` come out empty while the logs still *look* valid. Cover with a test asserting the tags are non-empty per blueprint.
2. **Event-emission transaction boundary (§5.4)** — the wrong session choice (`EventWriter` in-transaction vs `emit_event` separate-session) can detach ORM objects and break request flows (see the warning in `app/core/utils/log_action.py`). Get this reviewed and cover it with a full *flow* test, not just a unit test.
3. **Dependency resolution (§4.3)** — if `uv lock` won't resolve OTel against the pinned Flask/Werkzeug, **🚦 stop and surface the options** rather than bumping the core framework unilaterally.

---

## 1. Goals & Success Criteria

The platform owner needs three things, and a place to put them:

1. **See everything that happens** — every user action, every bug/exception, as a queryable record. Split cleanly so the *owner* sees operational detail and *customers* see a clean audit trail without infra noise.
2. **Understand every flow** — distributed traces across the request lifecycle, performance, stability, bottlenecks, with a tunable sampling knob per environment.
3. **See the user journey** — per session: pages visited, dwell time, clicks, friction points, heatmaps — **without** capturing the actual values/content the customer sees (privacy-preserving), to drive retention work.

### Definition of done (acceptance criteria)

- [ ] Every log line in `app/` is structured JSON (in `json` mode) carrying `timestamp`, `level`, `logger`, `event`, `feature`, `correlation_id`, `org_id`, `user_id`, `trace_id`, `span_id`, `request_id`.
- [ ] Every Flask blueprint emits logs tagged with a `feature` value; a semgrep rule fails CI on `print(` / raw `logging.getLogger(` in app code.
- [ ] Every mutating action across **all** blueprints (core, auth, org, **crm**) produces an `entity_event` (customer-visible audit) where it is a business fact — CRM gaps closed.
- [ ] A request to any key flow produces a single distributed trace; outbound Xero calls and DB queries are child spans; an upstream `traceparent` header continues the same trace.
- [ ] `otel_sample_rate` in the env `.ini` changes head sampling with no code change; traces, logs and events for one request share the same `trace_id`/`correlation_id`.
- [ ] Frontend produces a per-session journey (pageviews incl. HTMX swaps, dwell time, clicks, web-vitals) with all text/inputs masked by default; it links to the backend trace.
- [ ] One OSS platform (chosen in Part 4) ingests logs + traces + metrics; product-analytics/replay ingests RUM; an owner can pivot log → trace → session by shared id.
- [ ] Nothing in this stack is sent off to a SaaS we don't control; all data lands in self-hosted OSS.

---

## 2. Current-State Findings (codebase reality)

Verified during planning — the plan builds on these, not against them:

- **App factory:** `app/api/app_factory.py::create_app()` registers blueprints (`auth` `/auth`, `org` `/org`, `core` `/core`+`/api/core`, `crm` sub-blueprints `crm_api`/`crm_oauth`/`crm_pages`, `workflow_engine` feature-flagged). Middleware wired via `setup_tenant_context` / `setup_session_security`; `after_request` sets CSP/HSTS; `ProxyFix(x_for=1, x_proto=1, x_host=1)` trusts 1 Cloudflare hop.
- **Config:** `app/utils/config_loader.py` — `Config` wraps `ConfigParser`, env-selected `app/config/{local,test,prod}.ini`, exposed via typed `@property`s. This is where new `[observability]` keys + properties go.
- **Logging today:** mixed `logging.getLogger(__name__)`, `current_app.logger`, and **raw `print()`** (e.g. `app/app.py` banner, `config_loader.py`, `log_action.py`, `emit_event.py`). ~280 logging call-sites, **no central config** → no JSON, no shared context. Greenfield for structlog.
- **Event sourcing already exists** (`cursor_instructions/event-sourcing-temporal-sourcemap.md`, status Complete): `entity_events` append-only log, `EventWriter` (`app/core/backend/event_writer.py`), `emit_event` helper (`app/core/utils/emit_event.py`), per-entity summaries, and **`g.correlation_id = uuid4()` set per request** in `app/api/middleware/tenant_context.py`. Events cover core/inventory/execution/process/auth. **CRM is NOT covered** — confirmed gap (see §5.3).
- **Legacy audit:** `app/core/utils/log_action.py` + `audit_logs` table — coarse, kept "for backward compat". Two audit systems now coexist; the plan picks `entity_events` as the go-forward audit trail.
- **Request identity in `g`:** `g.correlation_id`, `g.user_id`, `g.org_id`, `g.user_email`, `g.user_role`, `g.org_name` — ready to bind into log/trace context.
- **DB engine:** `app/core/db/__init__.py:37` `engine = create_engine(...)` — the handle for `SQLAlchemyInstrumentor`.
- **Semgrep already in place:** `.semgrep/rules/{js-security,performance,python-multitenant}.yml`; `.gitlab-ci.yml` runs `semgrep --config .semgrep/rules/ app/ --error` in the `security` stage (currently `allow_failure: true`). Add an `observability.yml` rule set here.
- **Frontend:** vanilla JS SPA, **HTMX with `hx-boost="true"`** (navigations are AJAX swaps, *not* full reloads) + Alpine.js. `base_spa.html` has `<meta name="csrf-token">`; `CoreAPI.request()` (`app/core/frontend/js/core-api.js`) is the fetch wrapper. **CSP is strict** (`connect-src 'self'`, `script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com`) — RUM must respect this (self-host SDKs, same-origin collector).
- **CI:** GitLab (`.gitlab-ci.yml`), pre-commit ruff, tests run against a **real** Postgres (port 8401). Deps via `uv` (`pyproject.toml`).

---

## 3. Target Architecture (one picture)

```
                         ┌─────────────────────── Browser (SPA) ───────────────────────┐
                         │  Faro Web SDK (errors, web-vitals, FE traces w/ traceparent) │
                         │  PostHog JS (journey, clicks, replay, heatmaps — MASKED)     │
                         └───────────────┬───────────────────────────┬─────────────────┘
                                         │ (same-origin /telemetry proxy, W3C traceparent)
                                         ▼                           ▼
┌──────────────────────── Flask app ───────────────────────┐   Product analytics /
│  app/observability/                                       │   session replay
│   ├─ logging_config.py  structlog → JSON (stdout)         │   (PostHog,
│   ├─ context.py         bind feature/org/user/trace ctx   │    self-hosted)
│   ├─ tracing.py         OTel TracerProvider + @traced     │
│   ├─ metrics.py         RED + business metrics            │
│   └─ middleware.py      setup_observability(app)          │
│  Auto-instr: Flask, SQLAlchemy(engine), requests(Xero)    │
│  entity_events  ← business audit (customer-visible)       │
└───────┬───────────────────────┬───────────────────────────┘
        │ stdout JSON logs       │ OTLP (traces + metrics)
        ▼                        ▼
┌─────────────────── Grafana Alloy / OTel Collector ───────────────────┐
│  receivers: OTLP, Faro, (filelog/loki push) → processors → exporters  │
└───────┬───────────────┬───────────────┬───────────────────────────────┘
        ▼               ▼               ▼
      Loki            Tempo          Mimir/Prometheus      (+ Pyroscope profiling)
     (logs)         (traces)          (metrics)
        └───────────────┴───────────────┴────────► Grafana (single pane, correlation, alerting)
```

The unifying key is **`trace_id`** (and `correlation_id`, which we align to it): a log line, a span, a business event, and a frontend session all carry it, so the owner can pivot between them in Grafana.

---

## 4. Part 0 — Shared Scaffolding (do first)

### 4.1 New package `app/observability/`

```
app/observability/
  __init__.py          # re-exports: get_logger, setup_observability, traced, configure_*
  logging_config.py    # configure_logging(config) — structlog + stdlib bridge
  context.py           # feature map + request-context binding helpers
  tracing.py           # configure_tracing(app, config), @traced, span helpers, OTel↔log processor
  metrics.py           # configure_metrics(config) + instruments (RED + business)
  middleware.py        # setup_observability(app): wires before/after_request, access log
```

### 4.2 Config: `[observability]` section

Add to **all three** `.ini` files (and `.template`s) and to `config_loader.py` as properties.

```ini
[observability]
# --- Logging ---
log_level   = INFO            ; DEBUG|INFO|WARNING|ERROR
log_format  = json            ; json (prod/test) | console (pretty local dev)

# --- Tracing / Metrics (OpenTelemetry) ---
otel_enabled            = true
otel_service_name       = workflow-engine
otel_sample_rate        = 0.1     ; <<< the single tunable knob; ParentBased head sampling
otel_exporter_endpoint  = http://localhost:4317
otel_exporter_protocol  = grpc    ; grpc | http/protobuf
otel_capture_metrics    = true

# --- Frontend RUM ---
rum_enabled        = true
rum_collector_url  = /telemetry   ; same-origin proxy path (keeps CSP first-party)
rum_sample_rate    = 1.0
rum_mask_inputs    = true         ; mask all text + inputs by default
```

Per-environment overrides:

| key | local | test | prod |
|---|---|---|---|
| `log_format` | `console` | `json` | `json` |
| `log_level` | `DEBUG` | `INFO` | `INFO` |
| `otel_enabled` | `true` | `false` | `true` |
| `otel_sample_rate` | `1.0` | `0.0` | `0.1` (tune) |
| `rum_enabled` | `true` | `false` | `true` |

Add matching `@property` accessors to `Config` (mirror the existing `evidence_*`/`crm_enabled` style): `log_level`, `log_format`, `otel_enabled`, `otel_service_name`, `otel_sample_rate` (float), `otel_exporter_endpoint`, `otel_exporter_protocol`, `otel_capture_metrics`, `rum_enabled`, `rum_collector_url`, `rum_sample_rate` (float), `rum_mask_inputs`. Add a `getfloat` helper to `Config`.

### 4.3 Dependencies (`pyproject.toml`)

```
# logging
structlog>=24.1
# tracing/metrics
opentelemetry-sdk>=1.27
opentelemetry-exporter-otlp>=1.27
opentelemetry-instrumentation-flask>=0.48b0
opentelemetry-instrumentation-sqlalchemy>=0.48b0
opentelemetry-instrumentation-requests>=0.48b0
```
> Pin against Flask 2.3.3 / Werkzeug compatibility; `FlaskInstrumentor` supports Flask 2.x. Run `uv lock` and confirm `uv lock --check` (the CI dependency job) still passes.

### 4.4 Wiring order (critical)

In `create_app()`, configure logging/tracing **before** blueprint registration so early startup logs are structured and the WSGI app is wrapped once:

```
create_app():
    configure_logging(config)          # 1. structlog first — replaces print banner
    app = Flask(...)
    configure_tracing(app, config)     # 2. FlaskInstrumentor.instrument_app(app)
    configure_metrics(config)
    SQLAlchemyInstrumentor().instrument(engine=engine)   # from app.core.db import engine
    RequestsInstrumentor().instrument()
    ... register blueprints ...
    setup_observability(app)           # 3. before/after_request context binding + access log
    ...
    app.wsgi_app = ProxyFix(...)        # keep last
```

> `FlaskInstrumentor` must wrap the app *before* other `before_request` hooks run so the server span is open when our context binding executes (so `trace_id` is available to bind into log context).

### Part 0 checklist
- [x] Create `app/observability/` package skeleton (5 modules + `__init__`).
- [x] Add `[observability]` to `local.ini`, `test.ini`, `prod.ini` and all `.template`s, with per-env values from §4.2.
- [x] Add `getfloat()` + the observability `@property` accessors to `app/utils/config_loader.py`.
- [x] Add deps to `pyproject.toml`; `uv lock`; verify `uv lock --check`.
- [x] Restructure `create_app()` to the wiring order in §4.4 (logging → instrument → blueprints → setup_observability → ProxyFix).

---

## 5. Part 1 — Structured Logging with structlog

### 5.1 Central logging config (`logging_config.py`)

`configure_logging(config)` sets up structlog over the **stdlib logging** root so that *both* our code and third-party libs (Flask, Werkzeug, SQLAlchemy, requests) render through one pipeline.

Processor chain (shared):
1. `structlog.contextvars.merge_contextvars` — pulls request-scoped binds (feature/org/user/trace).
2. `structlog.stdlib.add_log_level`, `add_logger_name`.
3. `structlog.processors.TimeStamper(fmt="iso", utc=True)`.
4. Custom **`add_otel_context`** processor (lives in `tracing.py`) — injects `trace_id`, `span_id` from `opentelemetry.trace.get_current_span()` when a span is recording. This is the logs↔traces join key.
5. `structlog.processors.StackInfoRenderer`, `dict_tracebacks` (structured exceptions — every `logger.exception(...)` becomes a JSON stack).
6. Renderer (env-switched): `JSONRenderer()` when `log_format=json`; `ConsoleRenderer(colors=True)` when `console`.

Use `structlog.stdlib.ProcessorFormatter` as the stdlib `Formatter` so library logs (e.g. `werkzeug`, `sqlalchemy.engine`) get the same JSON shape. Set root level from `log_level`; quiet noisy libs (`werkzeug` access log → WARNING since we emit our own access log; `sqlalchemy.engine` → WARNING unless debugging).

Expose `get_logger(name=None)` → `structlog.get_logger(name)`.

### 5.2 Per-request context + the `feature` tag (`context.py` + `middleware.py`)

`feature` is mandatory on every log line and is derived from the blueprint:

```python
BLUEPRINT_FEATURE = {
    "auth": "auth",
    "org": "org",
    "core": "core",
    "crm": "crm", "crm_api": "crm", "crm_oauth": "crm", "crm_pages": "crm",
    "workflow_engine": "workflow_engine",
}
DEFAULT_FEATURE = "platform"   # app-level routes: index, healthcheck, /dashboard, serve_ui_shared

def feature_for_request() -> str:
    return BLUEPRINT_FEATURE.get(request.blueprint, DEFAULT_FEATURE)
```

`setup_observability(app)` registers:
- **`before_request`** (after tenant_context so `g` is populated): `structlog.contextvars.clear_contextvars()` then `bind_contextvars(feature=..., correlation_id=str(g.correlation_id), request_id=..., org_id=g.org_id, user_id=g.user_id, method=request.method, path=request.path, route=request.endpoint)`. (Do **not** bind raw query strings or bodies — see §9 PII.)
- **`after_request`** — emit one structured **access log**: `logger.info("http_request", status=..., duration_ms=..., bytes=..., feature=...)`. Duration from a `before_request` `time.perf_counter()` stamp on `g`.
- **`teardown_request`** — `clear_contextvars()`.

Because `feature` is bound into contextvars, **every** `logger.*` call within the request inherits it automatically — satisfying "all blueprints have a `feature` tag" without touching every call-site.

### 5.3 Events vs. Logs — the split (owner guidance)

The owner explicitly wants the *platform owner* view rich and the *customer* audit view free of infra noise. Two destinations, one decision rule:

| | **`entity_events`** (event sourcing) | **structlog logs** |
|---|---|---|
| **Question it answers** | "What happened to *this data*?" | "How did the *system* behave?" |
| **Audience** | Customers + owner (audit, compliance, cards/story UI) | Owner only (ops, debugging, security) |
| **Store** | Postgres `entity_events`, tenant-scoped, append-only, long retention | Loki, short/medium retention, sampled at DEBUG |
| **Examples** | invoice authorised, inventory consumed, process v3 created, user role changed, login | request latency, exception+stack, slow query, Xero 429 + retry, rate-limit hit, cache miss |
| **Contains values?** | Yes — business payload snapshot (it *is* the record) | No customer values — IDs + technical metadata only |

**Decision rule (put in code-review checklist):**
> Is it a fact a customer or auditor would want about *their data*, independent of infrastructure? → **`entity_event`**.
> Is it about how the system *performed/failed/behaved*? → **log**.
> Is it a security/compliance signal (login, lockout, permission change, token refresh failure)? → **both**: an `entity_event` for the durable audit trail **and** a log+metric for alerting.

### 5.4 Close the CRM audit gap (events)

The event-sourcing rollout covered core/inventory/execution/process/auth but **not CRM**. Add a CRM event catalog and emit from the mutating endpoints in `app/features/crm/routes/api_routes.py` (and oauth/service layers), reusing `EventWriter` (in-transaction) or `emit_event` (separate session) per the existing pattern.

| event_type | Trigger (endpoint / service) | Key payload |
|---|---|---|
| `crm_invoice.created` | `create_customer_invoice` (POST `/customers/<id>/invoices`) | contact_id, amounts, line items (refs), source_execution refs |
| `crm_invoice.authorised` | `authorise_invoice` (POST `/invoices/<id>/authorise`) | invoice_id, status before/after, xero_invoice_id |
| `crm_invoice.voided` | void/delete path (if present) | invoice_id, reason |
| `crm_note.created/updated/deleted` | notes CRUD (`/customers/<id>/notes`, `/notes/<id>`) | note_id, contact_id, diff (no body text if sensitive) |
| `crm_task.created/updated/deleted` | tasks CRUD (`/tasks`, `/tasks/<id>`) | task_id, status, assignee, diff |
| `crm_traceability_config.updated` | PUT `/traceability-config` | diff before/after |
| `crm_product_mapping.created/updated/deleted` | product-mappings CRUD | mapping_id, product refs, diff |
| `crm_xero.connected` / `crm_xero.disconnected` | oauth connect/disconnect (`oauth_routes.py`) | tenant_id, connected_by |
| `crm_xero.sync_completed` / `crm_xero.sync_failed` | `xero_sync_service` | job_id, counts, error class |

> `crm_xero.token_refreshed` and per-call Xero retries are **operational** → **logs + metrics**, not events (high volume, no customer-audit value). `connected`/`disconnected` and `sync_*` outcomes **are** events.

Decommission decision: `log_action`/`audit_logs` is the legacy coarse audit. Audit whether anything still *reads* `audit_logs`; if not, freeze it and route all new audit through `entity_events`. If a UI/report reads it, keep writing it from a shim but treat `entity_events` as source of truth. (Track as its own task — don't block this plan on the migration.)

### 5.5 Replace `print()` and ad-hoc logging

- `app/app.py` startup banner (`log_feature_status`) → `logger.info("feature_status", sections=..., blueprints=...)` (structured, secrets already masked).
- `config_loader.py` `print(...)` → module logger (note: logging may not be configured yet at import; acceptable to keep a minimal `print` for the very-early KeePass lines, or defer banner to `configure_logging`). Decide per line.
- `log_action.py` `print("Error logging action...")` and `emit_event.py` `logging.getLogger(...).warning(...)` → `get_logger().warning("audit_write_failed", ...)`.
- Sweep `current_app.logger.*` in middleware → `get_logger()` (keeps context binding; `current_app.logger` still works but bypasses our processors’ niceties).

### 5.6 Semgrep enforcement (`.semgrep/rules/observability.yml`)

```yaml
rules:
  - id: no-print-in-app
    languages: [python]
    severity: ERROR
    message: >
      print() is not structured logging. Use `from app.observability import get_logger`
      and emit a structured event (logger.info("event_name", key=value)). print() bypasses
      JSON formatting, the feature tag, and trace correlation.
    pattern: print(...)
    paths:
      include: ["app/"]
      exclude: ["app/cli/**", "scripts/**", "app/core/db/migrations/**", "tests/**"]

  - id: no-stdlib-getlogger
    languages: [python]
    severity: WARNING
    message: >
      Use structlog via `from app.observability import get_logger` instead of
      logging.getLogger(...) so logs carry feature/correlation/trace context.
    pattern: logging.getLogger(...)
    paths:
      include: ["app/"]
      exclude: ["app/observability/**", "scripts/**"]

  - id: prefer-structlog-over-current-app-logger
    languages: [python]
    severity: INFO
    message: Prefer get_logger() over current_app.logger for consistent structured context.
    pattern: current_app.logger.$METHOD(...)
    paths: { include: ["app/"] }
```

Wire into the existing `semgrep` CI job (it already globs `.semgrep/rules/`). Once the codebase is clean, flip the job from `allow_failure: true` → `false` for the `no-print-in-app` severity (or split a blocking sub-job).

> Note: "every blueprint binds `feature`" is enforced *structurally* (the central `before_request` does it for all), not per-call-site, so semgrep doesn't need to police it. The semgrep rules police the *anti-patterns* (`print`, raw getLogger).

### Part 1 checklist
- [x] `logging_config.py`: structlog + stdlib `ProcessorFormatter` bridge; JSON/console switch on `log_format`; quiet werkzeug/sqlalchemy.
- [x] `add_otel_context` processor injecting `trace_id`/`span_id` (lives in `tracing.py`, referenced by chain).
- [x] `context.py`: `BLUEPRINT_FEATURE` map + `feature_for_request()`.
- [x] `middleware.py`: before/after/teardown request — bind feature/correlation/org/user, emit `http_request` access log with `duration_ms`, clear contextvars.
- [x] Replace `print()`/ad-hoc logging in `app.py`, `config_loader.py`, `log_action.py`, `emit_event.py`, middleware.
- [x] CRM event catalog (§5.4): emit `entity_event`s from all CRM mutating endpoints/services.
- [x] Decide `audit_logs` legacy disposition (audit readers, freeze or shim).
- [x] Add `.semgrep/rules/observability.yml`; run `semgrep --config .semgrep/rules/` clean; tighten CI gate.
- [x] Document the events-vs-logs decision rule in `CONTRIBUTING`/code-review checklist.

---

## 6. Part 2 — OpenTelemetry (Traces + Metrics)

### 6.1 Tracer provider (`tracing.py`)

`configure_tracing(app, config)`:
- **Resource:** `service.name=otel_service_name`, `service.version` (from `pyproject`/`app.version`), `deployment.environment=config.environment`, `service.namespace="workflow-engine"`.
- **Sampler:** `ParentBased(root=TraceIdRatioBased(config.otel_sample_rate))`. ParentBased means: if an upstream service already decided to sample (via `traceparent`), we honour it → consistent end-to-end traces; only *root* spans use the ratio. This is the single tunable knob (§4.2).
- **Exporter:** `OTLPSpanExporter(endpoint=otel_exporter_endpoint)` (grpc or http per `otel_exporter_protocol`) wrapped in `BatchSpanProcessor`. When `otel_enabled=false` (test), install **no** exporter (or `ConsoleSpanExporter` behind a debug flag) so tests need no collector.
- **Propagators:** explicitly set `tracecontext` + `baggage` (W3C `traceparent`/`tracestate` is OTel default; set it explicitly so it can't be lost). `ProxyFix` already normalises forwarded headers; FlaskInstrumentor reads `traceparent` from the incoming request.
- **Auto-instrumentation:** `FlaskInstrumentor().instrument_app(app)`, `SQLAlchemyInstrumentor().instrument(engine=engine)` (from `app/core/db`), `RequestsInstrumentor().instrument()` (Xero outbound → child spans **and** outbound `traceparent` injection automatically).

### 6.2 `add_otel_context` log processor

The processor referenced in §5.1: read `get_current_span().get_span_context()`; if valid, add `trace_id` (32-hex) and `span_id` (16-hex). This is what makes "click a log → jump to its trace" work in Grafana (Loki↔Tempo derived field on `trace_id`).

### 6.3 Align `correlation_id` with `trace_id`

`g.correlation_id` already exists (set in `tenant_context`). Recommendation:
- Keep `correlation_id` as the request key, **and** record `trace_id` on every event. In `EventWriter`/`emit_event`, populate `entity_events.request_metadata` with `{"trace_id": ..., "span_id": ..., "correlation_id": ...}` (the column already exists). Result: an auditor on a business event can pivot to the full distributed trace.
- Optionally set `g.correlation_id` *from* the active trace_id at the top of the request so the two are identical (cleaner). Do this only if nothing else depends on the uuid4 shape.

### 6.4 Manual spans for key flows (`@traced` + context manager)

Auto-instrumentation gives the server span + DB + HTTP children. Add **domain** spans with business attributes so traces are navigable by what the business did. Provide a helper:

```python
@traced("execution.complete_step", attributes_fn=lambda **kw: {"execution_id": ..., "step_number": ...})
def complete_step(...): ...
# or:
with start_span("xero.sync", org_id=..., job_id=...): ...
```

Span attributes convention (low-cardinality, **no values**): `org_id`, `process_id`, `execution_id`, `step_number`, `entity_type`, `items_consumed_count`, `items_produced_count`, `add_method`, `result`.

**Key flows to instrument explicitly:**
- [x] Execution lifecycle: `create_execution`, `complete_step` (+ causal event emission), `_advance_execution` (started/completed/failed/cancelled).
- [x] DAG traversal: `DAGTraversal` walk + `TemporalDAGTracer` trace (sourcemap `/api/core/sourcemap/trace`).
- [x] Inventory writes: create / quantity_adjust / update / delete / wastage (the `InventoryQuantityWriteReason`-guarded paths).
- [x] Process versioning: create/update/add_step/update_step/delete_step.
- [x] CSV + barcode inventory upload (`inventory_upload_routes`) — batch size as attribute.
- [x] Auth: login, 2FA verify, signup, account lock/unlock.
- [x] CRM/Xero: `create_customer_invoice`, `authorise_invoice`, `xero_sync_service` job + each `xero_api_client` call (auto via requests instr; add a parent `xero.sync` span).
- [x] Evidence/process-docs upload + storage.

### 6.5 Metrics (`metrics.py`)

`configure_metrics(config)` — `MeterProvider` + `PeriodicExportingMetricReader(OTLPMetricExporter(...))` (gate on `otel_capture_metrics`).
- **RED (auto-ish):** request count + duration histogram + error count, labelled by `feature`, `route`, `status_class`. Emit from the `after_request` access-log hook (we already compute `duration_ms`) to avoid double bookkeeping — one place produces the access log *and* the histogram.
- **Business counters/histograms:** `executions_started`, `steps_completed`, `inventory_writes` (by reason), `invoices_created`, `xero_sync_failures`, `login_failures`, `rate_limit_hits`. Keep labels low-cardinality (no `org_id` on metrics unless tenant dashboards are needed and tenant count is bounded — prefer org on traces/logs, not metric labels).
- **Later (collector-side):** RED can alternatively be derived from spans via the **spanmetrics connector** in Alloy/Collector, reducing app code. Note as an option; start with app-side histogram for control.

### 6.6 Sampling strategy

- **Now:** head sampling via `otel_sample_rate` (ParentBased). local=1.0, prod start at 0.1 and tune.
- **Later:** **tail-based sampling** in the Collector (`tail_sampling` processor) — keep 100% of error/slow traces, downsample the boring ones. This needs the Collector, so it lands in Part 4. Document the policy: always-keep on `status_code=ERROR` or `duration > p95`.

### Part 2 checklist
- [x] `configure_tracing()`: Resource, `ParentBased(TraceIdRatioBased(otel_sample_rate))`, OTLP+Batch exporter, explicit W3C propagators, no-export in test.
- [x] Auto-instrument Flask (app), SQLAlchemy (`engine`), requests (Xero).
- [x] `add_otel_context` processor wired into the structlog chain.
- [x] Record `trace_id`/`span_id`/`correlation_id` into `entity_events.request_metadata` via `EventWriter`/`emit_event`.
- [x] `@traced` / `start_span` helper with low-cardinality, value-free attributes.
- [x] Manual spans on all key flows in §6.4.
- [x] `configure_metrics()`: RED from access-log hook + business counters; gate on `otel_capture_metrics`.
- [x] Verify a request with an injected `traceparent` continues the same trace (test in §8).
- [x] Document head→tail sampling roadmap.

---

## 7. Part 3 — Frontend RUM (journey, dwell, clicks, heatmap — masked)

> **🚦 HUMAN-GATED SECTION — an agent must not mark Part 3 "done" autonomously.** Prompt the human at these points:
> - **The SDKs are fixed** (Grafana Faro + PostHog, §13) — no tool decision to make; do not introduce alternatives.
> - **After masking is wired, before any merge** — a human must open the running tool, load a real session, and visually confirm in the browser **Network tab + the replay itself** that *no* customer values / card text / input contents are captured. An agent cannot verify this property; it must report *"wired up, awaiting human privacy verification,"* never *"done."*
> - **Before changing CSP** — if the same-origin `/telemetry` proxy can't be used and a `connect-src`/`script-src` relaxation is proposed, stop and get explicit sign-off (this widens the app's attack surface).
> - **Before enabling in production** (`rum_enabled=true` in `prod.ini`) — the human confirms the consent/notice posture (§7.3 / §9) is in place.

### 7.1 What we capture (and what we must NOT)

Capture: pageviews (incl. HTMX swaps), route, dwell time, clicks/rage-clicks, scroll, web-vitals (LCP/CLS/INP), JS errors, FE→BE trace link, session id, user/org id (as identifiers only).
**Do NOT capture:** input values, text content of cards/tables, file names with customer data, anything a customer sees. → **mask-all-text + mask-all-inputs by default** (`rum_mask_inputs=true`).

### 7.2 SPA / HTMX specifics (must-handle)

`hx-boost="true"` means navigations are AJAX `#page-content` swaps, **not** full reloads. Naïve RUM records a single pageview for a whole session. Hook HTMX events to register virtual pageviews + reset dwell timers:
- `htmx:pushedIntoHistory` / `htmx:afterSettle` → `capturePageview(location.pathname)`; stamp page-enter time → compute dwell on next navigation.
- Set the SDK to SPA/manual-pageview mode (disable automatic single-pageview).

### 7.3 CSP & first-party delivery (must-handle)

Current CSP: `connect-src 'self'`, `script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com`.
- **Self-host the SDK bundle** in `app/ui/shared/` (served via existing `/ui/shared/<file>` route) so `script-src 'self'` still holds — don't add a CDN.
- **Same-origin collector proxy:** ingest via `rum_collector_url=/telemetry`, a Flask route (or nginx/Cloudflare rule) that reverse-proxies to the Alloy Faro receiver / PostHog. Keeps `connect-src 'self'` intact, survives ad-blockers, and avoids leaking a third-party origin. Update `app_factory.set_security_headers` CSP only if a proxy is impossible.
- Add the SDK init to `base_spa.html` behind `{% if rum_enabled %}` (inject the flag via the existing `_inject_feature_flags` context processor).

### 7.4 Identity & trace stitching

- Identify the session with `user_id`/`org_id` (identifiers only — never email/PII in the analytics payload; or hash if the tool requires a distinct id).
- Propagate **W3C `traceparent`** from the Faro web-tracing SDK on `fetch`/XHR so a frontend span and the backend trace share a `trace_id` → full-stack trace in Tempo. `CoreAPI.request()` is the central fetch wrapper to hook (it already injects CSRF) — add the SDK's fetch instrumentation there or globally.

### 7.5 Tooling (see Part 4 for the full rationale)

Two complementary layers, **both locked** (§13) — do not evaluate alternatives:
1. **Grafana Faro** (`@grafana/faro-web-sdk` + `@grafana/faro-web-tracing`) → web-vitals, JS errors, and FE traces stitched to the backend, all into the **same Grafana stack**. This is the frontend observability SDK (performance / errors / full-stack tracing).
2. **PostHog (self-hosted)** → session replay, click/heatmaps, funnels, retention, journey — the "friction/retention/heatmap" goal Faro doesn't cover, with aggressive masking (§7.1).

### Part 3 checklist
- [x] Self-host chosen SDK bundle(s) in `app/ui/shared/`; load in `base_spa.html` behind `rum_enabled`.
- [x] Same-origin `/telemetry` proxy → collector/analytics; keep CSP `'self'`.
- [ ] Enable mask-all-text + mask-all-inputs; verify no values leave the browser (network inspection).
- [x] HTMX hooks for virtual pageviews + dwell timing (`htmx:pushedIntoHistory`/`afterSettle`).
- [x] Identify session by `user_id`/`org_id` (no PII); inject flags via context processor.
- [x] W3C `traceparent` propagation in `CoreAPI.request()` (FE↔BE trace stitch).
- [ ] Web-vitals + JS error capture verified; confirm a session replay shows masked content.
- [x] Document consent/notice posture (NZ Privacy Act / customer agreement).

---

## 8. Part 4 — OSS Ingest Platform (DECIDED: Grafana LGTM + Alloy + PostHog)

The owner has run Zabbix→PRTG→SolarWinds→Datadog and wants the OSS equivalent of "all of it." **This is decided — do not re-evaluate.** Backend telemetry (logs + traces + metrics) lands in **Grafana LGTM + Alloy**; product analytics + session replay is **PostHog** (self-hosted). The rest of this section is the build spec for that fixed stack — there are no alternatives to weigh.

> **🚦 HUMAN-GATED SECTION — this is infrastructure + decisions, not just code.** Prompt the human at these points:
> - **The stack is fixed** (§13) — Grafana LGTM + Alloy (logs/traces/metrics) + PostHog (replay/analytics). Do **not** evaluate or introduce alternatives (no SigNoz, no OpenReplay); build the Grafana stack as specified.
> - **After writing `docker-compose.observability.yml` + collector/datasource config, before declaring success** — a human runs the stack, generates traffic, and confirms a real request appears as a **log in Loki, a trace in Tempo, and a metric**, all pivotable by `trace_id`. "Config written" ≠ "data flowing": the agent reports the former and hands off; the human confirms the latter.
> - **Secrets** (collector auth, object-storage keys, Grafana admin) — never hard-code; prompt the human for how secrets are supplied (env / KeePass, per the existing pattern in `config_loader.py`).
> - **Retention & storage sizing** — propose the §9.2 values but get human confirmation before applying; this is the dial that drives the disk bill.

### 8.1 The platform — **Grafana LGTM + Alloy**

| Datadog component | OSS replacement | Role |
|---|---|---|
| Log Management | **Loki** | structlog JSON logs |
| APM / Traces | **Tempo** | OTLP distributed traces |
| Metrics | **Mimir** (or Prometheus) | OTLP/Prom metrics |
| Continuous Profiler | **Pyroscope** (optional) | CPU/alloc profiling — bottlenecks |
| Dashboards / Explore | **Grafana** | single pane, logs↔traces↔metrics correlation |
| Agent / DSM pipeline | **Grafana Alloy** | one collector: OTLP + **Faro receiver** + routing |
| Monitors / Alerting | **Grafana Alerting** (+ OnCall) | alert rules, routing |

Why this fits *here*: the app already speaks OTLP (Part 2) and ships JSON logs (Part 1); Faro (Part 3) lands in the **same** Alloy pipeline. Grafana's derived-field correlation lets the owner pivot `log → trace → profile` by `trace_id` — the Datadog muscle-memory transfers directly. Cost: you assemble ~4 services (Loki/Tempo/Mimir/Grafana + Alloy). Given the owner's Datadog rollout experience, assembly is not a blocker.

### 8.2 Second plane — **PostHog** (session replay / heatmaps / analytics)

The Grafana stack does **not** do session replay or heatmaps, so **PostHog (self-hosted)** is the second plane: session replay + heatmaps + funnels + retention + product analytics, with aggressive masking (§7.1). It directly serves the *friction / retention / heatmap* goals. Run it self-hosted alongside Grafana; ship its events through the same-origin `/telemetry` proxy (§7.3).

### 8.3 Alternatives considered — REJECTED, do not implement

**SigNoz** (single-binary OTLP APM) and **OpenReplay** (lean session replay) were evaluated and **rejected** in favour of Grafana + PostHog — unified correlation, profiling, and deeper product analytics. Recorded here only so the decision is not re-litigated: **do not build them, and do not point any exporter at them.**

### Part 4 checklist
- [ ] Stand up the **Grafana LGTM + Alloy** stack (Loki, Tempo, Mimir, Grafana, Alloy) — fixed; no alternatives.
- [x] `docker-compose.observability-grafana.yml` + `docker-compose.observability-posthog.yml`: split stacks on the shared dev network (per implementation constraint), with collector (Alloy), backend storage, and Grafana plane.
- [ ] Point `otel_exporter_endpoint` at the collector per env; verify traces/metrics/logs arrive.
- [x] Alloy: OTLP receiver + Faro receiver + (Loki push / filelog) → Loki/Tempo/Mimir.
- [x] Grafana: datasources + Loki↔Tempo `trace_id` derived field; starter dashboards (§10).
- [x] Tail-sampling policy in the collector (keep errors + slow traces).
- [ ] Retention + storage sizing per backend (§9.2).
- [ ] Stand up **PostHog** (self-hosted); same-origin `/telemetry` proxy target set.

---

## 9. Part 5a — Privacy, PII & Retention Governance

Multi-tenant manufacturing data + NZ Privacy Act / customer agreements → treat telemetry as potentially sensitive.

### 9.1 PII rules (enforce in review)
- [ ] **Logs:** never log request bodies, query strings with values, emails (beyond `user_id`), passwords/tokens/2FA secrets, inventory item *names/values*, customer names. IDs + technical metadata only. (config_loader already masks secrets in the banner — keep that discipline.)
- [ ] **Traces:** span attributes are IDs/counts/enums only — no free-text values.
- [ ] **Events:** `entity_events` *do* hold business values (by design) but are tenant-scoped in Postgres and **not** shipped to Loki/Tempo. Keep that boundary.
- [ ] **RUM:** mask-all on; verify in the network tab that no text/input content leaves the browser.
- [x] Add a small **redaction processor** to the structlog chain as a backstop (drop/----- known sensitive keys: `password`, `token`, `secret`, `authorization`, `cookie`, `email` → hashed/omitted).

### 9.2 Retention (tune to storage/compliance)
| Signal | Suggested retention | Notes |
|---|---|---|
| Logs (Loki) | 14–30 days | longer for security logs via a separate stream/label |
| Traces (Tempo) | 7–14 days | tail-sampled; errors kept longer |
| Metrics (Mimir) | 13 months | cheap, enables YoY |
| `entity_events` | indefinite / per data-policy | it's the audit system of record |
| Session replay | 30 days | masked; shortest practical for analytics value |

### Checklist
- [x] structlog redaction backstop processor.
- [x] Documented PII boundary (events-in-PG vs telemetry-shipped).
- [ ] Retention configured per backend; security-log stream separated.
- [x] Consent/notice copy for RUM in customer terms.

---

## 10. Part 5b — Dashboards, Alerts & Runbook

### Dashboards (Grafana)
- [ ] **Platform overview:** RED per `feature` (req rate, error %, p50/p95/p99 latency).
- [ ] **Per-feature drilldown:** core / crm / auth / org panels.
- [ ] **Execution health:** executions started/completed/failed, complete_step latency, DAG traversal time.
- [ ] **Xero integration:** sync success/failure, API latency, 429/retry rate, token-refresh failures.
- [ ] **Errors & exceptions:** top exceptions by `feature` (from logs), linked to traces.
- [ ] **DB:** slow queries, N+1 hotspots (cross-ref the existing performance semgrep rule), pool saturation.
- [ ] **RUM:** web-vitals by route, top friction pages, funnel/retention (PostHog), heatmaps.

### Alerts
- [ ] Error rate > X% per feature (5m).
- [ ] p95 latency regression per key route.
- [ ] Xero sync failure spike / auth-token refresh failures.
- [ ] `login_failures` / `rate_limit_hits` spike (security).
- [ ] Healthcheck `/healthcheck` down / DB disconnected.
- [ ] Collector pipeline drops / exporter failures (watch the watcher).

### Runbook
- [ ] "How to trace one request end-to-end" (find `trace_id` in a log → Tempo → spans → FE Faro span).
- [ ] "How to audit one entity" (`entity_events` story API → `request_metadata.trace_id` → Tempo).
- [ ] "How to watch a user session" (PostHog session → masked replay → linked backend traces).

---

## 11. Testing Strategy

Tests run against real Postgres; keep telemetry inert in `test` (`otel_enabled=false`, `rum_enabled=false`, in-memory span exporter where needed).

- [x] **Logging:** unit test that `configure_logging` produces JSON with required keys; that `feature` is bound for a request to each blueprint (parametrize auth/org/core/crm); that secrets are redacted.
- [x] **Context:** request to `/api/core/...` logs `feature=core`; `/crm/...` logs `feature=crm`; app route logs `feature=platform`.
- [ ] **Tracing:** with `InMemorySpanExporter`, assert a request produces a server span + DB child span; assert an injected `traceparent` continues the same `trace_id` (distributed propagation); assert Xero call (mocked) is a child span.
- [ ] **Events:** each new CRM mutating endpoint writes the expected `entity_event` (extend existing event tests); `request_metadata.trace_id` populated.
- [ ] **Metrics:** business counters increment on the relevant flow.
- [ ] **Semgrep:** `no-print-in-app` fails on a fixture with `print(`; passes on clean code; whole `app/` is clean.
- [ ] **No-regression:** full suite green with observability wired (it must not change request behaviour).
- [ ] **Frontend (node --test, per existing JS test harness):** masking config asserted; HTMX virtual-pageview hook fires on swap.

---

## 12. Phased Rollout

Each phase is one PR, independently shippable, gated behind config flags (`otel_enabled`, `rum_enabled`). Don't start a phase until the prior phase's **DoD** is green. **Mode** tells an automated agent how much to do alone (see §0.1).

### Phase A — Foundations (Part 0 + Part 1 logging core) · *Mode: autonomous*
Package skeleton, `[observability]` config + properties, deps + lock, central structlog, feature tags, access log, replace prints.
- **DoD:** every `app/` log line is JSON carrying `feature`/`correlation_id`/`org_id`/`user_id`; no `print(` in app code; suite green.
- **Verify:** run the suite; hit a `core`, a `crm`, and an app-level route and assert the logged `feature` ∈ {`core`,`crm`,`platform`}; `semgrep --config .semgrep/rules/observability.yml app/` clean; `uv lock --check`.
- **Prereq:** §13 is locked — apply those decisions directly. No blocking human gate remains for Phase A; the one owner-confirm item (`audit_logs`) has a safe non-blocking default.

### Phase B — Events completeness · *Mode: autonomous · ⚠️ review event txn boundaries (§5.4)*
CRM event catalog emitted, events-vs-logs rule documented, `audit_logs` frozen (non-destructive, per §13), semgrep gate tightened.
- **DoD:** every CRM mutating endpoint writes the expected `entity_event`; `request_metadata` carries identifiers; suite green incl. new event tests.
- **Verify:** extend event tests to each CRM endpoint; run a full execution flow test to prove **no request-flow regression** from the new emissions.

### Phase C — Tracing & metrics (Part 2) · *Mode: autonomous*
OTel provider + ParentBased sampler, auto-instrument Flask/SQLAlchemy/requests, manual spans on key flows, log↔trace join, metrics.
- **DoD:** a request yields one trace with DB + Xero child spans; an injected `traceparent` continues the same `trace_id`; logs carry `trace_id`; changing `otel_sample_rate` changes sampling with no code change.
- **Verify:** `InMemorySpanExporter` tests (server + child spans, propagation, mocked Xero child span); metric-increment tests.

### Phase D — Platform stand-up (Part 4) · *Mode: 🚦 human-gated*
Collector + chosen backend(s) + Grafana, exporters pointed, dashboards/alerts.
- **DoD (human-confirmed):** a real request shows up as a log in Loki, a trace in Tempo, and a metric — pivotable by `trace_id`.
- **Verify:** human runs `docker-compose.observability.yml`, generates traffic, confirms the three planes correlate. The agent stops at "config written" and prompts the human (§8 gate).

### Phase E — Frontend RUM (Part 3) · *Mode: 🚦 human-gated*
Self-hosted SDK(s), same-origin proxy, masking, HTMX virtual pageviews, trace stitch, replay/heatmap.
- **DoD (human-confirmed):** a session shows journey + dwell + clicks + masked replay; FE and BE share a `trace_id`; **no customer values leave the browser.**
- **Verify:** human inspects the browser Network tab + a recorded session for leaked content. The agent reports "wired, awaiting human privacy verification" (§7 gate).

### Phase F — Hardening · *Mode: autonomous + human sign-off*
Tail-sampling policy, retention config, structlog redaction backstop, runbook, alert tuning, flip `no-print-in-app` semgrep to blocking.
- **DoD:** errors/slow traces always retained; retention applied per §9.2 (human-confirmed sizing); semgrep gate blocking; runbook merged.
- **Verify:** induce an error and confirm its trace is retained; confirm CI fails on a `print(` fixture.

Each phase is independently shippable and reversible (flags default safe), so partial rollout is fine.

---

## 13. Decisions (RESOLVED — locked; do not re-open without the owner)

> Locked so an automated agent has **zero** platform or tooling choices to make. Apply these as written; do **not** evaluate or introduce alternatives.

- [x] **Telemetry platform:** **Grafana LGTM + Alloy** (Loki / Tempo / Mimir / Pyroscope / Grafana / Alloy). SigNoz rejected. — §8
- [x] **Frontend observability SDK:** **Grafana Faro**. — §7.5
- [x] **Session replay + product analytics:** **PostHog** (self-hosted). OpenReplay rejected. — §8.2
- [x] **`correlation_id`:** keep the per-request `uuid4` **and** record `trace_id`/`span_id` in `entity_events.request_metadata`. — §6.3
- [x] **Collector delivery:** same-origin `/telemetry` Flask proxy. — §7.3
- [x] **Metrics RED:** app-side histogram from the access-log hook now; collector spanmetrics later. — §6.5
- [x] **`audit_logs` legacy** *(owner-confirm; not blocking)* — default = **freeze, non-destructive**: `entity_events` is the audit system of record, stop adding new `log_action` calls, and leave the existing `audit_logs` table + current writers untouched (don't remove). Owner may later opt to fully migrate. Safe to proceed on this default.
