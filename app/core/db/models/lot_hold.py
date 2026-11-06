"""GL-P02: a quality hold on a lot of stock.

A hold stops a lot being used: consumed in production, matched to a sale, sent to a
tasting, dispatched to a contract customer or split off by a transfer
(``app/core/services/lot_holds.py`` enforces it at flush time). Counting it, moving it
whole and disposing of it stay allowed — that is what you do with a failed lot.

Rows are never deleted: a release closes the hold and keeps who, when and why, so the
lot's history reads "held 3 Nov (cloudy) — released 5 Nov (re-filtered, retested)".
"""

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class LotHold(TenantScoped, Base):
    __tablename__ = "lot_holds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "inventory_item_id"],
            ["inventory_items.org_id", "inventory_items.id"],
            name="fk_lot_hold_org_item",
            # A hold is a quality record: deleting the lot must not erase it.
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(trim(reason)) > 0", name="ck_lot_hold_reason"),
        CheckConstraint(
            "released_at IS NULL OR length(trim(coalesce(release_note, ''))) > 0", name="ck_lot_hold_release_note"
        ),
        # One open hold per lot; history is any number of released ones.
        Index(
            "uq_lot_hold_open",
            "org_id",
            "inventory_item_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inventory_item_id = Column(UUID(as_uuid=True), nullable=False)
    reason = Column(Text, nullable=False)
    # Set when the hold came from holding another lot and everything made from it.
    source_hold_id = Column(UUID(as_uuid=True), ForeignKey("lot_holds.id", ondelete="SET NULL"), nullable=True)
    placed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    placed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    released_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    released_at = Column(DateTime(timezone=True), nullable=True)
    release_note = Column(Text, nullable=True)
