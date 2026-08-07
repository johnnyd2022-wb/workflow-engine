# SPEC: process-design
status: reviewed
name: Process Design (create wizard, steps, reordering, process docs)
slug: process-design
blueprint: app/core/backend/backend.py (core_bp, registered in app_factory), app/core/backend/process_docs/ (register_routes(bp) mounted onto core_bp)
url_prefix: /core, /api/core

## Description
Lets an org build reusable process (workflow) definitions as an ordered list of steps:
a multi-page session-backed creation wizard, direct CRUD on processes/steps via JSON
API, drag/drop step reordering (fractional "Option B" positions on a 1000-grid), and
attaching SOP documentation (file upload or inline markdown) to individual steps. Every
mutating write to a process or its steps inserts an immutable `ProcessVersion` snapshot
and emits an event — this is the record `execution` reads from to know what procedure
was being followed for a given run, and what `traceability`/`dashboard` display.

## Users & permissions
- roles: any authenticated org member for process CRUD (except delete), step CRUD,
  reorder, and process-docs upload/inline/list/download (`@requires_auth` only, no
  role gate). ADMIN role required to delete a process
  (`@requires_role(UserRole.ADMIN)`, added 2026-08-03) and to delete a process-doc
  (`@requires_role(UserRole.ADMIN)`, process_docs_routes.py:207) — the two most
  destructive actions in the slice are the two gated ones.
- tenant_scoped: yes throughout. `ProcessRepository`/`ProcessStepDocumentRepository`
  filter every read/write by `org_id`; API handlers derive `org_id` from `g.org_id` /
  `g.current_org_id`, never from the request body. Object lookups return 404 (not 403)
  on cross-tenant access to avoid ID enumeration.
- ASSUMPTION: everything short of deletion has no role gate beyond `@requires_auth` —
  process design is treated as a shared team activity for create/edit, not an
  admin-only one. Deletion of a process (cascades to steps + version history) or a
  process-doc (destroys a file others may be relying on) is elevated to ADMIN.

## Acceptance criteria

### Process CRUD (`/api/core/processes*`)
- AC1: `GET /api/core/processes` lists all processes for the caller's org (never
  another org's), each with `step_count`, `active_executions`/`completed_executions`
  counts, and an `event_summary`; passing `include_steps=true` additionally embeds each
  process's steps. All three supporting queries (executions, event summaries, steps)
  are batch-fetched once for the whole list, not per-process (N+1 avoidance,
  backend.py:1216-1247).
- AC2: `POST /api/core/processes` creates a process (`name` required, 400 otherwise;
  `category` must be a valid `ProcessCategory` or 400), inserts version 1 with an empty
  steps snapshot, and emits `process.created`.
- AC3: `PUT /api/core/processes/<id>` updates only the org-owned process matching
  `<id>` (404 otherwise) and only writes a new `ProcessVersion` + emits `process.updated`
  when at least one field actually changed (no-op update returns 200 without a new
  version).
- AC4: `DELETE /api/core/processes/<id>` is **ADMIN-only** (403 for a non-admin member;
  added 2026-08-03, closing an asymmetry with process-docs delete's ADMIN gate —
  see "Resolved by founder decision" below) and deletes an org-owned process (404
  otherwise), cascading to its steps and its own `ProcessVersion` rows (DB
  `ON DELETE CASCADE`, see process_version.py:39-46), and emits `process.deleted`
  before the delete.
- AC5: `GET /api/core/processes/<id>` returns the process with its full step list
  (ordered by position/step_number) or 404 if not found in-org.

### Step CRUD & reordering
- AC6: `POST /api/core/processes/<id>/steps` requires `step_number` and `name` (400
  otherwise); accepts an explicit `position` (must be a positive, finite, non-`NaN`/
  `Inf` decimal on the 1000-grid — i.e. a multiple of 1000 — or 400) or defaults to
  "append after the current max position"; step outputs are validated so an item's
  `expiry_days` can't be set without `mark_ready` also being set
  (`_validate_step_outputs_expiry_after_ready`); a DB `IntegrityError` on insert returns
  409 rather than 500. On success, inserts a new `ProcessVersion` and emits
  `process.step_added`.
- AC7: `PUT /api/core/processes/<id>/steps/<step_id>` updates only fields present in
  the payload (partial update), re-validates `position` and output expiry rules the
  same way as create, 404s if the step or process doesn't belong to the org, and — like
  create — only writes a version/event when something actually changed.
- AC8: `DELETE /api/core/processes/<id>/steps/<step_id>` deletes an org-owned step
  (404 otherwise), inserts a version snapshot of the remaining steps, and emits
  `process.step_deleted`.
