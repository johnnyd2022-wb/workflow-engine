# REVIEW: wastage
date: 2026-08-11
branch: feat/global-org-scoping
baseline: tests green (25/25 in tests/test_wastage.py; repo-wide 730+ passed per CLAUDE.md norm)
verdict: **patched**

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| migration-safety | clean | 0 | [migration-safety.md](migration-safety.md) |
| security-audit | findings-open → patched | 1 | [security-audit.md](security-audit.md) |
| e2e-playwright | patched | — | [e2e-playwright.md](e2e-playwright.md) |
| unit-coverage | patched | — | [unit-coverage.md](unit-coverage.md) |
| test-evaluator (codex, independent) | invalid → fixed | 2 | [test-evaluator.md](test-evaluator.md) |
| perf-guardrails | clean | 0 | [perf-guardrails.md](perf-guardrails.md) |
| observability | patched | 1 | [observability.md](observability.md) |
| ci-gate | clean | 0 | [ci-gate.md](ci-gate.md) |

Execution: this session acted as orchestrator throughout, running stages inline
(`subagents`-equivalent) rather than as separate herdr tabs, except **test-evaluator**,
which genuinely ran on an independent engine (`codex exec`, model `gpt-5.6-sol`,
`--sandbox read-only`) per `grader_engine: codex` from preflight — so the review's most
adversarial stage had real fresh eyes, not self-grading.

## Why this slice, and what "review" meant here
`wastage` had never been reviewed (feature-index: `reviewed: never`), but its acceptance
criteria were not built from scratch — they were largely already written and
adversarially reviewed as part of the **inventory** slice's own review
(2026-07-27→29, commits `e748618`/`ac49b2c`, confirmed merged ancestors of this branch).
That review's F2 fix (`InvalidOperation` handling on `inventory_dispose_confirm`) already
touches one of wastage's own routes. This review extracted wastage's ACs into their own
spec (`.agents/specs/wastage.md`, `status: reconstructed`), re-verified them against
current code, and focused adversarial effort on the genuinely untested surface: the two
HTML disposal pages, which had no dedicated test file at all.

## What was wrong, and what now stops it recurring

### F1 (security-audit) — the two disposal HTML pages had no cross-tenant test
`/core/inventory/dispose` and `/core/inventory/dispose/confirm` were correct by code
inspection (both filter `InventoryItem.org_id == org_id`) but unproven: no dedicated test
file existed, and the only coverage was a generic render-smoke-test with no content
assertions. A repeated cross-org probe of the confirm page would also have left **no log
trace** (see Observability below) — belt-and-suspenders correctness with zero visibility
if it had ever broken.

Fixed: new file `tests/e2e/test_inventory_dispose_pages.py`, 7 tests covering AC-D1/D2/D3
(preselect, happy-path remainder, four unhappy-path branches, and the cross-tenant
probe). 4 new unit tests in `tests/test_wastage.py` close matching gaps in the JSON API's
own branches (zero-quantity item, non-string `quantity_unit`, malformed/filtered
`?inventory_item_id=` on the list route).

### F2 (test-evaluator, independent grader) — two of those new tests had weak assertions
Caught by the Codex grader via static analysis (its sandbox had no DB/browser access, so
it read the assertions against the route logic directly rather than running mutations
itself):
- The cross-tenant test asserted absence of the seeded on-hand quantity (`42`), but the
  page only ever discloses the **computed remainder** (`41`) — the assertion could never
  have caught a real quantity leak.
- The happy-path remainder test's bare `to_contain_text("7")` could coincidentally match
  a digit inside the test item's random hex-suffix name (~40% chance), independent of
  whether the remainder computation was correct.

Both fixed and **mutation-verified live** by the orchestrator (the grader's own sandbox
correctly refused to write its report file or make further edits, per
`.agents/verification-chain.md` §5 — this is the documented handoff, not a gap):
- Cross-tenant test now checks for `"41"` (the value that would actually leak), plus a
  sanity assertion that the legitimate owner's identical request does show it. Verified:
  a narrow mutation (removing just the explicit `.filter(org_id=...)`) was silently
  caught by this branch's own global `TenantScoped` filter and produced no leak at all —
  a genuine defense-in-depth win, and also why a **second**, real mutation
  (`unscoped()` + no filter) was needed to prove the fixed test actually goes red on a
  true leak. It did. Restored, reran: 7/7 green.
