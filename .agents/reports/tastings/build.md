# Tastings backend build

Status: backend implemented; UI/template/design options belong to the orchestrator.
Branch: feat/tastings. No commit, push, merge request, approval, pane messages or production DB access performed by this builder.

## Delivered

- `/crm/tastings` renders `tastings/index.html` using Tastings' feature template directory and `active_page='crm'`. Root supplies that template and its CRM static JS/CSS.
- Sales navigation exposes Tastings only for active NZ Alcohol subscribers. Endpoint access policy requires `sales.view` / `sales.record`, dispatch additionally requires `inventory.adjust`. All ten endpoint/method pairs are explicitly blocked for selected-site staff.
- Org-scoped events and allocations, dedicated tasting stock ledger, explicit tasting purpose, conservative source eligibility. Production outputs and declared opening stock are eligible; customer title, legacy ownership markers, order-linked output, receipt fragments, raw/WIP and Library markers are rejected at physical dispatch (and most at selection/planning). Whole counted packs and known pack conversion are mandatory.
- One CRM task per event. Due date is NZ start date, rep/contact/title/status synchronized atomically. Existing Sales and Core calendar readers receive it; clicks route to Tastings, generic task edits/delete/lane writes reject it. Database composite `(org_id,task_id)` FK plus unique task association enforce ownership.
- Planning is soft, not a physical reservation/removal. Dispatch accepts a bounded idempotency key and explicit actual date. Event, provenance, org/site, inventory and pool rows lock in stable order; all debits, signed `InventoryMovement` rows, removal evidence, task projection and EventWriter events commit or roll back together. Replay creates no extra movement/removal/event.
- Leftovers use decimal mL. Initial/remaining/reserved values obey a database conservation constraint. Finalisation records measured usage, allowing partial bottles. Reuse reserves available pool stock without another warehouse debit or excise reader identity. Cancellation releases reservations and never returns stock into warehouse/bond or reverses liability. Changed completed outcomes fail409.
- Every newly removed lot freezes product, pack, batch/lineage, ownership, actual date, source CCA/location, ABV provenance, tariff, applicable dated rate, duty/levy/GST and actor. DB trigger prevents changing any historical lot field except remaining/reserved mL. Unknown duty facts remain explicit frozen problems; missing volume/source authority blocks dispatch.
- Both excise adapters consume the same lot identity. The legacy draft uses frozen basis instead of live profile/rates, keeps separate rounded recorded lines, and carries late captures by immutable tasting-stock reference including original duty/levy/GST into the next open entry. Missing or late unresolved facts block false nil/complete lodgement. Per-CCA register/source-period review shows the same captured removals under the source CCA, retaining complete_lodgement=false/nil_return=None/total_duty=None.
- Sources already outside legacy licensed stock need an attributable prior out-transfer; their pool records retain that earlier removal date/reference, create no second removal reader row, and explicitly show prior_removal_recorded rather than paid. Received multi-site fragments remain excluded.
- Emits `tasting.created/updated/dispatched/completed/cancelled`, matching `crm_task.created/updated`, and canonical `inventory_item.quantity_adjusted` with before/after/delta/item snapshot for warehouse debits, for audit and LiveSync/cache invalidation.

## HTTP contract

Normal auth/tenant middleware and CSRF apply. Errors are `{error: text}` with400 validation,403 role,404 unavailable/not-found,409 lifecycle/idempotency/stock conflict.

- GET `/api/crm/tastings?start=YYYY-MM-DD&end=YYYY-MM-DD`: exclusive-end <=93-day window, default first NZ month-day through62days; `{tastings:[summary],truncated}`. At most200 summaries; rep names resolved in one bounded batch.
- GET `/api/crm/tastings/choices?q=&offset=0`: escaped literal name/email search <=100chars; each collection <=50; `{reps:[{id,name}],contacts:[{id,name}],stock:[{id,name,quantity,unit,batch}],has_more}`. Pagination offset <=100000. Server rechecks authority under dispatch locks.
- GET `/api/crm/tastings/pool?offset=0`: `{lots:[poolLot],has_more}`, at most50 nonempty lots. Each lot includes product/batch, purpose=tasting, canonical quantity/unit, initial/remaining/reserved/available mL, removed_on, duty_status, immutable basis.
- GET `/api/crm/tastings/<id>`: `{tasting:detail}`.
- POST `/api/crm/tastings`:201 `{tasting:detail}`; PUT `/api/crm/tastings/<id>`:200. Body `{title,venue_name,venue_address,venue_type:'own'|'external',licence_reference?,starts_at,ends_at,rep_id,contact_id?,notes?,allocations:[{source_item_id OR source_pool_id,quantity}]}`.0–20 unique sources when planning; dispatch requires 1–20. Warehouse quantity is canonical units; pool quantity is mL. Updates may omit unchanged fields. Times must be explicit valid NZ offset ISO timestamps, end after start within7days. Only planned events editable.
- POST `/api/crm/tastings/<id>/dispatch`: body `{actual_date:'YYYY-MM-DD'}`, header `Idempotency-Key`<=100chars, no future date;200 `{tasting:detail}`.
- POST `/api/crm/tastings/<id>/finalise`: body `{usage:[{allocation_id,used_volume_ml}],samples_count?,notes?}`. Exactly every allocation once; used mL0..reserved, max4decimalplaces; samples_count0..1000000.200 `{tasting:detail}`. Same outcome replay succeeds, changed replay409.
- POST `/api/crm/tastings/<id>/cancel`: emptyJSON body;200 `{tasting:detail}`. Completed events cannot cancel.

