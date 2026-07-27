# Feature Slicing Plan — proposal for review

**Status:** taxonomy agreed 2026-07-27, carve not started. Index is the active deliverable.
**Purpose:** define the slice taxonomy so (a) future Claude sessions can scope work to one
slice instead of "core", and (b) the eventual physical split has a target to move toward.

Two deliverables come out of this once agreed:

1. `.agents/feature-index.md` — the cached index sessions read to scope work. Can land
   **immediately**, describing today's code where it actually lives.
2. The physical carve — blueprints, directories, frontend. Incremental, over many MRs.

The index is the valuable half and does not depend on the carve. Write it first.

## Decisions (Johnny, 2026-07-27)

| # | Decision |
|---|---|
| 1 | **14 slices + platform is fine.** Better than status quo; merge later if it proves granular. |
| 2 | **`/workflow-engine/*` is legacy, not a target.** Go off what the code points to (see §1) — it's the app's former URL prefix, superseded by `/core/*`. Retire it; don't wire traceability to it. Don't break live links. |
| 3 | **`/core` is a subscription tier, not an architecture layer.** It's customer-facing: all core-tier features live under `/core` in the URL, and those URLs stay. But `app/core/` *as a directory name* means "shared kernel" internally, which is a different thing — rename that to `app/platform/`. Internal clarity, no URL change. |
| 4 | **identity stays at `app/api/routes/`.** It's platform-level foundations, not a feature in the traditional sense. Index it as a slice; don't move the files. |
| 5 | **Index first.** |

### Consequence of #3: two orthogonal axes

Decision 3 means "tier" was overloaded in the first draft. There are two independent axes and
the index must carry both:

- **Subscription tier** — what the customer buys. A *commercial* fact. Three tiers, below.
- **Architecture layer** — `platform` / `domain` / `derived` / `integration` / `shell`. Drives
  import direction and review scope. An *engineering* fact.

They don't line up: dashboard is `core` tier but `derived` layer; identity is `core` tier but
`platform` layer. Below, "Tier N" headings from the first draft now read as **layers**.

### The three subscription tiers

| Tier | Status | What it is |
|---|---|---|
| **core** | built — **everything in this repo today** | Production control: processes, executions, inventory, traceability, CRM, dashboard. All of it. |
| **compliant** | not built | Sits on top of core. Industry-specific compliance modules that capture everything needed for *live* compliance, and automate compliance and audit requirements. **Vanta for physical manufacturing.** |
| **enterprise** | not built | Core + compliant, plus multi-site, plus customer-facing logins — contract manufacturers' customers log in for live status and data about their own products. |

**Everything currently in the codebase is core tier, including CRM.** `crm_enabled` is a
feature toggle, not a tier gate — the first draft read it as a paid add-on boundary, which
it isn't.

### What the unbuilt tiers mean for how we slice now

This is the part that changes engineering decisions today, so it belongs in the plan rather
than a roadmap doc:

