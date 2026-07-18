"""Cross-tenant probe: org B must never reach org A's data.

The highest-value test in this suite. Every other failure here is an inconvenience; this
one is the failure that ends the company — a manufacturer seeing another manufacturer's
production data. Unit tests assert repositories filter by org_id; this asserts the whole
stack does, through a real authenticated browser session, which is the thing an attacker
actually holds.

Mutating verbs are covered as well as reads: a read probe that passes while the matching
PUT/DELETE silently succeeds cross-tenant would be a false all-clear.
"""

import uuid

import pytest

from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e


@pytest.fixture()
def two_tenants(browser, app_url, fresh_user):
    """Two orgs, each with its own authenticated browser context."""
    org_a, org_b = fresh_user(), fresh_user()
    contexts = []

    def _sign_in(user):
        context = browser.new_context(base_url=app_url, ignore_https_errors=True)
        contexts.append(context)
        page = context.new_page()
        login_through_ui(page, user["email"], user["password"])
        return page

    pages = {"a": _sign_in(org_a), "b": _sign_in(org_b)}
    yield pages
    for context in contexts:
        context.close()


def _create_inventory_item(page, name: str, barcode: str | None = None) -> str:
    payload = {"name": name, "quantity": 5, "unit": "kg", "inventory_type": "RAW_MATERIAL"}
    if barcode:
        payload["barcode"] = barcode
    response = page.request.post("/api/core/inventory", headers=csrf_headers(page), data=payload)
    assert response.status in (200, 201), f"setup failed: {response.status} {response.text()}"
    body = response.json()
    item_id = body.get("id") or body.get("item", {}).get("id")
    assert item_id, f"could not find id in create response: {body}"
    return item_id


def test_org_b_cannot_read_org_a_item_by_barcode(two_tenants):
    """Read-by-attribute probe (there is no GET-by-id route). find_by_barcode filters on
    org_id, so org B looking up org A's barcode must see nothing."""
    barcode = f"BC-{uuid.uuid4().hex[:10]}"
    name = f"Secret Botanicals {uuid.uuid4().hex[:6]}"
    _create_inventory_item(two_tenants["a"], name, barcode=barcode)

    response = two_tenants["b"].request.get(f"/api/core/inventory/barcode/{barcode}")
    assert response.status == 200, f"barcode lookup failed: {response.status}"
    body = response.json()
    assert body.get("exists") is False, "org B resolved org A's barcode to a real product"
    assert name not in response.text(), "org A's product name leaked via barcode lookup"

    # Sanity: org A itself can resolve its own barcode — proves the probe would catch a leak.
    owner = two_tenants["a"].request.get(f"/api/core/inventory/barcode/{barcode}")
    assert owner.json().get("exists") is True, "owner cannot see its own item — probe is inert"


def test_org_b_cannot_update_org_a_inventory_item(two_tenants):
    item_id = _create_inventory_item(two_tenants["a"], f"Secret Botanicals {uuid.uuid4().hex[:6]}")

    page_b = two_tenants["b"]
    response = page_b.request.put(
        f"/api/core/inventory/{item_id}",
        headers=csrf_headers(page_b),
        data={"name": "owned by B now", "quantity": 999, "unit": "kg"},
    )
    assert response.status in (403, 404), f"org B updated org A's item: {response.status}"


def test_org_b_cannot_delete_org_a_inventory_item(two_tenants):
    item_id = _create_inventory_item(two_tenants["a"], f"Secret Botanicals {uuid.uuid4().hex[:6]}")

    page_b = two_tenants["b"]
    response = page_b.request.delete(f"/api/core/inventory/{item_id}", headers=csrf_headers(page_b))
    assert response.status in (403, 404), f"org B deleted org A's item: {response.status}"

    # And it must still be there for its actual owner — a 404 that still deleted is worse
    # than a leak, because it hides.
    barcode_check = _reachable_by_owner(two_tenants["a"], item_id)
    assert barcode_check, "org A's item disappeared after org B's delete attempt"


def _reachable_by_owner(page, item_id: str) -> bool:
    """Owner can still PUT its own item (no GET-by-id exists to check with)."""
    response = page.request.put(
        f"/api/core/inventory/{item_id}",
        headers=csrf_headers(page),
        data={"name": "still mine", "quantity": 5, "unit": "kg"},
    )
    return response.status in (200, 201)


def test_org_b_inventory_list_excludes_org_a_items(two_tenants):
    marker = f"Isolation Marker {uuid.uuid4().hex[:8]}"
    _create_inventory_item(two_tenants["a"], marker)

    response = two_tenants["b"].request.get("/api/core/inventory")
    assert response.status == 200, f"list failed for org B: {response.status}"
    assert marker not in response.text(), "org A's item leaked into org B's inventory list"


def test_org_b_dashboard_summary_excludes_org_a_data(two_tenants):
    """Aggregates are the sneakiest leak: no ids cross, but the numbers do."""
    marker = f"Isolation Marker {uuid.uuid4().hex[:8]}"
    _create_inventory_item(two_tenants["a"], marker)

    response = two_tenants["b"].request.get("/api/core/dashboard/summary")
    assert response.status == 200, f"summary failed for org B: {response.status}"
    assert marker not in response.text(), "org A's data leaked into org B's dashboard summary"
