# Typed Tastings Tasks — independent spec critique

Reviewed `.agents/specs/tastings-tasks.md` against CRMTask, the CRM task repository/service/routes, Core's merged task serializer, Tastings' scheduling service/routes, and the Tasks drawer. No app, test, script, database or spec changes made.

GAP (high): Tenant scoping and subscription-lapse behavior are described only as existing rules and "generic task responses". There are materially different readers: `/api/crm/tasks`, contact-scoped task listings, Core's merged work queue, and direct task/tasting links. Core currently intentionally reads CRM records even when CRM product routes are disabled. The spec does not explicitly name which of those readers must hide specialized records, whether filtering happens before query limits, or how denied direct reads/mutations behave. → State that `crm_tasks`, `tastings`, `tasting_allocations`, and `tasting_stock_lots` retain org-scoped reads/writes and existing composite ownership constraints; backfill joins match both task ID and org ID. Apply the active-subscription exclusion before limiting all CRM/Core/contact task reads, return no tasting metadata or counts through generic responses, and deny direct specialized reads/writes after lapse. Keep historical excise/accounting access independent and intact. Name representative 404/403 response behavior for direct/deep-linked access and preserve existing permission checks.

GAP (medium): AC2 promises carried fields and no lost values, but the two existing creation contracts differ. An ordinary task permits a 500-character title and 20,000-character description; a tasting permits a 160-character title and 4,000-character notes, requires an active rep plus Auckland-offset start/end timestamps, and only receives a date from the Tasks drawer. The existing tasting service also generates the task description from venue/time instead of copying notes. A builder must guess whether to truncate, clear fields, guess an assignee/time, or reject a normal task draft. → Explicitly map title → title, description → notes, assignee → rep, contact → customer, and due date → Auckland local tasting day. Choose and disclose default start/end times (still editable), retain invalid/unselected rep data visibly for correction, and never silently truncate over-limit title/notes: preserve the source draft and show inline validation before saving. Switching back must restore all ordinary-task fields, including priority/status, even if those fields are not sent to the specialized service; retain tasting-specific draft fields when switching away and back until save/cancel. Decide what happens for fields changed while each type is active.

Non-blocking verification notes:

- AC4 explicitly covers old finished records, which the current `openTaskFromQueryString()` cannot open unless present in the loaded list. The eventual tests should exercise an old/archived record excluded from the initial list, not merely a recent completed task.
- AC5's lazy-fetch condition is testable. Include an assertion that an ordinary Tasks page visit performs zero separate tasting-list/stock-choice requests, and guard the joined tasting metadata path against per-task database queries. No new numeric performance ceiling is required by this spec, but existing performance ceilings should continue unchanged.
- AC1/AC3 require preserving relationship-based lifecycle guards as well as the new type field: a forged or inconsistent `task_type` must never make an existing linked tasting editable/deletable through ordinary task CRUD or lane changes.
- Exact-one-task creation should be verified at the persisted pair of task/event records, including form submit/double-click and failed validation; rendering one card is insufficient proof.

Initial verdict: gaps-found.

## Re-review after explicit critic resolutions

Both blocking gaps are resolved by the appended assumptions/contracts:

- The spec enumerates CRM/contact and Core active/archive readers, direct generic writes and the specialized subscription404 gate. Filtering before query limits is confirmed by the caller's shared repository/Core-query design. Existing ordinary CRM visibility and retained excise/accounting history are explicitly preserved. Tenant scope and same-org backfill remain requirements under Users/permissions and Data model; this refinement does not replace existing composite ownership constraints.
- The spec defines the complete common-field mapping, Auckland17:00–19:00 editable defaults, no guessed assignee, raw over-limit text retained with save blocked, two-way common-field synchronization, preserved ordinary priority/status and retained specialized draft/stock fields. This closes the field-limit and unsaved-switch ambiguity without silently discarding values.
- The unified creation endpoint, nested payload, atomic task/event pair and response shape are now explicit. The older specialized creation endpoint remains supported and creates typed tasks; existing lifecycle APIs retain their ownership of updates.

The earlier non-blocking verification notes still apply, particularly opening an archived finished record not loaded in the list, preserving relationship-based lifecycle guards, and checking persisted exact-one creation. This verdict grades spec readiness, not implementation correctness. No schema operations or app/test/script edits performed.

VERDICT: sound
