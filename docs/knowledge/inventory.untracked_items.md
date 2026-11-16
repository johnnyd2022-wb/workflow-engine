---
topic: "inventory.untracked_items"
title: "Untracked items"
domain: "inventory"
summary: "Stock that exists but has no recorded production history, flagged until a batch output or addition accounts for it."
related_topics:
  - inventory.lots
  - production.inputs_and_outputs
  - traceability.back
related_operations:
  - core_list_inventory
features: []
---
# Untracked items

## What it means

An **untracked item** is stock that is physically there but whose production history was never recorded in Biz-E, for example stock that predates the system. It is added as a normal lot with the untracked flag, and a note explaining it is required. Biz-E marks it with `extra_data.untracked` and sets `remaining_balance_to_reconcile` to the quantity added.

Untracked items are meant to be temporary. **Reconciling** one means matching it to a real recorded event, so the unexplained balance shrinks to nothing.

## How the records relate

- Reconciling happens in three ways: while adding stock, by mapping the untracked item to a workflow step (Biz-E records a batch for it), or by tagging a step's output with the untracked item when the step is completed.
- The completed-step path reduces the untracked lot by the smaller of the output quantity and its balance. Only any surplus becomes a new, fully sourced lot. The output name must match the untracked item's name, and the units must be compatible.
- An untracked lot has no producing step, so a trace backward ends there. See traceability.back.
- Untracked lots are listed by the untracked-items check when the quantity or the remaining balance is above zero. It surfaces as a `system_findings` entry on the lot.

## Authoritative operations

`core_list_inventory` shows `extra_data.untracked` and the note, and a `system_findings` entry with `check_id` `untracked_items` for each lot still to reconcile.

## Do not assume

- **Untracked is not lost or missing stock.** It exists. What is missing is its history.
- **Untracked is a record-keeping state, not a quality state.** It does not put a lot on hold.
- **The balance to reconcile and the quantity can differ.** The balance is what is still unexplained. The quantity is what is on hand now. ASSUMPTION: the addition path reduces the balance in the same way as the step path. That was taken from the reconciliation spec and not re-read in the code.
- **Do not treat an untracked lot's lineage as complete.** A trace back from anything made from it stops at the untracked lot.
