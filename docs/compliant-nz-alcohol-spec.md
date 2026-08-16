# Compliant / NZ Alcohol — Product and Technical Specification

**Status:** implemented foundation on `feat/compliant`

**Audience:** product, engineering, reviewers, and future agents

**Primary UI:** `/compliant`

**Feature flag:** `compliant_enabled`

## 1. Product intent

Compliant is a subscription-enabled product area that turns the operational evidence a
manufacturer already creates in Core into a clear, regulator-oriented evidence system.
The first module serves New Zealand alcohol manufacturers: distilleries, breweries,
cideries, meaderies, RTD producers, wineries, and vineyards.

The promise is deliberately narrower and more trustworthy than “zero-touch certified
compliance”:

- Show what is applicable to this business, in plain operational language.
- Derive live signals where Core has authoritative data.
- State data gaps rather than treating missing data as a pass.
- Ask for the smallest useful additional proof where automation is not yet possible.
- Reuse an existing Core execution or evidence file instead of creating a parallel
  compliance spreadsheet.
- Produce a tidy, source-linked audit pack for the requested framework and period.

It is **not** legal advice, a regulator filing service, or a claim that an organisation is
legally compliant. The dashboard calls its output “current operational evidence,” not a
legal score, and tells the operator to confirm requirements with the relevant regulator or
adviser.

## 2. Customer outcome and value moments

The intended first-use path is short:

1. An administrator enables Compliant and selects the alcohol types they make.
2. The platform removes irrelevant framework cards; for example, the Wine Standards pack
   is only shown when wine is selected.
3. The operator maps Core inventory names to alcohol type and ABV once.
4. Production and wastage movements immediately produce a live Customs litres-of-alcohol
   (LAL) view, including conspicuous gaps for unmapped items or incompatible units.
5. The action queue focuses on the few actions that unlock evidence or resolve attention
   states, rather than making the user navigate a control library.
6. When a person completes a production step, the normal Core evidence flow can surface an
   optional “Compliance evidence” shelf. It is additive and never blocks production.
7. Existing completed execution steps and uploaded evidence files are offered for reuse on
   the Compliant dashboard.
8. An auditor-facing pack is generated from one framework and optional date range in HTML
   (print/PDF) or CSV.

The emotional value is: “I can keep running production and can see exactly what I need to
prove before an audit, without rebuilding the work I have already done.”

## 3. Scope: NZ alcohol module

### Product applicability

| Product type | Frameworks surfaced |
| --- | --- |
| Spirits | Customs alcohol; National Programme 3 (NP3); trade waste when configured |
| Beer | Customs alcohol; NP3; trade waste when configured |
| Cider, mead, RTD, other alcohol | Customs alcohol; NP3; trade waste when configured |
| Wine / vineyard | Customs alcohol; Wine Standards Management Plan (WSMP); trade waste when configured |

`trade-waste` appears only where the organisation has a consent reference or has explicitly
said trade waste is required. This avoids presenting a council framework as relevant merely
because it exists.

### Framework catalogue

The versioned, source-linked catalogue is in
`app/features/compliant/modules/nz_alcohol/catalogue.py`.

