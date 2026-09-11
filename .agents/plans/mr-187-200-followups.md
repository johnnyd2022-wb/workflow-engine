# MR !187–!200 performance-series follow-ups

Source: `.agents/reports/perf/2026-08-29-mr-187-200-review.md` (merged as MR !201, review-only).
All findings re-verified against `main` @ `b98e773` on 2026-08-30. Each ships as its own MR,
adversarially reviewed by Codex (Breaker) in Herdr before push.

**Status: all six shipped and merged to `main`.** Re-verified in tree
`(verified 2026-09-11 by findings-sweep)` — each fix commit below is an ancestor of the
current head and touches the files its section names. This plan is closed; kept for the
audit trail.

| MR | Branch | Finding | Severity | Status |
|----|--------|---------|----------|--------|
| A | `fix/whitenoise-inventory-template-exposure` | P0 — WhiteNoise publishes server templates under `/static/inventory/` | security / info-disclosure | shipped — `a6d21c1`, merged `08e42ff` |
| B | `fix/migration-merge-revision` | P0 — shipped revision `feature_subscriptions_001` re-parented instead of merged | release/migration safety | shipped — `ca64a5e`, merged `d0baca8` |
| C | `fix/changes-feed-commit-safe-cursor` | P1 — `entity_events.seq` cursor is not commit-ordered; events can be skipped | correctness | shipped — `78458dc`, merged `e39b188` |
| D | `fix/if-match-atomic` | P1 — If-Match is read-compare-then-write (TOCTOU), not atomic | correctness / lost-update | shipped — `1a5ad8c`, merged `b0284b4` |
| E | `fix/system-findings-failure-semantics` | P1 — failed live check is dropped; system reports healthier than reality | reliability / compliance | shipped — `f22eae4`, merged `3bcf264` |
| F | `perf/mr-187-200-followups` | P2 — dead ETag path, over-broad expired-materials check, missing completed-exec index | performance | shipped — `2d2b83c` (bundle) |

