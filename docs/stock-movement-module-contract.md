# Stock movement module contract

Core owns locked stock, dispatches, receipts, in-transit quantities and immutable
lineage. Compliant modules own movement constraints and authority evidence.

`app.features.compliant.platform.stock_movements.evaluate_stock_movement(db,
org_id, context)` accepts a server-built context and returns a frozen
`MovementDecision(allowed, reason, evidence)`. Evidence is canonical JSON text so
later changes to an input mapping cannot alter the returned decision. Core parses
it into its append-only transfer ledger in the same transaction as quantity writes.
A denied decision must leave stock, receipts and audit records unchanged.

The context contains operation (`dispatch`, `receipt`, `loss`), trusted item,
source/destination site and location IDs, product name, inventory type, canonical
quantity/unit, business date, carrier, consignment reference, authority fields,
transfer/receipt IDs, actor, original source snapshot and immutable dispatch evidence.
Core verifies tenant membership, permissions and idempotency before invoking a
provider. Public requests never supply tenant identity or authoritative dispatch
snapshots. Receipt quantities must also fit the **remaining** transit balance under
lock; a module check against the original dispatch is not that accounting check.

No configured module means no additional compliance constraint. An enabled module
without a movement provider denies the operation. Providers must not commit or
mutate inventory. Core must call them before dispatch, receipt and loss confirmation;
this initial provider MR does not wire routes or enable multi-site operations.

## NZ Alcohol initial policy

The policy uses dated, exact-area CCA coverage and active product profiles. Missing
classification or coverage remains unresolved. Main-area coverage does not extend
to named locations.

Recorded same-legal-entity authority compares the registered licence entities;
movement to off-site storage still requires prior approval. Prior approval requires
a reference, evidence and an approval date no later than dispatch. These are staff
records of authority, not automated verification of an external permit. The caller
must restrict authority recording to appropriate compliance staff.

The dispatch snapshot records both licences and document references, authority,
carrier, consignment, date and quantity. Receipt must match the original transfer,
item, places and unit, and have valid destination coverage on its receipt date.

[Customs guidance](https://www.customs.govt.nz/business/excise/alcohol-and-excise/moving-products-excise-unpaid)
also permits specified further-manufacture, contract-owner and duty-free/export
movements. This first implementation does not infer those authorities from a site
label; trusted contract/activity evidence is still needed.

Unlicensed removals, temporary unlicensed storage and confirmed transit losses are
blocked until their specific approval and excise accounting workflows exist.
Food/liquor registration findings, per-licence excise entries and a transfer screen
remain separate open requirements. No existing licensed-area flag or excise behavior
is replaced merely by adding this seam.
