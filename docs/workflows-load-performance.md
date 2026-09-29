# Product workflows pages — load performance

Follows the same playbook as `docs/core-load-performance-design.md` and the sourcemap
work (!192): kill the on-load fan-out, serve a lightweight first paint, lazy-load the
heavy detail when the user asks for it, and never let a payload scale with org history
on the critical path.

Branch: `perf/workflows-load`. Work the checklist top-down; tick items as they land so
this doc is a resumable status. Each item names the file(s), the measured before, the
approach, the risk, and the test.

---

## Status — all 7 items resolved (2026-08-29)

| # | item | outcome |
|---|---|---|
| 1 | slim system-findings payload | **done** — 405 KB → 24 KB on every page |
| 2 | `/core/flows?id` 767 ms inventory query | **fixed by !191** (uncached `run_all_checks`); re-measure on merge |
| 3 | duplicate `/auth/me` | **done** — `CoreAPI.getMe` shared cache; 2 → 1 per page |
| 4 | banner re-fetch on boosted nav | verified — not a bug (banner is `/core/notifications`-only, re-inits fine) |
| 5 | `/core/processes` scaling | **done** — counts via `GROUP BY`, no longer loads all executions |
| 6 | wizard fragment queries | audited — clean |
| 7 | `/core/executions/live` overview reuse | verified — clean |
| 8 | create/edit-workflow wizard "Inputs" step loads 1.3 MB | **done** — `?view=compact`, drop redundant call → 142 KB |

Net: every workflows page dropped from ~640 KB to ~35–45 KB of API payload on first
paint. `/core/flows?id=<p>` still ~1.4 s pending !191. The create/edit-workflow wizard's
Inputs step went 1.3 MB → 142 KB.

### Deep interactive audit (2026-08-29, post items 1/3/5)

Walked every workflows page + tab with Playwright — process list → open a process →
flows2 sub-tabs (Structure / Batches / Inventory) + inventory filters → the full
create-workflow wizard (7 steps) → batch start → execute step. **Every tab / filter click
on flows2 is 0 API calls** (client-side re-render from data loaded on page open — good).
The only fat spot found: **the wizard "Inputs" step (and the Create-Process modal that
shares `create-process-modal.js::loadInventoryItems`) fetched `/api/core/inventory` three
times** — process-scoped, `?type=raw_material` (174 KB), and unfiltered (**1.09 MB**) —
then deduped by name. Fixed: both remaining calls use `?view=compact` and the redundant
`?type=raw_material` call is dropped (the unfiltered set already contains raw materials).
**1,303,832 B → 141,718 B**, 0 console errors, wizard/templates e2e green.

## Methodology

