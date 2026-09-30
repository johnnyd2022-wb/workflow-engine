"""Core task records, available to every organisation in every environment."""

import uuid

from sqlalchemy import TIMESTAMP, Column, Date, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

import app.core.db.models.task_board_lane  # noqa: F401 -- registers the "task_board_lanes" table this model points at
from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.utils.time import utc_now


class CoreTask(TenantScoped, Base):
    """An operational task created from the always-on Core workspace.

    CRM tasks keep their customer relationship and remain in ``crm_tasks``.  This model
    deliberately has no product-module dependency so Core Tasks stays available when
    CRM is disabled.
    """

    __tablename__ = "core_tasks"
    __table_args__ = (
        Index("ix_core_tasks_org_due_status", "org_id", "due_date", "status"),
        Index("ix_core_tasks_org_assignee_status", "org_id", "assigned_to_user_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(50), nullable=False, default="pending")
    priority = Column(String(20), nullable=False, default="medium")
    assigned_to_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    board_lane_id = Column(UUID(as_uuid=True), ForeignKey("task_board_lanes.id", ondelete="SET NULL"), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
