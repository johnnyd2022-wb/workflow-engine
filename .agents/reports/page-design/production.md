# PAGE DESIGN — production overview — 2026-10-11
plan: docs/production-redesign-plan.md
research: 4 comparable products (Katana Make screen, Breww production dashboard, Odoo 17 Shop Floor and work orders, MRPeasy), 3 craft references (Linear board and list, Tulip floor dashboards, Home from !512), 1 pattern source (Shopify Polaris index table and resource index)
directions: 3 (Board, Line, Worklist) behind ?style=1|2|3; Style 1 is Home's board; the user picks one and the others are deleted
passes: 4   defects fixed: 9   bugs fixed: a cancelled overview request logged as a failure; a workflow with no steps left a gap where progress goes; seven batches under way but six shown
screenshots: ~/.cache/workflow-engine-ui-shots/prod/00-before, 01 to 03, 04-final (style1-*, style2-*, style3-*, use-*)
tests: 8 test functions added (tests/e2e/test_production_overview.py, 3 of them concept-only), 1 changed (tests/e2e/test_workspace_overviews.py: it pinned the old stack and a click-to-open batch)
follow-ups: more than 20 batches; a batch number in the overview response; the main action after setup; keyboard order in the stacked layout; the tab strip sits 32px lower after an in-app visit (predates this)
verdict: findings-open (a style has to be chosen before this can merge)
