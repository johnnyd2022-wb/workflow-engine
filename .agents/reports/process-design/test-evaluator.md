# TEST EVALUATION — 2026-08-02

batch:
- tests/test_process_design.py (59 tests, unit/Flask test client)
- tests/e2e/test_process_docs_flow.py (17 tests, Playwright)
- tests/e2e/test_process_steps_flow.py (28 tests, Playwright)
- tests/e2e/test_process_wizard_flow.py (24 tests, Playwright)
Total: 128 new tests, all untracked (new files) on branch `review/process-design`.

## Static checks

- Every test asserts a concrete outcome (status code, response shape, DB row
  count/presence, or persisted value) — no bare "did not raise" smoke tests found.
- No widened/deleted assertions to review (all files are net-new, not edited).
- No unjustified `skip`/`xfail`/`quarantine` markers.
- Tautology hunt: no test recomputes its expected value from the function under test,
  no mock-asserts-itself pattern, no catch-all status tuples
  (`status_code in (200, 302, 404)`). One deliberately loose assertion —
  `test_org_b_cannot_delete_org_a_doc` accepts 200 for a cross-tenant delete attempt
  by design, since `delete_document`'s not-found and cross-org-miss paths are the same
  idempotent-success code path as AC19 intends; the test's real assertion is that org
  A's doc survives untouched, which it checks explicitly. This is correctly reasoned,
  not a loosened test.
- Sense check: AC-named tests exercise the AC they claim (spot-checked AC2, AC6, AC9,
  AC12, AC15-19 against spec). Org-scoped endpoints are tested against the hostile org,
  not just the owner, in both e2e files (`two_tenants` fixture, real second org via
  `fresh_user`, not mocked).
- Brittleness: assertions target status code + response shape/field values, not exact
  error-message strings, with one narrow, justified exception —
  `test_ac9_reorder_to_non_grid_position_returns_500_not_400` also checks
  `"chk_steps_position_grid" in resp.text()`, which is appropriate here since the test's
  entire point is pinning a specific (undesirable) DB-constraint-leak shape, not generic
  validation.

## Mutations (falsifiability probes)

7 probes run, all app/repo edits made surgically, reverted via `git checkout --
<file>` after each, `git status --porcelain` verified clean before/after every probe
(confirmed no stray diffs on `app/core/backend/backend.py`,
`app/core/db/repositories/process_repo.py`,
`app/core/db/repositories/process_step_document_repo.py`,
`app/core/backend/process_docs/process_docs_validation.py`).

1. `test_ac2_create_process_requires_name` (unit) — removed the `if not name: 400`
   check in `create_process`. RED (500 IntegrityError instead of 400). Reverted.
2. `test_ac9_reorder_rejects_step_id_not_belonging_to_process` (unit) — removed only
   the `locked_ids` membership guard in `reorder_steps`; test stayed GREEN because a
   second, independent layer (`.filter(Step.id==x, Step.process_id==pid)` in the update
   query) still 404s. Re-probed by breaking **both** layers (locked_ids check + the
   process_id filter in the update query) → RED (200 instead of 404). Reverted. Not a
   test defect — genuine defense-in-depth in the code, correctly caught once both
   layers were removed — but worth noting the first-layer probe alone is a false
   negative if graded in isolation.
3. `test_validate_process_and_step_rejects_step_not_in_process` (unit) — removed the
   step-ownership check in `validate_process_and_step`. RED (`ok=True` instead of
   `False`). Reverted.
4. `test_org_b_cannot_download_org_a_doc` (e2e, cross-tenant, real second-org fixture)
   — removed the `org_id` filter in `ProcessStepDocumentRepository.get_by_id`. RED
   (org B downloaded org A's doc, status 200 instead of 404). This is the mandatory
   cross-tenant probe, confirmed to fail closed against a real second org, not mocked.
   Reverted.
5. `test_org_b_cannot_update_org_a_step` (e2e, cross-tenant) — removed the `org_id`
   filter in `ProcessRepository.get_process_by_id` (the shared IDOR guard used by
   update/delete/reorder). RED (org B's PUT succeeded, 200 instead of 404, name
   hijacked). Reverted.
6. `test_ac9_reorder_to_non_grid_position_returns_500_not_400` (e2e, documented known
   gap) — simulated the eventual fix by adding grid validation inline in
   `reorder_steps`. RED (endpoint now correctly 400s, but the test still asserts 500 —
   proving the test is pinned to *current* buggy behavior, not a tautology that would
   pass regardless of what the endpoint does). Reverted.
7. `test_ac12_return_to_bypass_payloads_fall_back_to_safe_default` (e2e, all 8
   parametrized payloads) — fully neutered `_safe_flow_return_to` to return its input
   unchanged. All 8 payload variants went RED. Reverted.

7/7 probes behaved correctly once the actual guarded behavior was broken (probe 2
needed a second pass because of redundant defense-in-depth, not because the test is
weak).

## Findings

- `test_ac9_reorder_rejects_step_id_not_belonging_to_process` :: protected by two
  redundant guards (locked_ids check + process_id filter in the update). Not a defect —
  belt-and-suspenders is a legitimate design — but if either guard is refactored away
  in isolation this test alone won't catch it; the equivalent e2e cross-process test
  (`test_ac9_reorder_rejects_step_from_a_different_process`) provides the same coverage
  independently, so overall AC9 protection is not actually thin. No action required.
- No dedicated unit-level 500-not-400 duplicate for AC9 exists in
  `test_process_design.py`; `test_ac9_reorder_normal_in_grid_reorder_succeeds_and_persists`
  explicitly documents in its docstring why it defers that assertion to the e2e file
  rather than duplicating it. This is intentional and correctly labeled, not a gap.

## Verdict

verdict: valid

All 128 tests in scope assert real, falsifiable claims. The three known-gap markers
(`test_ac9_reorder_to_non_grid_position_returns_500_not_400` plus its documented
deferral in the unit file) correctly pin current buggy behavior with clear "GAP (found
in review)" comments explaining what to change once patched — they do not normalize the
bug as correct. The mandatory cross-tenant probes (docs download, step update) fail
closed against a real second-org fixture. No tautologies, no brittle exact-string
assertions beyond one justified DB-constraint-leak pin, no widened/loosened assertions.
