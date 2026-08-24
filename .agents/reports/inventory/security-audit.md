# SECURITY: inventory
date: 2026-07-27
verdict: findings-open
scanned: semgrep(0 findings, 591 rules incl. p/python p/flask p/owasp-top-ten + .semgrep/), gitleaks(0, 913 commits/24.45MB scanned), uv-audit(0 vulnerabilities, 84 packages)
manual_checklist: 7/7 completed (auth-on-every-route, tenant isolation, mass assignment, injection, SSRF/uploads, secrets/config, CSRF/CORS)

## Findings

### F1 [CRITICAL] Cross-tenant data exfiltration: unvalidated execution FK + unscoped trace enrichment
files: `app/core/backend/backend.py:3591-3599` (write side), `app/core/backend/dagtraversal.py:628-641` (read side), reachable via `app/core/backend/backend.py:3848` (`trace_raw_material`) and `:3938` (`trace_inventory_backward`)

This is the concrete exploit chain behind the orchestrator's candidate #1, and it's worse than a mass-assignment issue in isolation — it's a two-step cross-tenant read.

**Step 1 (write):** `create_inventory_item` parses `source_execution_id`, `source_execution_step_id`, `source_output_id` straight from client JSON into UUIDs with zero ownership check:
```python
source_execution_id = None
if data.get("source_execution_id"):
    source_execution_id = UUID(data["source_execution_id"])       # backend.py:3591-3593
source_execution_step_id = None
if data.get("source_execution_step_id"):
    source_execution_step_id = UUID(data["source_execution_step_id"])  # :3594-3596
source_output_id = None
if data.get("source_output_id"):
    source_output_id = UUID(data["source_output_id"])             # :3597-3599
```
These flow unchanged into `InventoryRepository.create_inventory_item` (`inventory_repo.py:93-158`), which writes them straight onto the new row. `executions.id` / `execution_steps.id` are global tables (not per-org partitioned), so nothing stops a value belonging to a different org.

**Step 2 (read):** `trace_raw_material` / `trace_inventory_backward` call into `dagtraversal.trace_forward`/`trace_backward`, which end in `DagTraversal._enrich_items_bulk` (`dagtraversal.py:628-674`):
```python
steps = self.session.query(ExecutionStep).filter(ExecutionStep.id.in_(step_ids)).all() if step_ids else []   # :635 — no org filter
executions = self.session.query(Execution).filter(Execution.id.in_(exec_ids)).all() if exec_ids else []       # :637 — no org filter
processes = self.session.query(Process).filter(Process.id.in_(process_ids)).all() if process_ids else []      # :640 — no org filter
```
Compare with the correctly-scoped sibling in the same file (`:314-319`, join `Execution` filtered by `self.org_id`) and with `backend.py:_hydrate_step_data` (`:493-519`), which explicitly joins through `Execution.org_id == org_id` "to enforce org_id (defense-in-depth against upstream scoping drift)". `_enrich_items_bulk` is the one enrichment path that doesn't do this.

**Attack:** an authenticated member of Org A calls `POST /api/core/inventory` with `source_execution_step_id` set to a UUID belonging to Org B (obtained via any prior leak, enumeration, or simply because they used to be a member of Org B before an org switch). They then call `GET /api/core/inventory/trace/<their_own_item_id>`. `_enrich_items_bulk` fetches Org B's `ExecutionStep` (including `execution_data` — prompts/internal fields, `actual_inputs`, `actual_outputs`) and `Process.name`, and stitches them into Org A's response as `extra_data.execution_prompts`, `variable_inputs`, `variable_output`, `process_name`. This is a genuine tenant-boundary break, not just a dangling/globally-unique FK: production process data (recipes, prompts, quantities) from one tenant becomes readable by another.

fix: two independent layers, do both:
1. In `create_inventory_item` (backend.py:3591-3599) and `InventoryRepository.create_inventory_item`, validate `source_execution_id` (and, transitively, the step/output) belongs to `org_id` before writing — reject with 400 otherwise. This is the root cause. Already fixed by commit `7650042`: `InventoryRepository._assert_source_refs_belong_to_org` now does exactly this (verified 2026-08-25 by findings-sweep).
2. In `_enrich_items_bulk` (dagtraversal.py:635,637,640), scope every query: join `ExecutionStep`→`Execution` filtered on `self.org_id` (same pattern as line 314-319 and `_hydrate_step_data`), and filter `Process` by joining through the already-org-scoped executions. Do this even after (1) is fixed — it's the actual defense-in-depth backstop and the only thing that would have contained this bug's blast radius on day one. Already fixed by commit `7650042`: `_enrich_items_bulk` now org-scopes every lookup (verified 2026-08-25 by findings-sweep).
rule_added: none — flagged as `escalate`-class per skill routing (tenant isolation / auth bypass); this skill run is read-only, remediation to be routed via fix-bug with a red-then-green org-A/org-B repro test per the skill's table.

