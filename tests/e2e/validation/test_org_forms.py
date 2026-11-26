import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e


def test_people_invite_rejects_invalid_email_without_submitting(page, app_url, fresh_user, assert_json_field_error):
    admin = fresh_user(UserRole.ADMIN)
    login_through_ui(page, admin["email"], admin["password"])
    page.goto("/core/people")
    page.get_by_role("button", name="Invite someone").click()
    email = page.get_by_role("textbox", name="Email")
    expect(email).to_have_attribute("maxlength", "255")
    email.fill("invalid-email")
    page.get_by_role("button", name="Create invite link").click()
    expect(page.get_by_text("Enter a valid email address.", exact=True)).to_be_visible()

    assert_json_field_error(page, "POST", "/org/users", {"email": "invalid-email"}, "email", headers=csrf_headers(page))
