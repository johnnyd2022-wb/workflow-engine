"""Live-cogs 8.1a: costing API — permissions, feature gate, tenant isolation, validation.

Spec .agents/specs/live-cogs.md, "Users & permissions", "API", AC40-AC42, AC62. Written before
the implementation.
"""

from uuid import uuid4

import pytest

from app.core.db.models.user import UserRole
from app.core.security.access_policy import GRANTABLE, PERMISSIONS, ROLE_PERMISSIONS
from tests.costing_helpers import D, complete, flows, lot, new_org, price, purge, user_client, workflow
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

API = "/api/core/costing"


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org = new_org(db)
    admin = user_client(db, flask_app, org)
    item = lot(db, org.id, "Juniper", 2, "kg")
    execution, (step,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
    complete(admin, execution, step, [(item, 1, "kg")], [{"name": "Gin", "quantity": 9, "unit": "bottles"}])
    entry = price(db, org.id, item.id, 90, 2)
    yield {"org": org, "admin": admin, "item": item, "execution": execution, "entry": entry}
    purge(db, org)


def _reads(w):
    return [
        f"{API}/lots/{w['item'].id}/cost",
        f"{API}/executions/{w['execution'].id}/cost",
        f"{API}/settings",
    ]


def _writes(w):
    """(method, path, body) for every 8.1a write route."""
    return [  # delete first: a later PUT would deactivate the entry it names
        ("delete", f"{API}/lots/{w['item'].id}/cost/{w['entry'].id}", None),
        ("put", f"{API}/lots/{w['item'].id}/cost", {"kind": "manual", "amount": "100", "quantity": "2"}),
        ("put", f"{API}/settings", {"use_last_known_price": False}),
    ]


def _call(client, method, path, body=None):
    fn = getattr(client, method)
    return fn(path, json=body) if body is not None else fn(path)


# --- permissions --------------------------------------------------------------------------


def test_permissions_are_declared_with_the_spec_defaults():
    assert {"costs.view", "costs.manage"} <= set(PERMISSIONS)
    assert {"costs.view", "costs.manage"} <= GRANTABLE
    assert {"costs.view", "costs.manage"} <= ROLE_PERMISSIONS[UserRole.ADMIN]
    assert {"costs.view", "costs.manage"} <= ROLE_PERMISSIONS[UserRole.MEMBER]
    for role in (UserRole.PRODUCTION, UserRole.COMPLIANCE, UserRole.SALES, UserRole.AUDITOR):
        assert not {"costs.view", "costs.manage"} & ROLE_PERMISSIONS[role], role


def test_ac40_production_user_gets_403_everywhere(world, db, flask_app):  # noqa: F811
    client = user_client(db, flask_app, world["org"], role=UserRole.PRODUCTION)
    for path in _reads(world):
        assert client.get(path).status_code == 403, path
    for method, path, body in _writes(world):
        assert _call(client, method, path, body).status_code == 403, path


def test_ac40_view_only_custom_role(world, db, flask_app):  # noqa: F811
    client = user_client(db, flask_app, world["org"], permissions=["costs.view", "inventory.view"])
    for path in _reads(world):
        assert client.get(path).status_code == 200, path
    for method, path, body in _writes(world):
        assert _call(client, method, path, body).status_code == 403, path


def test_ac40_manage_without_inventory_adjust_can_price_lots(world, db, flask_app):  # noqa: F811
    """Entering a price changes no stock, so costs.manage alone is enough (spec matrix)."""
    client = user_client(db, flask_app, world["org"], permissions=["costs.manage"])
    response = client.put(
        f"{API}/lots/{world['item'].id}/cost", json={"kind": "manual", "amount": "80", "quantity": "2"}
    )
    assert response.status_code == 200, response.get_json()
    assert client.get(f"{API}/lots/{world['item'].id}/cost").status_code == 403, "manage is not view"
    reread = world["admin"].get(f"{API}/lots/{world['item'].id}/cost").get_json()
    assert reread["unit_cost"] == "40.000000"


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.MEMBER])
def test_ac40_admin_and_staff_can_do_everything(world, db, flask_app, role):  # noqa: F811
    client = world["admin"] if role == UserRole.ADMIN else user_client(db, flask_app, world["org"], role=role)
    for path in _reads(world):
        assert client.get(path).status_code == 200, path
    for method, path, body in _writes(world):
        assert _call(client, method, path, body).status_code in (200, 204), (method, path)


# --- feature gate -------------------------------------------------------------------------


def test_ac41_every_route_404s_without_the_feature(world, db):
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    FeatureSubscriptionRepository(db).revoke(world["org"].id, "costing")
    db.commit()
    for path in _reads(world):
        assert world["admin"].get(path).status_code == 404, path
    for method, path, body in _writes(world):
        assert _call(world["admin"], method, path, body).status_code == 404, path


