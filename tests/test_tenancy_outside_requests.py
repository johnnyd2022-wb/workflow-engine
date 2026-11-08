"""GL-S02: work that runs outside a request still names its org.

Raw SQL and code run inside unscoped() never see the ORM's tenant filter. These pin the two
such paths that touch every org: the event-summary read model (raw SQL keyed by entity_id
alone) and the nightly warm-system-findings job (every check run with the filter off).
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


def test_the_nightly_warm_job_keeps_each_orgs_findings_to_itself(db):
    """warm-system-findings runs every check inside unscoped(), where the ORM's tenant
    filter is off, so each check has to name its org. A neighbour's expired stock must
    not appear in this org's cached findings."""
    import json
    from datetime import date, timedelta

    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.system_findings_cache import SystemFindingsCache
    from app.core.security.tenant_scope import unscoped
    from app.features.compliance_checks import system_findings_cache as sfc
    from tests.factories import InventoryItemFactory

    mine, neighbour = OrganisationFactory().id, OrganisationFactory().id
    db.commit()
    marker = f"Neighbour-only juniper {uuid4().hex[:6]}"
    InventoryItemFactory(org_id=neighbour, name=marker, expiry_date=date.today() - timedelta(days=30))
    InventoryItemFactory(org_id=mine, name="My own gin", expiry_date=date.today() - timedelta(days=30))
    db.commit()
    try:
        with unscoped():
            assert sfc.prewarm(mine, db) is True
            db.commit()
        db.expire_all()
        cached = db.query(SystemFindingsCache).filter(SystemFindingsCache.org_id == mine).one()
        text = json.dumps(cached.payload)
        assert "My own gin" in text, "the check should see this org's own expired stock"
        assert marker not in text
    finally:
        db.query(SystemFindingsCache).filter(SystemFindingsCache.org_id.in_([mine, neighbour])).delete(
            synchronize_session=False
        )
        db.query(InventoryItem).filter(InventoryItem.org_id.in_([mine, neighbour])).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id.in_([mine, neighbour])).delete(synchronize_session=False)
        db.commit()
