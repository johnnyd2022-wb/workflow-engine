"""Per-organisation notification policy for Core Tasks."""

import uuid

from sqlalchemy import JSON, Boolean, Column, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db.models.models import Base
from app.core.db.models.tenant_mixin import TenantScoped


class CoreTaskConfig(TenantScoped, Base):
    __tablename__ = "core_task_configs"
    __table_args__ = (UniqueConstraint("org_id", name="uq_core_task_configs_org"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    due_notifications_enabled = Column(Boolean, nullable=False, default=True)
    notification_lead_value = Column(Integer, nullable=False, default=7)
    notification_lead_unit = Column(String(10), nullable=False, default="days")
    # Board preferences deliberately live with the task policy rather than in browser
    # storage so a board follows its organisation across devices and sessions.
    done_archive_value = Column(Integer, nullable=False, default=1)
    done_archive_unit = Column(String(10), nullable=False, default="weeks")
    lane_order = Column(JSON, nullable=False, default=list)
    hidden_default_lanes = Column(JSON, nullable=False, default=list)
