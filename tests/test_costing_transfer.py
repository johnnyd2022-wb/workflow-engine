"""Live-cogs 8.1a AC32: a site transfer's destination lot carries the source lot's cost."""

from uuid import uuid4

from app.core.db.models.inventory_item import InventoryItem
from app.core.security.tenant_scope import unscoped
from app.features.site_transfers import service
from tests.costing_helpers import D, flows, lot_cost, price
from tests.test_site_operations import released  # noqa: F401
from tests.test_site_transfers import permit, start, transfers  # noqa: F401
from tests.test_sites import flask_app, world  # noqa: F401


def test_ac32_transfer_destination_reports_source_unit_cost(transfers, db):  # noqa: F811
    org, *_rest = transfers
    stock_id, actor_id = transfers[6], transfers[7]
    with unscoped():
        price(db, org.id, stock_id, 200, 20)  # $10 a bottle, whole-lot price over its created flow
    transfer = start(transfers)
    with unscoped():
        service.receive(db, org.id, actor_id, transfer["id"], str(uuid4()), {"quantity": "4"}, permit)
        db.commit()
        fragment = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org.id, InventoryItem.transfer_receipt_id.is_not(None))
            .one()
        )
        (row,) = flows(db, org.id, fragment.id)
        assert row.kind == "transfer_in" and D(str(row.quantity)) == D("4")
        cost = lot_cost(db, org.id, fragment.id)
        assert (D(cost["unit_cost"]), cost["status"], cost["source"]) == (D("10"), "actual", "transfer")
        assert cost["editable"] is False
        from app.features.costing.service import CostingError

        try:
            price(db, org.id, fragment.id, 1, 1)
            raise AssertionError("a transfer destination must not take a typed price")
        except CostingError:
            db.rollback()

        # The backfill reconstructs it as transfer_in too, with the live key.
        from app.features.costing.backfill import backfill_flows
        from app.features.costing.models import CostFlow

        db.query(CostFlow).filter(CostFlow.org_id == org.id, CostFlow.inventory_item_id == fragment.id).delete()
        db.commit()
        backfill_flows(db, org.id)
        db.commit()
        (rebuilt,) = flows(db, org.id, fragment.id)
        assert (rebuilt.kind, rebuilt.source_key, rebuilt.reconstructed) == (
            "transfer_in",
            f"create:{fragment.id}",
            True,
        )
        db.rollback()


def test_polish_transfer_provenance_names_the_site_it_came_from(transfers, db):  # noqa: F811
    from app.core.db.models.site import Site
    from app.features.costing.service import lot_provenance

    org, *_rest = transfers
    actor_id = transfers[7]
    transfer = start(transfers)
    with unscoped():
        service.receive(db, org.id, actor_id, transfer["id"], str(uuid4()), {"quantity": "4"}, permit)
        db.commit()
        fragment = (
            db.query(InventoryItem)
            .filter(InventoryItem.org_id == org.id, InventoryItem.transfer_receipt_id.is_not(None))
            .one()
        )
        source_site = db.query(Site).filter(Site.org_id == org.id, Site.id == transfer["source_site_id"]).one()
        provenance = lot_provenance(db, org.id, fragment)
    assert provenance["kind"] == "transfer" and provenance["site"] == source_site.name
