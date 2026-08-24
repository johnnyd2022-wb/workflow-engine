# SECURITY: traceability
date: 2026-08-09
verdict: findings-open
scanned: semgrep(0 findings, scoped to the 5 in-scope files), gitleaks(0), uv-audit(not run — no dependency change in this slice)
manual_checklist: 7/7 completed
invocation: chain stage (report only, no patching — per SKILL.md §5)

Scope: `GET /core/sourcemap`, `GET /api/core/inventory/trace/<raw_material_id>`,
`GET /api/core/inventory/trace-backward/<inventory_item_id>`, `GET /api/core/sourcemap/objects`,
`POST /api/core/sourcemap/trace` in `app/core/backend/backend.py`;
`app/core/backend/temporal_dag_tracer.py`; frontend `sourcemap.html`/`sourcemap.js`/`sourcemap.css`.
Out of scope per spec: entities/story/summary/activity endpoints, diff-humanization, `event_writer.py`
(activity-log slice) — not audited here even though `sourcemap_trace` calls `_human_summary` at its
own call site.

## Findings

- F1 [fix] `app/core/backend/backend.py:5726-5727` (calls into
  `app/core/backend/temporal_dag_tracer.py:121-134`) — Cross-tenant entity-state leak via
  `POST /api/core/sourcemap/trace` temporal branch.
  verdict: **CONFIRMED** (independent read of both files, not just the candidate description).
  repro/evidence: `sourcemap_trace()`'s `as_of`-present branch builds `TemporalDAGTracer(db, org_id, as_of, ...)`
  and calls `tracer.trace(root_id, root_type)` with no prior check that `root_id` belongs to `org_id`.
  Contrast with the `as_of`-absent branch three lines below the temporal one exits at (`backend.py:5766`):
  `db.query(InventoryItem).filter(InventoryItem.id == root_id, InventoryItem.org_id == org_id).first()`,
  which 404s before touching any state. The temporal branch has no equivalent gate. Inside `trace()`,
  `_snapshot_at()` (`temporal_dag_tracer.py:121-134`) is:
  ```python
  ev = (
      self.db.query(EntityEvent)
      .filter(EntityEvent.entity_id == entity_id, EntityEvent.created_at <= self.as_of)
      .order_by(EntityEvent.created_at.desc())
      .limit(1)
      .first()
  )
  return ev.payload if ev else None
  ```
  No `org_id` filter at all. Any authenticated user of any org, given another org's `InventoryItem`
  (or `Execution`) UUID and any `as_of` timestamp, gets that entity's latest event payload
  (name, quantity, supplier, batch number, etc. — whatever `EntityEvent.payload` carries) back as
  `root.state` in the JSON response. `edges` (line 46-55, filtered on `EntityEvent.org_id ==
  self.org_id`) and `timeline`/`_build_timeline()` (line 159-169, same org filter) are correctly
  scoped — this is a single-field leak isolated to the root snapshot, not a whole-graph leak, but it
  is a direct, unauthenticated-within-session cross-tenant data disclosure: no error, no 404, 200 with
  another tenant's data.
  patch: not applied (chain-stage grader; see invocation note above). Recommended fix: before calling
  `tracer.trace()`, resolve `root_id` against the caller's org the same way the `as_of`-absent branch
  does (a query against whichever table `root_type` implies, scoped by `org_id`, 404 on miss) — or,
  more robustly, filter `_snapshot_at()`'s query by `EntityEvent.org_id == self.org_id` directly,
  which also closes the hole for any other future caller of `TemporalDAGTracer` that forgets the
  pre-check. Both belong together: the route-level check is the fast-fail (404 before any tracer work
  happens at all), the tracer-level filter is defense-in-depth matching the pattern already used
  elsewhere in this codebase (`dagtraversal.py`'s `_enrich_items_bulk`/`add_step_order_connections`,
  which re-scope by `org_id` on every FK hop even though the base rows were already org-filtered).
  rule_added: none (route this to `fix-bug` per SKILL.md §5 — tenant isolation / data leak class needs
  a red-then-green repro test first: "org A's session, org B's InventoryItem UUID as root_id, as_of set
  → 404, not 200 with org B's data").
  Already fixed by commit `7c32b89`: `TemporalDAGTracer` now filters all three
  `EntityEvent` queries (`trace`'s step_events, `_snapshot_at`, `_build_timeline`) by
  `EntityEvent.org_id == self.org_id` — `_snapshot_at` previously had no org filter at
  all, now does (verified 2026-08-25 by findings-sweep).

- F2 [fix] `app/core/backend/backend.py:5771-5786` — `POST /api/core/sourcemap/trace`'s current-state
  (no `as_of`) branch is dead code that always 500s.
  verdict: **CONFIRMED**. `from app.features.workflow_engine.dagtraversal import trace_backward,
  trace_forward` — confirmed by `find app -iname dagtraversal.py`: the only such module in the repo is
  `app/core/backend/dagtraversal.py`; no `app/features/workflow_engine/` package exists at all
  (`find app/features/workflow_engine` returns nothing). Every call into this branch raises
  `ModuleNotFoundError` inside the `try` at line 5770, caught by the bare `except Exception:` at
  line ~5786, returning `{"error": "Trace failed"}, 500`. Independent of the import, the call itself
  is also wrong against the real module: it calls `trace_forward(str(root_id), db, org_id=str(org_id))`
  (line 5773) and reads `result_fwd.nodes` / `.edges` as object attributes, but the real
  `app.core.backend.dagtraversal.trace_forward(org_id, session, item_id, ...)` takes `org_id` as the
  first positional arg (not a keyword) and returns a plain dict with `["items"]`/`["connections"]` keys,
  not an object with `.nodes`/`.edges`. Fixing only the import path would still crash on the signature
  mismatch.
  Reachability: confirmed not currently reachable from the SPA. `sourcemap.js`'s only caller of this
  route is `smRunTemporalTrace()` (line 680-695), invoked only from `smTraceItem()` at line 661-662
  guarded by `if (temporalAsOf)`, and `temporalAsOf` is only ever set to a non-empty ISO string
  (`v + 'T23:59:59Z'`, line 1958) or reset to `''` (lines 785, 1968) — so the frontend can never fire this
  route without `as_of`. It is still a live, `@requires_auth`-only route with no other gate; any
  authenticated user who calls it directly (curl, Postman, browser devtools) without `as_of` gets a
  500 on every request, not the "trace it now" response the endpoint's own docstring and route name
  promise. Severity is availability/correctness (broken documented functionality, unhandled exception
  path, generic 500 swallowing whatever the real error is), not data exposure.
  patch: not applied (chain-stage grader). Recommended fix: replace the import with
  `from app.core.backend.dagtraversal import trace_backward, trace_forward` and adapt the call to the
  real signature/return shape (`trace_forward(org_id, db, root_id)` → dict with `["items"]`/`["connections"]`),
  matching how `trace_raw_material`/`trace_inventory_backward` already call it earlier in this same file.
  rule_added: none — one-off broken import/signature mismatch, not a mechanically generalizable class;
  a semgrep rule for "import from a module path that doesn't resolve" is not something semgrep's AST
  matching does (that's what `ruff`/import linting already catches — worth checking why CI didn't flag
  this; see note below).
  Already fixed by commit `7c32b89`: `backend.py`'s current-state branch now imports
  from the real `app.core.backend.dagtraversal` module and calls `trace_forward`/
  `trace_backward` with the real signature and dict return shape (verified 2026-08-25
  by findings-sweep).

- F3 [fix] `app/core/backend/backend.py:5606-5607` — `GET /api/core/sourcemap/objects` 500s on
  non-numeric `page`/`limit`.
  verdict: **CONFIRMED**.
  ```python
  page = max(1, int(request.args.get("page", 1)))
  limit = min(int(request.args.get("limit", 50)), 200)
  ```
  No `try/except` around either `int()` call. `GET /api/core/sourcemap/objects?page=abc` (or `?limit=abc`)
  raises `ValueError`, uncaught anywhere in this handler, unhandled 500. In `local`/`test`
  (`app/config/local.ini:3`, `app/config/test.ini:3`: `debug = true`) this renders Werkzeug's
  interactive debugger — a stack trace including source snippets — to whoever sent the request; in
  `prod` (`app/config/prod.ini:3`: `debug = false`) it's a generic 500 without the trace, but still an
  unhandled exception on ordinary malformed input from any authenticated user, not a 400.
  patch: not applied (chain-stage grader). Recommended fix: parse defensively, e.g.
  `try: page = max(1, int(request.args.get("page", 1))) except (TypeError, ValueError): return
  jsonify({"error": "Invalid page"}), 400` (same for `limit`).
  rule_added: recommend a `learned.yml` rule for "`int(request.args.get(...))` / `int(request.get_json()...)`
  with no enclosing try/except" — this is the second instance of the exact same class in this one
  route file (see F4), which is exactly the "mechanically recognizable, write the rule" trigger in
  SKILL.md §3. Not added from this stage (read-only); recommend to whichever skill picks up F3/F4's fix.
  Already fixed: `backend.py:5750-5753` now wraps both `int()` parses in
  `try/except (TypeError, ValueError)`, returning 400 (verified 2026-08-25 by
  findings-sweep).

- F4 [fix] `app/core/backend/backend.py:5704` — `POST /api/core/sourcemap/trace` 500s on non-numeric
  `depth`. **Not one of the two candidate findings — found during independent review of the same
  route.**
  verdict: **CONFIRMED**, same bug class as F3, different call site.
  `depth = min(int(data.get("depth", 5)), 10)` runs before the `root_id`
  presence/UUID checks (lines 5706-5710) and is not wrapped in any try/except. A request body of
  `{"root_id": "<valid-uuid>", "depth": "abc"}` raises `ValueError` on this line, before either the
  `root_id`-required check or the `UUID(root_id_str)` try/except get a chance to run — i.e. a client
  cannot even reach the 400 path AC11 documents by sending a bad `depth` alongside a fine `root_id`.
  Unhandled → 500 (interactive debugger in local/test, generic in prod, per F3's reasoning).
  patch: not applied (chain-stage grader). Recommended fix: same defensive-parse pattern as F3, applied
  to `depth` before the `root_id` checks, or move it after them and wrap in try/except returning
  `{"error": "Invalid depth"}, 400`.
  rule_added: see F3 — same learned-rule candidate covers this call site too (would fire on both).

## Attempted but clean

- **Auth on every route**: all 5 routes (`sourcemap` page, `trace_raw_material`,
  `trace_inventory_backward`, `sourcemap_objects`, `sourcemap_trace`) carry `@requires_auth`
  (verified by direct grep against `backend.py`, not by name — read each decorator line).
- **Tenant isolation, forward/backward trace (AC1-AC8)**: `trace_raw_material` and
  `trace_inventory_backward` both resolve the root item via `InventoryItem.id == <id>, InventoryItem.org_id
  == org_id` before calling `trace_forward`/`trace_backward`, returning 404 (not 403) on a miss —
  cross-org existence is not distinguishable from non-existence. `DAGTracer.traverse()`
  (`dagtraversal.py:296-360`) re-scopes every bulk query (`InventoryItem`, `ExecutionStep` joined
  through `Execution`) by `self.org_id`, including the backward-direction bulk load and the final
  enrichment pass (`_enrich_items_bulk`, `add_step_order_connections`) — both of the latter re-check
  `org_id` on every FK hop (`source_execution_step_id`, `source_execution_id`, `process_id`) even
  though the base item rows were already org-filtered, with an explicit comment explaining why
  (defense against a write-side bug ever letting a foreign FK slip through). `_hydrate_step_data`
  (`backend.py:504-546`) does the same for `step_data` hydration. This is the one part of the slice
  that reads as deliberately hardened, not merely correct by accident.
  Only exception found: F1 above (the temporal branch, a materially different code path).
- **`TemporalDAGTracer` edges/timeline (AC14, AC16)**: `trace()`'s edge-building query
  (`temporal_dag_tracer.py:46-55`) and `_build_timeline()` (`:159-169`) both filter
  `EntityEvent.org_id == self.org_id` correctly. Only `_snapshot_at()` (the root node's `state`) omits
  it — confirmed this is a single-method gap, not a whole-class failure of the tracer.
  - BFS termination (AC15): `connected` is a `set`; loop at `:94-103` stops when `new_conn - connected`
    is empty, and is additionally bounded by `self.max_depth` (itself clamped to 10 in `__init__`,
    line 31) — a cyclic graph cannot loop forever even before the depth cap.
- **Depth/max_depth clamping (AC12)**: `min(int(data.get("depth", 5)), 10)` at the route and
  `min(max_depth, 10)` in `TemporalDAGTracer.__init__` (`:31`) both clamp to 10 — confirmed a
  client-requested `depth: 9999` cannot expand the query beyond that cap (mechanism is sound; only its
  input-parsing robustness is the problem, see F4).
- **Mass assignment**: no route in scope constructs a model from raw request JSON; all writes in this
  slice are read-only traces (no POST/PUT that persists request data to `InventoryItem`/`Execution`/etc.).
- **Injection**: all queries are SQLAlchemy ORM with bound filters; `sourcemap_objects`' `.ilike(f"%{q}%")`
  interpolates into the LIKE pattern string but is passed as a bound parameter by SQLAlchemy, not
  concatenated into raw SQL — not injectable. No raw SQL, no `subprocess`, no file-path handling
  anywhere in this slice.
- **XSS (AC24)**: checked every `innerHTML`/`insertAdjacentHTML` assignment in `sourcemap.js` that
  touches server-supplied strings (item name, supplier, batch, process name, event summary, actor,
  timeline text) — all pass through `smEsc()` first, each with a `// nosemgrep: ... -- audited` comment
  next to it. Spot-checked the temporal-trace renderer specifically (`smRenderTemporalTrace`,
  lines 699-778, the newest/least-reviewed rendering path) since it's the one most likely to have been
  added without the same care as the older forward/backward rendering code — same pattern holds there
  too (`smEsc(s.name || node.id)`, `smEsc(ev.summary || ev.event_type)`, `smEsc(ev.actor)`, etc.).
  No un-escaped interpolation found.
- **CSRF**: `POST /api/core/sourcemap/trace` is not in the app-wide CSRF exemption list
  (`app_factory.py:387-389`, which only exempts `auth.*` and the two telemetry-ingest endpoints) — it
  gets standard Flask-WTF protection like every other mutating-verb route in the app. Not a
  slice-specific concern; verified rather than assumed.
- **Secrets**: gitleaks scoped scan (`backend.py`, `temporal_dag_tracer.py`, `dagtraversal.py`,
  `sourcemap.js`, `sourcemap.html`) — 0 findings.
- **Semgrep**: `p/flask` + `p/owasp-top-ten` + `.semgrep/` custom rules against the same 5 files —
  0 findings (247 rules run). Expected: both real findings here are tenant-isolation/logic bugs, the
  exact class semgrep's pattern matching does not reach.
- **uv audit**: not run — this slice made no dependency changes, and CI's `uv_audit` job already gates
  the tree independently of this review (per project memory: pip_audit/uv_audit CVE findings route to
  `dependency-update`, not this audit).

## Not verified

- Live exploitation of F1 against the running app server (`https://localhost:8005/`) was not performed
  in this pass — confirmation is from independent static reading of both the route and
  `_snapshot_at()`'s query, cross-checked against the org-scoped sibling query it should mirror. The
  code path is unambiguous (no `org_id` predicate exists on that query at all), so static confirmation
  is treated as sufficient; a live two-org repro is exactly the red-then-green test `fix-bug` should
  write before patching (see F1's routing note).
- `EntityEvent.payload`'s actual field contents (to enumerate precisely what F1 discloses beyond "name,
  quantity, supplier" — the payload shape is defined by the event-sourcing/activity-log slice, out of
  scope here per this review's non-goals).

## Recommended routing (SKILL.md §5 — this stage does not open MRs itself)

- F1 → **fix-bug**, flagged security/tenant-isolation. Needs a red-then-green two-org repro test first.
- F2 → **fix-bug** (or fixed inline as part of the same MR as F1, since both are in `sourcemap_trace`) —
  correctness/availability, not data exposure; lower urgency than F1 but should not ship a permanently
  broken documented code path.
- F3, F4 → small, scoped, mechanical input-validation fixes; low risk to bundle into the same MR as
  F1/F2 since all four live in the same handful of route functions in `backend.py`. Recommend one rule
  candidate (`learned.yml`) covering the shared `int(request.<args|json>.get(...))`-without-try/except
  pattern, since it now has two independent instances (F3, F4) in this slice alone.
