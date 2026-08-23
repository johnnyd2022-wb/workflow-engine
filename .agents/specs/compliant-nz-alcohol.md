# SPEC: compliant-nz-alcohol
status: reviewed
name: Compliant — NZ Alcohol module
slug: compliant-nz-alcohol
blueprint: app/features/compliant/modules/nz_alcohol/ (module layer); AlcoholProductProfile
model and its `/api/compliant/alcohol-products` routes physically live in the platform's
`models/`/`routes/` files but are conceptually this module's — see Provenance.
url_prefix: none of its own — contributes framework/control data through
`compliant-platform`'s `/api/compliant/*` routes; no dedicated blueprint or route file.

## Description
Install-time industry module for the Compliant product, covering New Zealand alcohol
manufacturers (spirits, beer, cider, mead, RTDs, wine). Owns the framework/control
catalogue (`catalogue.py`: Customs alcohol reconciliation, NP3 food control, Wine
Standards Management Plan, council trade waste) and the council-specific trade-waste
catalogue (`councils.py`: Auckland/Watercare, Wellington City, Christchurch, Hamilton,
Dunedin), and registers a `CoreChecksRunner` check (`module.py`) that surfaces attention
states on the dashboard/banner system. It does not own the platform's generic
enrolment/evidence/audit-pack machinery (`ComplianceProfile`, `ComplianceRecord`,
`ComplianceReport`, the `/api/compliant/*` route handlers) — that belongs to
`compliant-platform` and was reviewed there.

The module deliberately states data-coverage boundaries rather than implying automatic
certification: only Customs production/wastage litres-of-alcohol (LAL) is derived live
from Core inventory movements; every other framework is evidence-led (manual records
against catalogued controls). Numeric trade-waste discharge limits and sampling
frequencies are never asserted generically — they come from the customer's own council
consent, entered by the operator.

## Provenance
ASSUMPTION: reconstructed 2026-08-23 from code — no prior spec existed
(`reviewed: never` in `.agents/feature-index.md`). The index's `## compliant-nz-alcohol`
block already documents the boundary/architecture claims below; ACs here are derived from
reading `app/features/compliant/modules/nz_alcohol/{catalogue,councils,module}.py`, the
NZ-alcohol-specific branches of `app/features/compliant/service.py`
(`evaluate()`/`framework_for_profile()`/`build_audit_pack()`), `AlcoholProductProfile`, the
`compliant_nz_alcohol_001` migration, and `tests/test_compliant_catalog.py`.

ASSUMPTION: this review does not re-derive ACs for `/api/compliant/profile`,
`/api/compliant/records`, `/api/compliant/reports/*`, `compliant_bp.py`'s static route, or
the dashboard page — `.agents/specs/compliant-platform.md` already covers those and its
review (`.agents/reports/compliant-platform/review.md`, 2026-08-22) already patched three
real defects there (broken static route, CSV injection, disabled-profile bug) and
round-tripped `compliant_nz_alcohol_001` clean. Re-auditing them here would be circular
against work a human already accepted. `/api/compliant/alcohol-products` (GET/POST) is
listed under compliant-platform's ACs too but is included here as ACs because its
validation rules (`product_type` enum, ABV range) are module-domain knowledge, not
generic platform CRUD — reviewed defensively, not expecting new findings.

## Users & permissions
No module-specific route-level auth. All access is mediated through `compliant-platform`'s
routes: `@requires_auth` for reads, `@requires_role(UserRole.ADMIN)` for
`POST /api/compliant/alcohol-products`. Tenant scoping: `AlcoholProductProfile` filters by
`org_id` in every `ComplianceService` query (`product_profiles`, `add_product_profile`);
the module's own catalogue/council functions (`catalogue.py`, `councils.py`) are pure,
stateless lookups over static in-memory data with no tenant dimension at all — there is
nothing to isolate there.

## Data model
- `AlcoholProductProfile` (table `compliance_alcohol_product_profiles`, created by
  `compliant_nz_alcohol_001`): `org_id` (FK, CASCADE), `inventory_name` (≤255, unique per
  org), `product_type` (≤40, app-level enum: beer/spirits/wine/cider/mead/rtd/other),
  `abv_percent` (numeric(7,4)), `customs_product_code` (optional), `is_active` (default
  true). Unique constraint `(org_id, inventory_name)`; index `(org_id, product_type)`.

## Acceptance criteria

### Framework catalogue (`catalogue.py`)
- `NZ_ALCOHOL_FRAMEWORKS` defines exactly four frameworks: `customs-alcohol` (applies to
  `"all_alcohol"`), `np3-food-control` (applies to a tuple of beer/spirits/cider/mead/
  rtd/other), `wine-standards` (applies to `("wine",)` only), `trade-waste` (applies to
  the sentinel `"consent_required"`). Each carries `version`, `source_title`, `source_url`
  (non-trade-waste frameworks link a real `https://` government/regulator source) and an
  ordered `controls` tuple of `(control_id, description)` pairs.
