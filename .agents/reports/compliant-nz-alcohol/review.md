# REVIEW: compliant-nz-alcohol
date: 2026-08-23
branch: mc/review-feature-20260823-004826-9b76cb
baseline: tests green (33 passed, 0 pre-existing failures), working tree clean
verdict: **patched**

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| migration-safety | reused (clean) | 0 — `compliant_nz_alcohol_001` unchanged since compliant-platform's 2026-08-22 base→head→base→head round-trip | [compliant-platform/migration-safety.md](../compliant-platform/migration-safety.md) |
| security-audit | findings-open → patched | 2 | [security-audit.md](security-audit.md) |
| e2e-playwright | patched | 5 new tests (coverage gap-fill, no defects) | [e2e-playwright.md](e2e-playwright.md) |
| unit coverage | patched | `modules/nz_alcohol/` 83%→100% (`module.py` 56%→100%) | (see body below) |
| test-evaluator | mixed → patched | 2 real test-strictness gaps + 1 already-covered-elsewhere | [test-evaluator.md](test-evaluator.md) |
| perf-guardrails | reused (clean) | 0 — no routes of its own; `/api/compliant/alcohol-products` already measured in compliant-platform's 2026-08-22 run | [compliant-platform/perf-guardrails.md](../compliant-platform/perf-guardrails.md) |
| observability | clean, no changes needed | 0 — no auth/tenant boundary of its own; `access_denied` tracing already covers the shared routes (compliant-platform, 2026-08-22) | n/a |
| ci-gate | clean | 0 — ruff check/format pass on all touched files | (see body below) |

Execution mode: `herdr-tabs` per preflight. `security-audit` and `e2e-playwright` ran in
the declared parallel group (`security-audit·compliant-nz-alcohol` / Claude Sonnet,
`e2e-playwright·compliant-nz-alcohol` / Claude Sonnet), each in its own Herdr tab against
this worktree. `test-evaluator` ran as a Codex read-only stage
(`test-evaluator·compliant-nz-alcohol`); its sandbox correctly rejected writing its own
report file per `.agents/verification-chain.md` §5 — the orchestrator captured its
verbatim final message and transcribed `test-evaluator.md` on its behalf.

No spec existed for compliant-nz-alcohol before this review (`reviewed: never`); one was
reconstructed from the code, scoped tightly to the module-specific surface (catalogue,
councils, CoreChecksRunner registration, framework-applicability logic) since the
surrounding `compliant-platform` slice was already reviewed and patched the day before
(`.agents/reports/compliant-platform/review.md`, 2026-08-22) — re-auditing its routes, CSV
export, or the `compliant_nz_alcohol_001` migration here would have been circular against
work a human already accepted. User confirmed this scope before the chain ran.

Two real defects found and fixed, plus two real test-strictness gaps found and closed by
an independent grader.

## What was wrong, and what now stops it recurring

### F1 — `abv_percent: "nan"` crashed product creation with an unhandled 500
`app/features/compliant/routes/api_routes.py:144-147` (pre-fix). `Decimal(str("nan"))`
constructs without raising — NaN is a valid Decimal literal — so `_decimal()`'s
`except InvalidOperation` guard never fired. The crash happened one line later, at the
range comparison `Decimal("0") < abv_percent <= Decimal("100")`, which sat outside the
`try/except ValueError` block that only wrapped the construction. `ADMIN`-only,
self-inflicted, no cross-tenant or auth-bypass path — an input-validation robustness gap,
not a security exposure. Found by the security-audit stage via manual review (scanners
came back clean) and confirmed with a direct `Decimal` repro.
**Fix**: added an `abv_percent.is_finite()` short-circuit before the range comparison, and
moved the comparison inside the `try` block alongside `except (ValueError,
InvalidOperation)` as defense in depth. Stops recurring: `test_create_alcohol_product_
rejects_invalid_abv` extended with `nan`/`-nan`/`Infinity` parametrize cases (`tests/e2e/
compliant-platform/test_alcohol_products_flow.py`).

### F2 — an overlong `customs_product_code` crashed product creation with an unhandled 500
Same route, `api_routes.py:156` (pre-fix). The column is `String(100)`
(`alcohol_product_profile.py:24`) but the route never bounded the field before insert —
unlike `inventory_name`, which is checked at line 141. An overlong value raised
`sqlalchemy.exc.DataError` (Postgres `StringDataRightTruncation`), which is **not** a
subclass of `IntegrityError` (confirmed via MRO check), so it fell through the existing
`except IntegrityError` handler uncaught. Same severity profile as F1: `ADMIN`-only,
self-inflicted.
**Fix**: added a `len(customs_product_code) > 100` check returning 400, mirroring the
existing `inventory_name` pattern. Stops recurring: new
`test_create_alcohol_product_rejects_overlong_customs_product_code`.

