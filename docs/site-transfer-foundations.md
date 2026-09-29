# Recorded stock transfer foundation (partial plan 7.1d)

This slice requires the Sites foundation (!427), same-site operations prerequisite
(!429), Customs premises register (!430) and generic module movement provider (!431).
Core owns physical facts and quantity accounting. Module code owns Customs treatment,
movement authorities and field metadata. Core never imports NZ Alcohol.

## Staged release

`multiple_sites_enabled` remains the single customer-facing opt-in. The internal
`multiple_site_operations_enabled` release gate stays false. This MR does not activate
additional-site operations for any organisation. Integration must first cover Customs
loss/removal attribution, registrations and the remaining operation scopes. Tests enable
the internal gate explicitly to exercise real production, FIFO, dispatch and receipt.

The local tested migration chain is `multiple_sites_001 → site_operations_001 →
customs_premises_001 → site_transfers_001`. Claude owns integration: drop duplicate
provider ancestors and insert the liquor/food registration siblings before transfers.
Each schema slice must have one linear `down_revision`, without artificial `depends_on`.

## Accounting and identity

Dispatch locks organisation settings, source stock and active tenant sites/places before
constructing immutable server facts for policy evaluation. Only an allowed decision can
reduce shelf stock. The dispatched quantity becomes transit in `site_stock_transfers`;
it is on the books and is not an `InventoryItem` or a FIFO candidate.

Receipt locks the transfer row, revalidates the destination and evaluates receipt/loss
policies before any write. Good receipts create separate stock fragments at the recorded
destination; they preserve unit, product type, supplier batch, dates, production lineage
and metadata. Primary barcodes remain unique: fragments have no primary barcode and
retain the original barcode as an alias in metadata. Further dispatch preserves that
alias and source ancestry. Fragments never merge merely because labels match.

Every good fragment has one immutable, same-tenant receipt proof. The ORM guard validates
its initial quantity, destination, lineage and metadata against that proof and prohibits
retagging or changing its identity. Ordinary stock's existing batch/place deduplication
remains a partial unique index, now scoped by site; only receipt-backed fragments are
exempt. Existing location moves cannot cross sites or move receipt-backed fragments;
their merge requires recorded movement ancestry and matching unit/type/lineage/metadata.
When the internal multisite release is open, the legacy location-move path is closed:
all moves use recorded dispatch/receipt and module decisions. Off/staged behaviour stays.

For each transfer, `dispatched = received + confirmed loss + remaining transit`.
Counters and append-only receipt records change atomically. Damaged and short quantities
require explicit confirmation, actor permission, a reason and an allowed loss decision.
They reduce transit once, without a second source debit or ordinary wastage write.
Unconfirmed discrepancies remain transit. Overages cannot create stock implicitly.
The current NZ provider denies confirmed loss until excise attribution is implemented.

All mutations require an idempotency key. Per-organisation advisory locks serialise key
replays, the stored request hash rejects changed details and row locks serialise source
and transit budgets. The caller commits the entire transaction; denial or failure rolls
back stock, ledger counters, receipt facts and events together.

## Authority and tenant boundaries

The API obtains organisation and actor from authenticated request context. Composite
foreign keys bind source stock, sites/places, receipt proofs and actors to that tenant.
The service currently accepts producer-owned stock only; a non-null customer owner or
legacy owner hint is rejected. Customer ownership will be added in a coordinated slice.

Dispatch renders trusted `movement_requirements` metadata and enforces its authority
permission on the server. Ordinary receipt requires the existing `inventory.adjust`
permission and uses immutable dispatch authority; it rejects new approval input.
Dockets render escaped, bounded licence/authority evidence, never raw policy payloads.

Organisation flags are scalar-read under `FOR SHARE` for the whole shipping transaction,
including opt-in-off legacy shipping. Settings use `FOR NO KEY UPDATE`, followed by site
locks. The common organisation → site order prevents a mode change from expanding FIFO
scope mid-transaction and permits tenant foreign-key `KEY SHARE` checks without deadlock.

## Scope still open

This does not complete 7.1d/e/f: drag-and-drop or barcode picking, stocktake-style overage
resolution, customer-owned transfers, food/liquor findings, excise-ledger removals/losses,
per-site stocktakes, sales-channel mapping, all-screen totals and staff-by-site grants
remain follow-ups. Transit and receipt accounting guards are application ORM guards;
privileged database maintenance can bypass them and is outside public API mutation paths.

Validation includes real PostgreSQL migration round-trip and history retention,
conservation, tenant/identity rejection, rollback, idempotency, concurrent shipping flags
and receipt budgets, configured module permissions, and real HTTPS Chromium dispatch,
approval, partial receipt and docket at 1440px and 390px (`tests/e2e/test_site_transfers.py`).
