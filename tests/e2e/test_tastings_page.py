"""Tastings' shared UI, stock accounting journey and concept layout checks."""

import re
import statistics
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect

from tests.e2e import test_perf_budgets as perf
from tests.e2e.conftest import assert_clean_page

pytestmark = pytest.mark.e2e
NZ = ZoneInfo("Pacific/Auckland")


@pytest.fixture(scope="session")
def tasting_world(e2e_user):
    from app.core.db import db_session
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
    from app.features.compliant.models.excise import ExciseRate
    from app.features.compliant.service import ComplianceService
    from app.features.tastings.services import tasting_service
    from tests.factories import InventoryItemFactory

    db = db_session()
    org_id = UUID(str(e2e_user["org_id"]))
    user_id = UUID(str(e2e_user["user_id"]))
    FeatureSubscriptionRepository(db).grant(org_id, "compliant")
    ComplianceService(db).upsert_profile(org_id, {"enabled": True, "industry_module": "nz_alcohol"})
    item = InventoryItemFactory(
        org_id=org_id,
        name="Wildflower tasting gin",
        quantity="30",
        unit="bottles",
        inventory_type="final_product",
        supplier_batch_number="WB-TASTE-01",
        extra_data={"opening_stock": True, "abv_percent": "40"},
    )
    bulk = InventoryItemFactory(
        org_id=org_id,
        name="Bulk tasting gin",
        quantity="20",
        unit="l",
        inventory_type="final_product",
        supplier_batch_number="WB-BULK-01",
        extra_data={"opening_stock": True, "abv_percent": "40"},
    )
    db.add(
        AlcoholProductProfile(
            org_id=org_id,
            inventory_name=item.name,
            product_type="spirits",
            pack_volume_ml=700,
            abv_percent=40,
            customs_product_code="TASTING-UI",
            excise_category="gin",
        )
    )
    db.add(
        ExciseRate(
            org_id=org_id,
            tariff_item="TASTING-UI",
            rate_per_lal="50",
            effective_from=datetime.now(NZ).date().replace(month=1, day=1),
        )
    )
    start = datetime.now(NZ).replace(hour=16, minute=0, second=0, microsecond=0)
    data = {
        "title": "Bottle-store brand tasting",
        "venue_name": "Glengarry Wellington",
        "venue_address": "100 Tasting Road, Wellington",
        "venue_type": "external",
        "licence_reference": "Venue's reference",
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=2)).isoformat(),
        "rep_id": str(user_id),
        "allocations": [{"source_item_id": str(item.id), "quantity": "1"}],
    }
    event = tasting_service.save_event(db, org_id, user_id, data)
    db.commit()
    result = {
        "org_id": str(org_id),
        "rep_id": str(user_id),
        "item_id": str(item.id),
        "bulk_id": str(bulk.id),
        "event_id": str(event.id),
        "data": data,
    }
    db_session.remove()
    return result


def _open(page, style="1"):
    page.goto("/crm/tastings?style=" + style)
    expect(page.locator("[data-tasting-loading]")).to_be_hidden()
    expect(page.locator("[data-tasting-content]")).to_be_visible()
    page.wait_for_load_state("networkidle")


@pytest.mark.parametrize("phone", [False, True])
def test_rep_can_schedule_dispatch_sample_part_of_bottle_and_reuse_remainder(logged_in_page, tasting_world, phone):
    page = logged_in_page
    _open(page)
    if phone:
        page.set_viewport_size({"width": 390, "height": 844})
    title = "Saturday brand visit " + uuid4().hex[:6]
    page.get_by_role("button", name="Schedule a tasting", exact=True).first.click()
    form = page.locator("#tasting-form")
    form.get_by_label("Tasting name").fill(title)
    form.get_by_label("Venue name", exact=True).fill("Regional Wines")
    form.get_by_label("Venue address").fill("50 Example Street, Wellington")
    form.get_by_label("Venue licence reference").fill("Venue reference")
    form.get_by_role("searchbox", name="Find stock", exact=True).fill("Wildflower")
    with page.expect_response(lambda r: "/api/crm/tastings/choices?q=Wildflower" in r.url):
        page.get_by_role("button", name="Find stock", exact=True).click()
    form.get_by_label("Rep", exact=True).select_option(tasting_world["rep_id"])
    page.get_by_role("button", name="Add stock line").click()
    page.get_by_label("Product and batch 1", exact=True).select_option("stock:" + tasting_world["item_id"])
    page.get_by_role("button", name="Save tasting", exact=True).click()
    detail = page.locator("#tasting-detail")
    expect(detail).to_be_visible()
    expect(detail.locator("h2")).to_have_text(title)
    expect(page).to_have_url(re.compile(r"/crm/tastings\?style=1$"))
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/dispatch")
    ) as dispatch_response:
        page.get_by_role("button", name="Confirm stock removal", exact=True).click()
    lot_id = dispatch_response.value.json()["tasting"]["allocations"][0]["stock_lot_id"]
    expect(detail).to_contain_text("Record the outcome")
    detail.get_by_label("Sampled mL · Wildflower tasting gin", exact=True).fill("150")
    detail.get_by_label("Samples served · optional").fill("15")
    detail.get_by_label("Outcome notes · optional").fill("Good response; keep the remaining 550 mL for the next visit.")
    detail.get_by_role("button", name="Complete tasting", exact=True).click()
    expect(detail).to_contain_text("Completed")
    expect(detail).to_contain_text("150 mL sampled")
    page.get_by_role("button", name="Close tasting details").click()
    pool = page.locator('[data-tasting-lot-id="' + lot_id + '"]')
    expect(pool).to_contain_text("Wildflower tasting gin")
    expect(pool).to_contain_text("550 mL")
    pool.get_by_role("button", name="Use at a tasting").click()
    expect(page.locator("#tasting-editor")).to_be_visible()
    expect(page.get_by_label("Product and batch 1", exact=True)).to_have_value(re.compile(r"^pool:"))
    expect(page.locator("#tasting-form")).to_contain_text("Quantity · mL")
    assert_clean_page(page)



