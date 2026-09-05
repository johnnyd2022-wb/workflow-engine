# Customer-value execution plan — 5 September 2026

## Purpose

This plan converts four high-value product bets into a sequenced delivery programme:

1. an exception-to-resolution workflow;
2. demand, capacity, and stock-risk planning;
3. configurable automations and alerts; and
4. a business-performance cockpit.

The intended outcome is not more reporting. It is a daily operating system that helps a
producer spot a material risk, give it an owner, understand its commercial or production
impact, and prove that it was resolved.

Customer self-service is deliberately excluded. It remains an appropriate higher-tier
offer, but is not a dependency of this programme.

## Product thesis, customer and proof of value

Biz-E wins when a small regulated manufacturer can run one real workflow with less
spreadsheet coordination, less audit anxiety and less founder-only knowledge than before.
These investments are therefore designed for the people who must make a decision now, not
for a hypothetical executive-analytics persona:

| Customer moment | Primary user | Product response | Evidence of value |
| --- | --- | --- | --- |
| A batch, stock item, record or customer commitment becomes risky. | Founder/operator or operations manager | A case makes the risk, owner, due action and closure evidence unmistakable. | Fewer unowned/overdue risks; a faster, verifiable resolution. |
| A customer order or planned demand could exceed available materials or time. | Founder/operator or production planner | A dated, confidence-labelled scenario reveals the first shortage and required decision. | Shortfalls are identified before their due date; fewer expedites/stockouts. |
| The same risk is noticed and chased repeatedly. | Operations manager or compliance/quality staff | A narrow, auditable rule creates the same work once and tells the responsible person. | Less manual chasing without alert fatigue or duplicate work. |
| A founder needs to decide where to intervene this week. | Founder/operator | The Dashboard names the material change, its data quality and the owning workspace. | Faster drill-through to a decision, not more time reading charts. |

The first target cohort is small regulated manufacturers with a live Core workflow and a
named operating owner. Distilleries, breweries and wineries are the initial validation
cohort; the data model and UX must remain industry-neutral for every Biz-E organisation.
Whistlebird data is a realistic test fixture and discovery reference, never a tenant-only
product behaviour or an implied default configuration.

The commercial claim for this programme is deliberately modest and provable: **make a real
operational decision easier to see, assign and evidence.** Do not market savings, margin
improvement, forecasting accuracy or compliance assurance until pilots establish a
repeatable baseline and outcome measurement.

## Review basis and constraints

The plan was reviewed against the current documentation and merged implementation:

| Existing capability | What it makes possible | Planning implication |
| --- | --- | --- |
| Core system findings, Notifications, reconciliation and source-map links | The platform already detects inventory, expiry, traceability and execution risk. | Do not create another findings engine. Turn findings into durable, owned resolution work. |
| CRM tasks with status, priority, due date and assignee | A familiar task pattern already exists for commercial work. | Reuse its interaction conventions, but do not overload CRM tasks with production/compliance provenance. |
| Compliant records, evidence references and optional feature gating | Compliance work has its own source of truth and audit requirements. | Cases may link to a compliance record; the record remains authoritative. |
| `entity_events`, `EventWriter`, `EntityEventSummary` and LiveSync | Mutations are auditable and can update other users' screens without a reload. | Emit domain events for cases, plans and rules; use targeted subscriptions and compact read models. |
| Dashboard's one-summary-request control-tower contract | Dashboard is deliberately cross-workspace and action-first. | Dashboard may show counts, explanations and links, never fetch detailed case/planning data itself. |
| Core hub's compact overview plus lazy tabs | Real organisations have unbounded inventory and execution history. | All new overview surfaces need bounded aggregates; drill-down records load only after intent. |
| Core processes, executions, inventory movements and product mappings | The raw operational lineage exists. | Planning can begin with explicit demand plus inventory/execution facts; it must not pretend that incomplete historic data is a forecast. |

The following decisions are therefore locked for every delivery:

- Every record and query is `org_id` scoped and feature-gated where appropriate.
- The source system owns its facts: Core owns production and stock, Compliant owns evidence
  controls, CRM owns customer commitments and receivables.
