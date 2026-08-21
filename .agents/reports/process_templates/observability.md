# observability — process_templates

verdict: instrumented

## App-level plumbing

Already present repo-wide (structlog JSON logging, request-ID binding, OTel,
privacy-masked RUM) — nothing to add here. This feature's routes inherit the existing
`app.observability.access` HTTP access log (method/path/status/org_id/user_id) on every
request automatically, same as every other route in the app.

## Per-feature instrumentation added

Two channels, matching this repo's dual convention:

1. **`entity_events` DB records** (`EventWriter`, dotted `<slug>.<verb_past>` —
   already present before this stage, per spec AC11): `process_templates.catalog_viewed`,
   `process_templates.template_selected`, `process_templates.template_copied`.
2. **Structured log lines** (`structlog`, snake_case `<slug>_<verb_past_tense>` per the
   observability skill's stable-event-name convention — added this stage):
   - `process_templates_template_copied` (INFO) — the one state-changing operation
     this feature has, in `process_templates_service.copy_template`. Carries `org_id`,
     `template_id`, `family`, `process_id`.
   - `access_denied` (WARNING) — the generic, repo-wide event name every other
     cross-tenant/tenant-boundary 404 in this app already uses
     (`backend.py`'s `_log_process_access_denied`/`_log_trace_access_denied`), reused
     rather than inventing a `process_templates`-prefixed variant, so one log query
     still covers every access-denial class in the app. Fires in both
     `get_template_detail` and `copy_template` when a **real** catalogue `template_id`
     is requested for a family the caller's org isn't permitted for (the actual
     tenant-boundary-probe case AC3 exists to catch — a genuinely unknown id doesn't
     log, matching the existing pattern of not distinguishing "doesn't exist" from
     "not yours" in the response, only in the log).

Catalogue browsing itself (`list_catalog`) isn't a state change and isn't a denial, so
it gets neither log line — the `entity_events` record is its only trail, matching how
read-heavy list endpoints elsewhere in the app aren't individually log-lined beyond the
access log.

## Tests

`tests/test_process_templates.py::TestObservabilityLogging` (2 new tests, using the
same renderer-independent `_LogRecordCollector` root-logger-handler technique
`test_dilution_calculator.py` established): asserts the `access_denied` line fires with
the right `reason`/`template_id` on a family-mismatched detail fetch, and the
`process_templates_template_copied` line fires with the right `template_id`/`family` on
a successful copy. 29/29 unit tests green after this stage (27 pre-existing + 2 new).

## Gaps

None specific to this feature. No Sentry (repo convention: OTel/Grafana LGTM stack is
the equivalent, already wired, not proposed here). No new metrics/tracing added
(unprompted infra addition is against this skill's own rules).

VERDICT: instrumented
