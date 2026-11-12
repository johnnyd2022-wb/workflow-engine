"""Xero chart of accounts cache (live-cogs 8.1b).

``default_treatment`` is recomputed from the account on every sync; ``treatment_override`` is set
only by a person (costing accounts API) and never touched by sync. Effective treatment =
override, else default. ``default_treatment`` is null for non-expense accounts: their lines are
never stored.
"""

import uuid

from sqlalchemy import TIMESTAMP, CheckConstraint, Column, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now

TREATMENTS = ("stock", "not_stock", "duty", "overhead")


class XeroAccount(TenantScoped, Base):
    __tablename__ = "xero_accounts"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_xero_accounts_org_id"),
        UniqueConstraint("org_id", "xero_account_id", name="uq_xero_accounts_org_xero"),
        CheckConstraint(
            "treatment_override IS NULL OR treatment_override IN ('stock','not_stock','duty','overhead')",
            name="ck_xero_accounts_override",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    xero_account_id = Column(String(100), nullable=False)
    code = Column(String(50), nullable=True)
    name = Column(String(255), nullable=True)
    type = Column(String(50), nullable=True)
    account_class = Column(String(50), nullable=True)
    status = Column(String(50), nullable=True)
    default_treatment = Column(String(20), nullable=True)
    treatment_override = Column(String(20), nullable=True)
    last_synced_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    @property
    def treatment(self) -> str | None:
        return self.treatment_override or self.default_treatment
