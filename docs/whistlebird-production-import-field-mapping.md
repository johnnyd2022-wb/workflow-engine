# Whistlebird production-history import — field mapping

Source row → Biz-E target. See `docs/whistlebird-production-import.md` for the model and
`docs/whistlebird-import-decisions.md` for how ambiguous cases were resolved.

## Cross-cutting

Every written row carries this JSON in the target's existing JSON field
(`inventory_items.extra_data`, `execution_steps.execution_data`,
`inventory_movements.movement_metadata`, `compliance_records.details`):

```json
{"import_ref": "wildflower-vat7:bottling", "batch_ref": "wildflower-vat7",
 "source_ref": {"table": "product_actions_bottling", "id": 11},
 "timestamp_policy": "derived_noon_pacific_auckland"}
```

Money/volume/ABV are `Decimal`. Quantities are stored in the target item's canonical unit.
A step also stores `date_confidence` (`clean` | `resolved_by_context` | `derived`) and its
resolved `step_date`.

## Raw-material inventory (no workflow)

| Source | Count | Target | Mapping |
| --- | ---: | --- | --- |
| `purchases_ingredients` | 57 | `inventory_items` (`raw_material`) + `ADD` movement | name, supplier, `ingredients_code`, `ingredients_expiry`; `ingredients_amount` → g. `purchase_date` = source date. |
| `purchases_empty_bottles` | 1 | same | `empty_bottles_stored` → units; `bottle_size_ml` → `extra_data`. |
| `product_actions_create_premix` | 4 | same (`raw_material`) | `alcohol_volume` → L; ABV/LAL/`container_id` → `extra_data`. Dilution prep, not a production step. |

Neutral grain spirit purchases (17, all of Southern Grain Spirits' real orders, 2023-04-24
onward) no longer come from the legacy `purchases_gns` table -- as of 2026-09-18 they're
`clean_records` in `docs/whistlebird-raw-material-source.json`, mapped the same way
(`quantity` → L, `abv` folded into the record). This is the one raw-material source the
API-replay path (`scripts/whistlebird_replay.py`) no longer needs legacy-DB access for;
see that manifest's `_comment` and `whistlebird_replay_timeline.manifest_ngs_receipts`.
The ORM-direct `--rebuild-whistlebird-test` path still reads `purchases_gns` directly and
is unaffected by this change.

Reused supplier batch codes get a ` (lot <id>)` suffix; the original code is kept in
`extra_data.recorded_supplier_batch_number`.

## Production batches (one execution per VAT)

| Step | Date source | Output item | Notes |
| --- | --- | --- | --- |
| Maceration | earliest `product_actions_flavors.date` for the vat's flavour batches (manifest `steps.maceration` for VAT27+) | — | inputs: matched ingredient receipts by code, quantity unavailable (not decremented) |
| Distilling | latest `product_actions_flavors.date` ("clearing"); manifest `steps.distilling` | — | |
| Aging | `product_actions_flavor_vat.date`; manifest `steps.aging` | `VAT batch` (`work_in_progress`, L) + `PRODUCTION` movement | `volume_amount` → L; ABV → `extra_data` |
| Bottling | first `product_actions_bottling.date` for the vat; manifest `steps.bottling` | `Bottled product` (`final_product`, units) | one `PRODUCTION` movement per bottling row, each on its own date; `estimated` flag preserved |
| Labelling & packaging | final bottling date (`derived`) | — | inputs: the bottled product |

Rosella replaces Maceration+Distilling with **Rhubarb maceration**, whose inputs include
the aged Solstice `VAT batch` item named by `rosella_base_vat`.

**Cross-boundary batches** (VAT23/24/26): the prior DB supplies maceration/distilling/
aging; the manifest supplies only the post-cutoff bottling. `_merge_batches` fills a
missing step from the manifest but never overwrites one the prior DB recorded.

## Trials (Distilling → Library stock)

| Source | Count | Workflow | Mapping |
| --- | ---: | --- | --- |
| `product_actions_flavor_experiments` `GG*` | 8 | GG gin trials | `clearing_amount`/`clearing_abv` → `execution_data`; `flavor_stored_ml` → library-stock item (mL) |
| `product_actions_flavor_experiments` `WB*` | 13 | WB recipe trials | same |
| `product_actions_samples_created` | 1 | WB recipe trials | bottles × size → library-stock mL |
| `product_actions_distillation_experiments` | 6 | SGS spirit trials | `alcohol_yield_l` → mL; ABV/LAL/used-L → `execution_data` |
| `product_actions_samples_consumed` | 8 | (matched by flavour code) | dated `ADJUSTMENT` movement on the library-stock item; consumed volume not recorded → quantity 0, flagged |

## Customs

| Source | Count | Target | Mapping |
| --- | ---: | --- | --- |
| `customs_lodgements` | 13 | `compliance_records` (`customs-alcohol` / `period-lodgement`, `record_type = lodgement`) | `date_period` → `period_start`/`period_end` and `period_label`; `lal` → `measured_value`; volume/ABV/bottles → `details`. Title: `Customs lodgement — <period>`. |

## Not imported

`sales_product`, `buyers`, `crm_*`, `audit`, `inventory`/`monthly_totals`,
`product_actions_ex_stock_storage`, `product_actions_ethanol` — out of scope for the
production-history load (sales/CRM reconcile from Xero; snapshots would double-count).

## Repeatable reset

`scripts/whistlebird_migration.py --confirm-reset-whistlebird-test` deletes tenant-scoped
Core/CRM/Compliant data for the exact `Whistlebird Ltd` org, preserves the org, admin
users, trusted devices and 2FA, and verifies every reset table is empty before committing.
