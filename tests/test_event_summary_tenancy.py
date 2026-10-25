"""GL-S02: the event-summary read model's raw SQL names its org.

entity_event_summaries is keyed by entity_id alone, and the summary code reads and upserts it
with raw SQL, which the ORM's tenant filter never sees. A neighbour's event that carries the
same entity_id must neither read nor overwrite another org's summary.
"""

from uuid import uuid4

from app.core.backend.event_writer import EventWriter
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.entity_event_summary import EntityEventSummary
from app.core.db.models.organisation import Organisation
from tests.factories import OrganisationFactory


def _summary(db, entity_id):
    db.expire_all()
    return db.query(EntityEventSummary).filter(EntityEventSummary.entity_id == entity_id).one()


def test_a_neighbours_event_cannot_overwrite_a_summary(db):
    org_a, org_b = OrganisationFactory().id, OrganisationFactory().id
    db.commit()
    entity_id = uuid4()
    EventWriter(db, org_a).emit(
        "inventory_item.created", "inventory_item", entity_id, {"name": "Gin", "quantity": "10"}
    )
    db.commit()
    before = _summary(db, entity_id)
    assert before.org_id == org_a
    kept = dict(before.summary)

    EventWriter(db, org_b).emit(
        "inventory_item.created", "inventory_item", entity_id, {"name": "Hostile", "add_method": "csv"}
    )
    db.commit()

    after = _summary(db, entity_id)
    assert after.org_id == org_a
    assert after.summary == kept

    db.query(EntityEventSummary).filter(EntityEventSummary.entity_id == entity_id).delete()
    db.query(EntityEvent).filter(EntityEvent.entity_id == entity_id).delete()
    db.query(Organisation).filter(Organisation.id.in_([org_a, org_b])).delete(synchronize_session=False)
    db.commit()
