"""AC: `GET/POST /api/compliant/alcohol-products` -- list ordered by inventory_name,
create validates product_type/inventory_name/abv_percent, duplicate (org_id,
inventory_name) returns 409 not a raw 500 (.agents/specs/compliant-platform.md,
"Alcohol product profiles").
"""

from __future__ import annotations

import uuid

import pytest

from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e


def test_create_and_list_alcohol_products_happy_path(admin_page, create_alcohol_product):
    run_id = uuid.uuid4().hex[:8]
    zeta_name = f"Zeta Gin {run_id}"
    alpha_name = f"Alpha Gin {run_id}"
    create_alcohol_product(admin_page, zeta_name, product_type="spirits", abv_percent="40")
    create_alcohol_product(admin_page, alpha_name, product_type="spirits", abv_percent="37.5")

    response = admin_page.request.get("/api/compliant/alcohol-products")
    assert response.status == 200, response.text()
    products = response.json()["products"]
    names = [p["inventory_name"] for p in products if p["inventory_name"] in (zeta_name, alpha_name)]
    # AC: ordered by inventory_name -- Alpha must sort before Zeta regardless of
    # creation order (Zeta was created first above).
    assert names == [alpha_name, zeta_name]


def test_create_alcohol_product_duplicate_name_returns_409_not_500(admin_page, create_alcohol_product):
    name = f"House Gin {uuid.uuid4().hex[:8]}"
    create_alcohol_product(admin_page, name, product_type="spirits", abv_percent="40")

    response = admin_page.request.post(
        "/api/compliant/alcohol-products",
        headers=csrf_headers(admin_page),
        data={"inventory_name": name, "product_type": "spirits", "abv_percent": "40"},
    )
    assert response.status == 409, f"expected 409 on duplicate name, got {response.status}: {response.text()}"
    assert "already exists" in response.json()["error"]


def test_create_alcohol_product_requires_admin(member_page):
    response = member_page.request.post(
        "/api/compliant/alcohol-products",
        headers=csrf_headers(member_page),
        data={"inventory_name": "Member Gin", "product_type": "spirits", "abv_percent": "40"},
    )
    assert response.status == 403, f"expected a MEMBER to be rejected, got {response.status}"


def test_create_alcohol_product_rejects_unknown_product_type(admin_page):
    response = admin_page.request.post(
        "/api/compliant/alcohol-products",
        headers=csrf_headers(admin_page),
        data={"inventory_name": "Weird Product", "product_type": "moonshine", "abv_percent": "40"},
    )
    assert response.status == 400
    assert "type" in response.json()["error"]


@pytest.mark.parametrize("abv_percent", ["0", "-5", "100.01", "not-a-number", "nan", "-nan", "Infinity"])
def test_create_alcohol_product_rejects_invalid_abv(admin_page, abv_percent):
    """AC (security-audit F1): a non-finite Decimal (NaN/Infinity) must 400 cleanly, not
    crash with an unhandled decimal.InvalidOperation on the `<`/`<=` comparison."""
    response = admin_page.request.post(
        "/api/compliant/alcohol-products",
        headers=csrf_headers(admin_page),
        data={"inventory_name": f"Bad ABV {abv_percent}", "product_type": "spirits", "abv_percent": abv_percent},
    )
    assert response.status == 400, f"abv_percent={abv_percent!r} should be rejected, got {response.status}"


def test_create_alcohol_product_rejects_missing_inventory_name(admin_page):
    response = admin_page.request.post(
        "/api/compliant/alcohol-products",
        headers=csrf_headers(admin_page),
        data={"inventory_name": "", "product_type": "spirits", "abv_percent": "40"},
    )
    assert response.status == 400
    assert "inventory_name" in response.json()["error"]


def test_create_alcohol_product_rejects_overlong_customs_product_code(admin_page):
    """AC (security-audit F2): customs_product_code is String(100); an overlong value must
    400 before insert, not raise an uncaught sqlalchemy.exc.DataError (not an IntegrityError
    subclass, so it fell through the existing except block)."""
    response = admin_page.request.post(
        "/api/compliant/alcohol-products",
        headers=csrf_headers(admin_page),
        data={
            "inventory_name": "Overlong Customs Code",
            "product_type": "spirits",
            "abv_percent": "40",
            "customs_product_code": "X" * 101,
        },
    )
    assert response.status == 400
    assert "customs_product_code" in response.json()["error"]
