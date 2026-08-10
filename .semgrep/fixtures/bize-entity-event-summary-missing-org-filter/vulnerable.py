# Fixture: the code the rule bize-entity-event-summary-missing-org-filter must FIRE on.
from app.core.db.models.entity_event_summary import EntityEventSummary


def entity_summary_detail(db, eid):
    summary_row = db.query(EntityEventSummary).filter(EntityEventSummary.entity_id == eid).first()
    return summary_row.summary if summary_row else {}
