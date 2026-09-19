# Whistlebird production-history import — decisions log

Internal engineering audit trail for `scripts/whistlebird_migration.py`: how each
ambiguous source record was resolved during curation. Not loaded data — the tool itself
carries no "legacy"/"historical" wording (see `docs/whistlebird-production-import.md`).
"Prior database" / "v1" below refers to the old inventory database read at
`WB_LEGACY_DATABASE_URL`; "the sheet" is the founder's "Production!!" Google-Sheet tab,
curated into `docs/whistlebird-production-sheet-source.json`.

Status values: `open`, `resolved`, `accepted limitation`, `blocked`.

## Still open after the per-product-workflow rebuild (2026-09-07)

- **Per-batch maceration/distillation dates for VAT28+** load as `derived` (inherited
  from the recorded VAT-fill/bottling date) except where a specific step date was
  recoverable from context (see the per-record `notes` fields added 2026-09-11). VAT27
  and all prior-DB batches have real per-step dates.
- **Rosella VAT26 (prior DB)** predates Solstice, so its rhubarb-maceration step has no
  Solstice base-VAT input — its `RS01`/`RS02` flavour rows are treated as the maceration.
  Still needs founder confirmation that this early-Rosella method is correct — not
  addressed by the 2026-09-11 pass below.
- **VAT52** still excluded: an April 2026 Wildflower distillation under that number has
  no fill/bottling anywhere, and the later Solstice distill/fill/bottle chain has no
  recorded bottle count. See WB-029/WB-031 below.
- **VAT55 and VAT57** are distilled and filled but not yet bottled as of the 2026-09-11
  pull — re-run the import once their bottling rows land in the sheet.
- **An unlabelled 26-bottle line** (row 2058, positionally reads as VAT56) has no VAT
  number or "Bottling" text in the source — needs founder confirmation before it can be
  curated. See the manifest's `excluded` entry for the full reasoning.
- **Green Gold (gg01)** (row 2035: 41L of aged Wildflower drawn from VAT53 to make
  144x500ml bottles) is modelled as its own one-step `Green Gold gin` final-product
  workflow, not a trial: the sheet manifest's `green_gold_records` section feeds the API
  replay, which consumes 41L from VAT53's aged-Wildflower output and produces 144
  `Green Gold - final product` units. Implemented in code; not yet replayed into
  `whistlebird_test` (see WB-037).

## Findings register

