# Customer raw materials (7.2b)

The first contract-owned seam is `services/materials.py`. It supplies a frozen scope
from the persisted execution, its assignment, order and line. Customer IDs and owner
tags from a request are never authority. Unassigned production uses producer materials;
assigned raw inputs follow the line's producer/customer/mixed declaration. An owner
must match both the organisation and the order's customer. A different customer's lot
is rejected even when it has the same name, supplier batch or product output.

The policy applies sourcing declarations to raw materials. Finished goods and WIP stay
producer-owned until an explicit title decision is recorded. Customer title remains
unresolved; neither input ownership nor the duty payer settles it. Customer-owned
non-raw stock is closed in this slice.

## Transaction seam

Production must lock Step → Execution → Order → Organisation/Site → sorted Inventory
IDs, then validate all selected and reconciliation inputs before any debit or output
deposit. `resolve_execution_material_scope` locks Execution → Order, including the
absence of an assignment. Contract linking/unlinking now uses that same lock order.
Order status changes and line edits lock Order without subsequently locking Execution.
Completed/cancelled orders cannot authorize new production consumption.

`validate_execution_materials` resolves scope and validates every selected input plus
every output reconciliation lot. It does not commit or mutate quantity. It rejects a
missing ownership column and legacy owner metadata, rather than treating missing data
as producer title. Site checks remain in the generic site preflight.

The concurrency regression holds an unassigned execution's preflight transaction while
another database transaction attempts to link it. PostgreSQL blocking PIDs prove the
writer waits; the first scope remains producer-only, and the next transaction sees the
committed customer assignment. No cached assignment or caller owner can override it.

## Recorded receipts and immutable raw title

The next stock slice adds `InventoryItem.contract_customer_id`: NULL explicitly means
producer-owned; a UUID references a same-organisation contract customer. Existing stock
stays producer-owned. Historical owner hints in JSON remain unresolved and cannot be
consumed, moved, valued as producer acquisitions or offered for ordinary sales.

`ContractMaterialReceipt` records a same-org customer, staff actor, source evidence,
quantity/unit and a frozen stock snapshot. The staff receipt service accepts an active
customer path, validates inventory.adjust, site/location and units, takes an idempotency
lock, and creates a distinct raw lot and audit event in one transaction. Duplicate names,
supplier batches and supplier barcodes do not merge receipts or customers. Supplier
barcodes remain metadata; the internal stock UUID identifies the physical fragment.
Generic inventory/opening/import paths cannot set customer title or receipt proof.

Database and ORM guards make owner and receipt evidence immutable. Customer stock is
raw-only and cannot be deleted, relabelled or converted into untracked reconciliation
stock. An initial owned lot requires its matching material receipt; a transfer fragment
requires its dispatch/receipt proof. Existing supplier/lineage facts stay immutable.

## Consumption and movement conservation

The completion repository resolves the trusted scope before site/stock locks and
validates every input and reconciliation lot before any write. Customer debits require
an actual transaction-bound material preflight. Unassigned executions use producer raw
stock; customer/mixed lines may consume only their own customer's raw stock. The scope
cannot survive commit, bypass an inactive/cancelled order or accept caller owner tags.

Output creation and reduce-only reconciliation defer commit to the completion caller.
A later output failure rolls back inputs, outputs, reconciliation balances, step state
and events together. Ordinary WIP/finished outputs retain producer title in this slice.

Site dispatch snapshots preserve the trusted raw owner. Partial receipts create distinct
same-owner fragments with generic destination/lineage/unit proof and original receipt
metadata. Source on-hand plus destination fragments plus outstanding transit conserves
the original quantity. A customer-owned debit otherwise requires a recorded wastage
reason or ownership-aware dispatch. Legacy immediate move/merge, manual adjustments,
opening stock, ordinary reconciliation and sales reversals cannot deposit or relabel
customer stock.

## Acquisition projection and release gate

The customer stock projection reports free-issue acquisition cost zero and excludes
these rows from producer acquisition/sales selectors. This is a producer acquisition
projection, not an accounting inventory valuation or a finished-goods title decision.
There is no general monetary valuation report or stock cost model to extend here.
Ordinary final-product FIFO, manual allocation, candidates/product selectors and reversal
exclude both customer stock and unresolved historical owner hints.

`Organisation.contract_materials_enabled` defaults false and has no public setting or
activation API. Receipts, consumption of existing owned lots and dispatch remain closed
when it is off. Observational reads and conservation of already dispatched receipts do
not silently erase owner evidence. Sites operations and module movement policy gates
remain independent; raw ownership never decides CCA duty, order duty or finished title.

The migration combines the known `site_transfers_001` and `contract_portal_001`
prerequisites. Integration must linearise the submitted parent/food/planner migration
history before release; do not alter applied history. Downgrade refuses existing owned
stock or material receipt evidence. Fresh upgrade and empty downgrade/re-upgrade are
validated in a dedicated PostgreSQL database. Full 7.2 and 7.2b stay open for the remaining
finished-title policy, portal material projection and accounting/operating rollout.
