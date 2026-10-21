# PAGE DESIGN — customs (v2: entry, stock, settings) — 2026-10-21
plan: docs/customs-redesign-plan.md (v2 section)
research: 5 comparable products (Breww NZ and UK duty, InnoVint TTB, Katana, Lightspeed counts) + NZ Customs rules (Act ss 81/138/159, Regs 59-64, nil-return rules, entry timing), 2 craft references (Stripe Tax filings, Linear cycles), 2 pattern sources (GOV.UK summary list/card, task list)
directions: 3 (Entry sheet, Desk, Ledger); chosen: awaiting the pick
passes: 4   defects fixed: 19   bugs fixed: stocktake "broken" committed mid-resolution; stocktake adjustments invisible to the nightly stock check; scripted Customs forms submitted as boosted page loads ("Add a place")
screenshots: ~/.cache/workflow-engine-ui-shots/customs2/00-before .. 04
tests: 3 unit + 2 stocktake + 9 e2e added (incl. 9 CONCEPT ONLY width cases), 1 changed (test_dashboard_page: the record form is inside the folded Records, products moved to Settings)
follow-ups: NP3 page-design (separate MR); duty-credit line on the entry; remission claim tracking (NZCS 277 outcome)
verdict: findings-open