| ID | Status | Finding | Required decision or next action |
| --- | --- | --- | --- |
| WB-001 | resolved | v1 stores operational history as `DATE` only. It contains no time of day or source time zone. Biz-E timestamp columns therefore cannot preserve an original timestamp that does not exist. | Import the original date into date fields; for required timestamps use the agreed deterministic time of **12:00 Pacific/Auckland** and retain `legacy_date`, table and ID in provenance metadata. |
| WB-002 | resolved | v1 has no foreign keys, but its application code establishes a recoverable free-text chain. All 26 flavour-vat rows link to 52 flavour-batch rows; all 27 bottlings link to vats; 3 manual sales have explicit bottle-batch links. | Import these evidence-backed links, retaining source IDs and the original batch text as provenance. |
| WB-003 | open | The legacy audit table is not a transaction ledger: it has 1,100 rows and includes 551 sale actions, while `sales_product` has 315 rows. | Use operational tables as migration sources. Preserve audit rows only as secondary provenance where they corroborate a source record. |
| WB-004 | resolved | A similarly named target org, `whistlebird-test`, may exist while the requested `whistlebird_test` tenant is absent (as it was again after the test database was refreshed on 2026-09-04). | `scripts/whistlebird_migration.py --rebuild-whistlebird-test` now creates only the exact `whistlebird_test` tenant and deterministic test admin if absent, then resets and replays the reviewed import. It rejects every other tenant name. |
| WB-005 | resolved | Legacy CRM contacts are not Xero identities, and v1's `products` table is empty. Xero invoice/contact records must be obtained by Biz-E's authorised Xero connection; product mappings can then be backfilled from historic descriptions. | Authorised to connect `whistlebird_test` to Whistlebird Xero for a read-only historical sync. OAuth tokens will not be copied from v1. |
| WB-006 | open | Legacy data does not contain dedicated hygiene, staff-training, maintenance, pest, illness, or mock-recall records. | These are held in Google Sheets. Import the supported operational traceability now; capture the sheet evidence as a separate second stage. |
| WB-007 | accepted limitation | `sales_product` has no populated `product_name`, but 312 sales have 391 nested product entries. Legacy code derives their bottle batch solely from invoice date by selecting the most recently started bottling batch; it is not an explicit physical allocation. | Import it as a clearly labelled legacy batch suggestion, then reconcile/clean it up after Xero sync. Do not present it as direct evidence before reconciliation. |
| WB-008 | open | Legacy `uid` values are not a stable staff identity source (the profiled operational/audit rows contain 1,100 distinct values). | Preserve the raw legacy actor reference in provenance metadata; do not create or attribute Biz-E users from it. |
| WB-009 | resolved | `purchases_ingredients.ingredients_amount` has 57 values and no unit column in the database. | Legacy form code confirms the unit is **grams**. Import quantities as `g`, retaining supplier, ingredient code and expiry. |
| WB-010 | open | v1 has no document/evidence storage table or database file reference. NP3 records may therefore exist outside the database, but are not discoverable from this source schema. | Inventory the legacy filesystem/Google Drive/paper evidence separately before audit readiness is claimed; attach only reviewed records to Biz-E evidence/compliance controls. |
| WB-011 | open | The one-row `inventory` table and 20-row `monthly_totals` table are snapshots/aggregates, not linked transactions. Their values cannot safely be replayed as movements without double counting. | Use them only as period-end reconciliation assertions after operational rows are imported. Investigate every mismatch rather than applying a balancing adjustment. |
| WB-012 | resolved | `product_actions_flavor_experiments` creates a flavour intermediate in mL from clearing volume/ABV; distillation experiments reference those flavour codes. | Import it as historical WIP production, retain clearing/source values, and link only its code-based downstream references. |
| WB-013 | accepted limitation | Production actions end on 2025-05-20 (bottling on 2025-05-06), while sales continue through 2026-05-10. The v1 database cannot by itself establish a complete production-to-sale trail for the later sales period. | The Google Sheet supplies post-v1 operations and Xero supplies sales. Import/reconcile both in the second stage before presenting end-to-end coverage to a verifier. |
| WB-015 | resolved | Trade-waste framework applicability was unknown. | Whistlebird has no trade-waste consent; the operation's waste is composted off site. Do not configure the trade-waste framework. |
| WB-016 | resolved | It was unclear whether historical process templates would alter current operational workflows. | Approved: create clearly labelled historical templates and completed executions. They preserve actual source dates and create normal Core traceability edges; they are not current SOPs. |
| WB-017 | resolved | The v1 source reuses a supplier batch code for multiple purchases of the same ingredient, but Biz-E enforces a unique item name/batch pair. | Preserve each original code in provenance. Add a deterministic `legacy-<table>-<id>` suffix only to reused codes so every individual receipt remains a valid, traceable Core lot. |
| WB-018 | accepted limitation | v1 records ingredient codes against flavour operations but not consumed quantities. Sixty-two code references match more than one historical receipt because the source reused that code. | Import only the exact code-matched Core links and label their quantities unavailable. Do not infer allocation or decrement on-hand inventory; reconcile any disputed lot allocation from external evidence. |
| WB-019 | open | Xero sales/contact import is intentionally not represented by copied v1 rows or OAuth tokens. Biz-E's OAuth callback requires an authenticated interactive browser session for `whistlebird_test`. | Sign in to the test Biz-E instance as the Whistlebird test admin, connect Xero, and explicitly select the Whistlebird tenant. The initial sync can then populate customers/invoices and support reviewed product mappings. |
| WB-014 | accepted limitation | The legacy repository contains an experimental `supply_chain` sales-mapping module, but none of its referenced `supply_chain_*` tables exist in the restored production copy. | Treat the module as undeployed/stale code, not as historical source data. |

## Confirmed source coverage

- Operational history ranges from **2023-01-19** to **2026-05-13**; sale rows run through **2026-05-10**.
- 57 ingredient purchases, 9 GNS purchases, 1 bottle purchase, 53 flavour additions, 26 flavour-vat actions, 27 bottlings, 315 sales, 13 customs lodgements, and CRM records are present.
- No legacy source table contains timestamp-with-time-zone or timestamp-without-time-zone columns.

## Stage 2: production-sheet findings

