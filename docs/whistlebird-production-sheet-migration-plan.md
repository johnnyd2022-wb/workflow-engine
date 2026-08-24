# Whistlebird production-sheet → Biz-E migration plan (stage 2)

## Objective

Backfill the execution/production history that exists in neither the Whistlebird v1
legacy database nor the live Biz-E app, using the founder's Google Sheet
("Production!!" tab, spreadsheet `1R_4r1s1bIlHNPH_bSRNWUVcj3_iDiKu717u736Iiank`,
gid `1370312095`) as source. This is stage 2 of the migration referenced in
[`docs/whistlebird-migration-plan.md`](whistlebird-migration-plan.md) and findings
WB-006/WB-013.

This continues the same non-negotiable rules as stage 1: never mutate the source
(the sheet is read as a frozen snapshot, never written to), every imported row carries
legacy provenance, and reset/replay must be exact and repeatable.

## Two confirmed execution gaps

Cross-referencing the legacy migration's target tenant (`whistlebird_test`) against the
real live Biz-E org (`Whistlebird Ltd`, org_id `fce20553-da3f-4c26-a125-ad3585b0f2c6`)
established the actual gaps this stage must fill:

| Period | Coverage today |
| --- | --- |
| 2023-01-18 → 2025-05-20 | Legacy v1 DB, migrated into `whistlebird_test` (stage 1, done) |
| **2025-05-20 → 2026-01-17** | **Nothing.** No legacy DB rows, no live Biz-E executions. |
| 2026-01-17 → 2026-05-11 | Live Biz-E executions in `Whistlebird Ltd` (real usage, not migrated) |
| **2026-05-11 → sheet data end (2026-07-23)** | **Nothing recorded as executions**, though Xero sales continued to 2026-07-07 |

Xero sales/contacts are out of scope for this stage: they can be resynced into any org
at any time and are not derived from this sheet. This stage is scoped strictly to
production/execution history.

## Target org for this stage

**`whistlebird_test`** (the same disposable migration sandbox stage 1 used), not the
real `Whistlebird Ltd` org. This keeps the reset-and-retry loop safe while the importer
is being built and validated. Promoting a verified result into `Whistlebird Ltd` is a
deliberate, separately-confirmed one-time step — never let the automated
reset/dry-run/apply commands target `Whistlebird Ltd` directly. `RESET_ORG_NAME` in
`scripts/whistlebird_migration.py` stays hardcoded to `whistlebird_test`.

## Why this can't be a direct structured import

Stage 1 read structured legacy database rows. This sheet has **no column headers
anywhere** and its layout drifts: the same column position means a %-share of a batch
in one section and a litres-of-ethanol figure in another. It is a chronological lab
notebook, not a table export. Concretely (full detail in the source analysis kept
alongside this plan):

- Three product lines are interleaved: **Wildflower** (continuation of the legacy
  `WBWF01`–`WBWF14` batches), and two lines with **no legacy-DB counterpart at all**:
  **Rosella** and **Solstice**.
- Each VAT's lifecycle (maceration → distillation → vat fill → bottling) is often
  split across non-adjacent row ranges, sometimes with a follow-up note physically
  re-inserted near the block's start rather than appended at the end.
- Dates are a mix of Excel serials, `DD/MM/YYYY` text, one 2-digit-year value, and at
  least one outright unparseable string (row 743: `01/24/0204`).
- At least 7 dates contradict their own batch-block's chronological sequence and are
  very likely typos (see findings WB-021).
- Some rows are pre-batch scratch arithmetic ("Math for VAT...") with no real-world
  event behind them, and must be excluded, not imported as phantom executions.
- Some columns are tally/checkbox marks used while physically pouring jugs, not
  quantity measurements — a positional numeric-extraction heuristic would
  misread these as data.

Because of this, **automatic column-position parsing is not viable**, and treating the
whole tab as ground truth without review would create incorrect executions. Stage 2
therefore adds a **curation step** stage 1 didn't need.

## Migration stages

