# SPEC: live-cogs-packs
status: v1 (built on `feat/live-cogs-packs`; reviewed with the rest of live-cogs at the end)
name: Multipacks: consume packs by the item and cost them right
slug: live-cogs-packs
blueprint: no new slice. A pure helper `app/core/utils/packs.py`, used by Core (execution
consumption, inventory create/update, CSV, wastage), the `costing` slice (backfill, lot cost
payload, Purchases record) and the inventory stock-integrity check.
url_prefix: no new routes. `pack` is a new optional field on existing ones.
roadmap: `docs/source-to-sale-plan.md` 8.1i (extends 8.1; needs 8.1a–e, merged)
source: founder request, 13 Nov 2026: "Multipacks etc should all be used quantity wise according
to workflow item usage as inputs and broken down cost based on the right math."

## Description

A lot bought as packs (a case of 24 × 200 mL tonic, a 25 kg bag, a box of 500 labels) must be
usable by a workflow step in whatever unit the step uses (bottles, mL, g, pieces), and its cost
must break down correctly: per case, per bottle (÷ 24), per litre (÷ 4.8 L).

Before this, `are_units_compatible` matched a counted unit only to itself, so a step that used
"12 bottles" of a lot held in "cases" was refused, and the only pack data was
`AlcoholProductProfile.pack_volume_ml` on finished goods. The Add Inventory price hint read a
size out of the item's name, for display only, and treated one unit as the whole multipack.

This adds an optional **pack** on the lot: what one unit of the lot holds. Conversion uses it
where ordinary conversion can't apply. A lot with no pack behaves exactly as before.

Founder rules that bind this work (and where each is met):

- Costing works with no Xero connected. Pack entry is on every Add Inventory path (manual,
  barcode, CSV) as well as the Purchases record dialog; none of the consumption or cost tests
  connect Xero (AC15).
- Dialogs are bottom sheets. The Purchases record dialog already is one (`.pu-dialog`); this adds
  one field to it and no new dialog.
- Unknown cost is never $0. A lot with no price shows no per-bottle figure (AC13).
- Pages work at 375px with no sideways scroll (AC16). House style Style 1.

## Data model

No migration. The pack is `InventoryItem.extra_data["pack"]` (JSONB, already on the table):

```
{"count": 24, "size": "200", "size_unit": "ml"}     # one lot unit = 24 containers of 200 mL
{"count": 1,  "size": "25",  "size_unit": "kg"}     # one lot unit = a 25 kg bag
{"count": 500}                                      # one lot unit = 500 pieces (no size)
```

- `count`: whole number ≥ 1 (≥ 2 when there is no size). `size`: a positive decimal as a string.
  `size_unit`: `ml`, `l`, `g` or `kg`. `size` and `size_unit` come together or not at all.
- Written only through `clean_pack` (text such as `24 x 200 mL`, `24×200ml`, `700ml x 6`,
  `1,000 mL`, `25 kg`, `500 pcs`, `500 per box`, or a dict). Nothing else stores a pack, so every
  stored pack is valid; a damaged one is ignored on read (`lot_pack` returns `None`).
- A pack is a property of the lot, copied into nothing else. Editing it later changes how later
  consumption converts; flows already written keep the quantities they were written with.
- Tenancy and quantity guard are unchanged: the pack rides on the lot's existing org-scoped row,
  and `quantity` writes still go through `inventory_quantity_guard` with their reasons.

Where it is entered (all optional, all call `clean_pack`):

