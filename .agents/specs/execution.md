# SPEC: execution
status: reviewed
name: Execution (process runs, step completion, DAG traceability, evidence)
slug: execution
blueprint: core_bp — routes in `app/core/backend/backend.py` (executions API, execution
  metadata, `/core/flows*` and `/core/executions/live` view routes),
  `app/core/backend/dagtraversal.py` (traceability engine, used by the `traceability`
  slice's routes), `app/core/backend/complete_step_payload.py` (HTTP contract for step
  completion), `app/core/backend/evidence/*` (upload/download/list/delete)
url_prefix: /api/core, /core

## Description
Runs a `Process` (defined by the process-design slice) as an `Execution`: one row per
run, one `ExecutionStep` per step in the process's DAG, advanced in step-number order.
Completing a step (`POST .../steps/<id>/complete`) is the single highest-risk write path
in the app — `complete_step` (backend.py, ~615 lines) does, in one DB transaction:

1. Validates and sanitizes the request body (`complete_step_payload.py`): size cap,
   JSON depth/breadth/node-count budget, Pydantic `extra="forbid"` shape.
2. Strips client-supplied audit/trace keys from `execution_data`
   (`_strip_incoming_execution_trace_keys`) and re-derives `completed_by` /
   `completed_by_email` / `completed_by_user_id` from the authenticated session — the
   client can never forge who completed a step.
3. Marks the step `COMPLETED` via `ExecutionRepository.complete_step`, which enforces
   step order (all prior steps must be `COMPLETED` first) and advances the next step(s)
   to `READY` per the DAG (`_advance_execution`).
4. Consumes inventory for `actual_inputs` (unit conversion, availability check, FOR
   UPDATE row locks) and creates `InventoryItem` rows for `actual_outputs`
   (intermediate vs. final product, based on `is_terminal_step`), including custom
   per-output expiry/ready-date validation.
5. Commits inventory consumption + output creation atomically with the step completion;
   on any blocking error the whole transaction rolls back and the step stays `READY` so
   the client can retry.

`dagtraversal.py` is the read-side traceability engine: given a start inventory item, it
walks the produced-by/consumed-by graph (via `ExecutionStep.actual_inputs` /
`InventoryItem.source_execution_step_id`) forward or backward, org-scoped throughout, and
is the shared engine behind trace-forward/backward and expired-raw-material impact
lookups (consumed by the `traceability` slice).

Evidence (`evidence/*`) is a parallel, simpler subsystem: upload a file against an
execution (optionally a step), streamed to a temp file, MIME-sniffed from magic bytes
(not trusted from the client), checksummed, and moved into
`app/core/evidence_storage/<org_id>/<execution_id>/<uuid>.<ext>` only after the DB
record commits (no orphan files, two-phase: PENDING → ACTIVE).

## Users & permissions
- roles: any authenticated user of the org (`@requires_auth`); no `@requires_role` gate
  anywhere in this surface, same pattern as inventory — a MEMBER can create executions,
  complete steps, and upload/delete evidence.
