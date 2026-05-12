# Event Sourcing, Temporal Sourcemap & Platform-Wide Card Enrichment — Architecture & Implementation Plan

**Status:** In progress  
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
