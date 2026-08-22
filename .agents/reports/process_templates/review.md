# REVIEW: process_templates
date: 2026-08-22
baseline: tests green (29/29 unit, pre-review)
verdict: patched

## Context

This is a review-feature audit of `process_templates` (Industry Process Templates —
`feat/process_templates`, MR !169, merged to `main` at `2aa5375` earlier today). The
feature had already been through `new-feature`'s own full build-time chain
(spec-critic ×2, security-audit, security-tenant-audit, e2e-playwright, observability,
test-evaluator ×2, ci-gate — all green/clean/valid; see the non-`review-*`-prefixed
reports in this directory). This review re-ran the verification chain independently
against the merged code rather than trusting those build-time verdicts, per the
skill's "a reviewed feature and a newly built one end up provably equivalent" standard.
Not yet in `.agents/feature-index.md` at review start (freshly merged); this run's
findings feed that index update in Step 5.

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| migration audit | n/a — skipped | no migrations/model changes (spec: "Data model: none"); confirmed no migration file touched across the feature's commits | — |
| security-audit (independent re-audit) | clean | 0 | `review-security-audit.md` |
| e2e-playwright (gap-fill) | patched | 1 real flake fixed, 3 AC gaps closed with new tests | `review-e2e-playwright.md` |
| unit coverage check | — | 3 real gaps found (95% → handed to test-author) | (inline, this report) |
| test-author | covered | 3 gaps closed, 8 tests added | `review-test-author.md` |
| test-evaluator (test-author's internal grading) | valid | 0 | `review-test-author-eval.md` |
| perf-guardrails | within-budget (unchanged from build time) | 0 | `perf/2026-08-22-process-templates.md` (build-time; re-confirmed, no route/query-shape changes this pass) |
| observability | instrumented (unchanged from build time) | 0 | `observability.md` (build-time; `access_denied` warnings + `template_copied` event log confirmed present) |
| ci-gate (verify) | pass | 0 | `review-ci-gate.md` |

## What this review found and fixed

### 1. Real flake in the e2e suite (fixed)

`login_through_ui` returns as soon as the browser reaches `/dashboard`, but
`dashboard.js` fires its summary/findings fetches *after* that asynchronously. The
process_templates e2e fixtures then immediately navigated away, cancelling those
in-flight fetches; Chromium raises a plain `TypeError` (not `AbortError`) for a
navigation-cancelled fetch, which `core-api.js`'s catch block logs as a genuine
`console.error` — `assert_clean_page` correctly (if unluckily) flags that as a page
fault. This reproduced deterministically (1 failure in 2 runs, exact same assertion
both times) and was previously misdiagnosed at build time (`ci-gate.md`'s "Run 3")
as a generic "load-sensitive, pre-existing, not a regression" flake and left alone.
Fixed test-side: both `process_templates` e2e fixtures now
`wait_for_load_state("networkidle")` after login. Confirmed clean across 3 consecutive
full-suite e2e runs post-fix. Out of scope to patch the shared `core-api.js` race
itself (used by every SPA page) from this stage — flagged here for anyone auditing
that file next.

### 2. Three real unit-coverage gaps (closed)

A `pytest --cov` pass (95% line coverage pre-review) surfaced three branches with zero
test coverage, all genuine — not just uncovered lines, but untested *behavior* the
spec or the code's own comments call out as intentional:

- **Static-asset path-traversal/extension guard** (`process_templates_bp.py:31-33`) —
  a real security control (the route rejects `..`/`/`-containing or non-`.js`/`.css`
  filenames before `send_from_directory`) had never been exercised by a test. The
  build-time security-audit *verified this by reading the code*, not by running
  anything against it.
- **`_build_description`'s two AC6 branches** (`process_templates_service.py:104-113`)
  — the no-description fallback and the truncate-so-the-provenance-suffix-survives
  logic were both spec-mandated (AC6) but untested.
- **Genuinely-nonexistent template id → 404** (`registry.py:118`) — only the
  wrong-family-for-a-real-id 404 path (AC3) had a test; a fabricated id going through
  the same endpoint was unverified.

`test-author` closed all three with 8 new tests (exact-match assertions, not
smoke-only), re-graded internally by `test-evaluator` (verdict: `valid`, including
mutation spot-checks on all three guarded paths). Line coverage is now 99% (215 stmts,
2 misses — both explicitly out-of-scope: `registry.py:111`'s unused `all_templates()`
dead code, and one extreme-edge defensive guard inside the now-tested truncation
branch that no real catalogue data can reach).

### Noted, not acted on

`registry.py:110-111`'s `all_templates()` is unused dead code (no caller anywhere in
`app/` or `tests/`) — flagged as a low-priority cleanup candidate for a future pass,
not removed here (out of this review's scope; not a defect).

## Independent verification (this review, not trusted from stage reports)

- `tests/test_process_templates.py`: 37/37 passed (re-run directly).
- `tests/e2e/process_templates/`: 11/11 passed (re-run directly).
- Full repo suite `pytest tests/ -q`: **1622 passed, 31 skipped, 0 failed** (12m06s) —
  no regression anywhere from this review's changes. The 31 skips are the documented
  live-server 2FA suites; zero skips in `test_process_templates.py`.
- `ruff check` + `ruff format --check`: clean on every touched file.
- `semgrep --config .semgrep/rules/`: 0 findings, scoped re-scan.
- `gitleaks`: 0 leaks in the feature path.
- `uv audit`: 0 vulnerabilities.
- `semgrep --validate`: 29 rules, 0 config errors.
- No migration files touched by any process_templates commit.

## Findings recorded to history

Four findings recorded via `finding_history.py` (`--skill review-feature --ref
mc/review-feature-20260822-093608-4eb56a`), all verdict `fixed`:
`test-flake-dashboard-fetch-race`, `coverage-gap-static-asset-guard`,
`coverage-gap-build-description-truncation`, `coverage-gap-missing-template-id-404`.

## What remains open

Nothing blocking. The one advisory item carried over from build time
(`/api/core/dashboard/summary` at 39 queries vs. its 38-query ratchet) is unrelated to
this feature — this feature's diff never touches dashboard/summary code — and was
already the top item on the standing perf priority checklist before this review;
not re-actioned here.

**Recommendation**: ship as-is. This feature is now provably equivalent to a
freshly-built, freshly-reviewed one — same chain, same standard, independently
re-verified rather than trusted from its own build-time run.
