# Industry process templates — product specification

- **Status:** proposed roadmap feature
- **Date:** 2026-08-21
- **Audience:** New Zealand distilleries, breweries, wineries and vineyards

## Problem

Creating a process graph from a blank page is powerful but asks a new operator to understand
Biz-E's process, step, input, output, unit and traceability concepts before they receive value.
The Whistlebird migration showed recurring operational shapes: receive materials, create an
intermediate, transform or blend it, package it, sample it, and trace it to a finished batch.

This is especially costly for a small producer onboarding under time pressure for a Council,
Customs or customer audit. They need a credible starting workflow that they can make their own,
not a generic blank canvas or a rigid mandated SOP.

## Goal

Let an organisation choose **Start from scratch** or **Start from a template** when creating its
first process. A selected template becomes a normal organisation-owned Biz-E process which the
operator can edit before using it.

Success means a new producer can create a first traceable production workflow without needing to
design its process graph from zero, while every organisation remains responsible for its actual
SOPs and regulatory obligations.

## Product principles

- Templates accelerate setup; they are not legal, food-safety, Customs, or Council advice.
- Selecting a template copies it into the tenant. Later edits never affect the catalogue or another
  organisation.
- A copied template uses the existing Core process, step, input, output and prompt model. It is a
  starting configuration, not a new workflow schema.
- Inputs and outputs must support normal batch lineage. Avoid templates that merely collect notes.
- Industry language should be familiar, but labels, units and prompts must all be editable.
- Template provenance is visible: catalogue name, version and source industry are retained in the
  copied process description or existing metadata/event payload where available.

## Entry experience

From **Core → Processes → Create process**, show two equal choices:

1. **Start from scratch** — opens the current blank process wizard unchanged.
2. **Start from a template** — opens a searchable catalogue.

The catalogue is capability-driven rather than hard-coded to alcohol. It first resolves the
organisation's enabled product tier/capabilities and its selected Compliant industry module. For
an organisation with Compliant access and `nz_alcohol` selected, the default catalogue presents
the Distillery, Brewery and Winery/Vineyard families below. Each card shows its purpose, typical
inputs/outputs, default units, number of steps, and an explicit “customise before using”
statement. Selecting a card opens the existing process wizard prefilled with editable steps,
outputs and prompts. The final confirmation creates an ordinary tenant-owned process; it never
runs a batch automatically.

Organisations without that capability/module retain Start from scratch and see only any template
families their capabilities permit. The UI may offer a neutral “All available templates” filter,
but it must never expose an industry-specific catalogue merely because a user knows its URL.

## Initial catalogue

### Distillery

| Template | Default traceability shape | Default prompts / units |
| --- | --- | --- |
| Receive ingredient lot | Supplier → raw material lot | supplier, supplier batch, expiry; g or kg |
| Receive neutral spirit | Supplier → spirit lot | supplier batch, ABV; L |
| Flavour or botanical preparation | ingredient/spirit lots → flavour intermediate | trial/batch ID, measured volume, ABV; mL or L |
| Distillation run | spirit/flavour inputs → distillate | run ID, input/output ABV, yield; L |
| Blend or vat | intermediates → vat batch | vat ID, ABV, volume; L |
| Bottling run | vat batch + packaging → finished bottle batch | bottle batch, size, ABV, bottles produced; units |
| R&D trial and sampling | selected inputs → trial intermediate / sample record | experiment ID, hypothesis, measured result; mL, units |
| Controlled-area stock transfer | finished batch → storage/transfer record | source/destination, reference, quantity; units or L |

### Brewery

| Template | Default traceability shape |
| --- | --- |
| Receive malt, hops, yeast or adjunct lot | supplier → raw material lot |
| Brew day | raw lots → wort batch |
| Fermentation | wort + yeast → beer batch |
| Conditioning / blending | beer batches → conditioned batch |
| Packaging run | conditioned batch + packaging → finished pack batch |
| QA sample / trial | selected batch → sample record |

### Winery / vineyard

| Template | Default traceability shape |
| --- | --- |
| Grape intake | vineyard/block or supplier → grape lot |
| Crush and press | grape lot → juice/must batch |
| Fermentation | must + additions → wine batch |
| Racking, blending or stabilisation | wine batches → cellar batch |
| Bottling run | cellar batch + packaging → finished wine batch |
| Vineyard/block trial or QA sample | selected lot → sample record |

The first catalogue deliberately focuses on traceability and production. Compliance evidence,
customs declarations, cleaning records and staff competency remain captured in their dedicated
modules; a template can link to those workflows but must not imply completion of a control.

## Behaviour and data model

### Capability and industry-module resolution

Template discovery is a policy decision made server-side before cards are returned to the UI. The
MVP policy is:

1. Resolve the organisation's active product entitlement/capability for Compliant.
2. Resolve its enabled `ComplianceProfile` and selected `industry_module`.
3. Return only catalogue families mapped to that capability/module pair.

For the current alcohol module this mapping is:

| Required capability | Compliant industry module | Template families exposed |
| --- | --- | --- |
| Compliant | `nz_alcohol` | Distillery, Brewery, Winery/Vineyard |

