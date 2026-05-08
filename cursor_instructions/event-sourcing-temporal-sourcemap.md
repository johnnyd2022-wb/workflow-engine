# Event Sourcing, Temporal Sourcemap & Platform-Wide Card Enrichment — Architecture & Migration Plan

**Status:** Planned — not started  
**Priority:** Core differentiator feature  
**Context:** Platform is not live; no backward-compatibility obligation to existing data  

---

## 1. What We're Building and Why

This is a platform-wide infrastructure change with two distinct consumer surfaces:

**Surface 1 — The Sourcemap**  
A visual, interactive DAG showing the full provenance of any piece of data in the system — not just current state, but the state of relationships at any point in time. "Show me the lineage of Batch #dsnjkanf8 as it was on the day it was consumed" is a fundamentally different and more powerful question than "show me its lineage now." A manufacturing customer conducting a quality investigation, a compliance audit, or a recall analysis needs the historical answer, not the current one.

**Surface 2 — Cards Throughout the Platform**  
Every card in the UI (inventory item cards, execution cards, process cards) currently shows only what's in the mutable tables: name, quantity, status. With the event log, cards can show a much richer picture — who created it, when it was last used, how many times it's been through a process, what has changed since it was first recorded, and live activity indicators. This data is simply not derivable from current state alone. A card that says "Last used 3 days ago in Widget Assembly by Sarah · used 7 times across 3 processes · 0 wastage events" is qualitatively more useful than one that says "Quantity: 0 kg."

Both surfaces are powered by the same underlying `entity_events` log. The sourcemap needs temporal DAG reconstruction; the cards need fast per-entity aggregated summaries. These are different query shapes against the same data.

Without capturing state at mutation time, neither capability is possible. We cannot retrofit this later without rebuilding the data layer. Since the platform is pre-launch, we build it correctly now.

