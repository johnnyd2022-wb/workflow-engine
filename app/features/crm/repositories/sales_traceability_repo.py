"""Repository for CRM sales traceability configuration."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.features.crm.models.sales_traceability_config import SalesTraceabilityConfig


class SalesTraceabilityConfigRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_for_org(self, org_id: UUID) -> SalesTraceabilityConfig | None:
        return self.db.query(SalesTraceabilityConfig).filter(SalesTraceabilityConfig.org_id == org_id).first()

    def upsert(
        self,
        org_id: UUID,
        *,
        matching_strategy: str,
        matching_key: str = "batch_id",
        manual_review_days: int = 7,
        strict_mapping: bool = True,
        task_done_archive_days: int = 7,
    ) -> SalesTraceabilityConfig:
        row = self.get_for_org(org_id)
        if row is None:
            row = SalesTraceabilityConfig(
                org_id=org_id,
                matching_strategy=matching_strategy,
                matching_key=matching_key,
                manual_review_days=manual_review_days,
                strict_mapping=strict_mapping,
                task_done_archive_days=task_done_archive_days,
            )
            self.db.add(row)
            return row
        row.matching_strategy = matching_strategy
        row.matching_key = matching_key
        row.manual_review_days = manual_review_days
        row.strict_mapping = strict_mapping
        row.task_done_archive_days = task_done_archive_days
        return row
