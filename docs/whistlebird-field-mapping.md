# Whistlebird v1 → Biz-E field mapping

This is the working mapping registry for the migration. A row marked **hold** must not create
an operational quantity or traceability edge until its corresponding finding is resolved.

## Cross-cutting rules

Every imported record retains the following JSON provenance in an existing target JSON field
(`inventory_items.extra_data`, `execution_steps.execution_data`, or
`compliance_records.details`):

```json
{
  "source_system": "whistlebird_v1",
  "legacy_source": {"table": "<table>", "id": "<integer>"},
  "legacy_date": "YYYY-MM-DD",
  "timestamp_policy": "derived_noon_pacific_auckland"
}
```

`legacy_date` is authoritative. `created_at`, `started_at`, and `completed_at` must only use the
derived noon `Pacific/Auckland` instant when the target requires a timestamp. The v1 database has
no timestamp columns.

Money and LAL are parsed with `Decimal`, never binary float. Quantities are stored in the target
item's canonical unit, and every movement uses the same canonical unit.

## Operational mapping

| v1 table | Count | Biz-E destination | Mapping | Status |
| --- | ---: | --- | --- | --- |
| `suppliers` | 9 | raw-material metadata | Preserve supplier name/type/contact details only where needed by a purchased inventory item. No standalone supplier table exists in Biz-E. | ready |
| `purchases_gns` | 9 | `inventory_items`, `inventory_movements` | One GNS raw-material batch per source row. `gns_purchased_l` → L; ABV, supplier and legacy ID → `extra_data`; source date → purchase date and derived movement time. | ready |
| `purchases_empty_bottles` | 1 | `inventory_items`, `inventory_movements` | One packaging raw-material item; `empty_bottles_stored` → units; `bottle_size_ml` retained in metadata. | ready |
| `purchases_ingredients` | 57 | `inventory_items`, `inventory_movements` | Ingredient, supplier, code and expiry map directly; form code confirms `ingredients_amount` is grams. | ready |
| `product_actions_flavors` | 53 | WIP inventory + execution | Create/import a flavour-preparation execution. Flavour batch/code and ingredient-code text remain provenance; mL fields are stored as mL. | ready |
| `product_actions_flavor_vat` | 26 | WIP inventory + execution | Transform the named flavour batch into the vat batch. `volume_amount` is L; ABV and batch IDs become output metadata. All 26 rows have a recovered flavour-batch link. | ready |
| `product_actions_create_premix` | 4 | WIP inventory + execution | `alcohol_volume` → L and `alcohol_abv`/LAL/container ID → metadata. No source batch input is recorded, so no input edge is invented. | imported — source-only |
| `product_actions_distillation_experiments` | 6 | WIP inventory + execution | Input/output litre values, ABVs, LAL, experiment ID, and flavour-code references become execution data. Exact flavour-code edges are imported; alcohol inputs without a recorded source batch remain provenance only. | imported — partial lineage |
| `product_actions_bottling` | 27 | finished-product inventory + production movement | `bottles_stored` → units; bottle size, ABV, vat batch and bottle batch remain product/batch metadata. All vat batches have a v1 flavour-vat match. | imported — sales link pending |
| `product_actions_ex_stock_storage` | 1 | finished-product inventory + production movement | Finished-product quantity in units, with product/storage/batch fields retained as metadata. No input batch is recorded. | imported — source-only |
| `product_actions_flavor_experiments` | 21 | WIP inventory + execution | A flavour intermediate created from clearing mL/ABV and referenced by subsequent distillation experiments through its flavour code. | ready |
| `product_actions_samples_created` / `product_actions_samples_consumed` | 1 / 8 | completed historical sample executions | Preserve bottle count, ABV, size and LAL. Import the eight source-evidenced flavour-code links; do not fabricate inventory output or consumption quantities. | imported — one source-only record |
| `product_actions_ethanol` | 0 | — | No source rows. | no action |
| `inventory`, `monthly_totals` | 1 / 20 | validation only | These are snapshots/aggregates; importing them as movements would double count operational history. Compare them against the imported ledger instead. | ready |
| `customs_lodgements` | 13 | `compliance_records` | One `customs-alcohol/period-lodgement` record per source row, retaining period, volume, ABV, LAL, bottle count and legacy ID. | ready |

## Sales and CRM mapping

| v1 table | Count | Biz-E destination | Mapping | Status |
| --- | ---: | --- | --- | --- |
| `sales_product` | 315 | Xero invoice reconciliation + `product_mappings` | 312 rows contain 391 structured product entries with quantity, bottle batch, size, ABV, LAL and pricing. These are reconciled with authorised Biz-E Xero invoice lines; no direct invoice rows are invented. | post-Xero |
| `products` | 0 | `product_mappings` | Empty; use reviewed sales payload product keys and Xero line descriptions instead. | post-Xero |
| `buyers`, `crm_customers` | 86 / 125 | `xero_contacts` then CRM | Match after Xero sync by Xero contact identity, then reviewed name/email/address fallback. No v1 customer becomes an independent target contact before this stage. | post-Xero |
| `crm_follow_ups`, `crm_logs`, `crm_tasks` | 35 / 64 / 0 | `crm_tasks`, `crm_notes` | Create only when a reviewed target contact is resolved. Dates become due/created dates and source text remains attributed provenance. | post-Xero |
| `audit` | 1,100 | provenance only | Secondary corroboration, not a source of operational movements or sales. | ready |
| `emails`, `sales_product_samples` | 0 / 0 | — | No source rows. | no action |

## NP3 and Customs evidence boundaries

- Import supported operational traceability and Customs lodgements.
- Do **not** manufacture hygiene, cleaning, maintenance, staff competency, sickness, pest, mock-recall or corrective-action records: v1 has no dedicated source for them.
- The post-import validator will generate the exact missing evidence list for the `np3-food-control` controls.
- v1 has no document-storage table or file reference, so non-database evidence must be inventoried separately before audit completeness is asserted.
- `inventory` and `monthly_totals` are validation snapshots only; they never create compensating target movements.
- Production actions end in May 2025 while sales run to May 2026. The later sales period is explicitly outside the v1 production-chain coverage until supplemental operational history is imported.

## Repeatable reset

`scripts/whistlebird_migration.py --confirm-reset-whistlebird-test` deletes tenant-scoped Core,
CRM and Compliant data for the exact `whistlebird_test` organisation. It preserves the organisation,
admin users, trusted devices and 2FA backup codes. The command rejects every other organisation
name and verifies that all reset tables are empty before committing.
