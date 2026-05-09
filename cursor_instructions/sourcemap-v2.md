# Sourcemap V2 — Port to base_spa + redesign

## Goal
Port `sourcemap.html` to extend `base_spa.html` so the page shares the standard sidebar, topbar, HTMX boost, theme switching, and notification badge. Replace the embedded SVG flowchart with a responsive card-based trace layout. Split system findings into selectable tabs. All JS and CSS extracted to separate files.

---

## Phase 0 — Backup

- [x] Copy `app/core/frontend/sourcemap.html` → `app/core/frontend/sourcemap_v1_backup.html`

---

## Phase 1 — File structure

- [x] Create `app/core/frontend/css/sourcemap.css` (extracted + new styles)
- [x] Create `app/core/frontend/js/sourcemap.js` (extracted + rewritten JS)
- [x] Register `sourcemap.css` in the core CSS static route — confirmed, served from `css/` dir automatically
- [x] Register `sourcemap.js` in the core JS static route — confirmed, served from `js/` dir automatically

---

## Phase 2 — HTML shell (`sourcemap.html`)

- [x] Rewrite `sourcemap.html` to `{% extends "shared/base_spa.html" %}`
- [x] `{% block title %}` → "Source Map | Traceability"
- [x] `{% block body_class %}` → `sourcemap-page`
- [x] `{% block head_extras %}` → link `sourcemap.css`
- [x] `{% block content %}` → full page markup (see sections below)
- [x] JS init fires on both `DOMContentLoaded` and `htmx:afterSettle` on `#page-content`

---

## Phase 3 — Page markup (within `{% block content %}`)

### 3a — Search bar
- [x] Full-width sticky search input with clear button
- [x] Autocomplete dropdown (category-grouped: Raw / WIP / Final / Out of Stock / Metadata)
- [x] Autocomplete expanded: Batches / Suppliers / Operators (metadata categories, subordinate)
- [x] Batch-entry selection modal (re-skinned, in HTML + JS)

### 3b — View controls bar
- [x] Segmented toggle: **Timeline** | **Map** | **Table** (was Trace Flow | Table)
- [x] Wastage filter chip
- [x] Legend chips: Raw · WIP · Final · Check Needed (inline, right-aligned, hidden on mobile)

### 3c — Idle state (search prompt)
- [x] Large centered search prompt — no process overview cards
- [x] Subtext: "Search for a material, batch, supplier, or operator to trace its journey"
- [x] Idle state is replaced immediately on search/trace

### 3d — Traced state: impact header
- [x] Item name + type badge + batch (merged with trace header)
- [x] Stat strip: "X processes · Y executions · Z findings" — gives instant overview
- [x] Clear trace button in header

### 3e — Timeline view (default, view=timeline)
- [x] Vertical list of execution entries, chronological
- [x] Each entry: process name + date + flow summary line (Raw → WIP → Final)
- [x] Clicking expands inline item cards (reuses existing card renderer)
- [x] Shared source pill on raw material cards appearing in > 1 execution

### 3f — Map view (view=map)
- [x] Vertical CSS tree — root item at top, branches downward
- [x] Pure `<ul>/<li>` with `border-left` line + `::before` horizontal connector
- [x] One branch per execution group (process name + date label)
- [x] WIP nodes nested under execution, Finals nested under WIP
- [x] No SVG, no coordinates — scrolls vertically on all devices

### 3g — Table view (view=table)
- [x] Shown when "Table" segment is active
- [x] Table with Item / Type / Quantity / Batch / Supplier / Expiry columns
- [x] Empty state message when no trace is active

### 3h — System findings section
- [x] Tab selector: **All** | **Expired Materials** | **Untracked Items** | **Output Expiry** | **Ready Date**
- [x] Badge count on each tab, loaded on page init from all four API endpoints
- [x] Each tab renders finding cards with name + reason
- [x] **Trace ↗** button on each finding fires a trace and populates search input
- [x] `?show=check-needed` URL param → pre-selects Expired Materials tab on load

---

## Phase 4 — CSS (`sourcemap.css`)

- [x] All CSS written to `app/core/frontend/css/sourcemap.css`
- [x] Existing: search bar, controls, item cards, wastage, findings, modal
- [x] `.sm-idle-state` — centered prompt (no process grid)
- [x] `.sm-impact-header` — stat strip (X processes · Y executions · Z findings)
- [x] `.sm-timeline` — vertical timeline container
- [x] `.sm-timeline-entry` — one execution entry with dot + line + content
- [x] `.sm-timeline-dot` / `.sm-timeline-line` — CSS dot and vertical connector
- [x] `.sm-timeline-content` — process name, date, flow summary, expand button
- [x] `.sm-timeline-detail` — expandable item cards
- [x] `.sm-tree-container` — map view outer container
- [x] `.sm-tree-root` — root node
- [x] `.sm-tree-node` + `--raw/wip/final` — individual tree nodes
- [x] `.sm-tree-children` — `<ul>` with border-left line
- [x] `.sm-tree-item` — `<li>` with `::before` horizontal connector
- [x] `.sm-tree-group-label` — execution header (process + date) within tree

---

