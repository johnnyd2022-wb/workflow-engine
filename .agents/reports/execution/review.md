# REVIEW: execution
date: 2026-08-02
branch: review/execution (isolated worktree, cut fresh from origin/main)
baseline: tests green (748 passed, 30 skipped expected live_server), working tree clean
verdict: **patched**

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| security-audit | findings-open → patched | 2 | [security-audit.md](security-audit.md) |
| e2e-playwright | findings-open → patched | 1 app bug + 3 test-authoring issues | [e2e-playwright.md](e2e-playwright.md) |
| test-author | patched | — (coverage gap closed) | [test-author.md](test-author.md) |
| test-evaluator | invalid → fixed | 3 | [test-evaluator.md](test-evaluator.md) |
| perf-guardrails | clean | 0 | [perf-guardrails.md](perf-guardrails.md) |
| observability | patched | 1 | [observability.md](observability.md) |
| ci-gate | patched | 1 | [ci-gate.md](ci-gate.md) |

Execution mode `herdr-tabs`, grader engine `codex`. Two stages (e2e-playwright,
test-evaluator) hit their own usage limits or sandbox boundaries before writing a report
file; both are transcribed onto this branch by the orchestrator per
`.agents/verification-chain.md` §5's rule for exactly this situation — see each report's
own note. No migration-safety stage: this review touched no models or migrations.

Six real defects found and fixed, spanning three different layers of the same feature —
correctness, tenant isolation, and a frontend regression that made three of the other
five invisible to users until this review's own e2e stage forced the question.

## What was wrong, and what now stops it recurring

### F1 — execution_warnings silently dropped from persisted data
`backend.py`, `complete_step` (found reading the highest-risk function per the feature
index, before any chain stage ran): warnings collected during step completion (e.g.
"Skipping output with zero quantity") were mutated into
`execution_step.execution_data` — a plain JSONB column, not `MutableDict`-wrapped —
*after* an earlier `db_session.flush()` had already cleared SQLAlchemy's dirty-tracking
for that attribute. The in-place `dict[key] = value` mutation was invisible to the ORM:
returned correctly in the HTTP response, silently absent from the database row for
every later reader (traceability's `extra_data.execution_trace`, compliance-checks,
dashboard). Fixed by reassigning the dict (`{**old, "execution_warnings": ...}`) instead
of mutating it in place. Regression test:
`tests/test_executions.py::TestRegressionSafeguards::test_execution_warnings_persist_to_db_not_just_response`
(confirmed fails pre-fix via `git stash`).

### F2/F3 — cross-tenant ExecutionStep lookups in dagtraversal.py
Two lookups in the DAG traceability engine queried `ExecutionStep` by ID alone, with no
join back to `Execution.org_id` — unlike every other lookup in the same file (which the
file's own comments document as deliberate defense-in-depth: a `source_execution_step_id`
FK that's corrupted or forged must not pull another org's data across the tenant
boundary).

- `add_step_order_connections` (found in the same initial read as F1): **independently
  exploitable** — confirmed with a constructed regression
  (`TestAddStepOrderConnectionsTenantIsolation`) that fails pre-fix, passes post-fix.
- `find_impacted_by_expired_raw` (found by security-audit): same bug class, but *not*
  independently reachable through this function's actual call path — `traverse()`'s own
  forward-edge discovery already guarantees org-scoped provenance for every item it
  surfaces, confirmed empirically (a corrupted-FK item planted directly at the ORM layer
  was never discovered, pre-fix or post-fix). Fixed anyway for consistency with the
  file's own invariant (AC20 in the reconstructed spec); no cross-tenant regression test
  added since one would pass regardless of the fix (test-evaluator confirmed this
  reasoning holds). Two happy/unhappy-path tests added instead
  (`TestFindImpactedByExpiredRaw`) since the function had zero prior coverage.

### F4 — uploaded_by always None on evidence upload
`evidence_routes.py`: `getattr(g, "user_email", None) or getattr(g, "user", {}).get("email") if hasattr(g, "user") else None`
— the ternary binds looser than `or`, so this reduces to
`(... or ...) if hasattr(g, "user") else None`, and `g.user` is never set anywhere in
this codebase (only `g.user_email` / `g.user_id` / `g.current_user` are, per
`app/api/middleware/tenant_context.py`). Every evidence upload recorded `uploaded_by =
None`, silently losing the audit trail. Fixed by simplifying to
`getattr(g, "user_email", None)`. Regression:
`tests/test_evidence.py::TestEvidenceUploadRecordsUploader`.

