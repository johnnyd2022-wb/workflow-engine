"""Customs → Records: each check Customs can ask about, its proof, and a form that asks only
for what that check needs."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import assert_clean_page, attach_probe, login_through_ui

pytestmark = pytest.mark.e2e

RECORDS = "/compliant/nz-alcohol/customs/records"
READY = "[data-customs-records-root][aria-busy='false']"
CHECK_READY = "[data-customs-record-check-root][aria-busy='false']"


@pytest.fixture()
def customs_org(fresh_user):
    """An org subscribed to Compliance with the NZ Alcohol module on."""
    import uuid

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


def _open(browser, app_url, user, path=RECORDS, ready=READY, viewport=None):
    context = browser.new_context(
        base_url=app_url, ignore_https_errors=True, viewport=viewport or {"width": 1440, "height": 900}
    )
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    page.goto(path)
    page.locator(ready).wait_for()
    return page


def test_records_list_each_customs_check_once_by_its_plain_name(browser, app_url, customs_org):
    page = _open(browser, app_url, customs_org)
    expect(page.locator(".customs-views a[aria-current='page']")).to_have_text("Records")
    checks = page.locator(".customs-rec-check")
    expect(checks).to_have_count(5)
    expect(checks.first).to_contain_text("Products mapped to Customs items")
    expect(page.locator("[data-records-summary]")).to_contain_text("of 5 checks have current proof")
    expect(checks.first).to_have_attribute("href", RECORDS + "/product-mapping")
    assert_clean_page(page)
    page.context.close()


def test_a_checks_form_asks_only_for_what_that_check_needs(browser, app_url, customs_org):
    page = _open(browser, app_url, customs_org, path=RECORDS + "/reconciliation", ready=CHECK_READY)
    form = page.locator(".customs-rec-form")
    # Reconciliation: a period and the litres of alcohol declared, and no Production picker.
    expect(form.locator("#rec-reconciliation-start")).to_be_visible()
    expect(form.locator("#rec-reconciliation-lal")).to_be_visible()
    expect(form.locator(".customs-rec-form__picker")).to_have_count(0)
    page.goto(RECORDS + "/movement-evidence")
    page.locator(CHECK_READY).wait_for()
    # Movement evidence: Production records, and no period or declared LAL.
    expect(page.locator(".customs-rec-form__picker")).to_be_visible()
    expect(page.locator("#rec-movement-evidence-start")).to_have_count(0)
    expect(page.locator("#rec-movement-evidence-lal")).to_have_count(0)
    page.context.close()


def test_saving_evidence_makes_it_the_latest_proof(browser, app_url, customs_org):
    page = _open(browser, app_url, customs_org, path=RECORDS + "/record-retention", ready=CHECK_READY)
    page.locator("#rec-record-retention-ref").fill("Drive / Customs / Retention policy")
    page.get_by_role("button", name="Save evidence").click()
    expect(page.locator(".customs-rec-row").first).to_contain_text("Ref Drive / Customs / Retention policy")
    expect(page.locator(".customs-rec-facts")).to_contain_text("Records kept 7 years, in NZ")
    expect(page.locator(".customs-rec-head .customs-chip")).to_have_text("Current")
    assert_clean_page(page)
    page.context.close()


def test_the_old_evidence_address_opens_records(browser, app_url, customs_org):
    page = _open(browser, app_url, customs_org, path="/compliant/nz-alcohol/evidence")
    expect(page).to_have_url(f"{app_url}{RECORDS}")
    page.context.close()


@pytest.mark.parametrize("path", [RECORDS, RECORDS + "/reconciliation"], ids=["records", "check"])
@pytest.mark.parametrize(
    "viewport",
    [{"width": 390, "height": 844}, {"width": 1440, "height": 900}, {"width": 1920, "height": 1080}],
    ids=["phone", "laptop", "wall"],
)
def test_records_and_a_check_fit_without_sideways_scroll(browser, app_url, customs_org, path, viewport):
    ready = READY if path == RECORDS else CHECK_READY
    page = _open(browser, app_url, customs_org, path=path, ready=ready, viewport=viewport)
    if path == RECORDS:
        expect(page.locator(".customs-rec-check")).to_have_count(5)
    else:
        expect(page.locator(".customs-rec-form")).to_be_visible()
    overflow = page.evaluate("() => document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth")
    assert overflow <= 1, f"{path} scrolls sideways by {overflow}px at {viewport['width']}px"
    page.context.close()