- Dashboard remains the control tower; Core, Compliant and CRM remain working surfaces.
- New migrations are additive and reversible. Never edit an applied migration.
- Read paths use aggregates/read models, bounded lists and cursor pagination. No client-side
  fan-out, N+1 enrichment, or full-history response on first paint.
- Automatic actions may create work and notify people; they must not alter inventory,
  execution, financial or compliance facts without an explicit user-confirmed workflow.

## Programme order

| Release | Outcome | Why now | Dependency |
| --- | --- | --- | --- |
| A. Resolution foundation | Every important exception has a visible owner and closure trail. | It converts existing signals into action and supplies the common unit for automation and management reporting. | Existing findings, users, CRM tasks, compliance records. |
| B. Planning foundation | A planner can enter committed demand and see stock shortfalls and required production. | It prevents the next operational problem rather than documenting the last one. | Core inventory, executions, product mappings; Release A for risk hand-off. |
| C. Guardrail automation | Repeated, policy-backed risks open or update the right case and notify the right owner. | It removes manual chasing after a trusted case lifecycle exists. | Releases A and B; event stream. |
| D. Performance cockpit | Leadership sees service, cash, flow, risk and resolution trends with an explanation. | It should consume proven operational data, not lead the product with speculative charts. | Releases A–C and existing CRM/Core/Compliant summary data. |

Each release should be independently shippable behind a tenant capability flag. Do not wait
for all four before customers receive value.

## Delivery operating model: discovery to general availability

Every release follows the same small-customer-safe path. It keeps the product's
low-implementation promise while stopping one unusually complete test tenant from setting
the standard for everyone else.

| Stage | Required output | Exit decision |
| --- | --- | --- |
| 0. Qualify | A named pilot owner, one real operating decision, consent to use a safe copy of their data where needed, and a readiness report. | Do not enable the feature if the source facts or ownership are absent. Show setup/readiness instead. |
| 1. Discover | Five structured sessions across the target role(s), a current-state workflow, baseline measure, and a clickable/walkthrough prototype for the decision moment. | Build only the smallest workflow that changes the observed decision or removes a repeated chase. |
| 2. Instrument and dark-launch | Feature flag, audit events, performance dashboard, support runbook, and a reversible migration/disable path. Background calculation/rules may be observed without user-visible action first. | Enable for internal/disposable data and verify result correctness, latency and no cross-tenant leakage. |
| 3. Pilot | Two to five opted-in organisations, onboarding checklist, weekly review of correctness/noise and a clear escalation owner. | Expand only when the activation journey works, users trust the results, and no critical data/audit/performance issue remains open. |
| 4. General availability | In-product readiness guidance, help content, support playbook, metric dictionary where applicable, and release notes with limitations. | Default-on only for tenants whose prerequisites are met; otherwise retain an explicit opt-in/setup state. |

Use a per-release scorecard rather than choosing success after results are visible. Baseline
measures are captured in Stage 1; target thresholds are set with pilot customers before
Stage 3 because current evidence does not justify invented universal numbers.

| Release | Activation event | 30-day customer outcome | Expansion guardrail |
| --- | --- | --- | --- |
| A. Resolution | A pilot owner takes a real case through its next action. | Critical work has an owner/due date and verified resolution time is improving against baseline. | Do not expand if sources create duplicates or operators bypass the lifecycle. |
| B. Planning | A pilot publishes one dated, mapped demand scenario. | A material shortfall is found early enough to change a production/material decision. | Do not expand if mapping/data coverage makes projections routinely misleading. |
| C. Automation | A pilot enables one template and reviews its first actions. | The template removes a repeated chase with an acceptable false-positive/noise rate. | Do not expand if a retry can duplicate work or operators disable rules for noise. |
| D. Cockpit | A decision-maker drills from one dashboard signal to its source. | The weekly review reaches a material decision faster than the baseline process. | Do not expand if users treat unavailable data as healthy or cannot explain a metric. |

## A. Exception-to-resolution workflow

### Customer promise

"Every meaningful risk has an owner, a next step, a due date, linked evidence and a
verifiable resolution. Nothing critical disappears because a banner was dismissed."

### MVP scope

Introduce a tenant-scoped **Operational case** as a durable coordination record, separate
from a transient system finding and separate from a CRM task.

Case states:

```text
open → acknowledged → in_progress → resolved → verified
                         ↘ dismissed (requires reason and permission)
```

