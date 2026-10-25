"""Plan 2.5 in a browser: Settings has one tab row, and the sidebar lights Settings on its pages.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui), so no live
server is needed.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org  # noqa: F401 -- fixture re-export
from tests.test_crm import user as _member  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

HOST = "https://crm.test"
TABS = ["Account", "People", "Sites", "Integrations", "Tasks"]


@pytest.fixture()
def user(_member, db):  # noqa: F811
    # People and Sites are for admins.
    _member.role = UserRole.ADMIN
    db.commit()
    return _member


def _active_sidebar(page):
    return page.locator("#sidebar a.nav-link.active .nav-link-text")


@pytest.mark.parametrize("path", ["/core/people", "/core/sites", "/core/tasks/configuration", "/core/integrations"])
def test_a_settings_page_lights_settings_in_the_sidebar(sales_page, path):  # noqa: F811
    # The sidebar script picked the longest URL prefix, and /core/people starts with Production's /core.
    sales_page.goto(HOST + path)
    sales_page.wait_for_load_state("networkidle")
    expect(_active_sidebar(sales_page)).to_have_text(["Settings"])


def test_the_sidebar_follows_a_boosted_move_into_settings(sales_page):  # noqa: F811
    sales_page.goto(HOST + "/core/settings")
    sales_page.get_by_role("tab", name="People").click()
    expect(sales_page).to_have_url(HOST + "/core/people")
    expect(_active_sidebar(sales_page)).to_have_text(["Settings"])


def test_settings_pages_share_one_tab_row(sales_page):  # noqa: F811
    for path, current in [("/core/settings", "Account"), ("/core/people", "People"), ("/core/sites", "Sites")]:
        sales_page.goto(HOST + path)
        row = sales_page.get_by_role("tablist", name="Settings pages")
        expect(row.get_by_role("tab")).to_have_text(TABS)
        expect(row.get_by_role("tab", selected=True)).to_have_text(current)
        # The row says where you are, so there is no breadcrumb as well.
        expect(sales_page.locator("nav.breadcrumbs, [data-breadcrumbs]")).to_have_count(0)


def test_integrations_is_its_own_page_under_settings(sales_page):  # noqa: F811
    # It used to redirect into Sales settings whenever Sales was on.
    sales_page.goto(HOST + "/core/integrations")
    expect(sales_page).to_have_url(HOST + "/core/integrations")
    expect(sales_page.get_by_role("tablist", name="Settings pages").get_by_role("tab", selected=True)).to_have_text(
        "Integrations"
    )
