# CI-GATE VERIFY: process-design
date: 2026-08-02
mode: verify (existing pipeline, not rebuilt)

## Coverage checks
1. `pytest --collect-only -q tests/` → all 128 process-design tests collected
   (59 unit in `tests/test_process_design.py`, 69 e2e across
   `test_process_docs_flow.py`/`test_process_steps_flow.py`/`test_process_wizard_flow.py`).
   None silently uncollected.
2. `semgrep --validate --config .semgrep/` → 0 configuration errors, 28 rules valid.
   No new custom rule was added this review (both security-audit findings were judged
   not mechanically distinguishable enough for a bespoke rule — see
   `security-audit.md`), so nothing new to validate beyond confirming the existing set
   still parses.
3. No new migration this review → nothing to add to the alembic chain.
   `alembic heads` → single head (`crm_revenue_baseline_target_001`), no branching.
4. `.gitlab-ci.yml`'s `unit_tests` job runs `ENVIRONMENT=test uv run pytest tests/ -v`
   against a live Flask server it starts itself (`ci/setup_server.sh`) — a broad glob,
   so the four new test files are picked up automatically; no job/matrix edit needed to
   wire them in.

## Gate results (full local equivalent)

```
GATE lint: pass (ruff check app/ — 0 findings)
GATE unit: pass (906 passed, 0 failed, 0 skipped — full tests/ including e2e, live
           dev server up; process-design's own 128 tests pass within this total)
GATE semgrep: pass (0 findings scoped to the 8 process-design files, security-audit
           stage; --validate confirms rule set parses)
GATE migrations: pass (structural — all revisions touching processes/steps/
           process_versions/process_step_documents have real, symmetric downgrade()
           functions, verified by reading each; full upgrade/downgrade/upgrade
           rehearsal NOT run locally against the shared workflow-engine-test-db to
           avoid disrupting concurrent worktree sessions on the one shared container —
           CI's migration_reversibility job already performs exactly that rehearsal
           [downgrade base -> upgrade head -> downgrade -1 -> upgrade head] against a
           fresh per-pipeline Postgres service container, so the real gate is intact;
           see migrations.md)
GATE e2e: pass (69/69 process-design e2e tests, run together with the rest of the
           e2e suite as part of the 906-test full run)
```

## Not weakened
No `allow_failure: true`, `--cov-fail-under` change, `# nosemgrep`, or skip marker was
added or loosened anywhere in this review. (This repo's actual `.gitlab-ci.yml` has no
`--cov-fail-under` gate configured at all — the ci-gate skill's template mentions one
generically, but it doesn't exist in this project's real pipeline, so there was nothing
to check there.)

## Pipeline status
Not yet pushed — this review's changes are still local to the `review/process-design`
branch/worktree. Real `glab ci status` confirmation happens after merge-request's push,
per this skill's step 5 ("local green never substitutes for the pipeline that actually
guards merge").

## Verdict
Gate is intact and already covers everything this review added, with no CI config
changes required.
