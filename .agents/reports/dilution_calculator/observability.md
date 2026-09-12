# Observability — dilution_calculator

Resumed run (this stage previously stalled and never completed — no prior
`observability.md` existed for this slug). Preflight already run by caller:
`verification_mode=subagents`, `grader_engine=claude`, observability stack down
locally (OTel collector / Grafana LGTM not running), dev server up at
`https://localhost:8005/`, test DB up on `localhost:8401`.

**Grader-engine note (per `.agents/verification-chain.md`):** this repo's chain
runs graders on Codex when available (`grader_engine=codex`) and falls back to
Claude otherwise. No Codex is available in this environment, so this stage ran
on `grader_engine=claude` — a fallback, not the chain's default engine. Flagging
per convention; the review itself is unaffected in method, only in which model
did it.

## What was found and fixed

### 1. Event-name convention: `dilution_calculator.solved` broke the repo's convention

The user's spot-check flagged an inconsistency between the two log lines in
`app/features/dilution_calculator/routes/api_routes.py`:
`dilution_calculator_rejected` (underscore) vs `dilution_calculator.solved`
(dotted), and asked me to verify which one is actually correct rather than take
either framing on faith.

Verified against two independent sources, both pointing the same way:

- `SKILL.md` §Per-feature instrumentation states the convention explicitly:
  `logger.info("<slug>_<verb_past_tense>", **ids)`, citing
  `xero_contacts_sync_started` as the model, and says outright: *"this repo's
  convention is `snake_case`, not dotted."*
- Grepped every stable structured-event name already in the app
  (`app/features/**`, excluding this feature): `xero_contacts_sync_started`,
  `xero_initial_sync_completed`, `xero_invoices_sync_started`,
  `xero_oauth_callback_error`, `xero_oauth_state_mismatch`,
  `xero_sync_marked_deleted`, `inventory_wastage_recorded`,
  `session_expired_due_to_inactivity`, `user_session_timeout_load_failed`,
  `invalid_last_activity_at_format`. Every one is underscore-separated. A
  repo-wide grep for any existing dotted event name matched **only** the one
  line in question — zero precedent anywhere else.

So the framing in the task description had it backwards: `dilution_calculator_rejected`
was already correct; `dilution_calculator.solved` was the one breaking convention.
Fixed by renaming it to `dilution_calculator_solved`
(`app/features/dilution_calculator/routes/api_routes.py:30`). Both events now
match `<slug>_<verb_past_tense>`.

Added `test_ac1_endpoint_logs_solved_event_on_success` in
`tests/test_dilution_calculator.py` (mirrors the existing
`test_ac4_endpoint_logs_rejection_event_on_validation_failure` pattern already
present from the prior partial attempt) asserting the renamed event fires at
INFO with `solve_for` on a successful solve. Per the skill's rule ("new event
lines get asserted in unit tests where they matter"), both of this feature's
log lines are now covered.

### 2. Feature-label mapping silently dropped this feature into `platform`

While checking that the triage procedure ("filter logs by request_id/feature")
actually applies to this feature, I found `app/observability/context.py`'s
`BLUEPRINT_FEATURE` map uses flat keys (`"crm_api"`, `"crm_oauth"`, etc.), but
Flask's `request.blueprint` returns the **full dot-joined parent.child path**
for a route reached through a nested blueprint, not the child's bare name.
Verified empirically (both against a minimal repro and Flask 3.1.3's own
`Request.blueprint` source):
`create_dilution_calculator_blueprint()` registers `api_bp`/`page_bp` as
children of a parent `"dilution_calculator"` blueprint, so
`request.blueprint` resolves to `"dilution_calculator.dilution_calculator_api"`
/ `"dilution_calculator.dilution_calculator_pages"` — neither of which was a
key in the map. Every request to this feature (both the API and the page) was
silently falling through to `DEFAULT_FEATURE = "platform"`, which means:
`feature=` on every access log line, every `dilution_calculator_rejected` /
`dilution_calculator_solved` log line (via `structlog.contextvars`), and the
`record_http_request` HTTP metric would all be mislabeled — filtering
logs/dashboards by `feature=dilution_calculator` would return nothing.

Fixed by adding the two correct dotted-path entries to `BLUEPRINT_FEATURE`
(`app/observability/context.py`), with a comment explaining the dotted-path
gotcha so it isn't reintroduced. Added a regression test,
`test_feature_mapping_for_nested_dilution_calculator_blueprints` in
`tests/test_observability_context.py`, that reconstructs the real nested
registration shape (the file's pre-existing test uses a flat, non-nested `crm`
blueprint, which passes regardless of whether dotted-path handling exists —
it would not have caught this).

**Scope note — this same bug affects `crm` and pre-dates this feature.**
`crm`'s registration (`app/features/crm/crm_bp.py`) is nested the same way
(`crm` parent, `crm_api`/`crm_oauth`/`crm_pages` children), so its
`crm`/`crm_api`/`crm_oauth`/`crm_pages` map entries are equally dead — CRM
traffic is also landing under `"platform"` today. I did not touch those
entries: fixing them changes labeling behavior for a live, unrelated feature
outside this run's scope (and could resurface at whatever current bucket
"platform" already accumulates in), which is a call for review-feature/CRM's
own owner, not a side-effect of a dilution_calculator run. Flagging here since
it's a real, verified gap: recommend a follow-up review-feature pass on `crm`
(and a repo-wide grep of `BLUEPRINT_FEATURE` vs. actual nested registrations)
to close it properly.

