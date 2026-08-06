# REVIEW: process-design
date: 2026-08-02 (patched 2026-08-03 per founder decisions)
baseline: tests green (748 passed, 30 skipped — 30 expected live-server skips, no dev
server running at baseline time)
verdict: patched — all findings resolved, no open items

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| spec reconstruction | reconstructed → reviewed | n/a, no prior spec existed | `.agents/specs/process-design.md` |
| migration audit | pass (1 historical, low-severity) | 1 undocumented-but-reversible destructive migration, pre-existing | `.agents/reports/process-design/migrations.md`, `.agents/reports/migrations/drop_uq_steps_psn_001.md` |
| security-audit | findings-open → 2 fixed, 1 escalated | F1 dead code, F2 session leak+no audit trail, F3 admin-gate asymmetry | `.agents/reports/process-design/security-audit.md` |
| e2e-playwright (gap-fill) | pass, 69 tests added | 0 (closed 2 index-flagged coverage gaps, found 2 more bugs while writing) | `tests/e2e/test_process_docs_flow.py`, `test_process_steps_flow.py`, `test_process_wizard_flow.py` |
| unit coverage + test-author | pass, 59 tests added | 0 (closed zero-unit-coverage gap on process/step CRUD + reorder + wizard helpers) | `tests/test_process_design.py` |
| test-evaluator | **valid** | 0 (7 tests falsifiability-checked, all correctly go red when their target behavior breaks) | `.agents/reports/process-design/test-evaluator.md` |
| perf-guardrails | clean | 0 (all measured routes well under budget) | `.agents/reports/process-design/perf.md` |
| observability | instrumented | 0 (added `access_denied` warnings at 4 tenant-boundary-miss points; none existed before) | `.agents/reports/process-design/observability.md` |
| ci-gate verify | pass, no CI changes needed | 0 | `.agents/reports/process-design/ci-gate.md` |

## Before / after

- **Tests**: 0 process-design-specific tests → 130 (59 unit + 71 e2e, one net addition
  during patching: the reorder audit-trail test, plus the oversized-upload test split
  into two to cover both sides of the fixed boundary).
- **Coverage**: process/step CRUD, reorder, and wizard helpers (`backend.py:139-424`,
  `855-1022`, `1201-1694`) went from zero fast unit coverage (e2e-only, invisible to
  `pytest-cov` across the process boundary) to full validation/error-branch coverage.
  process-docs (`app/core/backend/process_docs/`) went from page-render-smoke-only to
  full upload/inline/download/delete + cross-tenant coverage.
- **Findings fixed**: 3 (dead code deleted; reorder's session leak, missing audit
  trail, missing position validation, and a partial-commit-on-validation-failure bug
  all fixed together; global `MAX_CONTENT_LENGTH` mismatch fixed).
- **Findings escalated (not patched)**: 1 (process-delete/doc-delete admin-gate
  asymmetry) + 1 pre-existing migration permit backfilled pending acknowledgement.
- **Rules added to `.semgrep/`**: 0 — both security findings were judged not
  mechanically distinguishable enough for a bespoke rule without a high false-positive
  rate (see security-audit.md's `rule_added` notes); recommended a `learned.yml`
  pattern-note instead once a second occurrence of the "return inside `with
  sess.begin():` before `.close()`" shape shows up elsewhere.
- **Full suite**: 906-908 passed (varies with live-server tests included/excluded
  based on dev-server state), 0 failed, throughout every re-run after patching.

## What changed (files)

- `app/core/backend/backend.py`: deleted dead `_assert_valid_step_write`; extracted
  `_is_valid_step_position` (shared grid-validity check); added
  `_log_process_access_denied` helper + wired into `_assert_flow_process_access`,
  `_get_process_or_404`, and `reorder_steps`; rewrote `reorder_steps` to validate
  positions up front, delegate to `ProcessRepository.reorder_steps`, and close its
  session via `try/finally`.
- `app/core/db/repositories/process_repo.py`: new `reorder_steps` method — validates
  all step ids belong to the process before applying any update (fixes the
  partial-commit-on-validation-failure bug found while restructuring), applies
  updates, inserts a `ProcessVersion`, emits `process.steps_reordered`.
- `app/core/backend/process_docs/process_docs_service.py`,
  `process_docs_validation.py`: added `access_denied` warnings at org-scope-miss
  points.
- `app/api/app_factory.py`: `MAX_CONTENT_LENGTH` now `max()` across every feature's
  own upload-size config, not just `evidence`'s.
- `tests/test_process_design.py` (new, 61 tests), `tests/e2e/test_process_docs_flow.py`
  (new, 18 tests), `tests/e2e/test_process_steps_flow.py` (new, 29 tests), `tests/e2e
  /test_process_wizard_flow.py` (new, 24 tests), `tests/e2e/test_workflow_flow.py`
  (+2 tests: admin-gated delete + member-forbidden).
- `.agents/specs/process-design.md` (new, reconstructed then updated to `reviewed`),
  `.agents/test-map.md` (row 9 updated), `.agents/history/findings.jsonl` (4 verdicts
  recorded, F3 updated fixed→fixed after the founder decision),
  `.agents/reports/migrations/drop_uq_steps_psn_001.md` (new permit, acknowledged).

## Founder decisions (2026-08-03)

1. **F3 — admin-gate asymmetry**: founder chose to add the ADMIN gate to
   `delete_process` (not drop it from process-docs delete). Patched:
   `@requires_role(UserRole.ADMIN)` added to `DELETE /api/core/processes/<id>`; tests
   updated across both the unit suite (`admin_client` fixture) and e2e
   (`admin_page` fixture + a new 403-for-member test).
2. **Migration permit**: founder acknowledged `drop_uq_steps_psn_001` (2026-04-13,
   already shipped, no data loss) — roll forward, no code/migration change. Permit
   file updated to `ACKNOWLEDGED — roll forward`.

Both decisions patched and the full suite re-run green (910 passed, 0 failed) after
each.

## Remaining note (not a finding, not blocking)

`process_docs_delete`'s 200-for-cross-tenant-and-already-deleted asymmetry: not
treated as a bug (arguably a *stronger* anti-enumeration property than the rest of the
API's 404-on-cross-tenant convention), left as-is, flagged only so a future "fix"
doesn't accidentally weaken it without realizing the tradeoff.

## Recommendation

Ready for **merge-request** to open the MR.
