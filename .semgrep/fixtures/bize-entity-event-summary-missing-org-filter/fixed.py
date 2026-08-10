# Fixture: the code the rule bize-entity-event-summary-missing-org-filter must stay SILENT on.
from app.core.db.models.entity_event_summary import EntityEventSummary


def entity_summary_detail(db, eid, org_id):
    summary_row = (
        db.query(EntityEventSummary)
        .filter(EntityEventSummary.entity_id == eid, EntityEventSummary.org_id == org_id)
        .first()
    )
    return summary_row.summary if summary_row else {}
