"""Compliance overview: honest evidence labels, next actions and three review concepts."""

import re
from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e


@pytest.fixture
def compliance_page(browser, app_url, fresh_user, db):
    user = fresh_user(UserRole.ADMIN)
    FeatureSubscriptionRepository(db).grant(UUID(user["org_id"]), "compliant")
    db.commit()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    login_through_ui(page, user["email"], user["password"])
    saved = page.request.put(
        "/api/compliant/profile",
        headers=csrf_headers(page),
        data={"enabled": True, "settings": {"food_control_programme": "np2", "alcohol_product_types": ["spirits"]}},
    )
    assert saved.ok, saved.text()
    yield page
    context.close()


def _open(page, style=1):
    page.goto(f"/compliant/nz-alcohol?style={style}")
    expect(page.locator("[data-compliant-root]")).to_have_attribute("aria-busy", "false")


def test_setup_checks_are_visible_in_readiness(compliance_page):
    page = compliance_page
    overview = page.request.get("/api/compliant/overview").json()
    attention = sum(f["summary_health"]["needs_attention"] for f in overview["frameworks"])
    assert attention > 0, "fixture must include checks still being set up"
    _open(page)
    expect(page.get_by_role("region", name="Evidence readiness", exact=True)).to_contain_text(f"{attention} to review")


def test_customs_and_np2_have_honest_evidence_labels(compliance_page):
    page = compliance_page
    _open(page)
    customs = page.get_by_role("article").filter(has=page.get_by_role("heading", name="Customs alcohol reconciliation"))
    expect(customs).not_to_contain_text("NP3")
    expect(customs).not_to_contain_text("Compliance score")
    expect(page.get_by_role("link", name="Open NP2", exact=True)).to_be_visible()


