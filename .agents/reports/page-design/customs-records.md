# PAGE DESIGN — customs-records — 2026-10-23
plan: docs/customs-records-redesign-plan.md
research: 4 comparable products (Vanta, Drata, Secureframe, Hyperproof), 0 craft references (gap: none researched separately), 2 pattern sources (GOV.UK task list; Polaris Sheet / Material side sheet / CMS Drawer)
directions: 3 (Checks and a page each, Checklist and a sheet, Timeline); chosen: awaiting the pick
placement: dedicated Records view (Excise entry · Stock · Records · Settings); entry page keeps a one-line link
passes: 5   defects fixed: 11   bugs fixed: none (the old evidence URL now redirects to Records)
screenshots: ~/.cache/workflow-engine-ui-shots/records/01..05; before: customs2/04/style1-records.png
tests: 1 file added (test_customs_records.py), 3 changed (test_customs_page.py, test_dashboard_page.py, test_compliant_frontend_assets.py: Records moved from a folded section to its own view)
follow-ups: remove unused record cards/form from compliant.js; duty-credit line on the entry
verdict: findings-open