| ID | Status | Finding | Required decision or next action |
| --- | --- | --- | --- |
| WB-020 | open | `compliance_records` is empty (0 rows) tenant-wide in `workflow-engine-test`, even though the stage-1 field mapping marks `customs_lodgements` → `compliance_records` as "ready" and the stage-1 plan states it was imported and verified. | Not part of stage 2's scope, but should be re-run/verified before stage 1 is considered closed: rerun `--apply-core-receipts-and-lodgements` against `whistlebird_test` and confirm with `--verify-import`. |
| WB-021 | resolved | The production sheet had 8 dates that contradicted their own batch-block's chronological sequence. Founder confirmed the correct date for each directly. | Row 177 → 2024-03-11. Row 388 → 2024-09-02. Row 743 (`01/24/0204`) → 2025-01-24. Row 1250 → 2025-08-01 (genuine event, not a typo). Row 1402 → 2025-09-02. Row 1588 → 2025-12-03. Row 1727 → 2026-02-12. Row 1981 → 2026-07-02. Use these exact dates in the curation manifest; no `unresolved` flag needed for these 8. |
| WB-022 | resolved | VAT47 had three bottling mentions (rows 1751, 1913, 1936). Cross-checked VAT44–VAT50 for complete distill/fill/bottle records: VAT44 has distilling (row 1657) and filling (row 1659) but **no bottling under its own name**; VAT47's row 1913 and row 1936 both record identical **78.5 bottles**. Founder confirmed: row 1751 ("Bottling VAT47 (WF)", 79 bottles) is actually VAT44's missing bottling, mislabeled in the sheet; row 1913 is a premature/duplicate note of the same event as row 1936; VAT50 simply never appears in the sheet (a skipped number, not a missing record). | VAT44 bottling: 79 bottles, date resolved_by_context (between row 1727's 2026-02-12 and row 1755's 2026-02-19 — use 2026-02-19). VAT47 bottling: single event, 78.5 bottles, 2026-05-07 (row 1936's date, corrected — the raw serial resolved day/month-swapped; founder confirmed the true date by checking it falls before row 1959's 2026-06-28). Row 1913 excluded from the manifest as a duplicate. |
| WB-023 | resolved | VAT48 is filled as "Solstice" (row 1755), then explicitly noted "Rosella converted from SS" after rhubarb maceration (row 1786). Founder clarified this is not an ad hoc relabel: **Solstice is the deliberate base spirit for Rosella** — Rosella is made by post-macerating a Solstice batch in rhubarb. This is a real production step, not a naming correction. | Import as **two linked executions**, reusing the exact input-resolution pattern `apply_evidenced_production` already uses for `vat_batch` references: (1) `Sheet: flavour vat` execution producing a Solstice WIP item (rows 1755–1775, batch label VAT48); (2) a new `Sheet: fruit maceration` execution whose `actual_inputs` references that Solstice VAT48 item and whose output is the Rosella finished item (rows 1786–1846, bottled 2026-03-26, 64 bottles). Do not collapse into one record or silently relabel Solstice as Rosella. |
| WB-024 | resolved | The sheet uses two concurrent VAT-numbering schemes: a per-product-line number (e.g. "Rosella VAT1", "Solstice VAT1") and a global sequential counter that continues Wildflower's own count across all three product lines (e.g. "Rosella VAT1 (26)", "Solstice VAT1 (27)"). Queried `whistlebird_test` directly: `product_actions_flavor_vat` legacy rows already cover `WBWF01`–`WBWF25` **and** `WBRS26` (batch label, legacy_id 26, legacy_date 2025-05-06 — Rosella's own first vat, already imported in stage 1). Only global VAT27+ (Solstice) has no legacy row at all. | Sheet Wildflower VAT15–25 and Rosella's first vat (global 26) are **not new data** — do not create fresh manifest records for their origin event. Any sheet row describing a *continuation* of one of these batches (a later distillation note, ABV reading, or bottling that happens after that batch's own `legacy_date` — e.g. Wildflower VAT23–25's post-cutoff bottling, Rosella VAT1's post-cutoff notes/second bottling) attaches via `linked_legacy_source` to the matching `legacy_id` instead. |
| WB-025 | open | Rows 1–221 (Wildflower VAT1–5) record two parallel columns of the same ingredient charge (e.g. ABV readings 33.8% vs 33.3% for the same botanical addition) — an observed twin-run layout that disappears from VAT7 onward. | Fold both readings into one manifest record's `extra_data.observed_runs`; do not import as two separate executions. |
| WB-026 | resolved | Whether this stage's tooling should target `Whistlebird Ltd` (a separate org with its own independent live Biz-E usage) or the `whistlebird_test` sandbox. | Founder confirmed (2026-08-23): `whistlebird_test` sandbox first, same as stage 1. **Correction (2026-08-24)**: `Whistlebird Ltd` is not a protected production org needing special handling — founder confirmed it's just his own tool experimentation. There is no separate "real org" to promote into; the plan is to rename `whistlebird_test` itself once its data is accurate. Earlier language in this file and the migration plan doc treating `Whistlebird Ltd` as something automated tooling must never touch is no longer load-bearing. |
| WB-027 | resolved | Corrected by WB-024's query: Rosella is **not** wholly new — its first vat (global VAT26, `WBRS26`) is already imported in stage 1, dated 2025-05-06, before the cutoff. Only **Solstice** (global VAT27+) has genuinely no legacy-DB counterpart. | Rosella imports as a cross-boundary continuation of legacy_id 26, same treatment as Wildflower VAT23–25. Solstice imports as wholly new under new `Sheet:`-prefixed process templates. |
| WB-028 | resolved | Row 1846 ("Cleaning up Rosella bottles (VAT48)") resolves by its serial to 2026-02-04, but sits in sheet order after VAT48's confirmed 2026-03-26 bottling (row 1821) — bottle cleanup logically happens after bottling, not a month before. Found while verifying WB-022; not one of the 8 dates already confirmed. | Founder confirmed (2026-09-11): row 1824 explains the real story — they realised VAT48 was over-filled, so redistilled Solstice to concentrate and added it directly to the already-bottled VAT48 stock (not back into a VAT). Row 1846 is not a production record; left excluded from the manifest with an updated reason rather than deleted, since there is genuinely nothing to import here. |
| WB-029 | resolved / narrowed | Two rows have a VAT number the sheet itself doesn't know: row 1883 "Bottling VATXX" (no date, sits after row 1881's 2026-04-16) and row 1939/1940 "Distilling Solstice (VAT52?)" (question mark in the source). | Founder confirmed (2026-09-11) row 1883 is **VAT50** — the remainder of the same Solstice redistillation from WB-028, math shows ~46.9L expected yield; the sheet itself was then edited to read "Bottling VAT50 (Solstice)" / "46 bottles," matching the founder's own estimate exactly. Imported as VAT50. Row 1939/1940's "VAT52?" is unchanged and now folded into WB-031 below, since it's the same underlying VAT52 ambiguity. |
| WB-030 | resolved | Row 1160–1162 ("Distilling wildflower" / "Bottling wildflower VAT23, 77 bottles", ~2025-07-17) shows the same 77-bottle count as VAT24's already-confirmed bottling (WB-024, row 1080, 2025-05-22). Could be a genuine coincidence (standard batch size) or another mislabel/duplicate like VAT44/47 (WB-022). | Reviewed both source lines directly with the founder (2026-09-11): row 1080 ("Bottling VAT 24 \| 77 stock") and row 1160–1162 ("Bottling wildflower VAT23 \| 77 bottles \| kept 1 for percy") each name their own VAT number explicitly, two months apart — unlike the VAT42/44/47 cases, neither row shows any relabelling, duplication, or crossed-out correction. Treated as a genuine coincidence of matching batch size and imported as VAT23. |
| WB-031 | partially resolved | Near the sheet's end, VAT52 is labelled as three different products across three separate mentions: "Distilled Wildflower (VAT52)" (row 1916), "Bottling Rosella (VAT52)" (row 1961), "Bottling Solstice VAT52" (row 1984). VAT51 also has a rhubarb addition noted (row 1932–1933), suggesting a possible Solstice→Rosella conversion similar to VAT48's (WB-023). | **Rosella/VAT51 side resolved (2026-09-11):** the founder edited the sheet itself — row 1962 now explicitly reads "Bottling Rosella (VAT51)" (46 bottles), no longer "VAT52." Row 1933's rhubarb addition confirms the Solstice→Rosella conversion. Imported as VAT51 (base) + VAT1051 (Rosella conversion), same pattern as VAT48/1048. **VAT52 side still open:** the April "Distilled Wildflower (VAT52)" run (rows 1910–1917) has no fill or bottling recorded under VAT52 as Wildflower anywhere; separately, the Solstice distill/fill/bottle chain under VAT52 (rows 1940–1985, still carries the founder's own "?") is internally consistent but has no bottle count recorded near its row-1985 bottling. Both sub-issues excluded pending founder answers — see the manifest's `excluded` entry. |
| WB-032 | resolved | Row 1676 ("Bottling Solstice (VAT 45)", ~2026-01-20) initially looked like a fill event for VAT45 (its content is fill-shaped math: 17.776L ethanol + 25.064L water, no bottle count) — but VAT45's own distillation only starts later at row 1696, making a literal VAT45 reading chronologically impossible (can't bottle before distilling). Founder corrected directly: this is actually **VAT42's bottling**, mislabelled — same pattern as VAT44/47 (WB-022). No bottle count is recorded near this row. | Imported as VAT42's bottling with an **estimated** quantity: the average of the other 8 recorded Solstice bottling counts (56.5, 56.5, 64.75, 61, 62, 60.5, 62, 61 → 60.53, rounded to 60.5). Flagged in the manifest as an estimate, not a directly recorded value — correct it if the real count is found. |
| WB-033 | resolved | VAT29's fill recipe matches Wildflower's standard shape (29.124L water + 24.456L ethanol) and a later row explicitly says "Bottling Wildflower VAT29" — but one row in between calls it "Distilling Solstice SS03 VAT29". | Founder confirmed (2026-08-24): VAT29 is Wildflower; the "Solstice SS03" mention is a mislabel. The real Solstice SS03 batch is VAT30 (row 1209 fill mention, row 1309–1310 bottling). |
| WB-034 | resolved | Direct query of the legacy v1 database (`whistlebird_db_test` container, `whistlebird_inventory` DB — the actual `WB_LEGACY_DATABASE_URL` source, not `whistlebird_test`) confirms two things relevant to WB-030: (1) legacy `product_actions_flavor_vat` tops out at id 26 (`WBRS26`) — the legacy system never had a VAT27+ at all, so the sheet's global-counter convention (Rosella=26, Solstice=27+) already existed in the old app, not invented by the sheet. (2) legacy `product_actions_bottling` (27 rows, IDs sequential 1–27, no ID gaps) jumps straight from `WBWF22` to `WBWF25` — **VAT23 and VAT24 were distilled/filled in the legacy system but their bottling was never logged there at all**, a genuine pre-existing gap, not a sheet artefact. | Corroborates WB-030: VAT23's and VAT24's sheet bottling mentions (both 77 units) are two separate real events filling a real legacy gap — confirmed by the founder (see WB-030) and imported. Minor unrelated note: legacy `product_actions_flavors` has a harmless row-ID gap (id 3 missing, jumps 2→4) but every flavour-batch code (WF01–WF50, RS01–RS02) is present and sequential — looks like a deleted/cancelled row, not a lost batch; no action needed. |
| WB-035 | resolved | Row 2015–2017 ("Bottling WF (VAT49)," 2026-07-16) initially had no recorded bottle count anywhere nearby. | Founder confirmed (2026-09-11): 78 bottles. The sheet was independently updated to show the same figure ("78 bottles," row 2017) before this was re-verified — doubly confirmed. Imported as VAT49. |
| WB-036 | open | An unlabelled "26 bottles" line (row 2058) sits immediately after VAT56's fill block (row 2042, filled ~2026-09-01) with no "Bottling VAT56" text and no VAT number anywhere nearby. Positionally it reads as VAT56's bottling, but every other batch in the manifest ages for at least ~2 weeks between fill and bottling — same-day fill-to-bottle would be a first. | Founder review needed: is this VAT56's bottling, and if so what's the real date (same-day, or does it belong to a later, undated event)? Excluded from the manifest pending confirmation. |
| WB-037 | open | Row 2035 ("31/07/2026 — Created Green Gold (gg01) - VAT53") records 41L drawn from VAT53 to produce 144x500ml "Green Gold" bottles, before VAT53's own 21-bottle Wildflower "remains" bottling (row 2040, 2026-09-01). | Implemented in code: `green_gold_records` manifest section, `Green Gold gin` workflow, replay/timeline events, timestamp-correction and `--verify-import` support (API-replay path only; the ORM-direct rebuild does not load it). **Still to do:** replay into `whistlebird_test`, run timestamp correction and `--verify-import` (expects 1 Green Gold gin execution), then map Xero "Green Gold" lines to `Green Gold - final product`. Caveat for founder: VAT53's maceration/distilling/aging dates are derived from its 2026-09-01 bottling date, yet Green Gold drew aged spirit from it on 2026-07-31 — VAT53's earlier step dates likely need correcting. |

