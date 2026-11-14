# SPEC: live-cogs overheads (8.1h)
status: v1 (build contract for roadmap 8.1h; spec `.agents/specs/live-cogs.md` Phase 4, opt-in)
slice: `app/features/costing/` (reuse, not a fork); API under `/api/core/costing/*`
roadmap: `docs/source-to-sale-plan.md` 8.1h

## What it is

Some producers want a batch to carry its share of rent, labour, power and the freight on what
they bought, so cost per bottle is a full **absorption** cost. Most don't, and for them nothing
changes. So it is **opt-in per org, off by default**, and with it off every cost figure, test and
response is byte-for-byte what it was before this MR.

When it is on:

1. The org types **overhead rates**: a name (Rent, Labour, Power), an amount, a basis (**per
   litre** of finished product, or **per batch**) and an effective-from date. A batch completed on
   or after that date takes the rate.
2. **Freight** on a purchase is landed cost: a freight line spreads over the stock the same
   purchase document paid for, by value, so those lots' unit costs include it.
3. Every cost shows the split: **materials** vs **overheads** (batch cost card, lot cost panel,
   margins). Overheads never decide whether a product is "ready"; readiness is about materials.

Works with no Xero connected: rates are typed; a freight line can be a Xero line **or** a manual
mark (below), and with no Xero the batch overheads still apply.

Out of scope (decided): time tracking and a rate per hour of a step (spec Q-out-of-scope), litres
of absolute alcohol (LAL) as a basis, spreading freight across more than one purchase document,
and posting anything to Xero. See "Assumptions".

## Data model (one migration, `costing_overheads_001`, off the single head, reversible)

- `costing_settings.include_overheads BOOLEAN NOT NULL DEFAULT false`.
- `purchase_lines.freight BOOLEAN NOT NULL DEFAULT false` — the user marked this line as freight.
- `stock_value_movements.kind` (8.1g) gains `overhead_absorbed` (its check constraint is widened; downgrade
  refuses while one is stored).
- `overhead_rates` (`TenantScoped`, `UniqueConstraint(org_id, id)`):

| Column | Notes |
| --- | --- |
| `name` | text, 1–80 chars, trimmed |
| `basis` | `per_litre` \| `per_batch` (check constraint) |
| `amount` | `NUMERIC(18,6)` ≥ 0, ex GST, in the org's base currency |
| `effective_from` | date, not null |
| `is_active` | bool, default true |
| `created_by_user_id`, `created_at`, `updated_at` | |

  Unique index on `(org_id, lower(name), basis, effective_from)` — one rate per name, basis and
  date; a clash is a 409. Downgrade refuses while any `overhead_rates` row exists (typed by a
  person, no other copy — the repo's convention).

`GET /settings` carries `"include_overheads": true` **only when on** (absent means off), so an
org that never opted in sees the same JSON as before. `PUT /settings` accepts
`{"include_overheads": true|false}` (`costs.manage`; non-boolean is 400).

## Which rate applies to which batch

A rate is a fact; the engine picks, per `(lower(name), basis)`, the **active** row with the
greatest `effective_from` ≤ the batch's completion date (the org's NZ calendar date of
`executions.completed_at`; ties: latest `created_at`, then id). A rate of **$0** ends that name
from its date (it applies nothing). A batch completed before every rate's date takes none.

## Which batches take overheads, and where it lands

- Only a **completed** batch (`status = completed`, `completed_at` set). A running batch has no
  overheads yet — its card says "Overheads are added when the batch is complete" — and
  `cost_so_far` is materials only. Completing the batch raises its lots' costs on the next read
  (nothing is stored, as ever).
- Only a batch that makes **finished product**: the *overhead step* is the last step (by step
  number) whose produced outputs include a `final_product` lot that is not Library stock. A
  batch with none (it only makes work-in-progress) takes no overheads, so a chain of
  batches never counts rent twice; the batch that finishes the product carries it.
- The overhead lands in the **batch's pool at the overhead step**, then is split between that
  step's outputs by the same weights as the materials (`cost_share`, quantity, or litres), so
  by-products and Library stock behave exactly as before.

**Amount.** Per batch: `amount`. Per litre: `amount × litres`, where litres = Σ over that step's
finished-product, non-Library output flows of `litres_of(quantity, unit, alcohol profile)` — L and
mL directly, a count unit (bottles) by the matching profile's `pack_volume_ml` (the same rule as
the litres split). Each line is rounded to 4 dp; the batch's overhead is the sum of its lines.

**Unknown litres are never $0.** If a per-litre rate applies but any of those outputs' litres
can't be worked out (a bottle count with no pack size), **no** per-litre line is applied, the
batch's status is `partial` (a floor), the warning is `overhead_litres_unknown`, and the card says
what to fix ("Tell Biz-E the bottle size…"). Per-batch rates still apply. `unit_cost` is then
null and `known_unit_cost` carries the floor, exactly as for a missing material.

