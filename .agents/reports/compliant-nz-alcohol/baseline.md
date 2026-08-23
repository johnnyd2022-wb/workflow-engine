# BASELINE: compliant-nz-alcohol
date: 2026-08-23
branch: mc/review-feature-20260823-004826-9b76cb
git status: clean

## Test run
```
uv run pytest tests/test_compliant_catalog.py tests/test_compliant_routes.py tests/test_compliant_frontend_assets.py -v
33 passed, 12 warnings in 7.33s
```
No pre-existing failures.

## Scope note
`compliant-platform` (the surrounding platform slice: profile/records/reports routes,
`compliant_bp.py`, dashboard) was reviewed 2026-08-22 (`.agents/reports/compliant-platform/
review.md`) and its spec explicitly notes: "AlcoholProductProfile ... and its
`/api/compliant/alcohol-products` routes live physically in the platform's models/routes
files, but conceptually belong to the `compliant-nz-alcohol` module per the feature index"
and were audited there (security, e2e, coverage, observability all patched/clean), plus the
`compliant_nz_alcohol_001` migration was already round-tripped clean by that review's
migration-safety stage.

This review therefore scopes tightly to the module-specific surface *not* already covered:
`app/features/compliant/modules/nz_alcohol/{catalogue,councils,module}.py` (framework
catalogue, council catalogue, applicability rules, CoreChecksRunner registration) and the
NZ-alcohol-specific branches of `service.py` (`evaluate()`'s framework-applicability
filtering, `framework_for_profile()` binding). Re-litigating the platform-layer routes,
CSV export, or profile/record CRUD already patched yesterday would violate the "don't
re-audit a finding a human already accepted" rule — `finding_history.py` is consulted in
Step 4 for exactly this reason.