| Framework slug | What the product tracks | Source |
| --- | --- | --- |
| `customs-alcohol` | product/ABV mapping, lodgements, reconciliation, movement proof, retention | [NZ Customs record-keeping obligations](https://www.customs.govt.nz/business/excise/alcohol-and-excise/record-keeping-obligations-for-alcohol-licenced-manufacturing-areas-and-off-site-storage) |
| `np3-food-control` | registration scope, verification, competency, hygiene, trace/recall, corrective actions | [MPI National Programme 3 guidance](https://www.mpi.govt.nz/dmsdocument/21853/direct) |
| `wine-standards` | WSMP registration, risk controls, trace/recall, returns/export proof | [MPI Wine Standards Management Plans](https://www.mpi.govt.nz/food-business/winemaking-standards-requirements-and-testing/wine-standards-management-plans) |
| `trade-waste` | consent, management plan, pre-treatment, monitoring, renewal, incidents | authority-specific catalogue below |

Trade-waste control catalogues live in
`app/features/compliant/modules/nz_alcohol/councils.py` and currently include:

- Auckland / Watercare — [trade-waste agreements](https://www.watercare.co.nz/business/help-and-support/trade-waste/trade-waste-agreements)
- Wellington City — [Trade Waste Bylaw 2016](https://wellington.govt.nz/-/media/your-council/plans-policies-and-bylaws/bylaws/files/trade-waste-bylaw-2016.pdf)
- Christchurch City — [Trade Waste Bylaw 2025](https://ccc.govt.nz/assets/Documents/The-Council/Plans-Strategies-Policies-Bylaws/Bylaws/Trade-Waste-Bylaw-2025.pdf)
- Hamilton City — [trade-waste applications](https://hamilton.govt.nz/property-rates-and-building/water-services/trade-waste-applications/)
- Dunedin City — [trade-waste guidance](https://www.dunedin.govt.nz/services/wastewater/tradewaste)

The catalogue intentionally does **not** hard-code generic numerical discharge limits or
sampling frequencies. Those are consent- and site-specific; showing a made-up universal
limit would create false confidence. The customer’s consent conditions belong in their
profile and evidence records.

## 4. System architecture

```text
Core: processes, executions, execution evidence, inventory movements
                         |
                         | read-only proof and live movement data
                         v
Compliant platform: profile + product profiles + evidence ledger + audit snapshots
                         |
                         | module registry / framework catalogue
                         v
NZ Alcohol: framework applicability, council source versions, control contracts,
            Customs LAL evaluator, Core system check
```

### Ownership boundaries

- **Core remains the operational source of truth.** Compliant does not alter inventory,
  execution status, workflow definitions, or Core evidence files.
- **Compliant owns applicability and compliance context.** It stores the organisation’s
  module settings, ABV/product mapping, manually captured records, and audit-pack
  snapshots.
- **A module owns domain knowledge.** The NZ Alcohol module owns framework identifiers,
  source links/versions, control descriptions, and its evaluator.
- **The platform composes modules.** Core only calls
  `app/features/compliant/platform/registry.py`; it does not know the NZ Alcohol check ID
  or regulatory data shape. A future industry module can register through the same seam.

### Installation and feature gating

- `config.compliant_enabled` controls blueprint registration, sidebar visibility, and
  registration of the NZ Alcohol Core check.
- The app factory conditionally registers `create_compliant_blueprint()`.
- `CoreChecksRunner` calls the platform registry. The module registers
  `compliant.nz_alcohol` only when the feature is enabled.
- The schema migration is `compliant_nz_alcohol_001`.

## 5. Data model

All Compliant tables are tenant-scoped with `org_id`, and have foreign keys to the owning
organisation with cascade deletion.

| Table / model | Purpose |
| --- | --- |
| `compliance_profiles` / `ComplianceProfile` | one profile per organisation: enabled state, industry module, council/consent fields, and explicit settings |
| `compliance_alcohol_product_profiles` / `AlcoholProductProfile` | unique Core inventory-name mapping with product type, ABV, optional Customs code, active state |
| `compliance_records` / `ComplianceRecord` | operational proof: control, record type/status, period/due dates, readings, evidence reference, trusted Core references, details |
| `compliance_reports` / `ComplianceReport` | immutable-at-generation audit-pack payload and SHA-256 checksum metadata |

Profile settings currently include:

- `alcohol_product_types`
- `trade_waste_required`
- `trade_waste_council`
- `require_core_source_refs`
- optional `customs_lal_tolerance`

The settings are explicit configuration, not hidden evaluator behaviour. This lets the UI
show the actual assumption that affects a result.

## 6. Evidence and live evaluation

### 6.1 Live Customs reconciliation

`ComplianceService.customs_reconciliation()` reads tenant-scoped Core
`InventoryMovement` records joined to `InventoryItem` names. For active alcohol product
profiles it calculates:

```text
litres of alcohol = quantity in litres × ABV / 100
net produced LAL = production LAL − wastage LAL
```

It currently supports litre and millilitre-compatible movements and considers production
and wastage. It reports—not suppresses—the following:

- movement count and inventory names with no alcohol/ABV product profile;
- movements in unsupported units;
- the explicit data-coverage boundary on the dashboard.

The reconciliation control moves to attention if data is unmapped/unsupported, or if a
user-recorded declared LAL differs from calculated LAL by more than the configured
tolerance. It is otherwise only one component of Customs proof: lodgements, stock,
sales/dispatches, transfers, and retention evidence remain distinct controls.

### 6.2 Evidence-led controls

Most controls are evidence-led because Core does not yet capture every regulator-specific
event. A `ComplianceRecord` can be an attestation, reading/sample, lodgement, competency,
or incident, with `complete`, `open`, `failed`, or `superseded` status.

The framework catalogue defines capture contracts. Examples:

- Customs lodgements require a lodgement record, period, and evidence reference.
- Customs reconciliation requires a period, evidence reference, and declared LAL.
- NP3 competency requires competency evidence and a review/expiry date.
- trace/recall controls require a trusted Core source reference.
- trade-waste monitoring requires a reading, evidence, measured value, and limit value.

The API validates those contracts server-side. The browser only explains what is needed;
it is not the security boundary.

### 6.3 Trusted Core links

`source_refs` can refer to an execution, execution step, execution evidence file, or
inventory movement. Before saving, Compliant checks that every UUID exists in one of those
Core tables **for the current organisation**. This prevents an organisation from claiming
another tenant’s data as evidence.

Validation is batched per source table, rather than performing a database query per UUID,
so a larger audit record does not introduce an N+1 query pattern.

`evidence_reference` deliberately remains a human-readable external reference (file
location, certificate number, signed record reference). It is useful but does not itself
prove that the referenced item exists.

### 6.4 Evidence states

Each control evaluates as:

- **`compliant`** — a current configuration/evidence record supports the control;
- **`setup`** — the required configuration or proof has not been supplied;
- **`attention`** — a record is open/failed/overdue, a configured limit is breached, or
  live Customs data has a gap or variance.

The dashboard’s “readiness” count is labelled “Current operational evidence, not a legal
compliance score.” This is an important product invariant: never turn these states into a
claim of regulatory certification.

## 7. UX design and interaction model

### Dashboard

`/compliant` is a single focused workspace rather than a generic forms area:

- A hero describes the honest product promise.
- A summary shows frameworks needing attention, frameworks on track, and live-data gaps.
- “Your next best moves” is a capped priority queue. Each action either unlocks Core data
  or closes a named control gap.
- One-minute setup asks only what the business makes and, if relevant, council/consent
  information.
- Framework cards list source-linked controls and offer direct audit-pack generation.
- Product suggestions detected from unprofiled Core movements fill the product-mapping
  form with one click.
- Recent Core evidence and completed execution steps are offered as reusable proof.
- The evidence form changes its guidance to match the selected control’s capture contract.

The primary UX principle is “tell the operator the next meaningful thing, then take them
to the exact form and prefill what Core already knows.”

### Core execution integration

`execution-render-prompts.js` asks `/api/compliant/capture-context` only while rendering
an execution prompt surface. If Compliant is enabled and the step has no normal evidence
prompt, it adds a synthetic `compliant_auto` evidence shelf.

Invariants:

- It uses the existing Core evidence/upload mechanism; it does not invent a separate
  compliance upload path.
- It is optional, non-blocking, and does not mutate the saved process definition.
- A workflow which never enables Compliant behaves as before.
- Existing standard evidence prompts are not duplicated.

### Server-first SPA state

The Core process wizard has been hardened so persisted process pages are rendered from the
API, rather than from `sessionStorage`. Browser storage is used only to recover an
in-progress **unsaved** wizard form across internal wizard pages.

On a normal navigation away from `/core/flows/create/*`, recovery state and the pending
new-step intent are cleared. It never deletes a server-saved process. An initialisation
generation guard stops a stale HTMX/SPA request from applying old data after a newer route
has rendered.

## 8. Audit packs

`POST /api/compliant/reports/<framework_slug>` generates a framework-specific snapshot,
optionally constrained by a period. It stores:

- the selected framework state and source version;
- applicable controls and their evaluated state;
- matching evidence records;
- live Customs reconciliation/coverage where relevant;
- generation metadata and SHA-256 checksum.

The generated report is tenant-scoped and may be retrieved as:

- JSON for inspection/integration;
- a printable HTML pack (which the browser can save as PDF);
- CSV evidence register.

This is evidence assembly, not a submission to Customs, MPI, a council, or an auditor.

## 9. API surface and permissions

| Endpoint | Behaviour | Permission |
| --- | --- | --- |
| `GET /api/compliant/overview` | dashboard data, frameworks, actions, coverage, proof candidates | authenticated user |
| `GET /api/compliant/capture-context` | minimal optional Core execution shelf context | authenticated user |
| `PUT /api/compliant/profile` | create/update enrolment and applicability settings | administrator |
| `GET/POST /api/compliant/alcohol-products` | view/create ABV product mappings | authenticated / administrator |
| `GET/POST /api/compliant/records` | view/create compliance evidence records | authenticated user |
| `POST /api/compliant/reports/<framework>` | generate audit snapshot | authenticated user |
| `GET /api/compliant/reports/<id>` | retrieve own report as JSON/HTML/CSV | authenticated user, tenant-scoped |

All state-changing browser requests send the existing CSRF token. Every direct database
lookup is filtered by `org_id`; tests verify that a report belonging to one organisation is
not available to another.

## 10. Core workflow and execution hardening delivered with this feature

These changes are related to the trustworthiness of evidence captured in normal Core work:

- Process-builder select prompts now collect their permitted choices, and both execution
  surfaces render those choices. Legacy selects without choices degrade to a text input so
  old workflows remain completable.
- `validate_execution_prompts` validates required prompt values and configured select
  membership in the server-side completion path; browser validation alone cannot bypass
  it.
- The execution repository locks the `ExecutionStep` row with `FOR UPDATE` before checking
  status or applying completion/inventory side effects. Two fast requests should not both
  complete the same step.
- The wizard uses server data for saved processes, clears transient recovery state on exit,
  and guards against stale asynchronous initialisation.

## 11. Explicit limits and open work

Reviewers must preserve these boundaries and should not silently “green” around them.

- **Customs scope is partial today.** Live LAL covers Core production and wastage only.
  Sales, receipts, stock, dispatches/transfers, and filed-lodgement ingestion are not yet
  automatically reconciled.
- **Framework catalogues need lifecycle ownership.** Sources are versioned/dated in code,
  but there is not yet a scheduled regulatory-source monitoring workflow.
- **Trade-waste limits are customer consent data.** The product currently captures and
  evaluates entered readings/limits; it does not parse a consent document into rules.
- **Manual evidence is not cryptographically immutable.** The public API has no update or
  delete endpoint, and audit reports snapshot payloads/checksums at generation, but the
  `ComplianceRecord` database table itself has no database-level append-only constraint or
  historical version chain. Do not claim immutable evidence until that is added.
- **External references are not verified.** A text evidence reference can point to a
  certificate or external document but cannot prove it is accessible or unaltered.
- **No regulator filings.** Audit packs are exportable evidence, not electronic lodgements
  or formal determinations.
- **No all-council coverage yet.** The listed council catalogues are a foundation, not a
  nationwide consent rules engine.

## 12. Regression and improvement checklist

Use this checklist for any Compliant, Core execution, or module change.

### Product correctness

- [ ] Selecting product types changes framework applicability as specified in section 3.
- [ ] The displayed council source/version comes from the selected authority catalogue.
- [ ] Missing product mappings or unsupported units show attention/data gaps, never zero
      production or a green reconciliation.
- [ ] A failed, open, overdue, or breached evidence record makes its control attention.
- [ ] The product never labels evidence readiness or a framework state as legal
      certification/compliance.

### Evidence integrity and tenancy

- [ ] All Compliant reads/writes include the organisation scope.
- [ ] Source UUIDs are accepted only if they resolve inside the current organisation.
- [ ] Capture-contract validation remains enforced by the API.
- [ ] Audit reports can only be read by their owning organisation.
- [ ] New bulk evidence flows avoid per-record/per-reference database queries.

### UX and Core integration

- [ ] One enabled organisation can reach a useful live LAL result by setting product type
      and mapping an existing Core inventory name/ABV.
- [ ] A Core execution with Compliant enabled shows at most one optional evidence shelf and
      still completes without that evidence.
- [ ] A normal Core evidence prompt is never duplicated.
- [ ] Saved workflow pages reflect fresh API data, not an old browser-storage overlay.
- [ ] Leaving the unsaved process wizard removes its local recovery state; leaving a saved
      process must not delete it.
- [ ] Completion remains correct when two browser tabs submit the same execution step.

### Test anchors

- `tests/test_compliant_catalog.py` — catalogue, applicability, LAL calculation, module
  registration.
- `tests/test_compliant_routes.py` — auth, validation, reports, organisation isolation.
- `tests/test_compliant_frontend_assets.py` — one complete, non-nested onboarding form and
  the visible no-certification boundary.
- `tests/test_execution_prompt_rules.py` — server-side prompt validation.
- `tests/test_executions.py` — execution prompt integration and completion behaviour.
- `tests/test_execution_modal_frontend_assets.py` — builder/renderer and additive evidence
  shelf contracts.

## 13. Recommended next investments

1. **Complete the Customs data spine.** Introduce clearly mapped Core/integration feeds for
   receipts, sales/dispatch, stocktake, transfers and filed lodgements, then reconcile them
   by period against production/wastage. Keep unmapped data visible until it is connected.
2. **Make evidence truly tamper-evident.** Add append-only record revisions, actor/time
   audit events, immutable file/version hashes, and a report manifest that contains those
   hashes. This is the highest trust improvement for serious audits.
3. **Make consent onboarding nearly zero-touch.** Add a consent/document ingestion flow
   that extracts proposed monitoring limits, dates, equipment, and renewal terms for a
   human to confirm before they become active controls. Never activate machine-extracted
   limits without explicit approval.
4. **Operationalise regulatory maintenance.** Assign ownership and a reviewed-at date to
   each framework/council source, with a scheduled source-change review and visible
   “catalogue needs review” state.
5. **Progressive training.** Tie competency requirements to staff roles and production
   tasks, surface only the next training need, and attach completion proof to the relevant
   NP3/WSMP control.

## 14. Code map

| Area | Primary code |
| --- | --- |
| Feature composition and routes | `app/features/compliant/compliant_bp.py`, `routes/` |
| Evaluation, data coverage, audit packs | `app/features/compliant/service.py` |
| NZ Alcohol frameworks/contracts | `modules/nz_alcohol/catalogue.py` |
| Council catalogues | `modules/nz_alcohol/councils.py` |
| Pluggable module registration | `platform/registry.py`, `modules/nz_alcohol/module.py` |
| Persistence | `models/`, `app/core/db/migrations/versions/compliant_nz_alcohol_001.py` |
| Compliant dashboard | `frontend/templates/compliant/dashboard.html`, `frontend/static/compliant.js` |
| Core evidence shelf | `app/core/frontend/js/core-api.js`, `execution-render-prompts.js` |
| Core execution/wizard reliability | `app/core/domain/execution_prompt_rules.py`, `execution_repo.py`, `create-process-modal.js` |

This document is an implementation-facing contract. If code and this document diverge,
either update the implementation, or update the document in the same change with an
explicit explanation of the product/trust impact.
