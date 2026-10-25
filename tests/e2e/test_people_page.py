"""People and roles in a browser: a failed load leaves nothing to act on, custom roles open in a
dialog and delete only when asked twice, and the page's fit.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from app.core.db.models.org_role import OrgRole
from app.core.db.models.user import UserRole
from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org  # noqa: F401 -- fixture re-export
from tests.test_crm import user as _member  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

PAGE = "https://crm.test/core/people"
READY = "[data-people-root][aria-busy='false']"


@pytest.fixture()
def user(_member, db):  # noqa: F811
    _member.role = UserRole.ADMIN
    db.commit()
    return _member


@pytest.fixture()
def cellar(db, org):  # noqa: F811
    role = OrgRole(
        org_id=org.id, name="Cellar door", base_role="sales", permissions=["sales.view"], site_access_mode="all"
    )
    db.add(role)
    db.commit()
    return role


def _open(page, width=1440, hash_=""):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{PAGE}{hash_}")
    page.locator(READY).wait_for()


def test_people_that_did_not_load_leave_nothing_to_act_on(sales_page):  # noqa: F811
    # A failed load left an empty list and a role list stuck on "Loading…".
    sales_page.route("**/org/users", lambda route: route.fulfill(status=503, json={"error": "People could not load."}))
    _open(sales_page)
    expect(sales_page.get_by_role("alert")).to_contain_text("People could not load.")
    expect(sales_page.locator("#people")).to_be_hidden()
    expect(sales_page.locator("#roles")).to_be_hidden()
    sales_page.unroute("**/org/users")
    sales_page.get_by_role("button", name="Try again").click()
    expect(sales_page.locator("#people")).to_be_visible()
    expect(sales_page.locator("[data-people-summary]")).to_have_text("1 person can sign in")


def test_a_custom_role_is_edited_in_a_dialog(sales_page, cellar, client):  # noqa: F811
    _open(sales_page)
    sales_page.get_by_role("navigation", name="People and roles").get_by_role("link", name="Roles").click()
    roles = sales_page.locator("#roles")
    expect(roles.locator(".pp-role-row")).to_have_count(7)
    roles.get_by_role("button", name="Edit Cellar door").click()
    dialog = sales_page.get_by_role("dialog", name="Edit Cellar door")
    expect(dialog.get_by_label("See customers, invoices and revenue")).to_be_checked()
    dialog.get_by_label("See stock on hand, suppliers and traceability").check()
    dialog.get_by_role("button", name="Save role").click()
    expect(dialog).to_be_hidden()
    expect(roles).to_contain_text("2 permissions")
    saved = next(r for r in client.get("/org/roles").get_json()["custom_roles"] if r["name"] == "Cellar door")
    assert sorted(saved["permissions"]) == ["inventory.view", "sales.view"]


def test_deleting_a_role_asks_twice_in_place(sales_page, cellar, client):  # noqa: F811
    # It used window.confirm, which some browsers block.
    _open(sales_page)
    sales_page.get_by_role("navigation", name="People and roles").get_by_role("link", name="Roles").click()
    sales_page.get_by_role("button", name="Edit Cellar door").click()
    delete = sales_page.get_by_role("dialog").locator("[data-role-delete]")
    delete.click()
    expect(delete).to_have_text("Delete Cellar door?")
    assert any(r["name"] == "Cellar door" for r in client.get("/org/roles").get_json()["custom_roles"])
    delete.click()
    expect(sales_page.locator("#roles")).not_to_contain_text("Cellar door")


def test_people_and_roles_show_one_at_a_time(sales_page):  # noqa: F811
    _open(sales_page)
    expect(sales_page.locator("#roles")).to_be_hidden()
    sales_page.get_by_role("navigation", name="People and roles").get_by_role("link", name="Roles").click()
    expect(sales_page.locator("#roles")).to_be_visible()
    expect(sales_page.locator("#people")).to_be_hidden()


@pytest.mark.parametrize("width", [390, 1440, 1920], ids=["phone", "laptop", "wall"])
def test_the_page_fits_without_sideways_scroll(sales_page, cellar, width):  # noqa: F811
    _open(sales_page, width=width)
    assert sales_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(sales_page.locator("#people .pp-person")).to_have_count(1)
