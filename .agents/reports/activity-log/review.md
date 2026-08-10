# REVIEW: activity-log
date: 2026-08-09
baseline: no dedicated tests existed (`test_finding_history`'s apparent match was a false
positive — substring "history" in its own docstring, confirmed zero real references to
EntityEvent/audit_repo/AuditLog on grep); git status clean at start.
verdict: patched

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| spec | reconstructed | — | `.agents/specs/activity-log.md` |
| security-audit | patched | 3 (1 fix — critical, 1 fix — medium, 1 reported not remediated) | `security-audit.md` |
| e2e-playwright | patched | gap-fill, 12 new tests | `e2e-playwright.md` |
| unit coverage / test-author | patched | 87→90 new unit tests | (folded into security-audit findings + `test-evaluator.md`) |
| test-evaluator | valid | 4 mutation spot-checks, all confirmed falsifiable | `test-evaluator.md` |
| migration-safety | clean (static only) | 0 | `migration-safety.md` |
| perf-guardrails | clean | 0 | `perf-guardrails.md` |
| observability | patched | 1 gap closed (access_denied logging) | `observability.md` |
| ci-gate | patched (scoped) | 2 environmental issues surfaced, out of scope | `ci-gate.md` |

## What this slice does

Reads back the append-only `entity_events` stream (written by the platform-layer
`EventWriter`, out of scope) as human-readable audit history: a per-entity timeline
(`story`), a per-entity computed summary card (`summary`), and an org-wide activity feed
(`activity`). ~450 of 721 lines are diff-humanisation presentation logic
(`_human_summary`, `_event_diff_rows`/`_build_diff_rows`/`_smart_list_diff_rows`,
`_fmt_field_value`) — a real extraction-to-service candidate per the feature index, not
touched here (rule: don't refactor beyond what findings require).

## Findings

### F1 — CONFIRMED, FIXED: cross-tenant BOLA in `entity_summary_detail` (CWE-639)

`GET /api/core/entities/<entity_type>/<entity_id>/summary` (`backend.py:5538`, pre-patch)
queried `EntityEventSummary` filtered only by `entity_id` (that table's primary key,
globally unique across every tenant) — no `org_id` filter, and `entity_id` came straight
from the URL path with zero ownership check anywhere in the route. Any authenticated user
of any org who obtained another org's entity UUID got that entity's full pre-computed
summary back. Because `entity_type` includes `user` and `org` (not just inventory), this
leaked another org's **user email, role, login count, failed-login count, last-login
time**, or **org name/status** — not just inventory data. The route has zero frontend
callers (confirmed by grep) but was live, authenticated, and directly reachable — the same
"dead branch, still a real bug" precedent the traceability review fixed the day before
(`7c32b89`).

**Fix**: added `EntityEventSummary.org_id == org_id` to the filter, matching the sibling
`recent_events` query in the same handler, which was already correctly scoped.
**Regression tests**: `tests/test_activity_log.py::TestAC7CrossTenantSummaryLeak` (4 tests:
inventory/user/org cross-tenant cases + own-org still works) and
`tests/e2e/activity_log/test_tenant_isolation.py::test_ac7_entity_summary_not_visible_cross_tenant`
(real two-browser-session probe). Both verified RED against the pre-patch code via `git
stash` before being trusted. **Semgrep rule**: `bize-entity-event-summary-missing-org-filter`
added to `.semgrep/rules/learned.yml`, verified fires on the bug/silent on the fix.

### F2 — CONFIRMED, FIXED: unhandled `int()` parse on `limit`/`offset`

`entity_story` and `entity_activity_feed` both did bare `int(request.args.get("limit", …))`
with no exception handling — a non-numeric value (`?limit=abc`) raised an unhandled
`ValueError` → uncaught 500 (no global `ValueError`→400 handler registered in
`app_factory.py`). Same bug class the traceability review fixed for `page`/`limit`/`depth`
in the sibling `/api/core/sourcemap/*` routes in this same file the day before.

**Fix**: wrapped both call sites in `try/except (TypeError, ValueError): return
jsonify({"error": "limit and offset must be integers"}), 400`. **Regression tests**: 4 unit
tests + 2 e2e tests, all verified RED pre-patch.

### F3 — reported, not remediated: `AuditLog` table is write-only, never read

`AuditRepository.list_logs_for_org` (the one properly org-scoped reader for the legacy
`audit_logs` table) has zero callers anywhere in `app/`. `audit_logs` rows are still
written on some actions (e.g. `org.settings_updated`, via `log_action()`) but never
surfaced by any endpoint. The feature index's description of `_merge_inventory_legacy_audit`
("blends pre-event-sourcing AuditLog rows") is inaccurate — it actually merges
`InventoryItem.extra_data.inventory_audit_history`, a third, different legacy format,
never `AuditLog` rows. Not a security issue; not remediated because whether to wire
`audit_logs` into a read path or retire the writes is a product decision, out of this
review's scope. Flagged for the user.

## Observability added

`access_denied` structured-log signal on `entity_story`/`entity_summary_detail` when a
lookup resolves to nothing for the caller's org (same pattern/rationale as
`_log_process_access_denied`/`_log_trace_access_denied`), added as defense-in-depth
telemetry specifically because F1 had zero server-side trace before this review. 3
regression tests, including one proving it does *not* fire on ordinary same-org traffic.

