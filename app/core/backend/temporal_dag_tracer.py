"""Temporal DAG tracer: reconstruct entity relationships at a point in time.

Queries entity_events to build the graph as it existed at `as_of`, rather than
querying current mutable state. Used by the sourcemap temporal replay feature.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.observability import traced

# Kept as a local copy rather than importing from dagtraversal.py — the two tracers are
# siblings with no existing cross-import. Matches dagtraversal._TRACE_METADATA_INTERNAL_KEYS
# / backend._EXECUTION_DATA_TRACE_KEYS exactly, so batch_id/custom_prompts mean the same
# thing whether they came from the current-state trace or this temporal one.
_TRACE_METADATA_INTERNAL_KEYS = {
    "completed_by",
    "completed_by_email",
    "completed_by_user_id",
    "completed_at",
    "execution_errors",
    "execution_warnings",
}
_SYSTEM_PROMPT_LABELS = {"batch number", "evidence"}


def _split_temporal_prompts(execution_data: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Same "Batch number" / custom-prompt split as dagtraversal._split_trace_prompts,
    applied to an execution.step_completed event's execution_data payload."""
    batch_id: str | None = None
    custom_prompts: dict[str, Any] = {}
    for key, value in execution_data.items():
        if key in _TRACE_METADATA_INTERNAL_KEYS or value is None or value == "":
            continue
        label = key.strip().lower()
        if label == "batch number":
            batch_id = value
        elif label in _SYSTEM_PROMPT_LABELS:
            continue
        else:
            custom_prompts[key] = value
    return batch_id, custom_prompts


