"""NP3 food safety: the register (readiness, needs doing, every check once) and a check's page."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import assert_clean_page, attach_probe, login_through_ui

pytestmark = pytest.mark.e2e

REGISTER = "/compliant/nz-alcohol/food-safety"
CHECK = "/compliant/nz-alcohol/np3-audit/check/"
READY = "[data-np3-audit-root][aria-busy='false']"
CHECK_READY = "[data-np3-check-root][aria-busy='false']"


@pytest.fixture()
def np3_org(fresh_user):
    """An org on NP3 with one review signed off (for a check that sits in two sections) and
    thirteen cleaning log entries."""
    from app.core.db import db_session
    from app.core.db.models.user import UserRole
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.compliant.models import ComplianceProfile
    from app.features.compliant.models.compliance_record import ComplianceRecord
    from app.features.compliant.modules.nz_alcohol.np3_audit import np3_log_template

    user = fresh_user(UserRole.ADMIN)
    org_id, user_id = uuid.UUID(user["org_id"]), uuid.UUID(user["user_id"])
    db = db_session()
    FeatureSubscriptionRepository(db).grant(org_id, "compliant")
    db.add(
        ComplianceProfile(
            org_id=org_id,
            enabled=True,
            settings={"alcohol_product_types": ["spirits"], "food_control_programme": "np3"},
        )
    )
    today = date.today()

    def record(control_id, record_type, title, created, due=None, details=None):
        at = datetime.combine(created, datetime.min.time(), tzinfo=UTC)
        db.add(
            ComplianceRecord(
                org_id=org_id,
                framework_slug="np3-food-control",
                control_id=control_id,
                record_type=record_type,
                status="complete",
                title=title,
                due_date=due,
                period_start=created if record_type != "attestation" else None,
                source_refs=[],
                details=details or {},
                created_by_user_id=user_id,
                created_at=at,
                updated_at=at,
            )
        )

    record(
        "staff-competency",
        "attestation",
        "NP3 review: Staff competency",
        today - timedelta(days=20),
        today + timedelta(days=160),
        {"how_we_meet": "Training matrix reviewed monthly.", "evidence_fields": {}, "attestation_confirmed": True},
    )
    for back in range(13):
        day = today - timedelta(days=3 + back * 7)
        record(
            "cleaning-and-hygiene",
            np3_log_template("cleaning-and-hygiene")["record_type"],
            "NP3 log: Cleaning and sanitising verification log",
            day,
            details={
                "np3_log_type": np3_log_template("cleaning-and-hygiene")["key"],
                "log_fields": {
                    "event_date": day.isoformat(),
                    "area_or_equipment": "Bottling line",
                    "method": "Hot water, then sanitiser",
                    "result": "ok",
                },
            },
        )
    db.commit()
    return user


def _open(browser, app_url, user, path=REGISTER, ready=READY, viewport=None):
    context = browser.new_context(
        base_url=app_url, ignore_https_errors=True, viewport=viewport or {"width": 1440, "height": 900}
    )
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    page.goto(path)
    page.locator(ready).wait_for()
    return page


def _control_ids(page):
    return page.locator("[data-np3-categories] .np3-check").evaluate_all("rows => rows.map(r => r.dataset.controlId)")


def test_the_register_leads_with_readiness_and_what_needs_doing(browser, app_url, np3_org):
    page = _open(browser, app_url, np3_org)
    expect(page.get_by_role("heading", level=1)).to_have_text("NP3 food safety")
    expect(page.locator(".np3-fact")).to_have_count(5)
    expect(page.locator("[data-np3-filter='ok'] .np3-fact__value")).to_contain_text("of")
    expect(page.locator("[data-np3-work-queue]")).to_be_visible()
    expect(page.locator(".np3-section-tab")).to_have_count(5)
    expect(page.locator(".np3-check").first).to_have_attribute("href", CHECK + "registration-scope")
    assert_clean_page(page)
    page.context.close()


def test_a_search_lists_each_check_once(browser, app_url, np3_org):
    """staff-competency sits in two sections; a search used to show it twice."""
    page = _open(browser, app_url, np3_org)
    page.locator("[data-np3-check-search]").fill("compet")
    expect(page.locator("[data-np3-active-category]")).to_have_text("Search results")
    ids = _control_ids(page)
    assert "staff-competency" in ids and len(ids) == len(set(ids)), ids
    page.context.close()


def test_a_readiness_filter_lists_each_check_once(browser, app_url, np3_org):
    page = _open(browser, app_url, np3_org)
    page.locator("[data-np3-filter='attention']").click()
    expect(page.locator("[data-np3-filter='attention']")).to_have_attribute("aria-pressed", "true")
    ids = _control_ids(page)
    assert ids and len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1]
    total = int(page.locator("[data-np3-filter='attention'] .np3-fact__value").inner_text())
    assert len(ids) == total
    page.get_by_role("button", name="Show every check").click()
    expect(page.locator("[data-np3-filter='attention']")).to_have_attribute("aria-pressed", "false")
    page.context.close()


def test_a_check_leads_with_what_the_verifier_asks_and_lists_every_entry(browser, app_url, np3_org):
    page = _open(browser, app_url, np3_org, path=CHECK + "cleaning-and-hygiene", ready=CHECK_READY)
    expect(page.locator(".np3-asks h2")).to_have_text("What your verifier will ask to see")
    expect(page.locator(".np3-asks .np3-evidence-checklist li").first).to_be_visible()
    # Thirteen entries: twelve shown, and the button says how many there are in all.
    entries = page.locator(".np3-entries > li")
    expect(entries).to_have_count(13)
    expect(page.locator(".np3-entries > li:visible")).to_have_count(12)
    page.get_by_role("button", name="Show all 13 entries").click()
    expect(page.locator(".np3-entries > li:visible")).to_have_count(13)
    # Values read back as labels, not stored keys.
    expect(entries.first.locator("dt").first).not_to_have_text("area_or_equipment")
    # Log entries are in the register, not repeated in History.
    expect(page.locator(".np3-history .np3-full-history > li")).to_have_count(0)
    assert_clean_page(page)
    page.context.close()


def test_a_sign_off_shows_its_field_labels_in_history(browser, app_url, np3_org):
    page = _open(browser, app_url, np3_org, path=CHECK + "allergen-management", ready=CHECK_READY)
    form = page.locator(".np3-check-review form")
    form.locator("textarea").fill("Allergen matrix checked against every label before bottling.")
    first = form.locator("input[name]:not([type='file'])").first
    key = first.get_attribute("name")
    first.fill("Quality drive / Allergen matrix v3")
    form.locator(".np3-confirmation input").check()
    form.get_by_role("button", name="Sign off this review").click()
    item = page.locator(".np3-history .np3-full-history > li").first
    expect(item).to_contain_text("Quality drive / Allergen matrix v3")
    expect(item.locator("dt").first).not_to_have_text(key)
    expect(page.locator("[data-np3-check-state]")).to_have_text("Evidence current")
    assert_clean_page(page)
    page.context.close()


def test_only_people_who_manage_compliance_see_the_reminder_setting(browser, app_url, np3_org):
    from app.core.db import db_session
    from app.core.db.models.audit_log import AuditLog
    from app.core.db.models.user import User, UserRole
    from tests.factories import DEFAULT_TEST_PASSWORD, UserFactory

    admin = _open(browser, app_url, np3_org, path=CHECK + "cleaning-and-hygiene", ready=CHECK_READY)
    expect(admin.locator(".np3-check-settings")).to_have_count(1)
    admin.context.close()

    db = db_session()
    member = UserFactory(
        org_id=uuid.UUID(np3_org["org_id"]),
        email=f"e2e-np3-member-{uuid.uuid4().hex[:8]}@example.test",
        role=UserRole.MEMBER,
    )
    db.commit()
    try:
        page = _open(
            browser,
            app_url,
            {"email": member.email, "password": DEFAULT_TEST_PASSWORD},
            path=CHECK + "cleaning-and-hygiene",
            ready=CHECK_READY,
        )
        expect(page.locator(".np3-check-settings")).to_have_count(0)
        page.context.close()
    finally:
        db.rollback()
        db.query(AuditLog).filter(AuditLog.user_id == member.id).delete(synchronize_session=False)
        db.query(User).filter(User.id == member.id).delete(synchronize_session=False)
        db.commit()


# CONCEPT ONLY: the three register styles at each width; deleted with the losing styles.
@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize(
    "viewport",
    [{"width": 390, "height": 844}, {"width": 1440, "height": 900}, {"width": 1920, "height": 1080}],
    ids=["phone", "laptop", "wall"],
)
def test_concept_styles_fit_without_sideways_scroll(browser, app_url, np3_org, style, viewport):
    page = _open(browser, app_url, np3_org, path=REGISTER + f"?style={style}", viewport=viewport)
    expect(page.locator(f'[data-np3-style="{style}"]')).to_have_count(1)
    for region in ("[data-verification-root]", "[data-np3-health-cards]", "[data-np3-categories]"):
        expect(page.locator(region)).to_have_count(1)
    expect(page.locator(".np3-check").first).to_be_visible()
    overflow = page.evaluate("() => document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth")
    assert overflow <= 1, f"style {style} scrolls sideways by {overflow}px at {viewport['width']}px"
    page.context.close()


@pytest.mark.parametrize(
    "viewport", [{"width": 390, "height": 844}, {"width": 1440, "height": 900}], ids=["phone", "laptop"]
)
def test_a_check_page_fits_without_sideways_scroll(browser, app_url, np3_org, viewport):
    page = _open(browser, app_url, np3_org, path=CHECK + "cleaning-and-hygiene", ready=CHECK_READY, viewport=viewport)
    overflow = page.evaluate("() => document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth")
    assert overflow <= 1, f"the check page scrolls sideways by {overflow}px at {viewport['width']}px"
    page.context.close()
