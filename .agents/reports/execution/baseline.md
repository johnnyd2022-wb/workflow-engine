# BASELINE: execution
date: 2026-08-02
branch: review/execution (isolated worktree, cut fresh from origin/main)

## Working tree
`git status` clean at audit start.

## Suite
```
uv run pytest tests/ -q
748 passed, 30 skipped in 311.23s
```

Green. The 30 skips are the `live_server` 2FA suites, expected per preflight
(`decisions.live_server_tests: skip` — no app server listening on :8005). No
pre-existing failures, so every finding this audit raises is attributable to the
execution surface, not to inherited noise.

Scoped subset also run in isolation for a faster signal:
```
uv run pytest tests/test_executions.py tests/test_dag_traversal.py \
  tests/test_complete_step_payload.py tests/test_batches_refactor_frontend_guards.py \
  tests/test_execution_modal_frontend_assets.py tests/test_execution_shared_utils_js.py -v
129 passed
uv run pytest tests/e2e/test_workflow_flow.py -v
6 passed
```

## Scope under audit
Routes:
- `/core/flows`, `/core/flows/executions/step`, `/core/flows/batches/start`, `/core/executions/live`
- `/api/core/executions` [GET, POST], `/api/core/executions/<id>` [GET], `/api/core/executions/<id>/with-process`
- `/api/core/executions/<id>/steps/<sid>/complete` [POST] — `complete_step`, backend.py:1992-2605
- `/api/core/execution-metadata`
- `/api/core/evidence/*` (config, upload, `<id>/download`, list, DELETE)

Backend:
- `app/core/backend/backend.py:1701-2605` (executions API; `complete_step` is the
  615-line highest-risk function in the app per the feature index)
- `app/core/backend/backend.py:4016-4099` (execution metadata)
- `app/core/backend/dagtraversal.py` (874 lines)
- `app/core/backend/complete_step_payload.py` (95 lines)
- `app/core/backend/evidence/` (routes, service, validation, storage)
- `app/core/db/repositories/execution_repo.py` — `complete_step`, `_advance_execution`

Models: `Execution`, `ExecutionStep`, `ExecutionEvidence`, `ApiIdempotencyKey`

No spec existed at `.agents/specs/execution.md` prior to this audit — reconstructed
per Step 2 (`status: reconstructed`).
