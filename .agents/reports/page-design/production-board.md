# PAGE DESIGN — production-board — 2026-10-15
plan: docs/production-board-redesign-plan.md
research: 3 comparable products (MRPeasy schedule read; Katana schedule, MRPeasy capacity search summaries), 0 craft references (searches for Linear/Height on this shape returned nothing usable), 2 pattern sources (SAP Fiori calendar web and Android, search summaries)
directions: 3 (Week, Agenda, By demand); chosen: pending
passes: 5   defects fixed: 14   bugs fixed: ui_shots purge skipped planning batch_models tables
screenshots: ~/.cache/workflow-engine-ui-shots/board-00-before, board-01 .. board-05
tests: 16 added (12 CONCEPT ONLY), 4 changed (board phone, material phone: open Details before card actions; capacity phone: period read from data-start/data-end; production layout: key card is "Planned batches")
follow-ups: remove the losing styles once picked; tick UX overhaul 4.3 on that MR; no craft reference found for this shape
verdict: patched
