---
name: preflight
description: "Deterministic environment check that runs before any code workflow: resolves ENVIRONMENT (unset means local — not test, not production), and reports whether the test DB, dev app server, OTel collector, docker, observability stack, glab, KeePassXC, scanners, and a Herdr partner pane are actually present. Backed by scripts/preflight.py, not agent guesswork. Use this skill at the start of new-feature, review-feature, fix-bug, suite-warden, prod-sentinel, security-audit, and any scheduled run, or when the user asks 'is my environment set up', 'why did the tests fail to even start', or hits an unexplained connection error. Autonomous: repairs what is safe to repair locally, never asks permission."
---

# Preflight

Every workflow in this repo starts by re-deriving the same facts — is the DB up, is the
app running, why is OTel screaming, am I paired with Codex — and each one pays tokens and
tool calls to learn what a socket probe answers in three seconds. This skill runs
`scripts/preflight.py` once and hands the answers to whoever asked.

The script is the authority. Do not re-check its findings by hand: if it says the app
server is down, it is down, and a second opinion from `curl` costs tokens to confirm a
fact you already have. Read `.agents/autonomy.md` — this skill runs unattended and fixes
what it can without asking.

## Run it

```bash
python3 scripts/preflight.py --json      # agents: parse this
python3 scripts/preflight.py             # humans: readable summary
python3 scripts/preflight.py --check app_server --quiet   # exit 0/1, for scripts
python3 scripts/preflight.py --skip-slow  # drop the alembic head comparison (~1s faster)
```

Runs in ~3s. Stdlib only, imports nothing from `app/` — importing the app would load
config, hit KeePassXC, and start the OTel exporter, which is three of the things being
checked.

## What the report means

The JSON has four sections that matter:

- **`environment`** — `name`, `was_set`, `assumed`. **An unset `ENVIRONMENT` is not an
  error**: `app/utils/config_loader.py:16` defaults it to `local`. But it means you are
  *not* in test and *not* in production, and `local.ini` is in play — including
  `otel_enabled = true`, `debug = true`, and KeePassXC-sourced secrets. Never assume a
  bare shell is the test environment.
- **`capabilities`** — booleans: `app_server`, `test_db`, `otel_collector`,
  `observability_stack`, `docker`, `glab`, `in_herdr`, `herdr_partner`, `deps`.
- **`decisions`** — the calls already made for you, so callers don't each invent their own:
  - `live_server_tests`: `run` | `skip` — **suite-warden consumes this.** `skip` means
    the 30 live-server tests in `tests/test_login_2fa_flow.py` and
    `tests/test_2fa_totp_optimized.py` would fail on `ConnectionRefusedError`, not on an
    assertion. That is an absent server, not a red suite.
  - `verification_mode`: `herdr-adversarial` (Codex partner pane present) | `subagents`.
    Pass this to the front doors instead of making them probe for Herdr themselves.
  - `otel_exporter_active`: whether spans will actually be exported. The exporter is
    gated on **both** `otel_enabled` and `grafana_data_enabled`
    (`app/observability/tracing.py:21-24`, `metrics.py:25-27`). `local.ini` ships
    `otel_enabled = true, grafana_data_enabled = false`, so the common case exports
    nothing and a down collector is harmless. Do not "fix" a down collector that nothing
    is exporting to.
  - `can_open_mr`, `db_writes_allowed`.
- **`blockers`** — failed *critical* checks (`environment`, `venv`, `deps`, `test_db`,
  `git`). Non-empty means stop and repair; everything else is informational.

## Repair, don't report-and-wait

Autonomy policy: fix what is safe and local, then re-run preflight to confirm. Do these
without asking:

| Blocker | Repair |
|---|---|
| `deps` missing (e.g. `factory`) | `uv sync --extra dev` |
| `test_db` down | `docker-compose -f docker-compose.test.yml up -d`, wait for the port |
| `migrations` pending | `uv run alembic upgrade head` (never `workflow upgrade-db`) |
| `otel_collector` down **while `otel_exporter_active`** | `uv run workflow observability start`. If the exporter is inactive, this check is informational — do nothing |
| `observability_stack` down | only if the task needs it (`prod-sentinel`, RUM work): `uv run workflow observability start` |
| `git` on main | branch before committing; git-commit-chain does this itself |

Do **not** repair these — report them and continue with reduced scope:

- `app_server` down → do not start a server as a side effect of a test run. Tell
  suite-warden to skip live suites, or start it deliberately when the task is about the
  running app.
- `glab` unauthenticated → needs a human login (`glab auth login`); say so.
- `keepass` missing → local secrets fall back to ini values; note the degradation.
- `gitleaks`/`semgrep` missing → security-audit's scanner pass is incomplete; say which
  layer didn't run rather than claiming a clean scan.

## Calling convention for other skills

```
1. python3 scripts/preflight.py --json
2. blockers non-empty? repair per the table, re-run, still blocked -> escalate per .agents/autonomy.md
3. read decisions.* and pass them down (verification_mode, live_server_tests, otel_env_override)
4. proceed
```

Run preflight **once** per workflow and pass the report down to subagents in their prompt
rather than having each stage re-run it. It is cheap, not free, and a subagent that
re-probes is a subagent that can disagree with its orchestrator about what environment
it's in.

## Extending the checks

New check = new `check_*()` function returning a `Check`, registered in `run_all()`'s
thread pool, and — if callers should branch on it — a key in `capabilities` and possibly
`decisions`. Keep the budget: short timeouts, no app imports, parallel probes. A preflight
that takes 30s stops getting run, and a check nobody runs protects nothing.

## Rules

- The script reports; it never edits config to make a check pass. Turning off
  `otel_enabled` in `local.ini` because the collector is down is falsifying the
  environment, not fixing it.
- `OTEL_SDK_DISABLED=1` does **not** silence this repo's OTel exporter — `tracing.py`
  builds the `TracerProvider` by hand and that env var only reaches the SDK's own
  auto-instrumentation entry points. Verified, not assumed. If you see export errors, a
  code path enabled the exporter; find it rather than reaching for the env var.
- Never claim a capability preflight said was absent. "Tests pass" when live suites were
  skipped is a false report — say "252 passed, 30 skipped (no app server)".
- Preflight never touches production: it reads local config files and probes localhost
  ports. `db_writes_allowed` is false for `ENVIRONMENT=production` and no skill in this
  suite runs there (`.agents/autonomy.md`).
