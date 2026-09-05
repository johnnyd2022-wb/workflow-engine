# Customer-value programme delivery slices

status: planned; A1 specification in progress
source: [Customer-value execution plan, 5 September 2026](../../docs/customer-value-execution-plan-2026-09-05.md)
registry: [Feature index](../feature-index.md#customer-value-programme--planned-slices)

This is the delivery ledger for all four features in the source plan. Item 1 means
Release A (exception-to-resolution), not just its first database migration. The current
work order produces its working spec; it does not mark any implementation complete.

| ID | Owner | Deliverable and exit condition | Dependency / status |
|---|---|---|---|
| A1 | operational-cases | First vertical slice: critical Core finding → owned, dated case → resolution/verification; queue/detail, Notifications entry, Dashboard count, audit and LiveSync. Includes additive models, tenant isolation, dedupe and concurrency. [Working spec](../specs/operational_cases.md). | **Specification in progress**; pilot/discovery decisions recorded in spec |
| A2 | operational-cases + compliance-checks | Extend adapters from A1's untracked-stock source to expired inputs, output expiry/ready dates; define stable item identities and per-item severity before enabling each. Stalled execution needs an explicit detector contract. | After A1; planned |
| A3 | operational-cases + compliant-platform | Manual cases and Compliant open/failed records, immutable evidence links and source transitions/recurrence; independently feature-gated. | After A1; planned |
| A4 | operational-cases + crm | Link customer commitments/tasks; create a CRM task from a case when communication is needed, with idempotency and provenance. | Follow-up, not A1 blocker; planned |
| B1.1 | planning | Readiness report and calculation contract: product eligibility, units, allocation precedence, expiry, expected outputs, buckets/time zone, rounding, freshness, confidence, missing-data actions. | Existing Core sources; planned |
| B1.2 | planning | Demand plans, versioned draft scenarios and lines; one published plan per org/horizon, audit history and prior results retained. | B1.1; planned |
| B1.3 | planning | Bounded material feasibility projection with stored input/version provenance; first shortfall, production requirement, explicit insufficient-data states. Production-shaped EXPLAIN before selecting indexes/caches. | B1.2; planned |
| B1.4 | planning + shell | `/core/planning` compact horizon summary and lazy paginated product/bucket detail; Core published-plan context. | B1.3; planned |
| B1.5 | planning + operational-cases + crm | Shortfall-to-case hand-off, opt-in CRM demand mapping and coverage context; projected risks remain distinct from stock facts. | B1.4 + A1; planned |
| B2 | planning + process-design | Process capacity profiles, weekly work-centre calendars, required runs/hours, bottlenecks and draft scenarios. | Trusted B1 pilot results; planned |
| C1 | automations | Template catalogue, tenant/versioned rules, transactional outbox, run/action logs, dry-run explanations, bounded worker/CLI and recovery runbook. | A1 + platform events; planned |
| C2 | automations + operational-cases | Case overdue/unowned and Core critical-finding templates; test dedupe/retry/recurrence and disabling pending actions. | C1; planned |
| C3 | automations + compliant-platform + planning | Compliant due/evidence and published planning-risk templates, with independent source gates. | C2 + relevant A3/B1; planned |
| C4 | automations + crm + compliance-checks | Linked CRM task creation and in-app notification preferences, recipients and receipts. | C2 + A4; planned |
| C5 | automations | Optional external delivery only after consent, receipts, retries/backoff, failure visibility and a separate delivery spec. | Deferred beyond in-app MVP |
| D1 | dashboard | Pilot-reviewed metric dictionary: one measure per section plus Attention, question, owner, formula, eligibility, source, time zone, comparison, freshness, availability and destination. | A–C contracts; planned |
| D2 | dashboard | Tenant daily/periodic business_metric_snapshots and compact current aggregates via owning services/SQL read models and EntityEventSummary. | D1; planned |
| D3 | dashboard | Extend existing summary with bounded Attention, delivery/flow, commercial/cash and risk/improvement sections; deterministic explanation references and optional-feature degradation. | D2; planned |
| D4 | dashboard | Lazy trend/detail routes for validated metrics, with one-navigation drill-through to contributing work/source. | D3 pilot use; planned |
| D5 | dashboard + identity | Tenant metric packs/role views only after an explicit permissions/configuration design beyond ADMIN/MEMBER. | Deferred; no invented roles in D3 |

A1 deliberately includes separate verification even though the source plan's final
first-MR checklist stops at resolved: verified closure is part of Release A's customer
promise. Starting with one critical finding adapter keeps that vertical slice bounded.
All adapters and later manual/CRM/Compliant entry points remain allocated above.

Every implementation slice inherits the source plan's discovery, dark-launch, pilot and
GA checkpoints; five discovery sessions per release are still outstanding, not presumed
complete. Each needs tenant-safe telemetry and outcome baselines, additive migration
checks where applicable, auth/org/idempotency tests, Playwright operator journeys,
EventWriter/LiveSync checks, query/bytes/latency budgets, lint/security checks and MR CI.

Flags default off on the server. Disabling preserves history and stops new writes/actions.
Unknown data is never a healthy zero. No slice may silently mutate stock, executions,
invoices or compliance facts; those remain explicit workflows in the owning workspace.
No arbitrary scripts, automatic write-offs, speculative forecasts, hidden COGS assumptions,
external portals or AI causal claims enter these releases.