def test_fractional_litre_line_keeps_unit_and_identity_after_second_stock_search(logged_in_page, tasting_world):
    page = logged_in_page
    _open(page)
    page.get_by_role("button", name="Schedule a tasting", exact=True).first.click()
    form = page.locator("#tasting-form")
    form.get_by_label("Tasting name").fill("Bulk and bottled tasting")
    form.get_by_label("Venue name", exact=True).fill("Regional Wines")
    form.get_by_label("Venue address").fill("50 Example Street")
    form.get_by_label("Rep", exact=True).select_option(tasting_world["rep_id"])
    page.get_by_role("button", name="Add stock line").click()
    page.get_by_label("Product and batch 1", exact=True).select_option("stock:" + tasting_world["bulk_id"])
    page.get_by_label("Quantity 1", exact=True).fill("0.5")
    form.get_by_role("searchbox", name="Find stock", exact=True).fill("Wildflower")
    with page.expect_response(lambda r: "/api/crm/tastings/choices?q=Wildflower" in r.url):
        page.get_by_role("button", name="Find stock", exact=True).click()
    expect(form.locator(".tasting-stock-line").first).to_contain_text("Quantity · l")
    expect(page.get_by_label("Product and batch 1").locator("option:checked")).to_contain_text("Bulk tasting gin")
    expect(page.get_by_label("Product and batch 1").locator("option:checked")).to_contain_text("WB-BULK-01")
    assert page.get_by_label("Quantity 1", exact=True).evaluate("el => el.checkValidity()")
    page.get_by_role("button", name="Add stock line").click()
    page.get_by_label("Product and batch 2", exact=True).select_option("stock:" + tasting_world["item_id"])
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/api/crm/tastings")) as saved:
        page.get_by_role("button", name="Save tasting", exact=True).click()
    assert saved.value.status == 201
    lines = saved.value.json()["tasting"]["allocations"]
    assert any(line["source_item_id"] == tasting_world["bulk_id"] and float(line["quantity"]) == 0.5 for line in lines)
    expect(page.locator("#tasting-detail")).to_contain_text("Bulk tasting gin")
    assert_clean_page(page)

def test_tasting_is_linked_from_shared_sales_calendar_and_survives_boosted_round_trip(logged_in_page, tasting_world):
    page = logged_in_page
    _open(page)
    page.get_by_role("link", name="Shared calendar", exact=True).click()
    page.wait_for_url("**/crm/tasks?view=week")
    page.get_by_role("button").filter(has_text="Bottle-store brand tasting").first.click()
    page.wait_for_url("**/crm/tastings?tasting_id=*")
    expect(page.locator("#tasting-detail")).to_be_visible()
    expect(page.locator("#tasting-detail-title")).to_have_text("Bottle-store brand tasting")
    page.get_by_role("button", name="Close tasting details").click()
    page.get_by_role("link", name="Shared calendar", exact=True).click()
    page.wait_for_url("**/crm/tasks?view=week")
    # A normal in-app nav back must initialise a new root, not reuse a run-once flag.
    page.get_by_role("tab", name="Tastings", exact=True).click()
    expect(page.locator("[data-tasting-content]")).to_be_visible()
    expect(page.locator("[data-tasting-loading]")).to_be_hidden()
    page.get_by_role("link", name="Shared calendar", exact=True).click()
    page.wait_for_url("**/crm/tasks?view=week")
    page.go_back()
    expect(page.locator("[data-tasting-content]")).to_be_visible()
    page.get_by_role("searchbox", name="Search tastings").fill("Nobody matches this restored search")
    expect(page.locator("[data-tasting-empty]")).to_be_visible()
    page.get_by_role("button", name="Clear filters").click()
    expect(page.locator(".tasting-event").filter(has_text="Bottle-store brand tasting")).to_be_visible()
    assert_clean_page(page)


