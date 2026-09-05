from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.features.operational_cases.models.operational_case_link import CaseLinkRelation, OperationalCaseLink


class OperationalCaseLinkRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(
        self,
        org_id: UUID,
        case_id: UUID,
        relation: str,
        entity_type: str,
        entity_id: UUID,
        created_by: UUID,
    ) -> OperationalCaseLink:
        link = OperationalCaseLink(
            org_id=org_id,
            case_id=case_id,
            relation=relation,
            entity_type=entity_type,
            entity_id=entity_id,
            created_by=created_by,
        )
        self.db.add(link)
        self.db.flush()
        return link

    def list_for_case(self, org_id: UUID, case_id: UUID, relation: str | None = None) -> list[OperationalCaseLink]:
        query = self.db.query(OperationalCaseLink).filter(
            OperationalCaseLink.org_id == org_id, OperationalCaseLink.case_id == case_id
        )
        if relation:
            query = query.filter(OperationalCaseLink.relation == relation)
        return query.order_by(OperationalCaseLink.created_at.asc()).all()

    def count_evidence(self, org_id: UUID, case_id: UUID) -> int:
        return (
            self.db.query(OperationalCaseLink)
            .filter(
                OperationalCaseLink.org_id == org_id,
                OperationalCaseLink.case_id == case_id,
                OperationalCaseLink.relation == CaseLinkRelation.EVIDENCE,
            )
            .count()
        )
