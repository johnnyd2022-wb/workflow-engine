"""Stage 4: organisation user management — add, remove, and authorization.

Adding/removing org members is an admin-only capability with real security weight (it
grants access to the org's data). Driven as an admin through the real browser session.
The /org/* routes are CSRF-protected (not in the exempt list), so mutations carry the
token like the SPA does.
"""

import uuid

import pytest

from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e


@pytest.fixture()
def admin_page(browser, app_url, fresh_user):
    from app.core.db.models.user import UserRole

    admin = fresh_user(role=UserRole.ADMIN)
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    login_through_ui(page, admin["email"], admin["password"])
    yield page
    context.close()


def test_admin_can_add_and_remove_a_user(admin_page):
    page = admin_page
    email = f"e2e-added-{uuid.uuid4().hex[:8]}@example.test"

    created = page.request.post(
        "/org/users",
        headers=csrf_headers(page),
        data={"email": email, "password": "Test-Passw0rd!1", "role": "member"},
    )
    assert created.status in (200, 201), f"add user failed: {created.status} {created.text()}"

    listing = page.request.get("/org/users")
    assert listing.status == 200 and email in listing.text(), "added user not listed"

    body = created.json()
    new_id = body.get("id") or body.get("user", {}).get("id")
    assert new_id, f"no id in add-user response: {created.text()}"

    removed = page.request.delete(f"/org/users/{new_id}", headers=csrf_headers(page))
    assert removed.status in (200, 204), f"remove user failed: {removed.status} {removed.text()}"

    # Removal is a soft-delete by design (org_routes: "admin only, soft delete"), and the
    # roster deliberately lists inactive users (list_users_for_org active_only=False), so
    # the user is deactivated, not gone. Assert the deactivation, not disappearance.
    after = page.request.get("/org/users").json()
    removed_user = next((u for u in after["users"] if u["id"] == new_id), None)
    assert removed_user is not None, "user vanished — expected a soft-delete, not a hard one"
    assert removed_user["is_active"] is False, "deleted user is still active"


def test_member_cannot_add_users(logged_in_page):
    """The session user is a plain member — creating users must be refused (403)."""
    page = logged_in_page
    resp = page.request.post(
        "/org/users",
        headers=csrf_headers(page),
        data={"email": f"nope-{uuid.uuid4().hex[:6]}@example.test", "password": "x", "role": "member"},
    )
    assert resp.status in (401, 403), f"a member was allowed to add a user: {resp.status}"
