"""Audit logging utility"""

from uuid import UUID

from flask import g

from app.core.db import db_session
from app.core.db.repositories.audit_repo import AuditRepository


def log_action(
    action: str,
    entity: str,
    entity_id: UUID | None = None,
    metadata: dict | None = None,
    org_id: UUID | None = None,
    user_id: UUID | None = None,
) -> None:
    """
    Log an action to the audit log.

    Automatically extracts org_id and user_id from Flask g if not provided.
    Note: Uses a separate session to avoid interfering with the request session.
    """
    # Get org_id and user_id from Flask g if not provided
    if org_id is None and hasattr(g, "current_org_id") and g.current_org_id:
        org_id = g.current_org_id

    if user_id is None and hasattr(g, "current_user") and g.current_user:
        user_id = g.current_user.id

    # Only log if we have an org_id
    if not org_id:
        return

    # Use a separate session for audit logging to avoid conflicts
    db = db_session()
    try:
        audit_repo = AuditRepository(db)
        audit_repo.write_log(
            org_id=org_id, user_id=user_id, action=action, entity=entity, entity_id=entity_id, metadata=metadata
        )
        db.commit()
    except Exception as e:
        # Log error but don't fail the operation
        # In production, you might want to use proper logging
        print(f"Error logging action: {e}")
        db.rollback()
    finally:
        db.close()