- AC9: `POST /api/core/processes/<id>/steps/reorder` accepts `{"orders": [{"id","position"}]}`
  (or a `"steps"` alias key), validates every position on the same 1000-grid as
  add_step/update_step (400 otherwise, checked before any DB call — so shape/position
  validation runs before existence checks, matching add_step/update_step's own
  ordering), validates the process belongs to the org (404 otherwise), row-locks
  (`FOR UPDATE`) every step under the process to serialize concurrent reorders,
  validates every `id` is among the locked (in-process) steps *before* applying any
  update (404 otherwise), then applies all position updates atomically via
  `ProcessRepository.reorder_steps` in a dedicated `SessionLocal()` transaction
  separate from the request-scoped session — inserting a `ProcessVersion` snapshot and
  emitting `process.steps_reordered`, same audit trail every other step mutation gets.
  - FIXED (was a review-found gap): reorder previously did not insert a
    `ProcessVersion` or emit an event, leaving it invisible to
    `traceability`/`activity-log`. Now goes through `ProcessRepository.reorder_steps`,
    matching add_step/update_step/delete_step.
  - FIXED (was a review-found gap): the route previously leaked a `SessionLocal`
    connection on 4 of its early-return error paths (skipped `sess.close()`). The
    route now wraps the session in `try/finally`. Fixing this also surfaced and fixed
    a second bug in the same code: validating and applying updates in one loop meant a
    mid-loop 404 could still commit whatever positions had already been written on
    that connection (a `return` inside `with sess.begin():` exits normally and
    commits, it doesn't roll back) — `reorder_steps` now validates every step id
    belongs to the process *before* applying any update, so a validation failure can
    never leave a partial reorder silently committed.
  - FIXED (was a review-found gap, not originally in this spec): reorder previously
    never ran positions through grid validation, so an off-grid position reached the
    DB's `chk_steps_position_grid` CHECK constraint raw and 500'd instead of
    400'ing. Now validated via `_is_valid_step_position` before any DB write.

### Create wizard (session-backed, `/core/flows/create/*`)
- AC10: `GET /core/flows/create` is the wizard entry point; with no `?id=` it starts a
  fresh session bucket (`_flow_state_reset`) and redirects into
  `process-overview?fresh=1`; with `?id=<uuid>` for an existing (org-owned; 404 via
  `_assert_flow_process_access` otherwise) process it resumes wizard state for that id.
- AC11: The wizard is 7 ordered pages (process-overview → step-name → inputs → outputs
  → evidence-and-prompts → summary → next-steps). Each page handler resolves
  `?id=`, asserts org ownership if present, then calls
  `_maybe_enforce_flow_wizard_step`, which redirects back to the furthest allowed page
  if the requested page is more than one step ahead of `max_step` in the session
  bucket — this blocks URL-driven skip-ahead for a wizard with no persisted anchor yet.
  Once a `process_id` exists (e.g. the API created it mid-wizard), first navigation to
  any page auto-initializes/advances the bucket instead of bouncing, since a persisted
  process is itself the anchor.
- AC12: Only same-app relative paths under `/core/flows` are honored as a wizard
  `return_to` target (`_safe_flow_return_to`); anything with a scheme, `//`, backslash,
  encoded backslash, `javascript:`/`data:`/`vbscript:` prefix, or a normalized path
  escaping `/core/flows` falls back to the default `?id=<process_id>` destination —
  this is the open-redirect guard referenced by the index and kept in sync with
  `batch-start-scripts.html`'s `ALLOWED_PREFIX`.
- AC13: `_filtered_flow_query_args` only ever forwards an allowlisted `{id, fresh}`
  query-string onto wizard redirects — no other query params survive a wizard
  redirect/link.
- ASSUMPTION: `/core/flows/create/step/<int:step>` (legacy numeric route) is a
  best-effort redirect shim to the current named pages; steps 5+ all fall through to
  `process-overview`, which appears intentional (old bookmarks/links land at the start
  rather than 404ing).
- FIXED (was a review-found gap): `_assert_valid_step_write` (previously
  backend.py:272-292) was defined — docstring claimed it "prevents inconsistent state
  caused by skipping ahead or colliding step numbers" — but was never called from any
  route, and even its body declined to enforce anything beyond what's already enforced
  elsewhere. Deleted as dead code.

### Process docs / SOPs (`/api/core/process-docs/*`)
- AC14: `GET /api/core/process-docs/config` returns the max upload size and allowed
  MIME types (from config) for the frontend to pre-validate before submitting.
- AC15: `POST /api/core/process-docs/upload` requires `process_id`+`step_id` that
  resolve to an org-owned process/step (`validate_process_and_step`, 400 otherwise),
  streams the file to a temp path under the storage root first (so the later
  `os.replace` is same-filesystem/atomic), rejects it (deleting the temp file) if it's
  oversized, empty, or its server-detected MIME (magic-bytes, falling back to the
  `Content-Type` header) isn't in the allowlist. On success: DB record is created and
  committed *before* the file is moved into place; if the move then fails, the record
  is soft-deleted (cleanup) and the temp file removed, so no orphaned "successful"
  record can point at a missing file.
- AC16: `POST /api/core/process-docs/inline` creates or (given `document_id`) updates
  an inline markdown SOP for an org-owned process/step; a file-based document
  (`storage_path` set) cannot be converted to inline via this endpoint (400).
- AC17: `GET /api/core/process-docs/<step_id>` lists every non-deleted doc (file-based
  or inline) attached to a step, scoped to the caller's org via the document's own
  `org_id` column (not a lookup on the step's process).
- AC18: `GET /api/core/process-docs/<doc_id>/download` streams a file-based doc's bytes
  (404 if not found/not org-owned/inline-only), defaulting to
  `Content-Disposition: attachment` unless `?inline=1`/`?view=1`, and always sets
  `X-Content-Type-Options: nosniff`.
- AC19: `DELETE /api/core/process-docs/<doc_id>` is ADMIN-only, soft-deletes the DB
  record first (commit), then best-effort deletes the underlying file — ordered so a
  failed file delete never leaves a "deleted" doc still discoverable via the API, and a
  failed record delete never orphans a file silently. Deleting an already-deleted /
  nonexistent doc returns success (idempotent).
- AC20: All stored files live under
  `process_docs_storage/<org_id>/<process_id>/<step_id>/<uuid>.<ext>`; filenames are
  server-generated UUIDs (never derived from user input), validated against a strict
  `^[a-f0-9\-]{36}\.(pdf|doc|docx|md|txt|bin)$` pattern before any filesystem read/
  delete, and `read_file_path` additionally confirms the resolved path stays under the
  storage root — defense in depth against path traversal even though filenames are
  never user-controlled.

## Data model
- `Process` (processes): id, org_id (FK, indexed), name, description, category (enum:
  manufacturing/chemical/packaging/assembly/other), is_draft, created_at, updated_at.
  Cascades to steps and executions on delete.
- `Step` (steps): id, process_id (FK), step_number (user-facing order, not canonical),
  position (NUMERIC(50,20), indexed — the actual sort key, "Option B" fractional
  positioning on a 1000-grid so drag/drop insert-between never requires bulk
  renumbering), name, description, inputs/outputs/execution_prompts (JSONB arrays).
- `ProcessVersion` (process_versions): immutable snapshot (`snapshot` JSONB) of a
  process + all its steps, auto-incrementing `version_number` per process, written on
  every process/step create/update/delete/reorder. `ON DELETE CASCADE` at the DB
  level; the ORM relationship is `passive_deletes=True` specifically so SQLAlchemy
  defers to that cascade instead of trying to null a NOT NULL `process_id` on process
  delete.
- `ProcessStepDocument` (process_step_documents): id, org_id/process_id/step_id (FKs,
  indexed), title, storage_path (nullable — file-based docs only), content_markdown
  (nullable — inline docs only), mime_type, file_size, created_by, deleted_at
  (soft-delete marker).

## Out of scope
- Execution/DAG traversal, running a batch, completing a step — `execution` slice.
- Inventory item selection referenced by step inputs/outputs — `inventory` slice.
- Lineage/traceability views built from `ProcessVersion` snapshots — `traceability`
  slice.

## Known gaps — as of the 2026-08-02 review

### Closed this review
- No dedicated process-docs test file (index-flagged gap) → closed:
  `tests/e2e/test_process_docs_flow.py` (17 tests: upload/inline/list/download/delete,
  cross-tenant probes).
- No test coverage for `/api/core/processes/<id>/steps/reorder` (unit or e2e) →
  closed: `tests/e2e/test_process_steps_flow.py` (28 tests) +
  `tests/test_process_design.py` unit tests, including the audit-trail and
  position-validation fixes below.
- `_assert_valid_step_write` dead code → deleted.
- Reorder endpoint: missing audit trail, `SessionLocal()` connection leak on
  early-return paths, and (found while fixing) a partial-commit-on-validation-failure
  bug and missing position-grid validation (500 instead of 400) → all fixed, see AC9.
- `app_factory.py`'s global `MAX_CONTENT_LENGTH` silently capped process-docs uploads
  at evidence's 10MB instead of process-docs' own advertised 20MB (found independently
  by security-audit and e2e-playwright, not originally listed here) → fixed: now
  `max()` across every feature's own upload cap.
- Process/step CRUD, reorder, and wizard helpers had zero *unit* (non-e2e) test
  coverage → closed: `tests/test_process_design.py` (59 tests).

### Resolved by founder decision (2026-08-03)
- **Admin-gate asymmetry**: founder chose to add `@requires_role(UserRole.ADMIN)` to
  `DELETE /api/core/processes/<id>` (the more destructive action — cascades to all
  steps + all `ProcessVersion` history) rather than drop the existing ADMIN gate from
  `DELETE /api/core/process-docs/<doc_id>`. AC4 updated above; both endpoints are now
  ADMIN-gated.
- **Undocumented historical destructive migration**: `drop_uq_steps_psn_001`
  (2026-04-13) removed a constraint with no permit file at the time. Permit backfilled
  at `.agents/reports/migrations/drop_uq_steps_psn_001.md`, founder-acknowledged
  2026-08-03, status `ACKNOWLEDGED — roll forward`. No code/migration change (no data
  was lost; the removal was part of a same-day, coherent design supersession).

### Noted, not a gap
- `process_docs_delete`'s cross-tenant-miss and already-deleted paths are the same
  code path (both return `200 {"deleted": true}`) — a *stronger* anti-enumeration
  property than every other process/step endpoint's 404-on-cross-tenant convention,
  but worth knowing it's an intentional asymmetry, not an oversight, if it's ever
  "fixed" to match the rest of the API.
