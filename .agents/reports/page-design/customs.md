# PAGE DESIGN — customs — 2026-10-20
plan: docs/customs-redesign-plan.md
research: 4 comparable products (Breww NZ excise report, NZ Customs entry rules, Ekos, Xero GST), 2 craft references (Stripe/TaxJar Filings, Linear cycles), 2 pattern sources (GOV.UK task list, Scottish Government check answers)
directions: 3 (Entry, Steps, Timeline); chosen: awaiting the pick (!544)
passes: 9   defects fixed: 27   bugs fixed: forms moved out of the excise root lost their handlers (console error); lodged periods without a saved entry read "nothing removed"; untracked months reported as overdue; entry lines merged per excise item gave a levy 1c off the lodged entry
screenshots: ~/.cache/workflow-engine-ui-shots/00-before .. 09
tests: 7 added (4 unit, 3 e2e + 9 CONCEPT ONLY layout cases), 2 changed (test_dashboard_page: evidence form behind "Add a record"; test_excise settings now include reminders_from)
follow-ups: duty-credit line on the entry; Customs page's per-CCA multi-site path; delete the losing styles after the pick
verdict: findings-open