**Carrying the split.** The engine carries the overhead part of every figure alongside it
(`Alloc.overhead`, `LotCost.unit_overhead`), so a lot made from a lot that carried overhead (a
later batch, a transfer) keeps showing that part as overhead. Materials = known − overhead.

## Freight as landed cost

A **freight line** is a line on an **active** purchase document, not superseded, with a positive
base-currency amount, that either has `freight = true` or has treatment `overhead` and the
words freight / courier / postage / shipping / delivery / cartage in its account name or
description. (Rent, power and wages lines are overheads, not freight, and are never spread.)

For one document `D`: `F` = Σ amounts of its freight lines; `V` = Σ amounts of its **positive**
purchase allocations (active or orphaned; refunds excluded) on its non-freight lines. Each
allocation `a` is priced `a.amount + F × a.amount / V` (when `V > 0`). So the lot's unit cost
includes freight, the freight part is reported as overhead, and the lot's status is unchanged.
Only within one document; with nothing recorded yet (`V = 0`) the freight is absorbed by nothing
and the line stays a plain overhead purchase. As more stock on the document is recorded, the
spread re-computes (computed on read).

**Marking a line as freight** (for a line the sync classified `stock`): the Purchases card has
"It's freight" (only shown when overheads are on). It sets `freight = true`, takes the whole
open amount as `not_stock_amount` (so it leaves To record and shows under Not stock with a
Freight badge) and refuses if anything is already recorded against the line. Reopen clears the
mark. `POST /purchases/<line_id>/freight` (`costs.manage`); 400 when overheads are off.

## API additions

| Route | Permission | Purpose |
| --- | --- | --- |
| `GET /overhead-rates` | `costs.view` | `{"rates": [...]}`, newest effective date first |
| `POST /overhead-rates` | `costs.manage` | `{name, basis, amount, effective_from}` → 201 |
| `PUT /overhead-rates/<id>` | `costs.manage` | any of those plus `is_active` |
| `DELETE /overhead-rates/<id>` | `costs.manage` | |
| `POST /purchases/<line_id>/freight` | `costs.manage` | mark as freight |

Payload additions, **present only when overheads are on** (absent otherwise):

- Lot (`GET /lots/<id>/cost`): `materials_unit_cost`, `overhead_unit_cost` (both to 6 dp; their
  sum is `known_unit_cost`).
- Batch (`GET /executions/<id>/cost`): `overheads` = `{"amount": "140.0000" | null, "lines":
  [{"name","basis","rate","quantity","amount"}], "note": null | "in_progress" |
  "no_finished_product" | "litres_unknown"}`; per output `overhead_amount`,
  `overhead_unit_cost`, `materials_unit_cost`.
- Margins (`GET /margins`): per row `materials_cost`, `overhead_cost` (sum is `cost`).

## Worked examples

**A. A 200 L batch.** Materials consumed cost $1,000. Rates: Rent $0.50 per litre, Labour $40 per
batch, both effective 1 Oct. The batch completes 15 Oct making 200 L of gin (unit L, final
product). Rent = 0.50 × 200 = $100.00; Labour = $40.00; overheads $140.00. The pool is
$1,140.00 → **$5.70/L**: materials $5.00/L, overheads $0.70/L. Switch the setting off and the
same lot reads $5.00/L with no `overheads` anywhere.

**B. Bottles.** 10 × 700 mL bottles (profile pack volume 700 mL) = 7 L; Rent at $0.50/L = $3.50,
plus Labour $40 = $43.50 on top of $90 of materials → $133.50 over 10 bottles = $13.35 each
($9.00 + $4.35). With 2 000 mL of Library stock beside the bottles the litres base is still 7 L
(Library stock is a remainder, not finished product). With no pack size on the profile the Rent
line is not applied, Labour is, and the batch reads partial: `known_unit_cost` $13.00 per bottle
(a floor: $90 + $40 over 10), `unit_cost` null.

**C. Freight.** A $300.00 purchase document: Juniper $150.00 and Coriander $100.00 recorded
as stock, plus a $50.00 line on "Freight & Courier". `F = 50`, `V = 250`. Juniper (2 kg) is
priced 150 + 50 × 150/250 = **$180.00** → $90.00/kg, of which $15.00/kg is freight; Coriander
(1 kg) 100 + 50 × 100/250 = **$120.00** → $120.00/kg. $300 in, $300 across the lots.
With overheads off they cost $150.00 and $100.00 as before. A $50 freight line on a *different*
document changes neither.

**D. Dates.** Rent $0.50/L from 1 Oct and $0.60/L from 1 Nov. A batch completed 15 Oct uses
$0.50; one completed 15 Nov uses $0.60; one completed 20 Sep uses neither. A $0.00 Rent row from
1 Dec ends it.

## Acceptance criteria

