"""Audit log repository with tenancy enforcement"""

from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.db.models.audit_log import AuditLog


class AuditRepository:
    """Repository for audit log operations with tenancy enforcement"""

    def __init__(self, db: Session):
        self.db = db

    def write_log(
        self,
        org_id: UUID,
        user_id: UUID | None,
        action: str,
        entity: str,
        entity_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> AuditLog:
        """Write an audit log entry"""
        log = AuditLog(
            org_id=org_id, user_id=user_id, action=action, entity=entity, entity_id=entity_id, meta_data=metadata
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def list_logs_for_org(
        self,
        org_id: UUID,
        user_id: UUID | None = None,
        action: str | None = None,
        entity: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        """List audit logs for an organisation (tenancy enforced)"""
        query = self.db.query(AuditLog).filter(AuditLog.org_id == org_id)

        if user_id is not None:
            query = query.filter(AuditLog.user_id == user_id)
        if action is not None:
            query = query.filter(AuditLog.action == action)
        if entity is not None:
            query = query.filter(AuditLog.entity == entity)

        return query.order_by(desc(AuditLog.timestamp)).limit(limit).offset(offset).all()
