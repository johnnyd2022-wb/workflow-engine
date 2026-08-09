# TEST EVALUATION — 2026-08-09

batch: tests/test_activity_log.py (87 tests, new file), tests/e2e/activity_log/ (12 tests
across conftest.py, test_story_panel.py, test_tenant_isolation.py, test_unhappy_paths.py,
test_activity_tab.py, new directory). Both files/directories are untracked (`??` in `git
status`) — no prior version to diff against, so the assertion-diff-widening check (skill
step 2.2) doesn't apply; every test is graded fresh.

## Runs (baseline, before any mutation)

- `env -u ENVIRONMENT uv run pytest tests/test_activity_log.py -q` → **87 passed**, 31 warnings
  (flask-limiter in-memory storage notice, unrelated to this slice).
- App server confirmed reachable at `https://localhost:8005/` (200).
- `env -u ENVIRONMENT uv run pytest tests/e2e/activity_log/ -q` → **12 passed**, 1 warning
  (same flask-limiter notice).

Both suites are green at rest, against the current working tree (which already contains the
uncommitted fix in `app/core/backend/backend.py`: `org_id` filter added to
`entity_summary_detail`'s `EntityEventSummary` query, and `try/except (TypeError, ValueError)`
wraps around `entity_story`'s and `entity_activity_feed`'s `limit`/`offset` parsing).

## Static checks

- **Asserts something real**: every test in both files ends in a concrete `assert` on
  response body/status/list contents, or a Playwright `expect(...)` on rendered DOM state.
  No test's only claim is "ran without raising" mislabelled as a real check. The two
  exceptions that are legitimately raise-only (`TestHumanSummaryFallback::test_ac16_unrecognized_event_type_does_not_raise`)
  are named exactly for what they prove ("does_not_raise"), matching skill step 2.1's carve-out.
- **Tautology hunt**: no test recomputes its expected value by calling the function under
  test — every parametrized case and every unit test compares against a literal string/dict
  written in the test. No `assert resp.status_code in (200, 302, 404)` catch-alls in the
  actual test assertions (the one `status_code in (200, 201)` at `test_activity_log.py:111`
  is in the shared `_make_client` login helper, not a test assertion itself — a login can
  legitimately return either code depending on flow, and a login failure there raises via
  the `assert` message rather than silently continuing). No `try/except: pass` wraps any
  assertion; the only `try/except Exception` in the file is `_purge_org`'s teardown cleanup
  (`test_activity_log.py:61-67`), which is fixture teardown, not test logic — it does not
  guard an assertion.
- **Sense check — org-scoped routes tested with the hostile org**: yes, throughout. Every
  cross-tenant claim (`TestAC7CrossTenantSummaryLeak`, `test_ac3_cross_tenant_entity_id_...`,
  `test_ac6_legacy_audit_merge_is_org_scoped`, `test_ac11_activity_feed_is_org_scoped`, all
  three e2e `test_tenant_isolation.py` tests) plants or creates real data in `other_org` /
  a second real browser session, then asserts the *caller's own* org's client gets nothing —
  not merely that the caller's org data is present. This is the real hostile-org shape the
  skill's step 2.4 asks for, not a same-org-only test dressed up as an isolation proof.
- **`TestAC7CrossTenantSummaryLeak::test_own_org_summary_still_returned` sanity check**
  (specifically requested): confirmed **not** a duplicate of the cross-tenant tests. It
  creates an item in the *caller's own* `org` (not `other_org`) and asserts the summary
  comes back non-empty with a real field (`add_method == "manual"`) — a distinct
  "fix doesn't overcorrect into always returning `{}`" claim, exercising the opposite branch
  (`org_id` matches) from the cross-tenant tests (`org_id` doesn't match). Both branches of
  the new `AND` filter are independently covered.
- **Minor redundancy, not a validity problem**: `TestAC8RecentEventsAlreadyOrgScoped::test_recent_events_excludes_other_orgs_events`
  (`test_activity_log.py:253-259`) issues the identical request as
  `TestAC7CrossTenantSummaryLeak::test_inventory_item_summary_not_visible_cross_tenant`
  (`test_activity_log.py:187-195`, which already asserts `body["recent_events"] == []` at
  line 195) and re-asserts the same field on the same response shape. Its docstring is
  explicit about why ("lock that in so a future edit can't regress both queries in the same
  handler at once") — this is deliberate belt-and-braces, not gaming, but it adds no new
  falsifiability beyond what AC7's own test already proves (the same mutation that breaks
  one breaks both — confirmed, see mutation spot-check #1 below, which failed the AC7 tests;
  I did not additionally re-run AC8 against that mutation since the code path is identical).
  Not a blocking finding.
- **Naming precision nit**: `tests/e2e/activity_log/test_story_panel.py::test_ac3_audit_history_panel_shows_empty_state_for_item_with_no_extra_events`
  (line 41) doesn't assert an empty state — it asserts `.to_have_count(1)` (exactly the
  creation event, no *extra* events). The docstring explains the nuance correctly ("this is
  a more accurate baseline than an 'empty state' assertion would be"), but the test's own
  *name* still says "shows_empty_state", which a reader skimming names only would read as
  "zero items render". The assertion itself is correct and falsifiable; only the name
  overpromises. Cosmetic, not a validity issue.

## Mutation spot-checks

All mutations made with `Edit`, verified with a scoped `pytest` run, then reverted with
`Edit` back to the exact original text. Final `git diff -- app/core/backend/backend.py`
confirmed byte-identical (same hash) to the pre-mutation diff after every probe; `git status
--porcelain` at the end of the session matches the session's starting status exactly (see
below).

