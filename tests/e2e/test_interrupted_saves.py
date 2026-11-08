"""GL-U03: receiving stock and saving evidence lose nothing when the save is interrupted.

A save can fail three ways: the connection is down, the session has ended, or the server saved it
but the reply never arrived. In each the form stays as typed and nothing claims it saved; pressing
Save again then adds one record, never two (Idempotency-Key, app/core/backend/idempotency.py).
"""

from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import attach_probe, login_through_ui

pytestmark = pytest.mark.e2e


def _break(page: Page, pattern: str, how: str) -> None:
    """Make the next POST to ``pattern`` fail: offline, signed out, or saved with the reply lost."""

    def handler(route):
        if route.request.method != "POST":
            return route.continue_()
        if how == "offline":
            return route.abort("internetdisconnected")
        if how == "signed-out":
            return route.fulfill(status=401, content_type="application/json", body='{"error": "Session expired"}')
        route.fetch()  # the server saves it...
        return route.abort("connectionreset")  # ...and the reply never arrives

    page.route(pattern, handler)


# --- receiving stock --------------------------------------------------------------------------


def _fill_receipt(page: Page, name: str) -> None:
    page.goto("/core/inventory/add/manual")
    expect(page.locator("#add-inventory-name")).to_be_visible()
    page.wait_for_load_state("networkidle")  # as test_inventory_flow: the page's script is bound
    page.locator("#add-inventory-name").fill(name)
    page.locator("#add-inventory-quantity").fill("12.5")
    page.locator("#add-inventory-unit").select_option("kg")


def _items_named(page: Page, name: str) -> int:
    listing = page.request.get("/api/core/inventory").json()
    items = listing.get("inventory_items", listing) if isinstance(listing, dict) else listing
    return sum(1 for i in items if i.get("name") == name)


@pytest.mark.parametrize("how", ["offline", "signed-out", "reply-lost"])
def test_an_interrupted_receipt_keeps_the_form_and_a_retry_adds_it_once(logged_in_page: Page, how):
    page = logged_in_page
    name = f"Juniper {uuid.uuid4().hex[:8]}"
    _fill_receipt(page, name)
    _break(page, "**/api/core/inventory", how)
    page.locator("#add-inv-manual-submit-btn").click()

    page.wait_for_timeout(800)
    assert page.url.endswith("/core/inventory/add/manual"), "a failed save must not move on as if saved"
    expect(page.locator("#add-inventory-name")).to_have_value(name)
    expect(page.locator("#add-inventory-quantity")).to_have_value("12.5")
    assert _items_named(page, name) == (1 if how == "reply-lost" else 0)

    page.unroute("**/api/core/inventory")
    page.locator("#add-inv-manual-submit-btn").click()
    page.wait_for_url(re.compile(r"/core$"), timeout=15_000)
    assert _items_named(page, name) == 1, "the retry must not add the stock a second time"


# --- evidence (Customs records) ---------------------------------------------------------------


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
    db.add(ComplianceProfile(org_id=org_id, enabled=True, settings={"alcohol_product_types": ["spirits"]}))
    db.commit()
    return user


def _records(page: Page) -> list:
    return page.request.get("/api/compliant/records?framework=customs-alcohol").json().get("records", [])


@pytest.mark.parametrize("how", ["offline", "reply-lost"])
def test_interrupted_evidence_keeps_the_form_and_a_retry_saves_it_once(browser, app_url, compliance_user, how):
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, compliance_user["email"], compliance_user["password"])
    page.goto("/compliant/nz-alcohol/customs/records/record-retention")
    page.locator("[data-customs-record-check-root][aria-busy='false']").wait_for()
    ref = page.locator("#rec-record-retention-ref")
    ref.fill("Drive / Customs / Retention policy")
    _break(page, "**/api/compliant/records", how)
    page.get_by_role("button", name="Save evidence").click()

    expect(page.locator("[data-compliant-error]")).to_be_visible()
    expect(ref).to_have_value("Drive / Customs / Retention policy")
    assert len(_records(page)) == (1 if how == "reply-lost" else 0)

    page.unroute("**/api/compliant/records")
    page.get_by_role("button", name="Save evidence").click()
    expect(page.locator(".customs-rec-row")).to_have_count(1)
    assert len(_records(page)) == 1, "the retry must not add the evidence a second time"
    context.close()
