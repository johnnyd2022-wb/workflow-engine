# spec-critic: process_templates

Spec: `.agents/specs/process_templates.md` (status: `approved-unattended`)
Source PRD: `docs/industry-process-templates-spec.md`

Grading as written, against the real code at `app/core/db/models/process.py`,
`app/core/db/models/step.py`, `app/core/db/models/execution_step.py`,
`app/core/db/repositories/process_repo.py`, `app/core/db/repositories/execution_repo.py`,
`app/core/backend/backend.py`, `app/features/compliant/models/compliance_profile.py`.

## GAP (high): AC9 is contradicted by the codebase's real WIP/final-product mechanism, given the spec's own single-step-template architecture decision

AC9 requires the "R&D trial and sampling" template's output to default to non-saleable
WIP/sample, "not marked as finished/saleable stock," citing `requires_inventory_selection`
and `extra_data`/label as the mechanism.

Two things are wrong with this, both grounded in real code:

1. `requires_inventory_selection` is an **input**-side field (does the operator have to pick
   a specific inventory lot at execution time). It appears only in step.py's inputs/outputs
   comment and in frontend JS (`flows2-steps.js`, `execution-step-spa.js`,
   `execution-open-step.js`, `create-process-modal.js`, `process-flow-next-steps-steps.js`) —
   there is no server-side reference to it at all (`grep` for it in `backend.py` and every
   repository returns zero hits). It has nothing to do with whether a produced output becomes
   `WORK_IN_PROGRESS` or `FINAL_PRODUCT` inventory.

2. The actual mechanism that decides `InventoryType.WORK_IN_PROGRESS` vs
   `InventoryType.FINAL_PRODUCT` is **`execution_step.is_terminal_step`**
   (`app/core/backend/backend.py:2297-2303`), which is computed in
   `execution_repo.py:97-110` as "is this step the last one by position order **within its
   process**" — pure DAG topology, not any output-level flag or label.

The spec's own **Architecture decisions ASSUMPTION** ("one catalogue template = one `Process`
with exactly **one** `Step`") means every template's single step is, by construction, always
the last step in its process — i.e. always terminal. Given the real terminal-step-detection
code, that means **every** template's output — R&D included — is classified `FINAL_PRODUCT`
on execution completion, with no existing field or label anywhere in the outputs schema that
can override it. AC9 as written cannot pass against the real code; it isn't a vague AC, it's
one whose only described mechanism doesn't exist and whose actual mechanism (terminal-step
position) guarantees the opposite of what the AC demands.

This needs to be resolved as an explicit `ASSUMPTION:`, not built around silently — e.g.:
"the R&D template's output is accepted as `FINAL_PRODUCT`-typed like any other single-step
template, but is distinguished by an `extra_data.sample = true` label plus name/description
copy; AC9 is redefined to assert that label is present and the copy explicitly warns the
output is not automatically saleable" — or, if the product intent must survive literally
(inventory_type actually gated at WIP), that requires a genuine code change to
`is_terminal_step`/output-type derivation that the spec's `Data model: changes: none` and
"no template-specific execution code" claims currently rule out. Either resolution changes
either an AC or the "no execution code changes" architecture claim — the spec can't currently
have both as written.

## GAP (high): AC6's copy response schema contradicts AC10's requirement on the same response

AC6 pins the `POST .../copy` response shape explicitly: `returns {"process_id": ...}`. AC10
requires "the copy confirmation" to also carry the fixed advisory string, alongside list and
detail responses. If "copy confirmation" in AC10 means the same POST response AC6 already
fully specified, the two ACs directly disagree on that response's shape (one says
process_id-only, the other says process_id + advisory). If AC10 instead means the frontend's
own UI confirmation step (sourced from the earlier detail-call response, not the copy
response), that's a legitimate reading, but it's not stated, and a builder/tester has no way
to tell which AC controls the `copy` endpoint's actual JSON contract. Needs one line
resolving whether `POST .../copy`'s response body is `{"process_id": ...}` only (and AC10's
"copy confirmation" is UI-only, backed by the detail call's advisory) or
`{"process_id": ..., "advisory": "..."}`.

## GAP (medium): the "Start from a template" path has no AC — only its API surface is specified

The spec's `url_prefix` names a page route, `/core/flows/create/template-catalog`, and the
Description says selecting a card "opens the existing process wizard prefilled with editable
steps" — but no AC exists for:
- what renders at `/core/flows/create/template-catalog` (page existence, auth, chooser-page
  link target) — AC1 only specifies the *chooser* page and the *scratch* branch's
  destination; the *template* branch's destination is unstated.
