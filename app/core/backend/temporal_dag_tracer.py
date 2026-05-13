"""Temporal DAG tracer: reconstruct entity relationships at a point in time.

Queries entity_events to build the graph as it existed at `as_of`, rather than
querying current mutable state. Used by the sourcemap temporal replay feature.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session


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
        nodes = self._build_node_list(connected, root_str, root_type, root_state)

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
                EntityEvent.created_at <= self.as_of,
            )
            .order_by(EntityEvent.created_at.desc())
            .limit(1)
            .first()
        )
        return ev.payload if ev else None

    def _build_node_list(
        self, connected: set[str], root_str: str, root_type: str, root_state: dict | None
    ) -> list[dict]:
        nodes: list[dict] = [{"id": root_str, "type": root_type, "is_root": True, "state": root_state}]
        for nid in connected:
            if nid == root_str:
                continue
            nodes.append({"id": nid, "type": None, "is_root": False, "state": None})
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