Summary includes id/task_id/rep_id/contact_id/rep_name, event/venue/text/status fields, timestamps, dispatched_on, actor IDs and href `/crm/tastings?tasting_id=<id>`. Detail adds allocations `{id,source_item_id,source_pool_id,stock_lot_id,quantity,reserved_volume_ml,used_volume_ml,state,product,batch,unit,duty_status,basis}`; immutable evidence remains visible after pool pagination/complete consumption.

## Isolated test database and migration

Shared test DB `workflow-engine-test` was stamped `contract_dispatch_001`, absent from fresh main. Its stamp/schema/data were NOT changed. A metadata-only baseline attempt exposed a pre-existing operational-case single-item CHECK generation defect, so it was abandoned in a separate unused scratch DB `workflow_tastings_scratch`; no app code was changed for that issue.

Working isolated DB: **workflow-engine-test_tastings_build**, suffix **tastings_build**. This was created empty and populated with a schema-only `pg_dump` from the local/test container (`workflow-engine-test-db`, Postgres16); no production connection or data copied. Only this scratch DB was stamped to cca_transfers_001. Alembic autogenerate created tastings_001; all unrelated schema drift was removed. Composite task FK/index and immutable-basis trigger are explicit additive hardening. The migration revises cca_transfers_001 and reverses cleanly. Up/down/up ran successfully entirely on scratch. Shared test DB remains untouched.

To use this isolated DB with normal config: `ENVIRONMENT=test PYTEST_XDIST_WORKER=tastings_build ...` (local config uses same database base name). The builder used wrappers setting config.config['database']['name'] before importing engine/pytest to avoid xdist's worker harness side effects:

- `/tmp/tasting_alembic.py`: `PYTHONPATH=. ENVIRONMENT=test uv run python /tmp/tasting_alembic.py upgrade head` / `downgrade cca_transfers_001`.
- `/tmp/tastings_pytest.py`: `PYTHONPATH=. ENVIRONMENT=test uv run python /tmp/tastings_pytest.py <pytest args>`.

All live screenshot seeding may now use suffix tastings_build; do not downgrade/drop/recreate the shared DB.

## Verification

- Initial related regression set: **124 passed**,52 existing Flask-Limiter warnings,54.71s. Suites: Tastings, excise, CCA movement excise, Sales excise, Core tasks, page registry, selected-site staff roles.
- Expanded regression set includes access policy: **140 passed**,57 existing warnings,61.95s. A prior expanded run had139passed plus one test formatting assertion (`'-2.0000'` vs `'-2'`); corrected test to compare exact Decimal value, preserving actor/event/count checks. It was not an application failure.
- Final dedicated feature suite after the last actor/provenance capture and Library eligibility changes: **24 passed**,1 existing Flask-Limiter warning,6.36s. Covers HTTP subscription/role/CSRF/hostile org, same-org references, time/bounds validation, atomic rollback, simultaneous warehouse/pool dispatch, idempotency and changed replay, partial-bottle outcomes/reuse/cancellation, frozen profile/rates, rate rollover, own venue, late/unresolved capture, active CCA grouping/review, separate Library markers, signed movement/event replay and DB immutability.
- Ruff on changed Python application/tests passes; `node --check app/features/crm/frontend/js/tasks-calendar.js` passes.
- Migration logs: `/tmp/tasting-final-down.log`, `/tmp/tasting-final-up.log` (up/down/up prior logs `/tmp/tasting-migration-up.log`, `/tmp/tasting-migration-down.log`, `/tmp/tasting-migration-up2.log`).
- Test logs: `/tmp/tasting-final-verified-tests.log`, `/tmp/tasting-final-feature-tests.log`.

## Explicit limits / review notes

- UI page template/assets and screenshot scenarios are intentionally root-owned and not provided here. No UI browser test performed by this backend builder.
- This is a recorded liability, never a claim of duty payment, filing or automatic remission. Modern per-CCA remains an observed register, as existing code requires.
- No automatic return-to-bond, duty credit, stock-to-sales conversion or post-finalisation correction flow. Completed outcomes immutable by design.
- Existing role registry and normal org tenant middleware still gate all APIs. New source/reference validations are explicit; the task ownership and source/pool ledger edges additionally have same-org database composite constraints.
- Legacy prior-removal stock uses the existing immutable-in-application out-transfer ledger; dispatch does not invent a new transfer or re-enter that liability. Warehouse source provenance cannot be inferred from a product suffix.
