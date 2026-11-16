---
topic: "inventory.ready_dates"
title: "Ready dates"
domain: "inventory"
summary: "A made lot can be on hand but not usable until a ready date that Biz-E works out from the step that made it."
related_topics:
  - inventory.availability
  - inventory.expiry
  - production.steps
  - planning.planned_batches
related_operations:
  - core_list_inventory
  - core_list_output_ready_date
features: []
---
# Ready dates

## What it means

Some outputs are not usable straight away, for example something maturing, resting or fermenting. A workflow's step output can carry a **ready-date rule**. It is one of:

- `fixed_duration`: ready = the time the step was completed plus a set duration, in days, weeks, months (about 30 days) or years (about 365 days);
- `set_at_execution`: the person completing the step enters the date, and it is stored on the lot (`extra_data.ready_date_actual`).

The rule can also carry a warn-before-ready window. A lot inside that window is labelled "Nearing ready", but it is still not usable.

The boundary is inclusive: before the ready time the lot is **not ready**, and at or after it the lot is **ready**.

## How the records relate

- A fixed-duration date is not stored on the lot. Biz-E works it out from the producing step's completion time and that step's output rule, matched by output name and unit. ASSUMPTION: the rule is read as it is now, so editing a workflow's rule later would move the dates of lots already made. This was read in code, not tested.
- Stock that was bought or added by hand has no producing step and so no ready date. It counts as ready.
- A step's expiry must be on or after its ready date. Biz-E refuses a rule or an entered date that breaks this.
- A step will not use a lot before its ready date unless the person confirms.

## Authoritative operations

`core_list_output_ready_date` returns made lots with quantity whose ready date has not arrived (at most 500). Each has the computed date and a state, "Not ready" or "Nearing ready". Quote its date rather than estimating one. `core_list_inventory` gives `ready_date_display` for each lot and the same finding in `system_findings`.

## Do not assume

- **An empty `core_list_output_ready_date` does not mean no lot has a rule.** It lists only lots still waiting. A lot that is already ready is not in it.
- **Ready date is not the production date, and not the expiry.**
- **Stock cover and sales matching ignore ready dates.** See inventory.availability.
- **A planned batch's `theoretical_ready_date` is an estimate**, and is null when the date cannot be predicted. It is not the date of any lot. See planning.planned_batches.
- **"Ready" here is about the lot. Cost "readiness" is a different idea** (costing.readiness).
