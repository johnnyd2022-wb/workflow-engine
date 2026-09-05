"""GET /api/core/changes -- a polled change feed over entity_events.

The SPA subscribes to this (client: live-sync.js) so every page reflects org-wide
mutations in near real time without a reload. `entity_events` is already the
event-sourcing spine (EventWriter.emit writes one row per mutation, in the mutation's
transaction); this endpoint exposes it as a cursor feed.

Cursor = entity_events.seq, allocated per-org by EventWriter under an advisory lock held
to commit (see event_writer._next_feed_seq). seq order == commit order per org and seqs
are gap-free per org: a reader that has seen seq N is guaranteed every seq <= N is
committed. There is no settle window -- the seq column has no DB default (migration
entity_events_seq_noident_001 dropped the old IDENTITY), so every insert goes through
that allocator, and (org_id, seq) is UNIQUE so a double-allocation fails loudly rather
than silently corrupting the feed order.

Register with: changes_feed.register_routes(core_bp)
"""

from __future__ import annotations

from uuid import UUID

from flask import g, jsonify, request
from sqlalchemy import bindparam as sa_bindparam
from sqlalchemy import text

from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.observability import get_logger

logger = get_logger(__name__)

_DEFAULT_LIMIT = 200
_MAX_LIMIT = 500

# Only the entity types the SPA re-syncs on are exposed. Keeps `user.*` (login times of
# colleagues, etc.) and any other internal events out of a feed every browser polls.
_SYNCED_ENTITY_TYPES = ("process", "execution", "execution_step", "step", "inventory_item")
# Only routing ids -- never entity state or PII -- are lifted out of the payload so the
# client can decide which events touch the view it is showing.
_KEY_FIELDS = (
    "process_id",
    "execution_id",
    "execution_step_id",
    "step_id",
    "source_execution_id",
)


# Pulled straight out of the JSONB in SQL so the feed never ships the (sometimes large)
# full payload just to read a handful of routing ids.
_KEY_SELECT = ", ".join(f"payload->>'{f}' AS k_{f}" for f in _KEY_FIELDS)


def _keys_from_row(row, entity_type: str, entity_id) -> dict:
    keys: dict = {}
    for f in _KEY_FIELDS:
        v = getattr(row, f"k_{f}", None)
        if v:
            keys[f] = v
    if entity_type == "inventory_item":
        keys["inventory_item_id"] = getattr(row, "k_id", None) or str(entity_id)
    return keys


def register_routes(bp):
    @bp.route("/api/core/changes", methods=["GET"])
    @requires_auth
    def get_changes():
        """Events for this org with seq > `since`, oldest first.

        No `since` -> a bootstrap response: the current head cursor and an empty list, so
        a client can start polling from "now" without replaying history.
        """
        org_id = UUID(g.org_id)
        db = db_session()

        since_raw = request.args.get("since")
        since: int | None = None
        if since_raw is not None and since_raw != "":
            try:
                since = int(since_raw)
            except ValueError:
                return jsonify({"error": "since must be an integer"}), 400
            if since < 0:
                return jsonify({"error": "since must be >= 0"}), 400

        try:
            limit = min(int(request.args.get("limit", _DEFAULT_LIMIT)), _MAX_LIMIT)
        except (TypeError, ValueError):
            return jsonify({"error": "limit must be an integer"}), 400
        if limit < 1:
            return jsonify({"error": "limit must be >= 1"}), 400

        head = db.execute(
            text(
                "SELECT COALESCE(("
                "SELECT seq FROM entity_events "
                "WHERE org_id = :org AND entity_type IN :types "
                "ORDER BY seq DESC LIMIT 1"
                "), 0)"
            ).bindparams(sa_bindparam("types", expanding=True)),
            {"org": str(org_id), "types": list(_SYNCED_ENTITY_TYPES)},
        ).scalar()

        if since is None:
            body = {"cursor": int(head), "has_more": False, "events": []}
            resp = jsonify(body)
            resp.headers["ETag"] = f'"{head}"'
            resp.headers["Cache-Control"] = "no-store"
            return resp, 200

        if request.headers.get("If-None-Match") == f'"{head}"' and since >= head:
            return "", 304

        rows = db.execute(
            text(
                f"""
                SELECT seq, event_type, entity_type, entity_id, created_at,
                       payload->>'id' AS k_id, {_KEY_SELECT}
                FROM entity_events
                WHERE org_id = :org
                  AND seq > :since
                  AND entity_type IN :types
                ORDER BY seq
                LIMIT :lim
                """
            ).bindparams(sa_bindparam("types", expanding=True)),
            {"org": str(org_id), "since": since, "lim": limit + 1, "types": list(_SYNCED_ENTITY_TYPES)},
        ).fetchall()

        has_more = len(rows) > limit
        rows = rows[:limit]

        events = [
            {
                "seq": int(r.seq),
                "event_type": r.event_type,
                "entity_type": r.entity_type,
                "entity_id": str(r.entity_id),
                "at": r.created_at.isoformat() if r.created_at else None,
                "keys": _keys_from_row(r, r.entity_type, r.entity_id),
            }
            for r in rows
        ]
        cursor = events[-1]["seq"] if events else since
        body = {"cursor": cursor, "has_more": has_more, "events": events}
        resp = jsonify(body)
        resp.headers["ETag"] = f'"{head}"'
        resp.headers["Cache-Control"] = "no-store"
        return resp, 200
