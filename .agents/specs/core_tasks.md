# Core Tasks

## Purpose

Core Tasks is the always-on operational work board. It gives each organisation a durable
place to plan and assign work without making production work a CRM record. The board also
shows existing CRM tasks as a separate source, so a team sees its work in one place while
customer context remains in CRM.

## Scope and access

- Routes: `/core/tasks` and `/core/tasks/configuration`.
- APIs: `/api/core/tasks`, `/api/core/tasks/configuration`, and `/api/core/tasks/lanes`.
- The feature is mounted with Core in every environment and has no feature flag or
  FeatureSubscription check. Every data query is still constrained by `org_id`.
- Any authenticated active organisation member can create, assign, update, complete, or
  cancel a Core task. An assignee must be an active user in that same organisation.

## Task records

`core_tasks` stores title (required), optional notes, optional due date, priority,
assignee, creator, status, completion timestamp, and timestamps. Statuses are `pending`,
`in_progress`, `completed`, and `cancelled`; priorities are `low`, `medium`, and `high`.
Changes emit `core_task.*` entity events in the same transaction as the row mutation.

The Core board reads Core tasks and CRM tasks in bounded organisation-scoped queries. CRM
cards are visibly labelled and link to CRM for editing, preserving their customer link.
Core task writes never depend on CRM being enabled.

## Lanes and recovery

The standard To Do, In Progress, Done, and Cancelled lanes are status projections. Custom
lanes are persisted in `task_board_lanes` with their board (`core` or `crm`), organisation,
title, and order. Each Core or CRM task stores its selected custom lane ID. A custom lane is
therefore shared across browsers and devices for the organisation.

Members can add, rename, remove, and reorder custom lanes. Reordering submits the complete
lane order in one transaction, so a partial browser update cannot leave duplicate or unstable
positions. Deleting a custom lane sets its tasks back to their status lane through a foreign
key with `ON DELETE SET NULL`; no task is deleted or hidden. A lane can only be assigned to a
task on its own organisation and board. The board supports more than one custom lane.

## Notifications and findings

Each organisation has one `core_task_configs` policy row. The default sends due-soon
notifications seven days before the due date. Members can enable or disable those alerts
and choose a whole-number lead period in days, weeks, or calendar months. This policy
applies to both Core and CRM tasks visible in the consolidated work queue.

`tasks_due` is a live Core check. Due-soon work appears in Notifications but does not lower
health. An open task whose due date is before today is flagged as an overdue system finding,
regardless of the due-soon setting, until it is completed or cancelled. The Notifications
page renders one actionable card per task and opens the Core board.

## UX and performance decisions

- The board loads tasks, durable lanes, and users concurrently; assignee names are resolved
  in one user query, avoiding card-level requests.
- The upcoming strip is a compact 14-day filter with due-count markers.
- Dragging a Core task makes at most two writes: lane placement then status. CRM board
  dragging uses its own durable lane endpoint and one status write if required.
- The due-task check is live and index-backed by `(org_id, due_date, status)`, so it does
  not invalidate or recompute the expensive inventory findings cache.
- The expensive findings cache has an explicit `org_id` predicate even outside a request,
  preventing background jobs and direct callers from reading another organisation's cache.