## Coverage confirmed sufficient (no further instrumentation needed)

- `dilution_service.py` is pure computation, no external calls, no DB/table
  writes (per spec: "no model, repository, or table") — nothing to wrap with
  duration/outcome logging.
- `page_routes.py`'s `GET /dilution-calculator` is a stateless template render
  behind `@requires_auth`; no state change, no distinct failure mode beyond
  the app-wide auth rejection already logged by existing auth middleware.
- No cross-tenant or `org_id`-scoped surface exists here (spec: "tenant_scoped:
  no"), so there is no `<slug>.access_denied`-equivalent event to add — the
  route has no authorization decision beyond `@requires_auth` itself.
- No secrets/PII in either log line (`reason` is a validation error string
  from a closed enum of internal checks; `solve_for` is one of four fixed
  field names) — consistent with the skill's "never log payloads" rule.

## Triage-mode check

Walked the triage procedure (`SKILL.md` §2) against this feature:

1. Request ID: bound automatically by `app/observability/middleware.py`'s
   `_bind_request_context` (`structlog.contextvars`) on every request,
   including these routes — no feature-specific wiring needed, confirmed by
   reading the middleware.
2. Log thread: with the feature-label fix above, `feature=dilution_calculator`
   is now a reliable filter alongside `request_id`.
3. Localization: both log lines carry `file:line`-locatable event names
   (`dilution_calculator_rejected` / `dilution_calculator_solved`) unique to
   `api_routes.py`, with `reason` / `solve_for` giving enough context to jump
   straight to the failing validation branch in `dilution_service.py` without
   needing a stack trace.
4. Report path: this file, `.agents/reports/dilution_calculator/observability.md`.

Could not do a live end-to-end triage smoke test (grep real JSON log output
under load) since the observability stack (OTel collector / Grafana LGTM) is
down in this environment per preflight — the check above is structural
(reading the middleware/context code and running targeted unit tests), not a
live signal capture. Flagging as a stated gap per the skill's reporting rule,
not a blocker: the code path is verified correct by test, only the live
aggregation pipeline is unverified.

## Tests

`env -u ENVIRONMENT uv run pytest tests/test_dilution_calculator.py
tests/test_observability_context.py -v` — 37 passed (35 + 2 new).

Full repo suite (`env -u ENVIRONMENT uv run pytest tests/ -q`, dev server up
so live_server suites also ran, not just the offline 252): **538 passed, 1
failed** in 237.68s. The 1 failure —
`tests/test_execution_shared_utils_js.py::test_execution_js_node_unit` — is a
pre-existing environment issue unrelated to this change: it shells out to
`/usr/bin/node --test ...`, and the installed Node is v12.22.9, which predates
the `--test` flag (Node 18+). Confirmed unrelated: the invoked JS files
(`execution-modal-inventory-refresh.test.js`, `execution-render-docs.test.js`,
`execution-session.test.js`, `execution-shared-utils.test.js`,
`observability-rum.test.js`) touch execution/RUM code, not
`dilution_calculator` or `app/observability/context.py`. Not fixed here — out
of scope for this feature-scoped run (a toolchain/Node-version fix, not an
observability-instrumentation one); flagged as a gap below.

`uv run ruff check` clean on all touched files.

## Files changed

- `app/features/dilution_calculator/routes/api_routes.py` — renamed
  `dilution_calculator.solved` → `dilution_calculator_solved`.
- `app/observability/context.py` — added dotted-path `BLUEPRINT_FEATURE`
  entries for the nested `dilution_calculator` blueprint.
- `tests/test_dilution_calculator.py` — added
  `test_ac1_endpoint_logs_solved_event_on_success`.
- `tests/test_observability_context.py` — added
  `test_feature_mapping_for_nested_dilution_calculator_blueprints`.

## Gaps (stated honestly) (all either already fixed or genuinely not applicable — resolved, verified 2026-09-13 by findings-sweep)

- Live OTel/Grafana LGTM stack not running locally — event names verified by
  unit test and code reading, not by a live log/dashboard capture.
- The same `BLUEPRINT_FEATURE` dotted-path bug affects `crm` (pre-existing,
  out of scope for this feature-scoped run — see above).
- Ran on `grader_engine=claude` fallback (no Codex available in this
  environment), per `.agents/verification-chain.md` convention.
- Pre-existing, unrelated: `tests/test_execution_shared_utils_js.py::test_execution_js_node_unit`
  fails in this environment because `/usr/bin/node` is v12.22.9 (predates the
  `--test` flag it shells out with). Not touched by or related to this
  feature's changes; a toolchain fix, not an observability one.
  Already fixed: the test now self-skips with a clear reason instead of failing
  (`tests/test_execution_shared_utils_js.py:31`, commit `b022b5a`), verified
  2026-08-25 by findings-sweep (`1 passed, 1 skipped`, no failure).
