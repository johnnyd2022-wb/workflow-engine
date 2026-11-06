# Planning commits materials (GL-P07 B2a)

Founder decision (2026-10-27): planning **soft-commits** materials. Others see the stock as
committed; using it warns but isn't blocked.

## What was there

The materials check needed an exact lot bound to every raw input on the planner's settings.
Even then availability was always "unresolved", deliberately, until a ledger of commitments
existed. Every planned batch said "Material availability unresolved", whatever was on the
shelf.

## What changes

- **A raw input finds its own stock.** An input with no lot chosen is met from the business's
  raw lots of that material, matched by name (case and spacing ignored), soonest to expire
  first. The lots can be held in any unit that converts: 1,000 g and 4 kg of caster sugar both
  meet an input of 2 kg. A lot chosen on the planner still wins, and is then held for that input
  only.
- **Availability is real.** A raw lot on hand is available from today, less what an unfinished
  execution step has already recorded using. Ownership, holds written into a lot's data,
  transit and site are checked as before and still block.
- **Checking materials commits them.** Each check allocates every live batch in start order
  and records each allocation in `planning_material_commitments` as an *active* commitment,
  held in the lot's own unit. What each batch held before is released, since everything was
  re-allocated together. A batch that can't get all its materials commits nothing.
- **A commitment ends with its batch.** Starting a batch *consumes* what it held; cancelling the
  batch or its demand *releases* it.
- **The board says what it found.** A batch's details list what is held for it ("Caster sugar ·
  1 kg held") and what it's short of ("Short of Caster sugar: 1000 g"). Its checks list drops
  "Materials have not been checked" once materials are held, or says "Not enough materials to
  start".
- `commitments_for_items` answers "what's held on these lots, and for which batch". B2b uses it
  on the stock screens.

## Not in this change (B2b)

- Inventory detail: "4 kg committed to Batch G-0412 (starts 3 Nov)".
- Soft warnings when disposing, consuming or selling committed stock.
- Supplier lead times turning a shortage into "order by 28 Oct", and a notification for it.
- Inputs made by another workflow (intermediates) still aren't planned.
- A started batch's inputs are held only once its steps record them. Between Start and the
  first recorded step, the floor is trusted.
- The start check (`evaluate_start`) stays closed until B4.

## Checks

- `tests/features/planning/test_material_adapter.py`:
  - unbound inputs are met from the same material's lots, soonest to expire first, across units,
    and never from another business;
  - inputs recorded on an unfinished step are held, and hold markers in JSON still block;
  - cancelling releases and starting consumes; cancelling a demand releases its batches;
  - concurrent checks leave one set of active commitments;
  - queries stay constant however many batches there are (7 → 9).
- `tests/e2e/planning/test_material_phone.py`: on a phone, a bound 5 kg lot is held for two 2 kg
  batches and the third is 1 kg short.
- Mutation check: removing any of the three lifecycle hooks fails a test.
- Screenshots (`ui_shots.py seed commitments`): board laptop, phone, dark, and planner settings.
  This refines the existing board, so there is one version.
