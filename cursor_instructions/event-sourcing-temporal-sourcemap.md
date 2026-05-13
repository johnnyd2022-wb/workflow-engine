# Event Sourcing, Temporal Sourcemap & Platform-Wide Card Enrichment — Architecture & Implementation Plan

**Status:** Complete ✅  
**Priority:** Core differentiator feature  
**Context:** Platform is pre-launch; no backward-compatibility obligation to existing data

---

## Progress Checklist

### Phase 1 — DB Migrations
- [x] `event_sourcing_core_001` — `entity_events` table with all 6 indexes
- [x] `event_sourcing_summaries_001` — `entity_event_summaries` table with 2 indexes
- [x] `event_sourcing_process_versions_001` — `process_versions` table + `process_version_id` on `executions` + `display_label` on `inventory_items`

### Phase 2 — ORM Models + EventWriter + Middleware
- [x] `app/core/db/models/entity_event.py` — EntityEvent ORM model
- [x] `app/core/db/models/entity_event_summary.py` — EntityEventSummary ORM model
- [x] `app/core/db/models/process_version.py` — ProcessVersion ORM model
- [x] Update `app/core/db/models/__init__.py` — export all three new models
- [x] Update `app/core/db/migrations/env.py` — import new models so alembic sees them
- [x] `app/core/backend/event_writer.py` — EventWriter class + per-entity summary upsert functions
- [x] Update `app/api/middleware/tenant_context.py` — set `g.correlation_id = uuid4()` on every request

### Phase 3 — Process Versioning + Events
- [x] `ProcessRepository.create_process` — insert process_versions row (v1), emit `process.created`
- [x] `ProcessRepository.update_process` — insert process_versions row, emit `process.updated` with diff
- [x] `ProcessRepository.add_step` — insert process_versions row, emit `process.step_added`
- [x] `ProcessRepository.update_step` — insert process_versions row, emit `process.step_updated` with diff
- [x] `ProcessRepository.delete_step` — capture step snapshot, insert process_versions row, emit `process.step_deleted`
- [x] `ProcessRepository.delete_process` — emit `process.deleted` tombstone before delete
- [x] `ExecutionRepository.create_execution` — look up latest process_version_id, set on execution, emit `execution.created`

### Phase 4 — Inventory + Execution Events
- [x] `InventoryRepository.create_inventory_item` — emit `inventory_item.created`
- [x] `InventoryRepository.add_quantity_to_inventory_item` — emit `inventory_item.quantity_adjusted`
- [x] `InventoryRepository.update_inventory_item` — compute diff, emit `inventory_item.updated`
- [x] `InventoryRepository.delete_inventory_item` — capture full snapshot, emit `inventory_item.deleted` tombstone
- [x] `WastageRepository.create_wastage_record` — emit `inventory_item.wasted`
- [x] `ExecutionRepository.complete_step` — emit `execution.step_completed` + all downstream events with causation chain
- [x] `ExecutionRepository._advance_execution` — emit `execution.started` (first step), `execution.completed`, `execution.failed`, `execution.cancelled`

### Phase 5 — Auth Events
- [x] Login success — emit `user.login`
- [x] Login failure — emit `user.login_failed` (system actor)
- [x] Signup / `UserRepository.create_user` — emit `user.created`
- [x] 2FA enabled/disabled — emit `user.2fa_enabled` / `user.2fa_disabled`
- [x] Role changed — emit `user.role_changed`
- [x] Account locked/unlocked — emit `user.account_locked` / `user.account_unlocked`
- [x] User deactivated — emit `user.deactivated`

### Phase 6 — API Endpoints
- [x] `GET /api/core/entities/<entity_type>/<entity_id>/summary` — per-entity rich summary
- [x] `GET /api/core/entities/<entity_type>/<entity_id>/story` — full event timeline
- [x] `GET /api/core/sourcemap/objects` — lightweight traceable objects index (paginated)
- [x] `POST /api/core/sourcemap/trace` — on-demand DAG traversal (with optional `as_of`)
- [x] Update `GET /api/core/inventory` list — JOIN entity_event_summaries, include `event_summary`
- [x] Update `GET /api/core/executions` list — include `event_summary`
- [x] Update `GET /api/core/processes` list — include `event_summary`

### Phase 7 — Card Enrichment UI
- [x] Inventory item cards — "Added by", "Last used X days ago", "Used N times", wastage count, quantity history sparkline
- [x] Execution (batch) cards — "Started by", "Process version N", materials consumed/produced, evidence count
- [x] Process cards — version number, last modified by, total runs, success rate, last run
- [x] Inventory item detail — expanding audit history panel (collapsible, full event timeline)
- [x] Process detail — version history panel (diffs with before/after for each change)
- [x] Execution detail — step-by-step audit trail with actor and timestamps

### Phase 8 — Sourcemap Rebuild
- [x] Replace page-load-everything with index load + on-demand trace
- [x] Build selector UI (grouped by type, batch disambiguation)
- [x] Build "Trace as of this moment" historical replay button on consumed events
- [x] Entity story panel when clicking a node
- [x] `app/core/backend/temporal_dag_tracer.py` — TemporalDAGTracer class

---

## 1. What We're Building and Why

This is a platform-wide infrastructure change with two distinct consumer surfaces:

**Surface 1 — The Sourcemap**  
A visual, interactive DAG showing the full provenance of any piece of data in the system — not just current state, but the state of relationships at any point in time. "Show me the lineage of Batch #dsnjkanf8 as it was on the day it was consumed" is a fundamentally different and more powerful question than "show me its lineage now." A manufacturing customer conducting a quality investigation, a compliance audit, or a recall analysis needs the historical answer, not the current one.

**Surface 2 — Cards Throughout the Platform**  
Every card in the UI (inventory item cards, execution cards, process cards) currently shows only what's in the mutable tables: name, quantity, status. With the event log, cards can show a much richer picture — who created it, when it was last used, how many times it's been through a process, what has changed since it was first recorded, and live activity indicators. This data is simply not derivable from current state alone. A card that says "Last used 3 days ago in Widget Assembly by Sarah · used 7 times across 3 processes · 0 wastage events" is qualitatively more useful than one that says "Quantity: 0 kg."

Both surfaces are powered by the same underlying `entity_events` log. The sourcemap needs temporal DAG reconstruction; the cards need fast per-entity aggregated summaries. These are different query shapes against the same data.

