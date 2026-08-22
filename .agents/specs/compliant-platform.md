# SPEC: compliant-platform
status: reviewed
name: Compliant Platform
slug: compliant-platform
blueprint: app/features/compliant/ (platform layer only; excludes app/features/compliant/modules/nz_alcohol/, spec'd separately as compliant-nz-alcohol)
url_prefix: /compliant, /api/compliant

## Description
Reusable, tenant-scoped compliance evidence platform for the Compliant product. Owns
enrolment (`ComplianceProfile`), manual evidence capture (`ComplianceRecord`), immutable
audit-pack snapshots (`ComplianceReport`), and the module composition seam
(`platform/registry.py`) that lets an industry module (today: `compliant-nz-alcohol`)
contribute framework/control catalogues without Core or the platform importing
industry-specific identifiers. Gated behind the `compliant_enabled` feature flag, which
gates the entire blueprint's registration (`app_factory.py:147`) — no individual route
carries its own flag check.

The platform does not certify legal compliance or mutate Core/CRM/inventory data. It reads
Core execution/inventory data to derive live evidence (e.g. Customs litres-of-alcohol
reconciliation) and lets operators attach manual records against a framework's controls.
Enrolled orgs get a non-blocking "Compliance evidence" capture shelf surfaced inside every
Core execution step (`/api/compliant/capture-context`); Core remains system of record for
uploads, Compliant only surfaces that proof for reuse.

## Provenance
ASSUMPTION: reconstructed 2026-08-22 from code — no prior `.agents/specs/compliant-platform.md`
existed; `reviewed: never` in `.agents/feature-index.md`. The index's `## compliant-platform`
block already documents most of the boundary/architecture claims below; ACs here are derived
from reading `app/features/compliant/{compliant_bp.py,routes/,service.py,models/,platform/}`
and `tests/test_compliant_routes.py`.

ASSUMPTION: `AlcoholProductProfile` (table `compliance_alcohol_product_profiles`) and its
`/api/compliant/alcohol-products` routes live physically in the platform's models/routes
files, but conceptually belong to the `compliant-nz-alcohol` module per the feature index.
`service.py` also imports `NZ_ALCOHOL_FRAMEWORKS` and the nz_alcohol catalogue directly in
`evaluate()`/`build_audit_pack()` — the index itself flags this as known, deliberate debt
("current module evaluator; to split when a second module lands"), not something this
review should refactor. ACs below cover these routes/behaviors as they exist today since a
platform review that skips them would leave real, live endpoints unaudited, but any fix that
would require splitting the module boundary is out of scope — flag it, don't do it.

## Users & permissions
Any authenticated org member (`@requires_auth`) may read Compliant data for their org.
`PUT /api/compliant/profile` and `POST /api/compliant/alcohol-products` additionally require
`UserRole.ADMIN` (`@requires_role`). No other route-level role gate. Tenant scoping follows
the codebase-wide convention: `tenant_context` middleware populates `g.org_id` unconditionally
before any route body runs; every query in `service.py` filters explicitly on `org_id`. There
is no per-route `@requires_org_scope` call, consistent with every other blueprint outside
`org_routes.py` — not a Compliant-specific gap.

## Acceptance criteria

### Blueprint & static assets (`compliant_bp.py`)
- Registered only when `compliant_enabled` is true (`app_factory.py:147-150`).
- `GET /compliant/static/<filename>` requires auth, serves only `.js`/`.css` from
  `frontend/static/`, rejects any filename containing `/` or `..` with 400 (path-traversal
  guard is inline, not via `send_from_directory`'s own safety alone).

### Dashboard page (`routes/page_routes.py`)
- `GET /compliant` — requires auth, renders `compliant/dashboard.html`.

### Profile / enrolment (`routes/api_routes.py`)
- `GET /api/compliant/overview` — requires auth. Returns profile (or `null` if never
  configured), evaluated frameworks, state counts, Core movement summary, live Customs
  reconciliation, data-coverage disclosure, priority actions, evidence-readiness counts,
  recent Core proof candidates, trade-waste catalogue list, selected trade-waste catalogue,
  and a disclaimer. Expensive per-org queries (records, reconciliation) are computed once and
  threaded through instead of re-run per section.
- `PUT /api/compliant/profile` — requires auth + ADMIN. Body must be a JSON object; `enabled`
  must be boolean if present, `settings` must be an object if present. Upserts
  `ComplianceProfile` (creates on first call). Logs an `update` action. Returns the refreshed
  profile view.
- `GET /api/compliant/capture-context` — requires auth. Returns whether the evidence capture
  shelf should show for this org (`profile.enabled`), a label and help string. Must never 500
  when no profile exists yet (returns `enabled: false`).

### Alcohol product profiles
- `GET /api/compliant/alcohol-products` — requires auth. Lists this org's
  `AlcoholProductProfile` rows, ordered by `inventory_name`.
- `POST /api/compliant/alcohol-products` — requires auth + ADMIN. Validates `product_type`
  against a fixed enum, `inventory_name` (required, ≤255 chars), `abv_percent` (numeric,
  `0 < x <= 100`). Duplicate `(org_id, inventory_name)` returns 409, not a raw 500 on the
  unique-constraint `IntegrityError`. Logs a `create` action. Returns 201.

### Manual compliance records
- `GET /api/compliant/records` — requires auth. Optional `?framework=<slug>` filter; unknown
  slug returns 400. Returns up to 200 most-recent records, newest first.
- `POST /api/compliant/records` — requires auth (no ADMIN gate — any org member may attest).
  Validates: known `framework_slug`/`control_id` pair against the static catalogue;
  `record_type` and `status` against fixed enums; `title` required ≤255 chars; `source_refs`
  a list of ≤30 strings; `details` an object; `declared_litres_of_alcohol` numeric if present;
  `evidence_reference` ≤1024 chars; `period_end >= period_start` when both given. Requires an
  existing enabled `ComplianceProfile` (409 otherwise). Enforces the control's declared
  capture requirements (`capture_requirements()`): required record type, period, due date,
  evidence reference, source refs, and any control-specific required fields. Every
  `source_ref` that parses as a UUID must resolve to a real row in *this org's* `Execution`,
  `ExecutionEvidence`, `ExecutionStep`, or `InventoryMovement` table — a same-format UUID
  belonging to another org, or to no row at all, is rejected (this is the tenant-isolation
  guarantee for cross-object linking, not just cross-org data reads). Logs a `create` action.
  Returns 201 with the serialised record.

### Audit packs (`routes/api_routes.py` + `service.build_audit_pack`)
- `POST /api/compliant/reports/<framework_slug>` — requires auth. Optional
  `period_start`/`period_end` filter records by overlap. 400 if the framework is unknown, the
  org has no enabled profile, or the framework does not apply to the org's current settings
  (checked before any DB scan). Builds an immutable JSON payload (framework state snapshot,
  source data, filtered records, disclaimer), SHA-256 checksums it, persists a
  `ComplianceReport` row, and returns `report_id` + checksum + payload + a `view_url`. Logs a
  `create` action.
- `GET /api/compliant/reports/<report_id>` — requires auth. 400 on a malformed UUID, 404 if
  the report doesn't belong to this org (must not distinguish "doesn't exist" from "exists in
  another org" in status code or body). `?format=html` renders a printable audit-pack page.
  `?format=csv` streams a CSV export (framework/control/type/status/title/period/due/evidence
  columns) with a `Content-Disposition: attachment` header. Default `format=json` returns id,
  checksum, and the full stored payload.
- Reports are immutable once created — no update/delete route exists; the checksum lets a
  viewer verify a payload hasn't been altered after generation.

### Composition seam (`platform/registry.py`)
- `register_enabled_module_checks(runner)` is the only function Core's `CoreChecksRunner`
  imports from Compliant (`app/core/backend/corechecks.py:83-85`). It must not require the
  runner (or Core) to know any industry-specific check ID, framework slug, or data shape —
  it delegates to whichever modules are installed (today: `nz_alcohol.module.register_checks`).
- A check registered this way that raises is caught by `CoreChecksRunner.run_all_checks()`
  (which wraps per-check exceptions into a flagged `CheckResult`) when run in aggregate, but
  `run_check()` (single-check path) does not catch — pre-existing Core behavior, not scoped
  to this review.

## Data model
- `ComplianceProfile` (`compliance_profiles`): one row per org (`uq_compliance_profiles_org`),
  `enabled`, `industry_module`, `council_name`, `trade_waste_consent_reference`, `settings`
  (JSONB, drives applicability/tolerance/product-type config).
- `ComplianceRecord` (`compliance_records`): append-only manual evidence — framework/control,
  type, status, title, period/due dates, measured/limit values, evidence reference,
  `source_refs` (JSONB list, tenant-validated at write time — see AC above), `details`
  (JSONB), owner/creator user refs (`SET NULL` on user delete).
- `ComplianceReport` (`compliance_reports`): immutable generated snapshot — framework slug,
  period, checksum, full JSONB payload, generator user ref (`SET NULL` on user delete).
- `AlcoholProductProfile` (`compliance_alcohol_product_profiles`): org+inventory_name unique,
  product type, ABV, optional Customs product code, active flag — see Provenance ASSUMPTION
  on why this is spec'd here despite belonging to the nz_alcohol module conceptually.
- All four tables: `org_id` FK to `organisations.id` with `ON DELETE CASCADE`. Migration
  `compliant_nz_alcohol_001` creates all four in one revision with a symmetric `downgrade()`.

## Out of scope for this review
- The nz_alcohol catalogue/council data and its evaluator logic (`compliant-nz-alcohol`
  slug, separately tracked, `reviewed: never`).
- Splitting the platform/nz_alcohol import boundary in `service.py` — documented, deliberate
  debt, not a defect this review should fix.