IDs are prefixed `OV` so they can't collide with the AC numbers other 8.1 builds take.

| AC | Behaviour | Test |
| --- | --- | --- |
| OV1 | Off by default: `GET /settings` has no `include_overheads`; configuring rates and freight with it off leaves every lot and batch payload identical, with no overhead keys | `test_ac_ov01_off_by_default_and_rates_change_nothing` |
| OV2 | `PUT /settings` turns it on/off (`costs.manage`, boolean only); `GET` shows it only when on | `test_ac_ov02_setting_round_trip_and_validation` |
| OV3 | Rate CRUD: validation (name, basis, amount, date), duplicate 409, edit, delete, list | `test_ac_ov03_rates_crud_and_validation` |
| OV4 | Example A: $5.70/L, split $5.00 + $0.70, in an org with no Xero tenant | `test_ac_ov04_worked_example_200_litre_batch_without_xero` |
| OV5 | Example D: effective dates, a later row supersedes, $0 ends a rate, before-first-date takes none | `test_ac_ov05_effective_dates` |
| OV6 | A running batch takes no overheads and says so; completing it adds them | `test_ac_ov06_running_batch_has_no_overheads_yet` |
| OV7 | A batch that only makes WIP takes none; one batch with a WIP step then a final step takes them once, on the final lot | `test_ac_ov07_overheads_land_once_on_finished_product` |
| OV8 | Example B: bottles by pack size; Library stock outside the litres base; no pack size → partial, never $0 | `test_ac_ov08_bottle_litres_library_and_unknown_pack_size` |
| OV9 | Overheads split between joint outputs by the step's `cost_share` | `test_ac_ov09_overheads_follow_the_cost_share` |
| OV10 | A lot made from a lot that carried overhead keeps it as overhead | `test_ac_ov10_overhead_carries_into_a_later_batch` |
| OV11 | Example C: freight by value across the document's recorded stock | `test_ac_ov11_freight_spreads_by_value_within_the_purchase` |
| OV12 | Freight stays inside its document; voided documents, refunds and rent lines don't spread; nothing recorded absorbs nothing | `test_ac_ov12_freight_boundaries` |
| OV13 | Mark a line as freight; refuses when recorded or when overheads are off; reopen clears | `test_ac_ov13_mark_a_line_as_freight` |
| OV14 | Readiness is unchanged by overheads, even a partial overhead | `test_ac_ov14_readiness_is_unaffected` |
| OV15 | Margins carry materials and overhead cost | `test_ac_ov15_margins_show_the_split` |
| OV16 | Isolation and permissions: feature off 404, other org's rate 404, viewer can't write | `test_ac_ov16_tenant_isolation_and_permissions` |
| OV17 | Migration adds the columns and table, reversible | `test_ac_ov17_migration_shape` |
| OV20 | The bridge's roll-forward shows absorbed overhead as its own component and stays balanced; off, it is 8.1g's | `test_ac_ov20_*` (`tests/test_costing_overheads_bridge.py`) |
| OV19 | Pricing many batches together costs no query per batch | `test_ac_ov19_primed_costs_do_not_query_per_batch` |
| OV18 | Browser: turn on, add a rate, see the split on the batch card and lot panel at phone width | `tests/e2e/test_costing_overheads_browser.py` |

## Assumptions (each can be overturned in review)

- ASSUMPTION H1: per litre means litres of **finished-product volume**, not LAL. Rejected: LAL —
  it needs ABV on every product and rent has nothing to do with strength; revisit as a third basis.
- ASSUMPTION H2: overheads attach to the batch that makes finished product and are taken at its
  completion. Rejected: spreading across WIP batches (double counts), or applying while running
  (litres aren't known yet).
  Caveat: this relies on intermediate outputs being work-in-progress, which Core does for every non-terminal step; a bulk output typed final product and then bottled would take overheads at both stages.
- ASSUMPTION H3: freight spreads over one purchase document's *recorded* stock by value; a freight
  line on a separate document is not matched to anything. Rejected: matching by date/supplier (a guess).
- ASSUMPTION H4: freight shows as overhead in the split (it is not material). Its lot status is unchanged.
- ASSUMPTION H5: an unmeasurable per-litre rate makes the batch partial rather than being
  guessed or skipped silently.
- ASSUMPTION H6 (with 8.1g, stock value and the Xero bridge): overhead taken into stock is part of
  a lot's value, so the roll-forward shows it as its own component, **overhead_absorbed**, instead of a
  negative production loss (a batch's rent and labour) or an estimate change (freight on a purchase).
  It is a stored movement kind (so a closed month stays fixed), shown only for an org that has opted
  in. The batch pool the stock value carries stays materials only. The bridge's Xero overhead total
  is untouched and now sits beside `absorbed: {batch, freight, total}`. Overhead spend not absorbed
  (rent paid but no batch finished) simply isn't in stock, so it needs no line.
