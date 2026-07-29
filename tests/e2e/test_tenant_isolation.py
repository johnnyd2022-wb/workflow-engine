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


def _create_inventory_item(
    page, name: str, barcode: str | None = None, quantity_override: int | None = None, inventory_type: str = "raw_material"
) -> str:
    payload = {
        "name": name,
        "quantity": quantity_override if quantity_override is not None else 5,
        "unit": "kg",
        "inventory_type": inventory_type,
    }
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


def test_org_b_cannot_adjust_org_a_inventory_item(two_tenants):
    """AC33/AC5: adjust is a guarded quantity write — cross-org must be 404, not a leak."""
    item_id = _create_inventory_item(two_tenants["a"], f"Secret Botanicals {uuid.uuid4().hex[:6]}")

    page_b = two_tenants["b"]
    response = page_b.request.post(
        f"/api/core/inventory/{item_id}/adjust",
        headers=csrf_headers(page_b),
        data={"new_quantity": 999},
    )
    assert response.status == 404, f"expected 404 not-found, got {response.status}: {response.text()}"

    # A 404 alone would also be returned by a route that rejected the response but had
    # already written. Read the owner's own quantity back and pin it exactly.
    page_a = two_tenants["a"]
    owner_view = page_a.request.get("/api/core/inventory")
    assert owner_view.status == 200, owner_view.status
    owned = next(i for i in owner_view.json()["inventory_items"] if i["id"] == item_id)
    assert owned["quantity"] == "5", f"org A's quantity changed despite the rejected adjust: {owned}"


def test_org_b_cannot_waste_org_a_inventory_item(two_tenants):
    """AC33/AC15: wastage on an id outside the caller's org is indistinguishable from a
    nonexistent id — never a distinguishable 403, and never a deduction."""
    item_id = _create_inventory_item(two_tenants["a"], f"Secret Botanicals {uuid.uuid4().hex[:6]}")

    page_b = two_tenants["b"]
    response = page_b.request.post(
        "/api/core/inventory/wastage",
        headers=csrf_headers(page_b),
        data={
            "entries": [{"inventory_item_id": item_id, "quantity_wasted": 1, "reason": "attempted cross-org waste"}],
            "idempotency_key": uuid.uuid4().hex,
        },
    )
    assert response.status == 400, f"expected 400, got {response.status}: {response.text()}"
    body = response.json()
    assert body["success"] is False
    assert any("not found or access denied" in e for e in body["errors"]), body["errors"]

    # Wasteability alone does not prove the item was untouched — an item silently reduced
    # from 5 to 4 is still wasteable. Pin the exact quantity BEFORE the owner writes.
    page_a = two_tenants["a"]
    owner_view = page_a.request.get("/api/core/inventory")
    assert owner_view.status == 200, owner_view.status
    owned = next(i for i in owner_view.json()["inventory_items"] if i["id"] == item_id)
    assert owned["quantity"] == "5", f"org A's quantity changed despite the rejected wastage: {owned}"

    owner_waste = page_a.request.post(
        "/api/core/inventory/wastage",
        headers=csrf_headers(page_a),
        data={
            "entries": [{"inventory_item_id": item_id, "quantity_wasted": 1, "reason": "owner waste after probe"}],
            "idempotency_key": uuid.uuid4().hex,
        },
    )
    assert owner_waste.status == 201, "owner could not waste its own item after org B's rejected attempt"


def test_org_b_wastage_list_excludes_org_a_records(two_tenants):
    """AC19/AC33: listing wastage never surfaces another org's records or item names."""
    marker = f"Isolation Wastage {uuid.uuid4().hex[:8]}"
    item_id = _create_inventory_item(two_tenants["a"], marker, quantity_override=5)
    page_a = two_tenants["a"]
    waste = page_a.request.post(
        "/api/core/inventory/wastage",
        headers=csrf_headers(page_a),
        data={
            "entries": [{"inventory_item_id": item_id, "quantity_wasted": 1, "reason": "org A wastage"}],
            "idempotency_key": uuid.uuid4().hex,
        },
    )
    assert waste.status == 201, f"setup wastage failed: {waste.status} {waste.text()}"
    record_id = waste.json()["wastage_records"][0]["id"]

    response = two_tenants["b"].request.get("/api/core/inventory/wastage")
    assert response.status == 200, f"list failed for org B: {response.status}"
    # Item-name absence alone is too weak: item-name hydration is separately org-scoped, so
    # a repository that lost its own org filter would leak the record while still rendering
    # item_name "Unknown" — and a marker-only assertion would pass. Assert on the record's
    # own fields, which no other layer sanitises. (test-evaluator's finding.)
    leaked = [r for r in response.json()["wastage_records"] if r["id"] == record_id]
    assert not leaked, f"org A's wastage record leaked into org B's wastage list: {leaked}"
    assert item_id not in response.text(), "org A's inventory item id leaked via the wastage list"
    assert "org A wastage" not in response.text(), "org A's wastage reason leaked into org B's list"
    assert marker not in response.text(), "org A's item name leaked into org B's wastage list"


