import uuid

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e


def test_signup_aligns_name_limit_and_api_validation(page, app_url, assert_json_field_error):
    page.goto("/")
    page.get_by_role("button", name="Sign Up").first.click()
    name = page.locator("#signup-org-name")
    expect(name).to_have_attribute("maxlength", "255")
    name.fill("A" * 256)
    assert len(name.input_value()) == 255

    assert_json_field_error(
        page,
        "POST",
        "/auth/signup",
        {
            "org_name": "A" * 256,
            "email": f"e2e-signup-validation-{uuid.uuid4()}@example.test",
            "password": "Example valid passphrase",
            "password_confirm": "Example valid passphrase",
        },
        "org_name",
    )


def test_opening_stock_wip_requires_quantity(page, app_url, fresh_user, assert_json_field_error):
    admin = fresh_user(UserRole.ADMIN)
    login_through_ui(page, admin["email"], admin["password"])
    page.goto("/core/go-live")
    name = page.get_by_label("What", exact=True)
    expect(name).to_be_visible()
    page.get_by_role("button", name="Save date").click()
    expect(page.get_by_text("Go-live date saved.", exact=False)).to_be_visible()
    name.fill("Opening stock")
    page.get_by_role("button", name="Record opening stock").click()
    expect(page.get_by_text("Enter a quantity for the work in progress.", exact=True)).to_be_visible()

    assert_json_field_error(
        page,
        "POST",
        "/api/core/opening-stock",
        {"items": [{"name": "Opening stock", "unit": "L", "quantity": 0, "inventory_type": "work_in_progress"}]},
        "items.0.quantity",
        headers=csrf_headers(page),
    )
