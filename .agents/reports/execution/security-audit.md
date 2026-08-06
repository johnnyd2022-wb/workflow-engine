# SECURITY: execution
date: 2026-08-02
verdict: findings-open
scanned: semgrep(0 findings, p/python+p/flask+p/owasp-top-ten+.semgrep/ against the 8 scoped files), gitleaks(0 leaks, full history), uv-audit(not run — see not_verified)
manual_checklist: 7/7 completed

## Scope
Routes: `/core/flows`, `/core/flows/executions/step`, `/core/flows/batches/start`,
`/core/executions/live`, `/api/core/executions*`, `/api/core/execution-metadata`,
`/api/core/evidence/*`. Files: `app/core/backend/backend.py:1695-2610` (executions API,
`complete_step`) and `:4016-4099` (execution metadata); `app/core/backend/dagtraversal.py`;
`app/core/backend/complete_step_payload.py`; `app/core/backend/evidence/*`.

## Prior fixes verified present (not re-reported)
1. `execution_warnings` JSONB reassign-not-mutate fix — confirmed at `backend.py:2495-2499`
   (dict rebuilt with `{**old, "execution_warnings": ...}` instead of in-place `dict[key] =`).
2. `DAGTracer.add_step_order_connections` org-scoped join — confirmed at
   `dagtraversal.py:750-757` (`.join(Execution, ...).filter(ExecutionStep.id.in_(step_ids),
   Execution.org_id == self.org_id)`).
3. Evidence `uploaded_by` operator-precedence fix — confirmed at
   `evidence_routes.py:81-82` (`getattr(g, "user_email", None)`, no ternary).

## Findings

