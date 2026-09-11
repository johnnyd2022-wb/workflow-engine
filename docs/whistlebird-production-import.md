# Whistlebird production-history import

`scripts/whistlebird_migration.py` loads Whistlebird's real production history into a
`whistlebird_test` organisation in `workflow-engine-test` so the tool shows what the
business has actually done, from two frozen sources:

1. **The prior inventory database** (`WB_LEGACY_DATABASE_URL`, read-only). Covers
   ingredient/GNS/bottle purchases, Wildflower batches VAT1–25, the first Rosella vat
   (VAT26), the 2023–2025 recipe/distillation trials, and every Customs lodgement.
2. **A curated per-batch manifest** — `docs/whistlebird-production-sheet-source.json`,
   a human-reviewed snapshot of the founder's "Production!!" Google-Sheet tab. Covers the
   post-cutoff batches (Solstice VAT27+, later Wildflower, the Rosella-from-Solstice
   conversion) that exist in no database.

The data is treated as **live production history**: no row it writes carries the words
"legacy", "historical", "migration" or "v1". A small machine-only `import_ref` marker on
every written row is the only trace, and it exists purely so a scoped reset-and-replay is
exact.

## Model

**One workflow per product; one execution per VAT batch.** Each batch execution walks its
workflow's steps in order and every step is stamped with its own real date.

| Workflow | Steps | Batch source |
| --- | --- | --- |
| **Wildflower gin** | Maceration → Distilling → Aging → Bottling → Labelling & packaging | prior DB VAT1–25 + manifest continuations/new |
| **Solstice gin** | Maceration → Distilling → Aging → Bottling → Labelling & packaging | manifest only (VAT27+) |
| **Rosella gin** | Rhubarb maceration → Aging → Bottling → Labelling & packaging | prior DB VAT26 + manifest VAT48 conversion; the rhubarb step consumes an aged Solstice VAT batch |
| **GG gin trials** | Distilling → Library stock | prior DB `product_actions_flavor_experiments` GG* |
| **WB recipe trials** | Distilling → Library stock | prior DB `flavor_experiments` WB* + `samples_created` |
| **SGS spirit trials** | Distilling → Library stock | prior DB `product_actions_distillation_experiments` |

- **Step dates.** Maceration = earliest flavour-prep date; Distilling = latest
  flavour-prep ("clearing") date; Aging = VAT-fill date; Bottling = first bottling date;
  Labelling = the final bottling date. Aging therefore spans distilling → bottling.
- **`derived` dates.** When a source records no separate event for a step, that step
  inherits the nearest recorded step's date and is flagged `date_confidence: "derived"`
  on the row. Step timestamps are clamped non-decreasing so they never run backwards.
- **Raw materials** (ingredients, GNS, bottles, premix prep) load as dated
  `raw_material` inventory items with an `ADD` movement — **no workflow, no execution**.
- **Customs lodgements** load as NZ-alcohol compliance records
  (`customs-alcohol` / `period-lodgement`) with their real periods.
- **Trial sample consumption** rows become dated adjustment movements against the trial's
  library-stock item; consumed volumes are not recorded in the source and are not invented.

## Provenance marker

Every written `inventory_items.extra_data`, `execution_steps.execution_data`,
`inventory_movements.movement_metadata` and `compliance_records.details` carries:

```json
{"import_ref": "<batch/step key>", "batch_ref": "<batch key>",
 "source_ref": {"table": "...", "id": 123}, "timestamp_policy": "derived_noon_pacific_auckland"}
```

`batch_ref` groups a batch's steps; the apply actions skip a batch/trial/item/lodgement
whose marker already exists, so every action is re-runnable.

## Commands

```bash
export WB_LEGACY_DATABASE_URL='postgresql://wb_admin:whistlebird@localhost:5401/whistlebird_inventory'
export BIZE_MIGRATION_DATABASE_URL='postgresql://workflow_rw:<db password>@localhost:8401/workflow-engine-test'
export WHISTLEBIRD_TEST_ADMIN_PASSWORD='<store in your password manager>'

# read-only
uv run python scripts/whistlebird_migration.py --dry-run-core
uv run python scripts/whistlebird_migration.py --dry-run-production
uv run python scripts/whistlebird_migration.py --dry-run-manifest
uv run python scripts/whistlebird_migration.py --verify-import

# full rebuild: preflight → create tenant if absent → scoped reset → replay → verify
uv run python scripts/whistlebird_migration.py --rebuild-whistlebird-test
```

Individual apply actions (`--setup-workflows`, `--apply-raw-materials`, `--apply-batches`,
`--apply-trials`, `--apply-customs-lodgements`) exist for iterating. Every write action
refuses any `--org-name` except `whistlebird_test`; `--confirm-reset-whistlebird-test`
deletes only that tenant's loaded data and preserves its org, users and 2FA.

## Non-negotiable rules

- Never write to the prior database or the Google Sheet.
- Every written row carries the `import_ref` marker and a `date_confidence` per step.
- A target timestamp derived from a source `DATE` is set to **12:00 Pacific/Auckland**.
- No step date, quantity, or bottle count is fabricated: unknowns are `derived`/`None`
  and flagged, or the batch is excluded (see `docs/whistlebird-import-decisions.md`).
- Reset is guarded by the exact `whistlebird_test` name and its explicit flag.

## Outstanding review

Per-batch **maceration and distillation dates for VAT28+** currently load as `derived`
(inherited from the recorded VAT-fill/bottling date) except where a specific step date
was recoverable from context. The "Production!!" tab records those events but with mixed
date formats — spreadsheet date serials sometimes day/month-swapped — and several
self-contradictions; each is resolved by chronological fit against its neighbours, not a
single global format assumption. VAT27 and all prior-DB batches (VAT1–26, trials) already
have real per-step dates. Five batches remain excluded pending founder confirmation
(VAT52, VAT55, VAT57, and an unlabelled bottling line) and the Green Gold trial output
needs a script change before it can be imported at all — see the decisions log.
