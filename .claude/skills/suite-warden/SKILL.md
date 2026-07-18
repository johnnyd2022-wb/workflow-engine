---
name: suite-warden
description: "Keeps the test suite's signal trustworthy so 'green means green': owns the live_server and quarantined pytest markers, the quarantine registry at .agents/test-quarantine.md, flake detection, and the rule that an absent dependency is a skip with a reason, never a failure. Use this skill when the suite has failures that aren't about the code (connection errors, missing services), when a test is flaky, when adding a test that needs a real server or external service, when someone asks 'are these failures real', or on a scheduled suite-health run. Runs preflight first and consumes its decisions. Autonomous: fixes gating and opens an MR; never deletes or weakens a test to get green."
---

# Suite Warden

Every agentic workflow in this repo treats the test suite as ground truth. That only
works if red means broken code. When a third of the suite fails because a service isn't
running, everyone — human and agent — learns to read failures as noise, and the next real
regression sails through behind the same shrug.

This skill's whole job is keeping that from happening. It does not write feature tests
(that's `new-feature`/`fix-bug`) and it does not own fixtures (`test-fixtures`). It owns
**the honesty of the signal**.

Read `.agents/autonomy.md`. This skill runs unattended and ships via MR.

## The one rule

**An absent dependency is a skip with a stated reason. A wrong answer is a failure.**

A test that cannot run has not found a bug. Reporting it as red is a lie in the direction
of alarm; deleting it is a lie in the direction of comfort. Skip it, name the reason, and
make the reason machine-checkable so it un-skips itself the moment the dependency is back.

## Step 1: Preflight, always

```bash
python3 scripts/preflight.py --json
```

Read `decisions.live_server_tests` (`run` | `skip`) and `capabilities.test_db`. Preflight
already made these calls — don't re-probe. If `test_db` is a blocker, repair per the
preflight skill and re-run; a suite that can't reach Postgres is an environment problem
wearing a test problem's clothes.

## Step 2: Run and classify

```bash
uv run pytest tests/ -q          # ENVIRONMENT unset is fine: it resolves to local,
                                 # whose ini points at the same test DB on :8401
```

Every failure lands in exactly one bucket. Getting this wrong is the whole failure mode
this skill exists to prevent:

| Bucket | Looks like | Action |
|---|---|---|
| **real** | An assertion failed. The code returned the wrong answer. | Hand to `fix-bug`. Never touch the test. |
| **environmental** | `ConnectionRefusedError`, `OperationalError`, missing binary, DNS. The test never reached an assertion. | Gate it (Step 3). It is not red — it is unrun. |
| **flaky** | Passes and fails on the same code. Time, ordering, randomness, shared state. | Step 4. |
| **stale** | Asserts behavior that intentionally changed. | Route to **test-author** to update it deliberately, with the intended change named as justification; **test-evaluator** then confirms the updated assertion still protects something rather than having been loosened to pass. Not suite-warden's to edit — this skill owns the signal, not the test's content. |

The tell for *environmental* is simple: **did the test reach an assertion?** A connection
error means the test never got to make a claim about the code.

## Step 3: Gating (the live-server marker)

Two suites drive a real dev server over HTTPS instead of exercising the app in-process:
`tests/test_login_2fa_flow.py` and `tests/test_2fa_totp_optimized.py` (30 tests against
`https://localhost:8005`). Without a server they failed with `ConnectionRefusedError` —
30 red tests that said nothing about the code.

The gate lives in `tests/conftest.py` and is declared in `pyproject.toml`:

```python
# in the test module
pytestmark = pytest.mark.live_server
```

`pytest_collection_modifyitems` probes the port once per session (from `config.port`, not
a hardcoded number) and skips marked tests with the reason when nothing is listening.
Result with no server: `252 passed, 30 skipped`. With `uv run workflow start` running:
those 30 execute for real.

**Adding a test that needs a real server:** mark it `live_server`. **Needs any other
external service** (a real Xero API, a live collector): add a marker in the same shape —
declare it in `pyproject.toml`, probe it once per session in `conftest.py`, skip with a
reason. Never let it fail-by-default, and never let it silently pass without running.

Report skips explicitly. "Tests pass" when 30 were skipped is a false report; the honest
line is `252 passed, 30 skipped (no app server)`.

## Step 4: Flakes

A test that passes and fails on identical code is worse than a failing test: it teaches
people to re-run until green, which is the same reflex as ignoring failures.

```bash
uv run pytest tests/test_<area>.py -q -p no:randomly --count 5   # if pytest-repeat present
for i in 1 2 3 4 5; do uv run pytest tests/test_<x>.py::test_<y> -q | tail -1; done
```

Usual causes here, in order: shared DB state between tests (the `db` fixture in
`conftest.py` exists for this), time/TOTP windows (the 2FA suites manipulate time),
ordering dependence, and unclosed sessions.

Fix the cause when you can find it. When you can't, **quarantine rather than tolerate** —
a quarantined test is a tracked debt; a flaky test in the main run is untracked erosion.

## Step 5: Quarantine, with an expiry

```python
pytestmark = pytest.mark.quarantined   # excluded from default runs by addopts
```

Every quarantine needs a row in `.agents/test-quarantine.md` — no exceptions, and the
registry is what makes this honest rather than a graveyard:

```markdown
| test | quarantined | why | owner | expires | issue |
|---|---|---|---|---|---|
| tests/test_x.py::test_y | 2026-07-17 | Fails ~1 in 5 on TOTP boundary; cause unknown | suite-warden | 2026-08-17 | !123 |
```

Run them deliberately: `uv run pytest -m quarantined`. On a scheduled run, re-run the
quarantine list: anything passing 10/10 comes back out; anything past `expires` gets
escalated as a report, not silently extended. A quarantine with no expiry is a deletion
with extra steps.

## Step 6: Noise is a failure mode too

Output nobody can read is output nobody reads. If a run buries its summary in stack
traces from a working system, that is in scope.

Worked example, for the pattern rather than the specifics: the full suite used to print
hundreds of OTel exporter errors plus `--- Logging error ---` tracebacks about closed
streams. The cause was not the environment — `tests/test_observability_telemetry_ingress.py`
built an app with `grafana_data_enabled=True` to test the `/telemetry` proxy, which also
satisfied `configure_tracing`'s `otel_enabled and grafana_data_enabled` gate
(`app/observability/tracing.py:21-24`), starting a real gRPC exporter whose background
worker then retried against a collector that wasn't running — for the rest of the
session, into streams pytest had already closed. The fix was one monkeypatch
(`otel_enabled=False`) in a test that never cared about server-side export. No assertion
changed.

The generalisable part: **find which code path turned the noise on.** Silencing at the
logging layer would have hidden a real export failure later.

## Step 7: Report and ship

`.agents/reports/suite-warden/<date>.md`:

```markdown
# SUITE HEALTH — <date>
preflight: live_server_tests=<run|skip>, test_db=<up|down>
result: <N> passed, <N> skipped, <N> failed in <T>s
skipped: <count> (<reason>) — <is this expected given preflight? yes/no>
real_failures: <list, each handed to fix-bug with a link> | none
flakes_seen: <test — pass rate over N runs> | none
quarantine: <added/removed/expired rows>
noise: <lines of non-test output; cause if investigated>
verdict: trustworthy | degraded (<why>)
```

`verdict: trustworthy` means: no unexplained failures, every skip has a reason preflight
predicted, and the summary line is readable. Anything else is `degraded`, and says why.

Real failures go to `fix-bug` (one MR per bug, not a batch). Gating and quarantine
changes go out via `git-commit-chain`.

## Rules

- **Never delete, skip, weaken, or broaden a test to get green.** A skip is only legal
  when a *dependency* is absent and the reason says which one. Skipping because a test
  fails is the prohibited move in `.agents/autonomy.md`, and this skill is where that
  temptation lives.
- Never mark a test `quarantined` without its registry row and an expiry date.
- Never claim a suite is green while tests are skipped — state the split.
- Don't start services as a side effect of a test run. If the app server is down, skip
  the live suites; starting a server mid-run makes results depend on run order.
- A test that has been quarantined twice for the same cause is a design problem, not a
  test problem: escalate it rather than quarantining a third time.

## Handoffs

- ← **preflight**: `decisions.live_server_tests` and `capabilities.test_db`.
- ← **new-feature / fix-bug / review-feature / dependency-update**: any test failure that
  never reached an assertion (connection error, missing service) is routed here rather
  than debugged as a code bug.
- → **fix-bug**: real failures — one MR per bug, never a batch.
- → **test-author**: the **stale** bucket — a test asserting behaviour that intentionally changed gets updated there, not here.
- → **test-evaluator**: to confirm a stale test's updated assertion still protects something (this skill owns runtime signal; the validity of a test's content is the evaluator's).
- → **test-fixtures**: when the fix is a missing/incorrect factory rather than a gate.
- → **git-commit-chain**: ships gating and quarantine changes.