## Phase 5 — JS (`sourcemap.js`)

- [x] All existing data-loading functions retained (processes, inventory, executions, metadata, wastage, findings)
- [x] `currentView` defaults to `'timeline'` (was `'flow'`)
- [x] `lastTraceResult` state variable — stores last trace for view re-render on toggle
- [x] `smRenderIdleState()` — replaces `smRenderOverview()` (no process cards; clean search prompt)
- [x] `smRenderTrace(traceResult)` — replaces `smRenderFlowRows()`; builds impact header + dispatches to timeline/map/table
- [x] `smBuildImpactHeader(tracedItem, groups)` — merged trace header + stat strip + clear button
- [x] `smRenderTimeline(groups, sharedSourceIds)` — vertical timeline, expandable entries
- [x] `smRenderMap(groups, tracedItem)` — vertical CSS tree (ul/li, no SVG)
- [x] `smBuildExecutionGroups()` retained — powers both timeline and map
- [x] `smBuildItemCard()` retained — powers expanded detail in timeline entries
- [x] View toggle updated for 3 views (timeline/map/table); re-renders from `lastTraceResult` on switch
- [x] Search expansion: Batches, Suppliers, Operators sections added to autocomplete
- [x] `smTraceByBatch(batch, items)` — traces all items with a given batch number
- [x] `smTraceBySupplier(supplier, items)` — traces all items from a supplier
- [x] `smTraceByPerson(person, executions)` — gathers items from executions by that person
- [x] `smClearTrace()` calls `smRenderIdleState()` (was `smRenderOverview()`)
- [x] HTMX re-init: script inside #page-content, readyState guard

---

## Phase 6 — Verify & clean up

- [ ] Test idle state (clean search prompt, no process cards)
- [ ] Test trace: single raw material → single process (timeline + map)
- [ ] Test trace: single raw material → multiple processes/executions
- [ ] Test view switching (timeline ↔ map ↔ table without re-fetch)
- [ ] Test backward trace (from WIP or final item)
- [ ] Test batch search → modal → trace
- [ ] Test supplier search → modal → trace
- [ ] Test wastage toggle
- [ ] Test all four system findings tabs with badge counts
- [ ] Test `?show=check-needed` param
- [ ] Test HTMX navigation (navigate away and back — page re-inits cleanly)
- [ ] Test mobile layout (timeline vertical, map tree, expand/collapse)
- [ ] Test dark mode (inherits from base_spa theme vars)
- [ ] Confirm `sourcemap_v1_backup.html` is intact and not served by any route

---

## UX design decisions

### Idle state
- No process overview cards (they linked to flows2, not tracing — confusing on a tracing page)
- Centered search prompt with instructional subtext
- Simple, focused: one job (trace something)

### After search: always show impact header
"Wheat Flour · WF-2024-03  ·  Raw  ·  3 processes · 7 executions · 1 finding"
- Gives instant scale before user looks at any detail

### Timeline view (default)
- Chronological story: each entry is one execution where the item was touched
- Expandable: click entry → see all item cards for that execution
- Works identically on mobile (already vertical)
- Aligns with future event sourcing: each entry = one entity event

### Map view (vertical tree, no SVG)
```
● Wheat Flour · WF-2024-03
│
├─ Bread Mix · 14 Apr
│    └─● Dough Mix A (WIP, 25 kg)
│           └─● Sourdough Loaf (Final, 8 units)
│
└─ Bread Mix · 16 Apr
     └─● Dough Mix A (WIP, 20 kg)
            └─● Sourdough Loaf (Final, 6 units)
```
- Pure CSS tree (border-left + ::before connectors)
- Only grows vertically → works on all screen sizes
- Branches = executions; depth = material stages

### Metadata tracing
Materials are primary; metadata is secondary but clearly available.
- Batches: find all items with that batch → modal → pick → trace
- Suppliers: find all items from supplier → modal → pick → trace
- Operators: find executions completed_by that person → gather items → modal → pick → trace
- Execution metadata (existing): trace first linked inventory item

### Future event sourcing alignment
- Timeline view maps directly to `entity_events` table (one entry per event)
- `as_of` parameter enables "show me the timeline up to this date" — no UI redesign needed
- Impact header stat counts can come from `entity_event_summaries` read model
- Map view structure stays the same; data source changes from mutable tables to event log

---

## API endpoints used

| Endpoint | Purpose |
|---|---|
| `GET /api/core/processes` | Process name resolution in groups |
| `GET /api/core/inventory` | Search autocomplete + batch/supplier pools |
| `GET /api/core/executions` | Resolve execution_id → process name + date + operator |
| `GET /api/core/inventory/trace/<id>` | Forward trace |
| `GET /api/core/inventory/trace-backward/<id>` | Backward trace |
| `GET /api/core/inventory/wastage` | Wastage toggle view |
| `GET /api/core/inventory/out-of-stock` | Out-of-stock items in search |
| `GET /api/core/inventory/expired-materials` | Findings: Expired Materials tab |
| `GET /api/core/inventory/untracked-items` | Findings: Untracked Items tab |
| `GET /api/core/system-findings` | Findings: Output Expiry + Ready Date tabs |
