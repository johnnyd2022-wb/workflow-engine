# TEST EVALUATION — 2026-10-11

Batch: new `tests/e2e/test_sales_design.py` (19 parametrized cases) and changed `test_sales_overview_keeps_figures_in_card_and_actions_in_header` in `tests/e2e/test_workspace_overviews.py` (3 viewport cases). Independent grader; app and tests were never edited in the author checkout.

## Static checks

- Concepts/header/overflow (12 cases): asserts real rendered headings, title/tab/body order, both actions, Style 1 paired-card geometry, distinct widget order for Styles 2/3, no sideways scroll, and canvas backing width divided by device pixel ratio. The initial CSS-width-only assertion was corrected during review.
- One initial load: observes browser network requests and demands exactly one overview request after network idle. No mocked call-count tautology.
- Keyboard task expansion/operator filter: native Enter and Space check expanded state and details visibility; selecting an actual operator hides the unmatched task and clearing restores it. The name now matches both exercised paths.
- Expanded task action: native Enter on its inner action must navigate to `/crm/tasks`; catches the nested key-handler regression identified in code review.
- Error handling (401/403/503): asserts unavailable UI and hidden figures. Permission/session errors have no retry; recovery after 503 must reveal figures and hide error UI. Mocks represent input statuses; assertions concern DOM behavior rather than asserting mocks back to themselves.
- Header Add widget/saved order: opens the actual modal, verifies stored Top Customers order in actual rendered DOM, changes concept without overwriting saved order, and follows boosted Customers → Overview return with remembered concept and order.
- Changed shared layout cases: preserve figure containment and overflow checks; replace obsolete equal-width body-actions assertions with explicit shared-header placement, action order and paired Style 1 geometry. This is the user's !515 alignment request, documented in the design plan, not silent weakening. The stale test name was renamed during review.

No added skips, xfails, broad status-code acceptance or catch-and-ignore assertions. No fixture value is asserted back as a supposed calculation result. Revenue arithmetic, invoice exports and backend tenant isolation are not claimed by these presentation tests; backend code is unchanged.

## Independent mutation probes

Probes ran in a disposable copy under `~/.cache/sales-grader-isolated`, with a symlink to the author's existing venv; no .env was present/copied. Local test database and real TLS/browser fixtures; no production environment. The copy was removed after restoration and execution.

1. Baseline targeted checks: **6 passed**.
2. Restore duplicate `x-init`, remove task keyboard handlers, suppress load-error state, and ignore saved-order priority: **6 failed** (single-init, keyboard/filter, all three initial-error statuses, saved layout).
3. Restore author code, then remove inner-action `@keydown.stop` and force canvas width to 600: **4 failed** (native inner-action navigation, backing-width checks at 1920 for all 3 styles).
4. Restore latest author app/test snapshot and rerun targeted tests plus the changed shared Sales cases: **13 passed, 35 deselected**, no skips. This includes the 7 behavior cases, all 3 sampled wide concepts, and all 3 changed shared layouts. The later test-name-only rename changes no assertions or behavior.

Log artifacts: `~/.cache/sales-grader-baseline.log`, `sales-grader-mutated.log`, `sales-grader-mutated-2.log`, `sales-grader-restored.log`. Local fixture teardown warnings concern an existing SQLAlchemy table-cycle sort, not assertion failures.

Findings: initial canvas assertion and missing nested-action navigation coverage corrected; shared test name corrected. No unresolved validity finding. Screenshot-specific widget creation/resize/drag, dark appearance and quiet-data checks remain the author's browser-verification responsibility and are not invented as assertions in this batch.

Verdict: **valid**.
