# Core Tasks

## Purpose

Core Tasks is the always-on operational work board. It gives each organisation a durable
place to plan and assign work without making production work a CRM record. The board also
shows existing CRM tasks as a separate source, so a team sees its work in one place while
customer context remains in CRM.

## Scope and access

- Core exposes Overview, Inventory, Product workflows, and Tasks as one tabbed workspace.
  `/core?tab=tasks` is the work board. `/core/tasks` remains a redirect so old
  notification links keep working. `/core/tasks/configuration` contains task settings.
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
therefore shared across browsers and devices for the organisation. Core stores the full lane
order and hidden standard lanes in its organisation task configuration, so members can drag a
custom or standard lane between any other lanes, hide a standard lane, and recover it from
Manage lanes on another device.

Members can add, rename, remove, and reorder custom lanes. Reordering submits the complete
custom-lane order in one transaction and stores the combined board order in the organisation
configuration. Deleting a custom lane sets its tasks back to their status lane through a
foreign key with `ON DELETE SET NULL`; no task is deleted or hidden. A lane can only be
assigned to a task on its own organisation and board. The board supports more than one custom
lane.

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
- The upcoming strip uses the CRM calendar interaction: it is pointer-draggable, grows one
  month at either edge, shows the visible month and a subtle drag-to-scroll cue, and filters
  by a clicked date.
- Completed and cancelled work remains on the active board for one week by default. The
  organisation can choose a whole-number archive period in days, weeks, or months. Older work
  is excluded in the database from the initial bounded board query and is fetched only after a
  member selects Load archive, where cards carry an Archived tag.
- Dragging a Core task makes at most two writes: lane placement then status. CRM board
  dragging uses its own durable lane endpoint and one status write if required.
- The due-task check is live and index-backed by `(org_id, due_date, status)`, so it does
  not invalidate or recompute the expensive inventory findings cache.
- The expensive findings cache has an explicit `org_id` predicate even outside a request,
  preventing background jobs and direct callers from reading another organisation's cache.
