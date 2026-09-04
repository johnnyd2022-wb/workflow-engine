# Whistlebird v1 → Biz-E migration plan

## Objective

Create a repeatable, tenant-scoped migration into a new `whistlebird_test` organisation in `workflow-engine-test`. It must preserve every meaningful v1 record, retain source provenance, and make the supported history usable for Biz-E traceability and compliance review.

This is a migration-development environment only. The source database is read-only. Reset operations will delete data for `whistlebird_test` only and will refuse any other organisation name.

Historical rows use their actual legacy business date in every target date field. For target columns that cannot be a date (for example `executions.started_at`), the importer derives a noon `Pacific/Auckland` timestamp on that same business date and labels it as derived in provenance metadata.

## Audit outcome

The completed validation must demonstrate the documented chain where v1 data supports it:

```text
supplier purchase / ingredient batch
  → flavour or intermediate batch
  → bottling batch / finished product
  → sales record or Xero invoice line
```

It will also identify records needed for NP3 that were never represented in v1, rather than fabricating them. Biz-E's existing compliance controls cover competency, hygiene, trace-and-recall, corrective actions, and the relevant Customs reconciliation records.

## Migration stages

1. **Profile (read-only)**
   - Capture schemas, exact row counts, date ranges, null rates, distinct batch/name values, and candidate free-text links.
   - Produce only aggregates and pseudonymous identifiers in committed reports; source PII and database dumps stay outside the repository.
   - Run the reusable preflight tool with `WB_LEGACY_DATABASE_URL` and `BIZE_MIGRATION_DATABASE_URL` set in the shell: `uv run python scripts/whistlebird_migration.py --output /safe/local/path/profile.json`. It performs no writes.
   - Use `--dry-run-core`, `--dry-run-production`, and `--dry-run-traceability` before every import iteration; none writes to either database.

2. **Map and approve**
   - Maintain a field-level mapping registry with legacy table/ID, target entity, transformation, units, timestamp/date policy, and validation rule.
   - Mark unresolved mappings in [`whistlebird-findings.md`](../whistlebird-findings.md). No unknown record is silently discarded.

3. **Prepare target tenant**
   - Create `whistlebird_test`, never reusing `whistlebird-test` or the existing Whistlebird organisation.
   - Configure Compliant for spirits (including gin liqueur), require Core source references, and exclude the trade-waste framework. The council/verifier audit is NP3-related; Google Sheet evidence is a later import stage.

   The reproducible setup command is `--rebuild-whistlebird-test`. It first runs every
   read-only preflight, then creates only this exact tenant and its deterministic test admin
   if absent, resets only this tenant's imported data, replays both migration stages, and
   fails if either verification report differs from its source counts. The password is required
   from `WHISTLEBIRD_TEST_ADMIN_PASSWORD`; it is never committed or printed. The default login
   email is `whistlebird_test_admin@whistlebird.test` and can be changed with `--admin-email`
   before the tenant is first created.

   ```bash
   export WHISTLEBIRD_TEST_ADMIN_PASSWORD='store-this-in-your-password-manager'
   uv run python scripts/whistlebird_migration.py --rebuild-whistlebird-test
   ```

4. **Import core history in dependency order**
   - Suppliers and purchases → tenant-scoped raw-material inventory items, supplier batches, expiry dates, and opening/addition movements.
   - Flavour, vat, premix and distillation actions → processes, executions, execution steps and work-in-progress outputs, preserving batch identifiers and source IDs.
   - Bottling/ex-stock actions → final-product inventory items and production movements linked to their execution outputs.
   - Customs lodgements → `compliance_records` with original period, LAL and source provenance.
   - CRM notes/tasks may be imported only after Xero contacts are present and identity matching is reviewed.

   Historical operational actions are represented as completed executions of clearly labelled templates such as `Legacy ingredient receipt`, `Legacy flavour preparation`, `Legacy flavour vat`, `Legacy distillation`, and `Legacy bottling`. Each execution records its actual inputs and outputs, so normal Core forward/backward tracing follows the migration chain rather than a separate reporting model.

5. **Connect Xero, then reconcile sales**
   - Use Biz-E's authorised Whistlebird Xero connection to import contacts and invoices. OAuth tokens are never copied from v1.
   - Backfill `product_mappings` from the reviewed sales-product descriptions and finished-product outputs.
   - Reconcile v1 sales records against Xero invoice lines and batches. Ambiguous, missing, and duplicate matches remain review items.

6. **Validate and prove repeatability**
   - Dry-run reports every proposed create/update/skip without writing.
   - Existing target JSON provenance makes reruns idempotent by legacy table + legacy ID; no migration-specific schema is introduced.
   - Scoped reset and re-import produce identical row counts, provenance links, inventory totals, LAL totals, and traceability results.
   - Generate a verifier-friendly reconciliation report with coverage and exceptions.

## Non-negotiable migration rules

- Never alter the legacy database.
- Every generated target row carries legacy table/ID, source date and transformation metadata in existing JSON fields.
- Use normal Biz-E repositories/services where possible so inventory quantity guards, event records and tenant isolation remain effective.
- A target timestamp derived from a legacy `DATE` is labelled as derived and set to **12:00 Pacific/Auckland**; the original date remains available.
- No external Xero operation, email, or production-system mutation is performed by the migration tooling.
- Reset is protected by the exact organisation name and an explicit `--confirm-reset-whistlebird-test` flag.

## Initial mapping inventory

| Legacy source | Target direction | Notes |
| --- | --- | --- |
| `suppliers`, `purchases_ingredients`, `purchases_gns`, `purchases_empty_bottles` | raw-material inventory and additive movements | Retain supplier, batch/code, purchase/expiry dates and ABV metadata. Units requiring conversion are validated before write. |
| flavour/vat/premix/distillation action tables | process/execution/WIP inventory | Batch links are free text and need linkage review. |
| `product_actions_bottling`, `product_actions_ex_stock_storage` | finished-product inventory and production movements | Preserve bottle size, ABV, bottle/vat batch and LAL. |
| `sales_product` | Xero reconciliation + sales traceability | There is no direct target equivalent for a legacy sale independent of Xero; map only after the authorised Xero sync. |
| `customs_lodgements` | Customs compliance records | Importable with original dates and declared values. |
| legacy audit/CRM tables | provenance and reviewed CRM migration | Secondary evidence only; never assumed to be a transaction source. |
