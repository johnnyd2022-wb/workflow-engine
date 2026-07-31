"""Tests for wastage recording and its idempotency (Batch 3).

Wastage disposal is a dual-write: it deducts inventory_items.quantity and appends the
wastage/movement audit rows in one transaction. On a client retry that must not double-apply
— the route accepts an optional idempotency_key and stores the response so a repeat with the
same key + same payload replays the stored result instead of disposing twice. A duplicated
disposal silently corrupts stock and audit numbers, and none of this was tested.

Idempotency is enforced in the route handler (POST /api/core/inventory/wastage), so those
tests drive it through an authenticated Flask test client. Wastage org-scoping is a
repository property, tested directly — this also completes the wastage isolation deferred
from Batch 2.
"""

import threading
import time
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db import db_session
from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovement
from app.core.db.models.inventory_wastage import InventoryWastage
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.wastage_repo import WastageRepository
from app.core.security.auth_service import AuthService
from tests.factories import InventoryItemFactory, OrganisationFactory, WastageFactory


@pytest.fixture
def org(db):
    organisation = OrganisationFactory()
    db.commit()
    # Capture the id as a plain value: the Flask test client's request teardown calls
    # db_session.remove(), which detaches `organisation`, so reading organisation.id in the
    # fixture teardown below would raise DetachedInstanceError. The UUID does not.
    org_id = organisation.id
    yield organisation
    db.rollback()
    # These org children have ON DELETE NO ACTION, so they must be removed before the org.
    # Deleting the org then cascades users + audit_logs + entity_events (all ON DELETE
    # CASCADE from organisations) — deleting the user directly would instead FK-fail on the
    # audit rows login created (users <- audit_logs is NO ACTION).
    for model in (InventoryMovement, InventoryWastage, ApiIdempotencyKey, InventoryItem):
        db.query(model).filter(model.org_id == org_id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def user(db, org):
    from app.core.db.repositories.user_repo import UserRepository

    u = UserRepository(db).create_user(
        org_id=org.id,
        email=f"wastage_{uuid4()}@test.com",
        password_hash=AuthService.hash_password("TestPass123!"),
    )
    db.commit()
    yield u


@pytest.fixture
def app_client(db, org, user):
    """Authenticated Flask test client scoped to `org`."""
    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    with flask_app.test_client() as client:
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        with flask_app.app_context():
            resp = client.post(
                "/auth/login",
                json={"email": user.email, "password": "TestPass123!"},
                content_type="application/json",
            )
            assert resp.status_code in (200, 201), f"Login failed: {resp.data}"
            yield client


def _quantity_of(item_id):
    return db_session().get(InventoryItem, item_id).quantity


def test_wastage_records_and_deducts_quantity(db, app_client, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")

    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={"entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "3", "reason": "spillage"}]},
    )

    assert resp.status_code == 201, resp.data
    assert resp.get_json()["success"] is True
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("7")
    assert db.query(InventoryWastage).filter(InventoryWastage.inventory_item_id == item.id).count() == 1


def test_wastage_idempotent_replay_does_not_double_deduct(db, app_client, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    payload = {
        "entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "3", "reason": "spillage"}],
        "idempotency_key": f"key-{uuid4()}",
    }

    first = app_client.post("/api/core/inventory/wastage", json=payload)
    assert first.status_code == 201, first.data
    assert not first.get_json().get("idempotent_replay", False)

    second = app_client.post("/api/core/inventory/wastage", json=payload)

    # Same key + same payload: the stored response is replayed, flagged, and nothing disposes again.
    assert second.status_code == 201, second.data
    assert second.get_json().get("idempotent_replay") is True
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("7")  # deducted once, not twice
    assert db.query(InventoryWastage).filter(InventoryWastage.inventory_item_id == item.id).count() == 1


def test_wastage_advisory_lock_serializes_concurrent_duplicate_submissions(db, org, user, monkeypatch):
    """AC18: concurrent duplicate submissions of the same org+key are serialized by the
    transaction-scoped `pg_advisory_xact_lock` in `_pg_advisory_lock_wastage_idempotency`,
    not just raced against the unique (org_id, key) constraint after the fact.

    `test_wastage_idempotent_replay_does_not_double_deduct` above proves the serial
    replay case, but a serial test can never exercise the lock itself: the second
    request only starts once the first has already returned. Two real threads with a
    `threading.Barrier` starting them at the same instant is not enough either — a
    fast local Postgres round-trip means the first request can validate, deduct, and
    commit before the second one even reaches the lock call, so the two never actually
    contend (verified: that version of this test kept passing with the lock call
    deleted entirely).

    So this version forces the contention deterministically instead of hoping for it:
    it wraps `_pg_advisory_lock_wastage_idempotency` to have the *first* caller to reach
    it call through to the real `pg_advisory_xact_lock` (still a genuine Postgres call,
    still genuinely holding the lock) and then sleep half a second before returning —
    holding the transaction, and therefore the lock, open. That gives the second caller
    a real window to issue its own `pg_advisory_xact_lock` and genuinely block on it
    inside Postgres. The serialization proven here is still Postgres's, not the test's;
    the wrapper only guarantees the two calls actually overlap.
    """
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    key = f"key-{uuid4()}"
    payload = {
        "entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "3", "reason": "spillage"}],
        "idempotency_key": key,
    }

    import app.core.backend.backend as backend_module

    original_lock = backend_module._pg_advisory_lock_wastage_idempotency
    order_lock = threading.Lock()
    call_count = {"n": 0}

    def delayed_lock(session, org_id_arg, idem_key_arg):
        original_lock(session, org_id_arg, idem_key_arg)  # the real pg_advisory_xact_lock call
        with order_lock:
            call_count["n"] += 1
            is_first = call_count["n"] == 1
        if is_first:
            time.sleep(0.5)

    monkeypatch.setattr(backend_module, "_pg_advisory_lock_wastage_idempotency", delayed_lock)

    from app.api.app_factory import create_app

    def _logged_in_client():
        flask_app = create_app()
        flask_app.config["TESTING"] = True
        flask_app.config["WTF_CSRF_ENABLED"] = False
        client = flask_app.test_client()
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        with flask_app.app_context():
            resp = client.post(
                "/auth/login",
                json={"email": user.email, "password": "TestPass123!"},
                content_type="application/json",
            )
            assert resp.status_code in (200, 201), f"Login failed: {resp.data}"
        return client

    # Two independent clients (own cookie jar, own connection) so the only thing shared
    # between the threads is the database — the thing the advisory lock actually guards.
    client_a = _logged_in_client()
    client_b = _logged_in_client()

    barrier = threading.Barrier(2)
    results: list[tuple[int, dict] | None] = [None, None]
    errors: list[BaseException] = []

    def _fire(idx, client):
        try:
            barrier.wait(timeout=10)
            resp = client.post("/api/core/inventory/wastage", json=payload)
            results[idx] = (resp.status_code, resp.get_json())
        except BaseException as exc:  # noqa: BLE001 - surfaced via the errors list below
            errors.append(exc)

    threads = [
        threading.Thread(target=_fire, args=(0, client_a)),
        threading.Thread(target=_fire, args=(1, client_b)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert all(r is not None for r in results), f"a thread did not complete in time: {results}"
    assert call_count["n"] == 2, "both requests must reach the lock for this test to prove anything"

    assert [r[0] for r in results] == [201, 201], results
    replay_flags = sorted(bool(r[1].get("idempotent_replay")) for r in results)
    # Exactly one request actually disposed; the loser of the lock race replayed the
    # stored response instead of disposing a second time.
    assert replay_flags == [False, True], results

    db.expire_all()
    assert _quantity_of(item.id) == Decimal("7"), "advisory lock failed to prevent a double deduction"
    assert db.query(InventoryWastage).filter(InventoryWastage.inventory_item_id == item.id).count() == 1


def test_wastage_key_reuse_with_different_payload_is_rejected(db, app_client, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    key = f"key-{uuid4()}"

    first = app_client.post(
        "/api/core/inventory/wastage",
        json={
            "entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "3", "reason": "spillage"}],
            "idempotency_key": key,
        },
    )
    assert first.status_code == 201, first.data

    # Same key, different quantity → the request is refused rather than silently applied or replayed.
    conflict = app_client.post(
        "/api/core/inventory/wastage",
        json={
            "entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "5", "reason": "spillage"}],
            "idempotency_key": key,
        },
    )
    assert conflict.status_code == 409, conflict.data
    assert conflict.get_json()["error_code"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("7")  # only the first disposal applied


def test_wastage_batch_failure_rolls_back_item_wastage_and_movement_together(db, app_client, org, monkeypatch):
    """AC14: inventory_items.quantity, inventory_wastage, and inventory_movements are one
    ledger invariant committed in a single transaction — only the success path was tested
    before this. Force a failure partway through a two-entry batch, after the first entry's
    quantity mutation and wastage row are already flushed (but not committed), and prove the
    whole batch rolls back together: a partial commit here is silent stock and audit
    corruption. Mutation this catches: removing the shared `db_session.commit()` /
    `except Exception: db_session.rollback()` wrapper (or committing per-entry instead of
    once for the batch) would leave the first entry's deduction and wastage row persisted
    even though the batch as a whole failed.
    """
    item_a = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    item_b = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    db.commit()

    import app.core.backend.backend as backend_module

    original_assert = backend_module.assert_movement_unit_matches_item_canonical
    calls = {"n": 0}

    def flaky_assert(movement_unit, inventory_item_unit):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("simulated failure staged between the two ledger writes")
        return original_assert(movement_unit, inventory_item_unit)

    monkeypatch.setattr(backend_module, "assert_movement_unit_matches_item_canonical", flaky_assert)

    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={
            "entries": [
                {"inventory_item_id": str(item_a.id), "quantity_wasted": "3", "reason": "spillage"},
                {"inventory_item_id": str(item_b.id), "quantity_wasted": "4", "reason": "spillage"},
            ]
        },
    )

    assert resp.status_code == 500, resp.data
    assert calls["n"] == 2, "the simulated failure must fire on the second entry, after the first was staged"
    db.expire_all()
    assert _quantity_of(item_a.id) == Decimal("10"), "the first entry's deduction must roll back with the batch"
    assert _quantity_of(item_b.id) == Decimal("10")
    assert (
        db.query(InventoryWastage)
        .filter(InventoryWastage.inventory_item_id.in_([item_a.id, item_b.id]))
        .count()
        == 0
    ), "no wastage row may survive a rolled-back batch, including the entry staged before the failure"
    assert (
        db.query(InventoryMovement)
        .filter(InventoryMovement.inventory_item_id.in_([item_a.id, item_b.id]))
        .count()
        == 0
    ), "no ledger movement row may survive a rolled-back batch"


def test_wastage_converts_compatible_non_canonical_unit_and_records_metadata(db, app_client, org):
    """AC16: wasting in a unit compatible with (but different from) the item's canonical
    unit must deduct the CONVERTED amount, write the ledger row in the item's canonical
    unit, and record both units in movement_metadata for audit/replay."""
    item = InventoryItemFactory(org_id=org.id, quantity="1", unit="kg")
    db.commit()

    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={
            "entries": [
                {
                    "inventory_item_id": str(item.id),
                    "quantity_wasted": "500",
                    "quantity_unit": "g",
                    "reason": "spillage",
                }
            ]
        },
    )

    assert resp.status_code == 201, resp.data
    db.expire_all()
    # 500 g converts to 0.5 kg — the deduction must be the converted amount, not raw "500".
    assert _quantity_of(item.id) == Decimal("0.5000")

    record = db.query(InventoryWastage).filter(InventoryWastage.inventory_item_id == item.id).one()
    assert record.unit == "kg", "the wastage record must be stored in the item's canonical unit"
    assert Decimal(record.quantity_wasted) == Decimal("0.5000")

    movement = db.query(InventoryMovement).filter(InventoryMovement.inventory_item_id == item.id).one()
    assert movement.unit == "kg"
    assert movement.quantity == Decimal("-0.5000")
    assert movement.movement_metadata["converted_from_unit"] == "g"
    assert movement.movement_metadata["canonical_unit"] == "kg"


def test_wastage_rejects_incompatible_unit_with_400(db, app_client, org):
    """AC16: a quantity_unit that cannot be converted to the item's unit (different unit
    category, e.g. volume against a mass-tracked item) must be refused, not silently
    treated as the item's own unit."""
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    db.commit()

    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={
            "entries": [
                {
                    "inventory_item_id": str(item.id),
                    "quantity_wasted": "1",
                    "quantity_unit": "L",
                    "reason": "spillage",
                }
            ]
        },
    )

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error_code"] == "VALIDATION_FAILED"
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("10"), "a rejected incompatible unit must not deduct anything"


def test_wastage_rejects_idempotency_key_over_128_chars(db, app_client, org):
    """AC17: an idempotency_key that isn't a non-empty string <=128 chars is a 400, not a
    silently-truncated or silently-ignored key."""
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    db.commit()

    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={
            "entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "1", "reason": "spillage"}],
            "idempotency_key": "x" * 129,
        },
    )

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error_code"] == "IDEMPOTENCY_KEY_INVALID"
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("10")


def test_wastage_rejects_empty_idempotency_key(db, app_client, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    db.commit()

    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={
            "entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "1", "reason": "spillage"}],
            "idempotency_key": "   ",
        },
    )

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error_code"] == "IDEMPOTENCY_KEY_INVALID"


def test_wastage_rejects_non_string_idempotency_key(db, app_client, org):
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    db.commit()

    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={
            "entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "1", "reason": "spillage"}],
            "idempotency_key": 12345,
        },
    )

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error_code"] == "IDEMPOTENCY_KEY_INVALID"


def test_wastage_batch_rejects_more_than_max_entries(db, app_client, org):
    """AC13: a batch larger than MAX_WASTAGE_BATCH_ENTRIES is rejected outright."""
    from app.core.backend.backend import MAX_WASTAGE_BATCH_ENTRIES

    item = InventoryItemFactory(org_id=org.id, quantity="1000", unit="kg")
    db.commit()

    entries = [
        {"inventory_item_id": str(item.id), "quantity_wasted": "1", "reason": f"r{i}"}
        for i in range(MAX_WASTAGE_BATCH_ENTRIES + 1)
    ]
    resp = app_client.post("/api/core/inventory/wastage", json={"entries": entries})

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error_code"] == "BATCH_TOO_LARGE"
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("1000"), "an oversized batch must write nothing"


def test_wastage_rejects_duplicate_item_id_within_batch(db, app_client, org):
    """AC12: the same inventory_item_id appearing twice in one batch is a validation error,
    not two independent deductions."""
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    db.commit()

    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={
            "entries": [
                {"inventory_item_id": str(item.id), "quantity_wasted": "1", "reason": "spillage"},
                {"inventory_item_id": str(item.id), "quantity_wasted": "2", "reason": "spillage"},
            ]
        },
    )

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error_code"] == "VALIDATION_FAILED"
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("10")


def test_wastage_rejects_non_object_entry(db, app_client, org):
    """AC12: an entry that isn't a JSON object (e.g. a bare string) is a validation error,
    not a crash trying to call .get() on it."""
    resp = app_client.post("/api/core/inventory/wastage", json={"entries": ["not-an-object"]})

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error_code"] == "VALIDATION_FAILED"
    assert any("must be an object" in e for e in resp.get_json()["errors"])


def test_wastage_rejects_missing_item_id(db, app_client, org):
    """AC12: a missing inventory_item_id is a validation error."""
    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={"entries": [{"quantity_wasted": "1", "reason": "spillage"}]},
    )

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error_code"] == "VALIDATION_FAILED"
    assert any("inventory_item_id required" in e for e in resp.get_json()["errors"])


