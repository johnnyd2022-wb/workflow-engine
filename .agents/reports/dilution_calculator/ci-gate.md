# CI GATE (verify mode) — dilution_calculator

date: 2026-07-26
mode: verify (not setup — `.gitlab-ci.yml` already exists and is not modified by this run)
worktree: /home/johnny/workflow-engine-dilution_calculator
branch: feat/dilution_calculator (`git merge-base main HEAD` = `a3ea78d`; 8 commits ahead of
`origin/main`, 16 commits in the `main...HEAD` range since main itself has moved)

This run does not rebuild the pipeline. It re-derives, locally, what each blocking job in
the real `.gitlab-ci.yml` would do against this branch's diff, and reports pass/fail per
job so the orchestrator can gate the merge request on real evidence rather than on the
prior stage reports' say-so. Every command below was actually executed in this worktree
during this run (not read off an old report) unless explicitly marked otherwise.

## Feature surface (from spec + diff)

`.agents/specs/dilution_calculator.md`: `Data model: changes: none, destructive: no`.
Confirmed against the repo, not assumed:

```
git diff main...HEAD --stat -- app/core/db/migrations/versions/
```
→ empty (no output). No migration file was added, changed, or removed by this branch.
`alembic history` still shows a single linear chain ending at
`crm_revenue_baseline_target_001 (head)` — that head belongs to an unrelated prior CRM
migration, not to this feature, exactly as expected when a feature adds zero schema.

Files this feature touches (`git diff --name-only main...HEAD`, non-report/non-metrics
subset):
- `app/features/dilution_calculator/**` (blueprint, routes, service, template) — new
- `app/api/app_factory.py` — blueprint registration
- `app/observability/context.py` — `BLUEPRINT_FEATURE` nested-blueprint mapping fix
- `app/ui/templates/shared/sidebar-v2.html` — nav link
- `tests/test_dilution_calculator.py` — new, 34 tests
- `tests/test_observability_context.py` — 1 new regression test
- `tests/e2e/test_dilution_calculator_flow.py` — new, 6 tests
- `tests/e2e/test_perf_budgets.py` — extended for POST-with-body routes, 2 tests exercise
  this feature's routes
- `.agents/perf/budgets.json`, `scripts/perf_triage.py` — perf-guardrails harness support

## GATE ruff: pass

```
uv run ruff check app/                 → All checks passed! (141 files, whole app/ tree)
uv run ruff format --check app/        → 141 files already formatted
```
Matches the CI `ruff` job's actual scope (`ruff check app/ --fix` then
`ruff format app/`, i.e. the whole `app/` tree, not feature-scoped). One pre-existing,
out-of-scope ruff finding exists at `tests/e2e/test_perf_budgets.py:170` (`UP017`,
`datetime.now(timezone.utc)` vs `datetime.UTC`) — confirmed via
`git diff main...HEAD -- tests/e2e/test_perf_budgets.py` that this exact line is
**unchanged** by this branch (present verbatim on `main`), and it sits under `tests/`,
which the `ruff` CI job never scans (`ruff check app/` only). Not this feature's
regression, not gated by this job, not fixed here per the skill's "don't touch what
isn't yours to touch" boundary for a verify pass.

## GATE unit_tests (pytest): pass

