---
topic: "planning.planned_batches"
title: "Planned batches"
domain: "planning"
summary: "A planned batch is a proposed run with frozen timing and an editable start date. It is a plan, not production, and reserves no stock."
related_topics:
  - production.batches
  - planning.stock_cover
  - inventory.ready_dates
related_operations:
  - planning_get_planning_batches
features: []
---
# Planned batches

## What it means

The planner turns a production demand into individual **planned batches**, each of one workflow output at one site. Its status is `blocked`, `planned`, `cancelled` or `started`. A `started` plan has a real batch behind it (production.batches).

A planned batch freezes its quantity, unit, workflow version, step durations and waits, demand reference and site. It has an editable `proposed_start_date`, a `theoretical_ready_date` worked out from step timings and ready-date rules, and a `forecast_ready_date` that stays empty until material, capacity and compliance stages are in.

## How the records relate

- Manual demand is a quantity the producer chose to make. It is rounded to the batch size and does not deduct stock.
- The planner can check materials for planned batches and commit lots to them. A commitment warns elsewhere but does not block.
- Dates start no earlier than today. A changed workflow needs review before a plan starts.

## Authoritative operations

`planning_get_planning_batches` lists plans between `start` and `end` (default the next seven days). `truncated` is true when more matched.

## Do not assume

- **A planned batch is not production.** Nothing has been made or used.
- **`theoretical_ready_date` is an estimate and may be null.**
- **A `blocked` plan cannot start** until its reasons are resolved.