- `CONTROL_REQUIREMENTS` declares, per `(framework_slug, control_id)`, which capture
  fields are mandatory (`record_types`, `period`, `evidence`, `due_date`, `fields`,
  `source_refs`); controls absent from the map have no extra requirements beyond the
  route's own generic validation.
- `capture_requirements(framework_slug, control_id, profile_settings)` returns the base
  requirement dict, with `source_refs: True` force-added when
  `profile_settings["require_core_source_refs"]` is truthy, regardless of the base map.
- `framework_applies(applies_to, profile_settings, trade_waste_consent_reference)` is the
  single source of truth for whether a framework is relevant to an org:
  - `"consent_required"` → applies iff a trade-waste consent reference is set OR
    `profile_settings["trade_waste_required"]` is truthy.
  - a tuple of product types → applies iff the org's configured
    `alcohol_product_types` setting is empty/unset (show everything before the operator
    has chosen) OR intersects the framework's tuple.
  - any other value (i.e. `"all_alcohol"`) → always applies.
- `framework_for_profile(framework, profile_settings)` only modifies the `trade-waste`
  framework: it looks up the org's `trade_waste_council` setting in the council catalogue
  and, if found, overlays `version`/`source_title`/`source_url`/`controls` from that
  council's data onto a copy of the base framework. Every other framework, and a
  `trade-waste` profile with no matching/unset council, is returned unchanged (not
  mutated in place).
- `framework_by_slug(slug)` returns `None` for an unknown slug rather than raising.

### Council trade-waste catalogue (`councils.py`)
- `TRADE_WASTE_CATALOGUES` covers exactly five councils (`auckland-watercare`,
  `wellington-city`, `christchurch`, `hamilton`, `dunedin`), each with `name`, `version`,
  `source_title`, a real `https://` `source_url`, and a non-empty `controls` tuple.
  Numeric discharge limits/sampling frequencies are deliberately absent from every
  catalogue entry — they are consent-specific and must never be asserted generically.
- `council_catalogue(slug)` returns the matching dict, or `None` for an unknown or `None`
  slug (never raises on `None`/empty input).

### CoreChecksRunner registration (`module.py`)
- `register_checks(runner)` registers exactly one check, `CHECK_ID = "compliant.nz_alcohol"`,
  and only when `config.compliant_enabled` is true — an org with the flag off gets no
  check registered, consistent with the platform-wide flag gate.
- `run_check(org_id, session)` evaluates the org's frameworks via `ComplianceService` and
  is flagged (`flagged=True`, with a count-bearing message) iff at least one applicable
  framework is in the `"attention"` state; an org with no applicable frameworks (module
  disabled, or profile not enrolled) returns `flagged=False` with an empty `frameworks`
  list rather than erroring.

### Framework applicability end-to-end (`service.py` NZ-alcohol branches)
- `ComplianceService.evaluate()` filters `NZ_ALCOHOL_FRAMEWORKS` through
  `framework_applies()` before building control states — an org whose
  `alcohol_product_types` setting is `["wine"]` never sees `np3-food-control` in its
  overview, and an org with no trade-waste consent and no `trade_waste_required` flag
  never sees `trade-waste`.
- The `trade-waste` framework returned by `evaluate()`/`build_audit_pack()` reflects the
  org's selected council (via `framework_for_profile()`) once `trade_waste_council` is
  set — its `source_url`/`version`/`controls` match that council's catalogue entry, not
  the generic placeholder.
- `build_audit_pack()` rejects (`ValueError`, surfaced as a 400 by the platform route)
  a request for a framework slug that is real but inapplicable to the org's current
  profile settings, checked via `framework_applies()` *before* any database query runs
  (cost-avoidance for a known-inapplicable request).

### Alcohol product profiles (`AlcoholProductProfile` + platform routes, domain rules only)
- `POST /api/compliant/alcohol-products` (ADMIN only) accepts `product_type` only from
  the fixed set `{beer, spirits, wine, cider, mead, rtd, other}` (400 otherwise);
  `abv_percent` must be a number strictly greater than 0 and at most 100 (400 otherwise);
  `inventory_name` required, ≤255 chars, unique per org (409 on duplicate via unique
  constraint, not 500).
- `GET /api/compliant/alcohol-products` returns every profile for the caller's org
  (auth-only), never another org's.

## Out of scope for this review
- `/api/compliant/profile`, `/api/compliant/records`, `/api/compliant/reports/*`,
  `compliant_bp.py`'s static route, the dashboard page, and CSV export — covered by
  `.agents/specs/compliant-platform.md` and its 2026-08-22 review.
- Splitting `service.py`'s direct import of NZ-alcohol catalogue functions into a true
  plugin boundary — documented, deliberate debt in the feature index
  ("current module evaluator; to split when a second module lands"), not a defect.
- Any second industry module — none exists yet; `platform/registry.py`'s composition
  seam is exercised only by this one module today.