def test_unauthenticated_is_401(world, flask_app):  # noqa: F811
    anon = flask_app.test_client()
    anon.environ_base["wsgi.url_scheme"] = "https"
    anon.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert anon.get(_reads(world)[0]).status_code == 401


# --- tenant isolation ---------------------------------------------------------------------


def test_ac42_other_orgs_ids_are_404_and_untouched(world, db, flask_app):  # noqa: F811
    other = new_org(db)
    try:
        intruder = user_client(db, flask_app, other)
        for path in _reads(world)[:2]:
            assert intruder.get(path).status_code == 404, path
        for method, path, body in _writes(world)[:2]:
            assert _call(intruder, method, path, body).status_code == 404, path
        # the victim's price is unchanged
        cost = world["admin"].get(f"{API}/lots/{world['item'].id}/cost").get_json()
        assert D(cost["unit_cost"]) == D("45")
    finally:
        purge(db, other)


def test_ac42_entry_of_another_lot_is_404(world, db):
    other_item = lot(db, world["org"].id, "Other", 1, "kg")
    response = world["admin"].delete(f"{API}/lots/{other_item.id}/cost/{world['entry'].id}")
    assert response.status_code == 404


def test_unknown_ids_are_404(world):
    for path in (f"{API}/lots/{uuid4()}/cost", f"{API}/executions/{uuid4()}/cost", f"{API}/lots/not-a-uuid/cost"):
        assert world["admin"].get(path).status_code == 404, path


# --- payloads and validation ----------------------------------------------------------------


def test_lot_cost_payload_shape(world):
    body = world["admin"].get(f"{API}/lots/{world['item'].id}/cost").get_json()
    for key in (
        "inventory_item_id",
        "unit",
        "unit_cost",
        "known_unit_cost",
        "status",
        "source",
        "estimate_from",
        "priced_quantity",
        "unpriced_quantity",
        "missing",
        "warnings",
        "entries",
        "editable",
    ):
        assert key in body, key
    assert body["unit_cost"] == "45.000000" and body["source"] == "manual" and body["editable"] is True
    assert body["known_unit_cost"] == "45.000000" and body["status"] == "actual"
    assert body["estimate_from"] is None and body["missing"] == [] and body["warnings"] == []
    (entry,) = body["entries"]
    assert entry["id"] == str(world["entry"].id) and entry["kind"] == "manual"
    assert entry["amount"] == "90.0000" and entry["quantity"] == "2.0000" and entry["cost_flow_id"] is None


def test_execution_cost_payload_shape(world):
    body = world["admin"].get(f"{API}/executions/{world['execution'].id}/cost").get_json()
    for key in (
        "execution_id",
        "status",
        "known_input_cost",
        "cost_so_far",
        "split_assumed",
        "missing",
        "inputs",
        "outputs",
    ):
        assert key in body, key
    assert body["cost_so_far"] == "0.0000" and body["cost_so_far_status"] == "actual"
    assert body["warnings"] == [] and body["missing"] == [] and body["split_assumed"] is False
    assert body["known_input_cost"] == "45.0000" and body["status"] == "actual"
    (out,) = body["outputs"]
    assert out["unit_cost"] == "5.000000" and out["known_amount"] == "45.0000"
    assert out["known_unit_cost"] == "5.000000" and out["weight"] == "1.000000"
    assert out["quantity"] == "9.0000" and out["unit"] == "bottles" and out["step_number"] == 1
    assert out["kind"] == "produced" and out["missing"] == [] and out["flow_id"]
    (inp,) = body["inputs"]
    assert inp["internal"] is False and inp["known_amount"] == "45.0000"


def test_put_free_and_manual(world):
    admin, item = world["admin"], world["item"]
    free = admin.put(f"{API}/lots/{item.id}/cost", json={"kind": "free"})
    assert free.status_code == 200, free.get_json()
    assert free.get_json()["unit_cost"] == "0.000000" and free.get_json()["source"] == "free"
    manual = admin.put(f"{API}/lots/{item.id}/cost", json={"kind": "manual", "amount": "50", "quantity": "2"})
    assert manual.get_json()["unit_cost"] == "25.000000"


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "manual", "amount": "-1", "quantity": "2"},
        {"kind": "manual", "amount": "10", "quantity": "0"},
        {"kind": "manual", "amount": "abc", "quantity": "2"},
        {"kind": "manual", "quantity": "2"},
        {"kind": "bogus", "amount": "1", "quantity": "1"},
        {"kind": "free", "amount": "5"},
        {"kind": "manual", "amount": "1", "quantity": "1", "cost_flow_id": str(uuid4())},
        {"kind": "manual", "amount": "NaN", "quantity": "1"},
        {"kind": "manual", "amount": "1e30", "quantity": "1"},
    ],
)
def test_put_rejects_bad_input(world, body):
    response = world["admin"].put(f"{API}/lots/{world['item'].id}/cost", json=body)
    assert response.status_code == 400, (body, response.get_json())
    assert D(world["admin"].get(f"{API}/lots/{world['item'].id}/cost").get_json()["unit_cost"]) == D("45")


