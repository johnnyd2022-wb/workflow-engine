# Sales page design — 2026-10-11

Verdict: patched. Style 1 Board selected and prepared for review.

Scope: `/crm` overview, based on main ba166c7b and the settled Production !515 title/tabs/actions. Style 1 Board is the closest match; Style 2 Revenue review leads with financial analysis; Style 3 Sales desk brings follow-ups forward. Research, tradeoffs and deliberate saved-layout behavior are in `docs/sales-redesign-plan.md`.

## Observations and fixes

Baseline showed duplicate Alpine initialization, unavailable data appearing as zero sales, mouse-only task expansion, weak dark chart/task contrast, oversized operator filtering and crowded phone chart labels. The visual loop also found shared selector specificity overriding grid/primary/chooser styles, doubled card padding, currency wrapping and canvas backing widths stale after visibility/layout changes. All were corrected within Sales scope. Independent review found an inner task-action Enter handler swallowed by the parent; it now navigates with native keyboard input, and disconnected components cannot re-observe chart parents.

## Screenshot loop

Cache root: `~/.cache/workflow-engine-ui-shots/sales-design`. Baseline `00-before` has six inspected shots including Home/Suppliers. Round 01: 42 inspected PNGs, visual issues corrected. Round 02: 55 inspected PNGs; remaining compact-phone task prominence corrected. Round 03: all 60 inspected PNGs, empty defect list. All six scenario functions completed successfully; the edit-only rerun corrected harness drag/selector/row-count assertions without changing application code.

Final covers all three styles, busy and quiet desktop/laptop/phone/wall/dark; loading; API error/retry; keyboard expansion; operator no-results/clear; invoice details; empty date range; actual custom-widget save/remove; boosted Customers return; actual resize/lock and HTML5 drag/drop events; actual Top N selection. Custom saved order intentionally takes precedence over concept suggestions.

The seeded unmapped-product state intentionally shows zero mapped products beside all-authorised-sales revenue. Phone full-page captures place the existing fixed bottom navigation at the initial viewport boundary; this is a capture artifact shared with the baseline.

## Validation

- 125 passed: Sales concepts/behavior, workspace overviews, Production layout, page render and boosted navigation suites on UTC.
- New Sales suite: 19 passed on each of three consecutive runs.
- Old-code proof: five targeted cases fail on the original template/script (duplicate init, keyboard and 401/403/503 unavailable states).
- Independent reviewer: clean HTML/JS; valid tests. Ten mutation failures then 13 restored passes. See `sales-review.md` and `sales-test-evaluation.md`.
- Ruff app/harness/tests and format checks, node syntax, custom Semgrep rules, git diff whitespace checks passed.

The shared Sales layout test was intentionally updated from body action rows to the settled header slot and directional primary ordering; figure containment and overflow checks remain. API/calculation/export/tenant-isolation behavior was not modified or re-certified by these UI checks. Existing modal focus and timezone/month-end behavior remain separate follow-ups.

## Shipping

All six baseline and 60 concept images were uploaded for the draft MR. Only each run's
throwaway UI Shots organisation is purged.

## Winner selection

The founder selected Style 1 Board and asked for Sales Trend to match the height of At a
glance. The chooser, query/session selection, Style 2/3 CSS and concept sorting were removed.
At 1280px and wider, a locked default trend now stretches within the same grid row as At a
glance; unlocking it preserves the existing full-width editing flow and saved layout.

A new browser regression measures the two bounding boxes in busy and quiet data, under
light and dark themes, and requires a sub-two-pixel height difference. It then unlocks the
trend and verifies that it moves below At a glance at full width. The winner-only Sales suite
passes all 15 cases.

Final winner pass: 20 of 20 screenshots inspected, covering busy/quiet desktop, laptop,
phone, wall and dark; loading, 503/retry, task expansion, operator filtering, invoice detail,
date-empty, custom widget, boosted return, layout editing and Top N. Equal-height pairing is
visually present in busy and quiet desktop/dark views. The final defect list is empty.