- what happens immediately after a successful `POST .../copy` — which wizard page the
  operator lands on (`process-overview`? `summary`, since the process/step/inputs/outputs
  are already populated?), and how that page's URL is constructed (`?id=<process_id>`
  presumably, but never stated).

This matters concretely because `_maybe_enforce_flow_wizard_step`
(`app/core/backend/backend.py:417-450`) gates step navigation off session `flow_state` keyed
by process id, auto-initializing only when `process_id is not None`; a freshly-copied
template process id falls into that auto-init branch, so it likely isn't *broken* — but
nothing in the spec commits to that landing page or asserts it, so an e2e test has no AC to
point at for "and then the operator sees the prefilled wizard." Given the Description makes
this the second half of the feature's core promise, this is a real Description/AC coverage
gap, not a nice-to-have.

## GAP (low): AC6's "fallback text" for a template with no description is never defined

"...unless the template defines no description fallback text is used instead" — this resolves
*that* a fallback exists, not *what* it is, nor how the `"Created from: <name> vY"` prefix and
the template's own description are joined (newline? separator? space?) when a description
*does* exist. Neither is falsifiable as written — a test can't assert against undefined
literal text. Needs either the fallback string and the join format spelled out, or an
explicit `ASSUMPTION:` naming both (e.g. fallback = `"No description provided by template
author."`, joined with `"\n\n"`).

## Assumptions judged reasonable (not gaps)

- **Full three-industry MVP in one build** (top of spec) — explicitly surfaced as an
  override of the PRD's own phased-rollout plan, with the rejected alternative named. This
  is exactly the shape an unattended-run assumption should take; reasonable to build against,
  though it does mean Brewery/Winery templates become selectable by real orgs before the
  PRD's own pilot-review step happens — that tension is the spec's to own, and it does own
  it, so not counted as a new gap here.
- **Blueprint registered unconditionally, no new `*_enabled` flag** — reasoning (per-org gating
  already happens via `ComplianceProfile` at request time; a static flag would be redundant)
  is sound and matches CLAUDE.md's description of `core_bp` as always-active territory.
- **Brewery/Winery prompts/units authored by domain analogy** — reasonable for MVP structural
  validity; explicitly scoped to "structurally valid," not "domain-perfect," consistent with
  the PRD's own pilot-review rollout step.
- **Fixed, non-per-template advisory string** — matches PRD's actual requirement ("must exist
  on every card," not "must be bespoke").

## Other checks performed, no gap found

- **Tenant scoping**: decided and grounded — `ComplianceProfile` resolved via
  `g.current_org_id` server-side (never a client-supplied tier/module/family), copy writes go
  through `ProcessRepository`'s existing `org_id`-filtered methods. AC7 explicitly tests
  cross-org 404 for a template-sourced process. No gap.
- **Destructive data model changes**: none exist. `changes: none` / `destructive: no` is
  accurate — no new tables/columns; catalogue is an in-process Python registry, provenance
  reuses the existing `Process.description` `String(1000)` column (confirmed in
  `process.py`). Consistent with `destructive: no`.
- **External surfaces**: `none` is accurate — no uploads/webhooks/third-party calls; the only
  write path is the existing `ProcessRepository`, the only new read is an in-process registry.
- **AC2/AC3/AC4 (capability gating, registry seam)**: testable and grounded — `EventWriter`
  and `ComplianceProfile` lookups already exist in the codebase (`app/features/compliant/
  service.py`) and require no new governed enum (`EventWriter.emit()` takes a free-form
  `event_type: str`, confirmed in `event_writer.py`), so AC11's four new event names need no
  schema/enum change either.
- **AC1 (chooser)**: testable behavior change — today's `GET /core/flows/create`
  unconditionally 302-redirects to `process-overview` (confirmed in `backend.py:898-917`);
  AC1's "renders a chooser instead" is an explicit, checkable divergence from that, and the
  `?id=` bypass and `fresh=1` scratch path are both pinned precisely enough to test.
- **AC5/Out-of-scope search boundary**: consistent — spec explicitly narrows PRD's "search/
  filter by industry and process type" down to a `family`-only filter and calls the rest out
  of scope, avoiding the untestable "searchable catalogue" language from the PRD.
- **Description/AC coverage otherwise**: every other Description promise (capability-gated
  catalogue, copy-not-mutate-registry, provenance in description, no auto-execution) is
  pinned by an AC.

## Summary

Two high-severity, code-grounded contradictions (AC9 vs. real terminal-step inventory typing
combined with the spec's own single-step-template decision; AC6 vs. AC10's disagreement on
the copy response's own JSON shape), one medium coverage gap (no AC for the template-selection
UI path/landing page, only its API), and one low gap (undefined fallback text/join format).
None of these are nitpicks — AC9 in particular is a specific, testable claim that the current
code makes false as stated, not just underspecified language.
