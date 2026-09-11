"""Durable, organisation-scoped custom lanes for the Core and CRM task boards."""

import uuid

from sqlalchemy import Column, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped


class TaskBoardLane(TenantScoped, Base):
    __tablename__ = "task_board_lanes"
    __table_args__ = (
        UniqueConstraint("org_id", "board", "title", name="uq_task_board_lanes_org_board_title"),
        Index("ix_task_board_lanes_org_board_position", "org_id", "board", "position"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    board = Column(String(20), nullable=False)  # core | crm
    title = Column(String(80), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