def test_put_rejects_body_over_16_kib_without_writing(world, db):
    from app.features.costing.models import LotCostEntry

    before = {
        entry.id
        for entry in db.query(LotCostEntry)
        .filter(LotCostEntry.org_id == world["org"].id, LotCostEntry.inventory_item_id == world["item"].id)
        .all()
    }
    body = '{"kind":"manual","amount":"1","quantity":"1","note":"' + ("x" * (20 * 1024)) + '"}'
    response = world["admin"].put(f"{API}/lots/{world['item'].id}/cost", data=body, content_type="application/json")
    assert response.status_code == 413
    db.expire_all()
    after = {
        entry.id
        for entry in db.query(LotCostEntry)
        .filter(LotCostEntry.org_id == world["org"].id, LotCostEntry.inventory_item_id == world["item"].id)
        .all()
    }
    assert after == before


def test_cost_entry_creator_is_tenant_scoped_and_set_null_on_delete(world, db):
    from sqlalchemy.exc import IntegrityError

    from app.core.db.models.user import User, UserRole
    from app.core.db.repositories.user_repo import UserRepository
    from app.features.costing import service
    from app.features.costing.models import LotCostEntry

    org = world["org"]
    other = new_org(db)
    try:
        foreign_user = UserRepository(db).create_user(
            org_id=other.id,
            email=f"foreign-cost-creator-{uuid4()}@test.com",
            password_hash="unused",
            role=UserRole.MEMBER,
            is_active=True,
        )
        actor = UserRepository(db).create_user(
            org_id=org.id,
            email=f"cost-creator-{uuid4()}@test.com",
            password_hash="unused",
            role=UserRole.MEMBER,
            is_active=True,
        )
        item = lot(db, org.id, "Creator-scoped", 1, "kg")
        db.commit()

        with pytest.raises(IntegrityError, match="fk_lot_cost_entries_creator"):
            service.set_lot_price(db, org.id, item.id, amount="1", quantity="1", user_id=foreign_user.id)
        db.rollback()

        entry = service.set_lot_price(db, org.id, item.id, amount="1", quantity="1", user_id=actor.id)
        db.commit()
        entry_id = entry.id
        db.delete(db.get(User, actor.id))
        db.commit()
        db.expire_all()
        persisted = db.get(LotCostEntry, entry_id)
        assert persisted.org_id == org.id
        assert persisted.created_by_user_id is None
    finally:
        purge(db, other)


def test_put_flow_price_on_the_lots_own_flow(world, db):
    (created,) = flows(db, world["org"].id, world["item"].id, kind="created")
    response = world["admin"].put(
        f"{API}/lots/{world['item'].id}/cost",
        json={"kind": "manual", "amount": "100", "quantity": "2", "cost_flow_id": str(created.id)},
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["unit_cost"] == "50.000000"


def test_put_on_production_lot_is_400(world, db):
    from app.core.db.models.inventory_item import InventoryItem

    gin = (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == world["org"].id, InventoryItem.source_execution_id == world["execution"].id)
        .one()
    )
    response = world["admin"].put(f"{API}/lots/{gin.id}/cost", json={"kind": "manual", "amount": "1", "quantity": "1"})
    assert response.status_code == 400


def test_delete_entry(world):
    admin = world["admin"]
    response = admin.delete(f"{API}/lots/{world['item'].id}/cost/{world['entry'].id}")
    assert response.status_code in (200, 204)
    assert admin.get(f"{API}/lots/{world['item'].id}/cost").get_json()["status"] == "unknown"
    again = admin.delete(f"{API}/lots/{world['item'].id}/cost/{world['entry'].id}")
    assert again.status_code == 404, "an already-deactivated entry is gone"


def test_ac62_settings(world):
    admin = world["admin"]
    assert admin.get(f"{API}/settings").get_json() == {"use_last_known_price": True}
    assert admin.put(f"{API}/settings", json={"use_last_known_price": False}).status_code == 200
    assert admin.get(f"{API}/settings").get_json() == {"use_last_known_price": False}
    for bad in ({"use_last_known_price": "no"}, {"use_last_known_price": 0}, {}, {"other": True}):
        assert admin.put(f"{API}/settings", json=bad).status_code == 400, bad
    assert admin.get(f"{API}/settings").get_json() == {"use_last_known_price": False}


def test_settings_are_per_org(world, db, flask_app):  # noqa: F811
    world["admin"].put(f"{API}/settings", json={"use_last_known_price": False})
    other = new_org(db)
    try:
        client = user_client(db, flask_app, other)
        assert client.get(f"{API}/settings").get_json() == {"use_last_known_price": True}
    finally:
        purge(db, other)