## Stage 3: 2026-09-11 follow-up (VAT23/49-54, sheet re-pull)

Applied via `--apply-batches` against `whistlebird_test`, verified idempotent with
`--verify-import`/`--verify-manifest` (0 mismatches, 0 wording leaks, 0 incomplete
steps). Seven new executions loaded: VAT23 (WB-030), VAT49 (WB-035), VAT50 (WB-029),
VAT51 + VAT1051/Rosella (WB-031, Rosella side), VAT53, VAT54. Still excluded: VAT52
(WB-029/WB-031, two sub-issues), VAT55 and VAT57 (not yet bottled), the unlabelled
26-bottle line (WB-036), and Rosella VAT26's early-method confirmation (unchanged from
the 2026-09-07 rebuild). Green Gold (gg01) is tracked as WB-037; it has since been implemented in code
(see above) and awaits a replay.

## Stage 4: 2026-09-14 -- raw-material (botanical) purchase reconstruction

New manifest: `docs/whistlebird-raw-material-source.json` -- purchase-level curation for the
same post-legacy-cutoff window (2025-05-13 onward), covering the botanicals consumed by
every Wildflower/Solstice maceration step already loaded (Stage 3).

**Founder-confirmed methodology (2026-09-14):**
- Each distillation runs two multi-shot concentrates into one VAT, so real per-batch
  consumption is **2x** the founder's stated per-shot recipe quantity.
