# Sales winner review — 2026-10-12

Scope: independent HTML/JS/CSS and test-evaluator review of the selected Board cleanup, including the locked Sales Trend/At a glance height contract. Reviewed current uncommitted diff against `d72fb955` without editing shared app/tests.

**Code verdict: clean. Test verdict: valid. No actionable findings.**

The template deletes the chooser/style binding and renders `widgetLayout` directly. JavaScript removes style query/session preferences, concept-specific order and the now-unused custom-layout flag; saved widget order, size, locking, drag/resize, Add widget, chart resize/theme observers and teardown remain intact. Searches find no leftover preview state/selectors in the CRM frontend. Shared section title/actions remain unchanged. CSS retains page-scoped Board rules and deletes losing layouts. At the wide breakpoint, only At a glance and the locked trend stretch to their common row height; unlocking restores the trend's saved full-column sizing without imposing equal-height treatment on other widgets.

Changed-test grade: four winning viewport cases retain title/regions/destinations/chart sizing/overflow and wide Board position assertions. Eight losing-style viewport cases and loser-specific widget ordering checks were deleted because those concepts were explicitly removed. Saved-layout/Add widget/navigation assertions remain; concept-switch-only assertions are removed. Four new busy/quiet × light/dark cases measure actual DOM position and card height, then unlock the trend and assert its move below the figures and wider span. Expectations do not call the renderer or reproduce the CSS calculation. No skips, swallowed assertions, tautologies or unexplained widening found.

Independent isolated snapshot: `/tmp/sales-winner-evaluator`, direct virtualenv Python with no editable-metadata changes.

- Changed winner viewport, height, and saved-layout navigation tests: **9 passed in 29.47s**, `/tmp/sales-winner-evaluator-green.log`.
- Kept final tests and replaced only isolated template/script/CSS with pre-cleanup `d72fb955`: height contract **4 failed in 14.99s**, `/tmp/sales-winner-evaluator-old.log`. All four failures were the height assertion: busy cards 447.09 versus 379.23px; quiet cards 324.38 versus 171.92px, in both themes.
- Restored exact final assets: all four height cases **4 passed in 14.03s**, `/tmp/sales-winner-evaluator-restored.log`.

Restored asset/test SHA-256 values match the shared worktree. No shared source/test mutation; only this report is written by the reviewer.

Coverage limits: the test permits less than 2px height difference for browser rounding; it verifies paired geometry at 1440px, while winner viewport tests cover 390/1024/1440/1920. Browser runtime here uses Chromium. Removal of legacy style-query/storage mechanics is statically verified; this batch does not contain a separate legacy-preference browser regression. The saved-layout return test asserts navigation and retained order but has no same-window sentinel, so it does not independently reject a full-navigation substitute. Financial calculations/backend permissions were not modified and are not re-certified by these layout tests. Final screenshots and broad unchanged checks are the orchestrator's separate evidence.