Measured with Playwright against `Whistlebird Ltd` (252 execs, 243 items, 12 processes,
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

### 1. Slim the `system-findings` banner payload — `[x]` (commit: system_findings_cache `_banner_finding_data`)

**Done.** `/api/core/system-findings` 405 KB → 24 KB on `Whistlebird Ltd` (~17x), on
every authenticated page (the sidebar notification badge in `base_spa.html` fetches it on
`DOMContentLoaded` **and** every `htmx:afterOnLoad`). `_banner_finding_data` projects the
`expired_materials` finding's `data` to the fields the banner / badge / Notifications page
actually read (`expired_raw_materials` → id/name/date fields; `impacted_items` →
id/name/`expired_raw_material_id`) and drops the `connections` DAG edge list entirely.
The cached expensive slice on disk and `/api/core/inventory/expired-materials` (full
shape, sourcemap) are untouched. Notifications page + banner verified via Playwright: 47
items, correct dates/names, 0 console errors.

<details><summary>original plan</summary>

**Files:** `app/features/compliance_checks/system_findings_cache.py` (or `corechecks.py` route),
`app/core/frontend/js/system-findings-banner.js`, `tests/test_system_findings_cache.py`,
`tests/test_corechecks_routes.py`.

**Before:** 636 KB on every page; 405 KB is `expired_materials.data`.

**Approach.** The `/api/core/system-findings` response feeds only the banner. Reshape the
per-finding `data` to what the banner actually renders:
- `expired_raw_materials`: `[{id, name, expiry_date}]` — not the full item object.
- `impacted_items`: `[{id, name}]` — not the full item object.
- **drop `connections` entirely** — the banner never touches it. Already done: see the
  "Done" summary above (verified 2026-09-15 by findings-sweep).
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

**Test:** `test_system_findings_cache.py::test_banner_payload_is_slimmed` — response
`findings[].data` has no `connections`, item objects carry only the kept keys.

</details>

---

### 2. `/core/flows?id=<p>` — the 767 ms `inventory?process_id` query — `[x]` (fixed by !191, re-measure on merge)

**Root cause found:** `/api/core/inventory?process_id=<p>` issues **295 queries for 1
item**. ~285 of those are `get_system_findings_by_item` → `runner.run_all_checks()`
running the `expired_materials` DAG traversal **48 times** (once per expired raw material,
org-wide, regardless of the 1-item result). Not a `process_id` index problem — the item
query itself is fast.

**Already fixed on `fix/deploy-console-errors` (MR !191):** that MR routes
`get_system_findings_by_item` through `system_findings_cache.get_check_results()` — the
same cached `expired_materials` slice the dashboard/banner use. `list_inventory` (and the
`?process_id` variant) drops from ~295 queries to ~15. This branch is cut from `main`
which predates !191; **re-measure `/core/flows?id=<p>` once !191 merges** and tick the
sub-parts below only if it's still slow:
- `?view=compact` for flows2's inventory panel if it doesn't render findings badges;
- a `(org_id, source_execution_id)` index if `EXPLAIN` on the process filter still scans.

**Files:** `app/core/backend/backend.py` (`list_inventory`), `app/core/db/repositories/inventory_repo.py`, `app/core/frontend/js/flows2-inventory.js` (or wherever flows2 calls it).

**Before:** 767 ms for ~4 KB (≈15 rows).

**Approach.** Profile `list_inventory` with `process_id` set against `Whistlebird Ltd`
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

### 3. duplicate `/auth/me` — `[x]` (commit: `CoreAPI.getMe`)

**Done.** `/auth/me` was fetched twice on `/core/flows?id=<p>` — the `bizeMascot` profile
Alpine component in `base_spa.html` (**every page**) and flows2-init's `getCurrentUser`.
Added `CoreAPI.getMe()` with a 30 s shared cache; routed `base_spa` `loadProfile`,
`account-info.js` and `flows2-init.js` through it. Now 1 request per page across flows2 /
processes / dashboard, 0 console errors. `execution-modal.js` (`no-store`, audit fields)
and the settings-page 2FA-status reads are deliberately left on direct fetches — they
need a guaranteed-fresh read.

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

### 4. Banner re-fetches on boosted navigation — `[x]` (verified — no action)

**Checked, not a bug.** The findings *banner* element now lives only on
`/core/notifications`. Playwright: a boosted nav dashboard → `/core/notifications`
renders all 47 items, 0 console errors — `system-findings-notifications.js` re-inits fine
on the swap (its script is inside `#page-content`, so htmx re-executes it, unlike the
`/core` hub scripts fixed in !193). The sidebar notification *badge* already re-fetches
on `htmx:afterOnLoad` (`base_spa.html`). Nothing to change.

<details><summary>original plan</summary>

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

</details>

---

### 5. `/core/processes` list — confirm it scales — `[x]` (commit: `count_by_process_and_status`)

**Done.** `list_processes` was already batched (no per-process N+1) but computed
active/completed counts by loading **every org execution with joined steps** into Python
(`list_executions(org_id)`) -- O(execution history). New
`ExecutionRepository.count_by_process_and_status()` does it in one `GROUP BY
process_id, status`. `/api/core/processes` measured 51 ms -> 7 ms, and its query count
is now O(1) in execution history instead of O(n). Per-row payload (`event_summary`,
counts) is small; no pagination needed at current sizes.

<details><summary>original plan</summary>

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

</details>

---

### 6. Wizard fragments (`/core/flows/create/*`) — audit for hidden queries — `[x]` (audited — clean)

**Audited, no action.** Each `/core/flows/create/*` handler does at most
`_flow_process_id_from_request()` + `_assert_flow_process_access(pid)` (one PK+org_id
scoped query) + `_maybe_enforce_flow_wizard_step()` + `render_template`. No lists, no
filter-in-Python, no N+1. The `process-overview` step's 749 ms was entirely the 636 KB
system-findings banner -- item 1 takes it to ~34 KB.

<details><summary>original plan</summary>

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

</details>

---

### 7. `/core/executions/live` — verify the overview reuse — `[x]` (verified — clean)

**Verified.** First paint fires `system-findings` (~24 KB after item 1) + `hub/overview`
(2.2 KB, the shared payload) + one scoped `processes/<id>` -- no `executions`, no
`processes?include_steps=true`. The active-batches graph already consumes
`window.__core2HubOverview` (!183). Nothing to change.

<details><summary>original plan</summary>

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

</details>

---

## Out of scope (noted, not planned here)

- The `{% block scripts %}`-outside-`#page-content` architecture that forces per-page
  `htmx:afterSettle` re-bootstraps (fixed piecemeal for dashboard.js, dilution calc,
  `/core` hub in !193, and item 4 here). A real fix is moving page bootstraps into the
  swapped region or a framework-level "page entered" hook — a base_spa refactor, its own
  piece of work.
- Response compression (gzip/br) at the app tier — would cut every payload including
  `system-findings` further, but that's a deploy/proxy concern, not app code.
