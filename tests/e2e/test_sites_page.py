"""Sites in a browser: switching on, the setup steps, adding a site and a stock area, refusing a
site in the dialog, a failed load, and the page's fit.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui).
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401 -- fixture re-export
from tests.factories import grant_multi_site
from tests.test_crm import db, org  # noqa: F401 -- fixture re-export
from tests.test_crm import user as _member  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

PAGE = "https://crm.test/core/sites"
READY = "[data-sites-root][aria-busy='false']"
SITES = "[data-sites-register] [data-site-id]"


@pytest.fixture()
def user(_member, db):  # noqa: F811
    _member.role = UserRole.ADMIN
    db.commit()
    grant_multi_site(db, _member.org_id)
    return _member


def _open(page, width=1440):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(PAGE)
    page.locator(READY).wait_for()


def _on(client, *names):  # noqa: F811
    assert client.put("/api/core/sites/settings", json={"enabled": True}).status_code == 200
    for name in names:
        assert client.post("/api/core/sites", json={"name": name, "kind": "storage"}).status_code == 201


def test_switching_on_lists_the_default_site_and_what_is_left(sales_page, client):  # noqa: F811
    _open(sales_page)
    expect(sales_page.locator("[data-sites-register]")).to_be_hidden()
    expect(sales_page.locator("[data-sites-intro]")).to_contain_text("Switch on to keep stock")
    sales_page.get_by_role("button", name="Switch on").click()
    expect(sales_page.locator(SITES)).to_have_count(1)
    expect(sales_page.locator(SITES).first).to_contain_text("Default")
    # One site is not yet several: the first step is still to do and says what to add.
    steps = sales_page.locator("[data-sites-steps] [data-step]")
    expect(steps.first).to_contain_text("Add your other sites")
    expect(steps.first).not_to_have_class(re.compile(r"st-step--done"))
    expect(sales_page.get_by_role("button", name="Add a site").first).to_be_visible()


def test_adding_a_stock_area_shows_it_on_the_site(sales_page, client):  # noqa: F811
    _on(client, "Bond store")
    _open(sales_page)
    sales_page.get_by_role("button", name="Add an area: Bond store").click()
    dialog = sales_page.get_by_role("dialog", name="Add a stock area at Bond store")
    dialog.get_by_label("Name").fill("Tank bay")
    dialog.get_by_role("button", name="Add area").click()
    expect(dialog).to_be_hidden()
    card = sales_page.locator(SITES, has_text="Bond store")
    expect(card.locator(".st-area")).to_have_text(["Tank bay"])
    expect(sales_page.locator("[data-sites-message]")).to_contain_text("Tank bay added at Bond store.")


def test_an_area_name_used_at_another_site_says_where(sales_page, client):  # noqa: F811
    _on(client, "Bond store", "Cellar door")
    sites = {s["name"]: s["id"] for s in client.get("/api/core/sites").get_json()["sites"]}
    made = client.post("/api/core/stock-locations", json={"name": "Dry store", "site_id": sites["Bond store"]})
    assert made.status_code == 201
    _open(sales_page)
    sales_page.get_by_role("button", name="Add an area: Cellar door").click()
    dialog = sales_page.get_by_role("dialog", name="Add a stock area at Cellar door")
    dialog.get_by_label("Name").fill("Dry store")
    dialog.get_by_role("button", name="Add area").click()
    expect(dialog.locator("[data-area-error]")).to_have_text(
        "Bond store already has an area called Dry store. Give this one a name of its own, such as Dry store (Cellar door)."
    )


def test_a_refused_site_keeps_its_reason_in_the_dialog(sales_page, client):  # noqa: F811
    _on(client, "Bond store")
    _open(sales_page)
    sales_page.get_by_role("button", name="Add a site").first.click()
    dialog = sales_page.get_by_role("dialog", name="Add a site")
    dialog.get_by_label("Name").fill("Bond store")
    dialog.get_by_role("button", name="Add site").click()
    expect(dialog.locator("[data-site-error]")).to_have_text("A site with that name already exists")
    expect(dialog).to_be_visible()


def test_sites_that_did_not_load_leave_nothing_to_act_on(sales_page):  # noqa: F811
    sales_page.route(
        "**/api/core/sites", lambda route: route.fulfill(status=503, json={"error": "Sites could not load."})
    )
    _open(sales_page)
    expect(sales_page.get_by_role("alert")).to_contain_text("Sites could not load.")
    expect(sales_page.locator("[data-sites-intro]")).to_be_hidden()
    expect(sales_page.locator("[data-sites-body]")).to_be_hidden()
    sales_page.unroute("**/api/core/sites")
    sales_page.get_by_role("button", name="Try again").click()
    expect(sales_page.get_by_role("button", name="Switch on")).to_be_visible()


@pytest.mark.parametrize("width", [390, 1440, 1920], ids=["phone", "laptop", "wall"])
def test_the_page_fits_without_sideways_scroll(sales_page, client, width):  # noqa: F811
    _on(client, "Bond store", "Cellar door")
    _open(sales_page, width=width)
    assert sales_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(sales_page.locator(SITES)).to_have_count(3)
    expect(sales_page.locator("[data-sites-foot]")).to_be_visible()
