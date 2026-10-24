"""Sites in a browser: switching on, adding and refusing a site in the dialog, saying truthfully
whether other sites can record work, a failed load, and (CONCEPT ONLY) each layout's fit.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org  # noqa: F401 -- fixture re-export
from tests.test_crm import user as _member  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

PAGE = "https://crm.test/core/sites"
READY = "[data-sites-root][aria-busy='false']"


@pytest.fixture()
def user(_member, db):  # noqa: F811
    _member.role = UserRole.ADMIN
    db.commit()
    return _member


def _open(page, style="1", width=1440):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{PAGE}?style={style}")
    page.locator(READY).wait_for()


def _on(client, *names):  # noqa: F811
    assert client.put("/api/core/sites/settings", json={"enabled": True}).status_code == 200
    for name in names:
        assert client.post("/api/core/sites", json={"name": name, "kind": "storage"}).status_code == 201


def test_switching_on_lists_the_default_site(sales_page, client):  # noqa: F811
    _open(sales_page)
    expect(sales_page.locator("[data-sites-register]")).to_be_hidden()
    sales_page.get_by_role("button", name="Switch on").click()
    sites = sales_page.locator("[data-sites-list] .st-site")
    expect(sites).to_have_count(1)
    expect(sites.first).to_contain_text("Default")
    expect(sales_page.get_by_role("button", name="Add a site").first).to_be_visible()


def test_a_refused_site_keeps_its_reason_in_the_dialog(sales_page, client):  # noqa: F811
    _on(client, "Bond store")
    _open(sales_page)
    sales_page.get_by_role("button", name="Add a site").first.click()
    dialog = sales_page.get_by_role("dialog", name="Add a site")
    dialog.get_by_label("Name").fill("Bond store")
    dialog.get_by_role("button", name="Add site").click()
    expect(dialog.locator("[data-site-error]")).to_have_text("A site with that name already exists")
    expect(dialog).to_be_visible()


def test_the_page_says_whether_other_sites_can_record_work(sales_page, client, org, db):  # noqa: F811
    # It always said recording at other sites "will become available", even once it was on.
    _on(client)
    _open(sales_page)
    expect(sales_page.locator("[data-sites-state]")).to_contain_text("stay at the default site")
    from app.core.db.models.organisation import Organisation

    db.query(Organisation).filter(Organisation.id == org.id).update(
        {Organisation.multiple_site_operations_enabled: True}
    )
    db.commit()
    _open(sales_page)
    expect(sales_page.locator("[data-sites-state]")).to_contain_text("can be recorded at any active site")


def test_sites_that_did_not_load_leave_nothing_to_act_on(sales_page):  # noqa: F811
    sales_page.route(
        "**/api/core/sites", lambda route: route.fulfill(status=503, json={"error": "Sites could not load."})
    )
    _open(sales_page)
    expect(sales_page.get_by_role("alert")).to_contain_text("Sites could not load.")
    expect(sales_page.locator("[data-sites-switch]")).to_be_hidden()
    sales_page.unroute("**/api/core/sites")
    sales_page.get_by_role("button", name="Try again").click()
    expect(sales_page.get_by_role("button", name="Switch on")).to_be_visible()


# CONCEPT ONLY: the rest are deleted with the two layouts not picked.
def test_edit_in_place_saves_the_row(sales_page, client):  # noqa: F811
    _on(client, "Bond store")
    _open(sales_page, style="3")
    sales_page.get_by_role("button", name="Edit: Bond store").click()
    row = sales_page.locator(".st-site.is-editing")
    row.get_by_label("Address").fill("12 Seaview Road")
    row.get_by_role("button", name="Save").click()
    expect(sales_page.locator(".st-site", has_text="Bond store")).to_contain_text("12 Seaview Road")
    expect(sales_page.locator(".st-site.is-editing")).to_have_count(0)


@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width", [390, 1440, 1920], ids=["phone", "laptop", "wall"])
def test_each_layout_fits_without_sideways_scroll(sales_page, client, style, width):  # noqa: F811
    _on(client, "Bond store", "Cellar door")
    _open(sales_page, style=style, width=width)
    assert sales_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(sales_page.locator("[data-sites-list] .st-site")).to_have_count(3)
