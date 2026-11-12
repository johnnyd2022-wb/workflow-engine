"""Live-cogs 8.1a AC32: a site transfer's destination lot carries the source lot's cost."""

from uuid import uuid4

import pytest

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


@pytest.mark.parametrize("primed", [False, True], ids=["lazy_walk", "bulk_prime"])
def test_ac42_a_forged_transfer_receipt_never_carries_another_orgs_cost(transfers, db, primed):  # noqa: F811
    """`inventory_items.transfer_receipt_id` is a composite key too (`fk_inventory_transfer_receipt`),
    so the forgery below cannot be stored in a normal session. With FK enforcement switched
    off for one transaction it can, and the walk's own `org_id` filters must still treat it as
    a transfer with no source rather than inherit the other org's price, whether the lot is costed
    by the lazy walk or by the bulk loader (`prime`) that Margins and Readiness use.

    This is an outcome-level guard: the receipt, transfer and source-lot lookups are three
    independent filters in series, so removing any one of them stays green and only removing all
    three turns it red. The first two cannot be isolated (a forged receipt is blocked by whichever
    filter remains); the source-lot filter is also pinned alone by
    `test_ac42_estimates_never_use_another_orgs_lots`."""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.core.db.models.site_transfer import SiteStockReceipt
    from app.features.costing.models import CostFlow
    from tests.costing_helpers import bypass_foreign_keys, lot, new_org, purge

    org, stock_id, actor_id = transfers[0], transfers[6], transfers[7]
    with unscoped():
        price(db, org.id, stock_id, 200, 20)  # $10 a bottle, over the source lot's created flow
    transfer = start(transfers)
    other = new_org(db)
    try:
        with unscoped():
            service.receive(db, org.id, actor_id, transfer["id"], str(uuid4()), {"quantity": "4"}, permit)
            db.commit()
            receipt = db.query(SiteStockReceipt).filter(SiteStockReceipt.org_id == org.id).one()
            theirs = (
                db.query(InventoryItem)
                .filter(InventoryItem.org_id == org.id, InventoryItem.transfer_receipt_id == receipt.id)
                .one()
            )
            theirs_cost = lot_cost(db, org.id, theirs.id)
            # control: the real destination does inherit the source's price
            assert (D(theirs_cost["unit_cost"]), theirs_cost["source"]) == (D("10"), "transfer")

            mine = lot(db, other.id, "House Gin", 4, "bottles", inventory_type="final_product")
            db.commit()
            forge = text("UPDATE inventory_items SET transfer_receipt_id = :r WHERE org_id = :o AND id = :i")
            args = {"r": receipt.id, "o": other.id, "i": mine.id}

            # with enforcement on, the database refuses (past the title trigger, which migration mode skips)
            db.execute(text("SELECT set_config('app.migration_mode','1',true)"))
            with pytest.raises(IntegrityError, match="fk_inventory_transfer_receipt"):
                db.execute(forge, args)
            db.rollback()

            # with it off (this also switches off the immutability trigger, so no migration mode is needed),
            # make the other org's lot look like a transfer destination pointing at that receipt
            bypass_foreign_keys(db)
            db.query(CostFlow).filter(CostFlow.org_id == other.id, CostFlow.inventory_item_id == mine.id).delete()
            db.add(
                CostFlow(
                    org_id=other.id,
                    inventory_item_id=mine.id,
                    direction="in",
                    kind="transfer_in",
                    quantity=D("4"),
                    source_key=f"forged:{mine.id}",
                    write_reason="test",
                    reconstructed=False,
                )
            )
            db.execute(forge, args)
            db.commit()
            db.refresh(mine)
            assert mine.transfer_receipt_id == receipt.id, "the forgery must actually be in place"

            cost = lot_cost(db, other.id, mine.id, primed=primed)
            assert cost["status"] == "unknown" and cost["unit_cost"] is None and cost["known_unit_cost"] is None
            assert cost["source"] != "transfer"
            assert "transfer_source_missing" in cost["warnings"]
            # and the owner's own answer did not move
            assert D(lot_cost(db, org.id, theirs.id)["unit_cost"]) == D("10")
    finally:
        purge(db, other)


def test_prime_keeps_transfer_source_queries_flat_as_receipt_lots_grow(transfers, db):  # noqa: F811
    from sqlalchemy import event

    from app.core.db.models.site_transfer import SiteStockReceipt
    from app.features.costing.engine import CostEngine

    org, stock_id, actor_id = transfers[0], transfers[6], transfers[7]
    destination_ids = []

    def add_receipts(count):
        for _ in range(count):
            transfer = start(transfers, quantity="1")
            with unscoped():
                service.receive(db, org.id, actor_id, transfer["id"], str(uuid4()), {"quantity": "1"}, permit)
                db.commit()
                receipt = (
                    db.query(SiteStockReceipt)
                    .filter(SiteStockReceipt.org_id == org.id)
                    .order_by(SiteStockReceipt.created_at.desc())
                    .first()
                )
                destination = (
                    db.query(InventoryItem)
                    .filter(InventoryItem.org_id == org.id, InventoryItem.transfer_receipt_id == receipt.id)
                    .one()
                )
                destination_ids.append(destination.id)

    def count_source_lookups():
        statements = []
        bind = db.get_bind()
        engine = getattr(bind, "engine", bind)

        def listener(*_args):
            statements.append(1)

        event.listen(engine, "before_cursor_execute", listener)
        try:
            costs = CostEngine(db, org.id)
            costs.prime([stock_id, *destination_ids])
            for item_id in destination_ids:
                costs._transfer_source(db.get(InventoryItem, item_id))
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(statements)

    with unscoped():
        add_receipts(2)
        baseline = count_source_lookups()
        add_receipts(6)
        scaled = count_source_lookups()

    assert scaled <= baseline + 4, f"query count grew from {baseline} to {scaled}"
