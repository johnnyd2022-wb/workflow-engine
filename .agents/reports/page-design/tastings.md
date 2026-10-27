# PAGE DESIGN — Tastings in Tasks — 2026-10-27

plan: docs/tastings-redesign-plan.md
research: original3 comparables/2 craft/1 pattern source plus refinement HubSpot, Salesforce, Vinsight, Linear, Todoist and NN/g; primary NZ domain basis retained in plan
direction chosen: founder requested Tasks integration, superseding standalone Agenda/Week/Preparation concepts. Existing Tasks Board/List/Week are all supported views; no new style pick is pending.
passes: original01–06; refinement07–09. All45 PNGs from07, all45 from08, and all47 from final09 were opened/read. Final09 scenarios succeeded and defect list is empty.
screenshots: ~/.cache/workflow-engine-ui-shots/tastings/09;47 final images uploaded into MR evidence; no PNGs tracked.

One New task entry exposes Type. Ordinary types use the small existing drawer. Selecting Tasting carries title, date, rep, customer and notes into specialized details with no preliminary save; toggling back retains both common and tasting-specific draft values. Cards open detail in the same workspace. Tasting stock is secondary and preserves reusable partial bottles separately from Library.

Refinement corrections: embedded dialog theme inheritance; phone filters sharing a row; visible in-dialog pagination error/retry; restored customer/rep options for selections outside the ordinary initial list. New browser regressions cover each functional defect. Final screenshots add pagination failure and recovery while keeping all earlier busy/quiet/filtered-empty/dark/phone/wall/editor/detail/stock/loading/error and sibling states. Interactions include search/clear, type/filter changes, open/close, save, stock reuse and boosted leave/return.

Validation:43 combined browser cases passed (27 Tastings,16 existing Tasks);93 shared browser regressions passed. Independent HTML/JS clean and test evaluator valid. Repeat runs and exact-head CI are recorded in tasks-verification.md/MR. Seed cleanup is required before final handoff; MR readiness waits for green CI.

Remaining product limits: recurrence, POS/offline integrations, completed-outcome amendment and return-to-bond are outside this feature. No open style decision. The earlier six-pass design history is retained below for traceability.

verdict: patched (selected UI finalized; MR transition follows exact-head CI)

---

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
