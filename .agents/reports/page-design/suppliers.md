# PAGE DESIGN — suppliers — 2026-10-18
plan: docs/suppliers-redesign-plan.md
research: 4 comparable products (Katana, MRPeasy, Xero, Unleashed — Unleashed had no first-party doc), 3 craft references (Apple Contacts/Mail split view, Attio record pages, Notion gallery), 3 pattern sources (Microsoft list/details and SAP Fiori master-detail, Carbon data table, GOV.UK summary list); mostly search summaries, Katana's supplier-card page read
directions: 3 (Register, Address book, Cards); chosen: Style 1 — Register (founder selection)
passes: 6   defects fixed: 13   bugs fixed: dark theme text at 1.02:1 contrast (hard-coded colours); search box 60px tall under base-spa input rules
screenshots: ~/.cache/workflow-engine-ui-shots/suppliers/00-before, 01 .. 06
tests: 19 added in tests/e2e/test_suppliers_design.py (12 CONCEPT ONLY), 0 changed
follow-ups: purchase dates per lot need purchase_date in the compact inventory list; link inventory lines to supplier records by id
verdict: patched

## Selection cleanup

Deleted Address book and Cards, their switch, style persistence and query selection. Retained all seven functional/regression cases and replaced twelve preview cases with four responsive register/drawer cases, including old preview URLs and stored choices. Independent grader: valid, no assertion weakening. All final PNGs reviewed: pass 01 (16 states), pass 02 (15 normal states, no console errors); expected injected API-error screenshot retained from pass 01. Selected-page/API/navigation suites: 47 passed. Node syntax, Ruff and scoped Semgrep passed. See MR for shared-suite and current-head CI results. Screenshot fixture purged.

Selected implementation head `03a7833c`: pipeline 2959892191 passed, including relevant_tests and mr_e2e. MR removed from draft; human review and merge remain required.
