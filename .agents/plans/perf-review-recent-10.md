# Performance / reliability / security review — 10 most recent MRs

Scope: the 10 MRs merged to `main` up to `c22f782` —
!208, !206, !207, !205, !204, !203, !202, !189, !201, !200 (+ !199 Phase B, adjacent).
Goal: the app is *quick, reliable, secure*. Every real finding becomes an MR
(Codex-reviewed in Herdr). Nothing deferred.

Reviewed as the code lives **now on main** (the MRs stack), focusing on the paths the
recent work created or touched: `/api/core/changes` (every tab, every 3 s),
`/api/core/system-findings` (every /core load), the process completed-run page, the
LiveSync client, the If-Match write paths, static-asset serving.

## Method

1. `semgrep --config .semgrep/rules/performance.yml app/` → **0 findings** (no N+1 /
   unbounded-query / await-in-loop patterns).
2. `perf-guardrails` tooling present (`scripts/perf_triage.py`, `.agents/perf/budgets.json`,
   `tests/e2e/test_perf_budgets.py`) — nothing outstanding.
3. Manual read of each MR's touched code + its live consumers, with `EXPLAIN (ANALYZE,
   BUFFERS)` on the per-request queries.

## Findings

### F0 — main has two alembic heads (!206 + !208 merged without a rebase)  [reliability, P0]
Both branched off `feat_subs_seq_merge_001`; `alembic upgrade head` on main now fails.
Blocks `migration_reversibility` CI and deploy.
→ **Shipped as !209** — empty merge revision `merge_noident_execpage_001`.

### F1 — `/api/core/changes` head query has no index for the `entity_type IN` filter  [perf, hot path]
`changes_feed.get_changes` runs, on **every browser tab every 3 s**:
```sql
SELECT COALESCE(MAX(seq),0) FROM entity_events
WHERE org_id = :org AND entity_type IN ('process','execution','execution_step','step','inventory_item')
```
`ix_entity_events_org_seq` is `(org_id, seq)` — Postgres scans it **backward** for the org
and filters `entity_type` row-by-row until the newest *synced* row. `user.login` /
`user.login_failed` / `org.*` events are frequent and **not** synced types (confirmed —
`EventWriter` + `_update_user_summary` write them), so the scan removes every trailing
non-synced row, every poll, per tab. Measured (2000 logins, 5 process events, 800 more
logins on top):

| | plan | buffers | Rows Removed by Filter | time |
|---|---|---|---|---|
| now | Index Scan Backward + Filter | 24 | **800** | 0.13 ms |
| + partial index | Index-Only Scan Backward | 3 | 0 | 0.07 ms |

"Rows Removed by Filter" scales linearly with login activity since the last content event
(a Monday-morning login burst → thousands of rows filtered per poll per tab). The rows
query is bounded by `seq > :since` so it is unaffected; only the head query needs this.
- **Fix:** `CREATE INDEX CONCURRENTLY ix_entity_events_org_seq_synced ON entity_events
  (org_id, seq) WHERE entity_type IN (<the 5 synced types>)` — matches the feed's exact
  filter, makes the head query an index-only fetch regardless of login volume. Additive,
  no deploy precondition.

### F2 — LiveSync polls a fixed 3 s even after a long run of 304s  [perf]
!206 added the conditional-GET / 304 path, but `live-sync.js` still `schedule(POLL_VISIBLE_MS
= 3000)` unconditionally. On a quiet org every visible tab issues an (empty, 304) request
every 3 s forever. Back the cadence off toward a ceiling (~15 s) after N consecutive
no-change polls, and snap back to 3 s on any delivered event, `poke()` (fires on every
local mutation), tab-focus, or `online`. ~5× fewer steady-state requests, no added latency
for the cases users notice (their own actions already `poke()`).
- **Fix:** `live-sync.js` only. New `idleStreak` counter; `nextInterval()` helper.

## No further findings

- !202 static-asset serving is WSGI-layer, already optimal.
- !203 `_run_live` / `_signals_from_results` add no per-request cost beyond what already ran.
- !204 If-Match `SELECT ... FOR UPDATE` + `refresh` is one extra round-trip on a *write*
  (rare vs the 3 s poll) and is required for correctness (the row may be identity-mapped
  stale from an earlier load) — not a regression.
- !189/!207/!209 are startup/migration only.
- !199/!200 If-Match client wiring is O(steps) map/max per user action — trivial.

## Execution

F1 + F2 ship together as **one MR** — both are changes-feed hot-path perf, small, disjoint
files (migration + JS). Codex-reviewed. F1's index is verified with `EXPLAIN`; F2 gets a
`node --test` for the cadence state machine.
