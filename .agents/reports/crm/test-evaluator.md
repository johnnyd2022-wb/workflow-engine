<!-- Codex test-evaluator (gpt-5.6-sol, high, --sandbox read-only), pane w55:p3, round 1, 2026-10-18. Transcribed verbatim by the orchestrator (.agents/verification-chain.md §5). -->
# TEST EVALUATION — 2026-10-18

Batch: 24 added tests across five files. Result: 21 valid, 3 invalid.

## Blocking findings

1. [tests/test_crm.py:2063](tests/test_crm.py:2063) — `test_a_partly_failed_sync_says_it_did_not_finish` does
 not create a partial sync. Contacts return an empty list and invoices fail, leaving both synced counts at zero. Under [xero_sync_service.py:39](/home/johnny/event-factory/.local/worktrees/workflow-engine/fd35062c-96bf-46ab-b43f-cf220f652d97/b
b71aa65-9423-4aa8-96d0-78c7b1d34cd8/app/features/crm/services/xero_sync_service.py:39), `partial` is therefore false and the route takes the 502 path. The test also omits a status assertion, so it does not protect the required partial-success
200 behavior. Sync at least one record and assert status 200, retained counts, `ok: false`, and the displayable error. Resolved in round 2 (2026-10-18), still true on 2026-10-21: the test imports one contact, forces the invoice failure and asserts 200, `ok: false`, `contacts_synced == 1` and the error text (`tests/test_crm.py:2270`).

2. [tests/test_crm.py:1999](tests/test_crm.py:1999) — the control claims assignment to a colleague, but `user
` is the same account used by `app_client`. An implementation that only permits self-assignment would pass. Create a second active user in the same organisation and assign the task to that user. Resolved in round 2 (2026-10-18), still true on 2026-10-21: the test creates a distinct same-org colleague and assigns to them (`tests/test_crm.py:2201`).

3. [tests/test_crm.py:2116](tests/test_crm.py:2116) — the configuration-link test never proves the Sales user
 can access `/crm` and `/crm/matching`. If both source pages regress to 403 or an empty response, the absence checks pass for the wrong reason. Assert status 200 and a page-specific marker before asserting the links are absent. Resolved in round 2 (2026-10-18), still true on 2026-10-21: each source page must return 200 and contain its marker first (`tests/test_crm.py:2341`).

## Per-test grading

Valid:

- Both configuration-page JS tests.
- Both customer-detail JS tests.
- All three invoice-route failure tests.
- The three negative assignee tests.
- Both customer-status filter tests.
- The outright-failure and clean-sync API tests.
- The first Xero-button permission test and the member control.
- Both contact resend tests.
- All three invoice validation/idempotency tests.

Invalid: the three tests identified above. No assertions were deleted or widened, and no skips or xfails were introduced.

## Verification

- Current Node suites passed.
- Python execution was prevented by the read-only environment having no writable temporary directory; the supplied origin-main run was used as runtime evidence.
- The origin-main app diff supports the red-first claims for the genuine bug tests.
- The claim that all three `TestCustomersPageXeroButtons` tests failed before the fix cannot be correct: `test_someone_who_manages_sales_still_gets_them` is explicitly a control, and the unguarded origin-main templates already expose those but
tons and links to a member. It should pass before and after the fix.
- A read-only origin-main probe also confirmed the hidden-form repro fails while `Edit details still fills the form from the customer` passes as a control.
- No mutation edits were made; `app/`, `tests/`, and `scripts/` remain untouched.

VERDICT: invalid

---
<!-- Round 2, pane w55:p4, transcribed verbatim. -->
# TEST EVALUATION — 2026-10-18

Batch: Round-2 re-grade of exactly three tests in `tests/test_crm.py`.

## Static grading

- `tests/test_crm.py:2068` — `test_a_partly_failed_sync_says_it_did_not_finish`: valid. It now imports one contact, forces invoice failure, and asserts status 200, `ok: false`, `contacts_synced == 1`, and displayable error text.
- `tests/test_crm.py:1999` — `test_a_task_can_still_be_assigned_to_someone_in_the_organisation`: valid. It creates a distinct active same-org colleague and verifies successful assignment to that colleague, so a self-assignment-only implementat
ion would fail.
- `tests/test_crm.py:2139` — `test_a_sales_user_is_not_sent_to_the_configuration_page_they_cannot_open`: valid. Each source page must return 200 and contain a page-specific marker before the forbidden-link absence is checked.

No widened/deleted assertions, tautologies, skips, or xfails were introduced.

## Scope integrity

`git show HEAD -- tests/test_crm.py` changes only these three test bodies plus the partial-sync helper extension. The helper’s default remains an empty reply, preserving the other two sync tests. No other test file changed in the latest commit
; the other 21 round-1-valid tests are unchanged.

The correction is accepted: `test_someone_who_manages_sales_still_gets_them` remains an unchanged control and is not treated as a bug test.

## Falsifiability and execution

The supplied origin/main evidence shows both changed bug tests fail before their fixes. The assignee control now directly distinguishes colleague assignment from self-only assignment.

No source mutation was performed because this stage is read-only. A targeted current-branch run was attempted; all three stopped during fixture setup because the sandbox could not resolve the configured test-database host. This is an environme
nt setup error, not contradictory test evidence.

Findings: none.

VERDICT: valid
