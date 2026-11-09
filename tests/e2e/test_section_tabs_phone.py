"""The section tab strip on a phone: when its tabs don't fit, the current one is scrolled into
view (never cut to "Task se") and the edges with more tabs past them are marked, which the CSS
fades. UX-SWEEP: Settings has five tabs once multiple sites are on, wider than a 390px phone.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui).
"""

from __future__ import annotations

import pytest

from app.core.db.models.user import UserRole
from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401 -- fixture re-export
from tests.factories import grant_multi_site
from tests.test_crm import db, org  # noqa: F401 -- fixture re-export
from tests.test_crm import user as _member  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

PHONE = {"width": 390, "height": 844}
NAV = "#page-content .section-tabs"


@pytest.fixture()
def user(_member, db):  # noqa: F811
    _member.role = UserRole.ADMIN
    db.commit()
    grant_multi_site(db, _member.org_id)
    return _member


@pytest.fixture()
def sites_on(client):  # noqa: F811
    assert client.put("/api/core/sites/settings", json={"enabled": True}).status_code == 200


def _strip(page, path):
    page.set_viewport_size(PHONE)
    page.goto(f"https://crm.test{path}")
    page.wait_for_load_state("networkidle")
    return page.evaluate(
        """sel => {
          const nav = document.querySelector(sel);
          const tab = nav.querySelector('.flow-mode-segment--active');
          const n = nav.getBoundingClientRect(), t = tab.getBoundingClientRect();
          return {overflows: nav.scrollWidth > nav.clientWidth + 1, label: tab.textContent.trim(),
                  inside: t.left >= n.left - 1 && t.right <= n.right + 1,
                  start: nav.hasAttribute('data-more-start'), end: nav.hasAttribute('data-more-end')};
        }""",
        NAV,
    )


def test_the_last_tab_is_scrolled_into_view_and_the_start_marked(sales_page, sites_on):  # noqa: F811
    strip = _strip(sales_page, "/core/tasks/configuration")
    assert strip["overflows"], "five Settings tabs should not fit at 390px; the test would prove nothing"
    assert strip["label"] == "Task settings"
    assert strip["inside"], "the current tab is cut off at the edge of the strip"
    assert strip["start"] and not strip["end"]


def test_the_first_tab_marks_more_to_the_right(sales_page, sites_on):  # noqa: F811
    strip = _strip(sales_page, "/core/settings")
    assert strip["inside"] and strip["end"] and not strip["start"]


def test_a_strip_that_fits_is_not_faded(sales_page):  # noqa: F811
    sales_page.set_viewport_size({"width": 1440, "height": 900})
    sales_page.goto("https://crm.test/core/settings")
    sales_page.wait_for_load_state("networkidle")
    nav = sales_page.locator(NAV)
    assert nav.get_attribute("data-more-start") is None
    assert nav.get_attribute("data-more-end") is None
