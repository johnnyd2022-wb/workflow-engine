"""Xero chart of accounts, cached per organisation (live-cogs 8.1b).

Read-only copy of Xero's Accounts. ``default_treatment`` is what Biz-E decides a purchase coded
to the account is (spec .agents/specs/live-cogs.md, "Deciding what is a stock purchase", Layer
1); it is ``NULL`` for accounts that are not expense accounts, because spending on those is not
stored. Per-account overrides arrive with the purchase rules (8.1c).
"""

import uuid

from sqlalchemy import TIMESTAMP, CheckConstraint, Column, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class XeroAccount(TenantScoped, Base):
    __tablename__ = "xero_accounts"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_xero_accounts_org_id"),
        UniqueConstraint("org_id", "xero_account_id", name="uq_xero_accounts_org_xero_account"),
        CheckConstraint(
            "default_treatment IS NULL OR default_treatment IN ('stock','not_stock','duty','overhead')",
            name="ck_xero_accounts_default_treatment",
        ),
        Index("ix_xero_accounts_org_code", "org_id", "code"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    xero_account_id = Column(String(100), nullable=False)
    code = Column(String(50), nullable=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=True)  # Xero type: DIRECTCOSTS, EXPENSE, OVERHEADS, BANK, ...
    account_class = Column(String(20), nullable=True)  # Xero class: ASSET, EXPENSE, REVENUE, ...
    status = Column(String(20), nullable=True)  # ACTIVE | ARCHIVED
    default_treatment = Column(String(20), nullable=True)
    last_synced_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
