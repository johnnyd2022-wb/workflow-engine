---
topic: "traceability.forward"
title: "Tracing forward to what a lot went into"
domain: "traceability"
summary: "Forward trace follows recorded step inputs to every lot made from a lot, at any depth. It is the basis for recall scoping."
related_topics:
  - traceability.back
  - traceability.to_sale
  - inventory.holds
  - inventory.expiry
related_operations:
  - core_list_expired_materials
  - core_trace_inventory_to_sale_graph
  - core_trace_raw_material
features: []
---
# Tracing forward to what a lot went into

## What it means

A forward trace starts at a lot, usually a raw material, and answers "what was made with this". It finds every step that recorded the lot as an actual input, takes every lot those steps made, and repeats from each, with no depth limit.

## How the records relate

- The response groups the lots found as `intermediates` and `finals`, with `all_items` and `connections`. Lots with zero quantity are included, so the audit trail is complete.
- Forward trace tells you which lots to look at. It does not say where they are now: use stock, holds and the to-sale trace for that.
- The expired-materials list is a narrower use of forward trace. For each expired raw material with stock, it lists products made from it after it expired.

## Authoritative operations

- `core_trace_raw_material`: everything made from one lot. The id can be any lot, despite the name.
- `core_trace_inventory_to_sale_graph`: forward and backward from a lot, plus sales.
- `core_list_expired_materials`: expired raw materials and the products made from them afterwards.

## Do not assume

- **Every output of a step counts as made from every input.** Forward trace is deliberately wide, so it is safe for scoping a recall but overstates what any one lot contains.
- **A lot used in a step that was never completed is not traced.** Only completed steps record actual inputs.
- **The expired-materials list is not a full forward trace.** It leaves out products made before expiry and lots with no stock left.
- **Holding a lot does not hold what was made from it.** Those lots must be held too (inventory.holds).
