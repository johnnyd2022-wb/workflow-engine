"""Excise duty rates and lodged periods (plan 2.1)."""

import uuid

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    Column,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db.models.models import Base
from app.core.utils.time import utc_now


class ExciseRate(Base):
    """Duty per litre of alcohol for one Customs tariff item, from a date (rates change 1 July)."""

    __tablename__ = "excise_rates"
    __table_args__ = (
        UniqueConstraint("org_id", "tariff_item", "effective_from", name="uq_excise_rates_org_item_from"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    tariff_item = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    rate_per_lal = Column(Numeric(12, 4), nullable=False)
    effective_from = Column(Date, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)


class ExciseLodgement(Base):
    """A period confirmed as lodged with Customs; its figures are locked in ``snapshot``."""

    __tablename__ = "excise_lodgements"
    __table_args__ = (
        # One entry per CCA licence per period; a single-site business has no licence here
        # and one entry per period (NULLS NOT DISTINCT).
        UniqueConstraint(
            "org_id",
            "licence_id",
            "period_start",
            name="uq_excise_lodgements_org_licence_period",
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(
            ["org_id", "licence_id"],
            ["customs_licences.org_id", "customs_licences.id"],
            name="fk_excise_lodgements_org_licence",
            ondelete="RESTRICT",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    # The CCA licence this entry was lodged for (GL-P07 A5); None for a single-site business.
    licence_id = Column(UUID(as_uuid=True), nullable=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    lodged_on = Column(Date, nullable=False)
    entry_reference = Column(String(100), nullable=True)
    nil_return = Column(Boolean, nullable=False, default=False, server_default="false")
    snapshot = Column(JSONB, nullable=False)
    lodged_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
