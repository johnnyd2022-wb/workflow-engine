# REVIEW: org
date: 2026-07-26
baseline: tests green (11 passed, 0 skipped, 0 failed)
verdict: patched

Blueprint: `app/api/routes/org_routes.py` (+ `app/core/security/org_manager.py`), spec
reconstructed at `.agents/specs/org.md` (8 ACs, status: reconstructed).

## Execution note
`verification_mode` from preflight was `herdr-tabs`, but `scripts/agent_launch.py`'s
herdr integration was broken against the installed herdr CLI (0.7.3) — `herdr pane run`
returns no output where the script expected a JSON envelope, so no stage could launch as
a labelled tab.

This run therefore fell back to in-process subagents (Claude, general-purpose) for the
two Claude-engine stages, and invoked `codex exec --sandbox read-only` directly for the
Codex-graded stage — bypassing the broken herdr wrapper while keeping the grader
read-only and on a separate engine, as the contract requires.

The launcher itself was **fixed in `d2389eb`** and verified end-to-end afterwards, so
subsequent runs get real tabs. It was a tooling regression affecting every skill that
calls `agent_launch.py launch`, not an org/auth finding.

Both `security-audit` and `e2e-playwright` ran as background subagents in the same
shared worktree and independently converged on overlapping fixes (see below) — a
real orchestration-dedup risk worth a `skill-smith` look, not something this review
patches itself.

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| migration-safety | n/a | no model/migration changes for this feature | — |
| security-audit | patched | 1 fix (F1), 2 test-gap closures (F2/F3) | `.agents/reports/org/security-audit.md` |
| e2e-playwright | patched | AC8 had zero coverage; 5 new tests | `.agents/reports/org/e2e-playwright.md` |
| test-evaluator (codex, read-only) | patched | G1: F1's fix had no regression test — closed | `.agents/reports/org/test-evaluator.md` |
| perf-guardrails | clean | `/org`, `/org/users` added to budgets.json measure list; both pass budget on first measurement | `.agents/reports/perf/last-run.json` |
| observability | patched | `@requires_role` (shared decorator, also used by `process_docs_routes.py`) logged no `access_denied` event on a 403 — added, with a test | `app/core/security/permissions.py` |
| ci-gate | clean | existing `.gitlab-ci.yml` already runs `pytest tests/ -v` (picks up new tests) and `semgrep --config .semgrep/rules/` (picks up the new learned rule + `semgrep_learned_rules` fixture-verify job); no CI changes needed | — |

## Before / after
- Tests: 11 → 27, all passing (5 cross-tenant AC8 tests, 6 AC2-AC6 edge-case closures,
  3 F1-regression tests, 1 F7 DELETE-forbidden-for-member, 1 observability
  access_denied test — some landed by security-audit, some by e2e-playwright, some by
  this aggregation pass; final count verified directly, not just claimed).
- Findings fixed: 1 security (info disclosure via raw exception text in 3 routes), 1
  observability gap (missing access_denied logging on role-check 403, shared decorator).
- Semgrep rules added: `.semgrep/rules/learned.yml#bize-verbose-error-to-client`
  (fixtures at `.semgrep/fixtures/bize-verbose-error-to-client/`, verified via
  `scripts/rule_candidates.py verify`).
- Coverage: `pytest-cov` is not a dev dependency in this repo (`--cov` fails with
  "unrecognized arguments"), so branch coverage was assessed by manual read-through
  against the 27 tests rather than measured — every route/branch in
  `org_routes.py` now has a passing/forbidden/not-found/invalid-input test, including
  the three formerly-uncovered generic-exception branches. Adding `pytest-cov` is a
  candidate follow-up for **dependency-update**, not done here (out of scope for a
  behavior review).

## Findings — now resolved (2026-07-27)

Resolved on the owner's instruction to fix all findings:

- **`OrgManager.switch_org` — REMOVED** (`b16c05f`). Zero callers anywhere in `app/`,
  `tests/`, or the frontend. Not merely unused but actively misleading: despite the name
  it switched nothing, returning a bool with a comment deferring the real work elsewhere,
  so a future caller would reasonably assume it changed the active org.
- **G2 — CLOSED** (`b16c05f`). `test_patch_org_writes_an_audit_log_row` now asserts the
  `audit_logs` row (action/entity/entity_id) and that the acting user is recorded. The
  route writes two independent trails and only `emit_event` was covered, so deleting the
  `log_action` call previously left the suite green.
- **Coverage now measured, not estimated** (`pytest-cov` added). `org_routes.py` **92%**,
  `permissions.py` **94%**, `org_manager.py` 70%. Replaces this report's earlier
  "assessed by manual read-through" caveat.

## Still open
- The cross-agent worktree-collision risk (two subagents in one shared worktree
  independently converging on overlapping edits) — recommend a `skill-smith` pass.
  The herdr-tabs break noted above is **fixed** (`d2389eb`).

## Recommendation
Merge. No open findings block. Spec status set to `reviewed`.