| Path | Field |
| --- | --- |
| Manual Add Inventory | "Pack size", shown for counted units, filled from the name until edited |
| Barcode Add Inventory | same; a known barcode fills it from the stored lot |
| CSV | optional `Pack size` column (the template's columns are unchanged; tests pin them) and a field on the review card |
| Purchases record dialog | "Pack size" per row; offered from the last lot's pack, else the rule's name |
| `POST` / `PUT /api/core/inventory` | `pack` (text or dict; `null` clears it on `PUT`) |

## Conversion rules

`convert_for_lot(quantity, unit, lot)` expresses `quantity` of `unit` in the lot's own unit.

1. Same unit, or a standard conversion (kg↔g, L↔mL): ordinary conversion. **The pack is never
   consulted**, so a lot of kg with a pack of 25 kg still takes 500 g as 0.5 kg.
2. Otherwise, with a pack, by what the lot is held in:
   - **Counted lot** (cases, bags, boxes, units…):
     - a counted unit that is the same word ("bag" of "bags"): the quantity as is;
     - another counted unit (bottles, pcs) and `count` > 1: `quantity ÷ count`;
     - a volume or mass compatible with the pack's size unit: `quantity in size_unit ÷ (count × size)`.
   - **Measured lot** (L, kg…) with a counted input and a sized pack: `quantity × size`, in the
     lot's unit.
3. Anything else raises `ValueError`, and the caller reports it exactly as before (units are
   incompatible). Results round half-up to 4 decimals (storage precision), except sums
   (`exact=True`) which keep full precision.

Worked examples (every one is a test):

| Lot | Step uses | Taken from the lot |
| --- | --- | --- |
| cases of 24 × 200 mL | 12 bottles | 12 ÷ 24 = **0.5000** cases |
| cases of 24 × 200 mL | 2.4 L | 2400 mL ÷ (24 × 200) = **0.5000** cases |
| cases of 24 × 200 mL | 600 mL | **0.1250** cases |
| bags of 25 kg | 500 g | 0.5 kg ÷ 25 = **0.0200** bags |
| litres, bought as 700 mL bottles | 6 bottles | 6 × 0.7 = **4.2000** L |
| boxes of 500 | 125 pcs | **0.2500** boxes |
| kg, pack 25 kg | 500 g | **0.5000** kg (rule 1; the pack is ignored) |
| cases, no pack | 12 bottles | refused, "units are incompatible" |
| cases of 24 × 200 mL | 500 g | refused (mass asked of a volume pack) |
| boxes of 500 | 100 g | refused (nothing says what a label weighs) |

**Whole containers.** A bottle out of a case is 1/24 = 0.0417 at 4-decimal storage, so 24 of them
would leave 1.0008 cases used and strand the last bottle. `settle_take` leaves a whole number of
containers: when what remains is within rounding of whole containers, the take is whatever gets
there. A take that leaves part of a container open (100 mL of a 200 mL bottle) is left as is,
and an over-take stays an over-take and is refused. The stock-integrity check judges a multipack
lot in containers (23 bottles in 0.9583 cases is whole; 0.5 of a bottle is `fractional_count`).

## Cost

Cost is derived, not journalled (live-cogs spec). The engine's lot cost is per **lot unit**
(dollars per case); consumption flows are written in lot units, so converting the quantity
correctly is the whole job: 12 bottles → 0.5 case × $48 = **$24.00**, i.e. $2.00 a bottle. No
engine change was needed for that; the engine reads the same flows.

Breakdown (`packs.breakdown`, returned by `GET /api/core/costing/lots/<id>/cost` as
`pack_breakdown`, only when the lot has a pack and a public (actual or estimated) unit cost):

| Lot, unit cost | Per container | Per litre / kg |
| --- | --- | --- |
| cases of 24 × 200 mL, $48.00 | $2.00 (1 of 24) | $10.00 per litre (4.8 L a case) |
| bags of 25 kg, $60.00 | not shown (one container) | $2.40 per kg |
| litres, 700 mL bottles, $10.00 | $7.00 per 700 mL | not shown |
| boxes of 500, $50.00 | $0.10 (1 of 500) | not shown |

A `partial` or `unknown` lot has `pack_breakdown: null`: no figure, never $0. The lot panel
shows the rows "Pack", "Each", "Per litre" or "Per kg".

The Add Inventory hint reads the typed pack, else the name: `= $48.00 per unit · $2.00 each of 24
· $10.00 per litre`. One unit is the whole pack, as before; the pack field now says so.

## Every place a quantity is converted

| Place | Treatment |
| --- | --- |
| Execution step consumption (`execution_routes.py`) | **pack-aware**: `can_convert_for_lot` + `convert_for_lot`, then `settle_take` |
| Costing backfill, rebuilding consumed flows (`costing/backfill.py`) | **pack-aware**, so a rebuilt flow equals the one written live |
| Stock-integrity check (`inventory/checks/stock_integrity.py`) | **pack-aware**: sums used stock through the pack, compares in containers |
| Wastage (`wastage_routes.py`) | **pack-aware**: 6 bottles of a lot of cases is 0.25 case |
| Costing engine lot cost, execution cost | unchanged: reads flows (already in lot units) |
| Costing engine site-transfer cost (`engine.py` ~758) | unchanged: lot unit to lot unit, no pack involved |
| Reconciliation (`reconciliation/service.py`) | unchanged: it reconciles untracked lots in their own unit, which carry no pack |
| Planning: availability, commitments, start (`planning/stock.py`, `material_adapter.py`, `start_service.py`) | **not changed** (see Out of scope); an unconvertible unit there already reads "can't be counted" |
| Sales FIFO, finished goods | unchanged: finished goods sell in their own unit; `pack_volume_ml` still serves excise |
| Stocktake (`stocktake.py`) | **not changed** (see Out of scope) |

## Acceptance criteria

- AC1: A pack text reads as: `24 x 200 mL`, `24×200ml`, `700ml x 6` → `{count, size, size_unit}`
  (24 × 200 ml, 24 × 200 ml, 6 × 700 ml); `1,000 mL` → 1000 ml; `1,5 L` → 1.5 l; `25 kg` → 1 × 25 kg;
  `500`, `500 pcs`, `24 bottles` → a bare count (500, 500, 24). `1`, `0`, `a few`, a ratio such as
  `650 g/L`, and a dict with a negative or NaN size are refused with "Pack size must look like …".
  A name never yields a bare count (`Labels 500` is not a pack). (`tests/test_packs.py`)
- AC2: `POST /api/core/inventory` with `pack: "24 x 200 mL"` stores `extra_data.pack` and returns it;
  an unreadable pack is a 400 and creates nothing; `metadata.pack` is read through the same parser
  (never stored raw; `metadata.pack = {"count": -1}` is a 400). `PUT` with `pack` sets it, with
  `null` clears it, without it (even with `metadata`) keeps it; the change is in the audit diff
  as `{"before": null, "after": "24 × 200 mL"}`. (`tests/test_pack_consumption.py`)
- AC3: Adding to an existing barcode lot with the same pack is a 200; a different pack
  (`6 x 700 mL` against `24 × 200 mL`) is a 409 naming the stored one; a barcode lookup returns
  the stored pack as text. (`tests/test_pack_consumption.py`)
- AC4: CSV: a `Pack size` column is optional; `24 x 200 mL` commits to `extra_data.pack`, a blank
  cell stores none, `a few` is a row error "Pack size must look like …", and a bad pack posted
  straight to csv-commit is a 400. The template's columns are unchanged. (`tests/test_pack_consumption.py`)
- AC5: Purchases record: a row's `pack` is stored on the lot it creates; an unreadable pack is a
  400 and records nothing; with no pack the lot is as before. The pre-fill offers the last lot's
  own pack (`6 × 700 mL` beats its name), else a pack read from a rule's name for counted units
  only (`Tonic 24 x 200ml`, cases → `24 × 200 mL`; `Juniper 25 kg`, kg → none).
  (`tests/test_pack_purchases.py`; browser: `test_the_record_dialog_takes_a_pack_and_stores_it_on_the_lot`)
- AC6: Every row of the worked-example table converts to the quantity shown, to 4 decimals.
  (`tests/test_packs.py`)
- AC7: Ordinary conversion wins and a lot with no pack is unchanged: 500 g of a kg lot with a
  pack is 0.5000; "Cases" against a lot of "cases" is 3.0000; 12 bottles against cases with no
  pack is refused with "units are incompatible" and the lot keeps its 2 cases; a single-container
  pack (700 mL bottles) does not turn a step's "cases" into bottles. (`tests/test_packs.py`,
  `tests/test_pack_consumption.py::test_without_a_pack_bottles_from_cases_is_still_refused`)