def test_wastage_rejects_invalid_item_id(db, app_client, org):
    """AC12: an inventory_item_id that isn't a valid UUID is a validation error, not a
    500 from a bare UUID(...) parse failure."""
    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={"entries": [{"inventory_item_id": "not-a-uuid", "quantity_wasted": "1", "reason": "spillage"}]},
    )

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error_code"] == "VALIDATION_FAILED"
    assert any("invalid inventory_item_id" in e.lower() for e in resp.get_json()["errors"])


def test_wastage_rejects_missing_reason(db, app_client, org):
    """AC12: a missing reason is a validation error — wastage without a stated cause must
    not be recordable."""
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    db.commit()

    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={"entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "1"}]},
    )

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error_code"] == "VALIDATION_FAILED"
    assert any("reason is required" in e for e in resp.get_json()["errors"])
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("10")


def test_wastage_rejects_reason_over_500_chars(db, app_client, org):
    """AC12: a reason longer than 500 characters is a validation error, not silently
    truncated on write."""
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    db.commit()

    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={
            "entries": [
                {"inventory_item_id": str(item.id), "quantity_wasted": "1", "reason": "x" * 501}
            ]
        },
    )

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error_code"] == "VALIDATION_FAILED"
    assert any("500 characters or fewer" in e for e in resp.get_json()["errors"])
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("10")


