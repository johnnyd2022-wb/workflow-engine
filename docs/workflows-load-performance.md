# Product workflows pages — load performance

Follows the same playbook as `docs/core-load-performance-design.md` and the sourcemap
work (!192): kill the on-load fan-out, serve a lightweight first paint, lazy-load the
heavy detail when the user asks for it, and never let a payload scale with org history
on the critical path.

Branch: `perf/workflows-load`. Work the checklist top-down; tick items as they land so
this doc is a resumable status. Each item names the file(s), the measured before, the
approach, the risk, and the test.

---

## Methodology

Measured with Playwright against `whistlebird_test` (252 execs, 243 items, 12 processes,
48 expired raw materials), logged in as a real user, wall time to `networkidle`, per-call
timing + bytes captured from the network. Dev server on `:8005`.

## Measured baseline (2026-08-29)

| page | wall | API calls | bytes | worst call |
|---|---|---|---|---|
| `/core/processes` | 671 ms | 3 | 648 KB | **`system-findings` 636 KB** / 83 ms |
| `/core/flows` (no id) | 707 ms | 1 | 636 KB | **`system-findings` 636 KB** / 56 ms |
| `/core/flows?id=<p>` | **1574 ms** | 6 | 645 KB | **`inventory?process_id` 767 ms / 4 KB** + `system-findings` 636 KB + `/auth/me` ×2 |
| `/core/flows/create/*` (wizard) | 749 ms | 2 | 637 KB | **`system-findings` 636 KB** / 97 ms |
| `/core/executions/live` | 753 ms | 3 | 639 KB | **`system-findings` 636 KB** / 93 ms |

**Two dominant problems, both cross-cutting:**

1. **`/api/core/system-findings` is 636 KB on every authenticated page.** 405 KB of that
   (measured uncompressed) is a *single* finding — `expired_materials` — whose `data`
   dict carries the full DAG impact tree: every `impacted_item` object, every
   `expired_raw_material` object, and the entire `connections` edge list. The banner
   renders a headline count + a short name list in an expandable detail; it never reads
   `connections` at all. The full tree is already available on demand from
   `/api/core/inventory/expired-materials` (sourcemap + notifications use it).
2. **`/core/flows?id=<p>` spends 767 ms on `/api/core/inventory?process_id=<p>` for 4 KB
   of data** — a slow query, not a big payload. Plus `/auth/me` fires twice and
   `system-findings` blocks nothing but still ships 636 KB.

Everything else (the process list at 11 KB, the wizard fragments, per-process executions)
is already lean.

---

## Work items

### 1. Slim the `system-findings` banner payload — `[ ]`

**Files:** `app/core/backend/system_findings_cache.py` (or `corechecks.py` route),
`app/core/frontend/js/system-findings-banner.js`, `tests/test_system_findings_cache.py`,
`tests/test_corechecks_routes.py`.

**Before:** 636 KB on every page; 405 KB is `expired_materials.data`.

**Approach.** The `/api/core/system-findings` response feeds only the banner. Reshape the
per-finding `data` to what the banner actually renders:
- `expired_raw_materials`: `[{id, name, expiry_date}]` — not the full item object.
- `impacted_items`: `[{id, name}]` — not the full item object.
- **drop `connections` entirely** — the banner never touches it.
- add `impacted_count` / `expired_count` scalars so the headline never needs the arrays.

Do the projection in `get_or_compute` when it builds `findings` (after
`get_check_results`), so the cached expensive slice on disk is unchanged and
`/api/core/inventory/expired-materials` (full shape, for sourcemap/notifications) is
untouched. Update `formatTriggerDetails` in the banner JS to the trimmed shape (it
already only reads `.name`).

Expect ~405 KB → ~10–20 KB, i.e. ~636 KB → ~230 KB total (the rest is `untracked_items`
etc. — check those too; apply the same projection to any finding whose `data` carries
full objects or edge lists).

**If still large:** make the "What triggered this" detail a lazy fetch —
`system-findings` returns `{check_id, text, counts}` only, and expanding the detail calls
`/api/core/inventory/expired-materials`. Bigger JS change; do it only if the projection
isn't enough.

**Risk:** the banner's "Dispose of inventory item" action needs the expired item ids —
keep `id` in `expired_raw_materials`. The Notifications page renders its own list from a
separate call, so it's unaffected (confirm: grep `getSystemFindings` callers).

**Test:** `test_system_findings_cache.py` — assert the response `findings[].data` has no
`connections` key and the item lists are `{id, name, ...}` shaped, and payload size is
under a ceiling on a seeded multi-expired fixture. `test_corechecks_routes.py` — banner
contract (shape, 401) still holds.

---

### 2. `/core/flows?id=<p>` — the 767 ms `inventory?process_id` query — `[ ]`

**Files:** `app/core/backend/backend.py` (`list_inventory`), `app/core/db/repositories/inventory_repo.py`, `app/core/frontend/js/flows2-inventory.js` (or wherever flows2 calls it).

**Before:** 767 ms for ~4 KB (≈15 rows).

**Approach.** Profile `list_inventory` with `process_id` set against `whistlebird_test`
(SQLAlchemy query counter + `EXPLAIN`). Likely causes, in order of probability:
- the producing-step / execution / process batch-load block runs even for a 15-row
  result and isn't `process_id`-narrowed;
- `get_system_findings_by_item` (now cached, but still merges live checks each call);
- a missing composite index for `(org_id, <process filter path>)` — the process filter
  is via `source_execution → process_id`, which may not be indexed.
- `output_ready_date` per-item `get_operator_ready_instant_for_item` lookups.

Then: narrow the enrichment to the returned rows, add the index if `EXPLAIN` shows a
scan, and/or switch flows2's call to `?view=compact` (added in !192) if flows2 only needs
core item fields for its inventory panel.