Already fixed by commit `7650042`: both layers are in place. (1)
`InventoryRepository._assert_source_refs_belong_to_org` (inventory_repo.py:132-170)
validates `source_execution_id`/`source_execution_step_id`/`source_output_id` against
`org_id` before `create_inventory_item` writes, raising `ValueError` which
`backend.py:3801` catches and returns 400. (2) `_enrich_items_bulk`
(dagtraversal.py:636-668) now joins `Execution`/`Process` filtered on `self.org_id` for
every lookup. Verified 2026-08-25 by findings-sweep.

### F2 [HIGH] `adjust_inventory_item_quantity`: "nan" causes an unhandled 500, not a 400
file: `app/core/backend/backend.py:3796-3821`, `app/core/db/repositories/inventory_repo.py:222-251`

```python
try:
    float(str(raw).strip())          # backend.py:3808 — float("nan") parses fine, no exception
except (TypeError, ValueError):
    return jsonify({"error": "new_quantity must be a valid number"}), 400
...
item = repo.set_inventory_item_quantity(UUID(item_id), org_id, str(raw).strip())   # :3814, only `except ValueError` at :3815
```
Inside the repo:
```python
target = _parse_quantity(new_quantity)      # inventory_repo.py:242 → Decimal("nan"), a valid Decimal, not None
if target is None or target < 0:            # :243 — Decimal("NaN") < 0 raises decimal.InvalidOperation
    raise ValueError(...)
```
Verified directly: `Decimal('NaN') < 0` raises `decimal.InvalidOperation`, which is **not** a `ValueError` subclass (`isinstance(InvalidOperation('x'), ValueError) == False`). The route's only exception handler is `except ValueError as e:` (backend.py:3815) — there is no catch-all in this route, unlike `create_inventory_item`/`update_inventory_item` which both have a trailing `except Exception:`. The exception propagates uncaught to Flask's default error handler: a non-JSON 500 response (breaking the API's JSON contract) and no `logger.exception` call, so this failure mode is invisible to the app's own structured logging/observability.

repro: `POST /api/core/inventory/<item_id>/adjust {"new_quantity": "nan"}` → 500 instead of 400.

fix: in `set_inventory_item_quantity` (inventory_repo.py:242-244), explicitly reject non-finite Decimals before comparing:
```python
target = _parse_quantity(new_quantity)
if target is None or not target.is_finite() or target < 0:
    raise ValueError("new_quantity must be a non-negative finite number")
```
`is_finite()` returns False for both NaN and Infinity and is checked before any ordering comparison, so it never reaches the `InvalidOperation`-raising path.
rule_added: none this run (single-file fix); recommend a `.semgrep/rules/learned.yml` rule flagging `Decimal(...) < `/`> `/`==` comparisons not preceded by an `is_finite()`/`is_nan()` guard in `app/core/**` — this is the second instance of the same root cause (see F3).

### F3 [MEDIUM] Huge-exponent quantities (`"1e400"`) raise `decimal.InvalidOperation` inside `coerce_stored_quantity`, degrading create/update to a generic 500
files: `app/core/utils/inventory_quantity.py:12-25`, consumed by `app/core/backend/backend.py:3491` (`create_inventory_item`) and `:3683` (`update_inventory_item`) via `InventoryRepository`

```python
def coerce_stored_quantity(value: object) -> Decimal:
    ...
    try:
        d = Decimal(str(value).strip())            # :20 — Decimal("1e400") parses fine, finite
    except (InvalidOperation, ValueError, TypeError) as e:
        raise ValueError(f"Invalid quantity: {value!r}") from e
    if not d.is_finite():
        return d.quantize(...)                      # unreachable comment aside — is_finite() is True for 1e400
    ...
    return d.quantize(STORAGE_QUANTIZE_EXP, rounding=ROUND_HALF_UP)   # :25 — raises InvalidOperation, NOT wrapped
```
Verified: `Decimal('1e400').quantize(Decimal('0.0001'))` raises `decimal.InvalidOperation` because representing 10^400 to 4 decimal places needs ~404 significant digits, exceeding the default context precision (28). This quantize call sits outside the `try/except` that wraps only the initial `Decimal(str(value))` parse.

Route-level impact differs from F2 because both `create_inventory_item` and `update_inventory_item` do have a trailing `except Exception:` (backend.py, end of each function) that catches this and logs+returns a generic 500 — so it doesn't crash unobserved like F2, but it's still the wrong status code (400 is correct for bad client input) and the generic exception message obscures the real cause in the log line (`"Error creating process"` / `"Error updating inventory item"` — note the copy-pasted wrong message in `create_inventory_item`'s except clause, a separate minor bug).

Note: `create_inventory_item`'s own pre-check (`float(quantity) <= 0`, backend.py:~3505) does not catch this either — `float("1e400")` silently returns `inf` in Python (no exception), which passes the `> 0` check, while the *actual* value written through is `str(quantity)` (the original un-normalized string), so the float pre-check and the stored value diverge.

fix: fold the `quantize()` call into the existing try/except in `coerce_stored_quantity` (inventory_quantity.py:19-25):
```python
try:
    d = Decimal(str(value).strip())
    if not d.is_finite():
        raise ValueError("Quantity must be finite")
    return d.quantize(STORAGE_QUANTIZE_EXP, rounding=ROUND_HALF_UP)
except (InvalidOperation, ValueError, TypeError) as e:
    raise ValueError(f"Invalid quantity: {value!r}") from e
```
This is the single shared choke point for create/update/adjust/repo callers, so one fix closes the sibling everywhere.
rule_added: none this run (see F2 — one learned-rule proposal covers both).

### F4 [MEDIUM, confirmed] `list_inventory_items` process_id filter has no `Execution.org_id` constraint
file: `app/core/db/repositories/inventory_repo.py:323-337`, reachable via `GET /api/core/inventory?process_id=...` (`backend.py:2603`)

```python
def list_inventory_items(self, org_id, inventory_type=None, process_id=None):
    query = self.db.query(InventoryItem).filter(InventoryItem.org_id == org_id)   # :327 — base query correctly scoped
    ...
    if process_id:
        tagged_pid = InventoryItem.extra_data["producing_process_id"].astext == str(process_id)
        query = query.outerjoin(Execution, InventoryItem.source_execution_id == Execution.id).filter(
            or_(Execution.process_id == process_id, tagged_pid)               # :334-336 — no Execution.org_id == org_id
        )
    return query.order_by(...).all()
```
Confirmed as a real gap — `get_untracked_items` in the same file (`:312-317`) does the correctly-scoped equivalent: `.outerjoin(Execution, ...).filter(Execution.org_id == org_id, or_(...))`.

Impact assessment (falsifying the worst-case reading): the base `FROM InventoryItem` is still `org_id`-scoped (line 327), and only `InventoryItem` columns are selected/returned — so this does not, by itself, return another org's *rows*. Combined with F1's FK-poisoning primitive, though, it means an org's own filtered inventory view (`?process_id=X`) can be polluted by matching against a different org's `Execution.process_id`, i.e. the WHERE-clause boundary leaks across tenants even though the SELECT boundary doesn't. Fix regardless — it's the same class of bug as F1 and should not diverge from its own sibling method.

fix: add `Execution.org_id == org_id` to the join filter, matching `get_untracked_items`:
```python
query = query.outerjoin(Execution, InventoryItem.source_execution_id == Execution.id).filter(
    or_(and_(Execution.org_id == org_id, Execution.process_id == process_id), tagged_pid)
)
```
rule_added: none — recommend a learned semgrep rule for `outerjoin(Execution, ...)` / `join(Execution, ...)` without a paired `Execution.org_id == org_id` filter in `app/core/db/repositories/**`, since this is now the second occurrence of exactly this omission pattern in one file.

### F5 [LOW] CSV raw-body upload path has no CSV-specific size limit; relies on an unrelated global cap
file: `app/core/backend/inventory_upload_routes.py:148-181`

```python
CSV_MAX_BYTES = 2 * 1024 * 1024   # :30 — documented/intended limit
...
file = request.files.get("file")
raw = request.get_data(as_text=True) if not file else None   # :169 — reads entire body before any size check
if file:
    content = file.read()
    if len(content) > CSV_MAX_BYTES:                          # :172 — multipart path checked
        return jsonify({"error": "File too large. Maximum size is 2MB."}), 400
    ...
elif raw is not None:
    text = raw                                                # :179 — raw-body path: NO CSV_MAX_BYTES check at all
```
Confirmed: Flask's `app.config['MAX_CONTENT_LENGTH']` **is** set globally (`app/api/app_factory.py:50-51`), so the raw-body branch is not literally unbounded — Werkzeug rejects any request body over that cap with a 413 before `request.get_data()` returns. But that cap is `config.evidence_max_file_size_mb` (default 10MB, `app/utils/config_loader.py:393-395`), a value owned by evidence-upload config, coincidentally reused here. The raw-body CSV path can therefore accept up to 10MB (5x the documented 2MB `CSV_MAX_BYTES`) with a full 500-row cap still enforced downstream but the size-per-row/field not bounded until `_sanitize()` truncates names to 255 chars — quantity/unit fields are parsed via `Decimal`/dict lookups with no explicit length cap before that. Given the 10MB global ceiling this is bounded, not an unbounded-DoS finding, but the coupling is accidental (an unrelated config bump for evidence uploads silently changes CSV's effective limit) and violates the endpoint's own documented contract ("File: max 2MB", docstring at `:154`).

fix: check `len(raw.encode("utf-8"))` (or `request.content_length`) against `CSV_MAX_BYTES` explicitly in the `elif raw is not None:` branch (line 178-179), same as the multipart branch, instead of relying on the shared global `MAX_CONTENT_LENGTH`.
rule_added: none (single-file, low severity).

## Attempted but clean

- **`EntityEventSummary` lookup in `list_inventory`** (`backend.py:2679`): filters only on `entity_id` (the table's primary key, `entity_event_summaries.entity_id`, model at `app/core/db/models/entity_event_summary.py:23`), not `org_id`. Traced the call site: `item_ids_all` (`:2676`) is built from `items`, which come from `InventoryRepository.list_inventory_items`'s already-`org_id`-scoped query. Since `entity_id` is the summary table's PK (1:1 with the item), this cannot return another org's row for an org-scoped id set. Not exploitable as-is. Recommend adding `EntityEventSummary.org_id == org_id` anyway as defense-in-depth (matches the project's own stated pattern of scoping even where the join makes it redundant), and because `_hydrate_step_data`'s docstring explicitly calls this pattern out as intentional practice elsewhere in this file.
- **`inventory_quantity_guard` regex heuristic** (`inventory_quantity_guard.py:57-70`): confirmed the regex misses schema-qualified (`public.inventory_items`) and quoted (`"inventory_items"`) identifiers in raw `text()` SQL. Traced the consequence: the DB trigger installed in `migrations/versions/inv_qty_pg_guard_001.py` defaults to **deny** (`coalesce(current_setting('app.inventory_qty_guard', true), '0') = '1'` — unset/NULL coalesces to `'0'`, i.e. rejected). A regex miss means the app fails to *proactively authorize* such a statement, so the trigger would reject even a legitimately-authorized raw write using those spellings — this fails **closed** (breaks functionality) not open (bypasses security). Not exploitable for unauthorized writes. Confirmed no bulk `Query.update()` or raw-SQL inventory-write path exists anywhere in the scoped files (grepped all `InventoryItem`-touching queries in `backend.py`/`inventory_repo.py`/`reconciliation_service.py`; every one is a plain SELECT with explicit `org_id` filters, or goes through the guarded ORM attribute-assignment path). Not re-raised as a security finding; worth a follow-up ticket for the regex's coverage gap purely as a reliability item if raw SQL against this table is ever introduced.
- **Unicode digit inputs** (`"١٢٣"` etc.): both `float()` and `Decimal()` parse Arabic-Indic digits identically (`123`/`123.5`) — no divergence between the validation-gate parse and the storage parse, so no smuggling vector there.
- **Wastage quantity parsing** (`inventory_wastage_quantity.py:40-61`): properly rejects non-finite values via `d.is_finite()` (line 49) before any comparison, and bounds magnitude at `1e18` (line 59) — no `float()` in this path at all, unlike the create/update/adjust routes. This is the correct pattern the other three should be brought in line with.
- **`record_wastage` error-detail leak** (`backend.py:3361`, `if not config.is_production:`): `config.is_production` (`app/utils/config_loader.py:153-155`) correctly checks `environment == "production"`; `ENVIRONMENT` is unset locally (resolves to `local` per `config_loader.py:16`) — behaves as intended, detail is only exposed outside production.
- **`reconcile_via_execution`** (`reconciliation_routes.py:110-168` → `reconciliation_service.py:500-682`): client-supplied `process_id`/`step_id` are validated against the org before use — `ExecutionRepository.create_execution` (`execution_repo.py:73-76`) raises `ValueError` if `Process.id == process_id, Process.org_id == org_id` doesn't match, and `step_id` must match one of that (org-validated) process's own generated execution steps (`reconciliation_service.py:575-578`) or the call errors out. No cross-tenant execution/process creation possible here.
- **CSRF, secrets, SSRF**: no user-supplied URLs or `subprocess` calls in scope; all state-changing routes carry `@requires_auth` and go through the app's standard Flask-WTF/session-cookie CSRF path (nothing bypasses it in these files); no hardcoded secrets found by gitleaks or manual read.

VERDICT: findings-open

---
*Stage ran read-only (Sonnet 5, high, Herdr tab w6:t2). Report transcribed verbatim by the review-feature orchestrator, per `.agents/verification-chain.md` §5. Remediation applied by the orchestrator; see .agents/reports/inventory/review.md for per-finding disposition.*