1. **Security-critical — AC7 headline regression.** Reverted the fix at
   `app/core/backend/backend.py:5541-5545` (`entity_summary_detail`): dropped
   `EntityEventSummary.org_id == org_id` from the filter, restoring the original BOLA.
   - `tests/test_activity_log.py::TestAC7CrossTenantSummaryLeak` → **3 of 4 failed** exactly
     as expected: `test_inventory_item_summary_not_visible_cross_tenant`,
     `test_user_summary_pii_not_visible_cross_tenant`, `test_org_summary_not_visible_cross_tenant`
     all went red with the real leaked payload in the assertion diff (e.g. org B's full
     `{'add_method': 'manual', 'created_at': ..., ...}` inventory summary, and the planted
     user-PII/org-metadata dicts). `test_own_org_summary_still_returned` correctly stayed
     green (same-org path unaffected by this mutation) — confirms it is measuring a
     different branch, corroborating the sanity check above.
   - `tests/e2e/activity_log/test_tenant_isolation.py::test_ac7_entity_summary_not_visible_cross_tenant`
     → **failed**, with org B's real inventory summary (`add_method`, `created_at`,
     `quantity_history`, etc.) visible in the assertion diff. This confirms the dev server
     backing the e2e suite has debug/reload wired up and picks up in-place edits to
     `backend.py` — the e2e suite is not silently hitting stale code.
   - Reverted; `git diff` back to the original three-hunk fix, confirmed byte-identical.

2. **Large parametrized `_human_summary` test.** Mutated the `inventory_item.wasted` branch
   (`backend.py:5200-5207`): changed the rendered verb from `"wasted"` to `"discarded"`.
   - `tests/test_activity_log.py::test_human_summary_every_known_event_type` → **exactly the
     one parametrize case for `inventory_item.wasted` failed** (`assert 'wasted — spillage'
     in '1 kg discarded — spillage'`); the other 30 cases in the same parametrize block
     stayed green, confirming each case independently exercises its own event-type branch
     rather than one shared assertion papering over all 31.
   - Reverted.

3. **Diff-rows / smart-list-diff.** Mutated `_smart_list_diff_rows`'s field-comparison guard
   at `backend.py:5057` from `if b_val == a_val: continue` to `if b_val != a_val: continue`
   (inverted — now skips *changed* fields and reports *unchanged* ones).
   - `tests/test_activity_log.py::TestSmartListDiffRows` and `::TestBuildDiffRowsListDispatch`
     → **3 failed**: `test_item_field_changed_within_list` (expected 1 changed-field row, the
     mutation suppressed it), `test_identical_lists_produce_no_rows` (expected `[]`, the
     mutation now reports every unchanged field as if it changed), and
     `test_build_diff_rows_dispatches_list_of_dicts_to_smart_list_diff` (expected 1 row, got
     2). All three correctly caught the mutation from different angles.
   - Reverted.

4. **F2 regression — unhandled `int()` on limit/offset.** Removed the `try/except
   (TypeError, ValueError)` wrapper around `entity_story`'s `limit`/`offset` parsing
   (`backend.py:5365-5369`), restoring the bare `int()` calls that raised unhandled on
   non-numeric input.
   - `tests/test_activity_log.py::TestEntityStory::test_ac_gap_non_numeric_limit_returns_400_not_500`
     and `::test_ac_gap_non_numeric_offset_returns_400_not_500` → **both failed**, with the
     real `ValueError: invalid literal for int() with base 10: 'abc'` surfacing instead of a
     400 response.
   - `tests/e2e/activity_log/test_unhappy_paths.py::test_regression_non_numeric_limit_on_story_returns_400_not_500`
     → **failed** against the live dev server, logged as an actual `500` in the structured
     access log (`'status': 500, ... 'route': 'core.entity_story'`) with the same traceback.
   - Reverted.

All four probes: mutation in → red; revert → green (re-confirmed both full suites pass
after the last revert, see below). No probe left the tree dirty.

## Post-mutation full-suite re-run

- `tests/test_activity_log.py -q` → 87 passed (unchanged from baseline).
- `tests/e2e/activity_log/ -q` → 12 passed (unchanged from baseline).
- `git status --porcelain` after all probes: identical to the session's starting status
  (`M .agents/feature-index.md`, `M .agents/history/findings.jsonl`, `M
  .semgrep/rules/learned.yml`, `M app/core/backend/backend.py`, plus the four untracked
  paths) — `git diff -- app/core/backend/backend.py` hashes identical before and after.

## Findings

None that block. One deliberate, self-documented redundancy
(`TestAC8RecentEventsAlreadyOrgScoped::test_recent_events_excludes_other_orgs_events`
duplicates a sub-assertion already covered by `TestAC7CrossTenantSummaryLeak`) and one
naming-precision nit (`test_ac3_audit_history_panel_shows_empty_state_for_item_with_no_extra_events`
doesn't test an empty state, it tests count==1) — both cosmetic, neither weakens
falsifiability, neither is gaming. No tautologies, no catch-all status assertions guarding
real claims, no widened/deleted assertions (nothing to diff against — both files are new),
no unjustified skips/xfails (none present at all).

## Verdict

**valid** — every test in scope (87 + 12 = 99) asserts a real, falsifiable claim against
either the live app or its pure-function presentation layer; the four risk-ranked mutation
probes (cross-tenant BOLA fix, a diff-humanisation branch, list-diff field comparison, and
the int()-parse regression guard) all went red on mutation and green on revert, at both the
unit and e2e/live-server level for the security-critical case. `TestAC7CrossTenantSummaryLeak::test_own_org_summary_still_returned`
is confirmed to be a genuine, non-duplicate "fix doesn't overcorrect" check.
