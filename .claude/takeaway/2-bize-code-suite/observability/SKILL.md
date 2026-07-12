---
name: observability
description: "Instrument the Flask app so agents (and humans) can diagnose production issues from real signals instead of guessing: structured JSON logging, request IDs, consistent error handling, and Sentry wiring, plus a triage procedure for reading those signals back. Use this skill when the user mentions logging, monitoring, Sentry, debugging production, 'why did this fail', or when new-feature calls it to instrument a fresh blueprint. Every improvement here tightens the feedback loop that makes agentic coding work."
---

# Observability

An agent debugging without telemetry is guessing with confidence. The goal of this skill is that when something breaks in a real environment, an agent can go from symptom to file:line using logs alone. Two modes: **instrument** (wire a feature or the app) and **triage** (read the signals when something is broken).

## 1. Instrument mode

### App-level plumbing (once, skip if present)

- **Structured JSON logs** via `structlog` (or stdlib logging with a JSON formatter): one event per line, machine-parseable, because agents grep and parse logs far better than they read prose.
- **Request ID middleware**: accept inbound `X-Request-ID` or generate one, bind it to the logger context, return it in the response header. This is the thread that stitches a user complaint to the exact log lines.
- **Canonical request log line**: one line per request on teardown with method, path, status, duration_ms, request_id, user_id, org_id (IDs only, never emails or names).
- **Error handlers**: a single Flask errorhandler for uncaught exceptions that logs the full traceback with request context and returns a JSON error envelope carrying the request_id, so users can quote an ID instead of describing a screen.
- **Sentry** (if the user has a DSN): `sentry-sdk[flask]`, environment tag, release tag from the git SHA, `traces_sample_rate` low (0.1) to start. If no DSN, note it as a gap; do not fake it.

### Per-feature instrumentation (when called with a slug)

Read `.agents/specs/<slug>.md` and instrument the blueprint:

- Log every state-changing operation at INFO with a stable event name: `logger.info("work_order.created", work_order_id=id, org_id=org_id)`. Event names are `<slug>.<verb_past_tense>`; stable names make dashboards and greps survive refactors.
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