The MVP supports manual creation and creation from:

- a Core system finding (expired stock, untracked item, output date, stalled execution);
- a Compliant open/failed record; and
- a CRM task or customer commitment where the consequence is operational.

Required fields: title, severity, source type/key, current status, owner, due date,
created/updated timestamps and immutable source snapshot. Resolution requires a structured
cause category, action taken, outcome and optional evidence/reference links. Verification
is a distinct act so an assignee cannot silently self-certify a critical issue without a
recorded policy decision.

### UX and ownership

- **Dashboard:** one bounded "Needs attention" summary: open/overdue cases by severity,
  plus the most important reason to navigate. It links to the owning workspace or case;
  it is not a case workbench.
- **Core:** `/core/cases` is the cross-operational queue, with assignee, severity, state,
  source and due-date filters. Its detail drawer/page has timeline, linked facts and
  resolution form.
- **Compliant:** evidence/control views show the linked case status and open the case in
  context; they do not duplicate the evidence workflow.
- **CRM:** a task/customer page can show linked cases and create a CRM task from a case
  when customer communication is needed.
- **Mobile:** show severity, owner and next due action before supporting context. Do not
  hide critical work based on the current ADMIN/MEMBER distinction; named role views are a
  later, tenant-configured enhancement.

### Technical delivery slices

1. Add additive `operational_cases`, `operational_case_links`, and append-only
   `operational_case_events` tables. Add indexes for `(org_id, status, due_at)`,
   `(org_id, severity, updated_at DESC)`, and a unique active-source dedupe key. The
   dedupe policy must state its source identity and active-state boundary before migration;
   it must not use an ambiguous title/date heuristic.
2. Add service/repository APIs with tenant isolation, state-transition validation and
   optimistic concurrency. Emit `operational_case.*` through `EventWriter` in the same
   transaction.
3. Build source adapters for Core findings and Compliance records. A source transition can
   update or re-open the active case, but never rewrite its recorded resolution history.
4. Add Core queue/detail UI and targeted LiveSync refresh. List APIs return compact case
   summaries; timeline/evidence loads only when opened.
5. Add Dashboard aggregate and workspace links. Reuse the existing single summary response
   rather than issuing a cases request from the browser.
6. Add CRM linking as a follow-up slice, not as a blocker for the operational MVP.

### Acceptance and value measures

- A user can take an active finding through owner, action, resolution and verification
  without losing the source link or crossing tenant boundaries.
- Repeated evaluation of the same active source does not create duplicate cases.
- A source recurrence re-opens or creates a new case according to explicit policy, with a
  visible audit reason.
- Another user sees a targeted queue/count refresh through LiveSync without a full page
  reload.
- A pilot can complete the first case without an administrator doing hidden setup beyond
  assigning the named owner and due-date policy.
- Track: open critical cases, overdue-case rate, median acknowledge time, median verified
  resolution time, recurrence within 30 days, and cases with no owner.

### Explicit non-goals

No generic project-management product, threaded chat, arbitrary custom fields, or automatic
write-off/disposal. Start with the structured fields needed to run a defensible operation.

## B. Demand, capacity and stock-risk planning

### Customer promise

"Before accepting or committing work, see whether demand can be met with available stock
and production capacity, what will run short, and the earliest action needed to avoid it."

### Product sequence

Planning must be honest about confidence. The first release uses **entered demand plans**
and known operational facts; it does not label sparse invoice history as a forecast.

#### B1 — demand and material feasibility

Add a planning workspace with one published plan per organisation/horizon and versioned
draft scenarios. A planner enters demand lines: mapped product, quantity, requested date,
source (`committed`, `forecast`, `internal`) and confidence. Import/sync from CRM becomes
an opt-in convenience only after mappings and data quality are verified.

The feasibility read model calculates, per product and time bucket:

- on-hand usable quantity, allocated quantity, known inbound/expected output and expiry
  restrictions;
- demand versus supply and the first projected shortfall date;
- required production quantity using editable process/output assumptions; and
- confidence/data-coverage labels, never a fabricated zero or a hidden assumption.