- Untracked (foraged, no purchase record): Wildflower's Lemon juice, Grapefruit (pink)
  juice, Lemon peel; Solstice's Kawakawa leaf, fresh orange peel, fresh orange juice.
- Supplier map: Alembics (Juniper Macedonia/Himalayan, Cinnamon, Liquorice root, Orris
  root, Coriander seeds, Hibiscus flowers, Lemon Myrtle, Elderflower), Davis Trading
  (Cardamom, Nutmeg), Moore Wilsons (Dried mango, Dried apples, Sumac Berries, Persian
  Black Limes), HB Malt Station (Dried orange peel).

**Clean tier (20 records):** real `jill@alembics.co.nz` order-confirmation emails --
orders #24600, #25053, #26770, #26930, #27558, #27804 (2025-08-10 through 2026-06-11).
Imported as dated receipts with quantity/price/supplier-batch-number, continuing the
legacy `ingredients_code` sequences (JBM004+, JBH004+, WNO006+, CIN002+, LR004+, COR005+,
ORR004+, LM006+, EF003+) -- not allocated to a specific consuming batch, same policy as
the legacy raw-material import (WB-018). Note: two of these orders' Nutmeg line items
came from Alembics even though the founder's current mental model has Nutmeg under Davis
Trading -- both suppliers evidently sold it at different times; kept as emailed.

**Inferred tier (110 records):** no email or database evidence exists for Hibiscus,
Cardamom, dried orange peel, Persian black lime, Sumac berries, Dried mango, Dried apple,
Green tea, or Szechuan pepper in this window. One record per consuming VAT, sized to that
VAT's own 2x-multiplied recipe requirement, dated 3 days before its maceration date,
supplier per the founder's list (updated same day to add Szechuan pepper -> Davis Trading
and Green tea -> Countdown/Woolworths), confidence `resolved_by_context`.

