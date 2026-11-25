from datetime import datetime
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.utils.time import utc_now
from app.features.crm.models.xero_pending_connection import XeroPendingConnection


class XeroPendingConnectionRepository:
    def __init__(self, db: Session):
        self.db = db

    def put(
        self,
        org_id: UUID,
        user_id: UUID,
        selection_id: UUID,
        connections: list[dict],
        credentials_encrypted: str,
        token_expires_at: datetime,
        expires_at: datetime,
    ) -> None:
        values = {
            "id": selection_id,
            "user_id": user_id,
            "connections": connections,
            "credentials_encrypted": credentials_encrypted,
            "token_expires_at": token_expires_at,
            "expires_at": expires_at,
        }
        statement = insert(XeroPendingConnection).values(org_id=org_id, **values)
        self.db.execute(statement.on_conflict_do_update(index_elements=["org_id"], set_=values))

    def get(
        self, org_id: UUID, user_id: UUID, selection_id: UUID, *, lock: bool = False
    ) -> XeroPendingConnection | None:
        query = self.db.query(XeroPendingConnection).filter(
            XeroPendingConnection.org_id == org_id,
            XeroPendingConnection.user_id == user_id,
            XeroPendingConnection.id == selection_id,
            XeroPendingConnection.expires_at > utc_now(),
        )
        if lock:
            query = query.with_for_update()
        return query.one_or_none()

    def clear(self, org_id: UUID) -> None:
        self.db.query(XeroPendingConnection).filter(XeroPendingConnection.org_id == org_id).delete(
            synchronize_session=False
        )
