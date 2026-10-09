# PAGE DESIGN — dashboard — 2026-10-10
plan: docs/dashboard-redesign-plan.md
research: 3 comparable products (Shopify admin home, Odoo manufacturing dashboards, Katana), 3 craft references (Stripe Dashboard home, Mercury, Linear Inbox), 2 pattern sources (Shopify app home pattern, Stephen Few)
passes: 6   defects fixed: 6 (health card beside attention left a blank area on a busy day, now a full-width band; health card overwritten by its own state text; setup strip louder than the content; dark-theme trend colour; narrow-screen block order; plural)   bugs fixed: "3 active batchs" plural; document listeners re-bound on every boosted visit; dates forced to US format
screenshots: ~/.cache/workflow-engine-ui-shots/dash/00-before, 01 to 05, 06-final
tests: 8 added (tests/e2e/dashboard/test_dashboard_today.py), 1 changed (tests/e2e/test_workspace_overviews.py: the layout test named the old blocks)
follow-ups: currency is still formatted as US dollars (the org's currency is not in the summary response); planned-work rows still print ISO dates and "batch(es)" because two existing tests pin that wording
verdict: patched
