> UI direction superseded by the founder-selected typed Tasks refinement in [tastings-tasks.md](tastings-tasks.md). The original stock/excise acceptance criteria remain in force; the standalone concept choice below is historical.

# SPEC: tastings
status: approved-unattended
name: Tastings
slug: tastings
blueprint: app/features/tastings/
url_prefix: /crm/tastings

## Description
Track alcohol brand sampling events at a licensed external venue or the producer's own venue: who is going, when, what stock is taken, and the resulting physical removal for excise. Tastings belong to Sales and use the existing Sales tasks and Core production task calendar, rather than a disconnected calendar. Tasting stock remains a distinct operational stock purpose and never merges with Library stock used for trials and consistency/quality checking.

## Users & permissions
- tenant_scoped: yes
- Existing sales.view reads; sales.record schedules and records outcomes. Stock dispatch also requires inventory.adjust. Existing org membership, subscription and selected-site role restrictions remain enforced.
- Availability uses nz_alcohol_active, the existing NZ Alcohol + Compliant subscription gate; no standalone new product subscription.

## Acceptance criteria
- AC1: Active NZ Alcohol subscribers see Sales > Tastings; other orgs get 404 for both page and API. All records, related contacts, assignees, stock and writes remain org scoped; wrong-role writes are denied; normal CSRF protection applies.
- AC2: Create/update/cancel an event with a bounded title, venue name and address, own/external venue, start/end in Pacific/Auckland, rep and optional CRM customer. Validate times and same-org references; show planned, dispatched, completed or cancelled state with useful empty/error states.
- AC3: A tasting has exactly one linked CRM task; schedule/assignee/status stay in sync atomically, so it appears in the existing Sales calendar and the Core merged task calendar. It links back to Tastings. Generic task edits cannot bypass dispatched-stock state rules or silently detach it. Cancellation before dispatch changes no stock or excise.
- AC4: Schedule with zero to twenty planned stock lines, then require one or more eligible producer-owned finished-product lots with positive canonical quantities (whole counts for bottles/cans). Planning/reserving an event alone is not a physical removal. Confirming physical dispatch uses an explicit actual date, locks stock, prevents overselling and duplicate/replayed dispatches, retains batch/lineage and actor evidence, and debits warehouse stock atomically. Concurrent insufficient-stock or invalid-line failure rolls back the entire dispatch.
- AC5: Dispatched stock is labelled and tracked as tasting stock, separate from Library stock and ordinary sales stock, including leftovers. Do not infer tasting stock from a product-name suffix. Show sent, used and remaining quantities. Completing or cancelling after dispatch does not put stock back into saleable/bonded inventory or reverse excise silently. Reusable unsampled remainder remains separately visible with its batch and duty status.
- AC6: Record an attributable, durable removal on dispatch for excise (including own-venue consumption), not on planning or invoice date. Feed the existing Customs excise surfaces/draft/register as appropriate to current code. Freeze the facts necessary to avoid changing old removals when the source/product is edited. Stock already outside the licensed area must not generate a second duty event. Missing duty/classification facts are visible and block a false nil/complete return; never treat unknown as zero. No Library-stock or Xero-sale double counting.
- AC7: UI works after a full load, boosted revisit, Back, phone and dark mode; calendar navigation remains shared with existing tasks. The page-design skill supplies three real structural options in a draft MR, with seeded browser screenshots, research and plan. No style choice or merge is performed on the user's behalf.
- AC8: Tests prove eligible/ineligible orgs and roles, hostile-org IDs, validation, idempotency, all-or-nothing stock accounting, concurrent allocation, task/calendar integration, recorded-date excise inclusion and no double count, and distinct tasting/Library stock. Relevant existing suites stay green and performance remains bounded.

## Data model
- changes: new org-scoped tasting/event and explicit tasting stock/allocation/removal records; task association; minimal additive integration to existing calendars and excise readers, chosen after code inspection.
- destructive: no

## External surfaces
- No third-party API or message sending. Existing app calendars and excise records only.

## Assumptions
- ASSUMPTION: The new feature is implemented in a separate draft MR after Home performance. Rejected mixing unrelated changes.
- ASSUMPTION: Use existing role permissions; sales reps can plan but the existing stock-adjust permission controls taking physical stock. Rejected granting new general inventory authority to every Sales user.
- ASSUMPTION: Venue licence information can be recorded as a reference; the app does not issue licences or claim to verify a venue's legal eligibility. Rejected external licence lookup or automated permission to supply alcohol.
- ASSUMPTION: Actual dispatch/own-venue consumption is the recorded stock removal; merely booking or allocating never incurs duty. Rejected duty on the planned calendar date.
- ASSUMPTION: Unsampled dispatched stock stays in a separate tasting pool with its original recorded removal liability; automatic returns, refunds and automatic duty credits are excluded. Rejected merging leftovers into Library or bonded stock.
- ASSUMPTION: Outcomes are samples used and free-text notes; external POS sales import and automatic revenue/conversion attribution are excluded.

## Out of scope
- Production infrastructure/deployment, licence verification, automated legal advice, direct Customs filing, automatic duty remission, CRM email invitations, recurring events and offline mobile sync.

## Concrete integration and conservation decisions (critic round 1)

