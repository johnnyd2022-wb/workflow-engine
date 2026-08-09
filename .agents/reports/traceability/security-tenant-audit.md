# SECURITY-TENANT-AUDIT: traceability
date: 2026-08-09
verdict: findings-open (2 new findings; both dispositioned by the orchestrator below)
invocation: chain stage, Codex (`gpt-5.6-sol`, `--sandbox read-only`, effort high), independent
  second pass on a separate quota pool from the security-audit stage.

**Note on this file's authorship**: the grader's own write to this path was rejected by its
enforced read-only sandbox (`apply_patch: writing is blocked by read-only sandbox`) — expected
per `.agents/verification-chain.md` §5 ("A `--sandbox read-only` grader cannot write that file
itself"). This file is the orchestrator's transcription of the grader's verbatim final message,
plus the orchestrator's own follow-up investigation and disposition of each finding.

## Grader's verbatim final message

> The audit found two open issues:
>
> - Medium: temporal_dag_tracer.py:57 trusts event-payload endpoint UUIDs. A foreign item
>   UUID can enter temporal `nodes` and `edges`, though foreign row state is not fetched.
> - Low: backend.py:5741 re-queries `EntityEvent` by timeline IDs without an `org_id`
>   predicate.
>
> The four prior fixes were confirmed, including `_snapshot_at` scoping, current-state root
> resolution, traversal scoping, and integer-parse handling. `root_type` is cosmetic and
> never selects a query/table.
>
> VERDICT: findings-open

## Confirmation of the four prior fixes (independent, per the grader)

All four findings from `.agents/reports/traceability/security-audit.md` (F1 cross-tenant
snapshot leak, F2 dead import, F3/F4 unhandled int parsing) were independently re-verified
against the patched code and confirmed closed. `root_type` was specifically checked for use
as an unvalidated table/query selector and confirmed cosmetic-only (labels the root node in
the response; the `as_of`-absent branch hardcodes `InventoryItem` regardless of its value).

## New finding G1 (Medium) — orchestrator disposition: confirmed, not patched here, routed

`app/core/backend/temporal_dag_tracer.py:57-90` (`trace()`'s edge-building loop) trusts
`item_id`/`exec_id` values read out of `EntityEvent.payload` JSON without independently
verifying those ids belong to `self.org_id`. The outer `step_events` query (lines 46-55) is
correctly `org_id`-scoped — so the *event row itself* is guaranteed to belong to the caller's
org — but nothing re-validates that the *ids named inside that event's JSON payload* do too.

**Followed up independently** (not just accepting the grader's framing): traced this to its
actual root cause. `ExecutionRepository.complete_step` (`app/core/db/repositories/execution_repo.py:214-303`)
accepts `actual_inputs`/`actual_outputs` from the caller with **no validation that any
`inventory_item_id` inside them belongs to `org_id`** before storing them on
`execution_step.actual_inputs`/`actual_outputs` and feeding them into
`EventWriter.emit(payload={"items_consumed": ..., "items_produced": ...})`. Grepped
`.agents/reports/execution/*.md` and `.agents/history/findings.jsonl` for prior coverage of
this exact class (`actual_input`/`complete_step`/cross-org item ownership) — none exists,
despite the `execution` slice's own review (`.agents/feature-index.md` → `execution`,
reviewed 2026-08-02, "6 real defects found and fixed"). This appears to be a genuinely new
finding, surfaced only because this stage was reading a *downstream consumer*
(`temporal_dag_tracer.py`) of data the `execution` slice's own review didn't examine from
this angle.

**Why not patched in this slice**: the fix belongs at the write side —
`ExecutionRepository.complete_step`, which `.agents/feature-index.md` flags as "the
highest-risk function in the app... read all of it before changing any of it" (615 lines,
consumes inventory, produces outputs, writes movements, emits events, enforces idempotency,
all in one transaction). That is squarely the `execution` slice's file, already has its own
45-test suite (`test_executions.py`), and a change to its input-validation contract is a
meaningfully bigger, more invasive change than this review's mandate — patching it here as a
drive-by would violate this review's own scope discipline (spec's non-goals section) and risk
the exact "two writers, no lock, whichever wrote last wins" hazard
`.agents/verification-chain.md` §6 warns about, since `execution` is a separately-owned slice
with its own review cadence.

**Why not hardened read-side in `temporal_dag_tracer.py` either**: the grader's own framing
— "though foreign row state is not fetched" — is accurate and important: `_build_node_list`
(line 137-145) already sets `state: None` unconditionally for every non-root node (AC17,
confirmed intentional/documented behavior, not this review's to change). So the actual
exposure if a foreign item_id *did* reach the payload is a bare opaque UUID appearing in
`nodes`/`edges` with no attached name/quantity/supplier/etc — meaningfully different from,
and far lower severity than, F1's confirmed-and-fixed full-snapshot leak. Adding per-edge
org-ownership validation queries in the read path to defend against a write-side bug that
may not even be reachable in practice (whether `complete_step`'s callers already constrain
`inventory_item_id` to the org before it reaches this function was not fully traced end to
end) would add real per-request query cost to guard against an unconfirmed, low-severity,
out-of-slice write path — not a proportionate fix for this review.

**Disposition**: recorded `confirmed` (not `fixed`) in the finding history, scoped to
`app/core/db/repositories/execution_repo.py` (its real location) rather than
`temporal_dag_tracer.py`, so a future `execution`-slice review or a targeted `fix-bug` picks
it up with the right file attached. Flagged in this review's final report as a
findings-open item for the human to see.

## New finding G2 (Low) — orchestrator disposition: fixed

`app/core/backend/backend.py:5741` — `sourcemap_trace`'s temporal branch re-queries
`EntityEvent` by primary-key id (`_EE_Trace.id.in_(timeline_ids)`) to attach human summaries,
without an `org_id` predicate. **Independently verified this is not exploitable via the
current call path**: `timeline_ids` is built entirely from `result["timeline"]`, which
`TemporalDAGTracer._build_timeline()` (line 160-169) already produces via a query filtered by
`EntityEvent.org_id == self.org_id` — so every id in `timeline_ids` is already guaranteed
org-scoped before this second query ever runs, and `id` is a globally-unique primary key
(no other org's row can share it). Not independently exploitable today, but it breaks the
codebase's own established convention of re-scoping every FK/id hop as defense-in-depth
(the same pattern the security-audit report praised in `dagtraversal.py`'s
`_enrich_items_bulk`/`add_step_order_connections`), and it's a one-line, zero-risk fix — so,
unlike G1, applied immediately: added `_EE_Trace.org_id == org_id` to the filter.

## Verification after G2's fix

```
uv run pytest tests/test_traceability.py tests/e2e/traceability/ -q
```
All green (see review.md for the consolidated run). No new regression test added for G2
specifically — same rationale test-map.md's row 10 precedent used for the analogous
`dagtraversal.py` fix: not independently exploitable via the current call path, so there is
no red-then-green state to capture; the existing F1 cross-tenant e2e probe
(`test_ac9_temporal_trace_root_state_not_visible_cross_tenant`) already exercises this exact
code path end to end and continues to pass.
