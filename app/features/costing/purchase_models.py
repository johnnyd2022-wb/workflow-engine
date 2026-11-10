"""Purchase facts (live-cogs 8.1b; spec .agents/specs/live-cogs.md, "Data model").

``purchase_documents`` is a source-agnostic header (a Xero bank transaction today) and
``purchase_lines`` its lines, in the org's base currency and excluding GST. They are written by
the sync (``purchase_sources.py``) and, from 8.1c, by the user's decisions on a line (state,
``not_stock_amount``, ``treatment_override``). Nothing here is a cost: costs are computed on read
from facts (``engine.py``).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now

SOURCES = ("xero_bank", "xero_bill", "xero_bill_credit", "manual")
KINDS = ("spend", "refund", "bill", "credit")
DOCUMENT_STATUSES = ("active", "voided")
STATES = ("open", "partly_recorded", "recorded", "skipped", "not_stock")
REVIEW_REASONS = ("amount_changed", "recoded", "deleted_in_xero")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class PurchaseDocument(TenantScoped, Base):
    __tablename__ = "purchase_documents"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_purchase_documents_org_id"),
        UniqueConstraint("org_id", "source", "external_id", name="uq_purchase_documents_source_external"),
        CheckConstraint(_in("source", SOURCES), name="ck_purchase_documents_source"),
        CheckConstraint(_in("kind", KINDS), name="ck_purchase_documents_kind"),
        CheckConstraint(_in("status", DOCUMENT_STATUSES), name="ck_purchase_documents_status"),
        Index("ix_purchase_documents_org_date", "org_id", "document_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(20), nullable=False)
    external_id = Column(String(100), nullable=False)
    kind = Column(String(10), nullable=False)
    payee_name = Column(String(255), nullable=True)
    xero_contact_id = Column(String(100), nullable=True)
    document_date = Column(Date, nullable=False)
    reference = Column(String(255), nullable=True)
    currency_code = Column(String(3), nullable=False, default="NZD", server_default="NZD")
    currency_rate = Column(Numeric(18, 8), nullable=False, default=1, server_default="1")
    status = Column(String(10), nullable=False, default="active", server_default="active")
    total_ex_tax = Column(Numeric(18, 4), nullable=False, default=0, server_default="0")
    total_tax = Column(Numeric(18, 4), nullable=False, default=0, server_default="0")
    external_updated_at = Column(DateTime(timezone=True), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class PurchaseLine(TenantScoped, Base):
    __tablename__ = "purchase_lines"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_purchase_lines_org_id"),
        UniqueConstraint("org_id", "document_id", "line_key", name="uq_purchase_lines_document_key"),
        ForeignKeyConstraint(
            ["org_id", "document_id"],
            ["purchase_documents.org_id", "purchase_documents.id"],
            name="fk_purchase_lines_document",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            _in("treatment", ("stock", "not_stock", "duty", "overhead")), name="ck_purchase_lines_treatment"
        ),
        CheckConstraint(_in("state", STATES), name="ck_purchase_lines_state"),
        CheckConstraint(
            f"review_reason IS NULL OR {_in('review_reason', REVIEW_REASONS)}", name="ck_purchase_lines_review_reason"
        ),
        # The part the owner said is not stock has the line's sign and never exceeds the line.
        CheckConstraint(
            "abs(not_stock_amount) <= abs(amount_ex_tax) AND not_stock_amount * amount_ex_tax >= 0",
            name="ck_purchase_lines_not_stock_within_amount",
        ),
        Index("ix_purchase_lines_document", "org_id", "document_id"),
        Index("ix_purchase_lines_org_treatment_state", "org_id", "treatment", "state"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), nullable=False)
    # Xero's LineItemID when it sends one, else "pos:<n>:<fingerprint>" (see purchase_sources.line_key).
    line_key = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    item_code = Column(String(100), nullable=True)
    quantity = Column(Numeric(18, 4), nullable=True)
    unit_amount = Column(Numeric(18, 6), nullable=True)
    account_code = Column(String(50), nullable=True)
    account_name = Column(String(255), nullable=True)
    amount_ex_tax = Column(Numeric(18, 4), nullable=False)
    tax_amount = Column(Numeric(18, 4), nullable=False, default=0, server_default="0")
    treatment = Column(String(20), nullable=False)
    # No foreign key yet: purchase_rules arrives with 8.1c, which adds it.
    treatment_rule_id = Column(UUID(as_uuid=True), nullable=True)
    treatment_override = Column(Boolean, nullable=False, default=False, server_default=sa.false())
    state = Column(String(20), nullable=False, default="open", server_default="open")
    not_stock_amount = Column(Numeric(18, 4), nullable=False, default=0, server_default="0")
    review_reason = Column(String(20), nullable=True)
    superseded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
