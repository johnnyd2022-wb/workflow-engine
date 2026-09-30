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

## Approval form projection

`movement_requirements(db, org_id)` returns fresh `fields` and an optional
`authority_permission`. Each field has name, text/select/date type, label, required
flag and optional value/label choices. Core renders this contract and submits these
values as the approval mapping; it must enforce the returned permission on the server
when recording module authority. This keeps industry choices out of Core templates.
An unsupported enabled module additionally returns `blocked: true`.

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
Per-licence excise entries and full operational release remain open requirements.
Transfer and food/liquor finding foundations are separate dependent MRs. No existing licensed-area flag or excise behavior
is replaced merely by adding this seam.

## Destination registration findings

NZ Alcohol projects an explicit `destination_activity` field (storage, manufacturing
or selling) through the existing generic approval form. It does not infer this value
from the destination's kind. Older clients or dispatch facts without this field raise
an activity-review finding. Invalid supplied values are rejected.

An authorised CCA movement records plain-text `system_alerts` within its immutable
module evidence when food activity coverage or a current dated liquor record is
missing. Receipt rechecks recorded coverage on its own date using the original
activity. These review findings do not replace Customs authority requirements, and
receiving stock never grants permission to sell.

The module's periodic check re-evaluates dispatch and receipt dates against the
recorded registers and emits the standard system-finding/notification contract.
Each underlying transfer/receipt has stable alert IDs. Newly documented historic
coverage can resolve the current finding without rewriting the original decision.
Food coverage is the explicit registration/activity/site/date link. A liquor record
must have the same site and organisation, current status, a number and issue/expiry
dates; a special licence must also cover the event date. This is a missing-record
check, not validation of licence conditions, hours, consumption mode or exemptions.
All those requirements still need producer review. No external permit is verified.

MPI permits explicit multi-site registration; addresses and coverage must be recorded:
[Register a food business](https://www.mpi.govt.nz/food-business/starting-a-food-business/register-food-business).
Liquor licence types authorise different activities:
[Police alcohol-licence overview](https://www.police.govt.nz/advice-services/drugs-and-alcohol/alcohol-licences).

Legacy dispatches without an activity remain reviewable; their immutable evidence
is not overwritten. An audited activity-correction workflow remains future work.
