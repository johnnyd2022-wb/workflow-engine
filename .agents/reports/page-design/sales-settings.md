# PAGE DESIGN — sales-settings — 2026-10-25
plan: docs/sales-settings-redesign-plan.md
research: 2 comparable products (Katana, Breww), 2 craft references (Linear members, Stripe team), 4 pattern sources (Primer saving, Polaris save bar, GitLab settings study, GOV.UK summary list)
directions: 3 (Cards, Side by side, Read first); chosen: awaiting the pick
passes: 5   defects fixed: 9   bugs fixed: every Save sent the whole form (saving Tasks saved a half-typed target); settings loaded twice (double x-init); a failed load showed defaults that could be saved over the real settings
screenshots: ~/.cache/workflow-engine-ui-shots/config-survey/00-before, sales/01 .. sales/05
tests: 15 e2e added (incl. 11 CONCEPT ONLY), 2 JS unit added, 1 changed (test_crm_contact_sync_ui: the Sales-wide default needs Save)
follow-ups: Sales tasks archive vs Production Task settings (two settings, two boards); double x-init on Analytics, Batch matching, Excise
verdict: findings-open
