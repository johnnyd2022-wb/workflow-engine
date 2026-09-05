# SPEC: operational_cases
status: approved
name: Exception-to-resolution workflow — Operational cases
slug: operational_cases
blueprint: app/features/operational_cases/
url_prefix: /core/cases (pages), /api/core/cases (API)

## Description

Give an operational exception a durable owner, due date, next action and evidence-backed
closure. A finding identifies risk; a case coordinates the response and survives changes
to that finding. The first implementation (A1) lets an operator create a case from a
critical untracked-stock finding, work it through resolution and separate verification,
and return to it from Notifications, a Cases queue or Dashboard. Corrective stock and
production actions continue through their existing confirmed workflows.

Source: [execution plan, Release A](../../docs/customer-value-execution-plan-2026-09-05.md#a-exception-to-resolution-workflow).
Programme: [delivery slices](../plans/customer-value-slices.md).
Approved by the user's “excellent, get to work!” on 2026-09-05. Implementation is in progress.
The existing `/core/*` URL convention takes precedence over a new slug URL prefix.

## Approved scope decisions

- ASSUMPTION: A1 starts with `untracked_items` where the canonical check includes an
  inventory item and its on-hand quantity is positive. This matches the current critical
  traceability signal. Rejected: treating every category or every red display as critical.
  Other sources, manual creation and Compliant/CRM adapters follow in A2–A4.
- ASSUMPTION: creation is an explicit **Create case** action requiring an owner, due
  date and next action. Rejected: silently creating a case on a GET or automatically
  opening one for every finding. Configurable automatic creation belongs to Release C.
- ASSUMPTION: both existing staff roles can work cases; ADMIN controls administrative
  dismissal and reassignment. A separate active staff member verifies a critical case.
  Rejected: self-verification or silently granting the creator an override. A one-person
  tenant can resolve a case but sees “Awaiting independent verification”; no pilot promise
  of verified closure without a second eligible user.
- ASSUMPTION: Notifications remains the discovery inbox; Cases is the shared work queue.
  Rejected: storing case lifecycle in sessionStorage or building a full resolution form
  into every banner/finding card.
- ASSUMPTION: initially require an explicit due date/time in UTC (labelled in the form,
  shown with local-time equivalent); no universal due-date SLA or hidden org timezone.
  Tenant-specific deadlines and verification policy require pilot evidence first.

## Users & permissions

- roles: ADMIN, MEMBER (existing `UserRole` values; no new roles).
- tenant_scoped: yes; every new table, query, uniqueness key, link, event and cursor.
- All routes require authentication and organisation scope; derive `org_id` and actor
  from the session, never payload fields. Repositories take explicit `org_id`.
- Both active roles can list/detail cases, create from an eligible finding, and view
  linked source facts they are authorised to see. Creator may assign any active same-org
  staff member on creation. After creation, only ADMIN may reassign owner; current owner
  or ADMIN may edit due date/next action and acknowledge/start/resolve/reopen an active
  case. An owner who is MEMBER receives 403 on reassignment, including self-handoff.
- Owner must remain an active same-org member on mutation. If later deactivated, retain
  attribution/history and show “Owner unavailable — reassign”; ADMIN reassigns. Include
  unavailable owners in the unowned/needs-owner aggregate. Never reassign silently.
- Verification: any active same-org MEMBER/ADMIN except the current owner or the actor
  who recorded the latest resolution. Dismissal: ADMIN only, with reason. No self-verify
  exception even for ADMIN in A1.
- Unauthenticated: 401. Missing/foreign-org case, source, link or member ID: 404 with
  indistinguishable body. Same-org forbidden action: 403. CSRF required on mutations.

## Acceptance criteria

- AC1: With the capability enabled, selecting Create case on an eligible finding and
  submitting an active same-org owner, future due timestamp and next action creates one
  `open` critical case with an immutable source snapshot and timeline event. Concurrent
  submissions for the same active source return the same case ID; retries cannot add
  duplicate timeline/domain events or replace another user's assignment. Ineligible or
  no-longer-active source returns a validation/conflict response and creates nothing.
- AC2: Every page/API, source lookup, list/filter, timeline, mutation and LiveSync payload
  obeys the permissions above. Two-org fixtures prove no cross-tenant data, counts or
  identifier-existence leakage; unsupported fields and invalid/foreign assignees write
  nothing. With the flag off, normal feature APIs/pages return 404, existing Core still
  works, and the authorised history-only path below remains read-only.
- AC3: Only transitions in the lifecycle table succeed. Resolution needs cause, action
  taken and outcome; verification needs an independent actor, verification note and a
  freshly confirmed cleared source. Dismissal requires ADMIN and a reason. Source
  disappearance, notification hiding or failed evaluation never closes a case. Every
  accepted change increments version once; a stale version returns 409 and loses no edit.
- AC4: The source identity and recurrence rules below hold through re-evaluation, changed
  names/dates, source clear/reappearance, source deletion and repeated terminal-source
  submissions. Earlier snapshots, resolution attempts and actors remain readable and
  unchanged. A new terminal-source occurrence links to its predecessor with an audit reason.
- AC5: Banner links preserve finding category; Notifications shows Create case/Open case;
  case alerts and Dashboard links open the relevant case/queue directly. Queue filters,
  paginated detail/timeline, existing corrective-action navigation and return context work
  on desktop and a 375px viewport. Hiding a finding never changes shared case counts.
  Loading/error/empty, unsaved-edit and concurrent-update states follow the UX contract.
- AC6: Case mutation, append-only case event and `operational_case.*` EventWriter event
  commit or roll back together. No-op retries emit nothing. A second same-org browser
  refreshes its visible queue/count/detail within one configured LiveSync poll interval
  plus 2 seconds after receiving the event; another org sees no refresh or event. Dirty
  forms show a conflict notice instead of being overwritten; inactive tabs fetch nothing.
- AC7: Lists/timelines and Dashboard meet the explicit query, byte and latency budgets
  below on both fixtures. Dashboard uses its existing single summary request and does not
  fetch cases/timelines/findings separately. Disabled, stale and failed data appear with
  an availability/freshness label, never as an apparently healthy zero.
- AC8: Disposable-DB upgrade/down/upgrade passes; flag-disable/re-enable preserves case
  IDs, links and history. Fault injection before commit leaves no partial record/events;
  recovery after a lost response and concurrent retry preserves exactly one active case.
  Operator runbook demonstrates retained-data rollback, export/restore rehearsal and
  explicit source-deleted/owner-unavailable recovery without touching production data.

## UX recommendation and operator journey

Keep the original banner → Notifications idea for discovering findings. Add durable case
coordination behind the action buttons and a direct path for users returning to known work.

| Surface | Purpose | Primary interaction |
|---|---|---|
| Shared findings banner/status | Summarise risk in one compact surface | “Review findings” → `/core/notifications?category=traceability`; preserve other existing category mappings |
| Notifications | Explain each detected item and its existing corrective options | No case: **Create case**; active case: **Open case**, with status/owner/due; terminal predecessor: **Review previous case**, then explicit new-occurrence form |
| Cases, `/core/cases` | Prioritise shared operational work | Default needs-attention queue; My cases, Needs owner, Overdue, Awaiting verification and All filters |
| Case detail, `/core/cases/<id>` | Own next action and defensible closure | State-appropriate action, source facts, resolution/verification and timeline |
| Dashboard | Cross-workspace attention | Count/link from existing summary; known case link bypasses Notifications |

Notifications already has source/action menus in
[`system-findings-notifications.js`](../../app/core/frontend/js/system-findings-notifications.js)
and stores ignore/dismiss state per browser session. Existing options include disposal,
reconciliation and process/Sourcemap navigation. Retain these owning-workspace actions;
case management records who will act and what happened. Rename personal presentation
actions to **Hide for this session** / **Hide until tomorrow** with helper text that work
remains open. Scope new hide keys by org/user/source. Do not migrate old hide keys into
server state. The Cases queue and shared attention badge ignore all hide keys.

General design guidance supports a compact banner linking to relevant work and visible
task status: [GOV.UK notification banner](https://design-system.service.gov.uk/components/notification-banner/)
and [task list](https://design-system.service.gov.uk/components/task-list/). The specific
Notifications-plus-Cases recommendation is our inference from this app's existing flows
and the need for ownership/history; it has not yet been validated with customers.

Example walkthrough (prototype script for discovery):

1. Operator sees “Untracked stock needs attention”, opens the filtered Notifications view,
   reviews the item/quantity and selects Create case.
2. Form prefills the source-derived title and critical severity, asks for owner, due
   timestamp and next action (“Check batch output and reconcile the remaining quantity”).
   Submission opens the new case. Duplicate creation opens the existing case and explains
   that its owner/due date were preserved.
3. Owner acknowledges and starts work. **Review stock**, **Reconcile in process step**
   (only with valid producing-step context) and **Trace source** reuse existing routes.
   Returning through a validated relative case return link preserves queue filters.
4. After the existing corrective workflow succeeds, the case still needs resolution.
   Owner records cause, action taken, outcome and optional evidence references.
5. A different colleague checks the source and records verification. The critical case
   leaves Needs attention, stays in All/history, and both browsers update.

Case header shows severity text/icon, status, owner, due/overdue and next action before
supporting context. Desktop uses a dedicated detail page in A1; mobile uses the same
route and stacked fields, not a squeezed drawer. Source/history sections load on intent.
No color-only states; labelled controls, keyboard access, visible focus and inline error
summary. On navigation away from an edited form, warn before discarding it. After a
conflict retain typed values and offer “Reload latest” to reconcile edits manually.
Loading uses placeholders; empty queue says why the filter is empty; API failure offers
Retry and preserves the last successful view labelled stale. LiveSync uses a polite
status announcement and does not steal focus or overwrite edits.

## Lifecycle and source policy

| From | To | Actor / required input |
|---|---|---|
| open | acknowledged | Owner or ADMIN; owner/due/next action valid |
| acknowledged | in_progress | Owner or ADMIN |
| in_progress | resolved | Owner or ADMIN; cause category, action taken, outcome |
| resolved | verified | Independent eligible user; verification note; source freshly cleared |
| resolved | in_progress | Owner or ADMIN; explicit reopen reason (including source recurrence) |
| open, acknowledged, in_progress, resolved | dismissed | ADMIN; reason; recorded as administrative closure, never verified resolution |

Other transitions return 409; repeating the same idempotency key replays its original
response. “Active” for dedupe and attention means `open`, `acknowledged`, `in_progress`,
**and `resolved`** (awaiting verification). `verified` and `dismissed` are terminal.
Due/owner/next-action edits apply only to active cases. Source identity, initial severity
and snapshot are not editable in A1. Cause enum v1: `data_entry`, `process_deviation`,
`equipment`, `material`, `unknown`, `other`; other requires explanation. No invented cause
is preselected. Resolution may be recorded while risk is still present, but verification
cannot pass until the canonical source check confirms clearance.

A1 identity: `(org_id, source_type='core_finding', check_id='untracked_items',
source_entity_type='inventory_item', source_entity_id=<UUID>)`. Never use notification
array position, item name, dates or display hashes. Capture identity server-side and
validate the selected item against the canonical untracked check, including reconciliation
balance eligibility. Positive on-hand quantity sets critical eligibility on creation;
verification requires absence from the canonical check, including no remaining balance.

The source adapter returns `active`, `cleared`, `unknown` or `deleted`, with `observed_at`
and evaluation provenance. A canonical successful check can confirm cleared; a cache miss,
stale cache, failed/truncated evaluation or inaccessible source is unknown. An actual
same-org deleted source is deleted. Neither unknown nor deleted qualifies for verification.
Deleted source leaves a snapshot and recovery guidance: restore in the owning workspace
or ADMIN-dismiss with evidence/reason. The check's existing detection limits must be
respected: absence from an incomplete list is never proof of clearance.

Creation and verification re-evaluate the **selected source** under a per-source
transaction/advisory lock shared by case commands. Read canonical inventory state with
row locking through the adapter so concurrent source writes serialize with the command.
Reuse/extract the check's eligibility logic; do not invoke the full DAG check suite in a
case command. Case requests are idempotent and serialize with each other. Read-only page
GETs may display cached source observation but never create cases or mutate their state.
An explicit `POST .../refresh-source` records an observation; it never transitions state.
There is no A1 background scanner and no correctness dependency on an open browser:
durable case state/overdue queries persist independently; live source freshness is labelled.

Reappearance while a case is active links to that case; if resolved, display **Reopen**
and require the explicit transition/reason. Never erase its earlier resolution attempt.
After terminal closure, **Create new occurrence** requires owner/due/next action and a
recurrence reason. It creates a new case with `previous_case_id`; the terminal record is
unchanged. A still-active source after dismissal is deliberately suppressed from ordinary
Create case: show its dismissal/reason and require this explicit new-occurrence action.
Repeated evaluations alone never open another case. No automatic reopen policy in A1.

## Data model

- changes: additive `operational_cases`, `operational_case_links`,
  `operational_case_events`; register proposed `operational_cases_enabled` tenant
  capability using the existing feature-flag mechanism; extend event/read-model handlers.
- destructive: no forward drops, renames or existing-data rewrites. A schema downgrade
  drops new tables and is destructive to new case data; use only on disposable fixtures.
  Retained-data application rollback is specified below.

Concrete gating: new deployment config `operational_cases_enabled=false` plus an active
existing `FeatureSubscription` row with `feature_key='operational_cases'` for that org.
Both are required for normal reads/writes. Reuse the generic entitlement repository/CLI;
no new subscription table, tier or price. Missing grant means disabled. History/export
exceptions still require the explicit same-org ADMIN/operator permissions above.

| Table | Required contract |
|---|---|
| operational_cases | UUID id, org_id, title (200 chars), severity (`critical` in A1), source_type/check_id/source_entity_type/source_entity_id, immutable source_snapshot JSONB (allowlisted ≤16 KiB), status, owner_id, due_at timestamptz, next_action (2,000 chars), integer version starting at 1, previous_case_id nullable (sole canonical predecessor), created_by/created_at/updated_at |
| operational_case_links | UUID id, org_id, case_id, relation (`source`, `evidence`), allowlisted entity_type/entity_id, created_by/created_at; original source link immutable; evidence additions append only |
| operational_case_events | UUID id, org_id, case_id, case_version, event_type, actor_id, recorded actor attribution, occurred_at, structured payload, corresponding EntityEvent id; append only, unique `(org_id, case_id, case_version)` |

A1 source snapshot schema v1 contains exactly: `schema_version` (1), `check_id`
(`untracked_items`), `source_entity_type` (`inventory_item`), `source_entity_id` (UUID
string), `item_name` (trimmed text, truncated to 200 Unicode characters), `unit` (trimmed
text, maximum 64 characters), `quantity` (required finite canonical Decimal string,
maximum 64 characters), `remaining_balance_to_reconcile` (null if absent, otherwise a
finite canonical Decimal string, maximum 64 characters), `source_execution_id`,
`source_execution_step_id`, `producing_step_id` (same-org UUID strings or null),
`observed_at` (UTC ISO-8601), `adapter_version` (`untracked_items_v1`),
`critical_reason` (`positive_untracked_stock`), and `truncated_fields` (array containing
`item_name` if truncated, otherwise empty). UUID references are tenant-validated; absent
optional references are null. Preserve absent remaining balance as null in the snapshot;
eligibility and verification use the canonical check's missing-as-zero normalization.
Positive-stock legacy rows with no remaining-balance metadata remain eligible; add an
AC1 regression for that case. Missing/invalid required quantity or unit, non-finite
numbers, malformed references or final UTF-8 JSON exceeding 16 KiB reject creation with
400 `invalid_source_data`; never fabricate zero or silently trim numeric/unit data.
Required numeric values are derived by the canonical check logic; optional presentation
fields cannot substitute for them. No raw `extra_data`, supplier/batch values, notes,
execution prompts/answers, arbitrary finding messages, or whole check payloads are copied.
Case title is server-generated from the bounded item name, capped at 200 characters.
Test the exact key set, forbidden-field exclusion, Unicode truncation marker and invalid
source rejection. This snapshot is business evidence stored only in the case record.

`previous_case_id` is the only predecessor relation used by reads, audits and exports;
do not duplicate it in operational_case_links. A recurrence command must identify the
latest same-source terminal predecessor; the server checks this under its source lock.
A missing/stale/wrong-source predecessor on a recurrence returns 409; a foreign-org ID
returns 404. The creation event records the predecessor ID/reason in the same transaction.

Case events hold structured resolution attempts, verification, reasons and before/after
assignment/deadline/action changes; the list row holds current projection fields. One
accepted command creates one version/event; an observation creates a version only if its
recorded source state changed. Earlier event payloads and snapshots cannot be edited.
All timestamps UTC; user text never enters product telemetry. Resolution action/outcome,
reopen/dismiss/verification notes are each 1–2,000 trimmed characters. A command body is
≤32 KiB; at most 10 existing evidence references per command. No file uploads or arbitrary
external URLs in A1. Allowlisted evidence targets: same-org execution evidence and
inventory/execution records accessible through their owning routes.

Enforce enum/status checks, `(org_id,id)` parent uniqueness and composite org-aware
foreign keys for case children/predecessors. Validate owner and polymorphic source/evidence
targets in their owning tenant-scoped services. No cascade from source/user deletion into
case history; record actor attribution at event time. User references may be tombstoned
without rewriting attribution. Audit links survive a source being removed.

Indexes: `(org_id,status,due_at)`, `(org_id,severity,updated_at DESC,id DESC)`,
`(org_id,case_id,case_version DESC)` for timeline; partial unique source tuple WHERE
status IN ('open','acknowledged','in_progress','resolved'). This database constraint is the
last guard for concurrent creation. No uniqueness by title/date. An active-source conflict
returns the existing case without changing it. Reuse `ApiIdempotencyKey` infrastructure
with explicit tenant/actor/command scope and payload hash (including expected_version);
an identical retry returns the same response, changed payload with same key returns 409.
Record the idempotency receipt in the transaction; do not store it only in browser memory.
Client keys are 1–128 characters. Store `oc:` plus SHA-256 of the actor UUID, HTTP method,
canonical route including case ID and client key in the existing 128-character key field;
org_id remains the database uniqueness scope. This prevents collisions with existing
wastage receipts and cross-actor response replay without changing that table's schema.

## API, ownership and event contracts

| Route | Contract |
|---|---|
| GET /api/core/cases | Filters owner (`me`, `needs_owner`, UUID), severity, status (default active set), source, overdue; opaque org/filter-bound cursor, default 25/max 100 rows; compact summaries and next_cursor |
| POST /api/core/cases/from-finding | Source identity, owner_id, due_at, next_action, optional previous_case_id/recurrence reason; Idempotency-Key required; 201 new / 200 existing active |
| GET /api/core/cases/<id> | Current compact fields, version, source snapshot/state/freshness and permitted actions; timeline separate |
| PATCH /api/core/cases/<id> | Allowlisted owner/due/next-action only; expected_version and Idempotency-Key required |
| POST /api/core/cases/<id>/transitions | target status, expected_version and required structured fields/evidence references; Idempotency-Key required |
| POST /api/core/cases/<id>/refresh-source | Explicit selected-source observation; expected_version and Idempotency-Key required; no lifecycle transition |
| GET /api/core/cases/<id>/events | Cursor by case_version descending, default 25/max 100; evidence links in that bounded event payload |
| GET /api/core/cases/history/<id> | Read-only detail/history shell data for same-org ADMIN when feature disabled; paginated events via history/<id>/events; no actions/source refresh |

Malformed/unknown inputs: 400. Stale expected_version or source no longer eligible: 409
with machine reason and latest case version where authorised. Expected_version is mandatory
on updates; invalid transition/eligibility failures create no case/domain event. For new
cases due_at must be future; existing overdue dates are retained until explicitly changed.
Changed due_at must also be future. Terminal cases have no edit endpoint.

Deterministic queue order is `updated_at DESC, id DESC`; filters handle urgency without
unstable wall-clock sorting. Overdue means due_at < server now and active, including
awaiting-verification cases; needs-owner includes inactive owner. Cursor pagination is a
live list, not a snapshot: after LiveSync invalidation reset to first page and dedupe IDs.

Service/repository code belongs under the new feature, following `.agents/conventions.md`.
Source adapters consume compliance-checks/owning-domain services; those domains must not
import case business logic. Register composition in app factory. Dashboard consumes a
case summary service; its route must not query new tables directly. Every command writes
through EventWriter in its existing transaction. Case events reference the emitted domain
event; failure of either audit write rolls back the mutation. Add `operational_case` to
existing feed/type validation and summary rendering where required; test actual delivery,
not merely that emit was called. Event names: `operational_case.created`, `.updated`,
`.acknowledged`, `.started`, `.resolved`, `.verified`, `.dismissed`, `.reopened`,
`.source_observed`. Structured telemetry contains IDs/versions/state, not business text.

Notifications obtains case summaries for its visible source IDs in one bounded
`POST /api/core/cases/source-status` read-only batch API, up to 100 source identities,
CSRF/auth/org-scoped and capability-gated. Return the active case or latest terminal
predecessor summary for each authorised source, with no free-text history. It has no
side effects and does not require an idempotency key. Foreign source IDs return 404 for
the entire batch. Render at most 25 Notifications cards per page before requesting their
case status; preserve existing category/hide filters. Never request one case per card. Keep the
existing findings API consumers compatible; do not move case creation into that GET.

Dashboard adds `operational_cases: {availability, as_of, active_count, critical_count,
overdue_count, needs_owner_count, awaiting_verification_count, href}` to its existing
summary. Counts overlap intentionally; do not sum them into a total. Disabled yields
`not_enabled` and null counts; failure yields `unavailable` and null counts. Active count
includes resolved pending verification. Use case aggregates, not a rerun of findings.

LiveSync invalidates only visible case lists/detail and counts for that org, coalescing
events through the existing subscription lifecycle. An open Notifications page refreshes
its case-status batch; Dashboard refreshes its summary. Do not cause every component to
fetch the whole source history or run checks. Due-time counts recompute on summary/list
requests and visible-tab resume; no stored “overdue” bit needing a worker to stay correct.

## Performance and validation plan

Proposed A1 budgets (engineering acceptance targets, not measured claims):

| Surface | Incremental feature queries | Uncompressed feature response bytes | Warm-server p95 |
|---|---|---|---|
| Queue at 25 rows | ≤3, independent of row count | ≤32 KiB | ≤500 ms |
| Detail / timeline at 25 events | ≤3 each | ≤32 KiB / ≤256 KiB | ≤500 ms each |
| Dashboard cases section | ≤1 aggregate query | ≤2 KiB added | ≤100 ms added to measured baseline |
| Visible finding case-status batch (≤100 identities) | ≤2 | ≤32 KiB | ≤500 ms |

Auth/session/tenant middleware queries are recorded separately in the baseline; no per-row
lookups hidden in the exclusion. Detail snapshot budget is included in 32 KiB. Cap event
payloads at 8 KiB, including evidence refs; timeline cap follows from 25 bounded events.
Validation rejects text that exceeds either character or encoded-byte payload limits.

Fixtures: small tenant (100 cases/1,000 case events) and long-lived tenant (100,000 cases,
1,000,000 events, 10% active), with second-org decoys and skewed owners/due dates. Record
baseline p50/p95/p99, query count, bytes and EXPLAIN ANALYZE BUFFERS; at least 100 requests
per measured read path after warm-up on a documented runner. CI asserts query/byte bounds;
controlled performance job enforces latency. Save evidence in implementation report before
pilot. Cache only tenant/versioned aggregates if measurement warrants it and define exact
invalidation; do not use caching to excuse unbounded SQL.

Use real PostgreSQL tests/factories for AC1–4/6/8, including concurrent sessions and
commit-failure injection. Playwright covers AC5–7 with two browser contexts plus another
org, dirty forms, source reappearance/deletion, source-check failure and missing owner.
Network assertion: initial Dashboard still issues exactly one summary data request;
no case/findings waterfall. New standalone queue/detail fetches only their bounded data.
Run migration-safety, security/tenant audits, e2e, performance, observability, test-author,
test-evaluator and CI gates during implementation per `/new-feature`; no code gates are
claimed complete by this documentation-only work order.

## External surfaces

- New authenticated same-origin pages/APIs and existing LiveSync event feed.
- Existing Core reconciliation, stock, execution and evidence routes via validated local
  links; no direct stock/production mutations from case commands.
- No external APIs, webhooks, email/Slack, uploads, automatic scheduler or worker in A1.
  Release C owns durable background automation and notification delivery rules.

## Rollout and recovery plan

1. Discovery: five sessions from the programme; validate triage wording, owner/deadline,
   critical eligibility, independent verification and one-person-tenant handling. Baseline
   acknowledge/verified resolution time and unowned/overdue rate; do not invent targets.
2. Apply additive migrations to disposable/internal data first. Flag stays off. Confirm
   indexes, tenancy and rollback. No backfill of historical findings into cases.
3. Pilot two to five opted-in orgs with named owner and verification colleague. Enable
   capability only after discovery/readiness and the implementation gates pass. Measure
   first case activation, overdue rate, recurrence within 30 days and verification delays.
4. On defect, disable capability server-side, rejecting new commands at the transactional
   write boundary as well as request entry; already committed commands remain. Hide normal
   Cases actions/aggregates and preserve all case tables/events. Same-org ADMIN can use
   read-only history routes and a documented tenant-scoped export CLI. Re-enable against
   retained state after repair; never re-create existing cases from cached notifications.
5. Roll back application code with additive schema retained. For an older application
   without history routes, operators use the documented read-only tenant export tool.
   Before any future removal, use an explicit backup/export and restore rehearsal on
   disposable data, compare case/event counts and checksums, and seek a separate removal
   decision. A normal feature rollback must never execute the table-dropping downgrade.

Implementation must supply the tenant-scoped read-only export CLI and runbook, including
JSONL case/link/event exports, schema version and manifest counts/checksums; streaming
batches ≤500, no production connection in agent verification. Export is ADMIN/operator
only and handled as tenant business data, never telemetry. A disposable restore rehearsal
uses exported IDs and reconciles uniqueness/events; no general production restore API.

## Out of scope

- A2–A4 adapters/manual cases, CRM task creation and Compliant record mutation.
- Automatically creating/reopening cases, rules, owner routing, scheduled reminders,
  durable notification receipts/preferences and external delivery (Release C).
- New findings engine, arbitrary case fields, chat, generic projects or custom role system.
- Automatic disposal, write-offs, quantity adjustment or bypass of existing confirmations.
- Planning, forecasting and cockpit trends beyond this slice's compact attention count.
- File duplication/uploads, arbitrary evidence URLs, automatic deletion/retention of history.

## Readiness record

Authoring inspected Core check severity/identity, Notifications actions/session storage,
system findings cache, EventWriter, permissions, feature index and slicing conventions.
Local preflight: test DB available; this worktree has no venv/dependencies or running app.
These do not block a draft spec; runtime, migration and browser verification remain
implementation work. Customer interviews, measured performance and pilot sign-off have
not occurred in this task. [Independent spec critique](../reports/operational_cases/spec-critic.md)
resolved three initial gaps and one introduced legacy-data mismatch; final verdict sound.
This checks specification consistency. The user subsequently approved implementation
on 2026-09-05; customer discovery and pilot enablement remain separate rollout gates.