The catalogue registry must declare its applicability separately from its process definition, for
example `required_capability: compliant` and `industry_modules: [nz_alcohol]`. Core receives a
generic list of permitted cards; it must not contain `if nz_alcohol` presentation logic. Future
modules (for example food manufacturing or supplements) add a capability/module-to-family mapping
and their own cards through the same policy boundary.

If billing/entitlement infrastructure does not yet expose a formal Compliant tier, MVP may use the
existing enabled Compliant feature/profile as the temporary server-side capability signal. This is
an explicit bridge, not a reason to trust a client-provided tier or industry selection.

### Template source

The MVP ships an application-owned, versioned catalogue registry rather than a tenant-editable
database table. Each entry defines only fields already supported by Core:

- process name, description and category;
- ordered steps;
- declared input/output labels and units;
- execution prompts and sensible defaults.

This avoids a new schema while allowing the catalogue to evolve in code. The selection action
copies the definition through the existing `ProcessRepository`, creating an ordinary `process`,
`step`, process version and events in the selected organisation.

### Tenant ownership and versioning

- Copied processes start as drafts so the operator reviews them before the first execution.
- The copied process is independent from its source template.
- Existing process-version behaviour records all later changes.
- The system displays “Created from: <template name> v<version>” where existing process
  description/event support permits. It must not overwrite a customer’s later process name.

### Execution behaviour

Templates only preconfigure a process; normal execution creates the real traceability:

1. Operator starts a batch from the copied process.
2. Operator selects the actual input lots, records measured outputs and completes prompts.
3. Biz-E creates WIP or final inventory with source execution/step/output references.
4. A downstream template can select that output as an input, preserving the ordinary Core lineage.

For R&D, use WIP/sample outputs by default. A trial becomes saleable only when an operator runs a
separate packaging/final-product workflow; this prevents tests being presented as commercial stock.

## MVP scope

### In

- Start-from-scratch versus start-from-template chooser in the process creation flow.
- Read-only curated catalogue for the three initial industries.
- Search/filter by industry and process type.
- Preview and editable prefilled wizard.
- Tenant-owned draft process created using existing Core tables and repositories.
- Catalogue unit tests for valid step positions, output IDs, units and tenant isolation.
- Analytics/events for catalogue viewed, template selected, template copied, first execution
  started and first execution completed.

### Out

- Claiming templates satisfy NZ Food Control Plan, Customs, Council, wine, or other obligations.
- Auto-creating inventory, executions, product mappings, compliance records or Xero mappings on
  selection.
- A marketplace, customer-shared templates, template billing, or tenant-editable catalogue entries.
- Industry-specific calculations beyond existing Core and Compliant capabilities.

## Acceptance criteria

- [ ] A user can choose Start from scratch and receives the unchanged blank process flow.
- [ ] The server returns alcohol template families only when the organisation has Compliant access
  and an enabled `nz_alcohol` industry module.
- [ ] An organisation cannot obtain an inapplicable template family by manipulating client state or
  a catalogue URL.
- [ ] The catalogue can add a new capability/industry-module mapping without changing Core's
  generic template-picker behaviour.
- [ ] A user can filter among the template families available to their organisation and preview each
  relevant template.
- [ ] Selecting a template opens an editable process draft with valid ordered steps and outputs.
- [ ] Saving creates only tenant-scoped existing Core records; no other tenant can read or modify it.
- [ ] Editing a copied process does not alter the catalogue or any other copied process.
- [ ] A completed execution from a copied template creates normal Core input/output lineage.
- [ ] The R&D template defaults to non-saleable WIP/sample output rather than final product.
- [ ] Template cards and confirmation language explicitly tell the operator to customise and validate
  the workflow against their own SOPs and obligations.

## Metrics and discovery

- Template selection rate versus blank creation rate.
- Time from first login to first completed execution.
- Percentage of copied templates edited before first run.
- First-week number of source-linked input/output batches per new tenant.
- Qualitative validation with at least one distillery, brewery and winery/vineyard before expanding
  the catalogue.

## Risks and decisions to validate

| Risk / assumption | Mitigation |
| --- | --- |
| A template may look like prescribed compliance advice. | Strong explanatory copy; use operational language; keep controls/evidence separate. |
| Templates become too generic to help. | Start with small, composable workflows and test them with pilot operators. |
| Templates become too prescriptive or cumbersome. | Keep every field editable and retain Start from scratch as an equal choice. |
| Different producers use different vocabulary and units. | Make labels, units, prompts and steps editable before save. |
| Catalogue code drifts from Core capabilities. | Test every catalogue entry through the existing repository and execution APIs. |
| Industry templates leak across an entitlement or module boundary. | Resolve applicability server-side and test the catalogue policy independently from the UI. |

## Rollout

1. Validate the initial distillery templates with Whistlebird’s live future workflows.
2. Review wording and flows with one brewery and one winery/vineyard pilot.
3. Ship the curated MVP behind the normal Core feature path.
4. Use adoption/edit data and pilot feedback to decide whether a tenant-owned template library is
   warranted.
