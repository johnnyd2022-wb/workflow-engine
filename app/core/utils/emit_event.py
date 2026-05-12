"""Utility for emitting entity events from outside a repository transaction.

Used by auth routes, which manage their own sessions separately.
Follows the same pattern as log_action: separate session, fire-and-forget,
never fails the calling request.
"""

from uuid import UUID

from app.core.db import SessionLocal


def emit_event(
    event_type: str,
    entity_type: str,
    entity_id: UUID,
    payload: dict,
    org_id: UUID,
    actor_id: UUID | None = None,
    actor_label: str | None = None,
    actor_type: str = "user",
    diff: dict | None = None,
) -> None:
    """Emit one entity event in a separate session (fire-and-forget).

    Never raises — caller is never blocked by event emission failure.
    Suitable for auth routes that manage their own session lifecycles.
    """
    from app.core.backend.event_writer import EventWriter

    db = SessionLocal()
    try:
        ew = EventWriter(db, org_id)
        ew.emit(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            diff=diff,
            actor_id=actor_id,
            actor_label=actor_label,
            actor_type=actor_type,
        )
        db.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("emit_event failed for %s: %s", event_type, e)
        db.rollback()
    finally:
        db.close()