# CONCEPT ONLY: removed with the chooser after the founder selects one layout.
@pytest.mark.parametrize("style", [1, 2, 3])
@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_concepts_keep_evidence_and_actions_reachable(compliance_page, style, width):
    page = compliance_page
    page.set_viewport_size({"width": width, "height": 1080})
    _open(page, style)
    expect(page.get_by_role("region", name="Evidence readiness", exact=True)).to_be_visible()
    expect(page.get_by_role("region", name="Next action", exact=True)).to_be_visible()
    obligations = page.get_by_role("region", name="Your obligations", exact=True)
    expect(obligations.get_by_role("article")).to_have_count(2)
    expect(page.get_by_role("link", name="Open NP2", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="Open Customs", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    if style == 2 and width >= 1280:
        readiness = page.get_by_role("region", name="Evidence readiness", exact=True).bounding_box()
        actions = page.get_by_role("region", name="Next action", exact=True).bounding_box()
        assert readiness["y"] == actions["y"]
        assert readiness["x"] + readiness["width"] < actions["x"]
        assert round(readiness["height"]) == round(actions["height"])
    if style == 3:
        customs = page.get_by_role("article").filter(
            has=page.get_by_role("heading", name="Customs alcohol reconciliation")
        )
        expect(customs.get_by_text("Evidence coverage", exact=True)).not_to_be_visible()
        customs.locator("summary").focus()
        page.keyboard.press("Enter")
        expect(customs.get_by_text("Evidence coverage", exact=True)).to_be_visible()
        customs.locator("summary").focus()
        page.keyboard.press("Enter")
        expect(customs.get_by_text("Evidence coverage", exact=True)).not_to_be_visible()


def test_all_returned_actions_expand_and_primary_opens_mapping(compliance_page):
    page = compliance_page
    overview = page.request.get("/api/compliant/overview").json()
    _open(page)
    actions = page.get_by_role("region", name="Next action", exact=True)
    expect(actions.get_by_role("heading", level=3)).to_have_text(overview["priority_actions"][0]["title"])
    expect(actions.get_by_role("link", name="Map products", exact=True)).to_have_attribute(
        "href", "/compliant/nz-alcohol/configuration"
    )
    page.locator("[data-more-actions] > summary").click()
    expect(page.locator("[data-priority-actions] > li")).to_have_count(len(overview["priority_actions"]) - 1)
    for action in overview["priority_actions"][1:]:
        expect(actions.get_by_role("link", name=action["title"], exact=True)).to_be_visible()
    page.locator("[data-more-actions] > summary").click()
    expect(page.locator("[data-priority-actions]")).not_to_be_visible()
    actions.get_by_role("link", name="Map products", exact=True).click()
    expect(page).to_have_url(re.compile("/configuration$"))


def test_concept_switch_remembers_choice_and_survives_boosted_return(compliance_page):
    page = compliance_page
    _open(page)
    page.evaluate('window.complianceRoundTrip = "same window"')
    page.get_by_role("button", name="2 · Board", exact=True).click()
    expect(page.get_by_role("button", name="2 · Board", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page).to_have_url(re.compile(r"\?style=2$"))
    from tests.e2e.test_boosted_navigation import _BOOSTED_CLICK_JS

    page.evaluate(_BOOSTED_CLICK_JS, "/core/suppliers")
    page.wait_for_function("window.__boostSettled === true")
    page.evaluate(_BOOSTED_CLICK_JS, "/compliant/nz-alcohol")
    page.wait_for_function("window.__boostSettled === true")
    expect(page.locator("[data-compliant-root]")).to_have_attribute("aria-busy", "false")
    expect(page.get_by_role("button", name="2 · Board", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_role("article")).to_have_count(2)
    assert page.evaluate("window.complianceRoundTrip") == "same window", (
        "must exercise boosted swaps, not full navigation"
    )
    _open(page, 3)
    expect(page.get_by_role("button", name="3 · Register", exact=True)).to_have_attribute("aria-pressed", "true")


def test_failed_load_has_no_success_totals_and_retry_recovers(compliance_page):
    page = compliance_page
    page.route("**/api/compliant/overview", lambda route: route.fulfill(status=503, json={"error": "Unavailable"}))
    _open(page)
    expect(page.get_by_role("alert")).to_contain_text("Readiness could not load")
    expect(page.get_by_role("region", name="Evidence readiness", exact=True)).to_contain_text(
        "Evidence status unavailable"
    )
    expect(page.locator("[data-ready]")).to_have_text("—")
    expect(page.get_by_role("region", name="Next action", exact=True)).to_contain_text("Next steps are unavailable")
    page.unroute("**/api/compliant/overview")
    page.get_by_role("button", name="Try again", exact=True).click()
    expect(page.get_by_role("alert")).not_to_be_visible()
    expect(page.get_by_role("article")).to_have_count(2)
    expect(page.locator("[data-ready]")).not_to_have_text("—")


def test_setup_and_quiet_states_do_not_invent_assurance(compliance_page):
    page = compliance_page
    page.route(
        "**/api/compliant/overview",
        lambda route: route.fulfill(json={"frameworks": [], "priority_actions": [], "evidence_readiness": {}}),
    )
    _open(page)
    expect(page.get_by_role("heading", name="Make this workspace yours")).to_be_visible()
    expect(page.get_by_role("link", name="Configure Compliance", exact=True)).to_have_attribute(
        "href", "/compliant/nz-alcohol/configuration"
    )
    expect(page.locator("[data-attention]")).to_have_text("—")
    expect(page.get_by_text("All checks have current evidence", exact=True)).not_to_be_visible()
    page.unroute("**/api/compliant/overview")
    response = page.request.get("/api/compliant/overview").json()
    response["priority_actions"] = []
    page.route("**/api/compliant/overview", lambda route: route.fulfill(json=response))
    _open(page)
    expect(page.get_by_role("heading", name="No next steps suggested")).to_be_visible()
    expect(page.get_by_role("region", name="Next action", exact=True)).to_contain_text(
        "Evidence status and dates still need your regular review"
    )
    expect(page.locator("[data-more-actions]")).not_to_be_visible()


@pytest.mark.parametrize("status", [401, 403])
def test_access_errors_offer_sign_in_or_admin_instead_of_retry(compliance_page, status):
    page = compliance_page
    page.route("**/api/compliant/overview", lambda route: route.fulfill(status=status, json={"error": "Unavailable"}))
    _open(page)
    expect(page.get_by_role("button", name="Try again", exact=True)).not_to_be_visible()
    if status == 401:
        expect(page.get_by_role("alert")).to_contain_text("Your session has ended")
        expect(page.get_by_role("link", name="Sign in", exact=True)).to_have_attribute("href", "/")
    else:
        expect(page.get_by_role("alert")).to_contain_text("Ask your organisation admin")
        expect(page.get_by_role("link", name="Sign in", exact=True)).not_to_be_visible()


def test_np2_and_customs_links_boot_their_destination_scripts(compliance_page):
    page = compliance_page
    _open(page)
    page.get_by_role("link", name="Open NP2", exact=True).click()
    expect(page.locator("[data-np3-audit-root]")).to_have_attribute("aria-busy", "false")
    expect(page.locator("[data-np3-categories]")).not_to_be_empty()
    _open(page)
    page.get_by_role("link", name="Open Customs", exact=True).click()
    expect(page.locator("[data-compliant-root]")).to_have_attribute("aria-busy", "false")
    expect(page.locator("[data-control-select] option")).not_to_have_count(0)


def test_non_manager_has_no_configuration_action(browser, app_url, fresh_user, db):
    user = fresh_user(UserRole.MEMBER)
    org_id = UUID(user["org_id"])
    FeatureSubscriptionRepository(db).grant(org_id, "compliant")
    from app.features.compliant.models import ComplianceProfile

    db.add(
        ComplianceProfile(
            org_id=org_id,
            enabled=True,
            settings={"food_control_programme": "np1", "alcohol_product_types": ["spirits"]},
        )
    )
    db.commit()
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    try:
        page = context.new_page()
        login_through_ui(page, user["email"], user["password"])
        _open(page)
        expect(page.get_by_role("region", name="Next action", exact=True)).to_contain_text(
            "Ask your organisation admin"
        )
        expect(page.get_by_role("link", name="Map products", exact=True)).not_to_be_visible()
        expect(page.get_by_role("link", name="Open NP1", exact=True)).to_be_visible()
        expect(page.get_by_role("link", name="Configuration", exact=True)).not_to_be_visible()
    finally:
        context.close()


def test_data_coverage_keeps_live_gaps_and_sources_accessible(compliance_page):
    page = compliance_page
    response = page.request.get("/api/compliant/overview").json()
    response["data_coverage"].update(unresolved_live_data_gaps=3, manual_evidence_records=7)
    page.route("**/api/compliant/overview", lambda route: route.fulfill(json=response))
    _open(page)
    page.get_by_text("Data coverage · 3 live-data gaps", exact=True).click()
    expect(page.locator("[data-data-facts]")).to_contain_text("Manual evidence records7")
    expect(page.locator("[data-data-scope]")).to_have_text(response["data_coverage"]["scope"])