## Sequencing
0. Verify prod/staging `alembic_version` before B (decides B's real severity).
1. A + E first (small, high-value).
2. C before any further live-sync consumer fan-out.
3. B once step 0 is known.
4. D independent.
5. F last (pure optimisation).

## Per-MR detail

### A — WhiteNoise inventory/img template exposure
- `app/api/app_factory.py:541-542` hands whole `inventory/` and `img/` dirs to `WhiteNoise.add_files`.
- `inventory/` contains server-rendered Jinja (`add.html`, `dispose.html`, `view.html`, …).
  `GET /static/inventory/add.html` → 200 raw template, unauth, before Flask allowlist route.
- Fix: keep only the two public assets (`inventory-icon.svg`, `inventory-spa-header.css`) reachable.
  Move them to a leaf static-only dir and register just that with WhiteNoise, OR drop the
  `inventory/`+`img/` WhiteNoise registration and leave them on the Flask allowlist route.
- Tests: every non-allowlisted inventory/img filename asserts non-200; allowed assets keep
  content-type + `Cache-Control`. Fix stale comments in `tests/test_static_whitenoise.py`.
- **Shipped** in `a6d21c1` (merged `08e42ff`): the two public assets moved to a sibling
  `app/core/frontend/inventory_static/` dir that holds nothing else, and
  `app/api/app_factory.py` now hands *that* dir to `WhiteNoise.add_files` (URL prefix
  `/static/inventory/` unchanged); the server templates stay in `inventory/` and are no
  longer reachable as static files. Covered by
  `tests/test_static_whitenoise.py::test_inventory_templates_not_exposed` and
  `tests/e2e/test_static_asset_security.py`. (verified 2026-09-11 by findings-sweep)

### B — migration merge revision
- `feature_subscriptions_001.down_revision` was changed `system_findings_cache_001` → `entity_events_seq_001`
  (commits `3b0e4d3`/`a28c525`).
- Fix: restore historical parent; add one empty merge revision
  `down_revision = ("entity_events_seq_001", "feature_subscriptions_001")`; re-parent all later revisions onto it.
- Verify: fresh `upgrade→downgrade→upgrade`; upgrade from a DB pinned at each old head and at the
  temp rewritten state. CI `migration_reversibility` green.
- **Shipped** in `ca64a5e` (merged `d0baca8`): `feature_subscriptions_001.down_revision` is
  back to `"system_findings_cache_001"` and new empty merge revision `feat_subs_seq_merge_001`
  has `down_revision = ("entity_events_seq_001", "feature_subscriptions_001")`. `uv run alembic
  heads` shows a single head. (verified 2026-09-11 by findings-sweep)

### C — commit-safe changes-feed cursor
- `app/core/backend/changes_feed.py` cursor = `entity_events.seq` (sequence), mitigated only by a
  1s `created_at` settle window. Long-running txn ⇒ its event permanently skipped.
- Fix: per-org feed counter allocated under an org-row lock in the event's own txn (in `EventWriter.emit`),
  or an outbox that assigns cursors post-commit. Feed switches to the new monotonic-per-org column.
- Test: two-session — hold txn A open, commit B, poll, commit A ⇒ both delivered exactly once.
- **Shipped** in `78458dc` (merged `e39b188`): `EventWriter.emit` allocates a commit-safe
  per-org cursor; `changes_feed.py` reads the new monotonic column. `tests/test_changes_feed.py`
  gained the two-session skip probe (+124 lines). Later refined by `af93915` (drop the settle
  window) and `98ba76e`. (verified 2026-09-11 by findings-sweep)

### D — atomic If-Match
- `update_process` (`backend.py:1574`), step update (`:1743`), `reorder_steps` (`:1828`): read `updated_at`,
  compare in Python, write later. `reorder_steps` compares on request session, writes on a fresh `SessionLocal`.
- Fix: `UPDATE … WHERE id=:id AND updated_at=:expected`; 0 rows ⇒ 409. For reorder: `SELECT … FOR UPDATE`
  the steps inside the write txn, re-check the structural token there, then apply.
- Test: barrier two-client, same initial token ⇒ exactly one 200, one 409.
- **Shipped** in `1a5ad8c` (merged `b0284b4`): `process_repo.py` — `update_process`,
  `update_step` and `reorder_steps` each `SELECT … FOR UPDATE` the row inside the write txn
  and re-compare `updated_at` there before applying, returning `STALE_WRITE` (→ 409) on a
  mismatch, so the check-and-write is one atomic transaction rather than a TOCTOU.
  `tests/test_process_design.py` gained the barrier two-client race test (+131 lines).
  Phase-D editor wiring followed in `8d6482d` / `b83da84`.
  (verified 2026-09-11 by findings-sweep)

### E — system-findings failure semantics
- `system_findings_cache.py::_run_live()` swallows a check exception (`except: continue`); the pre-cache
  `CoreChecksRunner.run_all_checks()` instead appends `CheckResult(flagged=True, "Check failed: …")`.
  Fix: restore runner semantics in both paths — live failure ⇒ append flagged failure result;
  cached compute failure ⇒ return equivalent failure result, not a bare raise.
  Test: one cached + one live failing check; assert finding present and `system_status` severity reflects it.
  Already fixed by `f22eae4` (merged `3bcf264`): `system_findings_cache._run_live()` now appends a
  flagged `"Check failed: …"` result instead of `continue`; `_compute_expensive()` returns
  `(results, ok)` and `_cached_expensive()` / `prewarm()` surface the flagged failure without
  persisting it; `system_status._signals_from_results()` emits a `CHECK_FAILED` signal so the
  state drops to `degraded`, never `healthy`. Four new tests in
  `tests/test_system_findings_cache.py`, each mutation-checked. (verified 2026-09-11 by findings-sweep)

### F — perf follow-ups (bundle)
- `live-sync.js:49` never sends `If-None-Match` ⇒ server 304 path dead ⇒ 2 queries/tab/3s.
  Fix: persist response ETag, send on next request for same cursor.
  Already fixed by commit `2d2b83c` (F bundle, merged `fc78bd9`): `app/core/frontend/js/live-sync.js`
  now stores `lastEtag` from the response `ETag` header (`:36`, `:56-57`) and sends it as
  `If-None-Match` on every non-bootstrap poll (`:54`); a 304 leaves the cursor untouched.
  Regression test `tests/js/live-sync-etag.test.js` (`node --test`), mutation-checked —
  dropping the header reddens all three cases. (verified 2026-08-31 by findings-sweep)
- `list_expired_materials` (`corechecks.py:201`) calls `get_check_results()` which runs every live check.
  Fix: narrow public cache accessor for just the `expired_materials` slice.
  Already fixed: `list_expired_materials` (`app/core/backend/corechecks.py:188`) now calls the
  narrow `get_expired_materials_result` accessor from `system_findings_cache` — not
  `get_check_results` — with a docstring spelling out the reason. (verified 2026-09-11 by findings-sweep)
- `list_executions` process+status+keyset (`execution_repo.py:200`) has no matching composite index.
  Fix: add `(org_id, process_id, status, created_at DESC, id DESC)`, verify with `EXPLAIN (ANALYZE, BUFFERS)`.
  Already fixed by migration `exec_completed_page_idx_001` ("Composite index for the process-scoped
  completed-execution page query", in the current head lineage via `merge_noident_execpage_001`):
  it creates `ix_executions_org_process_status_created_id` on
  `(org_id, process_id, status, created_at DESC, id DESC)` — exactly this shape —
  `CONCURRENTLY` in an autocommit block, `downgrade()` drops it. Confirmed present on the
  migrated test DB (`pg_indexes`). `list_executions` (`app/core/db/repositories/execution_repo.py:197-205`)
  filters `org_id`/`process_id`/`status` then `ORDER BY created_at DESC, id DESC`, which the
  index covers. `EXPLAIN` on local/CI data is tiny so the planner may still seq-scan — the
  same caveat `exec_completed_page_idx_001`'s own docstring records. (verified 2026-09-01 by findings-sweep)