class TemporalDAGTracer:
    """Reconstruct the provenance graph at a point in time using entity_events.

    Algorithm:
    1. Query all execution.step_completed events up to `as_of`.
    2. Extract consumed/produced item edges from each event payload.
    3. BFS from `root_id` up to `max_depth` hops to collect connected nodes.
    4. Return the subgraph (nodes + edges) as a serialisable dict.
    """

    def __init__(self, db: Session, org_id: UUID, as_of: datetime, max_depth: int = 5):
        self.db = db
        self.org_id = org_id
        self.as_of = as_of
        self.max_depth = min(max_depth, 10)

    @traced(
        "dag.temporal_trace",
        attributes_fn=lambda self, root_id, root_type="inventory_item": {
            "org_id": str(self.org_id),
            "root_id": str(root_id),
            "root_type": root_type,
            "max_depth": self.max_depth,
        },
    )
    def trace(self, root_id: UUID, root_type: str = "inventory_item") -> dict:
        """Return temporal graph rooted at root_id, as of self.as_of."""
        from app.core.db.models.entity_event import EntityEvent

        step_events = (
            self.db.query(EntityEvent)
            .filter(
                EntityEvent.org_id == self.org_id,
                EntityEvent.event_type == "execution.step_completed",
                EntityEvent.created_at <= self.as_of,
            )
            .order_by(EntityEvent.created_at.asc())
            .all()
        )

        edges: list[dict] = []
        for ev in step_events:
            p = ev.payload or {}
            exec_id = p.get("execution_id")
            if not exec_id:
                continue
            for c in p.get("items_consumed") or []:
                item_id = c.get("item_id")
                if item_id:
                    edges.append(
                        {
                            "from": str(item_id),
                            "to": str(exec_id),
                            "relationship": "consumed_by",
                            "execution_id": str(exec_id),
                            "quantity": c.get("quantity"),
                            "unit": c.get("unit"),
                            "at": ev.created_at.isoformat() if ev.created_at else None,
                        }
                    )
            for prod in p.get("items_produced") or []:
                item_id = prod.get("item_id")
                if item_id:
                    edges.append(
                        {
                            "from": str(exec_id),
                            "to": str(item_id),
                            "relationship": "produced",
                            "execution_id": str(exec_id),
                            "quantity": prod.get("quantity"),
                            "unit": prod.get("unit"),
                            "at": ev.created_at.isoformat() if ev.created_at else None,
                        }
                    )

        root_str = str(root_id)
        connected: set[str] = {root_str}
        for _ in range(self.max_depth):
            new_conn: set[str] = set()
            for e in edges:
                if e["from"] in connected:
                    new_conn.add(e["to"])
                if e["to"] in connected:
                    new_conn.add(e["from"])
            if not new_conn - connected:
                break
            connected |= new_conn

        filtered_edges = [e for e in edges if e["from"] in connected and e["to"] in connected]

        root_state = self._snapshot_at(root_id)
        node_metadata = self._collect_node_metadata(step_events)
        nodes = self._build_node_list(connected, root_str, root_type, root_state, node_metadata)

        timeline = self._build_timeline(connected)

        return {
            "root_id": root_str,
            "root_type": root_type,
            "as_of": self.as_of.isoformat(),
            "nodes": nodes,
            "edges": filtered_edges,
            "timeline": timeline,
        }

    def _snapshot_at(self, entity_id: UUID) -> dict | None:
        from app.core.db.models.entity_event import EntityEvent

        ev = (
            self.db.query(EntityEvent)
            .filter(
                EntityEvent.entity_id == entity_id,
                EntityEvent.org_id == self.org_id,
                EntityEvent.created_at <= self.as_of,
            )
            .order_by(EntityEvent.created_at.desc())
            .limit(1)
            .first()
        )
        return ev.payload if ev else None

    def _collect_node_metadata(self, step_events: list) -> dict[str, dict[str, Any]]:
        """Per-node batch_id/custom_prompts, keyed by item_id or execution_id, sourced from
        the same execution.step_completed events already fetched to build edges — no extra
        query. An execution node can accumulate metadata from more than one of its steps;
        later (chronologically later, since step_events is created_at-ascending) non-empty
        values win, matching the "last completed step" convention sourcemap.js already uses
        for completed_by."""
        metadata: dict[str, dict[str, Any]] = {}

        def _merge(node_id: str, batch_id: str | None, custom_prompts: dict[str, Any]) -> None:
            if not batch_id and not custom_prompts:
                return
            entry = metadata.setdefault(node_id, {})
            if batch_id:
                entry["batch_id"] = batch_id
            if custom_prompts:
                entry.setdefault("custom_prompts", {}).update(custom_prompts)

        for ev in step_events:
            p = ev.payload or {}
            execution_data = p.get("execution_data") or {}
            if not execution_data:
                continue
            batch_id, custom_prompts = _split_temporal_prompts(execution_data)
            if not batch_id and not custom_prompts:
                continue
            exec_id = p.get("execution_id")
            if exec_id:
                _merge(str(exec_id), batch_id, custom_prompts)
            for prod in p.get("items_produced") or []:
                item_id = prod.get("item_id")
                if item_id:
                    _merge(str(item_id), batch_id, custom_prompts)
        return metadata

    def _build_node_list(
        self,
        connected: set[str],
        root_str: str,
        root_type: str,
        root_state: dict | None,
        node_metadata: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict]:
        node_metadata = node_metadata or {}
        root_meta = node_metadata.get(root_str, {})
        nodes: list[dict] = [
            {
                "id": root_str,
                "type": root_type,
                "is_root": True,
                "state": root_state,
                "batch_id": root_meta.get("batch_id"),
                "custom_prompts": root_meta.get("custom_prompts") or {},
            }
        ]
        for nid in connected:
            if nid == root_str:
                continue
            meta = node_metadata.get(nid, {})
            nodes.append(
                {
                    "id": nid,
                    "type": None,
                    "is_root": False,
                    "state": None,
                    "batch_id": meta.get("batch_id"),
                    "custom_prompts": meta.get("custom_prompts") or {},
                }
            )
        return nodes

    def _build_timeline(self, connected: set[str]) -> list[dict]:
        from app.core.db.models.entity_event import EntityEvent

        valid_uuids: list[UUID] = []
        for nid in connected:
            try:
                valid_uuids.append(UUID(nid))
            except ValueError:
                pass

        if not valid_uuids:
            return []

        evs = (
            self.db.query(EntityEvent)
            .filter(
                EntityEvent.org_id == self.org_id,
                EntityEvent.entity_id.in_(valid_uuids),
                EntityEvent.created_at <= self.as_of,
            )
            .order_by(EntityEvent.created_at.asc())
            .limit(200)
            .all()
        )
        return [
            {
                "event_id": str(ev.id),
                "event_type": ev.event_type,
                "entity_id": str(ev.entity_id),
                "actor": ev.actor_label,
                "at": ev.created_at.isoformat() if ev.created_at else None,
            }
            for ev in evs
        ]