- tenant_scoped: yes. Every route resolves `org_id = UUID(g.org_id)` (API routes) or
  `getattr(g, "org_id", None)` (evidence routes) and passes it into the repository/service
  layer, which filters on `org_id` at every query. `dagtraversal.py` additionally
  re-scopes ExecutionStep/Execution/Process lookups by `org_id` even when the ID being
  looked up came from another already-org-scoped row's foreign key — defense in depth
  against a corrupted or forged provenance reference pulling another org's data across
  the tenant boundary (see `_enrich_items_bulk`'s comment).
- ASSUMPTION: the `/core/flows*` view routes gate on `@requires_auth` +
  `_assert_flow_process_access` (org-scoped process lookup, 404 on miss/wrong org) but
  not `@requires_org_scope`; derived from the decorators present as of this review,
  consistent with the inventory slice's spec.

## Acceptance criteria

### Execution lifecycle
- AC1: `POST /api/core/executions` creates an `Execution` (status `IN_PROGRESS`) with one
  `ExecutionStep` per `Step` of the given `process_id`, scoped to the caller's org, and
  returns 201. A `process_id` that doesn't resolve in the caller's org → 404 (via
  `ValueError` from the repo); a missing/malformed `process_id` → 400.
- AC2: `GET /api/core/executions` lists only the caller's org's executions, with
  optional `process_id`/`status` filters (400 on a malformed filter value), each
  annotated with `current_step` (first `READY` step, 1-based display position),
  `progress` (% completed steps), batched evidence, and an event-summary rollup — all
  fetched in batch (no per-execution query loop).
- AC3: `GET /api/core/executions/<id>` and `.../with-process` return 404 for an
  execution outside the caller's org, never partial data.

### complete_step (the 615-line critical path)
- AC4: `POST .../steps/<execution_step_id>/complete` enforces step order: completing a
  step before all lower-numbered steps are `COMPLETED` raises and returns 400
  (`ValueError` from the repo, "prior steps ... are not completed"); the step remains
  in its prior status.
- AC5: A step not in `READY`/`IN_PROGRESS` (already completed, or doesn't exist in the
  caller's org) → 400 / 404 respectively; no partial mutation (single transaction,
  rolled back on any failure after the initial repo-level flush).
- AC6: Request body is capped (768KB), JSON-validated for depth/breadth/node-count
  before use, and rejects unknown top-level keys (`CompleteStepRequestBody`,
  `extra="forbid"`). Oversized or malformed bodies → 400/413, never reach business logic.
- AC7: `completed_by` / `completed_by_email` / `completed_by_user_id` in the persisted
  `execution_data` always come from the authenticated session (`g.user_email`,
  `g.user_id`), never from the client payload — any client-supplied audit/trace keys are
  stripped before merge (`_strip_incoming_execution_trace_keys`).
- AC8: Consuming `actual_inputs` aggregates by `inventory_item_id` (so the same item
  can't be over-consumed by two input lines in one request), locks each item row
  (`FOR UPDATE`), checks unit compatibility/conversion, and blocks the whole completion
  (400, rollback) if any input's total requested quantity exceeds availability, the item
  isn't found, or the item isn't ready for consumption (unless
  `allow_consumption_override`).
- AC9: Producing `actual_outputs` creates one `InventoryItem` per non-zero-quantity
  output — `WORK_IN_PROGRESS` for non-terminal steps, `FINAL_PRODUCT` for
  `is_terminal_step`; zero/negative-quantity or unparseable-quantity outputs are
  **skipped with a warning**, not blocked.
- AC10: **Warnings collected during completion (e.g. skipped outputs, inventory items
  not found) are returned in the HTTP response AND persisted to
  `execution_step.execution_data.execution_warnings`** so later reads (traceability's
  `extra_data.execution_trace`, compliance-checks, dashboard) see them too — not just
  the immediate caller. *(Was broken before this review: see Known Issues Fixed.)*
- AC11: Per-output custom expiry (`fixed_duration` vs `set_at_execution`) and
  ready-date config on the step definition is enforced at completion time: a
  `set_at_execution` output without a valid operator-supplied value → 400; when both
  expiry and ready-date resolve, expiry must not precede ready-date.
- AC12: An output may optionally reconcile into an existing "untracked" inventory item
  (`untracked_item_id`) instead of creating new stock outright; only the surplus above
  the reconciled amount becomes a new `InventoryItem`.
- AC13: Inventory consumption + output creation + reconciliation commit in one
  transaction (`db_session.commit()` at the end of `complete_step`); any exception during
  that block rolls back everything, including the earlier step-completion flush.

### Evidence
- AC14: `POST /api/core/evidence/upload` requires `execution_id` (valid UUID, resolves
  in caller's org) and a file; the file is streamed to a temp path, size-capped
  (`evidence_max_file_size_mb`, default 10MB), and MIME-sniffed server-side from magic
  bytes (PNG/JPEG/PDF) — the client-declared `Content-Type` is only a fallback, never
  trusted alone.
- AC15: On success, the evidence record is created `PENDING`, the file is atomically
  moved into final storage, checksum-verified post-move, then marked `ACTIVE` — any
  failure at any stage deletes the DB record and/or file so no orphan of either kind
  survives.
- AC16: `uploaded_by` on the evidence record is always the authenticated session's
  email when present. *(Was broken before this review: see Known Issues Fixed.)*
- AC17: `GET .../<id>/download` and `DELETE .../<id>` 404 for evidence outside the
  caller's org (`get_by_id(..., org_id=...)` / `delete_by_id(..., org_id)`); download
  filenames are validated against a strict `UUID.ext` pattern before any filesystem read
  (no path traversal via a forged `storage_path`).

### Traceability (dagtraversal.py, consumed by the `traceability` slice)
- AC18: `DAGTracer.traverse` is org-scoped at every query (start items, execution steps,
  produced items) and terminates on arbitrarily large/cyclic graphs via a visited-node
  set (no recursion, iterative deque-based DFS/BFS).
- AC19: Items with quantity ≤ 0 are excluded from results unless they're in the
  traversal's `root_set`; edges whose endpoints get filtered out are removed too (no
  dangling edges in the returned graph).
- AC20: Every step/execution/process lookup used to enrich or connect traversal nodes is
  scoped to `self.org_id`, even when the foreign key being looked up was read off an
  already-org-scoped row — so a corrupted or forged `source_execution_step_id` cannot
  pull another org's step data (`step_number`, `actual_inputs`, `execution_data`) into
  this org's response. *(Was inconsistently applied before this review — see Known
  Issues Fixed.)*

## Data model
- `Execution`: `org_id`, `process_id`, `status` (IN_PROGRESS/COMPLETED/…), `started_at`,
  `completed_at`, `total_steps`.
- `ExecutionStep`: `execution_id`, `step_id` (FK to the process's `Step` definition),
  `step_number` (denormalized), `status` (PENDING/READY/IN_PROGRESS/COMPLETED/FAILED/
  SKIPPED), `is_terminal_step`, `actual_inputs`/`actual_outputs`/`execution_data`
  (JSONB, immutable-by-convention after completion — see Known Issues Fixed for the one
  place that wasn't respecting that), `started_at`, `completed_at`.
- `ExecutionEvidence`: `org_id`, `execution_id`, `step_id` (nullable), `file_name`,
  `storage_path` (relative, `org_id/execution_id/uuid.ext`), `mime_type`, `file_size`,
  `checksum_sha256`, `uploaded_by`, `evidence_status` (PENDING/ACTIVE).
- ASSUMPTION: the feature index (`.agents/feature-index.md`) lists `ApiIdempotencyKey`
  among this slice's models, but it is only referenced in `backend.py`'s wastage-batch
  route (inventory slice) — no execution-slice code path (`complete_step`,
  `ExecutionRepository`, evidence routes) constructs or queries it. `complete_step`'s
  own idempotency comes from the `ExecutionStep.status` state machine instead (a
  re-completion attempt fails with "not in a state that can be completed", not a silent
  200). Flagged as a stale index entry for **docs-truth**, not corrected here per this
  skill's own rule that index maintenance isn't this skill's job.

## Known Issues Fixed (this review)
1. **`execution_warnings` never persisted** (`backend.py`, `complete_step`): warnings
   were mutated into the already-flushed `execution_step.execution_data` JSONB dict
   in-place, which SQLAlchemy's dirty-tracking never saw (plain `JSONB` column, not
   `MutableDict`-wrapped) — silently dropped on commit. Returned to the caller in the
   HTTP response but invisible to every later reader. Fixed by reassigning the dict
   instead of mutating it in place. Regression test:
   `tests/test_executions.py::TestRegressionSafeguards::test_execution_warnings_persist_to_db_not_just_response`.
2. **Cross-tenant step lookup in `DAGTracer.add_step_order_connections`**
   (`dagtraversal.py`): unlike every other step/item lookup in the file, this one
   queried `ExecutionStep` by ID alone with no join back to `Execution.org_id`. Fixed to
   match the file's own documented defense-in-depth pattern. Regression test:
   `tests/test_dag_traversal.py::TestAddStepOrderConnectionsTenantIsolation`.
3. **`uploaded_by` always `None` on evidence upload** (`evidence_routes.py`): a
   conditional expression's operator precedence (`A or B if C else D` parses as
   `(A or B) if C else D`, not `A or (B if C else D)`) combined with `g.user` never
   being set anywhere in this codebase meant the real `g.user_email` was always
   discarded. Fixed by simplifying to `getattr(g, "user_email", None)`. Regression
   test: `tests/test_evidence.py::TestEvidenceUploadRecordsUploader`.

## Known coverage gaps (pre-existing, out of this review's fix scope)
- No test file existed for `app/core/backend/evidence/*` before this review; this audit
  added one targeted regression test, not full route coverage (upload validation edge
  cases, download, delete, config are still unexercised — hand-off candidate for
  **test-author**).
- `create_execution`'s exception handling has a dead second `except ValueError` clause
  (backend.py, `create_execution`) — the first `except ValueError` catches everything
  before it, so the intended 400 branch for a malformed `process_id`-shaped-but-invalid
  value is unreachable; every `ValueError` from the repo currently returns 404. Not
  fixed in this pass (behavior-preserving no-op today since the repo only raises
  `ValueError` for the "not found" case) — flagged for a follow-up since it would
  silently regress if the repo ever raises `ValueError` for a different reason.
