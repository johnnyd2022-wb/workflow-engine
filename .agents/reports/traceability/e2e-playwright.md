# E2E: traceability (sourcemap)

Gap-fill: no E2E coverage existed for this slice before this run (`tests/e2e/traceability/`
did not exist; `scripts/e2e_coverage.py --json` showed all five sourcemap/trace routes as
gaps). New suite: `tests/e2e/traceability/` (4 test files + `conftest.py`), 20 tests.

Note on that coverage-gap report: re-running `scripts/e2e_coverage.py --json` after writing
this suite *still* lists all five routes as gaps. That's a pre-existing blind spot in the
script, not a real gap — `tested_paths()` (`scripts/e2e_coverage.py:120`) globs
`E2E_DIR.glob("test_*.py")` non-recursively, so it never looks inside `tests/e2e/<slug>/`
subdirectories at all. `tests/e2e/reconciliation/` (the only other subdirectory) has the
same blind spot — confirmed by diffing its own route list against the gap report. Actual
pytest collection is unaffected (it's recursive by default): all 20 tests here were
collected and ran normally. Flagging this because **ci-gate** may wire `--check` as a
blocking gate and would otherwise treat this suite as if it doesn't exist; not fixed here
since `scripts/e2e_coverage.py` is outside this stage's named write scope
(`tests/e2e/traceability/**` and this report only).

Fixtures seed a real `R1 -> W1 -> F1` production chain via
`tests/dag_traversal_helpers.build_linear_dag` — the same repository code path the app
uses (`InventoryRepository`, `ExecutionRepository`), not a mock — rather than re-driving
the multi-step execution UI, which is already proven end to end by
`tests/e2e/test_workflow_flow.py` / `tests/e2e/test_execution_flow.py`. `fresh_user()`'s
existing teardown purges every row this creates.

## Coverage

| AC | Test | Result |
|---|---|---|
| AC21 (page loads, requires auth, controls hidden pre-trace) | `test_sourcemap_page.py::test_ac21_sourcemap_page_loads` | pass |
| AC3 (forward trace from browse grid renders timeline; raw material itself in impact header) | `test_sourcemap_page.py::test_ac3_forward_trace_from_browse_grid_renders_timeline` | pass |
| view-switch reuses cached trace, no refetch | `test_sourcemap_page.py::test_view_switch_renders_map_and_table_without_refetching_trace` | pass |
| wastage toggle fetches only `/inventory/wastage`, never refetches the trace | `test_sourcemap_page.py::test_wastage_toggle_does_not_refetch_trace` | pass |
| AC7 (backward trace: traced item itself in `all_items`/`traced_item`) + AC8 (source lists exclude it; connections only reference response ids) | `test_backward_trace.py::test_ac7_backward_trace_api_includes_traced_item_in_all_items` | pass |
| AC7 via UI (Table view shows both W1 and its source R1) | `test_backward_trace.py::test_ac7_backward_trace_from_wip_card_shows_traced_item_in_table` | pass |
| AC7 rooted at a final product (not just WIP) | `test_backward_trace.py::test_backward_trace_from_final_item_includes_traced_item_itself` | pass |
| AC2 (forward trace: cross-tenant id 404s indistinguishably from nonexistent) | `test_tenant_isolation.py::test_ac2_forward_trace_cross_tenant_existence_not_distinguishable` | pass |
| AC6 (backward trace: same, WIP item) | `test_tenant_isolation.py::test_ac6_backward_trace_cross_tenant_returns_404` | pass |
| AC6 (same, final product item) | `test_tenant_isolation.py::test_ac6_backward_trace_cross_tenant_final_product_returns_404` | pass |
| AC9 (temporal trace root state must not leak cross-tenant) | `test_tenant_isolation.py::test_ac9_temporal_trace_root_state_not_visible_cross_tenant` | pass (was xfail — see below) |
| AC1 (forward trace: non-UUID -> 400, not 500) | `test_unhappy_paths.py::test_ac1_forward_trace_non_uuid_returns_400_not_500` | pass |
| AC6 (backward trace: non-UUID -> 400) | `test_unhappy_paths.py::test_ac6_backward_trace_non_uuid_returns_400_not_500` | pass |
| AC11 (`POST /api/core/sourcemap/trace`: non-UUID `root_id` -> 400, not 500 — the same route AC9's test uses, and the one the temporal-replay UI actually calls per AC23) | `test_unhappy_paths.py::test_ac11_sourcemap_trace_post_non_uuid_root_id_returns_400_not_500` | pass |
| AC10 (`POST /api/core/sourcemap/trace` without `as_of` returns a real graph, not a 500) | `test_sourcemap_page.py::test_ac10_sourcemap_trace_dispatch_without_as_of_returns_current_state_graph` | pass (was untestable — see below) |
| AC2 (forward trace: well-formed but nonexistent UUID -> 404) | `test_unhappy_paths.py::test_ac2_forward_trace_nonexistent_uuid_in_own_org_returns_404` | pass |
| AC6 (backward trace: same) | `test_unhappy_paths.py::test_ac6_backward_trace_nonexistent_uuid_in_own_org_returns_404` | pass |
| unhappy path: empty search restores full browse grid (typed-empty and clear-button routes) | `test_unhappy_paths.py::test_empty_search_shows_all_browse_cards_again` | pass |
| unhappy path: item with no trace history renders as a lone card, not a broken timeline | `test_unhappy_paths.py::test_item_with_no_trace_history_renders_as_lone_card` | pass |
| same, API response shape (`connections: []`, `all_items` = itself only) | `test_unhappy_paths.py::test_item_with_no_trace_history_api_response_shape` | pass |

Flake check: ran the full `tests/e2e/traceability` directory **3/3 times clean**
(20 passed, 0 xfailed, no intermittent failures — final state, after the AC9/AC10 update
below).

## AC9 and AC10: found as failing, now fixed and asserted for real

This stage's original pass ran alongside the parallel security-audit stage, which was
scoped to read `backend.py`/`temporal_dag_tracer.py` at the same time this stage was
writing tests — so this stage's first version of `test_ac9_...` asserted the *secure*
expected behavior (`root.state is None` for a cross-tenant id) but was marked
`xfail(strict=False, reason=...)`, documenting AC9's known leak
(`TemporalDAGTracer._snapshot_at` queried `EntityEvent` by `entity_id` alone, no `org_id`
filter) without touching the file. AC10 (`POST /api/core/sourcemap/trace` without `as_of`
importing a module that doesn't exist anywhere in the repo, `ModuleNotFoundError` → masked
500) was left out of that first pass entirely, as untestable-without-patching and not in
the task's named AC list.

Both files have since been patched (uncommitted working-tree changes, confirmed by reading
the diff): `temporal_dag_tracer.py:121-134`'s `_snapshot_at` now filters by
`EntityEvent.org_id == self.org_id`, matching the org-scoping every other query in that
tracer already had (see `.agents/reports/traceability/security-audit.md` F1). `backend.py`'s
`sourcemap_trace` now imports from the real `app.core.backend.dagtraversal` module and calls
`trace_forward`/`trace_backward` with the correct positional signature and dict return shape
(F2), plus defensive `int()` parsing for `page`/`limit`/`depth` (F3/F4). With the block
lifted, `test_ac9_...`'s `xfail` marker was removed (the test now passes for real, not as an
`XPASS`) and `test_ac10_...` was added as a straightforward green regression test — both now
genuinely exercise the fixed code paths rather than documenting an open gap.

## Deliberately out of scope for this stage

- **AC20** (`sourcemap/objects` `?page=`/`?limit=` non-numeric → unhandled 500 — also since
  fixed, per `security-audit.md` F3, but not tested here). Not named in the task brief and
  not part of the UI-reachable flows listed (browse/trace/toggle/view-switch/cross-tenant/
  unhappy-path); `sourcemap/objects` itself isn't called by the current frontend
  (`sourcemap.js` builds its browse grid from `getInventory`/`getProcesses`/
  `getExecutions`, not this endpoint) — unlike AC10, this one stays out of scope even
  though the block lifted, since the exclusion was never about the backend being off
  limits.
- Entities/story/summary/activity endpoints, diff-humanization UI — explicitly out of
  scope per the task brief (activity-log slice).
- AC4/AC5 (zero-quantity items included; `step_data` hydration/org-scoping),
  AC12-AC17 (temporal trace internals: depth clamp, BFS termination, timeline
  ordering/limit, non-root `state: None`), AC18/AC19 (`sourcemap/objects` org-scoping and
  type filter) — all API/traversal-internal correctness, not UI-reachable; own tests
  exist or belong at the unit/API layer (`tests/test_dag_traversal.py` and friends), not
  duplicated here per the skill's "never mark an AC covered by a test that doesn't
  genuinely exercise it" rule and the task's explicit UI-reachable framing. (AC11 *is*
  covered — see the table above; it was cheap to add since `test_ac9_...` already exercises
  the same `POST /api/core/sourcemap/trace` route.)

## Next step

Hand this suite to **ci-gate** so it becomes a required check — an E2E suite that only
runs when someone remembers is decoration. The `backend.py`/`temporal_dag_tracer.py`
working-tree changes referenced above are outside this stage's write scope (uncommitted;
presumably staged for the fix-bug/merge-request handoff `security-audit.md` recommends) —
this report only reads and tests against them, it does not commit or take credit for them.

VERDICT: clean
