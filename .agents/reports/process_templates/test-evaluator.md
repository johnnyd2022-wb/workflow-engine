# test-evaluator — process_templates (round 1)

engine: codex (gpt-5.6-sol, effort high), `--sandbox read-only` via direct CLI
invoked_as: chain stage (called by new-feature) — read-only grader, no remediation performed
verdict: weakened (7 findings, all fixed — see round 2 for re-verification)

Report captured and written by the orchestrator on the grader's behalf per
`.agents/verification-chain.md` §5: the read-only sandbox correctly rejected the
grader's own attempt to write this file. Note: the sandbox could not resolve the
configured test-DB host, so 26/29 unit tests couldn't execute inside its environment
(3 DB-free tests did run and passed); grading of those 26 is source-level path-tracing
plus mutation reasoning, cross-checked against this run's own confirmed 29/29 unit +
8/8 e2e green results (recorded in earlier chain stages).

## Findings — all real, all fixed

1. **AC7 tenant-scoped test used the wrong repository method.**
   `test_ac7_copy_is_tenant_scoped` called `ProcessRepository.get_process_by_id`, but
   `GET /api/core/processes/<id>` (the actual route) calls `get_process_with_steps` —
   a different method whose org filter could regress without this test catching it.
   **Fix:** the in-org assertion now goes through the real HTTP route via
   `compliant_app_client`; the cross-org assertion now calls `get_process_with_steps`
   directly, matching the method the route actually uses.

2. **AC7 catalogue-immutability test ignored the PUT's own result.**
   `test_ac7_editing_copy_does_not_mutate_catalog` never checked the edit PUT
   succeeded — a 404 or silent no-op would still make "nothing changed" pass
   vacuously. **Fix:** asserts `put_resp.status_code == 200` and the returned name
   before checking the catalogue is untouched.

3. **AC4 only exercised the service layer, not the route layer its own claim names.**
   `test_ac4_new_capability_module_mapping_requires_no_route_or_service_change` called
   `list_catalog`/`get_template_detail` directly — proves the service is generic, not
   that the route layer above it is. **Fix:** added the same assertions via
   `compliant_app_client` against the real `/api/core/process-templates` and
   `/api/core/process-templates/<id>` endpoints.

4. **E2E family-filter test had no positive control.**
   `test_ac5_family_filter_narrows_the_card_grid` only asserted the Distillery card
   disappeared after filtering to Winery/Vineyard — would still pass if the filter
   simply cleared every card. **Fix:** added `expect(... "Grape intake" ...).to_be_visible()`
   to prove Winery cards survive the filter.

5. **Advisory tests (unit + e2e) compared against the production constant they were
   proving correct.** Importing `registry.TEMPLATE_CUSTOMISE_ADVISORY` as "expected"
   means a wording corruption moves expected and actual together — the test can never
   fail regardless of what the string says. **Fix:** both tests now compare against a
   literal, hardcoded copy of the current wording.

6. **AC11 analytics-event tests used `>= 1`, silently permitting duplicate emission.**
   A single GET emitting the event twice (a real bug class) would still pass.
   **Fix:** tightened both `test_ac11_list_call_emits_catalog_viewed` and
   `test_ac11_detail_call_emits_template_selected` to `== 1`.

7. **Unit AC13 wizard-resume test checked only `status_code == 200`,** which a
   route that always returns 200 regardless of `id` would also satisfy. **Fix:** added
   a negative control — a random, never-created process id against the same route
   404s (via the existing `_assert_flow_process_access` guard), so the 200 for the
   real copied process id is now paired with proof that *this specific id* is what
   made the difference.

## Confirmed valid without changes (per the grader)

- The AC9 sample_only pair: deleting the override breaks the main test; forcing every
  terminal output to WIP breaks the control test — the mechanism is genuinely proven,
  not just asserted.
- `_purge_org`'s delete ordering is correct for the rows it creates and does not mask
  a cross-org write; its docstring's "none cascade" phrasing was corrected for
  accuracy (an intra-table cascade exists but is irrelevant to this helper's own
  correctness) rather than the delete order itself, which needed no change.

## Re-verification

All 37 tests (29 unit + 8 e2e) green after every fix
(`uv run pytest tests/test_process_templates.py tests/e2e/process_templates/ -q`).
Round 2 of this grading stage re-checks these specific fixes — see
`.agents/reports/process_templates/test-evaluator-round2.md`.

VERDICT: weakened