## Coverage: before → after

- Dedicated test file: none → `tests/test_activity_log.py` (90 tests) +
  `tests/e2e/activity_log/` (12 tests, 3x flake-checked clean).
- `_human_summary`: 1 of ~28 event-type branches tested → all 28 tested (parametrized).
- `_smart_list_diff_rows`, `_step_added_diff_rows`, `_event_diff_rows` dispatch,
  `_fmt_field_value`/`_fmt_sub_val`: 0 → covered (added/removed/changed list items,
  malformed-entry guards, bool/label/inventory-type formatting branches).
- `_merge_inventory_legacy_audit`: unmatched-entry path only → matched-actor-augment path,
  no-history-key no-op path, and rich-summary-field path all covered.
- Graded by an independent subagent (test-evaluator skill, general-purpose agent, no
  memory of authoring these tests): **valid**. 4 mutation spot-checks (the F1 fix, one
  `_human_summary` branch, `_smart_list_diff_rows`, the F2 fix) all confirmed falsifiable —
  the corresponding tests went red when the source was mutated and green again when
  reverted. One cosmetic test-name fix applied (`test_ac3_...shows_empty_state...` renamed
  — it tested the single-event case, not an actual empty state).

## Two pre-existing environmental issues surfaced (not this slice's to fix)

Full detail in `ci-gate.md`. Both confirmed unrelated to any change in this review:

1. The shared test DB (port 8401, one container used by every concurrent `review/*`
   worktree) has `alembic_version` pointing at `tenant_org_id_notnull_001`, a migration
   that exists in some other worktree's in-flight branch, not this one's — it made
   `steps.org_id` NOT NULL on the live shared DB, breaking any test that creates a `Step`
   row (spans `test_executions.py`, `test_evidence.py`, `test_dag_traversal.py`,
   `test_inventory.py`, `test_traceability.py`, `test_process_design.py`, several `e2e/`
   suites — none of them this slice's).
2. The live dev server preflight found at `https://localhost:8005/` belongs to a different,
   already-merged worktree (`review-process-design`, running unattended since Aug 2) —
   `scripts/preflight.py` can't tell a reachable port from *this* worktree's server, so
   every `pytest.mark.live_server` test in a full-suite run was silently testing stale,
   unrelated code.

This slice's own suite (`tests/test_activity_log.py`, `tests/e2e/activity_log/`) is
unaffected by both — verified by inspection (neither touches `Step` rows or port 8005).

## What's still open

- F3 (AuditLog dead-read-path) — product decision, not actioned.
- `/story` and `/summary` are not in `.agents/perf/budgets.json` — the perf harness has no
  mechanism to measure path-parametrized routes (same gap the traceability review hit and
  left open for its own equivalent routes). `/activity` is measured, clean.
- `scripts/e2e_coverage.py` still reports all three routes as gaps post-fix — confirmed
  pre-existing script limitation (non-recursive glob misses `tests/e2e/<slug>/`
  subdirectories), not specific to this work.
- The two environmental issues above — flagged for the user, not fixed here.
- ~450 lines of diff-humanisation logic remain in the API layer (extraction-to-service
  candidate, feature-index-flagged) — now well-tested in place, not moved (out of scope).

VERDICT: patched