- AC8: A step that uses 12 bottles from 2 cases (24 × 200 mL, $96 paid) leaves 1.5 cases, writes a
  consumed flow of 0.5, costs the batch $24.00, and the 12 cans it makes cost $2.00 each. A step
  that uses 2.4 L of the same lot also leaves 1.5 cases. (`tests/test_pack_consumption.py`)
- AC9: A step that uses 49 bottles from 2 cases (48 bottles) is refused ("exceeds available") and
  the lot keeps its 2 cases. (`tests/test_pack_consumption.py`)
- AC10: 24 steps that each use 1 bottle from 1 case empty it to exactly 0, the consumed flows add
  up to exactly 1 case, the stock check shows no alert after bottles 1, 12 and 23, and a 25th
  bottle is refused. 100 mL from a case lot leaves half a bottle open and the stock check reports
  `fractional_count`. (`tests/test_pack_consumption.py`)
- AC11: The costing backfill, run after deleting the flows, rebuilds the 12-bottle step as a consumed
  flow of 0.5 case and skips no inputs. (`tests/test_pack_consumption.py`)
- AC12: Wastage of 6 bottles from 2 cases (24 × 200 mL) leaves 1.75 cases. (`tests/test_pack_consumption.py`)
- AC13: `GET …/lots/<id>/cost` for 2 cases at $96 returns `pack_breakdown` with `pack` "24 × 200 mL",
  `containers` 24, `per_container` 2.000000, `per_litre` 10.000000, `per_kg` null. A lot with no price
  has `unit_cost` null and `pack_breakdown` null; a lot with no pack has `pack_breakdown` null.
  A step that uses 125 pcs from 2 boxes of 500 ($100 paid) takes 0.25 box, costs the batch $12.50
  and makes pieces at $0.10 each. (`tests/test_pack_consumption.py`, `tests/test_packs.py`)
