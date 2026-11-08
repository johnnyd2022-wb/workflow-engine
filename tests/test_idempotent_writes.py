"""GL-U03: a receipt whose reply was lost can be saved again without adding the stock twice."""

from uuid import uuid4

import pytest

from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
from app.core.db.models.inventory_item import InventoryItem
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export

URL = "/api/core/inventory"


@pytest.fixture
def _account(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    yield {"client": client, "org_id": org.id}
    db.rollback()
    db.query(ApiIdempotencyKey).filter(ApiIdempotencyKey.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    clear_org_synthetic_data(db, org.id)


def _client(_account):
    return _account["client"]


def _count(db, name):
    db.expire_all()
    return db.query(InventoryItem).filter(InventoryItem.name == name).count()


def _body(name, qty="5"):
    return {"name": name, "quantity": qty, "unit": "kg", "inventory_type": "raw_material"}


def test_the_same_key_twice_adds_the_stock_once_and_replays_the_reply(_account, db):
    client, name, key = _client(_account), f"Juniper {uuid4().hex[:6]}", str(uuid4())
    first = client.post(URL, json=_body(name), headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.get_json()
    again = client.post(URL, json=_body(name), headers={"Idempotency-Key": key})
    assert again.status_code == 201
    assert again.headers.get("Idempotent-Replay") == "true"
    assert again.get_json()["id"] == first.get_json()["id"]
    assert _count(db, name) == 1


def test_a_reused_key_with_a_different_receipt_is_refused(_account, db):
    client, name, key = _client(_account), f"Coriander {uuid4().hex[:6]}", str(uuid4())
    assert client.post(URL, json=_body(name), headers={"Idempotency-Key": key}).status_code == 201
    other = client.post(URL, json=_body(name, "9"), headers={"Idempotency-Key": key})
    assert other.status_code == 409 and "different request" in other.get_json()["error"]
    assert _count(db, name) == 1


def test_a_rejected_save_frees_its_key_for_the_corrected_one(_account, db):
    client, name, key = _client(_account), f"Orris {uuid4().hex[:6]}", str(uuid4())
    bad = client.post(URL, json=_body(name, "0"), headers={"Idempotency-Key": key})
    assert bad.status_code == 400
    good = client.post(URL, json=_body(name, "3"), headers={"Idempotency-Key": key})
    assert good.status_code == 201, good.get_json()
    assert _count(db, name) == 1


def test_without_a_key_each_save_is_its_own(_account, db):
    client, name = _client(_account), f"Angelica {uuid4().hex[:6]}"
    assert client.post(URL, json=_body(name)).status_code == 201
    assert client.post(URL, json=_body(name)).status_code == 201
    assert _count(db, name) == 2


def test_a_saved_receipt_is_stored_against_its_org(_account, db):
    first, name, key = _client(_account), f"Cassia {uuid4().hex[:6]}", str(uuid4())
    assert first.post(URL, json=_body(name), headers={"Idempotency-Key": key}).status_code == 201
    rows = db.query(ApiIdempotencyKey).filter(ApiIdempotencyKey.org_id == _account["org_id"]).all()
    assert len(rows) == 1 and rows[0].http_status == 201  # stored, and scoped to this org
