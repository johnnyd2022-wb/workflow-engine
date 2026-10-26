# PAGE DESIGN — Tastings — 2026-10-27

plan: docs/tastings-redesign-plan.md
research: 3 comparable products, 2 craft references, 1 pattern source; primary NZ domain references recorded in plan
directions: 3 (Agenda, Week, Preparation board); chosen: awaiting the pick
passes: 6; final06 all71 PNGs read, all scenarios successful, no remaining visual defects
screenshots: ~/.cache/workflow-engine-ui-shots/tastings/01 through06; final comparisons uploaded to draft MR

Observed corrections: house gutters/tokens in dark mode; centered dialogs; phone dialog padding; week4-column laptop/7-column wall/1-column phone; empty-state duplicate grids; phone time wrapping; people-search button sizing; wall1280px shell alignment; metadata wrapping in compact cards. Functional corrections: counted-unit min/step, HTMX double-submit, NZ day labels, restored-root initialization, independent stock/people search, and preserving selected fractional-volume units after a new stock search. The last defect has an observed old-source red/new-source green browser regression. Dispatch visibility now matches both required permissions, and error colour uses the theme token.

Every pass exercised search/filter clearing, detail open/close, plan edit/save and in-app leave/return. Final set adds lower phone form/detail controls, busy/quiet on phone/wall/dark, desktop/phone detail, loading/error/filtered-empty and two sibling pages. One template/script serves all options and backend accounting is shared. Final06 keeps Tastings under the shared Tasks primary destination, preserving the four-tab navigation rule. Screenshot seed was purged; no PNGs enter Git.

Tests: 20 new browser cases including9 temporary concept-width cases and5 subscribed performance measures; full UTC suite passed three consecutive times (integration1/2/3). Independent HTML/JS follow-up clean and test evaluator valid. Shared suites recorded in e2e report.

Follow-ups: select one layout, remove switch/losers/CONCEPT ONLY tests, rerun final screenshots/tests before making MR ready. Deliberate product limits in spec/plan remain visible in MR.

verdict: findings-open (awaiting style choice only; no open implementation finding)
