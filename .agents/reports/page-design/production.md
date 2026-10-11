# PAGE DESIGN — production overview — 2026-10-11
plan: docs/production-redesign-plan.md
research: 4 comparable products (Katana Make screen, Breww production dashboard, Odoo 17 Shop Floor and work orders, MRPeasy), 3 craft references (Linear board and list, Tulip floor dashboards, Home from !512), and for the page head: NN/g Tabs Used Right, Carbon, Appian, Apple HIG, Material 3 via SAP Fiori, Shopify page guidance, W3C clear-purpose pattern, Fluent 2
directions: round one Board, Line, Worklist (Board chosen); round two actions in the header, as a bar, beside the work (header chosen); round three three orders of title, tabs and buttons (none picked; led to research); round four five mock-ups A to E (A chosen, with green current-tab text and a full-width bar). All losers, switches and concept code are deleted.
passes: 18   defects fixed: 29   bugs fixed: a cancelled overview request logged as a failure (and the same on Inventory); a workflow with no steps left a gap where progress goes; seven batches under way but six shown
screenshots: ~/.cache/workflow-engine-ui-shots/prod/00-before, 01 to 15 (the four rounds), 16, 17, 18-final (desktop, rail, wall, laptop, tablet, phone, dark, page-*, use-*)
tests: 9 test functions in tests/e2e/test_production_overview.py (new); changed: tests/e2e/test_workspace_overviews.py (it pinned the old stack, the filled equal-width tabs above the title and a click-to-open batch)
follow-ups: Planner, Workflows and Inventory still repeat their tab's word as a title under the shared head; more than 20 batches; a batch number in the overview response; one untraced "AbortError" console log on some page when left mid-load
verdict: findings-open (the repeated titles on the other Production tabs are a known defect left for their own redesigns)
