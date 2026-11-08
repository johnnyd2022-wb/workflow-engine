# SPEC: tastings_tasks
status: approved-unattended
name: Tastings as a task type
slug: tastings_tasks
blueprint: existing CRM and Tastings modules
url_prefix: /crm/tasks

## Description
Refine draft MR !586 in the direction explicitly chosen by the founder: one Sales Tasks workspace, one task record per tasting, and the existing Board/List/Week views. A task type selects a general follow-up, call, email or NZ Alcohol tasting. Selecting Tasting reveals the existing venue/stock form without saving an intermediate task or navigating to another page. Opening a tasting task displays its lifecycle and stock controls in place. A secondary Tasting stock action exposes reusable leftovers. Retain the verified stock/excise ledger and all its accounting safeguards.

## Users & permissions
- Tenant scoped, existing sales.view / sales.record and inventory.adjust permissions.
- Tasting type, filter, stock action and creation are available only with active nz_alcohol subscription. Existing tasting records after subscription lapse are excluded from generic task responses; accounting history remains intact.

## Acceptance criteria
- AC1: Persist task_type on CRM tasks (general/call/email/tasting), default existing tasks to general and backfill linked tastings. Reject unsupported types and type changes which would attach/detach a tasting or bypass its lifecycle. Backend subscription checks cannot be bypassed by forged type fields or generic task creation.
- AC2: New task offers a Type selector; general/call/email use the existing drawer. Tasting reveals the specialized form in the same workspace with unsaved title, notes, assignee, customer and selected day carried across. No preliminary save, duplicate task, page redirect or lost values on switching back. Unknown optional data is not sent into the tasting service.
- AC3: Board/List/Week display the same typed task records, with a compact tasting status/time/venue cue and a type filter preserved when changing view and by shareable URL. Clicking a tasting opens its details in place; tick-to-complete routes to outcome entry, and dragging cannot falsely complete a tasting. Generic tasks retain existing CRUD and lanes.
- AC4: Tasting form save creates exactly one typed task and one linked event atomically, refreshes the task views without full-page reload, and keeps the user's current view/filters. Outcomes/dispatch/cancel update that task in place. Existing Core merged tasks link to /crm/tasks?task_id=... and open the correct detail, including old finished records.
- AC5: A secondary Tasting stock panel supports balances, pagination and reuse. The same task detail offers removal date/stock confirmation and measured mL usage; existing conservation, excise snapshots/idempotency, permission/tenant rules and separation from Library stock are unchanged. Opening Tasks alone does not fetch separate tasting event lists or stock choices.
- AC6: Retire standalone tasting scheduling layouts and concept switch. /crm/tastings becomes a subscription-gated compatibility redirect to filtered Tasks, preserving validated tasting deep links; no independent duplicate calendar. Board/List/Week are supported task views, not temporary concepts.
- AC7: Real browser tests cover typed creation, general CRUD, all three view/filter combinations, inline stock lifecycle/reuse, deep links/boosted revisit/Back, phone/dark, gated orgs and failed requests. Backend verifies migration/backfill, type gating/validation, hostile references and no duplicate task. Independent security/build/test review and CI pass.

## Data model
- changes: additive CRMTask.task_type string with allowed-value check, default general; backfill only existing same-org tasting links. New migration after tastings_001; scratch up/down/up only.
- destructive: no; downgrade removes the new type column only, existing tasting stock/removal records remain.

## Assumptions
- ASSUMPTION: General, Call and Email are simple labels for ordinary CRM tasks; Tasting owns specialized venue/stock details. Rejected arbitrary user-defined schemas or production-task type migrations in this feature.
- ASSUMPTION: Refinement of the founder's chosen direction uses the established three Tasks views, removes all standalone concept styles, and needs no new style selection. Rejected another three-way page-design decision.
- ASSUMPTION: Planning stock remains optional and removal/outcome are separate deliberate writes; no automatic stock deduction on task completion. Rejected automatic excise or guessed consumption.
- ASSUMPTION: Existing records remain auditable after subscription lapse but specialized tasks are hidden from general task APIs until renewed; no lifecycle mutation through generic APIs.

## External surfaces
- Research only, no integrations or external communications. Existing app APIs and draft MR.

## Out of scope
- Recurrence, POS attribution, offline sync, custom task schemas, production-task type redesign, returns to bond, excise calculation changes, completed-outcome amendment, deployment.

## Critic resolutions
- Lapse gating applies to CRM list (including contact_id-filtered lists/contact detail tasks), Core merged list/archive and direct generic CRM PUT/DELETE/lane writes. Hide tasting task details in those readers while unsubscribed; generic writes remain rejected regardless of type or subscription. Specialized page/API keep their existing404 subscription gate. Core's historical visibility of ordinary CRM work when the CRM product is off remains unchanged. Record history is retained, not deleted. Source metadata changes only for tasting tasks.
- Lossless draft mapping: title→title, description→notes, assigned_to_user_id→rep_id, contact_id→contact_id, due_date→NZ starts/ends date. New start17:00/end19:00 NZ on selected day or current NZ day; do not guess a rep if unassigned. The specialized form retains the current raw text even if over160/4000; native validation blocks save and explains limits, never truncates. Switching back maps these common fields to the ordinary draft; specialized fields/stock selections are retained when toggling again until save/cancel/new task. Preserve priority/status of the ordinary draft on return. No network save until explicit form submission.
- Unified HTTP creation: POST /api/crm/tasks with task_type=tasting and nested tasting payload delegates to existing save_event within one transaction and returns task plus tasting. Generic title is not required outside that nested payload. Ignore no forged lifecycle/type fields: unsupported task_type rejected; ordinary tasks cannot convert to tasting through PUT; linked tasting task_type cannot be rewritten via generic PUT. Existing POST /api/crm/tastings remains a supported accounting API and also creates typed tasks. Frontend uses unified endpoint for new tasks and specialized PUT/dispatch/finalise/cancel for owned lifecycle.
