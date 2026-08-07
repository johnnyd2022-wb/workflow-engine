# Herdr Mission Control — Parallel Build and Safe Cutover

**Status:** accepted and cut over on Herdr 0.7.5 as of 2026-08-02. F3 opens Mission
Control; the legacy dashboard remains installed, checksummed, timer-backed, and available
through the atomic rollback command during the retention window.

### Implementation checkpoint — 2026-08-02

- Shadow CLI/TUI, normalized snapshot, run store, doctor, attention inbox, skill metrics,
  background snapshot timer, separate pane toggle, and atomic cutover/rollback tooling are
  implemented. The new pane is running as `mission-control-shadow` beside legacy status.
- Claude and Codex Herdr integrations are installed from backed-up configs.
- Focused Mission Control, launcher, and metrics tests are green; the legacy config,
  launcher, dashboard and timer still match their pre-build checksums.
- Herdr 0.7.5 was installed with live handoff. Client/server protocol 17 is compatible,
  all five agent panes survived, and current Claude v7/Codex v6 integrations remain active.
- Nightwatch resumed the original quota-stalled disposable Claude writer without input.
  It produced the isolated acceptance evidence and was explicitly marked
  `ready_for_review`; no product checkout was in its write scope.
- Production hardening, configuration/routing validation, snapshot soak, the Mission
  Control pane close/reopen smoke test, and 98 focused Mission Control/launcher/metrics
  tests pass. The legacy executable, launcher, timer and service still match their
  pre-build checksums; F8's file-viewer action remains available.
- The independent Codex grader found that the original diagnostic path attempted snapshot
  writes/socket access inside its read-only sandbox. Mission Control gained a non-mutating
  `--json` path and `doctor --read-only` warm-snapshot validation; the grader reran the
  rubric and returned `VERDICT: clean` with live and historical sessions both visible.
- The acceptance verifier sealed the writer/grader pair. The live cutover changed only F3,
  preserved F8, passed config reload, exercised close/reopen, rolled back to the exact
  pre-build checksum, and then reapplied successfully. The seven-day legacy runtime and
  30-day file retention windows start from this cutover.
- Post-cutover, the operational summary was reduced to two worktree-level buckets:
  `NEEDS YOU` and `DONE`. Session duplicates are collapsed; merged history is omitted from
  the summary (still available through archives); prepared mergeable MRs count as done;
  conflicting MRs count as needs-you. A two-minute disk cache supplies best-effort GitLab
  MR metadata without putting network latency on every 30-second snapshot refresh.

## Goal and invariants

Build Mission Control as a separate global application for every Herdr repository.
Version one is read-only apart from navigating to agents and reports. It must preserve
the existing colour key, MTB visual with circular agents, clear session columns, and
collapsible worktree sections.

The current F3 dashboard, cache, launcher and timer are frozen during shadow development.
Mission Control has its own executable, cache, state, logs and pane identity. An idle or
done agent is never treated as successful work: agent lifecycle and workflow lifecycle
remain separate.

## Runtime design

- `mission-control --interactive` opens the shadow TUI; `--json` emits its normalized
  snapshot; `doctor` validates dependencies and data sources without changing them.
- `mission-control report start|update|finish` writes versioned, atomic run records under
  `~/.local/state/herdr-mission-control/runs/`.
- Live Herdr topology is the authority for live agent state. The existing Claude cache is
  read-only historical evidence. Queue, Git, reports and metrics are independent adapters;
  a failed adapter produces a visible stale/error marker rather than crashing the UI.
- `agent_state` is one of `working`, `blocked`, `idle`, `done`, `unknown` and comes from
  Herdr. `run_state` is one of `queued`, `running`, `blocked`, `ready_for_review`, `failed`,
  `completed`, `unknown` and changes only through an explicit run report.
- Identity resolution uses live pane ID, then session ID, then worktree plus label. Explicit
  run metadata outranks inferred labels; live state outranks cache state.

## Delivery gates

1. Capture checksums and recoverable backups of the legacy executable, launcher, config,
   binary and systemd units. Do not import Mission Control from legacy code.
2. Build and test the shadow model, adapters, state store, TUI, JSON output, doctor and
   separate launcher. Run it manually; F3 remains unchanged.
3. Add best-effort reporting to shared launch points behind a feature flag. Reporting has
   a short timeout and cannot affect whether an agent launches, waits or completes.
4. Once the shadow UI works on Herdr 0.7.3, back up the binary/config/session state, use
   the stable-channel live handoff update, and verify all panes, agents, F3 and F8. Install
   Claude/Codex integrations for session identity. Roll back on any topology regression.
5. Run one complete workflow with a Claude writer and independent Codex read-only grader.
   Verify state, worktree, reports, Git status, attention grouping, navigation, narrow/wide
   layouts, archive toggles and explicit readiness. Compare coverage against legacy status.
6. Cut over by changing only the F3 command to the new launcher, reload config, and smoke
   test open/focus/close/restart. Restore the config backup to roll back.
7. Keep the legacy command and timer working for seven days and retain its files for at
   least 30 days. Queue mutation and automatic operational controls are post-cutover work.

## Acceptance tests

- Unit tests cover identity merging, source precedence, explicit readiness, malformed or
  stale JSON, deleted worktrees, subprocess timeouts and atomic record writes.
- TUI tests cover narrow, normal and wide dimensions without curses exceptions.
- Fake Herdr executables prove navigation rejects stale targets and never sends agent input.
- Automated tests use temporary state/config roots and never focus or close real panes.
- Existing launcher and skill-metrics tests stay green after best-effort reporting hooks.
- Cutover requires a clean `mission-control doctor`, one complete accepted workflow, intact
  F3/F8 behavior and a tested rollback command.

## Defaults

- All Herdr repositories are included; workflow-engine gets the richest reports/metrics
  adapter first.
- Stable Herdr only. The shadow dashboard is proven before upgrading 0.7.3.
- V1 can focus agents and reveal report paths, but cannot retry, cancel, prompt or edit the
  queue.
- Missing evidence is `unknown`, never guessed. Historical ledgers are not rewritten.