### F5 — evidence step_id accepted without ownership check (security-audit F2)
`evidence_service.upload_evidence_from_temp` stored `step_id` (a FK to the global
`steps` table) without checking it belongs to the execution's own process — low
severity today (no read path joins it back to leak cross-org data; a bad `step_id`
previously 500'd as a raw `IntegrityError` rather than leaking anything), but the same
FK shape `InventoryRepository._assert_source_refs_belong_to_org` already guards for
inventory provenance. Fixed by validating against `execution.execution_steps` before
persisting (400, not a DB-level crash). Regression:
`tests/test_evidence.py::TestEvidenceUploadValidatesStepId`.

### F6 — notifications silently degraded on the canonical execute-step page (found by e2e-playwright)
`app/core/frontend/js/execution-modal.js` installs a console-only fallback
`window.showNotification` immediately at parse time if one isn't already defined.
`base_spa.html` defines the real, DOM-updating one too, but *after*
`{% block content %}` — and `batch-start.html` (the canonical `/core/flows/batches/start`
execute-step screen) loads `execution-modal.js` *inside* that content block. Script
execution order meant the console-only fallback always won the race, so **every**
success/warning/error toast for step completion, evidence upload, and validation on the
one page operators actually use was only ever logged to the browser console — invisible
to a real user. This is why 6 of the 7 new Playwright tests (AC4, AC5, AC9/10, AC14 ×2,
AC17) initially failed: the underlying business logic was correct in every case: the
tests were asserting exactly the spec-required behavior. Fixed by deferring
`execution-modal.js`'s fallback installation to `DOMContentLoaded`, so `base_spa.html`'s
synchronously-executed real implementation always gets first claim on the global.
Verified via a throwaway diagnostic script before touching anything; all 7 e2e tests
plus the pre-existing 6 in `test_workflow_flow.py` pass post-fix.

## Also fixed (infrastructure / hardening, not app defects)
- **CI never actually ran Playwright e2e tests**: `unit_tests`'s `before_script` never
  installed Chromium, so `tests/e2e/conftest.py`'s own graceful-skip logic silently
  skipped every e2e test in the blocking `pytest tests/ -v` job — including the
  pre-existing `test_workflow_flow.py`, not just this review's new file. Fixed by adding
  `uv run playwright install --with-deps chromium` to `unit_tests`, matching the
  command already used (for a different, non-blocking job) in `cd_e2e`.
- **`access_denied` structured logging** added to two cross-tenant rejection points that
  had none (`_assert_flow_process_access`, evidence's new `step_id` check), matching the
  event name/shape already used by `permissions.py` and `inventory_repo.py`. Found a
  real `create_app()`/`caplog` interaction trap while writing the regression test for
  this (documented in `observability.md`).
- **Duplicate `id="notification-modal"`** across `base_spa.html`, `flows2-modals.html`,
  `core2.html` — confirmed harmless in practice (`getElementById` always resolves the
  shell's copy) but invalid HTML; flagged as a low-priority cleanup for whichever review
  next touches `flows2.html`/`core2.html` (not this slice's files), not patched here.
- **3 falsifiability defects in test-author's new tests** (test-evaluator, Codex):
  a path-traversal test that never reached the containment guard because the target
  file didn't exist; an idempotency test that used two different random UUIDs instead
  of retrying the same delete; an orphan-cleanup test that checked the wrong directory
  (final storage, not the temp upload path the failure actually leaves behind). All
  three fixed and reverified to fail pre-fix / pass post-fix.
- **`.gitignore`**: `app/core/evidence_storage/` was untracked but not ignored —
  writing tests for the evidence subsystem for the first time immediately produced
  stray org-id-named directories that `git status` would flag on any broad `git add`.

## Coverage added
- `tests/test_evidence.py` (new, 45 tests): the evidence subsystem had a single
  regression test before this review; now covers config/list/download/delete
  happy+unhappy paths, upload validation edge cases, all three post-commit
  failure/orphan-cleanup branches, and pure unit tests for `evidence_storage.py` /
  `evidence_validation.py`. Coverage: `evidence_routes.py` 42%→78%, `evidence_service.py`
  25%→68%, `evidence_storage.py` 62%→87%, `evidence_validation.py` 46%→64%.
- `tests/e2e/test_execution_flow.py` (new, 7 tests): browser-level proof for ACs a
  unit/API test can't fully cover (does the result actually render for the user), plus
  the mandatory cross-tenant probe.
- `tests/test_executions.py` / `tests/test_dag_traversal.py`: 5 new regression/coverage
  tests for the fixes above.
- `.agents/test-map.md` updated (row 27, Evidence: `none → covered`).

## Known coverage gaps (not closed this pass, documented honestly)
- `create_execution`'s dead second `except ValueError` clause (`backend.py:1731-1734`)
  — unreachable today (the repo only raises `ValueError` for "process not found," caught
  by the first clause), so behavior-preserving no-op currently, but would silently
  regress the intended 400 branch if the repo ever raises `ValueError` for a different
  reason. Flagged, not fixed — no observable behavior change to test against today.
- The feature index (`.agents/feature-index.md`) lists `ApiIdempotencyKey` among
  execution's models; it's only used by the wastage-batch route (inventory slice).
  Flagged for **docs-truth**, not corrected here per this skill's own scoping rule.
- Duplicate `notification-modal` id (see above) — process-design/dashboard territory.

## Release gates
None blocking. All fixes are backward-compatible (no API contract changes beyond a new
400 on a previously-500ing/undefined evidence `step_id` misuse, and previously-invisible
notifications now actually appearing — both strictly improvements). Full suite green:
`836 passed` (`uv run pytest tests/ -q`), plus the scoped execution-slice + e2e runs
throughout this review, all confirmed multiple times across the patch cycles above.