def test_wastage_rejects_wasting_more_than_on_hand(db, app_client, org):
    """AC15: wasting more than is on hand is a 400 naming the on-hand quantity, not a
    negative on-hand balance."""
    item = InventoryItemFactory(org_id=org.id, quantity="5", unit="kg")
    db.commit()

    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={"entries": [{"inventory_item_id": str(item.id), "quantity_wasted": "6", "reason": "spillage"}]},
    )

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error_code"] == "VALIDATION_FAILED"
    assert "5" in resp.get_json()["errors"][0]
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("5")


def test_wastage_records_are_org_scoped(db, two_org_two_user):
    org_a = two_org_two_user["org_a"]
    org_b = two_org_two_user["org_b"]
    item_a = InventoryItemFactory(org_id=org_a.id)
    item_b = InventoryItemFactory(org_id=org_b.id)
    WastageFactory(org_id=org_a.id, inventory_item_id=item_a.id)
    WastageFactory(org_id=org_b.id, inventory_item_id=item_b.id)
    db.commit()

    try:
        repo = WastageRepository(db)
        a_records = repo.list_wastage_records(org_a.id)
        a_item_ids = {r.inventory_item_id for r in a_records}
        assert item_a.id in a_item_ids
        assert item_b.id not in a_item_ids
    finally:
        for org_id in (org_a.id, org_b.id):
            db.query(InventoryWastage).filter(InventoryWastage.org_id == org_id).delete(synchronize_session=False)
            db.query(InventoryItem).filter(InventoryItem.org_id == org_id).delete(synchronize_session=False)
        db.commit()


