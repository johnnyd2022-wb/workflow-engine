# PERF: activity-log
date: 2026-08-09
verdict: clean

## Measured

`/api/core/entities/activity` added to `.agents/perf/budgets.json` → `measure.api` (the one
route in this slice with no path parameters). Result (`.agents/reports/perf/last-run.json`):
`backend_ms: 4.4` (budget 150, ceiling 1000), `queries: 4` (budget 15, ceiling 60) — well
inside both tiers. Full suite: 21/21 passed (20 pre-existing + this one), 0 ceiling breaches,
0 budget breaches.

## Not measured: `/story` and `/summary`

Both are path-parametrized (`/api/core/entities/<entity_type>/<entity_id>/...`) and
`tests/e2e/test_perf_budgets.py` (`_api_entries()`) has no ID-substitution mechanism — it
sends the `measure.api` route string (or `{route, method, body}` object) verbatim via
`page.request.get(route)`. Same limitation the traceability review hit and left unaddressed
for its own parametrized routes (`/api/core/inventory/trace/<raw_material_id>`,
`/api/core/inventory/trace-backward/<inventory_item_id>`, and `POST
/api/core/sourcemap/trace`'s body-required `root_id`) — none of those were added to
`budgets.json` either (`git show 7c32b89 -- .agents/perf/budgets.json`), confirming this is
an established, consistent gap in the harness rather than something specific to this slice
to invent a workaround for. Extending the harness to support per-route ID templating is a
tooling change with a blast radius wider than this review (it would affect every future
parametrized-route measurement, not just this slice's two routes) — flagged for whoever
next touches `scripts/perf_triage.py`/`test_perf_budgets.py`, not fixed here.

Qualitative read on both unmeasured routes, from the code (not a live measurement): `story`
and `summary` run 1-2 indexed queries each (`entity_events` on `(org_id, entity_type,
entity_id, created_at)`, `entity_event_summaries` on its PK) plus, for `story` on
`inventory_item`, one extra indexed `InventoryItem` lookup for the legacy-audit merge — same
shape and order of magnitude as `activity`'s measured 4 queries, not exempt as a hidden N+1.

## Static findings

`perf_triage.py`'s semgrep-based N+1 pass: 0 findings in the reviewed range. No new hot
areas flagged.

VERDICT: clean
