"""Opt-in keyset pagination on /api/core/executions and /api/core/inventory.

The design record asks for cursor pagination on the big list endpoints. It is added
*opt-in*: a request with no ?limit returns the full list exactly as before, so none of the
~20 existing callers (process pickers, sourcemap, reconciliation, dispose) change
behaviour. These tests pin both halves -- the unchanged default, and the paginated path:
stable disjoint pages, an honest has_more, and a 400 (not a 500) for a tampered cursor.
"""

from uuid import uuid4

import pytest

from app.core.db.models.execution import Execution
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import (
    DEFAULT_TEST_PASSWORD,
    ExecutionFactory,
    InventoryItemFactory,
    OrganisationFactory,
    ProcessFactory,
)

PASSWORD = DEFAULT_TEST_PASSWORD


@pytest.fixture
def flask_app():
    from app.api.app_factory import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        yield app


@pytest.fixture
def client_org(db, flask_app):
    org = OrganisationFactory()
    db.commit()
    email = f"user_{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org.id,
        email=email,
        password_hash=AuthService.hash_password(PASSWORD),
        is_active=True,
    )
    db.commit()
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    yield org, client
    db.rollback()
    db.query(InventoryItem).filter(InventoryItem.org_id == org.id).delete(synchronize_session=False)
    db.query(Execution).filter(Execution.org_id == org.id).delete(synchronize_session=False)
    db.query(Process).filter(Process.org_id == org.id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def _seed_executions(db, org, n):
    proc = ProcessFactory(org_id=org.id)
    for _ in range(n):
        ExecutionFactory(org_id=org.id, process_id=proc.id)
    db.commit()


def _seed_items(db, org, n):
    for _ in range(n):
        InventoryItemFactory(org_id=org.id, quantity="5")
    db.commit()


# --- backward compatibility: no ?limit == full list, no pagination keys ---------------


def test_executions_without_limit_returns_full_list_and_no_page_keys(db, client_org):
    org, client = client_org
    _seed_executions(db, org, 7)
    body = client.get("/api/core/executions").get_json()
    assert len(body["executions"]) == 7
    assert "has_more" not in body and "next_cursor" not in body


def test_inventory_without_limit_returns_full_list_and_no_page_keys(db, client_org):
    org, client = client_org
    _seed_items(db, org, 7)
    body = client.get("/api/core/inventory").get_json()
    assert len(body["inventory_items"]) == 7
    assert "has_more" not in body and "next_cursor" not in body


def test_inventory_compact_view_returns_core_fields_only(db, client_org):
    """view=compact drops the per-item enrichment (system_findings, producing-step
    hydration, audit history) the sourcemap browse grid never reads -- same rows, far
    smaller payload, and it still paginates."""
    org, client = client_org
    _seed_items(db, org, 7)

    full = client.get("/api/core/inventory").get_json()["inventory_items"]
    compact = client.get("/api/core/inventory?view=compact").get_json()["inventory_items"]

    assert len(compact) == len(full) == 7
    assert {i["id"] for i in compact} == {i["id"] for i in full}
    expected = {
        "id",
        "name",
        "display_label",
        "inventory_type",
        "quantity",
        "unit",
        "supplier",
        "supplier_batch_number",
        "expiry_date",
    }
    assert all(set(i) == expected for i in compact), compact[0].keys()
    assert "system_findings" not in compact[0]

    paged = client.get("/api/core/inventory?view=compact&limit=3").get_json()
    assert len(paged["inventory_items"]) == 3
    assert paged["has_more"] is True and paged["next_cursor"]


# --- paginated path -----------------------------------------------------------------


def test_executions_pagination_walks_disjoint_ordered_pages(db, client_org):
    org, client = client_org
    _seed_executions(db, org, 12)

    seen = []
    cursor = None
    pages = 0
    while True:
        url = "/api/core/executions?limit=5" + (f"&cursor={cursor}" if cursor else "")
        body = client.get(url).get_json()
        page = body["executions"]
        assert len(page) <= 5
        seen.extend(e["id"] for e in page)
        pages += 1
        if not body["has_more"]:
            assert body["next_cursor"] is None
            break
        cursor = body["next_cursor"]
        assert cursor
        assert pages < 10, "pagination did not terminate"

    assert pages == 3  # 5 + 5 + 2
    assert len(seen) == 12
    assert len(set(seen)) == 12, "pages overlapped"


def test_inventory_limit_is_clamped_to_50(db, client_org):
    org, client = client_org
    _seed_items(db, org, 55)
    body = client.get("/api/core/inventory?limit=1000").get_json()
    assert len(body["inventory_items"]) == 50
    assert body["has_more"] is True


@pytest.mark.parametrize("path", ["/api/core/executions", "/api/core/inventory"])
def test_bad_limit_and_tampered_cursor_are_400_not_500(client_org, path):
    _org, client = client_org
    assert client.get(f"{path}?limit=abc").status_code == 400
    assert client.get(f"{path}?limit=0").status_code == 400
    assert client.get(f"{path}?limit=5&cursor=not-a-real-cursor").status_code == 400
    assert client.get(f"{path}?limit=5&cursor=" + "A" * 12).status_code == 400