@pytest.mark.parametrize(
    ("quantity_wasted", "why"),
    [
        ("0", "zero"),
        ("-3", "negative"),
        ("nan", "not a number"),
        ("Infinity", "non-finite"),
        ("1e19", "over MAX_WASTAGE_MAGNITUDE"),
        ("not-a-number", "unparseable"),
    ],
)
def test_wastage_route_rejects_bad_quantity_without_writing(db, app_client, org, quantity_wasted, why):
    """AC12 at the ROUTE, not just the helper.

    `parse_wastage_quantity` is unit-tested for each of these, but helper coverage does not
    prove the route turns the helper's error into 400 + VALIDATION_FAILED with no writes —
    deleting the route's `qty_err` branch leaves every helper test green (test-evaluator
    round 3). This asserts the status, the error code, the untouched quantity, and that
    neither ledger table gained a row.
    """
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    db.commit()

    resp = app_client.post(
        "/api/core/inventory/wastage",
        json={"entries": [{"inventory_item_id": str(item.id), "quantity_wasted": quantity_wasted, "reason": why}]},
    )

    assert resp.status_code == 400, f"{why!r} should be rejected: {resp.data}"
    body = resp.get_json()
    assert body["success"] is False
    assert body["error_code"] == "VALIDATION_FAILED", body
    assert body["wastage_records"] == []
    db.expire_all()
    assert _quantity_of(item.id) == Decimal("10"), f"{why!r} deducted despite being rejected"
    assert db.query(InventoryWastage).filter(InventoryWastage.inventory_item_id == item.id).count() == 0
    assert db.query(InventoryMovement).filter(InventoryMovement.inventory_item_id == item.id).count() == 0