- F1 [fix] `app/core/backend/dagtraversal.py:577-579` — `DAGTracer.find_impacted_by_expired_raw`
  queries `ExecutionStep` by ID alone, with no join back to `Execution.org_id`:
  ```python
  steps = (
      self.session.query(ExecutionStep).filter(ExecutionStep.id.in_(step_ids_orm)).all() if step_ids_orm else []
  )
  ```
  This is the same bug class as prior fix #2 above (`add_step_order_connections`), in the
  same file, and the fix for #2 is present right below it (line 750) with an explicit
  comment explaining why every such lookup must be org-scoped — but this earlier function
  wasn't updated to match. `_enrich_items_bulk` (line 642-645) and
  `add_step_order_connections` (line 750-757) both re-scope by org even though the
  `source_execution_step_id` FK was read off an already-org-scoped `InventoryItem` row —
  exactly the defense-in-depth spec AC20 describes. `find_impacted_by_expired_raw` is the
  one remaining lookup in this file that doesn't.
  repro/evidence: `step_ids_orm` is built from `source_execution_step_id` on `InventoryItem`
  rows returned by `self.traverse()` (already org-scoped at the item level). If any of those
  rows carries a `source_execution_step_id` pointing at another org's `ExecutionStep` — via
  data corruption, a bug in a future write path, or any write path that bypasses
  `InventoryRepository._assert_source_refs_belong_to_org` (`inventory_repo.py:95-170`, the
  guard that blocks this exact attack on `POST /api/core/inventory`) — this function pulls
  that foreign step's `completed_at` and `execution_id` cross-org and returns them in the
  `impacted_items`/`connections` response. Reachable via `GET
  /api/core/inventory/expired-materials` → `run_expired_materials_check` →
  `find_impacted_by_expired_raw` (`checks/expired_materials.py`). Today's write-side guard
  (`_assert_source_refs_belong_to_org`) closes the only currently-known route to plant such a
  row via the public API, so this is defense-in-depth rather than a demonstrated live
  exploit — but it's the same class the review already treated as worth fixing twice
  elsewhere in this file, and per AC20's own stated invariant ("every step/execution/process
  lookup ... scoped to self.org_id, even when the foreign key ... came from an
  already-org-scoped row") this function is out of compliance.
  severity: medium (defense-in-depth gap in a tenant-isolation invariant the file otherwise
  enforces everywhere else; not independently exploitable via any route found in this audit,
  but one bypass of the write-side guard away from a live cross-org data leak of
  execution_id/completed_at).
  patch: not applied (chain-stage, read-only). Suggested fix, matching the sibling pattern at
  line 750-757:
  ```python
  steps = (
      self.session.query(ExecutionStep)
      .join(Execution, ExecutionStep.execution_id == Execution.id)
      .filter(ExecutionStep.id.in_(step_ids_orm), Execution.org_id == self.org_id)
      .all()
      if step_ids_orm else []
  )
  ```
  A regression test analogous to
  `tests/test_dag_traversal.py::TestAddStepOrderConnectionsTenantIsolation` (seed org B's
  `InventoryItem.source_execution_step_id` pointing at org A's step, call
  `find_impacted_by_expired_raw` as org A, assert org B's step is not visited) would close
  this the same way #2 was closed.
  rule_added: none (chain stage — recommend `.semgrep/rules/learned.yml`, id
  `bize-execution-step-query-missing-org-join`: flag `session.query(ExecutionStep).filter(...)`
  calls that reference `ExecutionStep.id` but have no `.join(Execution` / `Execution.org_id`
  in the same filter chain; fixture pair from this exact function pre/post patch. Left to the
  caller since a chain-stage grader doesn't own `.semgrep/` writes this run — logged here so
  it isn't lost.)
  finding_history: recorded `confirmed` (sig d6ece0b3f6a8, area
  `app/core/backend/dagtraversal.py`, kind `cross-tenant-execution-step-lookup`).

- F2 [accepted-risk candidate — recommend, not self-approved] `app/core/backend/evidence/evidence_routes.py:53,67,91`
  — `evidence_upload` accepts `step_id` from `request.form` and passes it straight through
  (`validate_upload_request` only checks it parses as a UUID) to
  `EvidenceRepository.create(..., step_id=step_uuid, ...)`, which stores it on
  `ExecutionEvidence.step_id` — a FK to the global `steps` table — with no check that the
  step belongs to the caller's org, or to the specified execution's process.
  repro/evidence: `evidence_routes.py:52-93`; `evidence_repo.py:18-47` (`create` takes
  `step_id` and stores it unchecked); `execution_evidence.py:25` (`step_id =
  Column(..., ForeignKey("steps.id"), ...)` — no org scoping in the FK itself, same category
  the codebase already treats as a live risk for inventory provenance FKs, see
  `_assert_source_refs_belong_to_org`'s own docstring: "nothing in the schema stops a row in
  org A from referencing org B's ... — that reference is then followed by lineage
  enrichment, so an unvalidated reference is a cross-tenant read primitive, not just a
  cosmetic data-integrity problem").
  Checked whether this is currently exploitable as a read primitive: every place `step_id`
  is later surfaced (`evidence_service.py:158,207,250`, exposed to clients as
  `step_definition_id`) resolves it only by matching against the *caller's own execution's*
  `execution_steps` map (`{str(es.step_id): str(es.id) for es in execution.execution_steps}`)
  — a cross-org `step_id` simply fails to match and comes back `execution_step_id: null`. No
  code path was found that joins `step_id` back to the `Step` table to render its name,
  process, or other org-owned data. So today this is a data-integrity gap (an evidence
  record can carry a dangling/foreign FK), not a demonstrated cross-tenant read.
  severity: low today; flagged because it deviates from the pattern the codebase applies
  everywhere else for exactly this FK shape (inventory's `source_execution_step_id`,
  `source_output_id`), and because "no current read path" is a property of today's code,
  not a schema-level guarantee — the next feature that joins evidence to its step (e.g. to
  show the step name on an evidence card) would inherit this hole silently, the same way the
  three bugs already fixed in this review were each "no current path" until code around
  them changed.
  patch: not applied (chain-stage, read-only). Suggested: validate `step_id` belongs to
  `execution.process`'s steps (the execution is already loaded org-scoped in
  `upload_evidence_from_temp`) before passing it to `evidence_repo.create`, mirroring
  `_assert_source_refs_belong_to_org`'s shape.
  rule_added: none (chain stage; same reasoning as F1 — recommend to caller).
  finding_history: recorded `confirmed` (sig 53530882c55d, area
  `app/core/backend/evidence/evidence_routes.py`, kind `unvalidated-cross-tenant-fk`).

## Attempted but clean
- Auth on every route in scope: all 13 routes checked (`/core/flows*`,
  `/core/executions/live`, `/api/core/executions*`, `/api/core/execution-metadata`,
  `/api/core/evidence/*`) carry `@requires_auth`; none bare.
- Tenant isolation on every query in `complete_step`, `create_execution`, `list_executions`,
  `get_execution`, `get_execution_with_process`, `get_execution_metadata`: all filter by
  `org_id`/`Execution.org_id` at the query level, including the inventory FOR-UPDATE lock
  (`get_inventory_item_by_id_for_update`, `inventory_repo.py:368-375`) and the reconciliation
  path (`reconciliation_service.py`, confirmed it routes through the org-guarded
  `create_inventory_item`, not raw ORM construction).
  Object lookups use `(id, org_id)` pairs throughout; cross-org access 404s, not 403
  (`get_execution_with_steps`, `EvidenceRepository.get_by_id`/`delete_by_id`).
- Evidence path traversal / mass assignment: `is_safe_filename` (UUID.ext regex, rejects
  `..`/`/`/`\\`) plus `candidate.resolve().relative_to(root.resolve())` in `read_file_path`
  (`evidence_storage.py:114-130`) — filenames are never client-controlled (server generates
  `uuid4()+ext` from server-detected MIME, `prepare_final_path`), and reads double-check the
  resolved path is still under the storage root. No traversal reachable.
  Upload MIME is server-sniffed from magic bytes (`detect_mime_from_path`,
  `evidence_validation.py:20-32`), client `Content-Type` only a fallback. Size capped
  (`get_max_file_size_bytes`, streamed to temp file, checked before move). Two-phase
  PENDING→ACTIVE commit with cleanup on every failure branch — no orphan DB row or file
  found in `upload_evidence_from_temp` across the checksum/finalize/verify/activate
  failure paths.
- `complete_step` request-body validation: 768KB cap enforced both via `Content-Length` and
  actual byte count (`backend.py:2003-2009`), depth/breadth/node-count budget via
  `validate_json_blob` (`complete_step_payload.py`), Pydantic `extra="forbid"` on the
  top-level shape. Client cannot forge `completed_by`/`completed_by_email`/
  `completed_by_user_id` — always re-derived from `g.user_email`/`g.user_id` after
  `_strip_incoming_execution_trace_keys` strips any client-supplied copies.
  `execution_step` mutation is org-scoped at the repo level
  (`ExecutionRepository.complete_step`, `execution_repo.py:240-245`, joins `Execution` and
  filters `org_id`), and step-order + status-machine enforcement (prior-steps-completed,
  READY/IN_PROGRESS-only) is checked before any mutation.
- Inventory consumption in `complete_step`: aggregated per `inventory_item_id` before
  locking (prevents double-spend across multiple input lines in one request), `FOR UPDATE`
  row lock held to commit, unit-compatibility/conversion checked, over-consumption blocked
  with rollback (400) rather than partial mutation.
- Open redirect / XSS on `/core/flows*` view routes: `_safe_flow_return_to`
  (`backend.py:148-209`) rejects `\\`, `//`, `javascript:`/`data:`/`vbscript:` schemes,
  encoded-backslash bypass (`%5c`), and anything resolving outside `/core/flows` after
  `posixpath.normpath`; double-unquote guards against doubly-encoded bypasses. Fragment is
  separately checked for the same scheme/traversal patterns. `execution_id`/`step_id`/
  `return_to` are rendered into `batch-start-scripts.html` via Jinja's `|tojson` filter
  (HTML-safe JSON encoding for `<script>` context), not `|safe` or raw interpolation — no
  XSS vector found.
- CSRF: state-changing routes in scope (`POST /api/core/executions`, `POST
  .../steps/<id>/complete`, `POST /api/core/evidence/upload`, `DELETE
  /api/core/evidence/<id>`) rely on the app-wide Flask-WTF `X-CSRFToken` contract per
  CLAUDE.md; not re-verified per-route in this pass (out of scope for a feature-slice audit
  — app-wide CSRF wiring is a single cross-cutting concern, not per-blueprint).
- Secrets: gitleaks full-history scan (942 commits) — 0 leaks in the scoped files or
  anywhere else in history.
- Mass assignment: `CompleteStepRequestBody` (Pydantic, `extra="forbid"`) is the only
  request-body-to-object path in scope; no `Model(**request.json)` or looped `setattr`
  found in `backend.py:1695-2610`, `evidence_routes.py`, or `evidence_service.py`.
- SQL injection: no raw SQL / string-built queries in any scoped file; all ORM with bound
  filters.

## Not verified
- `uv audit` was not run this pass (dependency CVE scan is out of this feature-slice's
  scope per the skill's own routing — CVEs go through `dependency-update`, not
  `security-audit`'s manual pass — and preflight didn't flag a stale lockfile). Standing
  gap, not new to this review.
- Docs-truth item noted in the spec (stale `ApiIdempotencyKey` feature-index entry) is a
  documentation-accuracy issue, not security; left to docs-truth per the spec's own note.
- `create_execution`'s dead second `except ValueError` clause (`backend.py:1731-1734`,
  documented in the spec's "Known coverage gaps" as intentionally not fixed this pass,
  behavior-preserving no-op today) — correctness/robustness issue, not a security
  vulnerability (it can't currently be forced to diverge from today's 404 behavior since the
  repo only raises `ValueError` for the not-found case); not re-flagged here per the spec's
  own scoping.
- CSRF wiring was assumed from CLAUDE.md's documented app-wide contract rather than
  independently traced through Flask-WTF config for this specific blueprint.
