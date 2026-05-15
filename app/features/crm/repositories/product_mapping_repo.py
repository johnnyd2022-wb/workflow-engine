"""Repository for ProductMapping records."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.features.crm.models.product_mapping import ProductMapping


class ProductMappingRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        org_id: UUID,
        biz_e_source_output_id: UUID | None,
        biz_e_product_name: str,
        xero_description_pattern: str,
        match_type: str = "exact",
        notes: str | None = None,
        created_by_user_id: UUID | None = None,
    ) -> ProductMapping:
        mapping = ProductMapping(
            org_id=org_id,
            biz_e_source_output_id=biz_e_source_output_id,
            biz_e_product_name=biz_e_product_name,
            xero_description_pattern=xero_description_pattern,
            match_type=match_type,
            notes=notes,
            created_by_user_id=created_by_user_id,
        )
        self.db.add(mapping)
        return mapping

    def get_by_id(self, mapping_id: UUID, org_id: UUID) -> ProductMapping | None:
        return (
            self.db.query(ProductMapping)
            .filter(
                ProductMapping.id == mapping_id,
                ProductMapping.org_id == org_id,
            )
            .first()
        )

    def list_for_org(self, org_id: UUID, active_only: bool = True) -> list[ProductMapping]:
        q = self.db.query(ProductMapping).filter(ProductMapping.org_id == org_id)
        if active_only:
            q = q.filter(ProductMapping.is_active == True)  # noqa: E712
        return q.order_by(ProductMapping.biz_e_product_name.asc()).all()

    def list_for_product(self, org_id: UUID, biz_e_product_name: str) -> list[ProductMapping]:
        return (
            self.db.query(ProductMapping)
            .filter(
                ProductMapping.org_id == org_id,
                ProductMapping.biz_e_product_name == biz_e_product_name,
                ProductMapping.is_active == True,  # noqa: E712
            )
            .all()
        )

    def update(self, mapping: ProductMapping, **fields) -> ProductMapping:
        for k, v in fields.items():
            setattr(mapping, k, v)
        return mapping

    def delete(self, mapping: ProductMapping) -> None:
        self.db.delete(mapping)