Before calculation, a tenant readiness report must show which required ingredients are
missing or unsuitable: product mapping, comparable units/conversions, stock status,
execution/output assumptions, demand date/quantity, and (for capacity) process profile and
calendar. A partial plan is useful only when its affected lines carry an explicit
`insufficient_data`/`not_configured` state and the specific next setup action. A total is
never silently calculated from unknown inputs.

An at-risk line can create or link an Operational case, preserving the distinction between
a forecast and an actual stock fact.

#### B2 — production capacity and scenarios

Add optional capacity profiles to a process: standard run duration, standard output,
setup/cleanup allowance and a work-centre/capacity group. Add simple capacity calendars
with available hours by week. The planner compares required runs against available hours,
shows the bottleneck and supports draft scenarios (for example, a new customer order or a
late ingredient delivery).

This is deliberately aggregate planning, not a minute-by-minute manufacturing scheduler.

### UX and data contracts

- **Planning workspace:** `/core/planning` opens with a compact horizon summary: demand
  value/units, product lines at risk, next shortfall, required versus available hours and
  plan freshness. Product/time-bucket detail is lazy and cursor-paginated.
- **Core:** inventory and active batches show a small "used by plan"/"at risk" context
  only when a published plan references the record. They do not duplicate planning grids.
- **CRM:** mapped sales lines may show planning coverage, but an unmapped line is clearly
  marked "not yet planned" rather than inferred.
- **Dashboard:** one planning risk/count and a link to Planning; no large forecast table.

New facts need additive models such as `demand_plans`, `demand_plan_versions`,
`demand_plan_lines`, `process_capacity_profiles` and `capacity_calendars`. Store source
references and calculation inputs/version alongside every published result, so a later
inventory change does not make a prior plan unexplainable.

### Technical delivery slices

1. Define units, product-mapping eligibility and planning confidence rules; add a data
   readiness report before enabling a tenant. Publish the calculation contract, including
   allocation precedence, expiry treatment, expected-output eligibility, time-bucket/time
   zone, rounding and how a stale source invalidates a result.
2. Add demand plan/version/line persistence, draft/publish controls and audit events.
3. Build a bounded server-side feasibility projection using inventory, allocations,
   active executions and explicit plan assumptions. Add `EXPLAIN (ANALYZE, BUFFERS)` at
   production-shaped volume before indexes or caching are chosen.
4. Build the Planning workspace and line-level drill-down. Keep calculation summaries
   server-side; never fetch all inventory/execution history into the browser.
5. Add at-risk case hand-off and CRM mapping/context.
6. Add capacity profiles, weekly calendar and scenarios only after material-feasibility
   results are trusted by pilot customers.

### Acceptance and value measures

- An organisation can publish a dated demand scenario without overwriting its prior plan.
- A projected shortage identifies the exact product, period, contributing inputs and
  calculation confidence.
- Changing stock, an active execution, or a published plan invalidates only that
  organisation's relevant planning read model.
- A planner can create a case directly from a shortfall with plan/version provenance.
- Track: planned lines with valid mapping, shortfalls detected before due date, stockouts,
  urgent expedites, plan-to-actual variance, capacity overload weeks and forecast coverage.

### Explicit non-goals

No black-box demand prediction, purchase-order system, procurement optimisation, workforce
rostering or automatic production scheduling in the first two releases.

## C. Configurable automations and alerts

### Customer promise

"The platform watches the agreed guardrails, creates the right work once, and tells the
right person why—without users building fragile scripts."

### MVP scope

Start with tenant-configured, product-owned templates rather than a general no-code engine:

- critical Core finding appears or worsens;
- case becomes overdue or unowned;
- Compliant record becomes open/failed or approaches its due date;
- published planning line crosses its stock/capacity risk threshold; and
- CRM task/customer commitment becomes overdue where it is linked to operational work.

Allowed MVP actions: create/update/dedupe an Operational case, create a linked CRM task,
and send an in-app notification. Email, Slack and webhooks come only after delivery,
consent, retry and audit guarantees are specified.

### Guardrails and architecture

- A rule has a stable template key, enabled state, severity/threshold parameters, owner
  routing, version and audit history. It is not arbitrary user-authored code.
- Event-triggered work is written to a durable, tenant-scoped automation outbox in the
  mutation transaction. A bounded worker/CLI claims and evaluates it after commit, so an
  execution or inventory write is never delayed by dashboard-sized evaluation.