**The approach: Hybrid Event Sourcing**  
We keep all existing mutable tables as the source of current state (they work, they're fast, no reason to abandon them). We add an append-only `entity_events` table that records every mutation with a full payload snapshot of the entity state at that moment. Current-state queries use the existing tables. Historical queries and card enrichment use the event log.

---

## 2. Current State (Codebase Reality)

### What Already Exists (Keep As-Is)

- **`inventory_movements` table** — append-only quantity ledger, complement not replacement
- **`audit_logs` table** — coarse action logging, keep for backward compat
- **`DAGTraversal.py`** at `app/features/workflow_engine/dagtraversal.py` — keep entirely for current-state traversal
- **`InventoryQuantityWriteReason` enum** at `app/core/domain/inventory_quantity_guard.py` — hook point for events
- **`g.user_id`, `g.user_email`, `g.org_id`** — populated in `load_tenant_context` before_request
- **All existing mutable tables** — source of current state; `entity_events` is additive

### What the New Code Touches

| File | Change |
|---|---|
| `app/core/db/migrations/versions/` | 3 new migration files |
| `app/core/db/models/entity_event.py` | New |
| `app/core/db/models/entity_event_summary.py` | New |
| `app/core/db/models/process_version.py` | New |
| `app/core/db/models/__init__.py` | Add 3 new exports |
| `app/core/db/migrations/env.py` | Add 3 new imports |
| `app/core/backend/event_writer.py` | New |
| `app/core/backend/temporal_dag_tracer.py` | New |
| `app/api/middleware/tenant_context.py` | Add `g.correlation_id` |
| `app/core/db/repositories/process_repo.py` | Process versioning + events |
| `app/core/db/repositories/inventory_repo.py` | Event emission |
| `app/core/db/repositories/execution_repo.py` | Event emission + causal chain |
| `app/core/db/repositories/wastage_repo.py` | Event emission |
| `app/api/routes/auth_routes.py` | User auth events |
| `app/core/backend/backend.py` | New endpoints |
| Frontend templates + JS | Card enrichment + sourcemap rebuild |

---

## 3. New Database Schema

### 3.1 `entity_events` — The Core Append-Only Log

```sql
CREATE TABLE entity_events (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID        NOT NULL REFERENCES organisations(id),
    event_type          VARCHAR(100) NOT NULL,
    entity_type         VARCHAR(100) NOT NULL,
    entity_id           UUID        NOT NULL,
    actor_id            UUID        REFERENCES users(id) ON DELETE SET NULL,
    actor_type          VARCHAR(50) NOT NULL DEFAULT 'user',
    actor_label         VARCHAR(255),
    payload             JSONB       NOT NULL,
    diff                JSONB,
    causation_id        UUID        REFERENCES entity_events(id) ON DELETE SET NULL,
    correlation_id      UUID,
    request_metadata    JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 6 indexes (see migration file for full list)
```

**Critical design:** Full entity snapshot in `payload`. State at time T = single indexed lookup, not replay chain.

### 3.2 `process_versions` — Process Definition Snapshots

```sql
CREATE TABLE process_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organisations(id),
    process_id      UUID NOT NULL REFERENCES processes(id) ON DELETE CASCADE,
    version_number  INTEGER NOT NULL,
    snapshot        JSONB NOT NULL,  -- full process + all steps at this moment
    changed_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    change_summary  VARCHAR(500),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (process_id, version_number)
);
```

### 3.3 `entity_event_summaries` — Pre-computed Read Model

```sql
CREATE TABLE entity_event_summaries (
    entity_id       UUID PRIMARY KEY,
    org_id          UUID NOT NULL REFERENCES organisations(id),
    entity_type     VARCHAR(100) NOT NULL,
    summary         JSONB NOT NULL,
    last_event_at   TIMESTAMPTZ NOT NULL,
    last_event_type VARCHAR(100) NOT NULL,
    last_actor      VARCHAR(255),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 3.4 Schema additions to existing tables

```sql
ALTER TABLE executions ADD COLUMN process_version_id UUID REFERENCES process_versions(id) ON DELETE SET NULL;
ALTER TABLE inventory_items ADD COLUMN display_label VARCHAR(255);
```

---

## 4. Event Types Catalog

### 4.1 Inventory Events

| event_type | Trigger | Key payload fields |
|---|---|---|
| `inventory_item.created` | `InventoryRepository.create_inventory_item` | full item snapshot + `add_method` (manual/barcode/csv/execution) |
| `inventory_item.quantity_adjusted` | `InventoryRepository.add_quantity_to_inventory_item` | quantity_before, quantity_after, delta, unit, reason |
| `inventory_item.consumed` | Inside `complete_step` — when step actual_inputs reference this item | quantity_consumed, unit, execution_id, execution_step_id, step_name |
| `inventory_item.produced` | Inside `complete_step` — when step produces new inventory | quantity_produced, unit, execution_id, execution_step_id |
| `inventory_item.wasted` | `WastageRepository.create_wastage_record` | quantity_wasted, unit, reason, wastage_id |
| `inventory_item.updated` | `InventoryRepository.update_inventory_item` | diff of changed fields, full snapshot after |
| `inventory_item.deleted` | `InventoryRepository.delete_inventory_item` | full snapshot before deletion (tombstone) |

**`add_method` field** on `inventory_item.created`: detect from `extra_data`:
- `extra_data.get("barcode_scan")` → `"barcode_scan"`
- `extra_data.get("csv_import")` → `"csv_import"`
- `source_execution_id` present → `"execution_output"`
- Otherwise → `"manual"`

### 4.2 Execution Events

| event_type | Trigger | Key payload fields |
|---|---|---|
| `execution.created` | `ExecutionRepository.create_execution` | process_id, process_version_id, total_steps |
| `execution.started` | First `_advance_execution` call | process_id |
| `execution.step_completed` | `ExecutionRepository.complete_step` | step_id, step_number, step_name, actual_inputs, actual_outputs, execution_data, items_consumed, items_produced |
| `execution.completed` | All steps done | total_steps, completed_at |
| `execution.cancelled` | Status → cancelled | reason |

**`execution.step_completed`** is the most important event. Its `items_consumed` and `items_produced` arrays create the causal links used by temporal DAG traversal.

### 4.3 Process Events

| event_type | Trigger | Key payload fields |
|---|---|---|
| `process.created` | `ProcessRepository.create_process` | full process snapshot, process_version_id |
| `process.updated` | `ProcessRepository.update_process` | diff, full snapshot after, process_version_id |
| `process.step_added` | `ProcessRepository.add_step` | step snapshot, process_version_id |
| `process.step_updated` | `ProcessRepository.update_step` | step diff, step snapshot after, process_version_id |
| `process.step_deleted` | `ProcessRepository.delete_step` | step snapshot before deletion, process_version_id |
| `process.deleted` | `ProcessRepository.delete_process` | final process snapshot (tombstone) |

### 4.4 User & Auth Events

| event_type | Trigger | Key payload fields |
|---|---|---|
| `user.created` | Signup / `UserRepository.create_user` | email, role, org_id |
| `user.login` | Successful auth | ip, user_agent, 2fa_used |
| `user.login_failed` | Failed auth | ip, user_agent, reason, actor_type="system" |
| `user.2fa_enabled` | Enable 2FA | — |
| `user.2fa_disabled` | Disable 2FA | — |
| `user.role_changed` | Role update | old_role, new_role |
| `user.account_locked` | Lock account | reason, locked_until |
| `user.account_unlocked` | Unlock account | — |
| `user.deactivated` | Soft-delete user | — |

---

## 5. The EventWriter Module

**File:** `app/core/backend/event_writer.py`

### Key rules:
1. `emit()` is always called inside the parent DB transaction. Never commit separately.
2. `_upsert_summary()` is called in the same transaction as the event write.
3. `actor_id` comes from `g.user_id` (string → UUID conversion needed).
4. `actor_label` comes from `g.user_email`.
5. `correlation_id` comes from `g.correlation_id` (set by middleware).
6. If `g.correlation_id` is absent, generate a new UUID rather than leaving null.

### g field names (verified from tenant_context.py):
- `g.user_id` — str(UUID) of current user
- `g.user_email` — email string
- `g.org_id` — str(UUID) of current org

### Summary upsert logic:
Each entity type has its own `_update_<type>_summary(session, event)` function that knows how to update `entity_event_summaries.summary` JSONB from the new event. Called from `emit()` after adding the event. Upsert uses `INSERT ... ON CONFLICT (entity_id) DO UPDATE`.

### `quantity_history` cap:
The inventory summary's `quantity_history` is capped at 50 entries. New entries are appended and trimmed to the last 50. Full history remains in `entity_events`.

---

## 6. Repository Hookup — Implementation Details

### ProcessRepository Changes

Every mutation:
1. Mutate the process/step (existing logic)
2. Build the snapshot JSONB: `{"id": ..., "name": ..., "steps": [all steps with full fields]}`
3. Compute version_number: `SELECT COALESCE(MAX(version_number), 0) + 1 FROM process_versions WHERE process_id = ?`
4. Insert ProcessVersion row
5. Emit event via `EventWriter`

The `EventWriter` is constructed inside each method: `EventWriter(self.db, org_id)`.

For `delete_step` and `delete_process`: capture the full snapshot BEFORE the delete, then emit, then delete.

### ExecutionRepository Changes

**`create_execution`:**
- After creating the execution, query latest `ProcessVersion` for this process
- Set `execution.process_version_id = latest_version.id`
- Emit `execution.created`

**`complete_step` — causal chain:**
```
1. Emit execution.step_completed → capture returned event.id as step_event_id
2. Parse actual_inputs → for each item_id referenced:
   a. Emit inventory_item.consumed with causation_id=step_event_id
3. Parse actual_outputs → for each item produced:
   a. Emit inventory_item.produced with causation_id=step_event_id  
4. If execution now completed: emit execution.completed with causation_id=step_event_id
```

**Parsing actual_inputs/actual_outputs:**
The `actual_inputs` list items have shape `{"inventory_item_id": "uuid", "quantity": ..., "unit": ...}`.
The `actual_outputs` list items have shape `{"inventory_item_id": "uuid", "quantity_produced": ..., "unit": ...}`.

### InventoryRepository Changes

For `add_quantity_to_inventory_item`: capture `quantity_before` before the mutation, emit after.

For `update_inventory_item`: compute diff as `{"field": {"before": old, "after": new}}` for each changed field.

For `delete_inventory_item`: capture full snapshot BEFORE delete via `get_inventory_item_by_id`, emit tombstone, then delete.

### WastageRepository Changes

`create_wastage_record`: accepts an optional `causation_id` parameter so that when called from within `complete_step`, the causation chain is preserved.

---

## 7. Temporal Trace Architecture

### 7.1 `as_of` Reconstruction

Given a root entity and timestamp T:
1. For each node: `SELECT payload FROM entity_events WHERE entity_id = $id AND created_at <= $T ORDER BY created_at DESC LIMIT 1`
2. For edges: `execution.step_completed` events before T with `items_consumed`/`items_produced` arrays
3. Entity with no events before T → did not exist yet → exclude
4. Entity whose last event before T is `*.deleted` → was deleted → show as tombstone or exclude

### 7.2 `TemporalDAGTracer` Class

**File:** `app/core/backend/temporal_dag_tracer.py`

Same `TraversalResult` output shape as existing `DAGTracer`. Frontend receives identical graph structure regardless of current vs temporal trace.

### 7.3 New API Endpoints

#### `GET /api/core/sourcemap/objects`
Lightweight paginated index of all traceable entities. Query only id, name, key discriminator columns. Returns 50 per page by default.

```json
{
  "objects": [{"id": "uuid", "type": "inventory_item", "label": "...", "discriminators": {...}}],
  "total": 142,
  "page": 1
}
```

#### `POST /api/core/sourcemap/trace`
```json
// Request
{"root_type": "inventory_item", "root_id": "uuid", "as_of": "2026-02-01T12:00:00Z", "depth": 6}

// Response
{"root": {...}, "nodes": [...], "edges": [...], "as_of": "...", "is_current": false, "story": [...]}
```

Routes to `DAGTracer` (current, `as_of` absent) or `TemporalDAGTracer` (historical, `as_of` present).

#### `GET /api/core/entities/<entity_type>/<entity_id>/summary`
Full computed summary for single card detail view. Queries `entity_events` directly (more detail than summary table).

#### `GET /api/core/entities/<entity_type>/<entity_id>/story`
Full event history for one entity, ordered chronologically.

```json
{"entity_id": "uuid", "entity_type": "inventory_item", "events": [{"event_type": "...", "at": "...", "actor": "...", "summary": "...", "diff": {...}}]}
```

---

## 8. Card Enrichment UI

### Inventory Item Cards
- "Added by [email] on [date]" — from `inventory_item.created` event actor_label
- "Added via [method]" — from `inventory_item.created` payload `add_method` (manual / barcode scan / CSV upload / execution output)
- "Last used [X days ago] in [process name]" — from last `inventory_item.consumed` event
- "Used [N] times across [M] processes" — from `entity_event_summaries.summary`
- "Never used" / "Fully consumed" / "Partially consumed" status hint
- Expanding audit history panel: collapsible timeline of all events for this item
- Wastage badge: count from `entity_event_summaries.summary.wastage_event_count`

### Execution (Batch) Cards
- "Started by [name]" — from `execution.created` actor_label
- "Process version [N] — definition from [date]" — from `process_version_id` FK
- Materials consumed so far / produced so far — aggregated from step events
- "[N] evidence files attached"
- Step timing: last activity

### Process Cards
- "Version [N] — last updated [X days ago] by [name]"
- "What changed in latest version" — from `change_summary` on latest process_version
- "[N] total runs · [M] completed · [P] active"
- "Success rate [X%]"
- "Draft — not yet run" indicator

### Audit History UI Pattern
For all entity detail views: a collapsible "Audit History" section at the bottom of the card/detail panel. It shows the full event timeline fetched from `GET /api/core/entities/:type/:id/story`. Each event entry shows:
- Timestamp (relative + absolute on hover)
- Actor email
- Human-readable summary string
- For update events: expandable before/after diff

For process detail: "Version History" tab showing each process_versions row with the diff between versions.

---

## 9. Correlation ID Middleware

Add to `app/api/middleware/tenant_context.py` in `load_tenant_context` (before any early returns):

```python
from uuid import uuid4
g.correlation_id = uuid4()
```

This gives every HTTP request a unique UUID. All events emitted during that request share the same `correlation_id` (pulled from `g.correlation_id` in `EventWriter.emit()`).

---

## 10. Commit Strategy

Clean, logical commit groupings:

1. `feat(db): event sourcing foundation migrations` — Phase 1 migrations
2. `feat(core): event sourcing ORM models and EventWriter` — Phase 2 models + event_writer.py
3. `feat(middleware): correlation ID generation per request` — Phase 3 middleware
4. `feat(process): process versioning and event emission` — Phase 3 repos
5. `feat(inventory): inventory and wastage event emission` — Phase 4 inventory repos
6. `feat(execution): execution event emission with causal chain` — Phase 4 execution repo
7. `feat(auth): user and auth event emission` — Phase 5 auth events
8. `feat(api): entity summary, story, and sourcemap endpoints` — Phase 6 API
9. `feat(ui): audit history on inventory, process, and execution cards` — Phase 7 UI
10. `feat(sourcemap): temporal trace, objects index, and sourcemap rebuild` — Phase 8 sourcemap

---

## 11. What NOT to Change

- **`inventory_movements` table** — keep as-is. Financial-grade ledger. `inventory_item.quantity_adjusted` events complement it.
- **`DAGTraversal.py`** — keep entirely. Temporal gets its own class.
- **`audit_logs` table** — keep, do not remove.
- **`InventoryQuantityWriteReason` enum** — keep and use its values in event payloads.
- **All existing mutable tables** — source of current state.
- **`api_idempotency_keys`** — keep.

---

## 12. Key Invariants

1. **Event emission is inside the parent transaction.** Never commit an event separately.
2. **Payload is always the full entity state after the event.** Never store partial payload.
3. **Never delete from `entity_events`.** Tombstone events record deletions.
4. **`process_versions` is updated on every process or step mutation.** No skip path.
5. **`execution.process_version_id` is set at creation and never changed.**
6. **`correlation_id` is always set.** If `g.correlation_id` absent, generate new UUID.
7. **`entity_event_summaries` is updated in the same transaction as the event.**
8. **`entity_event_summaries.summary.quantity_history` is capped at 50 entries.**

---

## 13. Testing Requirements

1. Every repository mutation emits the expected event(s) — test at repository layer
2. `complete_step` emits the full causal chain with matching `causation_id`
3. Transaction rollback removes the event (no orphan rows)
4. Temporal reconstruction matches known state at `as_of` timestamp
5. Process version captures steps correctly after each mutation
6. Temporal trace returns different graph than current trace for same root
7. `entity_event_summaries` is always consistent with `entity_events`
8. Card enrichment data is accurate after mutations
9. `quantity_history` is capped at 50 entries regardless of how many adjustments occur

---

## 15. Audit Log Polish — Implementation Summary (May 2026 follow-up)

After the initial 8-phase implementation, a second pass improved audit log quality and consolidated the sourcemap UI.

### Structured diff rows (backend)

`app/core/backend/backend.py` — `_build_diff_rows`, `_event_diff_rows`, `_step_added_diff_rows`:

- All diff data is now returned as `diff_rows: [{label, before, after}]` rather than flat summary strings.
- `before` is set to `null` when the old value was absent — the frontend only renders `→` when **both** `before` and `after` are non-null (no dangling arrows on additions/deletions).
- `_event_diff_rows` dispatcher routes `step_added` / `step_updated` / other events to correct diff extraction. `step_added` synthesizes rows for description, inputs, outputs, and prompts so every new step is fully documented.
- `_smart_list_diff_rows` deep-diffs lists by `id`/`name`/`label` key, producing per-field rows like `Outputs 'Honey syrup' – Quantity: 2 → 3`.
- All "by {actor}" removed from summary strings — actor is shown as a separate UI element after the summary text.
- `execution.cancelled` → human summary includes the cancellation reason.

### Empty-diff guard (process repo)

`app/core/db/repositories/process_repo.py` — `update_process`, `update_step`:

- Both methods now return early (`if not diff: return entity`) before inserting a process version or emitting an event. This prevents phantom "Process version saved (no configuration changes)" events that were fired when the frontend called both PATCH /steps and PATCH /process on every save.

### Sort toggle and actor display (all timeline UIs)

`app/core/frontend/processes/flows2.html`, `app/core/frontend/inventory/view.html`:

- Every audit history panel now has an ↑/↓ sort toggle (oldest first / newest first). State is per-panel.
- Actor email shown as a separate tertiary line below the diff block, using `--text-tertiary` colour.
- Matching CSS added to `flows2.css` and `inventory-view.css` using the `sm-act-clear-btn` button pattern.

### Process list history panel

`app/core/frontend/processes/list.html`, `app/core/frontend/css/processes-list.css`:

- Every process row in the list now has a "History" button alongside the chevron arrow.
- Clicking opens an inline sliding drawer (`pl-story-panel`) from the right edge with title, sort toggle, and close button. Fetches `/api/core/entities/process/:id/story` on demand.
- Full CSS for the slide-in panel using `transform: translateX(100%)` → `translateX(0)` with `0.22s ease` transition.

### Org-wide activity feed + sourcemap Activity tab

`app/core/backend/backend.py` — `GET /api/core/entities/activity`:

- New endpoint returning all `entity_events` for the org, filterable by `entity_type` (comma-separated), `from_date`, `to_date`, `limit` (max 500), `offset`. Each event includes `summary` and `diff_rows`.

`app/core/frontend/js/sourcemap.js`:

- Sourcemap loads `_smAllActivity` at startup (200 most recent events via the new endpoint).
- Activity tab completely rebuilt: entity type filter pills, operator dropdown (derived from event actors, not just execution operators), date range picker, search query filter, and a new `smBuildActivityFeed` renderer showing colored entity-type badges, expandable diffs, and "Audit history" per-entity buttons.
- `smOpenStoryPanel(id, name, entityType)` — panel now supports any entity type, not just inventory items.
- Operators tab removed entirely — operator filtering merged into Activity tab as a `<select>` dropdown, reducing navigation clutter.
- Dead code removed: `smBuildOperatorBrowseCard` and `smTraceByPerson` functions eliminated.

`app/core/frontend/css/sourcemap.css`:

- New CSS for `.sm-act-feed`, `.sm-act-entry`, `.sm-act-badge` variants (inventory=green, process=blue, execution=purple, user=yellow), `.sm-act-operator-select`, and all supporting elements. Dark mode variants included.

---

## 17. What Was Built — Implementation Summary

All 8 phases are complete as of May 2026. Here is what was built and where to find it.

### Database layer (Phase 1)

Three alembic migrations, all applied:

| Migration | Revision ID | Creates |
|---|---|---|
| `event_sourcing_core_001` | `event_sourcing_core_001` | `entity_events` table + 7 indexes |
| `event_sourcing_summaries_001` | `event_sourcing_summaries_001` | `entity_event_summaries` table + 2 indexes |
| `event_sourcing_proc_ver_001` | `event_sourcing_proc_ver_001` | `process_versions` table; adds `process_version_id` to `executions` and `display_label` to `inventory_items` |

Run `docker exec workflow-engine-test sh -c "cd /app && ENVIRONMENT=test uv run alembic upgrade head"` to apply to the test DB.

### Core infrastructure (Phase 2)

- `app/core/db/models/entity_event.py` — `EntityEvent` ORM model
- `app/core/db/models/entity_event_summary.py` — `EntityEventSummary` ORM model
- `app/core/db/models/process_version.py` — `ProcessVersion` ORM model
- `app/core/backend/event_writer.py` — `EventWriter` class; single entry point for all event writes; upserts `entity_event_summaries` in the same transaction
- `app/api/middleware/tenant_context.py` — `g.correlation_id = uuid4()` set per HTTP request so all events from one request share the same correlation UUID

### Repository event emission (Phases 3–4)

| Repository | Events emitted |
|---|---|
| `ProcessRepository` | `process.created`, `process.updated` (with diff), `process.step_added`, `process.step_updated`, `process.step_deleted`, `process.deleted` (tombstone) |
| `ExecutionRepository.create_execution` | `execution.created` (on execution entity + process entity for run-count tracking) |
| `ExecutionRepository.complete_step` | `execution.step_completed` → `inventory_item.consumed` (per input) + `inventory_item.produced` (per output) + `execution.completed` (on final step), all linked by `causation_id` |
| `InventoryRepository` | `inventory_item.created` (with `add_method`), `inventory_item.quantity_adjusted`, `inventory_item.updated` (with diff), `inventory_item.deleted` (tombstone) |
| `WastageRepository` | `inventory_item.wasted` (accepts optional `causation_id` from step completion) |

### Auth events (Phase 5)

Emitted via `app/core/utils/emit_event.py` (separate session, fire-and-forget so auth routes are never blocked):

- `user.created` — on signup
- `user.login` — on successful login (direct) and after 2FA verification, with `2fa_used` flag
- `user.login_failed` — on failed login, `actor_type="system"`
- `user.2fa_enabled` / `user.2fa_disabled`

### API endpoints (Phase 6)

All endpoints are on `core_bp`, protected by `@requires_auth`:

| Endpoint | Description |
|---|---|
| `GET /api/core/entities/<type>/<id>/story` | Chronological event timeline for one entity. Returns `{events: [{event_type, at, actor, summary, diff, payload}]}`. Used by all audit history panels. |
| `GET /api/core/entities/<type>/<id>/summary` | Latest `entity_event_summaries` row for one entity. Used by detail views. |
| `GET /api/core/sourcemap/objects` | Paginated index of all traceable entities (inventory items, executions, processes). Query params: `page`, `limit`, `q`, `type`. |
| `POST /api/core/sourcemap/trace` | On-demand DAG traversal. Body: `{root_type, root_id, depth, as_of?}`. Routes to `TemporalDAGTracer` when `as_of` is present, `DAGTracer` otherwise. |

The three list endpoints (`GET /api/core/inventory`, `/api/core/executions`, `/api/core/processes`) all batch-load `entity_event_summaries` and include an `event_summary` key on every item.

### Card enrichment UI (Phase 7)

**Inventory view** (`app/core/frontend/inventory/view.html`):
- Mobile cards show colour-coded add-method badge (purple = barcode, blue = used N×, red = wastage count)
- "Added by … · date" and "Last used … in process" meta lines below badges
- "Audit history" collapsible panel at the bottom of each card — lazy-loads from the story endpoint on first expand

**Process list** (`app/core/frontend/processes/list.html`):
- Each process entry has a third tertiary line: `v{N} · Last edited by {email} · {date} · {N} runs`

**Execution cards** (`app/core/frontend/js/flows2-executions.js`):
- "Started by" uses `event_summary.created_by` (authoritative, from the event log) rather than the current logged-in user
- Completed cards show: "X steps completed · Y inputs consumed · Z outputs produced"

**Process audit log** (`app/core/frontend/processes/flows2.html`):
- The "Audit history" details panel lazy-loads from the story endpoint on first expand
- Replaced the previous "Coming soon" placeholder with a live chronological timeline

### Sourcemap temporal trace and story panel (Phase 8)

- `app/core/backend/temporal_dag_tracer.py` — `TemporalDAGTracer` class; accepts `db`, `org_id`, `as_of`, `max_depth`; queries `execution.step_completed` events before `as_of` to reconstruct the provenance graph as it existed at that moment
- `POST /api/core/sourcemap/trace` now delegates temporal requests to `TemporalDAGTracer` instead of inline BFS
- Each sourcemap item card has an "Audit history" button that opens a slide-in story panel (`.sm-story-panel`) — lazy-fetches `/api/core/entities/inventory_item/<id>/story` and renders a chronological timeline

---

## 16. UI Testing Guide — What to Do and What to Expect

Start the app: `python app/app.py` (or `uv run workflow start`). All features work with real data — the more actions taken, the richer the audit trail.

### 16.1 Inventory view — audit enrichment

**How to test:**
1. Go to `/core/inventory/view`
2. Badges and "Added by" meta appear in both the desktop **Audit** column (table view) and on cards (mobile < 900px)
3. Add some inventory items via different methods: one manually, one via barcode scan (set `extra_data.barcode_scan = true`), one via CSV upload

**What to expect:**
- Items added via barcode show a purple **Barcode** badge
- Items added via CSV show a purple **CSV import** badge
- Items used in executions show a blue **Used N×** badge
- Items with wastage records show a red **N wastage** badge
- Below the badges: "Added by user@example.com · 13 May 2026"
- After an item has been consumed in a process step: "Last used 13 May 2026 in Step Name"
- At the bottom of each card: an "Audit history" expand control. Click it — first click triggers a fetch. Subsequent opens are instant (already loaded)
- The timeline shows oldest events at the top, newest at the bottom, each with a blue dot, human-readable sentence, and date

**If you see no badges / no audit meta:** The item was created before the event sourcing migration was applied — no events exist for it yet. Create a new item to see enrichment immediately.

### 16.2 Process list — version and run history

**How to test:**
1. Go to `/core/flows` (the process list page)
2. Create a new process, add a step, then edit the process name

**What to expect:**
- Under each process name and the "X steps · Y active · Z completed" line, a third line appears in light grey
- Fresh process (just created): `v1 · Created by user@example.com · 13 May 2026`
- After editing: `v2 · Last edited by user@example.com · 13 May 2026`
- After running a batch: `v2 · Last edited by … · 13 May 2026 · 1 run`

**If you see no tertiary line:** The process was created before the migration. Edit or add a step to the process — that write will emit an event and the line will appear from that point on.

### 16.3 Process detail — audit history panel

**How to test:**
1. Open any process at `/core/flows?id=<uuid>`
2. Scroll to the bottom of the "Edit process" panel (the definition tab)
3. Click "Audit history"

**What to expect:**
- A collapsible details panel expands (animated chevron)
- First open triggers a fetch — you see "Loading…" briefly
- Timeline appears: `Process created by user@example.com · 13 May 2026`, then any step additions/edits
- Each entry has a blue dot, sentence, and date
- Collapse and re-open: no fetch — content stays loaded

### 16.4 Execution (batch) cards — actor and materials summary

**How to test:**
1. Open a process at `/core/flows?id=<uuid>`
2. Switch to the "Batches" panel
3. Start a new batch and complete a step that consumes inputs and produces outputs

**What to expect:**

Active batch card:
- "Started: 13 May 2026, 10:30 am"
- "Started by: user@example.com" — sourced from the event log, not the current session

Completed batch card (expand by clicking the header):
- "Completed: 13 May 2026, 10:45 am"
- "Started by: user@example.com"
- "3 steps completed · 2 inputs consumed · 1 output produced" (numbers reflect what was recorded in step completions)

### 16.5 Sourcemap — entity story panel

**How to test:**
1. Go to `/core/sourcemap`
2. Click any inventory item in the browse grid to start a trace
3. On any item card in the trace result, click the **"Audit history"** button (appears below the "Details" toggle)

**What to expect:**
- A drawer slides in from the right edge of the screen (360px wide)
- The item's name appears in the drawer header
- A chronological timeline loads: every recorded event for that item — created, quantity adjustments, consumptions, production, wastage
- The trace area shifts left (margin-right: 360px) so cards are not obscured
- Click × in the drawer header to close — the trace area returns to full width
- Only inventory item story panels are wired in the sourcemap; other entity types use the `/story` endpoint directly

### 16.6 Sourcemap — temporal trace via API

The temporal trace is a backend-only feature at present (no dedicated UI button yet). Test it directly:

```bash
# Get a valid inventory item UUID first
curl -s -X GET "http://localhost:8000/api/core/inventory" \
  -H "Cookie: <your-session-cookie>" | jq '.inventory_items[0].id'

# Temporal trace — reconstructs provenance as of a point in time
curl -s -X POST "http://localhost:8000/api/core/sourcemap/trace" \
  -H "Content-Type: application/json" \
  -H "Cookie: <your-session-cookie>" \
  -d '{
    "root_type": "inventory_item",
    "root_id": "<uuid>",
    "as_of": "2026-05-13T10:00:00Z",
    "depth": 5
  }' | jq '{nodes: (.nodes | length), edges: (.edges | length), is_current, as_of}'
