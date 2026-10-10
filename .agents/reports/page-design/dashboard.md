# PAGE DESIGN — dashboard — 2026-10-10
plan: docs/dashboard-redesign-plan.md
research: 5 comparable products (Shopify admin home, Odoo manufacturing dashboards, Katana, Safefood 360, Drata/Vanta), 5 craft references (Stripe home, Mercury, Linear Inbox and Pulse, Geckoboard, Notion dashboard summary), 4 pattern sources (Shopify app home pattern, Stephen Few, bento grid guides, Carbon tiles)
directions: 3 (Stacked, Board, Briefing) behind ?style=1|2|3; the user picks one and the other two are deleted
passes: 12   defects fixed: 16   bugs fixed: "3 active batchs" plural; document listeners re-bound on every boosted visit; dates forced to US format
screenshots: ~/.cache/workflow-engine-ui-shots/dash/00-before, 01 to 11, 12-final (style1-*, style2-*, style3-*)
tests: 18 test functions added (13 in tests/e2e/dashboard/test_dashboard_today.py, of which 3 are concept-only style tests; 5 unit in tests/test_dashboard_summary.py), 2 changed (tests/e2e/test_workspace_overviews.py and tests/test_compliant_frontend_assets.py: both pinned the old blocks)
follow-ups: confirm the overall score's weighting; currency still US dollars; "today" follows the server clock's timezone; planned-work rows still print ISO dates
verdict: findings-open (a style has to be chosen before this can merge)
