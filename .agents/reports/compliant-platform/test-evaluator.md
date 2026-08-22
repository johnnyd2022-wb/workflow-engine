# TEST-EVALUATOR: compliant-platform
date: 2026-08-22
stage: test-evaluator (Codex, gpt-5.6-sol, effort high, `--sandbox read-only`). Its own
report write was correctly rejected by the sandbox (`.agents/verification-chain.md` §5 —
"A `--sandbox read-only` grader cannot write that file itself"); the orchestrator captured
its verbatim final message from the session transcript
(`~/.codex/sessions/2026/08/23/rollout-2026-08-23T01-37-22-*.jsonl`) and writes this report
on its behalf, then patched every finding below.

## Grader's verbatim final message

> Graded 57 cases: 52 valid, 5 invalid.
>
> Blocking findings:
>
> - `test_compliant_routes.py:194`: CSV test covers only `=` and `+`; removing `-`/`@`
>   protection stayed green.
> - `test_compliant_routes.py:248`: tests `ADD` only; admitting `ADJUSTMENT` incorrectly
>   stayed green.
> - `test_records_flow.py:25`: tests missing profile, not disabled profile. The source
>   currently accepts records for disabled profiles at `api_routes.py:238`, contrary to
>   the spec.
> - `test_records_flow.py:41`: claims ADMIN is unnecessary but uses `admin_page`; an ADMIN
>   gate would leave it green.
> - `test_reports_flow.py:21`: tests missing profile only; removing disabled-profile
>   enforcement would stay green.
>
> Required mutations for CSV identity, static endpoint collision, three reconciliation
> paths, and report tenant filtering all went red. Runtime mutations were restored; no
> source/test drift remains.
>
> VERDICT: mixed

## Findings and patches (orchestrator, this pass)

1. **Real source defect, not just a test gap**: `POST /api/compliant/records`
   (`api_routes.py:238`, was `if profile is None:`) accepted records against a profile that
   exists but is *disabled* — contrary to the spec's "Requires an existing **enabled**
   ComplianceProfile (409 otherwise)". Fixed: `if profile is None or not profile.enabled:`.
   Added `tests/e2e/compliant-platform/test_records_flow.py::
   test_create_record_requires_profile_to_be_enabled_not_merely_present` to pin it.
2. `test_compliant_routes.py::test_audit_pack_csv_export_neutralises_formula_injection`
   only exercised `=`/`+`; a narrowed `_csv_safe` prefix set would have stayed green.
   Added a direct, parametrized unit test —
   `test_csv_safe_prefixes_every_formula_trigger_character` over all six trigger
   characters (`=`, `+`, `-`, `@`, tab, CR) plus `test_csv_safe_leaves_ordinary_text_and_
   none_untouched` — rather than only widening the round-trip test, since a unit test of
   the helper itself is the more precise claim.
3. `test_customs_reconciliation_ignores_non_production_wastage_movement_types` only
   covered `ADD`; parametrized over `ADD` and `ADJUSTMENT` (the full non-production/
   wastage set in `InventoryMovementType`).
4. `test_reports_flow.py::test_create_report_requires_an_enabled_profile` had the same
   missing-vs-disabled gap as (1) on the report-creation path. `build_audit_pack`
   (`service.py`) already correctly checked `profile is None or not profile.enabled` — this
   was a test-strictness gap only, no source defect. Added
   `test_create_report_requires_profile_to_be_enabled_not_merely_present`.
5. `test_create_record_happy_path_does_not_require_admin` used `admin_page`, which cannot
   distinguish "no ADMIN gate" from "ADMIN gate present, and this caller happens to be
   ADMIN" — the actual role claim is proven by the adjacent
   `test_create_record_member_can_attest_without_admin_role` (uses a same-org MEMBER).
   Renamed to `test_create_record_happy_path_returns_full_record_shape` and reworded its
   docstring to claim only what it proves (response shape), rather than duplicate/weaken
   the role assertion.

## Verification after patching
```
uv run pytest tests/test_compliant_routes.py tests/e2e/compliant-platform -q
72 passed, 10 warnings in 129.76s (0:02:09)
```
(Was 62 before this pass — net +10 tests: the disabled-profile pin on both routes, the
`_csv_safe` unit tests, and the `ADJUSTMENT` parametrization case.)

## Not re-graded
The 5 fixes above were not sent back through a second independent grading pass (the
skill's circuit breaker is two full patch *rounds* before escalation; this was the single
round the findings arrived in, and the fixes are small, mechanical, and directly
traceable to each finding). `finding_history.py` records covering the CSV-injection and
static-endpoint fixes already exist from the security-audit/e2e-playwright stages; the
disabled-profile defect found here is recorded separately below.

VERDICT: mixed (post-patch: all blocking findings addressed, verified green)
