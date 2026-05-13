"""Repository for XeroTenant records."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.features.crm.models.xero_tenant import XeroTenant


class XeroTenantRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(
        self,
        org_id: UUID,
        xero_tenant_id: str,
        xero_tenant_name: str | None,
        xero_tenant_type: str | None,
    ) -> XeroTenant:
        tenant = (
            self.db.query(XeroTenant)
            .filter(
                XeroTenant.org_id == org_id,
                XeroTenant.xero_tenant_id == xero_tenant_id,
            )
            .first()
        )

        if tenant:
            tenant.xero_tenant_name = xero_tenant_name
            tenant.xero_tenant_type = xero_tenant_type
            tenant.is_connected = True
            tenant.connected_at = datetime.utcnow()
            tenant.disconnected_at = None
            tenant.updated_at = datetime.utcnow()
        else:
            tenant = XeroTenant(
                org_id=org_id,
                xero_tenant_id=xero_tenant_id,
                xero_tenant_name=xero_tenant_name,
                xero_tenant_type=xero_tenant_type,
                is_connected=True,
                connected_at=datetime.utcnow(),
            )
            self.db.add(tenant)

        return tenant

    def get_connected(self, org_id: UUID) -> XeroTenant | None:
        return (
            self.db.query(XeroTenant)
            .filter(
                XeroTenant.org_id == org_id,
                XeroTenant.is_connected == True,  # noqa: E712
            )
            .first()
        )

    def mark_disconnected(self, org_id: UUID) -> None:
        self.db.query(XeroTenant).filter(XeroTenant.org_id == org_id).update(
            {"is_connected": False, "disconnected_at": datetime.utcnow(), "updated_at": datetime.utcnow()}
        )

    def update_last_sync(self, org_id: UUID, synced_at: datetime) -> None:
        self.db.query(XeroTenant).filter(
            XeroTenant.org_id == org_id,
            XeroTenant.is_connected == True,  # noqa: E712
        ).update({"last_successful_sync_at": synced_at, "updated_at": datetime.utcnow()})
