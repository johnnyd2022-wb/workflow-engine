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
- **Green Gold (gg01) trial output** (row 2035: 41L drawn from VAT53 to make 144x500ml
  bottles) uses the already-provisioned `GG gin trials` workflow but has no import path
  yet — `apply_trial_batches`/`_trial_records` only reads trials from the legacy
  database, and the sheet manifest has no equivalent section. Needs a script change
  (a sheet-sourced trial manifest, mirroring how `records`/`excluded` work for batches)
  before it can be imported; tracked here as a follow-up, not folded into this pass.

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
| WB-037 | open | Row 2035 ("31/07/2026 — Created Green Gold (gg01) - VAT53") records 41L drawn from VAT53 to produce 144x500ml "Green Gold" trial bottles, before VAT53's own 21-bottle Wildflower "remains" bottling (row 2040, 2026-09-01). The `GG gin trials` workflow already exists (`GG_TRIAL_WORKFLOW` in `scripts/whistlebird_migration.py`), but `apply_trial_batches`/`_trial_records` only ever reads trials from the legacy database — there is no manifest-driven path for a sheet-sourced trial. | Needs a script change: add a sheet-trial section to the manifest (analogous to `records`/`excluded` for batches) and a loader that feeds it into `apply_trial_batches`, referencing VAT53 as the consumed input the same way `rosella_base_vat` references a base VAT today. Not folded into this pass — VAT53's own bottling is imported; the Green Gold output is not. |

## Stage 3: 2026-09-11 follow-up (VAT23/49-54, sheet re-pull)

Applied via `--apply-batches` against `whistlebird_test`, verified idempotent with
`--verify-import`/`--verify-manifest` (0 mismatches, 0 wording leaks, 0 incomplete
steps). Seven new executions loaded: VAT23 (WB-030), VAT49 (WB-035), VAT50 (WB-029),
VAT51 + VAT1051/Rosella (WB-031, Rosella side), VAT53, VAT54. Still excluded: VAT52
(WB-029/WB-031, two sub-issues), VAT55 and VAT57 (not yet bottled), the unlabelled
26-bottle line (WB-036), and Rosella VAT26's early-method confirmation (unchanged from
the 2026-09-07 rebuild). Green Gold (gg01) trial output tracked as WB-037, needs a
script change before it can be imported at all.

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