**compliant → the check registry is the seam.** `CoreChecksRunner.register_check`
(`corechecks.py:81`) already registers checks by id into a runner rather than hard-wiring
routes. That is exactly the shape industry-specific compliance modules need. The
compliance-checks slice (#7) is therefore not just a slice — it's the **extension point the
compliant tier plugs into**, and it should be carved with that in mind: a stable check
interface, findings as data, and no assumption that the built-in check set is the whole set.
Getting this boundary right is worth more than the line count suggests.

**enterprise → two schema-wide changes that slicing makes survivable.**

1. *Multi-site* adds a `site_id` dimension beneath `org_id`. Today the tenant rule is one
   `org_id` filter per query (conventions §2), repeated inline across every repository.
   Multi-site means revisiting **every** one of those. Spread across 13 slices that's a
   series of scoped, reviewable MRs; concentrated in a 5784-line file it's one unreviewable
   diff. This is the strongest argument yet for doing the carve before the tier work, not
   after.
2. *Customer-facing logins* introduce a **second principal type**. Every `requires_auth` /
   `g.current_user` assumption in the app currently means "a staff user of this org". An
   external customer principal sees a narrow, cross-cutting slice of one org's data — their
   own products' status only. That is an authorisation model change, not a login flow
   change, and it lands squarely on identity + permissions.

Neither is scheduled. But both argue for the same near-term thing: get the boundaries
explicit and the `org_id` filtering out of route handlers and into repositories, because
that is where the `site_id` and principal-type changes will have to be made.

---

## 1. What the code actually looks like today

Measured, not assumed.

| Blueprint | Where | Size |
|---|---|---|
| `auth_bp` | `app/api/routes/auth_routes.py` | 1501 lines |
| `org_bp` | `app/api/routes/org_routes.py` | 265 lines |
| `core_bp` | `app/core/backend/backend.py` | **5784 lines** + 5 attached route modules |
| `crm` (parent) | `app/features/crm/crm_bp.py` → `crm_api`, `crm_pages`, `crm_oauth` | ~4000 lines, properly split |
| `dilution_calculator` (parent) | `app/features/dilution_calculator/` → `dilution_calculator_api`, `dilution_calculator_pages` | 225 lines, properly split |

`core_bp` already has a partial seam: five modules attach via `register_routes(bp)` rather
than living in `backend.py` — `corechecks`, `inventory_upload_routes`,
`reconciliation_routes`, `evidence/evidence_routes`, `process_docs/process_docs_routes`.
**This is the mechanism the whole carve should use.** It moves code without moving URLs.

### What `/workflow-engine/*` actually is

Pre-existing, not caused by this plan, but it distorts how anyone scopes work:

1. **`workflow_engine_bp` does not exist.** CLAUDE.md describes a `/workflow-engine/*`
   blueprint for lineage tracing. There is no such blueprint anywhere in `app/`.
2. **`workflow_engine_enabled` is a dead flag.** Read at `app/utils/config_loader.py:278`,
   never consulted by any caller. `crm_enabled` is the only flag that actually gates a
   blueprint (`app/api/app_factory.py:102`). `schedule_enabled` and
   `invoice_button_enabled` are also read-but-unused.
3. **No live link points at it.** The compliance nav entry is commented out in Jinja
   (`{# Compliance hidden for now (desktop + mobile). #}`) in both sidebars that carry it.
   Nothing 404s today.

**It is the app's former URL prefix, not a planned feature.** The evidence is
`app/ui/templates/components/sidebar.html` — an unused legacy sidebar whose nav is
`/workflow-engine/flow-engine`, `/workflow-engine/integrations`,
`/workflow-engine/settings`: a one-to-one mirror of today's `/core/*` pages. The app was
served under `/workflow-engine/*` and moved to `/core/*`; the flag and the CLAUDE.md
paragraph are leftovers from that era.

So: **retire the prefix and the flag.** Do not wire traceability to it — traceability keeps
its existing `/api/core/inventory/trace/*` and `/api/core/sourcemap/*` URLs, which are live
and used. The lineage code CLAUDE.md attributes to the phantom blueprint is real
(`temporal_dag_tracer.py` + those routes); it just lives in core, and slice 8 is where it
should end up — under `/core`, which is also correct on the subscription axis.

### Dead frontend files found alongside

- `app/ui/templates/components/sidebar.html` — legacy, nothing includes it.
- `app/ui/shared/sidebar-v2.html` — unreachable: `/ui/shared/<filename>`
  (`app_factory.py:108`) whitelists `.js` and `.css` only, so this `.html` can never be served.
- Live sidebar is `app/ui/templates/shared/sidebar-v2.html`, resolved via the app-level
  `template_folder` (`app_factory.py:47`) from `base_spa.html:67`.

Three files named some variant of "sidebar", one of them real. Worth deleting the other two
during the shell slice (#13) rather than carrying them through the carve.

### Where the 5784 lines of `backend.py` go

| Lines | Block | Proposed slice |
|---:|---|---|
| 603 | helpers, flow-wizard session state, validation | split across slices / platform |
| 439 | page routes (all 24 of them) | split across slices |
| 157 | static file serving (js/css/img/inventory) | shell |
| 494 | processes + steps API | process-design |
| 907 | executions API (`complete_step` alone is 615) | execution |
| 412 | inventory list + read | inventory |
| 453 | wastage record/list + advisory-lock idempotency | wastage |
| 357 | inventory CRUD + adjust | inventory |
| 191 | trace forward/backward | traceability |
| 84 | execution metadata | execution |
| 681 | dashboard summary + action board | dashboard |
| 56 | metrics | dashboard |
| 721 | entity story, activity feed, audit diff humanisation | activity-log |
| 206 | sourcemap objects + trace | traceability |
| 23 | demo DB reset | demo-data |

No single block is over ~900 lines. **The file is big because it's 13 features stacked in
one module, not because any one feature is huge.** That's the case for slicing.

---

## 2. Proposed taxonomy

The organising rule: **a slice owns a user-facing capability end to end** — its routes, its
business logic, its tables, its templates and JS. If two things always change together,
they're one slice. If one can be flag-disabled without breaking the other, they're two.

Tiered, because not all slices are peers — a dashboard that reads six other slices is not
the same kind of thing as inventory.

### Layer 0 — Platform (`app/platform/`, per decision 3)

Everything shared, with a hard rule: **platform never imports a slice.** Import direction
is one-way, which is what makes slices independently reviewable. Owns no routes, with the
one deliberate exception of identity (decision 4).

| Contents | From |
|---|---|
| DB session, `Base`, engine | `app/core/db/` |
| Tenant context, session security, HTTPS middleware | `app/api/middleware/` |
| `requires_auth`, `requires_org_scope`, permissions | `app/core/security/permissions.py` |
| Config loader, secrets | `app/utils/config_loader.py`, `scripts/local_secrets.py` |
| Observability (logging, tracing, metrics) | `app/observability/` |
| `EventWriter`, `emit_event`, `log_action` | `app/core/backend/event_writer.py`, `app/core/utils/` |
| Unit conversion, quantity guards, time, phone | `app/core/utils/`, `app/core/domain/` |
| API helpers, idempotency key model | `app/utils/api_helpers.py` |

Note `EventWriter` is platform (everything writes events) while *reading* those events back
as a story is a slice (activity-log, #10). Writer down, reader up.

Identity sits here too, by decision 4 — indexed as a slice, physically staying at
`app/api/routes/`. It's the most security-sensitive code in the repo and moving it churns
the file every auditor opens first, for no architectural gain: `/auth/*`, `/org/*`,
`auth_service`, `org_manager`, `backup_code_encryption`, 4 repos, models `User`
`Organisation` `TrustedDevice` `TwoFactorBackupCode`.

### Layer 1 — Domain slices (the product)

| # | Slice | Owns | Today |
|---|---|---|---|
| 2 | **process-design** | Designing a process: the create wizard, steps, reordering, versioning, step documents | `backend.py` processes+steps API (494) + wizard pages, `process_docs/` (~800), `process_repo`, `process_step_document_repo`, models `Process` `ProcessVersion` `Step` `ProcessStepDocument`, `create-process-modal.js` (6765!), `process-flow-*.html` |
| 3 | **execution** | Running a process: batches, step completion, DAG traversal, evidence capture | `backend.py` executions API (907) + metadata (84), `dagtraversal.py` (850), `complete_step_payload.py`, `evidence/` (~650), `execution_repo`, `evidence_repo`, models `Execution` `ExecutionStep` `ExecutionEvidence`, ~5000 lines of `execution-*.js` |
| 4 | **inventory** | Stock items, quantities, movements, CSV/barcode intake, adjustments | `backend.py` inventory blocks (769), `inventory_upload_routes.py` (396), `inventory_repo`, models `InventoryItem` `InventoryMovement`, `inventory/*.html`, `inventory-*.js` |
| 15 | **dilution-calculator** | Solve any one of starting/final ABV and volume from the other three, plus water to add | **Already sliced** — `app/features/dilution_calculator/` (225 lines, stateless, no models). Nothing to carve; it and crm are the two worked examples to copy. |

Splits I considered and rejected for now, with the trigger that would change my mind:

- **process-design vs execution** — genuinely separate (design-time vs run-time, different
  tables, different users). Keeping them separate is the single highest-value boundary in
  this plan. Already split above; noting it because `flows2-*.js` currently straddles both.
- **evidence as its own slice** — it has its own storage dir, service, validation and
  routes, so it's tempting. But evidence only ever attaches to an execution step; nothing
  consumes it independently. Sub-module of execution. Revisit if evidence gets attached to
  inventory or processes directly.
- **2FA out of identity** — no. It's one auth flow.

### Layer 2 — Derived slices (read or extend Layer 1)

| # | Slice | Owns | Why separate |
|---|---|---|---|
| 5 | **wastage** | `/api/core/inventory/wastage`, dispose + dispose-confirm pages | Own table, own reason enum, own advisory-lock idempotency (`_pg_advisory_lock_wastage_idempotency`), own compliance meaning. 453 lines + `wastage_repo` + `InventoryWastage`. Cleanly flag-able. |
| 6 | **reconciliation** | `/api/core/inventory/reconcile/*` — matching untracked stock, reconcile via addition/execution | `reconciliation_service.py` is 889 lines, second-largest module in core, plus 2 dedicated JS files. Entirely self-contained already. |
| 7 | **compliance-checks** | `/api/core/system-findings`, expired materials, untracked items, output expiry/ready-date, notifications page, system status | `corechecks.py` + `checks/` (4 files, ~1200) + `system_status.py` + 1453 lines of findings JS. **This is what the dead `/workflow-engine/compliance` nav link should serve.** |
| 8 | **traceability** | `/api/core/inventory/trace/*`, `trace-backward`, `/api/core/sourcemap/*`, lineage | `temporal_dag_tracer.py`, trace routes (191), sourcemap (206), `sourcemap.js` (2128). **This is the "workflow engine" CLAUDE.md describes** — but per decision 2 it keeps its live `/api/core/*` URLs; the `/workflow-engine/*` prefix is legacy and gets retired, not reused. |
| 9 | **activity-log** | `/api/core/entities/*/story`, `/summary`, `/activity` — reading the event stream back as human-readable history | 721 lines of diff/humanisation logic, `audit_repo`, models `EntityEvent` `EntityEventSummary` `AuditLog`. Reader only — the writer stays in platform. |
| 10 | **dashboard** | `/core/dashboard`, `/api/core/dashboard/summary`, `/api/core/metrics` | 737 lines that aggregate across executions, inventory, checks and events. **Composition slice** — must consume other slices' services, never query their tables directly. This constraint is the whole point of naming it. |

### Layer 3 — Integrations

| # | Slice | Notes |
|---|---|---|
| 11 | **crm** | Already correctly sliced. Leave alone. |
| 12 | **xero** | *Candidate* sub-split of crm: `xero_api_client`, `xero_oauth_service`, `xero_sync_service`, `xero_invoice_repo` and 5 more repos ≈ 2100 lines vs `crm_service.py` at 1253. Two different things (customer records vs an external accounting API) sharing a directory. Low priority — CRM isn't painful yet. |

### Layer 4 — Non-product

| # | Slice | Notes |
|---|---|---|
| 13 | **shell** | Landing page, sidebar, `base_spa.html`, nav, session-expired, the four static-serving routes, `/core` hub page, settings + integrations pages. Owns chrome, not domain logic. |
| 14 | **demo-data** | `mock_data.py` (681), `resetdb.py` (378), `/api/core/reset-demo-db`, `mockData.js`. Isolating this means production can hard-disable a route that wipes and reseeds a database — worth doing for that reason alone. |

**Total: 15 slices + platform.** Core stops being one 5784-line feature and becomes nine.
Two slices (crm, dilution-calculator) already have the target layout and need no work.

---

## 3. The frontend problem

Backend slicing is mechanical. Frontend has one real obstacle:

`/core/static/js/<filename>` (`backend.py:1043`) serves from a single flat directory,
`app/core/frontend/js/`, with a filename whitelist and no subdirectories. Same for css, img
and inventory. Every template references assets by bare filename. **The moment JS moves
into `app/features/<slice>/frontend/js/`, every one of those references 404s.**

Options, in order of preference:

1. **Asset registry** — a dict of `filename → owning slice dir`, built at import time by
   scanning registered slices. Serving route stays one route, keeps its traversal guards
   and whitelist, gains a lookup. Templates don't change. ~40 lines. Recommended.
2. **Per-slice static routes** — each blueprint declares `static_folder`. More Flask-native
   but changes every URL in every template, and CSP/cache headers get duplicated.
3. **Build step** — collect assets into one output dir. Introduces a build to a repo that
   deliberately has none. No.

Option 1 also gives the feature index a free, accurate `assets:` list per slice.

Secondary: `create-process-modal.js` at 6765 lines and `sourcemap.js` at 2128 are the two
frontend files that most need internal splitting — but that's a separate job from slicing,
and shouldn't block it.

---

## 4. Suggested sequencing

Each phase is independently shippable and leaves the app working. Phases 1–2 change **no
URLs**, so the e2e suite is the safety net throughout.

**Phase 0 — write the index (do this regardless).** `.agents/feature-index.md` describing
today's reality, including "lives in `backend.py:2601-3012`" style pointers. Immediate value
to every session; zero risk. Fix the three discrepancies in §1 at the same time.

**Phase 1 — move code, keep `core_bp`.** For each slice, create
`app/features/<slug>/routes/` and move its routes there, attaching via the existing
`register_routes(core_bp)` seam. URLs, blueprint names, `url_for` targets and templates all
unchanged — and per decision 3, core-tier slices keep serving `/core/*` and `/api/core/*`
however the directories are arranged. Order by independence — least entangled first:

1. demo-data (23 lines + 2 modules; trivial, proves the pattern)
2. reconciliation (already standalone)
3. wastage (already standalone-ish)
4. compliance-checks (already uses the seam)
5. traceability
6. activity-log
7. dashboard (last of these — it reads all the others, so it validates the boundaries)

Then the Layer 1 slices, which are bigger and more entangled: inventory → process-design →
execution. Identity is exempt (decision 4).

**Phase 2 — real blueprints.** Each slice gets its own `Blueprint`, mounted at its current
URL prefix. `core_bp` shrinks to shell. Still no URL changes.

**Phase 3 — flags and models.** Feature flags per slice where it makes sense (traceability,
compliance-checks, wastage, demo-data). Move models and repos into slice dirs. Models last —
they're the most cross-referenced and the least urgent.

**Phase 4 — frontend.** Asset registry, then move templates/JS/CSS per slice.

**Phase 5 — tests follow.** `tests/` is currently flat (40 files). Once slices are real,
mirror them: `tests/features/<slug>/`. Conventions §6 already flags the flat layout as a
known gap rather than a convention, so this isn't a change of direction.

---

## 5. Proposed index format

`.agents/feature-index.md`, one block per slice. Optimised for a session to read one block
and know what it can touch:

```markdown
## inventory
subscription: core          # commercial axis — drives URL prefix + flag
layer: domain               # architecture axis — drives import direction
flag: none (always on)
routes: /core/inventory/*, /api/core/inventory (GET POST PUT DELETE), /api/core/inventory/<id>/adjust
backend: app/core/backend/backend.py:2601-3012,3489-3845; app/core/backend/inventory_upload_routes.py
models: InventoryItem, InventoryMovement
repos: app/core/db/repositories/inventory_repo.py
frontend: app/core/frontend/inventory/*.html, js/inventory-*.js
tests: tests/test_multi_tenant_api.py, tests/e2e/test_inventory_flow.py
depends on: platform
depended on by: execution, wastage, reconciliation, compliance-checks, dashboard, traceability
invariant: every quantity write passes an InventoryQuantityWriteReason (conventions §5)
```

`depends on` / `depended on by` is what makes it useful for scoping: a session asked to
change inventory can see immediately that six slices will feel it.

**Staleness:** the index is a cache, so it will rot. Two mitigations worth considering —
(a) `repo-conventions` or `skill-smith` gains an index-freshness check, or (b) a script
that verifies every `routes:` entry resolves against the live URL map, the way
`scripts/preflight.py` verifies environment claims. The latter is stronger and probably
cheap. Recommend deciding this before writing the index, not after.

---

## 6. Open items

All five original questions are resolved — see **Decisions** at the top.

Left open, to settle when the relevant phase starts rather than now:

1. **Index staleness check** (§5) — script that validates `routes:` against the live URL
   map, vs. a skill-owned freshness pass. Decide before the index has grown enough to rot.
2. **Retiring `workflow_engine_enabled`** — decision 2 says the flag goes. Removing it
   touches `local.ini`, `test.ini` and `config_loader.py:278`. Trivial, but it's a config
   change to production files, so it wants its own small MR rather than riding along with a
   code move.
3. **Xero sub-split** (slice 12) — deferred until CRM actually hurts.
4. **`app/core/` → `app/platform/` rename mechanics** — decision 3 approves it, but it's a
   large import-churn diff. Best done as its own MR *after* Phase 1 has emptied the
   interesting code out of `app/core/backend/`, so the rename touches less.