- AC14: Manual Add Inventory: with unit "units" the pack field shows and is filled from the name
  (`Tonic 24 x 200ml` → `24 × 200 mL`); for kg it is hidden; typing `500 pcs` makes the hint
  `= $50.00 per unit · $0.10 each of 500` for $100 / 2; an edit wins over the name and the hint
  follows it (`6 x 700 mL` → `= $48.00 per unit · $8.00 each of 6 · $11.43 per litre`); an
  unreadable pack ("a few") shows "Write it like …" and stops the save with the field focused; a
  saved form stores `{"count": 6, "size": "700", "size_unit": "ml"}`.
  (`tests/e2e/test_pack_field_browser.py`, `tests/e2e/test_costing_pack_hint_browser.py`)
- AC15: None of AC2–AC13 connects Xero or needs a purchase: the org in those tests has no Xero tenant.
  (`tests/test_pack_consumption.py` builds its org with `new_org` and no `connect`.)
- AC16: At 375px the manual Add Inventory page with the pack field shown, and the Purchases record
  dialog with a row open, do not scroll sideways; the record dialog is a bottom sheet.
  (`tests/e2e/test_pack_field_browser.py::test_the_pack_field_does_not_scroll_a_phone_sideways`;
  screenshots in the MR)
- AC17: The lot panel of a cases-of-24 lot priced at $48 shows Pack 24 × 200 mL, Each $2.00 (1 of 24),
  Per litre $10.00. (`tests/e2e/test_pack_field_browser.py`)

## Assumptions (the founder can overturn any in review)

- A1. One unit of the lot is the whole pack. A lot "Tonic 24 x 200ml" held in `units` is one case
  per unit, as the existing hint already read it. Someone counting single bottles as units leaves the
  pack blank (or `1 x 200 mL`).
- A2. A pack is per lot, not per product name. The same tonic bought as a different pack later is
  a different lot with its own pack; a barcode lot refuses a conflicting pack (409) rather than
  guessing.
- A3. Packs are for raw materials and bought-in goods. The manual form does not offer the field
  for work-in-progress or finished goods (those carry `pack_volume_ml` and are made, not bought).
- A4. A pack with no size is a bare count and can't stand in for mass or volume. If someone wants
  labels used by weight they say so with a sized pack.
- A5. Changing a lot's pack later affects only later conversions.

## Out of scope (follow-ups, not built here)

- **Planning** (`planning/stock.py`, `material_adapter.py`, `start_service.py`): availability, material
  commitments and batch start convert with the standard converter. A batch planned in bottles against
  a lot held in cases reads "can't be counted" there, as before. Making it pack-aware has to be done
  in all three at once, or the plan and the start disagree.
- **Stocktake** (`stocktake.py`): counts of counted lots are whole numbers of the lot's unit, so a
  part-used case lot (23 bottles = 0.9583 case) can't be counted in bottles yet.
- **Rule templates** (`purchase_rules`): the pre-fill reads the rule's name; a rule doesn't store a pack.
- **Reconciliation of untracked lots** and **sales of finished goods** carry no pack by design.
