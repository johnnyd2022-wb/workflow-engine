"""Tenant-scoped product images and their live inventory lineage."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.process import Process
from app.core.db.models.product_image import ProductImage


class ProductImageRepository:
    def __init__(self, db: Session):
        self.db = db

    def workflow_ids_with_image(self, org_id: UUID, process_ids: Collection[UUID]) -> set[UUID]:
        if not process_ids:
            return set()
        return set(
            self.db.scalars(
                select(ProductImage.process_id).where(
                    ProductImage.org_id == org_id, ProductImage.process_id.in_(process_ids)
                )
            )
        )

    def workflow_image(self, org_id: UUID, process_id: UUID) -> bytes | None:
        return self.db.scalar(
            select(ProductImage.content).where(ProductImage.org_id == org_id, ProductImage.process_id == process_id)
        )

    def lock_workflow(self, org_id: UUID, process_id: UUID) -> bool:
        return (
            self.db.scalar(
                select(Process.id).where(Process.org_id == org_id, Process.id == process_id).with_for_update()
            )
            is not None
        )

    def save(self, org_id: UUID, process_id: UUID, content: bytes) -> None:
        statement = insert(ProductImage).values(org_id=org_id, process_id=process_id, content=content)
        self.db.execute(
            statement.on_conflict_do_update(
                index_elements=[ProductImage.process_id],
                set_={"content": statement.excluded.content},
                where=ProductImage.org_id == org_id,
            )
        )

    def remove(self, org_id: UUID, process_id: UUID) -> None:
        self.db.query(ProductImage).filter(
            ProductImage.org_id == org_id, ProductImage.process_id == process_id
        ).delete()

    def inventory_image_ids(self, org_id: UUID, item_ids: Collection[UUID]) -> dict[UUID, UUID]:
        if not item_ids:
            return {}
        rows = self._finished_lots(org_id, InventoryItem.id, ProductImage.id).where(InventoryItem.id.in_(item_ids))
        return dict(self.db.execute(rows).tuples().all())

    def inventory_image(self, org_id: UUID, item_id: UUID) -> bytes | None:
        return self.db.scalar(self._finished_lots(org_id, ProductImage.content).where(InventoryItem.id == item_id))

    @staticmethod
    def _finished_lots(org_id: UUID, *columns):
        # Legacy lots can have batch lineage alone. If a step is specified, require
        # that exact step to be terminal and agree with any recorded batch lineage.
        return (
            select(*columns)
            .select_from(InventoryItem)
            .outerjoin(
                ExecutionStep,
                and_(ExecutionStep.id == InventoryItem.source_execution_step_id, ExecutionStep.org_id == org_id),
            )
            .join(
                Execution,
                and_(
                    Execution.id == func.coalesce(InventoryItem.source_execution_id, ExecutionStep.execution_id),
                    Execution.org_id == org_id,
                ),
            )
            .join(ProductImage, and_(ProductImage.process_id == Execution.process_id, ProductImage.org_id == org_id))
            .where(
                InventoryItem.org_id == org_id,
                InventoryItem.inventory_type == InventoryType.FINAL_PRODUCT.value,
                or_(
                    InventoryItem.source_execution_step_id.is_(None),
                    and_(ExecutionStep.is_terminal_step.is_(True), ExecutionStep.execution_id == Execution.id),
                ),
            )
        )
