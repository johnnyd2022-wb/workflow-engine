# PAGE DESIGN — dashboard (Home) — 2026-10-11
plan: docs/dashboard-redesign-plan.md
research: 5 comparable products (Shopify admin home, Odoo manufacturing dashboards, Katana, Safefood 360, Drata/Vanta), 5 craft references (Stripe home, Mercury, Linear Inbox and Pulse, Geckoboard, Notion dashboard summary), 4 pattern sources (Shopify app home pattern, Stephen Few, bento grids, Carbon tiles); for the tab names: Katana, MRPeasy, Cin7 Core, Breww, Drata, Vanta, Stripe, Xero, HubSpot, NN/g on branded menu terms
directions: three styles were shown (Stacked, Board, Rail), plus a briefing style and a menu along the bottom; the user chose the Board with the menu down the left; the rest and the switches are deleted
passes: 21   defects fixed: 27   bugs fixed: "3 active batchs" plural; document listeners re-bound on every boosted visit; dates forced to US format; sidebar's collapsed state forgotten on every load and its logout hidden; Inventory's edit panel ignored the collapsed sidebar
screenshots: ~/.cache/workflow-engine-ui-shots/dash/00-before, 01 to 16 (the three-style rounds), 17-sidebar-before, 18 to 20, 21-final
tests: 15 in tests/e2e/dashboard/test_dashboard_today.py, 5 in tests/e2e/test_sidebar_rail.py (new), 5 unit in tests/test_dashboard_summary.py; changed: tests/e2e/test_workspace_overviews.py, tests/test_compliant_frontend_assets.py, tests/test_navigation.py and tests/e2e/test_boosted_navigation.py (the Home label)
follow-ups: confirm the overall score's weighting; currency still US dollars; "today" follows the server clock's timezone; planned-work rows still print ISO dates; the top bar's contents stop at 1400px on a wide screen; "dashboard" wording on other pages
verdict: patched
