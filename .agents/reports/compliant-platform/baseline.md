# BASELINE: compliant-platform
date: 2026-08-22
spec: .agents/specs/compliant-platform.md (status: reconstructed, user-confirmed)

## git status
Clean at start (only new untracked file: .agents/specs/compliant-platform.md).

## Test run
`uv run pytest tests/test_compliant_routes.py -v` (ENVIRONMENT unset, per CLAUDE.md)

```
5 passed, 5 warnings in 3.70s
```

All 5 pre-existing tests green. No pre-existing failures to report.

## Observations feeding into the chain
- Test file is thin (5 tests / 177 lines) for a feature with 9 routes across profile,
  alcohol-products, records, and reports — expect real coverage gaps at the unit-coverage
  stage.
- `routes/api_routes.py` has a CSV export (`GET /api/compliant/reports/<id>?format=csv`)
  writing user-supplied fields (record title, evidence_reference) into CSV cells with no
  formula-injection guard — the only CSV export in the app, no existing sanitizer to reuse.
  Flagging for the security-audit stage.
- `service.py` directly imports `NZ_ALCOHOL_FRAMEWORKS`/nz_alcohol catalogue functions —
  documented, deliberate debt per the feature index ("to split when a second module lands").
  Not a defect to patch in this review.

## Addendum: full-suite re-run after migration-safety incident
The migration-safety stage's launched pane went beyond its scoped task (see
`.agents/reports/compliant-platform/migration-safety.md`) and left the **shared** test DB
with a missing index (`ix_api_idempotency_keys_created_at`, unrelated table). Repaired
directly, then re-ran the full suite to confirm no other collateral drift:

```
uv run pytest tests/ -q
1 failed, 1610 passed, 31 skipped, 349 warnings in 735.01s
FAILED tests/e2e/process_templates/test_process_templates_flow.py::test_ac2_org_without_compliant_sees_empty_catalogue[chromium]
```

The single failure is `ssl.SSLError: UNEXPECTED_EOF_WHILE_READING` / `BrokenPipeError` inside
werkzeug's dev server during the test's live-server HTTP round trip — a connection-level
flake that never reached an assertion, in an unrelated slice (`process_templates`), re-run
in isolation and passed clean. Not a regression; not compliant-platform's to own (suite-warden
territory per the skill's own carve-out). Confirms the DB repair was complete and no other
schema drifted. CLAUDE.md's documented "730 passed, 30 skipped" is stale against the current
"1610 passed, 31 skipped" — a pre-existing docs-truth gap, unrelated to this review.
