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

## Coordinated stock integration still required

Customer receipts are not enabled by this seam. Before receipt activation:

- Sites adds nullable `InventoryItem.contract_customer_id` with a composite
  organisation/customer FK. NULL explicitly means producer-owned; existing rows retain
  NULL and legacy owner hints require explicit resolution. Owner changes are rejected
  by a database guard. New customer lots are raw-only.
- Sites preserves owner in transfer snapshots and distinct receipt fragments, validates
  immutable owner/provenance together, and prevents merges across owners or lineage.
  Generic movements conserve ownership; Compliant continues to own duty decisions.
- The production adapter resolves contract scope before site/inventory locks, invokes
  both preflights before writes, and handles ownership failures transactionally. The
  small core adapter is Sites-owned after its transfer MR is stable.
- Ordinary sales FIFO/manual allocation and producer valuation exclude customer stock;
  manual quantity edits, opening/import paths, reconciliation, wastage and reversals
  cannot relabel or silently deposit it. Free-issue material carries no producer cost.
- Receipt routes use trusted staff capabilities, active same-org customers, audit and
  idempotency. Generic stock APIs reject owner fields. Selected customer lots remain
  traceable through execution input records and recall lineage.

No inventory model, repository, site guard or transfer file is edited by this contract
service slice. It has no migration or public route. Full 7.2b stays open until the
coordinated stock guards, receipt path, valuation/sales exclusions and conservation
checks pass together.