**The approach: Hybrid Event Sourcing**  
We keep all existing mutable tables as the source of current state (they work, they're fast, no reason to abandon them). We add an append-only `entity_events` table that records every mutation with a full payload snapshot of the entity state at that moment. Current-state queries use the existing tables. Historical queries and card enrichment use the event log.

This is not full event sourcing (where current state is derived entirely from events). Current state remains in mutable tables. The event log is additive — an audit trail that enables temporal queries and rich derived metadata.

---

## 2. Current State Assessment

### What Already Exists (Keep As-Is)

**`inventory_movements` table** — already append-only, already captures quantity deltas with timestamps. This is the precursor pattern. Do not change it; the new event log complements it.

**`audit_logs` table** — coarse action logging (action string, entity string, entity_id, metadata JSON). Keep for backward compat, but it is not rich enough for replay. Going forward, the `entity_events` table is the authoritative record; `audit_logs` can optionally be populated from it.

**`DAGTraversal.py`** — the core traversal engine. Walks `inventory_items.source_execution_step_id` and `execution_steps.actual_inputs` to build forward/backward graphs. Keep entirely for current-state traversal. Temporal traversal is a separate code path (see Section 7).

**`InventoryQuantityWriteReason` enum** — already gates all quantity writes. This is the correct hook point for event emission on inventory mutations. Do not remove it.

### What's Missing

1. **No entity state snapshots at mutation time** — when `execution_steps.actual_inputs` is written, there's no record of what that looked like if it later changes. Same for process definitions at execution time.

2. **No process versioning** — if a process is updated after an execution runs, there is no way to know what procedure was actually followed during that execution. This is critical for compliance.

3. **No causation chain** — when completing a step produces inventory items, consumes inputs, and records evidence, there's no record that these mutations were caused by the same user action.

4. **Sourcemap loads everything on page load** — N+1 fixed in the previous session, but the architecture still pulls all data upfront. With event sourcing and a proper trace endpoint, this becomes lazy: load a lightweight index, trace on demand.

---

## 3. New Database Schema

### 3.1 `entity_events` — The Core Append-Only Log

```sql
CREATE TABLE entity_events (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID        NOT NULL REFERENCES organisations(id),
    
    -- What happened
    event_type          VARCHAR(100) NOT NULL,
    -- e.g. "inventory_item.created", "execution.step_completed", "process.step_updated"
    -- Namespace format: {entity_type}.{verb}
    
    -- What entity it happened to
    entity_type         VARCHAR(100) NOT NULL,
    -- e.g. "inventory_item", "execution", "process", "step", "execution_step", "user"
    entity_id           UUID        NOT NULL,
    
    -- Who did it
    actor_id            UUID        REFERENCES users(id) ON DELETE SET NULL,
    actor_type          VARCHAR(50) NOT NULL DEFAULT 'user',
    -- 'user' | 'system' (for automated/background mutations)
    actor_label         VARCHAR(255),
    -- Denormalized email at event time — survives user deletion/rename
    
    -- The full state of the entity AFTER this event
    -- This is the key field for temporal reconstruction.
    -- Given an entity_id and an as_of timestamp, find MAX(created_at) <= as_of
    -- and read payload — that IS the entity state at that moment.
    payload             JSONB       NOT NULL,
    
    -- What specifically changed (field-level diff, optional but useful)
    -- Format: {"field_name": {"before": <old>, "after": <new>}}
    diff                JSONB,
    
    -- Causal chain linkage
    causation_id        UUID        REFERENCES entity_events(id) ON DELETE SET NULL,
    -- The event that directly caused this event.
    -- e.g. inventory_item.produced has causation_id = execution.step_completed event id
    
    correlation_id      UUID,
    -- The top-level operation that triggered this entire chain.
    -- All events from one HTTP request share the same correlation_id.
    -- Not a FK — correlation_id is generated per-request and stored in g.correlation_id
    
    -- Request context (for audit trail display)
    request_metadata    JSONB,
    -- {"ip": "...", "user_agent": "...", "request_id": "..."}
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Primary lookup: "give me all events for this entity in order"
CREATE INDEX ix_entity_events_org_entity ON entity_events (org_id, entity_type, entity_id, created_at);

-- "Give me the state of this entity at time T"
-- (used for temporal trace reconstruction)
CREATE INDEX ix_entity_events_entity_time ON entity_events (entity_id, created_at DESC);

-- "Give me all events of this type in this org (e.g. all step_completed events)"
CREATE INDEX ix_entity_events_type ON entity_events (org_id, event_type, created_at);

-- "Give me all actions by this user"
CREATE INDEX ix_entity_events_actor ON entity_events (org_id, actor_id, created_at);

-- "Give me the full causal chain from this event"
CREATE INDEX ix_entity_events_causation ON entity_events (causation_id) WHERE causation_id IS NOT NULL;

-- "Give me all events in this operation"
CREATE INDEX ix_entity_events_correlation ON entity_events (correlation_id) WHERE correlation_id IS NOT NULL;

-- "Full org timeline" (used for the story view)
CREATE INDEX ix_entity_events_org_time ON entity_events (org_id, created_at);
```

**Critical design decision — full snapshot in payload:**  
Each row stores the complete entity state after the mutation, not just a diff. This means reconstructing state at time T is a single indexed lookup (find last event before T), not a replay chain. Storage is larger but query performance is O(log n) regardless of history depth. The `diff` field is additive — useful for displaying "what changed" in the story view but not required for reconstruction.

---

### 3.2 `process_versions` — Process Definition Snapshots

This table captures a complete snapshot of a process and all its steps every time the process definition changes. This is how we answer "what procedure was being followed when Execution #4421 ran?"

```sql
CREATE TABLE process_versions (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID        NOT NULL REFERENCES organisations(id),
    process_id          UUID        NOT NULL REFERENCES processes(id) ON DELETE CASCADE,
    version_number      INTEGER     NOT NULL,
    -- Auto-incrementing per process, not global
    
    snapshot            JSONB       NOT NULL,
    -- Full process definition at this version:
    -- {
    --   "id": "...", "name": "...", "description": "...",
    --   "category": "...", "is_draft": false,
    --   "steps": [
    --     {
    --       "id": "...", "step_number": 1, "position": "...",
    --       "name": "...", "description": "...",
    --       "inputs": [...], "outputs": [...], "execution_prompts": [...]
    --     }
    --   ]
    -- }
    
    changed_by          UUID        REFERENCES users(id) ON DELETE SET NULL,
    change_summary      VARCHAR(500),
    -- Human-readable: "Added QC step", "Updated input quantities", etc.
    -- Populated from diff or left as "Process updated"
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    UNIQUE (process_id, version_number)
);

CREATE INDEX ix_process_versions_process ON process_versions (process_id, version_number DESC);
CREATE INDEX ix_process_versions_org ON process_versions (org_id, created_at);
```

**How version_number is assigned:**  
On every write to `processes` or `steps` (create, update, delete), insert a new `process_versions` row with `version_number = (SELECT COALESCE(MAX(version_number), 0) + 1 FROM process_versions WHERE process_id = ?)`.

---

### 3.3 Add `process_version_id` to `executions`

```sql
ALTER TABLE executions 
ADD COLUMN process_version_id UUID REFERENCES process_versions(id) ON DELETE SET NULL;

CREATE INDEX ix_executions_process_version ON executions (process_version_id);
```

When an execution is created, record which `process_versions` row was current at that moment. This gives a permanent, fast link from any execution to the exact process definition that was active when it ran. The `process_versions.snapshot` JSONB contains the complete steps definition — no join required to reconstruct "what procedure was followed."

---

### 3.4 Add `traceable_object_type` to `inventory_items` (Optional Refinement)

Currently `inventory_type` (raw_material, work_in_progress, final_product) carries the semantic. Consider adding:

```sql
ALTER TABLE inventory_items
ADD COLUMN display_label VARCHAR(255);
-- Human-readable for the sourcemap selector, e.g. "Batch #dsnjkanf8 (Steel Rod 10mm, 50kg)"
-- Computed at creation, stored for fast index queries
```

This avoids the sourcemap index endpoint having to reconstruct display strings from multiple fields at query time.

---

## 4. Event Types Catalog

Every mutation in the system emits one or more events. Below is the complete catalog. This is the contract — every repository mutation maps to one or more entries here.

### 4.1 Inventory Events

| event_type | Trigger | Key payload fields |
|---|---|---|
| `inventory_item.created` | `InventoryRepository.create_inventory_item` | Full item snapshot: name, quantity, unit, type, supplier, batch_number, expiry_date, source_execution_id, source_execution_step_id |
| `inventory_item.quantity_adjusted` | `InventoryRepository.add_quantity_to_inventory_item` | quantity_before, quantity_after, delta, unit, reason (InventoryQuantityWriteReason value), movement_id |
| `inventory_item.consumed` | Inside `complete_step` — when step actual_inputs reference this item | quantity_consumed, unit, execution_id, execution_step_id, step_name |
| `inventory_item.produced` | Inside `complete_step` — when step produces new inventory | quantity_produced, unit, execution_id, execution_step_id, step_name, source_output_id |
| `inventory_item.wasted` | `WastageRepository.create_wastage_record` | quantity_wasted, unit, recorded_by, wastage_id |
| `inventory_item.updated` | `InventoryRepository.update_inventory_item` | diff of changed fields, full snapshot after |
| `inventory_item.deleted` | `InventoryRepository.delete_inventory_item` | Full snapshot before deletion (this is the last event for the entity) |

### 4.2 Execution Events

| event_type | Trigger | Key payload fields |
|---|---|---|
| `execution.created` | `ExecutionRepository.create_execution` | process_id, process_version_id, process_snapshot (full steps definition at creation time) |
| `execution.started` | First step transition from pending → in_progress | process_id, process_version_id |
| `execution.step_started` | `execution_step.status` → in_progress | step_id, step_number, step_name, step_snapshot (full step definition from process_version) |
| `execution.step_completed` | `ExecutionRepository.complete_step` | step_id, step_number, step_name, actual_inputs (full with inventory_item_ids), actual_outputs, execution_data, evidence_ids, items_consumed (list of {item_id, qty}), items_produced (list of {item_id, qty}) |
| `execution.completed` | All steps done, execution status → completed | total_steps, completed_at |
| `execution.failed` | Status → failed | reason, failed_at_step |
| `execution.cancelled` | Status → cancelled | reason |

**Note on `execution.step_completed`:** This is the most important event. Its payload must include the complete picture of what happened at that step: what was consumed, what was produced, what data was recorded, what evidence was attached. The `items_consumed` and `items_produced` arrays create the causal links that the temporal DAG traversal will use.

### 4.3 Process Events

| event_type | Trigger | Key payload fields |
|---|---|---|
| `process.created` | `ProcessRepository.create_process` | Full process snapshot (no steps yet) |
| `process.updated` | `ProcessRepository.update_process` | diff, full snapshot after, new process_version_id |
| `process.published` | is_draft false → true | process_version_id |
| `process.step_added` | `ProcessRepository.add_step` | step snapshot, process_version_id |
| `process.step_updated` | `ProcessRepository.update_step` | step diff, step snapshot after, process_version_id |
| `process.step_deleted` | `ProcessRepository.delete_step` | step snapshot before deletion, process_version_id |
| `process.deleted` | `ProcessRepository.delete_process` | Final process snapshot (tombstone event) |

### 4.4 User & Auth Events

| event_type | Trigger | Key payload fields |
|---|---|---|
| `user.created` | `UserRepository.create_user` | email, role, org_id (no password hash) |
| `user.login` | Successful auth | ip, user_agent, 2fa_used |
| `user.login_failed` | Failed auth | ip, user_agent, reason |
| `user.2fa_enabled` | `UserRepository.enable_two_factor` | — |
| `user.2fa_disabled` | `UserRepository.disable_two_factor` | — |
| `user.role_changed` | Role update | old_role, new_role |
| `user.account_locked` | `UserRepository.lock_account` | reason, locked_until |
| `user.account_unlocked` | `UserRepository.unlock_account` | — |
| `user.deactivated` | `UserRepository.delete_user` (soft) | — |

---

## 5. The EventWriter Module

All event emission goes through a single module. Never write to `entity_events` inline in business logic or route handlers. This enforces consistency and makes it easy to audit what emits events.

**Create:** `app/core/backend/event_writer.py`

```python
# Conceptual structure — implement fully
from uuid import UUID, uuid4
from datetime import datetime, timezone
from flask import g
from app.core.models import EntityEvent  # the new ORM model

class EventWriter:
    def __init__(self, session, org_id: UUID):
        self.session = session
        self.org_id = org_id

    def emit(
        self,
        event_type: str,
        entity_type: str,
        entity_id: UUID,
        payload: dict,
        diff: dict = None,
        causation_id: UUID = None,
        actor_id: UUID = None,
        actor_label: str = None,
        actor_type: str = "user",
    ) -> EntityEvent:
        event = EntityEvent(
            org_id=self.org_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id or getattr(g, "current_user_id", None),
            actor_type=actor_type,
            actor_label=actor_label or getattr(g, "current_user_email", None),
            payload=payload,
            diff=diff,
            causation_id=causation_id,
            correlation_id=getattr(g, "correlation_id", None),
            request_metadata=_request_metadata(),
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(event)
        # Do NOT commit here — the event is flushed with the parent transaction.
        # If the parent transaction rolls back, the event is also rolled back.
        return event

def _request_metadata() -> dict:
    """Pull safe request context from Flask g / request."""
    try:
        from flask import request
        return {
            "ip": request.remote_addr,
            "user_agent": request.user_agent.string[:200] if request.user_agent else None,
        }
    except RuntimeError:
        return {}
```

**Key rule:** EventWriter.emit() is called inside the same database transaction as the mutation. If the mutation rolls back, the event rolls back with it. There is no dual-write problem.

**Correlation ID middleware:**  
Add to the request lifecycle (in middleware or `before_request`):
```python
g.correlation_id = uuid4()
```
This gives every HTTP request a unique ID. All events emitted during that request share it.

---

## 6. Repository Hookup Plan

Each repository method that mutates state needs an `EventWriter` call added. The repositories already receive a `db_session` — pass `EventWriter(db_session, org_id)` into them or construct it inside each method.

### ExecutionRepository — highest priority

**`create_execution`:**
1. Create execution as now
2. Capture current `process_version_id` (latest for this process)
3. Set `execution.process_version_id`
4. Emit `execution.created` with `process_version_id` and `process_snapshot` (from `process_versions.snapshot`)

**`complete_step` — most complex:**
This single method can: advance execution_step status, produce inventory items, consume inventory inputs, record wastage, attach evidence. All events from this method share the same `causation_id` chain.

Order of events:
1. Emit `execution.step_completed` — this is the root event for this operation, capture its returned `id`
2. For each consumed inventory item: emit `inventory_item.consumed` with `causation_id = step_completed_event.id`
3. For each produced inventory item: emit `inventory_item.produced` with `causation_id = step_completed_event.id`
4. For each quantity adjustment: emit `inventory_item.quantity_adjusted` with `causation_id = step_completed_event.id`
5. If execution is now complete: emit `execution.completed` with `causation_id = step_completed_event.id`

All of these share the same `correlation_id` (from `g.correlation_id`).

### ProcessRepository

**`create_process`:**
1. Create process
2. Insert first `process_versions` row (version 1, empty steps snapshot)
3. Emit `process.created`

**`update_process`:**
1. Update process
2. Insert new `process_versions` row (snapshot includes current steps)
3. Emit `process.updated` with diff

**`add_step` / `update_step` / `delete_step`:**
1. Mutate step
2. Insert new `process_versions` row
3. Emit `process.step_added` / `process.step_updated` / `process.step_deleted`

### InventoryRepository

**`create_inventory_item`:** Emit `inventory_item.created`

**`add_quantity_to_inventory_item`:** Emit `inventory_item.quantity_adjusted` (already gated by `InventoryQuantityWriteReason` — use that enum value in the event payload as `reason`)

**`update_inventory_item`:** Compute diff (before/after), emit `inventory_item.updated`

**`delete_inventory_item`:** Capture full snapshot first, emit `inventory_item.deleted`, then delete

### WastageRepository

**`create_wastage_record`:** Emit `inventory_item.wasted` with `causation_id` if called from within a step completion (propagate from caller)

---

## 7. Temporal Trace Architecture

### 7.1 How `as_of` Reconstruction Works

Given a root entity and a timestamp `T`:

1. For each node in the DAG, find its state at time T:
   ```sql
   SELECT payload FROM entity_events
   WHERE entity_id = $entity_id AND created_at <= $as_of
   ORDER BY created_at DESC
   LIMIT 1
   ```
   The `payload` is the complete entity state — no replay required.

2. To find what edges existed at time T: look at `execution.step_completed` events before T. Each such event's payload contains `items_consumed` and `items_produced`. These ARE the edges of the DAG at that point in time.

3. An entity that has no events before T did not exist yet — exclude it from the graph.

4. An entity whose last event before T is a `*.deleted` event was deleted by T — show it with a "deleted" visual state if relevant, or exclude it.

### 7.2 `DAGTraversal.py` — What Changes

**Nothing changes in `DAGTraversal.py` for current-state queries.** It continues to work exactly as it does now for the live sourcemap view.

For temporal queries, create a new `TemporalDAGTracer` class (separate file: `app/core/backend/temporal_dag_tracer.py`):

```python
class TemporalDAGTracer:
    """
    Reconstructs the DAG state as it existed at a given point in time,
    using the entity_events log rather than current mutable table state.
    """
    def __init__(self, org_id: UUID, session, as_of: datetime):
        self.org_id = org_id
        self.session = session
        self.as_of = as_of

    def get_entity_state_at(self, entity_id: UUID) -> dict | None:
        """
        Returns the payload (entity state) of the last event for this entity
        at or before self.as_of. Returns None if entity didn't exist yet.
        """
        ...

    def get_edges_at(self) -> list[dict]:
        """
        Returns all {from_id, to_id, execution_id, step_completed_at} edges
        that existed at self.as_of. Derived from execution.step_completed events.
        """
        ...

    def trace(self, root_id: UUID) -> TraversalResult:
        """
        Walks the DAG from root_id using only relationships that existed
        at self.as_of, with entity states reconstructed at that time.
        """
        ...
```

The output shape is the same `TraversalResult` as the current tracer — the frontend receives the same graph structure regardless of whether it's a current or temporal trace.

### 7.3 New API Endpoints

**`GET /api/core/sourcemap/objects`** — Lightweight traceable objects index

Returns a flat list of all traceable entities (just enough for selectors). Paginated and searchable.

```json
{
  "objects": [
    {
      "id": "uuid",
      "type": "inventory_item",
      "label": "Batch #dsnjkanf8",
      "sublabel": "Steel Rod 10mm · 50 kg · received 2026-01-10",
      "discriminators": {
        "supplier": "Acme Metals",
        "batch_number": "dsnjkanf8",
        "expiry_date": "2027-01-10",
        "quantity_remaining": "0 kg"
      },
      "traceable_since": "2026-01-10T09:00:00Z",
      "is_consumed": true
    },
    {
      "id": "uuid",
      "type": "execution",
      "label": "Widget Assembly · Run #14",
      "sublabel": "Completed 2026-02-01 · 4 steps",
      "discriminators": {
        "process_name": "Widget Assembly",
        "status": "completed",
        "started_at": "2026-02-01T08:00:00Z"
      },
      "traceable_since": "2026-02-01T08:00:00Z"
    }
  ],
  "total": 142,
  "page": 1
}
```

**`POST /api/core/sourcemap/trace`** — On-demand DAG traversal

```json
// Request
{
  "root_type": "inventory_item",
  "root_id": "uuid",
  "as_of": "2026-02-01T12:00:00Z",   // optional; omit for current state
  "depth": 6                           // optional; default 5
}

// Response
{
  "root": { "id": "...", "type": "inventory_item", "label": "..." },
  "nodes": [
    {
      "id": "...",
      "type": "inventory_item",
      "entity_type": "inventory_item",
      "label": "...",
      "state": { /* entity payload at as_of, or current state */ },
      "events": [  /* optional: key events for story view */
        { "event_type": "inventory_item.consumed", "created_at": "...", "summary": "..." }
      ]
    }
  ],
  "edges": [
    { "from": "uuid", "to": "uuid", "relationship": "consumed_by", "execution_id": "...", "at": "..." }
  ],
  "as_of": "2026-02-01T12:00:00Z",
  "is_current": false,
  "story": [   /* ordered timeline of events in this subgraph */
    { "at": "...", "event_type": "...", "entity_id": "...", "summary": "...", "actor": "..." }
  ]
}
```

**`GET /api/core/sourcemap/entity/:type/:id/story`** — Timeline of events for a single entity

Returns the full event history for one entity, ordered chronologically. Used when drilling into a node on the sourcemap.

```json
{
  "entity_id": "uuid",
  "entity_type": "inventory_item",
  "events": [
    {
      "id": "uuid",
      "event_type": "inventory_item.created",
      "at": "2026-01-10T09:00:00Z",
      "actor": "john@acme.com",
      "summary": "Batch #dsnjkanf8 created: 50 kg received from Acme Metals",
      "payload": { ... },
      "diff": null,
      "caused_by": null
    },
    {
      "id": "uuid",
      "event_type": "inventory_item.consumed",
      "at": "2026-02-01T10:23:00Z",
      "actor": "sarah@acme.com",
      "summary": "25 kg consumed by Execution #4421 (Widget Assembly, Step 2)",
      "payload": { ... },
      "diff": { "quantity": { "before": "50.0000", "after": "25.0000" } },
      "caused_by": { "event_type": "execution.step_completed", "id": "uuid" }
    }
  ]
}
```

---

## 8. Card Enrichment Across the Platform

Cards are the primary UI primitive — every inventory item, execution, and process is presented as a card somewhere in the platform. Currently cards show only what's in the mutable tables: name, quantity, status, dates. The event log makes it possible to show a richer, more useful picture on every card without any additional user input.

This section defines what each card type gains, the query patterns that power it, and the infrastructure needed to keep those queries fast in list views.

---

### 8.1 What Each Card Type Gains

#### Inventory Item Cards

| Data point | Derived from |
|---|---|
| "Added by [name] on [date]" | `inventory_item.created` → `actor_label`, `created_at` |
| "Added from [process name]" or "Purchased from [supplier]" | `inventory_item.created` payload → `source_execution_id` present = produced; absent = purchased |
| "Last used [X days ago] in [process name]" | Last `inventory_item.consumed` event → `created_at`, payload `execution_name` |
| "Used [N] times across [M] processes" | Count + distinct `process_id` from all `inventory_item.consumed` events |
| "Currently in use by [N] active executions" | `inventory_item.consumed` events whose `execution_id` maps to an in-progress execution |
| "[N] wastage events · [total qty] wasted" | Count + sum from `inventory_item.wasted` events |
| Quantity history sparkline | `inventory_item.quantity_adjusted` events ordered by `created_at` → plot `quantity_after` |
| "Never used" / "Fully consumed" / "Partially consumed" status hint | Derived from consumed count vs current quantity |
| "Expiring in [N] days — used in [M] active executions" | `expiry_date` proximity + count of in-progress executions referencing this item |

#### Execution (Batch) Cards

| Data point | Derived from |
|---|---|
| "Started by [name]" | `execution.created` → `actor_label` |
| "Process version [N] — definition from [date]" | `execution.process_version_id` → `process_versions.version_number` + `created_at` |
| "Step [X] of [Y] — last activity [N mins ago]" | Last `execution.step_completed` event `created_at` (supplements live status) |
| "Consumed so far: [item list with quantities]" | Aggregate `items_consumed` arrays from all `execution.step_completed` events for this execution |
| "Produced so far: [item list with quantities]" | Aggregate `items_produced` arrays from all `execution.step_completed` events |
| "[N] evidence files attached" | Count `evidence_ids` across all `execution.step_completed` event payloads |
| "Last action by [name]" | Last event for this execution → `actor_label` |
| Step timing: avg per step, slowest step | Pairs of `execution.step_started` + `execution.step_completed` timestamps |

#### Process Cards

| Data point | Derived from |
|---|---|
| "Version [N] — last updated [X days ago] by [name]" | `process_versions.version_number` max + last `process.step_updated` or `process.updated` → `actor_label` |
| "What changed in latest version" | Last `process.step_added` / `process.step_updated` / `process.step_deleted` → `change_summary` |
| "[N] total runs · [M] completed · [P] active" | Count `execution.created`, `execution.completed`, active executions |
| "Success rate [X%]" | Count `execution.completed` / (completed + failed + cancelled) events |
| "Avg completion time [X hrs]" | Avg of (`execution.completed`.created_at − `execution.started`.created_at) |
| "Last run [X days ago] by [name]" | Last `execution.created` event → `created_at`, `actor_label` |
| "Never run" indicator | Zero `execution.created` events |
| "Draft — not yet run" | `is_draft` = true + zero executions |

---

### 8.2 Query Patterns

All card enrichment reduces to three query shapes against `entity_events`:

**Pattern A — Last event of a specific type for an entity:**
```sql
SELECT payload, created_at, actor_label
FROM entity_events
WHERE entity_id = $id AND event_type = $type
ORDER BY created_at DESC
LIMIT 1
```
Covered by `ix_entity_events_entity_time`. Fast.

**Pattern B — Count (and optional aggregate) of a specific event type:**
```sql
SELECT COUNT(*), SUM((payload->>'quantity_consumed')::numeric)
FROM entity_events
WHERE entity_id = $id AND event_type = 'inventory_item.consumed'
```
Covered by `ix_entity_events_org_entity`. Fast for single entities.

**Pattern C — Distinct related entities across events:**
```sql
SELECT DISTINCT payload->>'process_id' AS process_id
FROM entity_events
WHERE entity_id = $id AND event_type = 'inventory_item.consumed'
```

These patterns are fast for a single card. The problem is **list views**: rendering 50 inventory item cards on the inventory page cannot make 50 × N summary queries. That requires the `entity_event_summaries` read model described next.

---

### 8.3 `entity_event_summaries` — The Read Model for List Views

For individual card detail views, query `entity_events` directly. For list views where many cards are rendered at once, use a pre-computed summary table that is upserted on every event write.

```sql
CREATE TABLE entity_event_summaries (
    entity_id       UUID            PRIMARY KEY,
    org_id          UUID            NOT NULL REFERENCES organisations(id),
    entity_type     VARCHAR(100)    NOT NULL,
    summary         JSONB           NOT NULL,
    last_event_at   TIMESTAMPTZ     NOT NULL,
    last_event_type VARCHAR(100)    NOT NULL,
    last_actor      VARCHAR(255),   -- denormalized for list display
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX ix_entity_summaries_org_type ON entity_event_summaries (org_id, entity_type);
CREATE INDEX ix_entity_summaries_last_event ON entity_event_summaries (org_id, entity_type, last_event_at DESC);
```

The `summary` JSONB shape is entity-type-specific:

```json
// inventory_item summary
{
  "created_by": "john@acme.com",
  "created_at": "2026-01-10T09:00:00Z",
  "last_consumed_at": "2026-02-01T10:23:00Z",
  "last_consumed_by": "sarah@acme.com",
  "last_consumed_execution": "Widget Assembly · Run #14",
  "times_consumed": 3,
  "processes_used_in": 2,
  "wastage_event_count": 0,
  "total_quantity_wasted": "0.0000",
  "quantity_history": [
    { "at": "2026-01-10T09:00:00Z", "qty": "50.0000" },
    { "at": "2026-02-01T10:23:00Z", "qty": "25.0000" }
  ],
  "status_hint": "partially_consumed"
}

// execution summary
{
  "created_by": "sarah@acme.com",
  "created_at": "2026-02-01T08:00:00Z",
  "process_version": 3,
  "process_version_date": "2026-01-28T14:00:00Z",
  "last_step_completed_at": "2026-02-01T10:23:00Z",
  "last_step_actor": "sarah@acme.com",
  "steps_completed": 2,
  "evidence_count": 4,
  "items_consumed": [
    { "item_id": "uuid", "name": "Steel Rod 10mm", "qty": "25.0000", "unit": "kg" }
  ],
  "items_produced": []
}

// process summary
{
  "current_version": 3,
  "last_modified_at": "2026-01-28T14:00:00Z",
  "last_modified_by": "john@acme.com",
  "last_change_summary": "Added QC step",
  "total_runs": 14,
  "completed_runs": 11,
  "failed_runs": 1,
  "cancelled_runs": 0,
  "active_runs": 2,
  "avg_completion_hours": 4.2,
  "last_run_at": "2026-02-01T08:00:00Z",
  "last_run_by": "sarah@acme.com"
}
```

**Update mechanism:** The `EventWriter.emit()` method upserts into `entity_event_summaries` after writing the event, within the same transaction. The upsert logic is entity-type-specific (a small function per entity type that knows how to update the summary from the new event).

```python
# In EventWriter.emit(), after adding the EntityEvent:
_upsert_summary(self.session, event)
```

This keeps the summary always consistent — it is updated atomically with the event that caused it. If the transaction rolls back, the summary update also rolls back.

**Important:** `quantity_history` in the inventory summary should be capped (last N entries, e.g. 50) to prevent unbounded JSONB growth on heavily-traded items. Older history remains fully queryable from `entity_events` directly.

---

### 8.4 New API Endpoint — Entity Summary

**`GET /api/core/entities/:type/:id/summary`** — Full computed summary for a single card detail view

Used when the user opens an individual card. Returns more detail than the list-view summary table, and can query `entity_events` directly rather than the pre-computed summary.

```json
{
  "entity_id": "uuid",
  "entity_type": "inventory_item",
  "summary": {
    "created_by": "john@acme.com",
    "created_at": "...",
    "last_consumed_at": "...",
    "last_consumed_by": "...",
    "last_consumed_execution": "Widget Assembly · Run #14",
    "times_consumed": 3,
    "processes_used_in": ["Widget Assembly", "Frame Assembly"],
    "wastage_event_count": 0,
    "total_quantity_wasted": "0.0000 kg",
    "currently_in_active_executions": 0,
    "quantity_history": [ ... ]
  },
  "recent_events": [
    {
      "event_type": "inventory_item.consumed",
      "at": "...",
      "actor": "sarah@acme.com",
      "summary": "25 kg consumed by Execution #4421 (Widget Assembly, Step 2)"
    }
  ]
}
```

**`POST /api/core/entities/summaries`** — Batch summary fetch for list views (fallback)

If `entity_event_summaries` is not yet populated for some entities (e.g. during Phase 1 of rollout), the list endpoint can fall back to this batch endpoint:

```json
// Request
{ "entities": [{ "type": "inventory_item", "id": "uuid" }, ...] }

// Response  
{ "summaries": { "uuid": { ... }, "uuid": { ... } } }
```

In practice, once `entity_event_summaries` is being maintained, list endpoints should JOIN to it directly and include the summary in the list response rather than making a second request.

---

### 8.5 Integration with List Endpoints

Once `entity_event_summaries` is populated, list endpoints can JOIN it to include enrichment inline:

```python
# In list_inventory_items():
# JOIN entity_event_summaries on entity_id to include summary per item
# The summary JSONB is passed through as-is in the response
# Frontend reads summary.last_consumed_at, summary.times_consumed, etc.
```

This means the inventory list page, the process list page, and the executions list page all get card enrichment data in a single query — no second round-trip. The JOIN cost is a primary-key lookup on `entity_event_summaries` which is negligible.

---

## 9. Sourcemap Frontend Architecture

This replaces the current page-load-everything approach.

### 9.1 Page Load

Three fast requests fire in parallel:
1. `GET /api/core/sourcemap/objects?page=1&limit=50` — populate selectors
2. `GET /api/core/system-findings` — existing (keep)
3. Static assets (already 304-cached)

No inventory data, no executions data, no process steps. Just the index.

### 9.2 Selector UX

Group objects by type in the left panel:
- **Inventory Items** (grouped by name, then list batches as sub-items)
- **Executions** (grouped by process name)
- **Processes**

Batch disambiguation: clicking "Steel Rod 10mm" expands to show all batches with their discriminator fields (supplier, batch number, date received, quantity remaining). User selects a specific batch, then clicks Trace.

Search box filters the index client-side (already loaded) or triggers `GET /api/core/sourcemap/objects?q=steel+rod` for larger datasets.

### 9.3 On Trace

1. POST to `/api/core/sourcemap/trace` with `{root_type, root_id}` — no `as_of` for current state
2. Render the returned `{nodes, edges}` graph
3. Each node in the graph is clickable to drill in and see its story (GET entity story endpoint)

### 9.4 Historical Trace ("at consumption" view)

When viewing an inventory item node, a sidebar shows key events (its story). One of those events will be `inventory_item.consumed` with a timestamp. A button "Trace as of this moment" re-fires POST with `as_of = consumed_at`. The graph rebuilds showing the historical state.

The user can toggle between "Now" and each historical snapshot using a timeline slider or event list.

---

## 10. Migration Phases

Since the platform is pre-launch, there is no live data to migrate. Phase ordering is by dependency. Phases 1–5 are pure infrastructure with no visible UI changes. Card enrichment (Phase 6) and the sourcemap rebuild (Phases 7–8) are built on top of that foundation.

### Phase 1 — New Tables (DB migrations, no app changes)
- [ ] Add `entity_events` table with all indexes
- [ ] Add `entity_event_summaries` table with indexes
- [ ] Add `process_versions` table
- [ ] Add `process_version_id` to `executions`
- [ ] Add `display_label` to `inventory_items`

### Phase 2 — EventWriter & Middleware
- [ ] Create `app/core/backend/event_writer.py` including `_upsert_summary()` dispatch
- [ ] Create per-entity summary updater functions (one per entity type: `_update_inventory_summary`, `_update_execution_summary`, `_update_process_summary`)
- [ ] Add `g.correlation_id = uuid4()` to request lifecycle (in `before_request` hook in middleware)
- [ ] Add `g.current_user_id` and `g.current_user_email` population to `@requires_auth` (verify already done)
- [ ] Create `EntityEvent` and `EntityEventSummary` SQLAlchemy models

### Phase 3 — Process Versioning
- [ ] Hook `ProcessRepository.create_process` → insert process_versions row (v1), emit `process.created`
- [ ] Hook `ProcessRepository.update_process` → insert process_versions row, emit `process.updated`
- [ ] Hook `ProcessRepository.add_step` → insert process_versions row, emit `process.step_added`
- [ ] Hook `ProcessRepository.update_step` → insert process_versions row, emit `process.step_updated`
- [ ] Hook `ProcessRepository.delete_step` → insert process_versions row, emit `process.step_deleted`
- [ ] Hook `ProcessRepository.delete_process` → emit `process.deleted`
- [ ] Hook `ExecutionRepository.create_execution` → set `process_version_id` on execution

### Phase 4 — Inventory & Execution Events
- [ ] Hook `InventoryRepository.create_inventory_item` → emit `inventory_item.created`
- [ ] Hook `InventoryRepository.add_quantity_to_inventory_item` → emit `inventory_item.quantity_adjusted`
- [ ] Hook `InventoryRepository.update_inventory_item` → compute diff, emit `inventory_item.updated`
- [ ] Hook `InventoryRepository.delete_inventory_item` → emit `inventory_item.deleted`
- [ ] Hook `WastageRepository.create_wastage_record` → emit `inventory_item.wasted`
- [ ] Hook `ExecutionRepository.complete_step` → emit `execution.step_completed` and all downstream events with causation chain (see Section 6)
- [ ] Hook execution status transitions → emit `execution.started`, `execution.completed`, `execution.failed`, `execution.cancelled`

### Phase 5 — Auth Events
- [ ] Hook login success/failure → emit `user.login` / `user.login_failed`
- [ ] Hook user mutations → emit remaining user events

### Phase 6 — Card Enrichment API & Frontend
This phase delivers visible value immediately on existing pages before the sourcemap rebuild begins.
- [ ] Implement `GET /api/core/entities/:type/:id/summary` — per-entity summary endpoint (queries `entity_events` directly, used for individual card detail views)
- [ ] Update `GET /api/core/inventory` list endpoint to JOIN `entity_event_summaries` and include `event_summary` field per item
- [ ] Update `GET /api/core/executions` list endpoint to include `event_summary` field per execution
- [ ] Update `GET /api/core/processes` list endpoint to include `event_summary` field per process
- [ ] Update inventory item cards to display: added by, last used, times consumed, wastage count
- [ ] Update execution (batch) cards to display: started by, process version, materials consumed/produced, evidence count
- [ ] Update process cards to display: version number, last modified by, total runs, success rate, last run

### Phase 7 — Traceable Objects Index Endpoint
- [ ] Implement `GET /api/core/sourcemap/objects` — queries across inventory_items + executions + processes, assembles lightweight objects with discriminator fields
- [ ] Query only id, name, key discriminator columns — never joins to steps or execution_steps

### Phase 8 — Temporal Trace Endpoint
- [ ] Create `app/core/backend/temporal_dag_tracer.py` with `TemporalDAGTracer`
- [ ] Implement `POST /api/core/sourcemap/trace` — routes to `DAGTraversal.py` (current) or `TemporalDAGTracer` (historical) based on `as_of`
- [ ] Implement `GET /api/core/sourcemap/entity/:type/:id/story`

### Phase 9 — Sourcemap Frontend Rebuild
- [ ] Replace page-load-everything with index load + on-demand trace
- [ ] Build selector UI (grouped by type, batch disambiguation)
- [ ] Build graph renderer consuming `{nodes, edges}` from trace endpoint
- [ ] Build story/timeline panel for individual nodes
- [ ] Build "Trace as of this moment" historical replay UI

---

## 11. What NOT to Change

- **`inventory_movements` table** — keep as-is. It is a financial-grade ledger for quantity changes. The new `inventory_item.quantity_adjusted` events complement it; they do not replace it.
- **`DAGTraversal.py`** — keep entirely for current-state queries. Do not modify to add temporal logic. Temporal gets its own class.
- **`audit_logs` table** — keep, do not remove. It predates this system and may be referenced elsewhere. Going forward it can be populated from entity_events if desired, but is not authoritative.
- **`InventoryQuantityWriteReason` enum** — keep and extend. Use its values as the `reason` field in `inventory_item.quantity_adjusted` events.
- **All existing mutable tables** — keep as the source of current state. `entity_events` is additive.
- **`api_idempotency_keys`** — keep. Idempotency of HTTP requests is separate from event sourcing.

---

## 12. Testing Requirements

The event log is only as good as its completeness guarantee. Tests must verify:

1. **Every repository mutation emits the expected event(s)** — test at the repository layer, not the route layer. After each mutation, assert that an `entity_events` row exists with the correct `event_type`, `entity_id`, and key `payload` fields.

2. **`complete_step` emits the full causal chain** — assert that `execution.step_completed`, `inventory_item.consumed` (for each input), and `inventory_item.produced` (for each output) all exist with matching `causation_id`.

3. **Transaction rollback removes the event** — if the parent transaction rolls back, no orphan event row should exist.

4. **Temporal reconstruction matches known state** — create entities, run mutations, then query `entity_events` with `as_of = timestamp_between_mutations` and verify the reconstructed state matches what was true at that time.

5. **Process version captures steps correctly** — after adding/modifying/deleting a step, assert that `process_versions` snapshot reflects the new state and the previous version is unchanged.

6. **Temporal trace returns different graph than current trace** — integration test: create a process, run an execution, modify the process (add a step), then assert that trace with `as_of = before_modification` returns the old process version in the graph nodes, and current trace returns the new version.

7. **`entity_event_summaries` is always consistent with `entity_events`** — after each mutation, assert that the summary row for that entity reflects the new event. Assert that rolling back the transaction also rolls back the summary update.

8. **Card enrichment data is accurate** — after consuming an inventory item, assert that the item's summary shows `times_consumed` incremented and `last_consumed_at` updated. After completing an execution, assert the process summary shows `completed_runs` incremented and `avg_completion_hours` recalculated.

9. **Summary `quantity_history` is capped** — after writing more than 50 quantity adjustments to a single item, assert that `summary.quantity_history` contains exactly 50 entries (the most recent), and that all events remain in `entity_events`.

---

## 13. Key Invariants (Enforce in Code)

1. **Event emission is inside the parent transaction.** Never commit an event separately from its triggering mutation.

2. **Payload is always the full entity state after the event.** Never store a partial payload. If you can't reconstruct the entity from the payload alone, the payload is incomplete.

3. **Never delete from `entity_events`.** Tombstone events (e.g., `inventory_item.deleted`) are how deletions are recorded. The event log is immutable.

4. **`process_versions` is updated on every process or step mutation.** There is no "skip versioning" path. If a mutation touches `processes` or `steps`, a new version row is created.

5. **`execution.process_version_id` is set at creation and never changed.** It is the permanent record of which process definition the execution ran against.

6. **`correlation_id` is always set from `g.correlation_id`.** If `g.correlation_id` is somehow absent, generate a new UUID rather than leaving it null.

7. **`entity_event_summaries` is updated in the same transaction as the event.** Never update the summary in a separate transaction or a background task. Eventual consistency between events and summaries is not acceptable — a card showing stale data immediately after a mutation is a trust problem.

8. **`entity_event_summaries.quantity_history` is capped at 50 entries.** The upsert logic must enforce this cap. Full history is always available from `entity_events`; the summary is for fast card display only.