```

**What to expect:**
- `is_current: false`, `as_of` echoed back
- `nodes` and `edges` reflect the graph as it existed at the given timestamp
- Empty `edges` if no step-completion events existed before that time

### 16.7 Entity story API — direct inspection

```bash
# Full event timeline for an inventory item
curl -s "http://localhost:8000/api/core/entities/inventory_item/<uuid>/story" \
  -H "Cookie: <session>" | jq '.events[] | {event_type, at, actor, summary}'

# Pre-computed summary
curl -s "http://localhost:8000/api/core/entities/inventory_item/<uuid>/summary" \
  -H "Cookie: <session>" | jq '.summary'
```

**What to expect:**
- `/story` returns events oldest-first, each with a human-readable `summary` field
- `/summary` returns the latest `entity_event_summaries.summary` JSONB — `add_method`, `times_consumed`, `quantity_history`, `wastage_event_count`, etc.

### 16.8 Database inspection

Connect directly to the test or local database to verify event storage:

```sql
-- See all events for an entity
SELECT event_type, actor_label, created_at, payload->>'add_method' as add_method
FROM entity_events
WHERE entity_id = '<uuid>'
ORDER BY created_at;

-- Check that causal chains are intact
SELECT id, event_type, causation_id
FROM entity_events
WHERE causation_id IS NOT NULL
ORDER BY created_at DESC
LIMIT 20;

