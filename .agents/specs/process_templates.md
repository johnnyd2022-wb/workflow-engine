# SPEC: process_templates
status: built
name: Industry Process Templates
slug: process_templates
blueprint: app/features/process_templates/ (plus one small, precedented change to
  existing shared execution-completion code in app/core/backend/backend.py — see the
  `sample_only` architecture decision below; not a new blueprint concern, but real code
  outside app/features/process_templates/ that this feature's AC9 depends on)
url_prefix: /api/core/process-templates, /core/flows/create/template-catalog,
  /core/flows/create/start (chooser; see AC1 — a new route, not the existing
  /core/flows/create)

## Source

Product spec: `docs/industry-process-templates-spec.md` (2026-08-21, "proposed roadmap
feature"). This engineering spec translates that PRD into a buildable, testable slice.
This run is unattended (user asked to "work through this until I have an MR to review,"
walked away) — every open PRD question below is resolved into an `ASSUMPTION:` line
rather than left implicit. These assumptions lead the MR description per
`.agents/autonomy.md`.

## Description

Lets an organisation choose **Start from scratch** or **Start from a template** when
creating a process. A curated, application-owned catalogue of industry-specific process
templates (Distillery, Brewery, Winery/Vineyard) is offered only to organisations with
Compliant enabled and `industry_module = nz_alcohol`, resolved server-side. Selecting a
template copies it into the org as an ordinary draft `Process` (+ `Step`s) via the
existing `ProcessRepository`, which the operator then edits in the existing process
wizard before first use. Templates are a starting point, not a schema change, a
compliance record, or a tenant-editable table.

ASSUMPTION: catalogue exposes the full three-industry MVP (Distillery, Brewery,
Winery/Vineyard) in one build, per the user's explicit choice over a Distillery-only
first slice. Rejected alternative: ship Distillery only, matching the PRD's own rollout
plan step 1 ("validate with Whistlebird's live workflows" before the other two
families) — the user chose the larger scope instead.

## Users & permissions

- roles: any authenticated org member (`@requires_auth` only) may list/preview
  templates and copy one into their org — matches `process-design`'s permission model,
  where process create/edit has no role gate beyond auth (ADMIN is reserved for
  destructive actions, which copying a template is not).
- tenant_scoped: yes. Catalogue *content* is not tenant data (it's an app-owned static
  registry, not a DB table), but which families/templates a request may see is resolved
  from the caller's `org_id` (via its `ComplianceProfile`), and the copy action writes
  only to the caller's org through `ProcessRepository`, which already filters/writes by
  `org_id` on every method.

## Acceptance criteria

### Chooser & scratch path (unchanged blank flow)
- AC1: `GET /core/flows/create/start` renders a two-choice chooser ("Start from
  scratch" / "Start from a template"). This is a **new route**, not a change to the
  existing `GET /core/flows/create` — that route keeps its exact current behaviour
  (unconditional redirect to `process-overview?fresh=1` with the same
  `_flow_state_reset` session reset) unmodified, because several pre-existing
  `test_process_wizard_flow.py` e2e tests (from the `process-design` spec) treat a bare
  `GET /core/flows/create` as a guaranteed pass-through to `process-overview` —
  branching that route on the chooser broke four of them (skip-ahead bounce targets,
  single-step-advance setup, and the route's own entry test). ASSUMPTION (revised
  after that regression was caught by the full suite): the chooser lives at its own
  URL; the two real "Create process" entry points in the UI
  (`app/core/frontend/processes/list.html`'s create card,
  `app/core/frontend/core/core2.html`'s hub card) point at
  `/core/flows/create/start` instead of `/core/flows/create` directly. The chooser's
  "Start from scratch" card links straight to the unmodified `/core/flows/create`.
  `GET /core/flows/create?id=<uuid>` (resuming an existing process) was never touched.

### Catalogue API and capability policy
- AC2: `GET /api/core/process-templates` returns only template families mapped to the
  caller's org's active capability/module pair — for the current mapping, Distillery +
  Brewery + Winery/Vineyard when the org's `ComplianceProfile.enabled` is `true` and
  `industry_module == "nz_alcohol"`; an empty family list otherwise (org keeps Start
  from scratch). Resolution reads `ComplianceProfile` server-side via
  `g.current_org_id`; it never trusts a client-supplied tier, module, or family.
- AC3: `GET /api/core/process-templates/<template_id>` 404s for a template whose family
  is not in the caller's org's permitted set, even though the id is a valid catalogue
  entry for another (unmet) capability/module pair — this is the "can't obtain an
  inapplicable family by manipulating client state or a catalogue URL" requirement,
  tested by requesting a real template id from an org without Compliant enabled.
- AC4: The catalogue registry declares each template's `required_capability` and
  `industry_modules` as data separate from its process/step definition (a plain
  dict/dataclass field, not an `if nz_alcohol` branch in the route or service layer).
  Adding a second module (e.g. a hypothetical `food_manufacturing`) to the mapping table
  requires no change to the list/detail/copy route handlers — proven by a unit test
  that registers a synthetic second-module template and asserts the existing routes
  serve it with zero code changes beyond registry data.

### Preview and copy
- AC5: Each list-response entry carries family, template id/name/description, its
  single-step default traceability shape ("X → Y" per the PRD tables), step count,
  default units, and a fixed "customise before using" advisory string. Filtering by
  `family` (query param) narrows the list; an unknown family value returns an empty
  list, not 400 (the UI's filter is a convenience, not a validated enum boundary).
- AC6: `POST /api/core/process-templates/<template_id>/copy` 404s under the same rule
  as AC3, otherwise creates one org-owned draft `Process` (`is_draft=True`) plus its
  step(s) through `ProcessRepository.create_process` / `add_step` — reusing that
  repository's existing versioning (`ProcessVersion` insert) and eventing
  (`process.created`, `process.step_added`) rather than a bespoke write path — and
  returns `{"process_id": ...}`. The copied process's `description` is built as
  `"<template.description>\n\nCreated from: <template name> v<catalogue_version>"`
  when the template defines a description, or, when it doesn't (no catalogue entry in
  this build omits one, but the code path is defined regardless), just
  `"Created from: <template name> v<catalogue_version>"` alone. If the combined string
  would exceed `Process.description`'s 1000-char column, the template's own
  description text is truncated first so the "Created from: ..." provenance suffix is
  never the part that gets cut. The operator's own later edits to `description`
  overwrite this, never the reverse.
- AC7: Saving via AC6 creates only tenant-scoped records under the caller's org; a
  second org's `two_org_two_user`-style request for the resulting `process_id` gets 404
  from the existing `ProcessRepository.get_process_by_id` org filter — no new isolation
  logic needed, but a test proves it holds for template-sourced processes too.
  Editing the copied process afterward (existing `PUT /api/core/processes/<id>`) never
  mutates the catalogue registry (it's static, in-process Python data) or any other
  org's copy.
- AC8: A completed execution run against a copied-template process produces normal
  Core input/output lineage (execution → execution_step → inventory items with source
  references) — proven by running one full execute-and-complete cycle against a copied
  "Receive ingredient lot" template process in the unit suite, asserting the created
  inventory item's `source_execution_step_id` resolves back to it. No template-specific
  execution code exists; this is existing `core_bp` execution behaviour exercised
  end-to-end once to prove templates don't bypass it.
- AC9: The "R&D trial and sampling" Distillery template's (and every other family's
  "QA sample"/trial-style template's) output is created as `WORK_IN_PROGRESS`
  inventory, never `FINAL_PRODUCT`, when an execution against it completes — proven by
  running one execute-and-complete cycle in the unit suite and asserting
  `inventory_item.inventory_type == InventoryType.WORK_IN_PROGRESS.value`. See the
  `sample_only` architecture decision below for the mechanism: this AC is unbuildable
  against existing code without it (spec-critic finding, confirmed against
  `backend.py:2297-2303` / `execution_repo.py:97-110` — inventory type there is decided
  purely by `execution_step.is_terminal_step`, itself purely a function of step
  position; a one-step template's only step is always terminal, so today every
  template's output would always be `FINAL_PRODUCT` with no override available).
- AC10: List and detail API responses (AC2/AC3) include the fixed advisory string
  telling the operator to customise and validate the workflow against their own SOPs
  and obligations (verbatim across every template — this is compliance-adjacent
  language, not per-template copy). The frontend catalogue page (AC12) renders that
  same advisory text — sourced from the detail response, not a second copy of the
  string — in the confirmation step before calling AC6's copy endpoint. ASSUMPTION
  (resolves an AC6/AC10 conflict spec-critic flagged): AC6's `POST .../copy` response
  body stays exactly `{"process_id": ...}` — the advisory is a pre-copy confirmation
  concern (frontend), not a field the copy endpoint itself needs to return.

### Catalogue page and post-copy navigation
- AC12: `GET /core/flows/create/template-catalog` (`@requires_auth`) renders the
  template browser page — family filter, cards from AC2, a preview panel from AC3, and
  a "Use this template" action calling AC6. An org whose AC2 call returns zero families
  still gets a 200 render of this page with an empty/"no templates available for your
  organisation" state, not a 404 — the route itself is not capability-gated, only its
  data is (matches AC2's "empty family list otherwise" contract).
- AC13: On a successful copy (AC6), the frontend navigates the browser to
  `/core/flows/create/summary?id=<process_id>` — resuming the existing wizard's
  `_maybe_enforce_flow_wizard_step`/`_assert_flow_process_access` machinery on the
  newly-created draft, which is what "opens an editable process draft with valid
  ordered steps and outputs" (PRD language) resolves to: reusing the existing wizard
  exactly as `process-design`'s AC10 already supports resuming any org-owned
  `process_id`, not a new template-specific editor.

### Analytics
- AC11: Four events are emitted through the existing `EventWriter`:
  `process_templates.catalog_viewed` (list call), `process_templates.template_selected`
  (detail call), `process_templates.template_copied` (successful copy, payload includes
  `template_id`, `family`, `process_id`). ASSUMPTION: "first execution started" / "first
  execution completed" from the PRD's metrics section are **not** new events emitted by
  this feature — they're derivable from existing `execution.created`/`execution
  completed`-shaped events already in `core_bp` joined to `process_templates.template_copied`
  by `process_id`, which avoids a new per-execution flag on `Process` a template-sourced
  process doesn't otherwise need. If that join proves insufficient in practice, a
  follow-up finding is filed rather than adding schema now.

## Data model

- changes: none. No new tables/columns. Catalogue is an application-owned, versioned
  Python registry (`app/features/process_templates/catalog/registry.py`), not a DB
  table (matches PRD "MVP ships an application-owned, versioned catalogue registry
  rather than a tenant-editable database table"). Provenance is stored in the copied
  `Process.description` (existing `String(1000)` column) — no new field.
- destructive: no.

## Architecture decisions (ASSUMPTION, not in the PRD)

- ASSUMPTION: one catalogue template = one `Process` with exactly **one** `Step`,
  matching each PRD table row's single-hop traceability shape ("X → Y"). Templates
  compose into multi-stage workflows the way the PRD describes ("a downstream template
  can select that output as an input") — by an operator running several
  template-sourced processes and chaining their executions through ordinary inventory
  selection — not by the copy action assembling one multi-step `Process` per row.
  Rejected alternative: model each industry family as a single multi-step `Process`
  (e.g. one 8-step "Distillery" process) — rejected because it doesn't match the PRD's
  per-row traceability table and would force an operator into one rigid step order.
- ASSUMPTION: blueprint is registered unconditionally alongside `core_bp` (no new
  `*_enabled` config flag, unlike `crm`/`compliant`). Rationale: exposure is already
  gated per-org, per-request by `ComplianceProfile` (AC2/AC3) — a static config flag
  would be a second, redundant gate and CLAUDE.md already classifies process-adjacent
  functionality as `core_bp`'s "always active" territory.
- ASSUMPTION: Brewery and Winery/Vineyard templates' execution prompts and default
  units are authored at the same level of detail as the PRD's fully-specified
  Distillery table, by domain analogy (malt/hops/yeast lots in kg; wort/beer/must/wine
  in L; batch/lot/vintage identifiers as text prompts) since the PRD only names those
  two families' steps and traceability shape, not their prompts/units. The PRD's own
  rollout plan calls for pilot review of these two families before wider release —
  unaffected by this build, which only needs them to be *structurally* valid and
  editable, not domain-perfect on day one.
- ASSUMPTION (resolves a spec-critic finding): AC9's non-saleable R&D/sample output
  requires a small, real behaviour change in `core_bp`'s step-completion output-typing
  code (`backend.py`, near line 2297, where `inventory_type` is currently decided
  solely by `execution_step.is_terminal_step`). Add: when the matching static output
  definition (`od`, already looked up there by name for `custom_expiry` — same
  precedent) carries `extra_data.sample_only == true`, force
  `inventory_type = InventoryType.WORK_IN_PROGRESS.value` regardless of
  `is_terminal_step`. This is new business logic on an existing JSONB `extra_data`
  field (`Step.outputs[].extra_data`, exactly how `custom_expiry`/`ready_date` already
  work per `compliance-checks`), not a data-model or schema change — the "Data model:
  none" claim above still holds. The R&D/trial/QA-sample templates across all three
  families set `sample_only: true` on their output; every other template omits it and
  keeps today's terminal-step-based classification unchanged. Rejected alternative:
  make R&D a multi-step template so its useful output is structurally non-terminal —
  rejected because the process's own last step would still emit `FINAL_PRODUCT` under
  existing code, so it doesn't actually solve the problem, it just relocates it.
- ASSUMPTION: the "customise before using" advisory (AC10) is a single fixed string
  constant, not per-family/per-template copy — PRD requires the statement to exist on
  every card, not that it be bespoke per card.

## External surfaces

- none. No third-party APIs, webhooks, uploads, or background jobs. Pure internal
  catalogue read + existing-repository write.

## Out of scope

- Claiming templates satisfy NZ Food Control Plan, Customs, Council, wine, or other
  regulatory obligations (advisory copy only, per AC10).
- Auto-creating inventory, executions, product mappings, compliance records, or Xero
  mappings on template selection.
- A marketplace, customer-shared templates, template billing, or tenant-editable
  catalogue entries (registry is code-owned, versioned in this repo).
- Industry-specific calculations beyond existing Core/Compliant capabilities.
- A capability/module mapping UI for a second industry module — AC4 proves the seam
  exists in code; wiring an actual second module is a future feature.
- Search beyond the `family` filter (AC5) — no free-text search in this slice.
