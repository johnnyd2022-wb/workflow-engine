"""GL-P02: a quality hold stops a lot being used until an authorised person releases it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.lot_hold import LotHold
from app.core.db.models.user import UserRole
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.core.security.auth_service import AuthService
from app.core.services import lot_holds
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export
from tests.test_go_live import _cleanup


def _lot(db, org_id, name, quantity="10", kind=InventoryType.RAW_MATERIAL, age_days=0):
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_CREATE):
        item = InventoryItem(
            org_id=org_id,
            name=name,
            quantity=Decimal(quantity),
            unit="each" if kind == InventoryType.FINAL_PRODUCT else "kg",
            inventory_type=kind.value,
            purchase_date=(datetime.now(UTC) - timedelta(days=age_days)).date(),
        )
        db.add(item)
        db.commit()
    return item


def _client(flask_app, org_id, db, role):  # noqa: F811
    email = f"hold-{uuid4().hex[:8]}@example.test"
    UserRepository(db).create_user(
        org_id=org_id,
        email=email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        role=role,
        is_active=True,
    )
    db.commit()
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200
    return client


def _drop_holds(db, *org_ids):
    db.rollback()
    db.query(LotHold).filter(LotHold.org_id.in_(org_ids)).update({LotHold.source_hold_id: None})
    db.query(LotHold).filter(LotHold.org_id.in_(org_ids)).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def org(db, flask_app):  # noqa: F811
    org, admin = _admin_client(db, flask_app)
    yield org, admin
    _drop_holds(db, org.id)
    _cleanup(db, org.id)


def _hold(db, org_id, item, reason="Cloudy after bottling"):
    holds = lot_holds.place_hold(db, org_id, item.id, reason, None)
    db.commit()
    return holds[0]


def _use(db, item, reason, new_quantity="4"):
    with allow_inventory_quantity_write(reason):
        item.quantity = Decimal(new_quantity)
        db.flush()


# --- enforcement at the flush -----------------------------------------------------------------


# The enum members the app passes, and their plain values: both must be refused.
@pytest.mark.parametrize("reason", [*lot_holds._USE, *(r.value for r in lot_holds._USE)], ids=str)
def test_every_use_of_a_held_lot_is_refused(db, org, reason):
    org_obj, _ = org
    item = _lot(db, org_obj.id, "Juniper")
    _hold(db, org_obj.id, item)
    with pytest.raises(lot_holds.LotOnHoldError, match="Juniper is on quality hold \\(Cloudy after bottling\\)"):
        _use(db, item, reason)
    db.rollback()
    db.refresh(item)
    assert item.quantity == Decimal("10")


@pytest.mark.parametrize(
    "reason",
    [
        InventoryQuantityWriteReason.WASTAGE_RECORD,  # disposing of a failed lot
        InventoryQuantityWriteReason.MANUAL_API_UPDATE,  # a count correction
        InventoryQuantityWriteReason.REPOSITORY_UPDATE,
        InventoryQuantityWriteReason.SALES_FIFO_REVERSAL,
    ],
)
def test_counting_and_disposing_of_a_held_lot_still_work(db, org, reason):
    org_obj, _ = org
    item = _lot(db, org_obj.id, "Juniper")
    _hold(db, org_obj.id, item)
    _use(db, item, reason)
    db.commit()
    assert item.quantity == Decimal("4")


def test_adding_to_a_held_lot_is_not_a_use(db, org):
    org_obj, _ = org
    item = _lot(db, org_obj.id, "Juniper")
    _hold(db, org_obj.id, item)
    _use(db, item, InventoryQuantityWriteReason.EXECUTION_STEP_INVENTORY, new_quantity="12")
    db.commit()


def test_a_released_lot_can_be_used_again(db, org):
    org_obj, _ = org
    item = _lot(db, org_obj.id, "Juniper")
    hold = _hold(db, org_obj.id, item)
    lot_holds.release_hold(db, org_obj.id, hold.id, "Retested: passed", None)
    db.commit()
    _use(db, item, InventoryQuantityWriteReason.EXECUTION_STEP_INVENTORY)
    db.commit()
    assert item.quantity == Decimal("4")


def test_a_hold_in_another_org_never_blocks_this_one(db, org, flask_app):  # noqa: F811
    org_obj, _ = org
    other, _client_b = _admin_client(db, flask_app)
    try:
        mine = _lot(db, org_obj.id, "Juniper")
        theirs = _lot(db, other.id, "Juniper")
        _hold(db, other.id, theirs)
        _use(db, mine, InventoryQuantityWriteReason.EXECUTION_STEP_INVENTORY)
        db.commit()
    finally:
        _drop_holds(db, other.id)
        _cleanup(db, other.id)


# --- sales skip held lots ----------------------------------------------------------------------


def test_a_sale_skips_the_held_lot_and_drains_the_next(db, org):
    org_obj, _ = org
    name = f"Navy Gin {uuid4().hex[:6]}"
    older = _lot(db, org_obj.id, name, "6", InventoryType.FINAL_PRODUCT, age_days=30)
    newer = _lot(db, org_obj.id, name, "6", InventoryType.FINAL_PRODUCT, age_days=1)
    _hold(db, org_obj.id, older)
    InventoryRepository(db).consume_final_product_fifo(org_obj.id, name, "4", commit=True)
    db.refresh(older)
    db.refresh(newer)
    assert (older.quantity, newer.quantity) == (Decimal("6"), Decimal("2"))


def test_a_sale_only_held_stock_could_fill_is_refused_not_taken(db, org):
    org_obj, _ = org
    name = f"Navy Gin {uuid4().hex[:6]}"
    only = _lot(db, org_obj.id, name, "6", InventoryType.FINAL_PRODUCT)
    _hold(db, org_obj.id, only)
    with pytest.raises(ValueError):
        InventoryRepository(db).consume_final_product_fifo(org_obj.id, name, "4", commit=True)
    db.rollback()
    db.refresh(only)
    assert only.quantity == Decimal("6")


# --- the planner ------------------------------------------------------------------------------


def test_the_planner_counts_a_held_lot_as_unusable(db, org):
    from app.features.planning import material_adapter

    org_obj, _ = org
    item = _lot(db, org_obj.id, "Juniper")
    _hold(db, org_obj.id, item)
    observations, _pool = material_adapter._observe(db, org_obj.id, [item.id], datetime.now(UTC).date())
    reasons = " ".join(str(v) for v in observations.values())
    assert "Lot is on quality hold: Cloudy after bottling" in reasons


# --- placing and releasing ----------------------------------------------------------------------


def test_a_hold_needs_a_reason_and_one_open_hold_per_lot(db, org):
    org_obj, _ = org
    item = _lot(db, org_obj.id, "Juniper")
    with pytest.raises(lot_holds.LotHoldError, match="Say why"):
        lot_holds.place_hold(db, org_obj.id, item.id, "   ", None)
    _hold(db, org_obj.id, item)
    with pytest.raises(lot_holds.LotHoldError, match="already on hold"):
        lot_holds.place_hold(db, org_obj.id, item.id, "again", None)


def test_release_needs_a_note_and_keeps_the_history(db, org):
    org_obj, _ = org
    item = _lot(db, org_obj.id, "Juniper")
    hold = _hold(db, org_obj.id, item)
    with pytest.raises(lot_holds.LotHoldError, match="Say why the lot can be released"):
        lot_holds.release_hold(db, org_obj.id, hold.id, "", None)
    lot_holds.release_hold(db, org_obj.id, hold.id, "Re-filtered and retested", None)
    db.commit()
    with pytest.raises(lot_holds.LotHoldError, match="already released"):
        lot_holds.release_hold(db, org_obj.id, hold.id, "again", None)
    second = _hold(db, org_obj.id, item, "Label misprint")
    past = lot_holds.history(db, org_obj.id, item.id)
    assert [(h.reason, h.release_note) for h in past] == [
        ("Label misprint", None),
        ("Cloudy after bottling", "Re-filtered and retested"),
    ]
    assert second.released_at is None
    kinds = [
        e.event_type
        for e in db.query(EntityEvent).filter(EntityEvent.org_id == org_obj.id, EntityEvent.entity_id == item.id)
    ]
    assert kinds.count("inventory_item.hold_placed") == 2
    assert kinds.count("inventory_item.hold_released") == 1


def test_only_lots_made_from_this_one_can_be_held_with_it(db, org, monkeypatch):
    org_obj, _ = org
    parent = _lot(db, org_obj.id, "Juniper")
    child = _lot(db, org_obj.id, "Gin batch 12", kind=InventoryType.FINAL_PRODUCT)
    stranger = _lot(db, org_obj.id, "Coriander")
    monkeypatch.setattr(lot_holds, "made_from", lambda *_a: [{"id": str(child.id)}])
    with pytest.raises(lot_holds.LotHoldError, match="Only lots made from this one"):
        lot_holds.place_hold(db, org_obj.id, parent.id, "Contaminated", None, [stranger.id])
    db.rollback()
    holds = lot_holds.place_hold(db, org_obj.id, parent.id, "Contaminated", None, [child.id])
    db.commit()
    assert [h.inventory_item_id for h in holds] == [parent.id, child.id]
    assert holds[1].source_hold_id == holds[0].id
    assert set(lot_holds.open_holds(db, org_obj.id)) == {parent.id, child.id}


# --- routes and permissions ---------------------------------------------------------------------


def test_staff_hold_but_only_an_admin_releases(db, org, flask_app):  # noqa: F811
    org_obj, admin = org
    staff = _client(flask_app, org_obj.id, db, UserRole.MEMBER)
    item = _lot(db, org_obj.id, "Juniper")

    placed = staff.post(f"/api/core/inventory/{item.id}/holds", json={"reason": "Smells off"})
    assert placed.status_code == 201, placed.get_json()
    hold_id = placed.get_json()["holds"][0]["id"]
    assert staff.post(f"/api/core/inventory/{item.id}/holds", json={"reason": "x"}).status_code == 400

    view = staff.get(f"/api/core/inventory/{item.id}/holds").get_json()
    assert view["open"]["reason"] == "Smells off"
    assert [h["id"] for h in staff.get("/api/core/holds").get_json()["holds"]] == [hold_id]

    assert staff.post(f"/api/core/holds/{hold_id}/release", json={"note": "fine"}).status_code == 403
    released = admin.post(f"/api/core/holds/{hold_id}/release", json={"note": "Retested: passed"})
    assert released.status_code == 200
    assert released.get_json()["hold"]["open"] is False
    assert admin.get("/api/core/holds").get_json()["holds"] == []


def test_another_org_cannot_see_hold_or_release(db, org, flask_app):  # noqa: F811
    org_obj, admin = org
    other, outsider = _admin_client(db, flask_app)
    try:
        item = _lot(db, org_obj.id, "Juniper")
        hold_id = admin.post(f"/api/core/inventory/{item.id}/holds", json={"reason": "Cloudy"}).get_json()["holds"][0][
            "id"
        ]
        assert outsider.get(f"/api/core/inventory/{item.id}/holds").status_code == 404
        assert outsider.post(f"/api/core/inventory/{item.id}/holds", json={"reason": "x"}).status_code == 404
        assert outsider.post(f"/api/core/holds/{hold_id}/release", json={"note": "x"}).status_code == 404
        theirs = _lot(db, other.id, "Juniper")
        _hold(db, other.id, theirs)
        assert [h["inventory_item_id"] for h in outsider.get("/api/core/holds").get_json()["holds"]] == [str(theirs.id)]
        assert [h["inventory_item_id"] for h in admin.get("/api/core/holds").get_json()["holds"]] == [str(item.id)]
        assert lot_holds.open_holds(db, org_obj.id).keys() == {item.id}
        assert lot_holds.open_holds(db, other.id).keys() == {theirs.id}
    finally:
        _drop_holds(db, other.id)
        _cleanup(db, other.id)


def test_bad_input_is_a_plain_400(db, org):
    org_obj, admin = org
    item = _lot(db, org_obj.id, "Juniper")
    assert admin.post(f"/api/core/inventory/{item.id}/holds", json={"reason": ""}).status_code == 400
    assert admin.post(f"/api/core/inventory/{item.id}/holds", json={"reason": "x" * 501}).status_code == 400
    bad = admin.post(f"/api/core/inventory/{item.id}/holds", json={"reason": "x", "also_hold": ["nope"]})
    assert bad.status_code == 400
    assert admin.post("/api/core/inventory/not-a-uuid/holds", json={"reason": "x"}).status_code == 404
    assert admin.post(f"/api/core/holds/{uuid4()}/release", json={"note": "x"}).status_code == 404


def test_a_production_step_using_a_held_lot_is_refused_with_the_reason(db, org):
    """The real path: completing a step that consumes the held lot answers 400 and takes nothing."""
    from app.core.db.repositories.execution_repo import ExecutionRepository
    from app.core.db.repositories.process_repo import ProcessRepository
    from tests.factories import ProcessFactory

    org_obj, admin = org
    item = _lot(db, org_obj.id, "Juniper")
    process = ProcessFactory(org_id=org_obj.id)
    ProcessRepository(db).add_step(
        process.id,
        org_obj.id,
        step_number=1,
        position=1000,
        name="Macerate",
        inputs=[{"name": "Juniper", "quantity": 2, "unit": "kg"}],
        outputs=[],
    )
    execution = ExecutionRepository(db).create_execution(org_obj.id, process.id)
    db.commit()
    step = execution.execution_steps[0]
    _hold(db, org_obj.id, item)

    resp = admin.post(
        f"/api/core/executions/{execution.id}/steps/{step.id}/complete",
        json={
            "actual_inputs": [{"inventory_item_id": str(item.id), "name": "Juniper", "quantity": 2, "unit": "kg"}],
            "actual_outputs": [],
        },
    )
    assert resp.status_code == 409, resp.data
    assert "quality hold" in resp.get_data(as_text=True)
    db.expire_all()
    assert db.get(InventoryItem, item.id).quantity == Decimal("10")


def test_any_route_that_hits_a_held_lot_answers_409(flask_app):  # noqa: F811
    """The app-wide handler: a route with no catch of its own still says which lot and why."""

    def boom():
        raise lot_holds.LotOnHoldError("Juniper", "Cloudy")

    flask_app.add_url_rule("/__test/held", "test_held_boom", boom)
    resp = flask_app.test_client().get("/__test/held", base_url="https://localhost")
    assert resp.status_code == 409
    assert resp.get_json() == {
        "error": "Juniper is on quality hold (Cloudy). Release the hold before using it.",
        "code": "lot_on_hold",
    }


def test_a_lot_with_hold_history_cannot_be_deleted(db, org):
    """A hold is a quality record: deleting the lot must not erase it (route says so; FK backstops)."""
    from sqlalchemy.exc import IntegrityError

    org_obj, admin = org
    item = _lot(db, org_obj.id, "Juniper")
    hold = _hold(db, org_obj.id, item)
    lot_holds.release_hold(db, org_obj.id, hold.id, "Retested: passed", None)
    db.commit()

    resp = admin.delete(f"/api/core/inventory/{item.id}")
    assert resp.status_code == 409
    assert resp.get_json()["code"] == "lot_has_hold_history"
    db.expire_all()
    assert db.get(InventoryItem, item.id) is not None
    assert [h.id for h in lot_holds.history(db, org_obj.id, item.id)] == [hold.id]

    # Any other path that tries is stopped by the foreign key, not allowed to cascade.
    with pytest.raises(IntegrityError):
        InventoryRepository(db).delete_inventory_item(item.id, org_obj.id)
    db.rollback()
    assert db.query(LotHold).filter(LotHold.id == hold.id).count() == 1


def test_a_lot_never_held_still_deletes(db, org):
    org_obj, admin = org
    item = _lot(db, org_obj.id, "Coriander")
    assert admin.delete(f"/api/core/inventory/{item.id}").status_code == 200