### Scheduling and ownership of edits
Tastings owns schedule, rep, venue, status and stock outcomes. The existing calendars receive an all-day projection of the Pacific/Auckland start date (CRMTask.due_date); cards link to the tasting detail, which shows actual start/end. Generic CRM task PUT/DELETE and lane status writes reject tasting-linked tasks with a route to the event; rescheduling/cancelling happens atomically in Tastings. Dates are ISO timestamps with an explicit offset, validated against Pacific/Auckland at that instant (reject ambiguous/nonexistent naive local values). Title <=160, venue <=160, address <=500, licence reference <=160, notes <=4000; event end strictly follows start and duration <=7 days. Plan edits only before dispatch; outcome through dedicated finalisation after dispatch; outcome_notes is separate from retained plan notes. Cancelled/completed events remain auditable, never hard-deleted.

### Tables and planning
- Tasting: org_id, unique same-org CRM task association, schedule/venue/rep/contact, lifecycle state, unique per-org dispatch key and canonical request hash, timestamps/actor.
- TastingAllocation: same-org tasting association; exactly one source warehouse item or existing TastingStockLot; proposed canonical quantity for stock or mL for a pool; actual reserved_volume_ml after dispatch, used_volume_ml on finalisation, state and source snapshot.
- TastingStockLot: same-org original inventory source and creating event/allocation, canonical removed quantity/unit, initial/remaining mL, removal date, capture timestamp/actor, frozen excise basis and source/batch/lineage/CCA facts. Purpose explicitly tasting. Separate ledger; never create Library or saleable InventoryItem rows for these balances.
Planning is soft: quantities are proposals, not availability reservations. Dispatch (actual date <=today) atomically locks and validates all lines. Limits: <=20 allocation lines/event; source search paginated <=50; event list <=200 within <=93 days, truncation/pagination explicit; pool list <=50/page. No all-history inventory materialisation.

### Source eligibility and stock writes
Accept producer-owned finished stock with established lineage/ownership and positive canonical units; whole bottles/cans/kegs or volume units. Resolve order ownership through prepare_dispatch_duty BEFORE stock locks. Reject every contract-order-linked output, customer-owned/legacy-marked stock, and received transfer fragments (whose quantity is governed by receipt accounting), rather than misclassifying another business's liability. Source Site/Location must be same-org and active; selected-site staff are denied the feature by the endpoint registry. No cross-site transfer is created or faked. Multi-site orgs can remove ordinary producer lots at their source site, with dated source CCA coverage; existing SiteStockTransfer/StockTransfer are not written for tastings, so the new removal has one identity only.

For legacy single-site sources, the existing stock location inside_licensed_area flag/default defines the removal boundary. For multi-site or recorded CCA sources, use licence_for_area on actual date and require valid source coverage. Warehouse stock already outside the licensed area can only enter the tasting pool when its prior immutable out-transfer/removal evidence proves it was previously removed; otherwise reject ambiguous status before debit. Existing tasting pool reuse always carries its original removal identity. Library-stock markers never become pool categories or automatic destinations.

### Quantities, leftovers and finalisation
Tasting pool accounting uses Decimal mL at four decimal places. Warehouse dispatch retains canonical units and freezes conversion volume (pack size from configured product or exact volume conversion); missing pack size blocks dispatch because pool quantities cannot be conserved. Let B be original dispatched mL, U the sum of finalised usage, and R the sum reserved for currently dispatched allocations: remaining=B-U; available=B-U-R; all are >=0. Reusing an unsampled remainder in a later tasting reserves from available pool mL, without another warehouse debit or removal. Finalising supplies measured used_mL per allocation (0<=used<=reserved); an opened bottle can consume e.g.150mL of a 700mL bottle, leaving550mL in the pool. A separate optional samples_count is a bounded nonnegative statistic, not an inventory quantity. Finalisation is replay-safe; a changed repeat fails409. Cancel after dispatch releases the reservation and leaves the physical stock in the tasting pool with its original removal liability; no automatic bonded return/credit. Corrections after finalisation are explicitly rejected in v1; retained notes explain the outcome, with no silent overwrites.

### Excise adapters and snapshots
Each newly removed pool lot is the one immutable removal identity; allocation reuse has no new removal. Snapshot source item/unit/pack/batch/lineage, actual date and recording time, named source CCA/location and owner, product classification/tariff, ABV and provenance, rate/basis effective on actual removal date, L/LAL/duty/levy/GST where supported. Never call a recorded liability 'paid' or claim Customs lodgement.

- Legacy single-site draft: add tasting removals to the existing removal reader and use the frozen tasting basis rather than current inventory/product/rate data. Reuse has no reader row. Carry a late-recorded tasting removal into _late_adjustments using its immutable tasting-stock-lot reference, leaving previously lodged snapshots unchanged. Missing classification/ABV/rates yields an explicit problem and entry.complete=false; never nil/complete. Line merging and rounding must preserve the frozen basis and documented rate date; do not silently reprice on draft date.
- Multi-site/per-CCA register: include these same tasting removals grouped under the frozen valid source CCA alongside existing SiteStockTransfer observations; source/basis problems are unresolved rows. Preserve complete_lodgement=false, nil_return=None and total_duty=None. Include tastings in the source CCA period review's observed counts/duty/details, with their own ids rather than impersonating SiteStockTransfer. Existing outstanding accounting sources remain explicit.
- Missing classification/ABV/rates: retain the removal facts and make its unresolved capture visible in the event/pool and relevant excise surface. Never invent zero duty. Missing volume conversion or ownership/source authority blocks the stock dispatch. A frozen unresolved row cannot silently become a completed return by later profile edits.
Tests include backdating after a lodged period, edited product/source/rates, no sale/transfer duplication, rate rollover, own-venue removal, modern per-CCA rows, unknown-basis blocking of false completion, and reuse with no second removal.

ASSUMPTION: A rep can book a tasting before choosing stock (0–20 planned lines). Physical dispatch requires at least one line; booking alone removes nothing.
