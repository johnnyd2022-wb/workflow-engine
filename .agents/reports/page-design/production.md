# PAGE DESIGN — production overview — 2026-10-11
plan: docs/production-redesign-plan.md
research: 4 comparable products (Katana Make screen, Breww production dashboard, Odoo 17 Shop Floor and work orders, MRPeasy), 3 craft references (Linear board and list, Tulip floor dashboards, Home from !512), 1 pattern source (Shopify Polaris index table and resource index); round two's "taken from" row was written from memory when the search limit was hit and has since been removed from the plan
directions: round one Board, Line, Worklist (Board chosen); round two actions in the header, as a bar, beside the work (header chosen); round three, behind ?style=1|2|3 and ?cta=left|center: the header version, title above the tabs with the buttons under the tabs, and the buttons under the title, the last two left or centred
passes: 11   defects fixed: 19   bugs fixed: a cancelled overview request logged as a failure; a workflow with no steps left a gap where progress goes; seven batches under way but six shown
screenshots: ~/.cache/workflow-engine-ui-shots/prod/00-before, 01 to 04-final (round one), 05 to 09-final (round two), 10, 11-final (round three: style1-*, style2-left-*, style2-centre-*, style3-left-*, style3-centre-*)
tests: 10 test functions added (tests/e2e/test_production_overview.py, 4 of them concept-only), 1 changed (tests/e2e/test_workspace_overviews.py: it pinned the old stack and a click-to-open batch)
follow-ups: more than 20 batches; a batch number in the overview response; keyboard order in the stacked layout; the tab strip sits 32px lower after an in-app visit (predates this); if Style 2 is chosen, the other Production tabs need the same title-above-tabs order
verdict: findings-open (a style has to be chosen before this can merge)