def test_org_b_out_of_stock_excludes_org_a_items(two_tenants):
    """AC8/AC33: out-of-stock recall tracing must never cross tenants."""
    marker = f"Isolation OutOfStock {uuid.uuid4().hex[:8]}"
    # inventory_type must be the exact lowercase enum value — out-of-stock filters on it
    # exactly, unlike list_inventory's other filters (see test_inventory_flow.py).
    item_id = _create_inventory_item(two_tenants["a"], marker, quantity_override=3, inventory_type="raw_material")
    page_a = two_tenants["a"]
    zero_out = page_a.request.post(
        f"/api/core/inventory/{item_id}/adjust",
        headers=csrf_headers(page_a),
        data={"new_quantity": 0},
    )
    assert zero_out.status == 200, f"setup adjust failed: {zero_out.status} {zero_out.text()}"

    response = two_tenants["b"].request.get("/api/core/inventory/out-of-stock")
    assert response.status == 200, f"out-of-stock failed for org B: {response.status}"
    assert marker not in response.text(), "org A's zeroed item leaked into org B's out-of-stock listing"


def _create_untracked_item(page, name: str) -> str:
    resp = page.request.post(
        "/api/core/inventory",
        headers=csrf_headers(page),
        data={
            "name": name,
            "quantity": 8,
            "unit": "kg",
            "inventory_type": "raw_material",
            "untracked": True,
            "notes": "cross-tenant reconciliation probe",
        },
    )
    assert resp.status == 201, f"untracked setup failed: {resp.status} {resp.text()}"
    return resp.json()["id"]


def test_org_b_matching_untracked_excludes_org_a_items(two_tenants):
    """AC29/AC33: reconciliation's untracked-item search is org-scoped."""
    marker = f"Isolation Untracked {uuid.uuid4().hex[:8]}"
    _create_untracked_item(two_tenants["a"], marker)

    response = two_tenants["b"].request.get(f"/api/core/inventory/reconcile/matching-untracked?name={marker}&unit=kg")
    assert response.status == 200, f"matching-untracked failed for org B: {response.status}"
    assert response.json()["matching_untracked"] == [], "org A's untracked item leaked into org B's search"


def test_org_b_cannot_reconcile_via_addition_onto_org_a_untracked_item(two_tenants):
    """AC30/AC33: mapping onto another org's untracked_item_id must fail as not-found, and
    must not mutate org A's item."""
    marker = f"Isolation Reconcile {uuid.uuid4().hex[:8]}"
    untracked_id = _create_untracked_item(two_tenants["a"], marker)

    page_b = two_tenants["b"]
    response = page_b.request.post(
        "/api/core/inventory/reconcile/via-addition",
        headers=csrf_headers(page_b),
        data={"name": marker, "quantity": 5, "unit": "kg", "untracked_item_id": untracked_id},
    )
    assert response.status == 400, f"expected 400, got {response.status}: {response.text()}"
    assert "not found" in response.json()["error"].lower()

    # Org A's untracked balance must be untouched. Mere membership in the matching list is
    # too weak — an item partially reduced from 8 to 3 still matches. Pin the balance.
    page_a = two_tenants["a"]
    still_matches = page_a.request.get(f"/api/core/inventory/reconcile/matching-untracked?name={marker}&unit=kg")
    matches = still_matches.json()["matching_untracked"]
    mine = next((m for m in matches if m["id"] == untracked_id), None)
    assert mine is not None, "org A's untracked item disappeared after org B's rejected attempt"
    assert str(mine["quantity"]) == "8", f"org A's untracked balance changed: {mine}"
    # remaining_balance_to_reconcile is the field the reconcile flow actually decrements —
    # quantity alone can hold steady while the reconcile ledger moves underneath it.
    owner_list = page_a.request.get("/api/core/inventory")
    assert owner_list.status == 200, owner_list.status
    owner_item = next(i for i in owner_list.json()["inventory_items"] if i["id"] == untracked_id)
    assert str(owner_item["extra_data"].get("remaining_balance_to_reconcile")) == "8.0", (
        f"org A's reconcile balance moved despite the rejected attempt: {owner_item['extra_data']}"
    )

    # And org B must not have quietly received an item of its own out of the rejected call.
    b_items = page_b.request.get("/api/core/inventory")
    assert b_items.status == 200, b_items.status
    assert marker not in b_items.text(), "org B received an item from its own rejected reconcile"