1. **Curate a structured source manifest (human-reviewed, one-time per batch of rows)**
   - Produce `docs/whistlebird-production-sheet-source.json`: one structured record per
     real production event (maceration/flavour-prep, distillation, vat fill, bottling,
     sample), each carrying: source row range, product line, local VAT/batch number,
     the sheet's own global VAT counter (see WB-024), resolved ISO date, a
     `date_confidence` of `clean` / `resolved_by_context` / `unresolved`, quantity,
     unit, and — for a batch that continues a legacy-imported one (Wildflower VAT23–25)
     — an explicit `linked_legacy_source: {table, id}` pointing at the existing
     `product_actions_flavor_vat`/`product_actions_distillation_experiments` row it
     continues, resolved by a human matching batch text, not inferred by string match.
   - This manifest is the frozen, versioned input the deterministic importer reads.
     It is never regenerated automatically from the live sheet — the sheet itself is
     only re-consulted if the founder corrects a record.
   - Rows flagged `unresolved` (row 743, and any other contradictory/ambiguous date
     the founder hasn't confirmed) are excluded from `--apply-production-sheet` until
     resolved; `--dry-run-production-sheet` reports them as a named blocker count so
     they're never silently skipped without visibility.

2. **Map and approve**
   - Extend [`docs/whistlebird-production-sheet-field-mapping.md`](whistlebird-production-sheet-field-mapping.md)
     with one row per manifest record type, same format as stage 1's mapping registry.
   - New open findings tracked in [`whistlebird-findings.md`](../whistlebird-findings.md)
     (WB-020 onward) — nothing is silently discarded or auto-resolved past what the
     analysis actually supports.

3. **Extend the process template set**
   - Reuse operation-typed templates, matching the "Legacy X" naming convention with a
     `Sheet:` prefix so provenance stays visually distinct: `Sheet: flavour
     preparation`, `Sheet: flavour vat`, `Sheet: distillation`, `Sheet: bottling`,
     `Sheet: fruit maceration`. Templates are operation-typed, not product-line-typed —
     Wildflower/Rosella/Solstice all use the same small template set, exactly like
     stage 1 did across its ingredient/flavour/bottling operations. `Sheet: fruit
     maceration` is new (not present in stage 1): it takes a flavour-vat batch as
     input and produces a distinct finished product — the Solstice → Rosella
     rhubarb-maceration step (WB-023) — a real production step, not a relabel.
   - Created once via an extended `setup_historical_process_templates` (same
     idempotent create/repair/existing behaviour), never per-row.

4. **Import in dependency order**
   - Direct DB query against `whistlebird_test` confirmed `product_actions_flavor_vat`
     legacy rows already cover `WBWF01`–`WBWF25` **and** Rosella's first vat
     (`WBRS26`, legacy_id 26, dated 2025-05-06). Sheet rows describing these batches'
     origin are **not new data** — only their post-cutoff continuations (a later
     distillation note, ABV reading, or bottling) attach to the matching `legacy_id`
     via `linked_legacy_source`, rather than creating a disconnected new item. This is
     the "cross-reference to data we already have populated" the founder asked for,
     and now covers Wildflower VAT23–25 *and* Rosella's opening vat.
   - Only **Solstice** (global VAT27+) has no legacy counterpart at all and creates
     wholly new inventory items/executions exactly like stage 1's
     `apply_evidenced_production`, using `_derived_timestamp` (noon Pacific/Auckland)
     on the manifest's resolved date.
   - A VAT whose product identity changes mid-batch (VAT48: filled as Solstice,
     explicitly noted "converted from SS" to Rosella — WB-023) is keyed by its final
     stated product in the manifest; the curation step records the conversion note in
     provenance rather than the importer inferring it.
   - Idempotency follows the exact stage-1 pattern: `legacy_table = "production_sheet"`,
     `legacy_id` = a stable per-record key derived from the manifest (spreadsheet row
     of the record's defining event), looked up via
     `InventoryItem.extra_data.contains({"legacy_source": {"table": "production_sheet", "id": ...}})`
     before creating anything.
   - Provenance reuses `_legacy_provenance`'s exact shape with `source_system` set to
     `"whistlebird_production_sheet"` (distinct from `"whistlebird_v1"`) so
     verification and reset reporting can distinguish the two source stages while
     `reset_target_org` continues to wipe both (org-scoped, not source-scoped, exactly
     as stage 1 already does).

5. **Validate and prove repeatability**
   - `--dry-run-production-sheet` reports proposed create/update/skip counts by
     product line and operation type, the `unresolved`-date blocker count, and the
     cross-boundary-link count, without writing — same aggregate-only, no-PII shape as
     stage 1's dry runs.
   - `--confirm-reset-whistlebird-test` (unchanged) plus a re-run of
     `--apply-production-sheet` must reproduce identical row counts, provenance links,
     and inventory totals — the manifest being a static file is what makes this
     actually deterministic, unlike re-reading the live, editable sheet each time.
   - Extend `build_import_verification` with a `production_sheet` block comparing the
     manifest's expected counts against `source_system = 'whistlebird_production_sheet'`
     actual counts, mirroring the existing `whistlebird_v1` comparison.

## Non-negotiable rules (unchanged from stage 1, restated for this stage)

- The Google Sheet is read-only source material; nothing is written back to it.
- Every imported row carries legacy provenance (manifest row/record id, resolved date,
  and a `date_confidence` field so a human can audit exactly how sure the importer was).
- Reset stays guarded by the exact `whistlebird_test` org name and the existing
  `--confirm-reset-whistlebird-test` flag; this stage adds no new reset surface.
- No record with `date_confidence: unresolved` is written by `--apply-production-sheet`.
- No tally/checkbox column value or scratch-math row is ever imported as a quantity or
  a standalone execution.
- Automated tooling never targets `Whistlebird Ltd` (the real org) directly.
