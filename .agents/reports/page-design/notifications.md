# PAGE DESIGN — notifications — 2026-10-27
plan: docs/notifications-redesign-plan.md
research: 3 comparable products (Vanta My Work, Stripe Actions required, GitHub notifications), 2 craft references (Linear Inbox, Stripe), 2 pattern sources (Carbon notification pattern; overflow/row-action and hover-reveal accessibility guidance)
directions: 3 (Work queue, Inbox and detail, By area); chosen: Style 1 (Work queue), 2026-10-27
passes: 4   defects fixed: 14   bugs fixed: Dispose did nothing on a full load; actions landed on generic pages; ids shown for unnamed lots and sales; stale cached findings after a deploy
screenshots: ~/.cache/workflow-engine-ui-shots/notifications/{00-before,01,02,03,04}
tests: 8 browser tests added (the CONCEPT ONLY group became one layout check), 5 unit tests added, 3 changed (excise link, cache trimming, new-org notifications)
follow-ups: shared (not per-browser) done state; deep link to one sale line on Batch matching
verdict: patched