- Remainder test now anchors on the rendering sentence via a regex, immune to the hex
  suffix collision.

### Observability — the same silent-cross-tenant-probe class the inventory review found elsewhere
Neither of wastage's two "item not found or cross-org" branches
(`record_wastage`'s per-entry lookup, `inventory_dispose_confirm`'s preview lookup)
logged anything — a repeated tenant-boundary probe of either surface would have left
zero trace, the same gap the inventory review fixed for a different route
(`_assert_source_refs_belong_to_org`). Fixed: both now emit the same `access_denied`
event name/shape already used by `permissions.py`/`inventory_repo.py`/the
process-design and traceability slices, so one query covers wastage too. Two new
regression tests, one mutation-verified live (dropped the log call, confirmed the test
goes red, restored, confirmed 31/31 green in `test_wastage.py`).

## Deliverables that outlive this conversation
- **`.agents/specs/wastage.md`** — 22 ACs (12 extracted from the inventory review's own
  spec, re-verified; 3 new for the HTML pages), `status: reconstructed`.
- **13 new tests**: 6 unit (`tests/test_wastage.py`, 25 → 31) + 7 e2e (new file
  `tests/e2e/test_inventory_dispose_pages.py`).
- **2 new `access_denied` log sites** (`app/core/backend/backend.py`), matching the
  codebase's established observability pattern.
- **2 new perf-budget measure entries** (`.agents/perf/budgets.json` →
  `measure.pages`), both confirmed comfortably within budget.
- **4 finding-history records** (`scripts/finding_history.py`): the coverage-gap finding
  (security-audit → e2e-playwright, confirmed→fixed) and both test-quality findings
  (test-evaluator, confirmed→fixed).

## Before / after
| | before | after |
|---|---|---|
| `tests/test_wastage.py` | 25 tests | **31 tests** |
| dedicated HTML-page tests | 0 | **7** (new file) |
| `wastage_repo.py` coverage | 96% | **100%** |
| `inventory_wastage_quantity.py` coverage | 89% | 91% |
| cross-tenant probe on HTML pages | none | yes, mutation-verified |
| `access_denied` logging on wastage's cross-org paths | none | both branches |
| semgrep findings (wastage files) | — | **0** |
| gitleaks / uv-audit | — | **0 / 0** |
| repo-wide full suite | (not re-run for this slice before) | **1395 passed, 0 failed, 31 skipped** |

## Disclosed gaps, not closed (diminishing returns, listed rather than chased)
- `backend.py:3055` — non-PostgreSQL no-op branch of the advisory lock; prod is always
  Postgres.
- `backend.py:3264-3266` — a `convert_to_inventory_unit_decimal` `ValueError` after
  `are_units_compatible` already passed; only reachable if those two functions disagree,
  which would be a `unit_conversion.py` bug, out of this slice.
- `backend.py:3359-3373` — the `IntegrityError` commit-conflict fallback path; the
  advisory lock (mutation-verified elsewhere in this suite) already prevents the race
  this path defends against in practice.
- `inventory_wastage_quantity.py:21,52,55-56,75` — dead/unreachable code
  (`quantize_wastage_quantity` has no caller in `app/`) and signed-zero/precision-overflow
  edge cases narrower than the `nan`/`Infinity`/`1e19` cases already covered.
- `record_wastage` still lacks a pure **unit**-level (non-e2e) test for its own
  "not found or access denied" branch — currently only proven by the e2e cross-tenant
  probe (`tests/e2e/test_tenant_isolation.py::test_org_b_cannot_waste_org_a_inventory_item`).
  Acceptable per this codebase's own convention (the e2e-playwright skill mandates the
  cross-tenant probe live at that layer), but noted for a future coverage pass.
- `WastageRepository.create_wastage_record` has no production caller (only
  `tests/factories.py` uses it for fixture seeding) — not a route, not a finding, flagged
  for awareness in the spec's Out of scope.

## Full suite
```
pytest tests/ -q   (ENVIRONMENT unset)
1395 passed, 31 skipped, 304 warnings in 609.10s
```
No regressions anywhere in the repo from this review's changes.