**Known gap, same shape as WB-037:** `_raw_material_records` in
`scripts/whistlebird_migration.py` only reads the legacy database's purchase tables --
there is no manifest-driven loader for this new file yet, and no mechanism to link a raw
material receipt as `actual_inputs` on a maceration step. The manifest above is data-only
until that script extension exists; not attempted in this pass.

## Stage 5: 2026-09-15 -- fixes surfaced by the real API-replay run

Replaying Stage 4's raw-material manifest through the live application API (rather than
direct ORM writes) surfaced a real, pre-existing gap: four Alembics batch numbers
(`MJUN-PP440328`, `PO786MAR22-1`, `WNUT-NMW-0-1000`, `LIQ-B401600`) are each reused across
two separate orders, and `inventory_items` enforces a `(org_id, name, supplier_batch_number)`
uniqueness constraint the ORM-direct script never actually exercised. Disambiguated the
second occurrence of each with a `-{internal code}` suffix, the same deterministic pattern
WB-017 already established for the legacy period -- the first (original) occurrence keeps
its real batch number unchanged. Affected: JBM005, JBH005, WNO007, LR005.

## Stage 6: 2026-09-15 -- API-replay framework replaces the ORM-direct loader

Per Johnny's direction, `whistlebird_test` is now loaded by two scripts instead of one:

1. **`scripts/whistlebird_replay.py`** replays every historical event (raw material
   purchase, execution/step, trial, customs lodgement) through the real application API
   -- the same routes, auth, validation, and business logic (including real inventory
   consumption) a browser hits. Ordering comes from
   `scripts/whistlebird_replay_timeline.py`'s date-prioritised topological sort over
   the same sources `whistlebird_migration.py` already reads.
2. **`scripts/whistlebird_replay_correct_timestamps.py`** runs after, and is the ONLY
   place a historical date gets applied -- directly at the database level, keyed off
   the same import markers. The live API is never given a backdating capability; this
   script is internal tooling for populating/resetting `whistlebird_test` only.

**No "derived"/`date_confidence`/`timestamp_policy` language reaches the loaded data.**
Verified by direct SQL sweep across every `execution_data`/`extra_data`/`details`
column in the org: zero matches. That curation trail lives only in this file and the
JSON manifests.

**Full verification, exact on every count**: `--verify-import` reports
`raw_material_items` 200/200, `Rosella gin`/`Solstice gin`/`Wildflower gin` 3/14/38
each exact, `customs_lodgements` 13/13, `date_mismatches` 0/0, `incomplete_batch_steps`
0/0, `wording_leaks` all 0. `build_import_verification`'s raw-material baseline was
extended to include the new manifest (previously only knew about the legacy DB).