Feature-scoped, run directly:
```
env -u ENVIRONMENT uv run pytest tests/test_dilution_calculator.py tests/test_observability_context.py -v
→ 37 passed (34 feature AC tests + 1 pre-existing context test + 1 new nested-blueprint
  regression test), 3.39s

env -u ENVIRONMENT uv run pytest tests/e2e/test_dilution_calculator_flow.py -v
→ 6 passed, 9.55s (Playwright/Chromium, dev app server up at https://localhost:8005/)
```
`pytest --collect-only -q tests/ | grep -i dilution` confirms all 43 dilution-related
tests are actually collected by the root `tests/` target the CI `unit_tests` job runs
(34 in `test_dilution_calculator.py`, 1 in `test_observability_context.py`, 6 in
`test_dilution_calculator_flow.py`, 2 in `test_perf_budgets.py` parametrized on this
feature's routes) — none are silently excluded by markers or collection config.

Full repo suite, matching the CI `unit_tests` job's actual command
(`ENVIRONMENT=test uv run pytest tests/ -v`, run here as
`env -u ENVIRONMENT uv run pytest tests/ -q` per this repo's documented host-run rule —
`ENVIRONMENT=test` targets `host.docker.internal` and hangs from a host shell; `local.ini`
under `ENVIRONMENT` unset points at the same test DB on `localhost:8401` the CI service
container would be):
```
538 passed, 1 failed in 233.05s (0:03:53)
FAILED tests/test_execution_shared_utils_js.py::test_execution_js_node_unit
```
The 1 failure is pre-existing and unrelated: it shells out to `/usr/bin/node --test ...`
against JS files for execution/RUM code (`execution-modal-inventory-refresh.test.js`,
`execution-render-docs.test.js`, `execution-session.test.js`,
`execution-shared-utils.test.js`, `observability-rum.test.js`) — none of which this
feature touches — and fails because the installed Node is v12.22.9, which predates the
`--test` flag (needs Node 18+). Confirmed identical to the failure already documented in
`.agents/reports/dilution_calculator/observability.md` and `test-author.md` from two
prior stages of this same run, i.e. a stable environment gap, not a regression introduced
since. This is a toolchain issue, not a feature-scoped test failure, so `unit_tests` is
graded pass on this feature's own account; the pre-existing Node gap is flagged, not
silently absorbed into the verdict.

## GATE semgrep: pass

Three semgrep jobs exist in the real `.gitlab-ci.yml`; all three re-run here scoped to
this feature's files:
```
semgrep --config .semgrep/rules/ app/features/dilution_calculator/ --include="*.py" --include="*.js" --error
→ 14 python rules run on 4 files, 0 findings (feature has no .js files)

semgrep --config .semgrep/rules/observability.yml app/features/dilution_calculator/ app/observability/context.py --include="*.py" --severity ERROR --error
→ 1 rule run on 5 files, 0 findings

python3 scripts/rule_candidates.py verify   (the semgrep_learned_rules job's actual script)
→ learned rules: 1 (bize-mass-assignment-from-request) — fires on its vulnerable fixture,
  silent on the fixed one. No learned rule exists for this feature (none needed — zero
  findings were ever produced for it to learn from, confirmed in security-audit.md).
```
`semgrep --validate --config .semgrep/` → "Configuration is valid - found 0 configuration
error(s), and 25 rule(s)." Custom rules parse. `security-audit.md`'s own broader run
(`p/python` + `p/flask` + `p/owasp-top-ten` + `.semgrep/` across 7 files including
`app_factory.py` and `sidebar-v2.html`) is consistent: 171 rules, 0 findings — re-run here
independently, same result.

## GATE gitleaks: pass (host binary confirmed still absent — ran via the CI job's own Docker image instead)

Confirmed the known gap is still real:
```
which gitleaks   → not found
gitleaks version → /bin/bash: gitleaks: command not found
python3 scripts/preflight.py --json → capabilities.deps notwithstanding, advice: "4/5 available — missing: gitleaks"
```
Same gap `security-audit.md` and `preflight.py` already reported for this branch — not
newly discovered, and not resolved by anything this run did to the environment.

Rather than stop at "could not execute," checked whether the exact image the CI
`gitleaks` job itself uses (`zricethezav/gitleaks:latest`, `entrypoint: [""]`) was
already cached locally — it was (`docker images` shows it, 50.3MB, no pull needed) — and
ran it with the **same command shape** the CI job uses, scoped to this branch's diff
range exactly as the job's own range-selection logic would resolve it for an MR pipeline
(`$CI_MERGE_REQUEST_DIFF_BASE_SHA..$CI_COMMIT_SHA`, approximated here as
`$(git merge-base main HEAD)..HEAD` since no MR is open yet):
```
docker run --rm \
  -v /home/johnny/workflow-engine-dilution_calculator:/home/johnny/workflow-engine-dilution_calculator \
  -v /home/johnny/workflow-engine:/home/johnny/workflow-engine \
  -w /home/johnny/workflow-engine-dilution_calculator \
  --entrypoint gitleaks zricethezav/gitleaks:latest \
  detect --source . --no-banner --log-opts="a3ea78d4c0fc75f169f8d0c8ac4457ec48552249..HEAD"
→ 16 commits scanned, ~238.84 KB, no leaks found
```
(Needed both the worktree and the main repo's `.git` mounted — a worktree's `.git` is a
pointer file into the parent repo's `.git/worktrees/...`, which the first attempt without
the second mount couldn't resolve, surfaced as "0 commits scanned" rather than a false
clean.)

This is the real tool, the real image, the real diff range — not a substitute or a
weakened check — so it is graded as an actual pass, not a skip. But the underlying
environment gap preflight and prior stages flagged (`gitleaks` absent as a bare host
binary) is still accurate and still unresolved; the CI runner pulls the image itself and
is unaffected either way, but any other local workflow that assumes a bare `gitleaks`
binary on PATH will still fail here. Recorded so the next agent doesn't have to
re-discover the Docker workaround.

## GATE uv_audit: pass

```
uv --version → 0.11.32 (pinned in CI as UV_VERSION=0.11.29; local uv is newer, both
  support the preview audit command used here)
uv audit --frozen --output-format json --preview-features audit-command,json-output
→ {"summary": {"audited_packages": 82, "vulnerabilities": 0, "adverse_statuses": 0}}
```
Re-run fresh this session; matches the committed
`.agents/reports/dilution_calculator/uv-audit.json` byte-for-byte on the summary fields —
not stale.

## GATE migration_reversibility: pass (no new migration to test; existing chain still round-trips)

Spec states `Data model: changes: none` — verified true above (empty diff on
`app/core/db/migrations/versions/`), so there is no new revision for this gate to prove
reversible. Ran the actual CI job commands anyway, against the existing chain, to confirm
the gate itself isn't broken for this branch:
```
env -u ENVIRONMENT uv run alembic current   → crm_revenue_baseline_target_001 (head)
env -u ENVIRONMENT uv run alembic downgrade -1
  → Running downgrade crm_revenue_baseline_target_001 -> crm_task_done_archive_001
env -u ENVIRONMENT uv run alembic upgrade head
  → Running upgrade crm_task_done_archive_001 -> crm_revenue_baseline_target_001
env -u ENVIRONMENT uv run alembic current   → crm_revenue_baseline_target_001 (head)
```
`alembic heads` shows exactly one head throughout. Down/up/current round-trips cleanly.

## GATE data_stores: pass (bonus — same `test` stage as ruff, blocking, feeds off this branch's own new report/metrics files)

Not asked for explicitly but blocking in the real pipeline and touched by this run's own
report-writing:
```
python3 scripts/skill_metrics.py --check   → ✓ ledgers well-formed
python3 scripts/finding_history.py --check → ✓ history store well-formed
python3 scripts/agent_launch.py --check    → routing OK
```

## Not re-litigated (already graded by prior stages, spot-checked not re-run in full here)

- `security-audit.md` (verdict: clean, 7/7 manual checklist, semgrep+uv-audit clean,
  gitleaks flagged as not-run at that time — same gap this gate independently confirmed
  and additionally closed via Docker above).
- `e2e-playwright.md` (verdict: patched — the `hx-boost` bug found and fixed, then
  re-verified 3/3 flake-free; already reflected in the 6/6 e2e pass above).
- `test-evaluator.md` (verdict: valid — the batch of new/changed tests, including the
  observability regression test, graded as real, falsifiable, not gamed).
- `perf-guardrails.md` (verdict: within-budget / patched — both routes clear generic
  budgets by a wide margin; not a blocking CI job in this repo's actual `.gitlab-ci.yml`,
  so not gated here, only noted for completeness).

## Summary

```
GATE ruff: pass
GATE unit_tests: pass (538 passed, 1 pre-existing unrelated failure — tests/test_execution_shared_utils_js.py, stale system Node, not this feature)
GATE semgrep: pass (0 findings across all 3 semgrep CI jobs: semgrep, semgrep_observability, semgrep_learned_rules)
GATE gitleaks: pass (host binary still absent, confirmed — ran via the CI job's own cached Docker image against the same diff range instead; 16 commits scanned, no leaks)
GATE uv_audit: pass (0 vulnerabilities, 82 packages)
GATE migration_reversibility: pass (no new migration — spec's "changes: none" verified true; existing chain still round-trips down/up cleanly)
GATE data_stores: pass (bonus, blocking in same stage)
```

No gate failed. No gate was weakened, skipped, or had its threshold lowered to reach this
result. The one true environment gap (gitleaks absent as a bare host binary) is
unresolved but was not silently passed over — it was actively worked around using the
exact tool the CI job itself runs, and reported as such rather than assumed clean.

Pipeline status on the real GitLab runner was not checked as part of this run — no MR is
open yet for this branch (`git branch -vv` / no tracking ref to `origin/feat/...`). Per
the skill: "local green never substitutes for the pipeline that actually guards merge" —
this is the local-equivalent pass that clears the way to open the MR, not a substitute
for watching the real pipeline once one exists.
