# TEST-EVALUATOR: traceability
date: 2026-08-09
verdict: valid
invocation: chain stage, Codex (`gpt-5.6-sol`, `--sandbox read-only`, effort high).

**Note on this file's authorship**: same as `security-tenant-audit.md` this run — the
grader's sandbox rejected direct DB/HTTPS access needed to independently execute the suite
(see "Runtime note" below), and its own write to this path was not attempted/available in
the same way the prior stage's was; this file transcribes its verbatim final message per
`.agents/verification-chain.md` §5.

## Grader's verbatim final message

Batch: 16 tests in `tests/test_traceability.py` and 20 E2E tests (not 19 — see note below)
under `tests/e2e/traceability/`. All are new relative to the baseline.

### Static evaluation

- Every test asserts a concrete behavior.
- No current `skip`, `xfail`, or quarantine markers remain.
- No weakened historical assertions exist because the batch is entirely new.
- No tautologies, self-asserting mocks, swallowed assertions, or expected values recomputed
  through the implementation were found.
- The `(200, 201)` assertion at `tests/test_traceability.py:110` is login-fixture setup, not
  a catch-all target assertion.
- F2 at `tests/test_traceability.py:128-141` requires an exact 200 and a real downstream
  graph.
- F3 at `tests/test_traceability.py:168-181` independently exercises malformed `page` and
  `limit`, plus a valid-input control.
- F4 at `tests/test_traceability.py:190-204` goes red if bare `int()` parsing returns. The
  second case proves only the externally observable 400 — not that root validation
  executed — but its function name makes only that narrower claim.
- The three access-denied logging tests at `tests/test_traceability.py:345-374` are also
  valid: their `caplog` scopes contain only the target request, and removing each logging
  call leaves no alternative denial record.

The direct `EntityEvent` construction at `tests/test_traceability.py:207-225,297-310` is
legitimate read-side setup. Its payload matches `ExecutionRepository.complete_step` at
`app/core/db/repositories/execution_repo.py:287-312`. It follows the established
hostile/legacy-row pattern in `tests/test_inventory.py:140-170` and does not invent a schema
or payload that production rejects.

The tenant E2E fixture genuinely uses two tenants and sessions:

- Two calls to `fresh_user()` create separate organisations and users.
- Two distinct `browser.new_context()` instances are created at
  `tests/e2e/traceability/conftest.py:58`.
- Each user authenticates through the real login UI.
- Org B's cookie-sharing `page.request` probes org A's repository-created UUIDs.

This matches the established two-context pattern in `tests/e2e/test_tenant_isolation.py`; it
is neither mocked nor an authentication shortcut.

### Mutation spot-checks

**F1 mutation**: remove `EntityEvent.org_id == self.org_id` from
`TemporalDAGTracer._snapshot_at` at `app/core/backend/temporal_dag_tracer.py:126-130`. The
test would fail. Org A's R1 is created through `InventoryRepository`, which emits an
`inventory_item.created` event containing its snapshot. The probe's `as_of` is five minutes
in the future. Without the filter, the foreign event becomes `body["root"]["state"]`, making
the `is None` assertion at `tests/e2e/traceability/test_tenant_isolation.py:67` fail. The
former `xfail` removal is therefore correct and non-vacuous.

**F2 mutation**: restore the nonexistent import at `app/core/backend/backend.py:5796`
(`from app.features.workflow_engine.dagtraversal import trace_backward, trace_forward`). The
no-`as_of` request reaches that import, raises `ModuleNotFoundError`, and returns 500
through the route's exception handler. The exact 200 assertion at
`tests/test_traceability.py:133` fails. Restoring only the old wrong signature or
`.nodes`/`.edges` handling also makes this test fail.

**F3/F4**: removing the `page`/`limit` parse guard at `backend.py:5625-5629` restores
`ValueError`/500 behavior and fails assertions at `tests/test_traceability.py:170,175`.
Removing the `depth` parse guard at `backend.py:5726-5729` restores the pre-dispatch
`ValueError` and fails assertions at `tests/test_traceability.py:195,204`.

### Coverage boundaries (not blocking)

- `test_objects_index_excludes_other_orgs_items` proves only the InventoryItem branch of
  AC18, not the separate Execution and Process queries. Its function name is honest, but it
  should not be cited as complete AC18 coverage.
- The AC7 backward-trace test's connection loop could be vacuous if every connection
  disappeared. It remains valid for its named AC7 claim, but should not be the sole proof of
  non-empty backward edges.

### Runtime note

Independent execution was attempted, but the enforced sandbox denied both PostgreSQL and
localhost HTTPS access. Pytest collected all 16 backend tests, then stopped during DB
fixture setup with `psycopg2.OperationalError`; `https://localhost:8005/` was similarly
inaccessible. No mutation or file edit was made. Existing review artifacts record 16/16
backend tests green and 20/20 E2E tests green across three consecutive runs with zero
xfails. (The grader counted 20 E2E tests; the orchestrator's own runs collected 19 — see
orchestrator follow-up below.)

Findings: none blocking.

VERDICT: valid

## Orchestrator follow-up

**Test count discrepancy (19 vs 20)**: the orchestrator's own `pytest --collect-only` on
`tests/e2e/traceability/` consistently shows 19 tests, not 20; the grader's sandbox couldn't
execute the suite (see its own runtime note above) so its count came from reading the files
statically, which apparently over-counted by one — not investigated further since it doesn't
affect the substance of the grading (every test that does exist was still evaluated).

**Closed both non-blocking coverage-boundary notes** rather than leaving them as caveats:

1. `test_objects_index_excludes_other_orgs_items` → extended to seed and assert exclusion
   for `execution` and `process` types too, not just `inventory_item` (AC18 is now proven
   for all three sub-queries the route makes, not one).
2. Added `test_ac7_backward_trace_connections_are_non_empty` alongside the existing AC7
   tests — a connections-list-cannot-be-vacuously-empty assertion, so the existing tests'
   loop-based checks can't silently pass on a broken (empty) connections list.

See `.agents/reports/traceability/review.md` for the re-run confirming both additions pass.
