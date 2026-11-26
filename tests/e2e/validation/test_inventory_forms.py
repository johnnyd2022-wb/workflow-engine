import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e


def test_manual_inventory_quantity_matches_server_bounds(logged_in_page, app_url, assert_json_field_error):
    page = logged_in_page
    page.goto("/core/inventory/add/manual")
    quantity = page.get_by_role("spinbutton", name="Quantity")
    expect(quantity).to_have_attribute("min", "0.0001")
    quantity.fill("0")
    assert quantity.evaluate("(input) => input.validity.rangeUnderflow")

    assert_json_field_error(
        page,
        "POST",
        "/api/core/inventory",
        {"name": "Manual stock", "quantity": 0, "unit": "kg"},
        "quantity",
        headers=csrf_headers(page),
    )