- Scheduled checks use the same evaluator and idempotency keys. A retry cannot produce two
  cases, tasks or notifications.
- Every outcome records trigger event, evaluated inputs, rule version, chosen action and
  recipient. A disabled rule stops future actions without deleting historical evidence.
- Configuration changes require the same tenant-authorised change trail as the action they
  cause: who enabled/changed a rule, its old/new version, effective time and the intended
  dedupe scope. Provide a dry-run/last-evaluated explanation before a rule is enabled.
- LiveSync delivers only the compact changed counts/records to active screens; it does not
  cause each browser to re-evaluate rules.

### Delivery slices

1. Add template catalogue, tenant rule configuration, outbox/run/action-log persistence
   and an operator-safe CLI/worker contract.
2. Implement case overdue/unowned and Core critical-finding templates first; validate
   dedupe, retry and re-open semantics.
3. Add Compliant due/evidence and Planning risk templates behind their feature gates.
4. Add CRM-linked task creation and in-app notification preferences.
5. Add delivery integrations only with explicit delivery receipts, exponential backoff,
   failure visibility and tenant consent.

### Acceptance and value measures

- A threshold crossing creates at most one active case/action for its dedupe scope.
- A rule run is explainable from the UI and auditable without reading logs.
- Rule processing is resilient to a worker retry and cannot mutate inventory, execution,
  invoice or compliance facts directly.
- A tenant can disable a noisy rule immediately, see its pending/recent outcomes, and know
  that disabling it does not close or erase work already created.
- Track: avoided duplicate alerts, actions created automatically, acknowledge time by
  template, notification delivery failures and rules disabled due to noise.

## D. Business-performance cockpit

### Customer promise

"In one glance, know whether the business is on track, what changed, why it changed, and
which workspace owns the next decision."

### Product shape

Dashboard remains a control tower, not an analytics warehouse and not a fourth workbench.
Its initial view has four bounded sections:

1. **Attention:** critical/overdue Operational cases, evidence risk and planning risk,
   grouped by owning workspace.
2. **Delivery and flow:** active/stalled production, completed throughput, yield/wastage
   where measurement coverage exists, and capacity exceptions.
3. **Commercial and cash:** CRM revenue, receivables, task/commitment health and mapped
   demand coverage. Margin is withheld until cost/COGS quality is explicitly sufficient.
4. **Risk and improvement:** compliance state, inventory cover/expiry risk, case-resolution
   trend and the top driver behind each material change.

Every metric carries a definition, comparison period, freshness timestamp, source/workspace
link and availability state (`available`, `insufficient_data`, `not_enabled`). Never show
missing data as a healthy zero.

The initial metric dictionary is intentionally no more than one decision-ready measure per
section plus Attention. Each metric specification names: business question; unit and
formula; eligible statuses; source tables/read model; time zone and comparison window;
freshness service-level objective; data exclusions; destination route; and accountable
workspace. A metric cannot appear on Dashboard until this specification and its
`insufficient_data` behaviour are reviewed with a pilot.

### Explanation before prediction

The first explanation layer is deterministic: compare current and prior aggregates, then
attribute a movement to recorded events, cases, inventory movement, execution status or
CRM fact. Example: "on-time completion fell because three active batches are stalled over
48 hours" links to Core; it does not claim causal certainty beyond the data.

Natural-language or predictive insight is a later enhancement, only after metric lineage,
tenant data controls and user-verifiable source links are in place.

### Technical delivery slices

1. Publish a metric dictionary with owner, definition, source, time zone, eligibility and
   data-quality requirements. Agree a small executive default set with pilot customers.
2. Add tenant-scoped daily/periodic `business_metric_snapshots` and compact current-state
   aggregates. Build from explicit SQL/read models and existing `EntityEventSummary`, not
   a Python walk of events or records.
3. Extend the existing Dashboard summary endpoint with a bounded cockpit section and
   explanation references. Preserve its one-request browser contract and optional-feature
   degradation.
4. Add trend/detail pages only for metrics that earn use; they are lazy routes, not data
   hidden behind an initial Dashboard waterfall.
5. Add tenant-configured metric packs/role views after the current two-role model has a
   clear permission and configuration design.

### Acceptance and value measures

