# Whistlebird production-sheet → Biz-E field mapping (stage 2)

Working mapping registry for the "Production!!" sheet tab. Unlike stage 1's registry
(structured DB columns), every row here maps a **curated manifest record type** — see
[`docs/whistlebird-production-sheet-migration-plan.md`](whistlebird-production-sheet-migration-plan.md)
stage 1 — not a raw sheet column, because the sheet itself has no headers and its
column layout drifts between sections.

## Cross-cutting rules

Every imported record carries the following JSON provenance shape in the same target
fields stage 1 used (`inventory_items.extra_data`, `execution_steps.execution_data`):

```json
{
  "source_system": "whistlebird_production_sheet",
  "legacy_source": {"table": "production_sheet", "id": "<manifest record id>"},
  "legacy_date": "YYYY-MM-DD",
  "timestamp_policy": "derived_noon_pacific_auckland",
  "date_confidence": "clean | resolved_by_context | unresolved",
  "sheet_row_range": "<first>-<last>",
  "sheet_global_vat_number": "<int, if present>",
  "sheet_local_batch_label": "<e.g. WBWF15, Rosella VAT1, Solstice VAT2>"
}
```

`legacy_date` is the curator's resolved date. `date_confidence: unresolved` records are
never written by `--apply-production-sheet` (see plan, non-negotiable rules).
A record continuing an already-imported legacy batch also carries:

```json
{"linked_legacy_source": {"table": "product_actions_flavor_vat", "id": 19}}
```

Money/volume/ABV fields are `Decimal`, never binary float — same `_decimal()` helper as
stage 1. Quantities use the target item's canonical unit; tally/checkbox columns
(Shape B in the source analysis) are never read as quantities.

## Operation mapping

| Manifest record type | Biz-E destination | Mapping | Status |
| --- | --- | --- | --- |
| `maceration` (botanical charge, Shape A rows) | WIP inventory + `Sheet: flavour preparation` execution | Ingredient names/weights become execution data; the twin-column layout in rows 1–221 (two parallel observed runs of the same charge) is folded into one manifest record with both readings retained in `extra_data.observed_runs`, not imported as two executions. | needs curation |
| `distillation` (Shape C date+event rows) | WIP inventory + `Sheet: distillation` execution | Event label and resolved date only; ABV readings from nearby rows attach as `extra_data`, not as separate movements. | needs curation |
| `vat_fill` | WIP inventory + `Sheet: flavour vat` execution | Ethanol/water volumes from Shape B rows, excluding tally-mark columns. Wildflower VAT1–25 and Rosella's global-VAT26 origin already exist in the legacy import (confirmed `WBWF01`–`WBWF25`, `WBRS26` — WB-024/WB-027); sheet rows for these link via `linked_legacy_source` to the matching `legacy_id` rather than creating new items. Only Solstice (global VAT27+) fills create wholly new items. | needs curation; cross-boundary link targets confirmed for VAT23/24/25/Rosella-26 |
| `bottling` | finished-product inventory + production movement | Bottle count from the event row. Resolved (WB-022): row 1751 ("Bottling VAT47", 79 bottles) is actually VAT44's bottling, mislabeled — imports under VAT44. Row 1913 is a duplicate/premature note of the same event as row 1936 and is excluded. VAT47's real bottling is one event: row 1936, 78.5 bottles, 2026-05-07. | ready |
| `sample` | completed historical sample execution | Same "no fabricated inventory output" rule as stage 1's `apply_sample_history`, if any sample-labelled rows are found during curation (none confirmed yet in the analysed range). | not yet found |
| Solstice-to-Rosella maceration (VAT48 and any future batch following the same pattern) | `Sheet: flavour vat` execution (Solstice output) → separate `Sheet: fruit maceration` execution (consumes that Solstice item, outputs Rosella) | Resolved (WB-023): Solstice is the deliberate base spirit for Rosella — a real post-maceration production step (rhubarb), not a relabel. VAT48 imports as **two linked executions**, using the same `actual_inputs`/`vat_batch` reference-resolution pattern stage 1's `apply_evidenced_production` already uses for flavour-vat/bottling lineage. The Solstice-fill execution (rows 1755–1775) produces the input item; the new `Sheet: fruit maceration` execution (rows 1786–1846, bottled 2026-03-26, 64 bottles) consumes it and produces the Rosella output. | ready |
| scratch/planning rows ("Math for VAT...", tally checklists) | — | Explicitly excluded. Not a manifest record. | no action |
| non-production tabs (Purchases, Sales sheet, Contacts, Pricing calculator, etc.) | — | Out of scope for this stage; only the "Production!!" tab is in scope. | no action |

## Product-line summary

| Product line | Legacy DB counterpart | First sheet appearance | Notes |
| --- | --- | --- | --- |
| Wildflower | Yes — `WBWF01`–`WBWF25` all already imported in stage 1 (confirmed by direct query, WB-024) | Row 1 (VAT1) | VAT1–25 are **not new data**; only continuation events after each batch's own `legacy_date` (e.g. VAT23–25's post-cutoff bottling) attach via `linked_legacy_source`. VAT26+ (global counter) onward is new — but global VAT26 is Rosella's, see below. |
| Rosella | Yes — first vat (`WBRS26`, legacy_id 26, legacy_date 2025-05-06) already imported in stage 1 (WB-027) | Row 1016 ("Rosella VAT1 (26)") | Cross-boundary, same treatment as Wildflower VAT23–25: the vat's origin already exists in `whistlebird_test`; only its post-cutoff continuation (ABV drop note, rhubarb addition, second bottling attempt — rows 1022–1257) is new and links via `linked_legacy_source` to legacy_id 26. |
| Solstice | No — confirmed no legacy row exists for global VAT27+ | Row 1083 ("Solstice VAT1 (27)") | Genuinely wholly new product/process; first line with no cross-boundary linkage. VAT48 later converts to Rosella mid-batch (WB-023) — a wholly-new Solstice fill retroactively relabelled, not a link back to legacy data. |

## Repeatable reset

Unchanged from stage 1: `scripts/whistlebird_migration.py --confirm-reset-whistlebird-test`
deletes tenant-scoped Core data for `whistlebird_test` regardless of `source_system`,
so a reset clears both the `whistlebird_v1` and `whistlebird_production_sheet` rows
together. No new reset surface is introduced by this stage.