**Real bugs found and fixed by going through the real API instead of writing around
it** (see `docs/whistlebird-replay-plan.md`'s "Real bugs found" section for detail):
a genuine flush-timing gap in `complete_step` that would affect any real user
completing a consumption-only step; two Alembics batch-number reuse collisions against
a uniqueness constraint the ORM-direct path never exercised; one legacy zero-quantity
data row; and the ORM-direct script's "quantity unknown" `actual_inputs` convention,
which the real endpoint correctly rejects (real consumption is now only ever reported
where an exact quantity is actually known).

The old `scripts/whistlebird_migration.py` `apply_*` functions remain as-is (used by
`--rebuild-whistlebird-test`'s bootstrap, and as the read-only source layer
`build_timeline()` itself reads from) -- this stage adds a parallel, API-driven loading
path rather than replacing the underlying data model.

## Stage 7: 2026-09-18 -- maceration step-1 inputs declared on the process template

Closes half of Stage 4's "known gap": `setup_product_workflows()` created every process's
Maceration/Rhubarb maceration step with `inputs=[]` (never passed to
`repository.add_step()`), so the process *definition* itself never declared what a batch
consumes -- distinct from `execution_steps.actual_inputs`, which Stage 6's replay already
populates per completed step. A user opening the process editor (or Johnny reviewing
"process structure") saw no botanicals on step 1 at all, regardless of what a given
execution's completed-step detail recorded.

Added the founder-confirmed recipe from `docs/whistlebird-raw-material-source.json`
(per-shot quantities, x2 per batch) as Wildflower/Solstice Maceration `inputs`, and the
aged-base-VAT + rhubarb inputs for Rosella's Rhubarb maceration -- `requires_inventory_selection:
true` for tracked botanical purchases and NGS, `false` for foraged ingredients never
purchased as tracked inventory (same tier split as Stage 4). No quantity is fabricated
where none is on record (rhubarb, the base VAT quantity).

`setup_product_workflows()` only ever added missing steps and skipped a process whose
step count already matched -- an already-created empty-inputs step could never pick up a
later definition change. Added a repair path (`repository.update_step`) so this reaches
existing rows; ran once against `whistlebird_test` (`inputs_repaired`: Wildflower/Solstice/
Rosella gin).

**Still open, unchanged from Stage 4:** linking a *specific* tracked-botanical purchase
receipt to a *specific* historical VAT's `actual_inputs` (beyond the "inferred" manifest
tier's already-linked entries) is a separate, larger exercise -- matching which purchase
lot fed which batch is a business-judgement call, not something this template change
attempts.

## Stage 8: 2026-09-17/18 -- label-batch numbering and a real FIFO sales-drain engine

Per Johnny's direction: Whistlebird buys pre-printed label rolls of 500. The first 500
bottles ever labelled for a product are physically "batch 1", the next 500 "batch 2",
and so on -- independent of which VAT produced them. He asked for this to be modelled
now (via the replay, on real historical data) so a future Xero-invoice sales sync has a
real batch identity to drain FIFO against, and asked me to check whether the CRM
module's existing "sales traceability" settings (`matching_strategy: fifo`,
`matching_key: batch_id`) already implement that draining.

**They don't.** `app/features/crm/models/sales_traceability_config.py` /
`sales_traceability_repo.py` is a config row only -- a toggle a user sets, with no
engine anywhere that reads it and actually walks batches. `app/initialize.py`'s
`workflow_execution_sales_mapping` table (the only other hit for "batch"/"fifo" in the
codebase) is dead legacy scaffolding from before the multi-tenant rewrite -- its
`create_*_table()` functions are only called from that file's own standalone `main()`,
never from the running app. There was nothing to "just connect."

**What this stage builds instead:**

1. **Batch numbering at Labelling** (`scripts/whistlebird_replay_timeline.py`'s
   `_assign_label_batches`): for each product line, sorts every batch by its real
   labelling date, then walks the cumulative bottle count in fixed 500-unit windows.
   Almost every VAT lands in exactly one label batch; a VAT whose run straddles a
   500-bottle boundary produces two (rare, but real -- e.g. Wildflower VAT6, VAT12,
   VAT18, VAT23, VAT43 and Solstice VAT45 all straddle a boundary in the current data).
2. **A real place to store it**: `complete_step` (`app/core/backend/backend.py`) now
   accepts an optional `batch_number` on any output, stored on the created item's
   `extra_data` -- generic, not Whistlebird-specific (any manufacturer tagging finished
   goods with a lot/run number can use it). `scripts/whistlebird_replay.py`'s labelling
   branch now posts one `actual_outputs` entry per label batch a VAT's bottles fall
   into, instead of one lump sum.
3. **A real FIFO drain**: `InventoryRepository.consume_final_product_fifo` (new) plus
   `POST /api/core/inventory/consume-fifo` (new) -- given a product name and a quantity,
   walks that product's final_product items oldest-batch-number-first, splitting across
   items when a request crosses a batch boundary, and refusing (no partial consumption)
   if on-hand stock is short. This is the landing point for the eventual Xero sync,
   which does not exist yet -- Johnny was explicit that connecting Xero is separate,
   future work. Nothing calls this endpoint automatically today.

**Verified against the live `whistlebird_test` target** (full reset -> replay -> 654
events issued -> timestamp correction -> `--verify-import`, all exact, same as Stage
6): Wildflower lands in 6 batches (five full 500s + a 413.5-bottle open batch 6),
Solstice in 2 (one full 500 + a 178.75-bottle open batch 2), Rosella in 1 (162.5
bottles, still filling batch 1) -- matching the previously-verified totals (2913.5 /
678.75 / 162.5) exactly. A live test call to `consume-fifo` for 600 Wildflower units
correctly drained all of batch 1 (500) then 100 units of batch 2, confirmed against the
DB, then the target was reset and replayed again from scratch so no test consumption
was left sitting in what is supposed to be a real, sales-free production history.

## Stage 9: 2026-09-18 -- explicit Wildflower/Solstice WIP chain and production prompts

The Wildflower and Solstice workflow definitions now model the physical hand-off at
every production stage: Maceration produces the two 1.8L / 20% ABV flasks (3.6L total),
Distilling consumes that charge and produces 2.16L Gin concentrate, Aging consumes the
concentrate plus its product-specific NGS/water fill and produces `Aged Gin`, Bottling
consumes that aged spirit, and Labelling & packaging consumes bottled product to create
the product-specific final stock. Process-template input references are resolved only
after the preceding output UUID exists, so rerunning setup also repairs the previously
created empty output/input/prompt fields without replacing populated historical data.

The API replay now mirrors the same WIP chain rather than only recording the Aging and
Bottling outputs. It records the required `VAT number` prompt on Aging from the global
VAT, and assigns each Wildflower/Solstice distillation a deterministic pair of flask
codes (`WBWF01`, `WBWF02`, ... / `WBSS01`, `WBSS02`, ...), ordered by that line's real
distillation date with global VAT as the stable tie-breaker. A two-flask distillation is
one execution step, so the pair is stored in its single `Flask code` text prompt.

The existing 500-label-roll allocation now applies at both Bottling and Labelling &
packaging: a VAT crossing a label-roll boundary emits one WIP bottled-product output per
label batch, and Labelling consumes all of those WIP items before producing the matching
batch-numbered final-product outputs. This prevents the excess from a boundary-crossing
VAT being stranded as unlabelled WIP while keeping the later FIFO sales drain aligned to
the physical labels.

## Stage 10: 2026-09-18 -- new sheet rows re-pulled, and real in-progress batches

Re-pulled the live "Production!!" tab (3,122 rows) against the manifest's prior curation
and found:

- **VAT56 (Wildflower, complete):** distilled/filled ~2026-09-01 (row 2041 "Distilled
  WF", row 2044 "Filling VAT56", neither dated separately -- derived). A new, clearly
  labelled "Bottled VAT56" / "78.5 bottled" (rows 2123-2124) supersedes the unlabelled
  "26 bottles" line the prior pull flagged as ambiguous -- the founder's later explicit
  label with a different total is the authoritative figure. That row carries no date of
  its own either; founder-confirmed 2026-09-17 (it sits right after VAT59's same-dated
  fill block).
- **VAT55/57/58/59 (Wildflower, genuinely in progress):** each distilled and filled, none
  bottled as of this pull (VAT59's fill, 2026-09-17, is the most recent activity in the
  whole tab). Founder's explicit instruction: import real in-progress work rather than
  waiting for it to finish, and keep it updated as the sheet does.
- **VAT52 stays excluded, unchanged** -- its two conflated sub-issues are a genuine
  labelling ambiguity (see the Stage-preceding excluded[] entry), not simple in-progress
  status, and need founder disambiguation rather than a pending marker.

Importing 55/57/58/59 as merely "excluded, awaiting bottling" (the prior convention)
would have meant three real, already-happened production steps per batch sitting nowhere
in the target -- not what "record live progress and update as we go" means. This needed
a real mechanism, not just more manifest rows:

- **New `ProductionBatch.pending_steps` (a frozenset, defaulting empty)** marks the step
  keys that haven't happened yet -- a manifest step spec of `{"pending": true}` instead
  of a date/confidence. `_load_manifest` requires this to be a *suffix* of the product
  line's step order (a step can't be done before one that precedes it) and raises loudly
  if it isn't, rather than silently reordering. Pending steps need no date at all.
- **`_batch_events` stops emitting `complete_step` events at the first pending step**,
  leaving the execution created and every real step completed, exactly like a real user
  mid-process -- `execution_steps` for the untouched tail simply don't exist yet in the
  target, not "completed with a fabricated date."
- **The ORM-direct `--rebuild-whistlebird-test` path has no pending-step awareness**
  (`apply_production_batches` always completed every step, unconditionally) --
  `zip(step_keys, exec_steps, strict=True)` would have marked an unfinished step
  COMPLETED. Rather than teach that already-lesser, already-behind path (it's documented
  elsewhere as missing dedicated-NGS purchases too) a second partial-completion mode, it
  now skips a pending batch entirely, and `build_import_verification` was taught to
  expect that skip only for that path's own check.
- **Real bug caught by the first live run, not a review:** `_enrich_ingredient_codes`
  rebuilt `ProductionBatch` field-by-field and silently dropped `pending_steps` for any
  batch that picked up raw-material ingredient codes -- exactly VAT55/57/58/59 once their
  own botanical purchases were added (below), so they wrongly completed bottling/
  labelling in the first full-pipeline attempt. Fixed by using `dataclasses.replace`
  instead of a manual field list, which structurally can't drop a field this way again.
  Regression-tested (`test_enrich_ingredient_codes_preserves_pending_steps`).

> **Superseded 2026-09-19:** the per-batch, exactly-sized purchases described below were replaced by whole-pack
> restocks that fan out across batches -- see `docs/whistlebird-replay-plan.md` "Real pack sizes".

**Botanical stock was already exhausted for these batches**, independent of the pending-
step work: `Cardamom pods`, `Green tea`, `Orange peel - dried`, `Hibiscus flowers`,
`Dried mango slices`, and `Dried apple ring` are never bought in bulk -- every prior
Wildflower VAT (27 through 53) already carries its own dedicated, exactly-sized
`resolved_by_context` inferred purchase for each of these six, dated 3 days before that
VAT's maceration (see e.g. `CP005`/`GRT003`'s `consumed_by`). VAT55/56/57/58/59 needed
the same treatment -- added 30 more inferred records (6 ingredients x 5 batches,
`CP015`-`CP019`, `GRT013`-`GRT017`, `OPD016`-`OPD020`, `HF017`-`HF021`, `DMS015`-`DMS019`,
`DAS015`-`DAS019`), same quantities and suppliers as every prior entry, dated 3 days
before each batch's own resolved maceration date. Checked a recent Alembics order
(#28585, 2026-09-15) first in case real evidence existed -- it covered Juniper/
Elderflower/Lemon Myrtle only, not these six, so `resolved_by_context` is correct, not a
shortcut.

**Verified against a full reset -> replay (684 events) -> timestamp-correction ->
`--verify-import` cycle**, all counts exact: Wildflower batch_executions 43 (up from 38),
`incomplete_batch_steps` 8 actual/8 expected (4 batches x bottling+labelling), raw_material_items
238 (up from 208). VAT57's execution_steps directly checked in the target: exactly
Maceration/Distilling/Aging rows, all COMPLETED, execution status IN_PROGRESS -- Bottling
and Labelling don't exist as rows yet, not "completed with a fake date."