**Risk:** flows2's inventory panel may show findings badges / ready-date state — check
what fields it renders before switching to compact.

**Test:** a perf-budget entry for `/api/core/inventory` with `process_id` (or a targeted
query-count assertion), plus an e2e that `/core/flows?id=<p>` reaches interactive without
the heavy query on the critical path.

---

### 3. `/core/flows?id=<p>` — duplicate `/auth/me` — `[ ]`

**Files:** `app/core/frontend/js/flows2-init.js` (line ~407), `app/core/frontend/js/core-api.js` (account-info component), `app/core/frontend/js/*account*`.

**Before:** `/auth/me` fired twice on `/core/flows?id=<p>`.

**Approach.** Find the two callers (flows2-init's own `fetch('/auth/me')` + the shared
account-info component). Route both through one cached accessor (`CoreAPI` already has
in-flight GET dedupe — the two calls may just be far enough apart to miss it; a short
result cache like `getSystemFindings`'s settle-window fixes it), or have flows2-init
consume the account-info component's result.

**Risk:** minimal — `/auth/me` is 414 B; this is hygiene, not a hotspot.

**Test:** extend the flows2 e2e (or `test_core_load_waterfall`-style) to assert `/auth/me`
is requested at most once per page load.

---

### 4. Banner re-fetches on boosted navigation — `[ ]`

**Files:** `app/core/frontend/js/system-findings-banner.js`, `app/core/frontend/shared/base_spa.html`.

**Before:** `system-findings-banner.js` self-inits on `DOMContentLoaded` only. After an
`hx-boost` navigation the banner shows **stale** findings until a full refresh (same
architecture gap as the `/core` hub bug fixed in !193, lower severity — wrong data, not a
dead page).

**Approach.** base_spa's `htmx:afterSettle` handler already calls `spaSyncBannerBack()`
(back-button href). Add `window.loadSystemFindingsBanner()` there too, guarded so it only
fires when `#system-findings-banner` is present in the swapped `#page-content`. The banner
JS already exposes `loadSystemFindingsBanner` on `window` and accepts a `preloaded` arg,
so this is a one-line add plus a guard.

**Risk:** double-fetch on pages that also preload it (the `/core` hub passes its own
result). `getSystemFindings` has a 3 s settle-window cache (from !183) that absorbs this;
verify.

**Test:** e2e — boost between two pages and assert the banner list updates (or at least
that `system-findings` is re-requested) rather than showing the first page's stale set.

---

### 5. `/core/processes` list — confirm it scales — `[ ]`

**Files:** `app/core/backend/backend.py` (`list_processes` API), `app/core/db/repositories/process_repo.py`, `app/core/frontend/js/processes-list*.js`.

**Before:** 11 KB / 51 ms for 12 processes — fine now, unknown at 500.

**Approach.** Check the `/api/core/processes` payload per row — if it carries steps,
version history, or per-process execution counts, that's O(processes × detail). If it's
flat metadata, leave it. If it grows, add `?limit` + keyset cursor (the !183 helpers) and
have the list page paginate / virtualise. Seed 500 processes on a scratch org and
re-measure before deciding.

**Risk:** none if it's already flat; pagination is opt-in and backward-compatible.

**Test:** perf-budget entry for `/api/core/processes`; if paginated, reuse the
`test_list_pagination.py` pattern.

---

### 6. Wizard fragments (`/core/flows/create/*`) — audit for hidden queries — `[ ]`

**Files:** `app/core/backend/backend.py` (the ~10 `/core/flows/create/*` routes),
`app/core/frontend/processes/process-wizard-fragment-*.html`.

**Before:** `process-overview` step = 749 ms, and its *only* API cost is the 636 KB
banner (item 1 fixes that). But each wizard step is a full `render_template` — check the
route handlers don't do per-request queries (process lookup, category lists, unit lists)
that could be cached or moved client-side.

**Approach.** Read each `/core/flows/create/*` handler; note any that query. Most are
static fragments. If a handler loads e.g. the full process to render a summary, confirm
it's a single scoped query, not a list + filter.

**Risk:** low — these are mostly static.

**Test:** `tests/e2e/test_process_wizard_flow.py` already covers the flow; add a
query-count assertion on the heaviest step if one is found.

---

### 7. `/core/executions/live` — verify the overview reuse — `[ ]`

**Files:** `app/core/frontend/core/core2.html` (it renders core2 with
`core2_focus="active_batches_live"`), `app/core/frontend/js/core-active-batches-graph.js`.

**Before:** 753 ms — `system-findings` 636 KB (item 1) + `hub/overview` 2.2 KB + one
process fetch. Already close to optimal once item 1 lands.

**Approach.** Confirm the active-batches graph on this focused view reuses the
`hub/overview` payload (it does on `/core` per !183) and doesn't issue its own
`executions` / `processes?include_steps=true`. If the focused view bypasses the shared
payload, wire it through `window.__core2HubOverview` like the hub does.

**Risk:** low.

**Test:** extend `test_core_load_waterfall.py` with a `/core/executions/live` case
mirroring the `/core` assertions (one overview call, no heavy lists).

---

## Out of scope (noted, not planned here)

- The `{% block scripts %}`-outside-`#page-content` architecture that forces per-page
  `htmx:afterSettle` re-bootstraps (fixed piecemeal for dashboard.js, dilution calc,
  `/core` hub in !193, and item 4 here). A real fix is moving page bootstraps into the
  swapped region or a framework-level "page entered" hook — a base_spa refactor, its own
  piece of work.
- Response compression (gzip/br) at the app tier — would cut every payload including
  `system-findings` further, but that's a deploy/proxy concern, not app code.