Both findings are the same underlying pattern (validate happy-path shape, not edge-case
input, before handing data to a DB layer that can raise a non-`IntegrityError` exception).
`scripts/finding_history.py` recorded both `confirmed` (by security-audit) then `fixed`
(by this review) — sigs in `.agents/history/findings.jsonl`.

### Test-strictness gaps closed (found by test-evaluator, an independent Codex grader)
The e2e-playwright stage's 5 new tests and this review's 3 new `run_check()` tests were
graded before being accepted. The grader ran a standalone mutation harness (pytest itself
couldn't run inside its sandbox — the documented `host.docker.internal` DNS trap from a
misconfigured environment, not a test defect) and found two tests that would stay green
under a real regression:

- `test_trade_waste_framework_reflects_selected_council` checked `source_url`/`version`/
  `source_title` match the selected council but never checked `controls` — a mutation
  dropping the controls overlay (while still copying the metadata fields) passed
  unnoticed. **Fixed**: added an assertion that the response's control-id set matches the
  council catalogue's, plus a cross-check that Hamilton's and Dunedin's control sets
  genuinely differ (proving the overlay swaps controls per council, not a shared base set
  that happens to overlap).
- `test_run_check_flags_and_counts_attention_frameworks` created exactly one
  attention-state framework, so a hardcoded `"1 NZ Alcohol compliance framework(s)..."`
  message (ignoring the real count) would have passed. **Fixed**: the test now creates two
  attention-state frameworks (`customs-alcohol`, `np3-food-control`) and asserts the
  message says "2", not "1".

A third, lower-severity note (the new audit-pack-rejection E2E test proves the 400 but not
the AC's "before any database query" ordering claim) turned out to already be covered:
`test_report_for_inapplicable_framework_skips_the_reconciliation_scan`
(`tests/test_compliant_routes.py`, pre-existing from the compliant-platform review) patches
`ComplianceService.customs_reconciliation` to raise and asserts the 400 still happens — the
real cost-avoidance concern (the expensive org-wide movement scan) is provably not run.
No further test added for this.

## Coverage
`app/features/compliant/modules/nz_alcohol/` (the module-specific scope): 83% → **100%**.
`catalogue.py`/`councils.py` were already at 100% (pure, well-tested contract functions);
`module.py`'s `run_check()` body was completely untested (0% of its 8 statements) —
closed with 3 new tests covering not-enrolled, no-attention, and multi-framework-attention
cases, the last of which is also what caught the hardcoded-count gap above.
`app/features/compliant/service.py`'s NZ-alcohol branches (`evaluate()`'s applicability
filtering, `framework_for_profile()`, `build_audit_pack()`'s applicability gate) were
already covered at the unit level by `tests/test_compliant_catalog.py` before this review
started; the 5 new E2E tests add browser-level, cross-request proof that the same behavior
holds end-to-end (a setting change on org A demonstrably flips which frameworks org A's
next request sees), which `test_compliant_catalog.py`'s pure-function unit tests alone
don't establish.

## Disclosed, not chased
- `service.py` still imports NZ-alcohol catalogue functions directly (`evaluate()`,
  `build_audit_pack()`) rather than through a formal plugin interface — documented,
  deliberate debt in the feature index ("current module evaluator; to split when a second
  module lands"), out of this review's scope per its own spec.
- `catalogue.py`/`councils.py` pure-function edge cases not directly unit-tested beyond
  what `test_compliant_catalog.py` already covers (e.g. `framework_by_slug(None)`,
  `council_catalogue(None)`) were checked manually by the security-audit stage
  ("Attempted but clean" section) and confirmed correct; not independently re-tested here
  since they're already exercised transitively by the E2E applicability tests and the
  existing catalogue contract tests.

## Verification
```
uv run pytest tests/test_compliant_catalog.py tests/test_compliant_routes.py \
  tests/test_compliant_frontend_assets.py tests/e2e/compliant-platform/ -q
97 passed, 16 warnings in 157.55s (0:02:37)

uv run pytest tests/test_compliant_catalog.py tests/test_compliant_routes.py \
  --cov=app/features/compliant/modules/nz_alcohol --cov-report=term-missing -q
TOTAL   47   0   100%
33 passed

uv run ruff check <touched files>       # All checks passed!
uv run ruff format --check <touched files>   # 4 files already formatted
```

## Recommendation
Ship. Two real defects fixed (both input-validation robustness, not tenant/auth
exposure), module-specific coverage taken from 83% to 100%, and the new/changed tests
independently graded by a separate-engine adversarial reviewer with two real
test-strictness gaps found and closed rather than accepted at face value.
