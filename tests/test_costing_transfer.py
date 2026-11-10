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
        price(db, org.id, stock_id, 200, 20)  # $10 a bottle, whole-lot (factory lot: no flows)
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
        db.rollback()
