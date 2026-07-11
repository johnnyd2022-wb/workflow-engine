---
name: observability
description: "Instrument the Flask app so agents (and humans) can diagnose production issues from real signals instead of guessing: structured JSON logging, request IDs, consistent error handling, and Sentry wiring, plus a triage procedure for reading those signals back. Use this skill when the user mentions logging, monitoring, Sentry, debugging production, 'why did this fail', or when new-feature calls it to instrument a fresh blueprint. Every improvement here tightens the feedback loop that makes agentic coding work."
---

# Observability

An agent debugging without telemetry is guessing with confidence. The goal of this skill is that when something breaks in a real environment, an agent can go from symptom to file:line using logs alone. Two modes: **instrument** (wire a feature or the app) and **triage** (read the signals when something is broken).

## 1. Instrument mode

### App-level plumbing — already present in this repo, skip and use it

This repo already has the full stack this section would otherwise build: `structlog`
JSON logging and request-ID binding (`app/observability/middleware.py`,
`logging_config.py`), OpenTelemetry traces/metrics (`tracing.py`), and privacy-masked
browser RUM to Faro/PostHog, all config-driven per environment
(`app/config/*.ini` `[observability]`). No Sentry — don't add it or propose it; the
existing OTel/Grafana LGTM stack is the equivalent and is already wired. Read
`docs/observability-local-dev.md` and run `uv run workflow observability status` before
assuming anything is missing. Local stack lifecycle: `uv run workflow observability
{secrets|start|status|stop}`.

### Per-feature instrumentation (when called with a slug)

Read `.agents/specs/<slug>.md` and instrument the blueprint:

- Log every state-changing operation at INFO with a stable event name: `logger.info("<slug>_<verb_past_tense>", **ids)`, e.g. `logger.info("xero_contacts_sync_started", org_id=str(org_id))` (`app/features/crm/services/xero_sync_service.py:160`) — this repo's convention is `snake_case`, not dotted; stable names make dashboards and greps survive refactors.
- Log every rejected authorization or cross-tenant attempt at WARNING (`<slug>.access_denied`) with the requesting user and target IDs; these lines are the audit trail the security skill's 404s would otherwise hide.
- Wrap external calls (APIs, webhooks from the spec's External surfaces) with duration and outcome logs; external dependencies are where prod pain concentrates.
- **Never log**: passwords, tokens, session cookies, full request bodies, or personal data. IDs over payloads, always. Add a semgrep rule to `.semgrep/` if a risky logging pattern is found (`logger.*(request.json)` and friends).

## 2. Triage mode

When called with a symptom ("500s on /orders since noon"):

1. Get the request_id: from the user's error envelope, Sentry event, or the canonical log line matching the path/status/time window.
2. Pull the thread: filter logs by that request_id to reconstruct the request end to end.
3. Localize from the traceback in the error handler line; correlate with the last deploy (`git log --since`) and any recent migration (`alembic history`).
4. Write findings to `.agents/reports/triage/<date>-<slug>.md` with the evidence chain: symptom, request_ids examined, root cause, fix. Hand the fix to the normal build/review flow; triage diagnoses, it does not hotfix around the gates.

## 3. Report

Instrument mode writes `.agents/reports/<slug>/observability.md`: what was instrumented, event names added, gaps (no Sentry DSN, no log aggregation, etc). Gaps stated honestly are how the user knows what to buy or set up next.

## Rules

- Logging is code: new event lines get asserted in unit tests where they matter (especially `access_denied`).
- Do not add metrics/tracing infrastructure (Prometheus, OTel) unprompted; propose it when the app has traffic that justifies it.
- Noise is a failure mode: a DEBUG firehose in prod buries the signal. INFO for state changes, WARNING for denials and degradation, ERROR for broken invariants.