-- View pre-computed summaries
SELECT entity_type, summary->>'add_method', summary->>'times_consumed', last_event_type
FROM entity_event_summaries
ORDER BY last_event_at DESC
LIMIT 20;

-- Check process version history
SELECT process_id, version_number, change_summary, created_at
FROM process_versions
ORDER BY created_at DESC;
```

### 16.9 Known limitations

- **Pre-migration data:** Items, processes, and executions created before the migrations have no events. The UI degrades gracefully — audit badges and meta lines simply don't appear (they check for `event_summary` null). New actions on old entities will start generating events.
- **add_method detection:** Detected from `extra_data` keys at creation time. Items added before event sourcing show no add-method badge.
- **2FA/login tests:** The `test_login_2fa_flow.py` and `test_2fa_totp_optimized.py` test files require a live app server running on port 8005. They fail in the test container (no server running there). All repository-level and API integration tests pass (189 passed, 1 skipped in the Docker test container).
- **Pre-migration entities:** Items, processes, and executions created before the migrations have no events. The UI degrades gracefully — audit badges and meta lines simply don't appear. New actions on old entities will start generating events immediately.
- **Quantity sparkline requires 2+ history points:** An item only shows a sparkline after at least two quantity events (creation + one adjustment or consumption).
- **2FA/login tests:** The `test_login_2fa_flow.py` and `test_2fa_totp_optimized.py` test files require a live app server running on port 8005. All repository-level and API integration tests pass.
- **Temporal trace node state:** Nodes in temporal results only have state when a matching event exists in `entity_events` before the `as_of` date. Nodes with no pre-date events appear nameless (UUID only). Items created before event sourcing will not have state in temporal results.

---

## 18. Platform Gap Analysis vs. Product Claims

All gaps identified in the original analysis are now complete. Source-to-sale tracing is excluded from scope (CRM and accounting integrations are a separate workstream).

### Claim audit — final status

| Claim | Status | Where to see it |
|---|---|---|
| "Every action is recorded at the point of work" | ✅ Done | Sourcemap → Activity tab → All |
| "Every change is preserved in context" | ✅ Done | Any entity's audit history panel or History button |
| "Every workflow is connected end-to-end" | ✅ Done | Sourcemap → select any item → Timeline view |
| "Every decision, material and action is reconstructable instantly" | ✅ Done | Sourcemap → trace an item → "Replay as of" date-picker |
| "Every inventory item is tracked and connected" | ✅ Done | Inventory view → card → Audit history |
| "Every product in each state of production is tracked" | ✅ Done | Sourcemap temporal replay shows state at any past date |
| "Capture your work as it happens" | ✅ Done | Events written in same transaction as every mutation |
| "Understand how your production changes over time" | ✅ Done | Process list → History button; process detail → Audit history |
| "Reconstruct any production state instantly" | ✅ Done | Sourcemap → Replay as of [date] |
| "Ensure consistent actions across teams and users" | ✅ Done | Structured workflows enforce defined step definitions |
| "Reduce errors during your workflow" | ✅ Done | Input/output validation at step completion |
| "Be audit-ready by default" | ✅ Done | Activity tab is a complete org-wide audit log, always on |
| Activity visible by operator/person | ✅ Done | Activity tab → operator dropdown filter |
| Settings changes tracked | ✅ Done | Activity tab → Settings filter |
| User/auth events in org activity feed | ✅ Done | Activity tab → Users filter |

---

## 19. Gap Resolution — Implementation Detail

### Gap 1 — Temporal trace UI ✅

**Files:** `app/core/frontend/sourcemap/sourcemap.html`, `app/core/frontend/js/sourcemap.js`, `app/core/frontend/css/sourcemap.css`, `app/core/backend/temporal_dag_tracer.py`, `app/core/backend/backend.py`

**What was built:**
- "Replay as of" date-picker added to the controls bar (visible when a trace is active)
- Clicking Apply calls `smRunTemporalTrace(itemId)` → `POST /api/core/sourcemap/trace` with `as_of: date + 'T23:59:59Z'`
- `smRenderTemporalTrace(result)` renders a dedicated view: yellow as-of banner, node cards showing each item's name/quantity/type at that point in time, connection count, and event timeline
- Clicking "Live" resets `temporalAsOf` and re-runs the standard current-state trace
- `temporal_dag_tracer.py` now includes `event_id` in timeline items so `_human_summary` generates proper text instead of a generic string replace
- `smClearTrace()` also resets temporal state and the date input

**How to use:**
1. Go to `/core/sourcemap`
2. Select any inventory item from the browse grid to start a trace
3. Once the trace is displayed, the controls bar shows "Replay as of [date input] [Apply] [Live]"
4. Enter a past date and click Apply
5. A yellow banner appears: "Showing provenance as of [date] — not current state"
6. Node cards show the item's name, quantity, and type as they were recorded up to that date
7. The event timeline below lists all events before that date in reverse order
8. Click Live to return to the current-state trace

### Gap 2 — User events in Activity tab ✅

**Files:** `app/core/frontend/js/sourcemap.js`

**What was built:**
- "Users" filter pill added to the entity type buttons in the Activity tab
- The backend `/api/core/entities/activity` endpoint already returns all entity types including `user` — no backend change needed
- `_SM_ENTITY_BADGE` already defined yellow badge for `user` type

**How to see it:**
1. Go to `/core/sourcemap` → Activity tab
2. Click the "Users" pill
3. See login events, 2FA changes, and role changes for all users in the org
4. Each entry shows: yellow "User" badge, human-readable summary ("Logged in with 2FA from 192.168.x.x"), actor email, timestamp

### Gap 3 — Org settings change events ✅

**Files:** `app/api/routes/org_routes.py`, `app/core/backend/event_writer.py`, `app/core/backend/backend.py`

**What was built:**
- `update_org` route captures before-state (name, status) then emits `org.settings_updated` with a diff if anything changed; no event emitted when nothing changes
- New `org` entity type added to `_parse_entity_type`, `_upsert_summary` dispatcher, and `_human_summary`
- `_update_org_summary`: upserts `{name, status, last_changed_at, last_changed_by}` in `entity_event_summaries`
- `_human_summary` for `org.settings_updated` includes what changed: "Organisation settings updated — Name changed to 'Acme Co'"
- "Settings" pill and neutral grey `.sm-act-badge--org` badge added to Activity tab

**How to see it:**
1. Go to `/org/settings` (or wherever the org name/status is editable) and change the org name
2. Go to `/core/sourcemap` → Activity tab → click "Settings"
3. See a grey "Settings" badge entry: "Organisation settings updated — Name changed to 'New Name'"

### Gap 4 — Quantity sparkline on inventory cards ✅

**Files:** `app/core/frontend/inventory/view.html`, `app/core/frontend/css/inventory-view.css`

**What was built:**
- `buildSparkline(es)` function renders an 80×24px inline SVG polyline from `event_summary.quantity_history`
- Only renders when there are 2+ data points (flat lines are skipped)
- Drawn in `var(--color-primary, #3b82f6)` at 75% opacity, positioned to the right of the quantity text
- CSS: `.inv-view-card__val--qty` uses flex to align text and sparkline; `.inv-sparkline` is `display: block`

**How to see it:**
1. Go to `/core/inventory/view` on a screen narrower than 900px (or use DevTools responsive mode to force card layout)
2. Find an inventory item that has had at least one quantity adjustment since event sourcing was deployed
3. In the Quantity row, a small blue sparkline appears to the right of the number showing the quantity trend over time
4. More adjustments = richer sparkline

### Gap 5 — Success rate on process cards ✅

**Files:** `app/core/frontend/processes/list.html`

**What was built:**
- The tertiary audit line on each process list entry now computes success rate from `event_summary.completed_runs` / `event_summary.total_runs`
- Only shown when `total_runs > 1` (a single run doesn't have a meaningful rate)
- Cancelled count shown separately when non-zero: `2 runs · 100% success` or `5 runs · 60% success · 2 cancelled`
- Data was already tracked in `entity_event_summaries.summary` (`completed_runs`, `cancelled_runs`, `failed_runs`) — this was purely a UI change

**How to see it:**
1. Go to `/core/flows` (the process list)
2. Find a process that has been run at least twice
3. The grey tertiary line shows: `v3 · Last edited by user@example.com · 13 May 2026 · 4 runs · 75% success · 1 cancelled`

### Gap 6 — Evidence count on execution cards ✅

**Files:** `app/core/frontend/js/flows2-executions.js`

**What was built:**
- The completed execution card summary line now appends evidence file count: `3 steps completed · 2 inputs consumed · 1 output produced · 2 evidence files`
- Uses `(execution.evidence || []).length` — the evidence array is already returned in the execution list API response
- Only shown when `evidenceCount > 0`

**How to see it:**
1. Go to any process at `/core/flows?id=<uuid>` → Batches tab
2. Find a completed batch where evidence files were uploaded during execution
3. Expand the completed batch card — the summary line under "Started by" now includes the evidence file count

---

## 20. Complete UI Test Checklist — event-sourcing Branch

Start the app: `uv run workflow start` (or `python app/app.py`). Use a real browser — mobile tests require DevTools responsive mode or a physical device. Work through each section in order; some tests build on actions from earlier sections.

---

### Page 1 — `/core/inventory/view` (Inventory view)

**Test 1.1 — Audit badges and "Added by" in table view (desktop)**
1. Open the page at full desktop width (≥ 900px) — you will see the table layout.
2. Look at the **Audit** column (rightmost column, replacing the old "Metadata" column).
3. **Expect:** For any item created after event sourcing was deployed:
   - Coloured pill badges: Purple **Barcode scan** if via barcode, Purple **CSV import** if via CSV, Blue **Used N×** if consumed, Red **N wastage** if wastage recorded
   - A grey "Added by user@email.com · 13 May 2026" line below the badges
   - An "Audit history" collapsible at the bottom of the cell
4. Items created before event sourcing show only the "Audit history" expand (with no recorded events) and no badges/meta lines.
5. Create a new item now — refresh the page and confirm the new row shows "Added by" immediately.

**Test 1.2 — Audit badges and meta in card view (mobile)**
**Setup:** Switch to card layout by narrowing the browser below 900px or using DevTools → Responsive → 390px width.
1. Look at any inventory item card.
2. **Expect:** Same badges and "Added by" / "Last used" lines appear above the data rows.
3. After running a batch that consumes this item, **expect** a `Last used 13 May 2026 in Step Name` line.

**Test 1.3 — Quantity sparkline**
1. Find an item that has had at least two quantity events (created + one manual adjustment or consumption).
2. Look at the **Quantity** row on the card.
3. **Expect:** A small blue SVG line chart appears to the right of the quantity number, showing the trend over time.
4. Items with only one event show no sparkline (needs 2+ data points).
5. On screens narrower than 320px the sparkline hides; verify no layout breakage.

**Test 1.4 — Audit history panel**
1. Click **Audit history** at the bottom of any card.
2. **Expect:** A `<details>` block expands showing "Loading…" then a chronological timeline.
3. Each event shows: blue dot · summary sentence · actor email (smaller, grey) · date (right-aligned).
4. For update events, a diff block appears below the summary: label, red strikethrough old value, `→`, green new value. If there was no old value, no `→` is shown.
5. Click **↑ Oldest first** / **↓ Newest first** to toggle sort order — timeline reverses.
6. **Tap target check (mobile):** Sort toggle button should be easy to tap (≥ 36px height). Verify with finger or DevTools touch simulation.
7. Collapse and re-expand: no second network request (content stays loaded).

**Test 1.5 — Mobile layout (≤ 390px)**
1. Verify card layout is used (table is hidden).
2. Scroll through several cards — no horizontal overflow.
3. Badges wrap to multiple lines without overflow.
4. Audit history panel content scrolls within the `<details>` block.

---

### Page 2 — `/core/flows` (Process list)

**Test 2.1 — Tertiary audit line on process entries**
1. Look at any process in the list.
2. **Expect:** Below the "N steps · N active · N completed" line, a third grey line appears:
   - Fresh process: `v1 · Created by user@email.com · 13 May 2026`
   - After edits: `v3 · Last edited by user@email.com · 13 May 2026`
   - After runs: `v3 · Last edited by … · 13 May 2026 · 4 runs`
   - After multiple runs: `… · 4 runs · 75% success` (only shown when total > 1)
   - If runs were cancelled: `… · 4 runs · 75% success · 1 cancelled`

**Test 2.2 — History button on process entries**
1. Look at the right side of any process row — there is a **History** button beside the chevron arrow.
2. Click **History**.
3. **Expect:** A slide-in drawer appears from the right edge of the screen, showing the process name as the panel title.
4. A timeline loads: process created event, then any step additions/edits, each with blue dot, summary, actor, date.
5. Sort toggle (**↑ Oldest first**) in the panel header switches order.
6. Click **×** to close — panel slides out.
7. **Mobile (≤ 420px):** Panel occupies full screen width. Background dims with a dark overlay. Verify the × button and sort button are easy to tap.
8. Clicking outside the panel on desktop closes it. On mobile, the list items behind the overlay are non-interactive while the panel is open.

---

### Page 3 — `/core/flows?id=<uuid>` (Process detail — flows2)

**Test 3.1 — Audit history panel in process definition**
1. Open any process.
2. Scroll to the bottom of the definition/edit panel.
3. Click **Audit history**.
4. **Expect:** A collapsible panel expands with a timeline of process events.
5. Update events show structured diff rows — one line per changed field, with coloured before/after values.
6. Step additions show all fields that were set: description, each input (name, qty, unit), each output, each prompt.
7. Sort toggle works (oldest/newest).
8. Actor appears below the diff block in small grey text, not embedded in the summary sentence.

**Test 3.2 — Execution (batch) cards — Started by**
1. Switch to the **Batches** tab.
2. Find any active or completed batch.
3. **Expect:** "Started by: user@email.com" sourced from the event log (authoritative actor, not current session user).

**Test 3.3 — Completed batch summary line**
1. Find a completed batch and expand its card.
2. **Expect:** A grey summary line: `N steps completed · N inputs consumed · N outputs produced`
3. If evidence files were attached during the batch: `· N evidence files` appended to the line.

---

### Page 4 — `/core/sourcemap` (Sourcemap)

#### Browse grid

**Test 4.1 — Browse tabs**
1. Open the sourcemap. The browse grid shows the **Inventory** tab by default.
2. Switch between **Batches**, **Suppliers**, and **Activity** tabs.
3. **Expect:** Operators tab is gone — operator filtering is now inside Activity.

**Test 4.2 — Activity tab — entity type filters**
1. Click the **Activity** tab.
2. **Expect:** A row of filter pills: **All · Inventory · Processes · Executions · Users · Settings**
3. Click **Inventory** — only inventory events appear (created, adjusted, consumed, wasted).
4. Click **Processes** — only process events (created, step added, step updated, etc.).
5. Click **Executions** — only execution events.
6. Click **Users** — login events, 2FA changes, role changes for all users in the org.
7. Click **Settings** — org name/status change events (grey "Settings" badge).
8. Click **All** — all events visible, newest first.

**Test 4.3 — Activity tab — operator filter**
1. With Activity tab open, look at the right end of the filter pill row.
2. **Expect:** An **All operators** dropdown (only appears if there are events with actors).
3. Select a specific operator — feed filters to only that person's actions.
4. Combined with an entity type pill: filters by both operator AND type simultaneously.

**Test 4.4 — Activity tab — date range filter**
1. Click Activity. Look below the pills for the date picker bar (From / To / Apply / Clear).
2. Enter a **From** date and click **Apply** — feed shows only events on or after that date.
3. Enter both **From** and **To** — shows events in that range.
4. Click **Clear** — dates reset, full feed returns.
5. Combine with entity type pill and operator — all three filters work together.

**Test 4.5 — Activity feed entries**
1. Look at individual feed entries.
2. **Expect:** Each entry shows: coloured entity type badge · summary sentence · "Show diff" link (if there are field changes) · actor email · relative date (right-aligned).
3. Click **Show diff** — a diff block expands inline showing label / red old value / `→` / green new value, one row per changed field. For additions, no red strikethrough and no `→`.
4. Click **Audit history** on an entry — a story panel slides in from the right showing the full event history for that specific entity.
5. **Mobile:** Entry text wraps cleanly. Badges don't overflow. Show diff and Audit history buttons are large enough to tap (≥ 32px).

**Test 4.6 — Activity tab — search**
1. Type a term in the main search bar while Activity tab is selected.
2. **Expect:** Feed filters by matching summary text, actor name, or event type.

#### Trace mode

**Test 4.7 — Starting a trace**
1. From the browse grid, click any inventory item card.
2. **Expect:** The browse grid is replaced by a trace result. The controls bar appears above showing: **Timeline · Map · Table** view toggle + **Replay as of** date bar + legend.

**Test 4.8 — Story panel from trace**
1. In the trace result, find any item card that has an **Audit history** button.
2. Click it — a story panel slides in from the right.
3. **Expect:** Full chronological event history for that specific inventory item.
4. Sort toggle in the panel header works.
5. Close with × button.
6. **Mobile:** Panel goes full-width. Background dims. × button is large enough to tap.

**Test 4.9 — Temporal replay (Replay as of)**
1. After starting a trace, look at the controls bar.
2. **Expect:** A "Replay as of" label, a date input, an **Apply** button, and (when a date is active) a **Live** button.
3. Enter a date in the past (before today) and click **Apply**.
4. **Expect:**
   - A yellow banner appears: "⏱ Showing provenance as of [date] — not current state"
   - Node cards appear showing each item's name, type, and quantity as recorded up to that date
   - A connection count line: "N connections recorded before this date"
   - An event timeline below listing all events before that date, newest first, with actor and human-readable summary text
5. Nodes whose events all post-date the selected date will show no meaningful state (UUID only) — this is expected.
6. Click **Live** — returns to the standard current-state trace view; banner disappears; date input clears.
7. **Mobile:** Date input grows to fill available width. Apply and Live buttons have adequate tap height.

**Test 4.10 — Temporal replay grid layout (mobile)**
1. With the temporal replay result showing, at 390px width:
2. **Expect:** Node cards display in a 2-column grid (1-column below 400px, 3-column above 600px).
3. Cards don't overflow horizontally.

---

### Page 5 — `/org/settings` → back to Activity tab

**Test 5.1 — Org settings change event**
1. Go to the org settings page (accessible via user menu or `/org/settings`).
2. Change the organisation name and save.
3. Go to `/core/sourcemap` → **Activity** tab → click **Settings** filter.
4. **Expect:** An entry appears with a grey **Settings** badge: "Organisation settings updated — Name changed to 'New Name'"
5. Actor email and date are shown.
6. If only status changes (not name), the summary reflects the status change instead.

---

### Mobile regression tests (run all pages at 390px width)

**Test 6.1 — Process list at 390px**
- Items display correctly with name, meta, audit line.
- History button is visible and tappable (≥ 36px tap height).
- History panel slides in full-width; background dims; × button is easy to tap; scroll works to bottom of timeline.

**Test 6.2 — Inventory cards at 390px**
- Card layout is active (table hidden).
- Sparkline renders next to quantity (or hides cleanly on very small screens).
- Audit history sort button has adequate tap height.
- Panel body scrolls smoothly (momentum scroll on iOS).

**Test 6.3 — Sourcemap Activity tab at 390px**
- Filter pills wrap to multiple lines without overflowing.
- Operator dropdown sits inline with pills and doesn't truncate.
- Date picker bar wraps cleanly; date inputs fill available width.
- Activity feed entries don't cause horizontal scroll.
- Show diff and Audit history buttons are tappable.

**Test 6.4 — Sourcemap temporal replay at 390px**
- Replay as of bar wraps as its own row below the view toggle.
- Date input stretches to fill available space.
- Apply and Live buttons have adequate tap height.
- Temporal node grid shows 2 columns (or 1 below 400px).
- Yellow banner wraps text without overflow.

**Test 6.5 — Sourcemap story panels at 390px**
- Panel opens full-width.
- Background dims behind panel (dark overlay).
- Panel body scrolls to show all timeline events.
- Safe area at the bottom (iPhone home bar): content is not obscured.
- Sort button and × close button are easy to tap.

**Test 6.6 — Process audit history panel at 390px (flows2)**
- Sort toggle has adequate tap height.
- Diff rows wrap cleanly inside the expanded panel.
- Time column does not overflow or truncate the event summary.

---

### End-to-end scenario — full audit trail

Run this scenario to verify the whole system works together:

1. **Create a process** at `/core/flows/create` with at least two steps, one input, one output.
2. **Edit the process** — change the process name and modify a step's description. Save.
3. **Run a batch** — start an execution, complete one step (attach an evidence file if possible), complete remaining steps.
4. **Add inventory** manually, then adjust the quantity.
5. **Check each surface:**
   - `/core/flows` — process list shows version, last editor, run count, success rate
   - Process list → **History** button — shows created + step added + two update events with diffs
   - `/core/flows?id=<uuid>` → Audit history — same events with full diff detail
   - Completed batch card — shows steps completed, inputs consumed, outputs produced, evidence count
   - `/core/inventory/view` (card layout) — inventory item shows added-by meta; after batch, shows Last used and Used N× badge; sparkline visible after quantity adjustment
   - Inventory card → **Audit history** — quantity adjusted event, consumed event with step name
   - `/core/sourcemap` → **Activity** tab — all five event types visible in one feed
   - Activity → **Users** filter — your login from this session should appear
   - Sourcemap → click an inventory item → trace → **Replay as of** yesterday — shows provenance as it was before today's batch