- Dashboard first paint stays one summary request with a documented response-size,
  query-count and p95 budget at production-shaped tenant volume.
- Each non-trivial metric links to its owning data/workspace and declares data availability.
- A user can move from a negative trend to the contributing case, execution, finding or
  CRM record in one navigation.
- A weekly pilot review can explain every displayed material movement from its recorded
  inputs without an engineer reconstructing the result from logs.
- Track: weekly active decision-makers, drill-through rate, time-to-identify a material
  change, percentage of metrics with sufficient data, and customer-reported usefulness of
  the explanation layer.

## Cross-cutting delivery and quality gates

Every implementation MR in this programme must include:

- an additive migration with upgrade/downgrade and tenant-isolation coverage where data
  changes;
- service/repository unit tests for state transitions or calculations;
- API tests for authentication, org isolation, idempotency and optional-feature gating;
- Playwright coverage for the primary operator journey and request-waterfall contract;
- query-count/response-size/performance-budget assertions against production-shaped data;
- EventWriter/LiveSync coverage for cross-user refresh where a user-visible state changes;
- structured audit events with entity IDs, rule/plan/case versions and no sensitive payloads;
- `ruff`, relevant Python/JS tests, `git diff --check`, Semgrep and the MR pipeline.

### Performance, availability and operability contract

The existing Dashboard and Core contracts are product requirements, not implementation
preferences. For each release, establish production-shaped fixtures for a small active
tenant and a long-lived tenant; record baseline query count, p50/p95/p99 latency and
response bytes before adding the feature. Set an explicit budget in the implementation
ADR/MR and fail the relevant API/Playwright regression when it is exceeded. A cache may
only cache tenant-scoped, versioned aggregate data and must have a documented invalidation
event; it is not a substitute for a bounded query shape.

Feature flags default safe and are evaluated server-side for every read and write. A flag
disable must leave prior facts auditable and the rest of the application usable. Any worker
or scheduled evaluator needs: single-run/concurrency protection, idempotency, bounded
batching, retry/dead-letter visibility, health metrics and an operator runbook. No release
may depend on a browser being open to produce a correct outcome.

Instrument feature-use and outcome events with tenant-safe identifiers and no business
values/free text. Reuse the repository's privacy posture: telemetry is for reliability and
product improvement, with masking and customer notice/consent requirements honoured before
production collection. Product analytics must never become a second unbounded operational
data store.

### Decisions deliberately deferred

These are not holes to fill opportunistically within the four releases:

- Customer self-service, external customer portals and tier/package changes.
- Arbitrary workflow builders, scripts, webhooks and email/Slack delivery before the
  underlying action audit and delivery reliability are proven.
- AI-generated recommendations, causal claims, autonomous inventory/production/financial
  changes, or a generic business-intelligence warehouse.
- Tenant-configured role-based dashboard variants until a permission/configuration model
  exists beyond the current ADMIN/MEMBER distinction.
- Industry-specific default thresholds. Begin with visible, editable pilot configuration
  and promote a default only after cross-tenant evidence supports it.

## Discovery checkpoints before each release

Do not substitute internal assumptions for customer evidence. Before starting each release,
run five structured pilot interviews/usability sessions and answer these questions:

| Release | Decision to validate |
| --- | --- |
| A | Which exceptions genuinely need verification, who owns them, and what makes a resolution credible? |
| B | Which demand sources are trusted, which products are correctly mapped, and what planning horizon drives real decisions? |
| C | Which repeated chases are valuable enough to automate, and what alert volume is acceptable? |
| D | Which weekly decisions customers make, which metrics they trust, and what explanation changes their action? |

If a tenant lacks the required data, ship an honest readiness/setup state and an explicit
next data-quality action. Do not conceal the gap with a generic score or forecast.

## First implementation MR after this plan

Start Release A with a narrow vertical slice:

1. Core critical finding → deduplicated Operational case with owner and due date.
2. Core case queue with acknowledge/in-progress/resolved transitions and immutable source
   link/timeline.
3. Dashboard attention count/link from the existing summary response.
4. Tenant isolation, duplicate-source, state-transition, audit-event and cross-browser
   LiveSync regression tests.

This creates the common action object needed by planning, automation and the cockpit while
delivering customer-visible value on its own.
