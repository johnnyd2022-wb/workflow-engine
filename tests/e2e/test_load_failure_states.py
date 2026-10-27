"""GL-U04: when a page's data fails to load, it says so, rather than spinning or looking empty.

Each page here had one of two faults when its API answered 500: a "Loading…" line left beside the
error for good, or no error at all and an empty state that read as "nothing to see" (no
notifications, no stock). Every API call is answered with a 500 and the page is checked for
both.
"""

from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import login_through_ui

pytestmark = pytest.mark.e2e

FAILED = '{"error": "The server could not answer"}'
STILL_LOADING = re.compile(r"^\s*Loading(…|\.\.\.|\s+\w+…)\s*$", re.I)


@pytest.fixture()
def compliance_user(fresh_user):
    from app.core.db import db_session
    from app.core.db.models.user import UserRole
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.compliant.models import ComplianceProfile

    user = fresh_user(UserRole.ADMIN)
    org_id = uuid.UUID(user["org_id"])
    db = db_session()
    FeatureSubscriptionRepository(db).grant(org_id, "compliant")
    settings = {"alcohol_product_types": ["spirits"], "food_control_programme": "np3"}
    db.add(ComplianceProfile(org_id=org_id, enabled=True, settings=settings))
    db.commit()
    return user


@pytest.fixture()
def failing_page(browser, app_url, compliance_user):
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    login_through_ui(page, compliance_user["email"], compliance_user["password"])
    yield page
    context.close()


def _visit_with_api_down(page: Page, path: str) -> None:
    page.route(
        re.compile(r"/api/"), lambda route: route.fulfill(status=500, content_type="application/json", body=FAILED)
    )
    page.goto(path)
    page.wait_for_timeout(1500)  # every request has failed by now; nothing is left to arrive


def _loading_lines(page: Page) -> list[str]:
    texts = page.locator("#page-content :is(p, h2, div, span)").evaluate_all(
        "nodes => nodes.filter(n => n.offsetParent && n.children.length === 0).map(n => n.textContent)"
    )
    return [t.strip() for t in texts if STILL_LOADING.match(t)]


@pytest.mark.parametrize(
    "path",
    [
        "/compliant/nz-alcohol/customs",
        "/compliant/nz-alcohol/customs/records",
        "/compliant/nz-alcohol/customs/settings",
        "/compliant/nz-alcohol/customs/transfers",
        "/compliant/nz-alcohol/np3-audit",
        "/core/go-live",
        "/core/site-transfers",
    ],
)
def test_a_failed_load_shows_the_error_and_leaves_nothing_loading(failing_page: Page, path):
    _visit_with_api_down(failing_page, path)
    assert _loading_lines(failing_page) == []
    expect(failing_page.locator("#page-content").get_by_text("The server could not answer").first).to_be_visible()


def test_notifications_that_failed_to_load_do_not_say_all_is_clear(failing_page: Page):
    _visit_with_api_down(failing_page, "/core/notifications")
    content = failing_page.locator("#page-content")
    expect(content.get_by_text("Couldn't load notifications")).to_be_visible()
    expect(content.get_by_text("No system notifications right now")).to_have_count(0)


def test_stock_that_failed_to_load_is_not_shown_as_no_stock(failing_page: Page):
    _visit_with_api_down(failing_page, "/core/sourcemap")
    content = failing_page.locator("#page-content")
    expect(content.get_by_text("Failed to load data")).to_be_visible()
    expect(content.get_by_text("No inventory items found")).to_have_count(0)


def test_a_new_orgs_notifications_carry_no_unknown_date(browser, app_url, compliance_user):
    # A new compliance org's notifications are NP3 checks, which have no date they were raised.
    # Each card said "Unknown" where the date goes; now the date line is left out.
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    try:
        login_through_ui(page, compliance_user["email"], compliance_user["password"])
        page.goto("/core/notifications")
        content = page.locator("#page-content")
        # Its notifications are the programme's checks (the "needs attention" count heads them).
        expect(content.locator(".nt-row", has_text="Add evidence").first).to_be_visible()
        expect(content.get_by_text("Unknown", exact=True)).to_have_count(0)
    finally:
        context.close()
