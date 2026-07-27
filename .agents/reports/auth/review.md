# REVIEW: auth
date: 2026-07-26
baseline: tests green (10 passed, 30 skipped — live_server 2FA suites, no dev server running)
verdict: patched

Blueprint: `app/api/routes/auth_routes.py` (1548 lines) + `app/core/security/auth_service.py`,
`app/api/middleware/session_security.py`, `app/core/security/permissions.py` (shared).
Spec reconstructed at `.agents/specs/auth.md` (21 ACs, status: reconstructed).

## Execution note
Same `herdr-tabs` breakage as the org review — fell back to in-process subagents for
Claude-engine stages and direct `codex exec --sandbox read-only` for the Codex-graded
test-evaluator stage.

**Incident during aggregation**: while manually verifying the test-evaluator's route-level
regression test, a `git checkout -- app/api/routes/auth_routes.py` (intended to undo a
temporary experimental edit) discarded *all* of security-audit's uncommitted patches to
that file — F1's route-half, F2, F3, and their nosemgrep suppressions. Recovered in full
from an unreachable git blob (`git fsck --unreachable --dangling`, content-matched and
confirmed against the diff's recorded target blob hash) — verified zero data loss via a
full-repo test run (506 passed / 30 skipped) after recovery. Logged in
`.agents/reports/auth/test-evaluator.md` as a mistake worth remembering: `git checkout --
<file>` reverts the *whole file*, not the last edit — use `git stash` or a manual
counter-edit instead when a file has other uncommitted work in flight.

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| migration-safety | n/a | no model/migration changes for this feature | — |
| security-audit | patched | 3 real fixes (F1 timing enumeration, F2 session-rotation drift, F3 disable_2fa trusted-device gap) | `.agents/reports/auth/security-audit.md` |
| e2e-playwright | patched | 7 AC gaps closed (AC3/4/8/9/13/17/20), 13 new tests | `.agents/reports/auth/e2e-playwright.md` |
| test-evaluator (codex, read-only) | patched | G1 (inactive-user timing test missing) + G2 (route-level reordering had no regression test — the more serious gap) both closed; G3 (F2 test style) considered, no change | `.agents/reports/auth/test-evaluator.md` |
| perf-guardrails | clean | `/auth/me` (already measured) passes budget; login/signup deliberately not added to budgets.json — bcrypt cost dominates and isn't a meaningful perf-regression signal | — |
| observability | clean | `access_denied` (403) logging added at the shared `permissions.py` decorator level (same fix as org review, since both blueprints use it); 401s deliberately not logged — routine session-expiry noise, not a security signal | `app/core/security/permissions.py` |
| ci-gate | clean | existing `.gitlab-ci.yml` picks up new tests (`pytest tests/ -v`) and the new learned rule (`semgrep --config .semgrep/rules/` + `semgrep_learned_rules` fixture-verify job); no CI changes needed | — |

## Before / after
- Tests: 10 passed/30 skipped → 33 passed/30 skipped (all live_server skips are the
  legitimate 2FA suites needing `uv run workflow start`; none of the new coverage needed
  a live server — every route here is local Flask/pyotp logic with no outbound calls).
- Findings fixed: 3 security (F1 timing/enumeration, F2 session-rotation drift, F3
  disable_2fa trusted-device gap), all with red→green-verified regression tests.
- Semgrep rules added: `.semgrep/rules/learned.yml#bize-session-clear-without-rotate`
  (fixtures at `.semgrep/fixtures/bize-session-clear-without-rotate/`); the
  `bize-verbose-error-to-client` rule from the org review also fires here (3 suppressed
  false-positives in auth_routes.py where `{e}` only reaches the server-side log, never
  the client response — justified inline with `nosemgrep`).
- False positives suppressed: 6 total across both learned rules plus 1 pre-existing
  semgrep rule, each with an inline justification comment.
- Escalated (not fixed, human judgment needed): (1) `USE_RELAXED_AUTH_RATE_LIMITS`
  trusting `ENVIRONMENT=test` — a deployment-config risk if that var were ever
  misconfigured in production, not a code bug; (2) `org_id` as an optional login
  parameter has no legitimate function now that email is globally unique — flagged for
  the feature owner to decide whether to remove it, not removed unilaterally.
- Coverage: same `pytest-cov`-not-installed gap as org; assessed by manual read-through.
  Every route's success/failure/validation branches now have a test, including the
  three formerly-timing-unsafe code paths.

## Full-repo regression check
`uv run pytest tests/ -q` → **506 passed, 30 skipped, 0 failed** (up from the documented
baseline of 252 passed/30 skipped — both blueprint reviews combined added 254 net tests
across the repo... actually the bulk is org+auth's own files; ran repo-wide specifically
to catch any blast-radius regression from the two shared-file changes, `permissions.py`
and `auth_service.py`/`session_security.py`. None found.)

## Escalations — now resolved (2026-07-27)

Both items originally left open for human judgment were resolved on the owner's
instruction to fix all findings:

- **`org_id` login parameter — REMOVED** (`6de6865`). Confirmed no caller: the login form
  posts `email`/`password`/`device_fingerprint` only, and nothing in `app/` or the
  frontend sends it. Since `User.email` is `unique=True` globally, the parameter could
  never select a different account — only act as an org-membership oracle. The two tests
  that encoded the old contract were replaced with tests asserting the field is now inert.
- **`USE_RELAXED_AUTH_RATE_LIMITS` — now fails closed** (`6de6865`). Gated on an
  allowlist (`ENVIRONMENT in {local, test}`) instead of ambient CI markers, so production,
  unset, misspelled, and unknown environments all keep the strict 5/min limit no matter
  what `CI`/`GITLAB_CI` say. Verified the old logic returned `True` for
  `ENVIRONMENT=production, CI=true` and the new one returns `False`, so
  `tests/test_auth_rate_limit_gating.py` is a real regression guard.

## Still open
- G3 from test-evaluator (F2 test asserts observable outcome, not that `rotate_session()`
  was called) — considered and deliberately rejected: asserting the `Set-Cookie` header is
  the correct level; mocking the helper would be an implementation-detail test that breaks
  on refactor while proving less.
- **Rotation status of the historic committed credentials is UNCONFIRMED** — see
  `.gitleaks.toml`. Allowlisting silenced the scanner; it did not revoke anything. Needs a
  human to confirm whether the GitLab PATs and `sk-live-` value in the pre-2026 deleted
  files were ever real, and rotate if so.
- The cross-agent worktree-collision risk (two subagents editing one shared worktree
  converged on overlapping edits) — still worth a `skill-smith` pass.

## Recommendation
Merge. No open findings block; the two escalated items are product/ops decisions, not
code defects, and don't block a merge. Spec status set to `reviewed`.