def test_search_empty_and_clear_preserve_the_event(logged_in_page, tasting_world):
    page = logged_in_page
    _open(page)
    page.get_by_role("searchbox", name="Search tastings").fill("No venue has this unique name")
    expect(page.locator("[data-tasting-empty]")).to_be_visible()
    expect(page.locator("[data-tasting-empty-title]")).to_have_text("No tastings match")
    page.get_by_role("button", name="Clear filters").click()
    expect(page.locator(".tasting-event").filter(has_text="Bottle-store brand tasting")).to_be_visible()
    assert_clean_page(page)


# CONCEPT ONLY: deleted with the two losing layouts after founder selection.
@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width,height", [(390, 844), (1440, 1000), (1920, 1080)])
def test_concept_layouts_fit_phone_laptop_and_wall(logged_in_page, tasting_world, style, width, height):
    page = logged_in_page
    page.set_viewport_size({"width": width, "height": height})
    _open(page, style)
    expect(page.locator("[data-tastings-root]")).to_have_attribute("data-tastings-style", style)
    expect(page.locator("#tasting-events-title")).to_be_visible()
    expect(page.locator("#tasting-pool-title")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "No sideways document scroll"
    assert page.locator("[data-tastings-root]").evaluate("el => el.scrollWidth <= el.clientWidth+1"), (
        "Content must fit its workspace"
    )
    assert_clean_page(page)


def test_invalid_end_time_keeps_the_form_open_and_explains_the_problem(logged_in_page, tasting_world):
    page = logged_in_page
    _open(page)
    before = page.locator(".tasting-event").count()
    page.get_by_role("button", name="Schedule a tasting", exact=True).first.click()
    form = page.locator("#tasting-form")
    form.get_by_label("Tasting name").fill("A visit with an invalid time")
    form.get_by_label("Venue name", exact=True).fill("Bottle store")
    form.get_by_label("Venue address").fill("10 Test Street")
    form.get_by_label("Rep", exact=True).select_option(tasting_world["rep_id"])
    form.get_by_label("Ends · NZ time").fill(form.get_by_label("Starts · NZ time").input_value())
    form.get_by_role("button", name="Save tasting", exact=True).click()
    expect(page.locator("[data-tasting-form-error]")).to_be_visible()
    expect(page.locator("#tasting-editor")).to_be_visible()
    expect(page.locator(".tasting-event")).to_have_count(before)


perf_instrumentation = perf.perf_instrumentation

MEASURE = perf.BUDGETS["feature_measure"]["tastings"]


@pytest.mark.perf
@pytest.mark.parametrize("route", MEASURE["api"])
def test_tastings_api_budget(perf_instrumentation, logged_in_page, tasting_world, route):
    path = route.format(event_id=tasting_world["event_id"])
    start = perf.REGISTRY.count("GET", path)
    for _ in range(perf.WARMUP + perf.API_SAMPLES):
        response = logged_in_page.request.get(path)
        assert response.status == 200, f"Subscribed populated route must be measurable: {path}"
    samples = perf.REGISTRY.since("GET", path, start)[perf.WARMUP :]
    assert len(samples) == perf.API_SAMPLES
    perf._evaluate(
        route,
        "api",
        {
            "backend_ms": statistics.median(row["ms"] for row in samples),
            "queries": max(row["queries"] for row in samples),
        },
    )


@pytest.mark.perf
@pytest.mark.parametrize("route", MEASURE["pages"])
def test_tastings_page_budget(perf_instrumentation, logged_in_page, tasting_world, route):
    page = logged_in_page
    assert page.goto(route).status == 200
    start = perf.REGISTRY.count("GET", route)
    lcps = []
    for _ in range(perf.PAGE_SAMPLES):
        assert page.goto(route).status == 200
        lcps.append(page.evaluate(perf._LCP_JS))
        assert page.locator("[data-tasting-content]").is_visible()
    samples = perf.REGISTRY.since("GET", route, start)
    assert len(samples) == perf.PAGE_SAMPLES
    assert all(value > 0 for value in lcps)
    perf._evaluate(
        route,
        "page",
        {
            "backend_ms": statistics.median(row["ms"] for row in samples),
            "queries": max(row["queries"] for row in samples),
            "lcp_ms": statistics.median(lcps),
        },
    )
