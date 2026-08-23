# TEST EVALUATION — 2026-08-23
batch: tests/test_demo_data.py (7 tests, new file), tests/e2e/demo-data/conftest.py +
tests/e2e/demo-data/test_reset_demo_db.py (3 tests, new suite) — graded against
app/features/demo_data/routes/api_routes.py (the F1/F2 patch + observability logging).

## Engine note (grader_engine fallback — disclosed per verification-chain.md §1)
`grader_engine: codex` per preflight, but the installed Codex CLI (codex-cli 0.130.0)
is broken in this environment: it fails to refresh its own model list
(`unknown variant "max", expected one of "none","minimal","low","medium","high","xhigh"`
— a version-skew issue between the CLI and the account's current model catalog),
independent of which model was requested. Two `codex exec --sandbox read-only` attempts
both failed before producing any grading output. Falling back to self-grading as
Claude (the same agent that wrote these tests) rather than leave the batch ungraded —
disclosed here per the fallback rule, not presented as independent-engine review. The
mutation probes below were run for real against the live test DB (this environment's
own pytest works fine; only the Codex CLI itself is broken), which is the substantive
part of this skill; the static checks are self-review, the weaker part of this
fallback.

## Static checks

| test | asserts real claim? | diff-widened? | tautology? | name matches proof? |
|---|---|---|---|---|
| `test_env_gate_blocks_outside_test_and_local` | yes (403 + error text) | n/a (new) | no | yes |
| `test_unauthenticated_reset_is_rejected` | yes (401) | n/a (new) | no | yes |
| `test_demo_org_member_can_reset` | yes (200, success, log line, twice) | n/a (new) | no | yes |
| `test_outsider_org_member_gets_403_forbidden` | yes (403, FORBIDDEN, access_denied log) | n/a (new) | no | yes — tests the hostile org, not just the owner |
| `test_exception_during_reset_returns_generic_message_not_raw_exception` | yes (500, generic message, secret absent) | n/a (new) | no | yes |
| `test_reset_demo_db_returns_user_not_found_when_demo_user_missing` | yes (exact dict) | n/a (new) | no | yes |
| `test_clear_demo_db_is_noop_when_demo_user_missing` | yes (returns None) | n/a (new) | no | yes |
| e2e `test_ac1_unauthenticated_reset_is_rejected` | yes (400 + "csrf" in body) | n/a (new) | no | yes |
| e2e `test_ac3_demo_org_member_can_reset_and_reseed` | yes (200, success, process name, expired item) | n/a (new) | no | yes |
| e2e `test_cross_tenant_reset_is_rejected` | yes (403) | n/a (new) | no | yes — the mandatory cross-tenant probe, correctly uses a hostile org |

No catch-all status assertions (`in (200, 302, 404)` style), no `try/except: pass`
around an assert, no test recomputing its expected value from the function under test.

## Mutations — the falsifiability probe (all run live against the test DB, restored after each)

| # | mutation | probed test(s) | result |
|---|---|---|---|
| 1 | `api_routes.py`: `if not demo_user or g.current_org_id != demo_user.org_id:` → `if not demo_user:` (drops the caller-org comparison — the exact F1 regression) | `test_outsider_org_member_gets_403_forbidden`, e2e `test_cross_tenant_reset_is_rejected` | **both FAILED (red)** — confirmed real |
| 2 | `api_routes.py`: 500-body message reverted to `str(e)` (the exact F2 regression) | `test_exception_during_reset_returns_generic_message_not_raw_exception` | **FAILED (red)** — confirmed real |
| 3 | `api_routes.py`: `if config.environment not in ("test","local"):` → `if False:` | `test_env_gate_blocks_outside_test_and_local` | **FAILED (red)** — confirmed real |
| 4 | `api_routes.py`: removed `@requires_auth` | `test_unauthenticated_reset_is_rejected` | **FAILED (red)**, via an `AttributeError` on `g.current_user.id` rather than the expected assertion — still confirms the test catches the regression, though the route itself would need its own defensiveness if this decorator were ever genuinely dropped (noted, not this test's job to fix) |

Each mutation was reverted immediately after its probe; `git status --porcelain` and
`ruff check`/`ruff format --check` confirmed the tree matched the pre-probe patch state
before moving to the next, and the full batch (10 tests) was re-run green after all
probes completed.

Not probed (sample tier — cosmetic/lower-risk): `test_demo_org_member_can_reset`,
`test_reset_demo_db_returns_user_not_found_when_demo_user_missing`,
`test_clear_demo_db_is_noop_when_demo_user_missing`, e2e AC1/AC3 — each is a
straightforward direct assertion on a return value or HTTP status with no
authorization/tenant-isolation logic in the path being probed elsewhere in this batch.

## Findings
None.

verdict: valid
