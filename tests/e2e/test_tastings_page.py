"""Tastings' shared UI, typed Tasks workflow, stock accounting and supported layouts."""

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
    view = {"1": "board", "2": "list", "3": "week"}[style]
    page.goto("/crm/tasks?type=tasting&view=" + view)
    expect(page.locator("#tasks-page")).to_have_attribute("aria-busy", "false")
    page.wait_for_load_state("networkidle")


@pytest.mark.parametrize("phone", [False, True])
def test_rep_can_schedule_dispatch_sample_part_of_bottle_and_reuse_remainder(logged_in_page, tasting_world, phone):
    page = logged_in_page
    _open(page)
    if phone:
        page.set_viewport_size({"width": 390, "height": 844})
    title = "Saturday brand visit " + uuid4().hex[:6]
    page.get_by_role("button", name="New task", exact=True).first.click()
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
    expect(page).to_have_url(re.compile(r"/crm/tasks\?type=tasting&view=board$"))
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
    page.get_by_role("button", name="Tasting stock", exact=True).click()
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
    page.get_by_role("button", name="New task", exact=True).first.click()
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
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/api/crm/tasks")) as saved:
        page.get_by_role("button", name="Save tasting", exact=True).click()
    assert saved.value.status == 201
    lines = saved.value.json()["tasting"]["allocations"]
    assert any(line["source_item_id"] == tasting_world["bulk_id"] and float(line["quantity"]) == 0.5 for line in lines)
    expect(page.locator("#tasting-detail")).to_contain_text("Bulk tasting gin")
    assert_clean_page(page)


def test_tasting_is_inline_in_shared_tasks_and_survives_boosted_round_trip(logged_in_page, tasting_world):
    page = logged_in_page
    _open(page, "3")
    page.get_by_role("button").filter(has_text="Bottle-store brand tasting").first.click()
    expect(page.locator("#tasting-detail")).to_be_visible()
    expect(page.locator("#tasting-detail-title")).to_have_text("Bottle-store brand tasting")
    expect(page).to_have_url(re.compile(r"/crm/tasks\?type=tasting&view=week$"))
    page.get_by_role("button", name="Close tasting details").click()
    page.get_by_role("tab", name="Customers", exact=True).click()
    page.wait_for_url("**/crm/customers")
    page.get_by_role("tab", name="Tasks", exact=True).click()
    page.wait_for_url("**/crm/tasks")
    expect(page.locator("#tasks-page")).to_have_attribute("aria-busy", "false")
    # HTMX deliberately disables history cache; each Back forces a document reload.
    for target in ("**/crm/customers", "**/crm/tasks?type=tasting&view=week"):
        page.evaluate("window.__tastingHistoryDocument = true")
        page.go_back(wait_until="commit")
        page.wait_for_url(target, wait_until="commit")
        page.wait_for_function("!window.__tastingHistoryDocument && document.readyState === 'complete'")
    expect(page.locator("#tasks-page")).to_have_attribute("aria-busy", "false")
    page.wait_for_function("!!document.querySelector('#tasks-search')?._x_model")
    page.get_by_role("searchbox", name="Search tasks", exact=True).fill("Nobody matches this restored search")
    expect(page.get_by_text("No open tasks match.")).to_be_visible()
    page.get_by_role("button", name="Clear", exact=True).click()
    page.get_by_role("button").filter(has_text="Bottle-store brand tasting").first.click()
    expect(page.locator("#tasting-detail-title")).to_have_text("Bottle-store brand tasting")
    assert_clean_page(page)


def test_search_empty_and_clear_preserve_the_event(logged_in_page, tasting_world):
    page = logged_in_page
    _open(page)
    page.get_by_role("searchbox", name="Search tasks").fill("No venue has this unique name")
    expect(page.get_by_text("No open tasks match.")).to_be_visible()
    page.get_by_role("button", name="Clear", exact=True).click()
    expect(page.locator(".tasks-card").filter(has_text="Bottle-store brand tasting")).to_be_visible()
    assert_clean_page(page)


@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width,height", [(390, 844), (1440, 1000), (1920, 1080)])
def test_supported_task_views_fit_phone_laptop_and_wall(logged_in_page, tasting_world, style, width, height):
    page = logged_in_page
    page.set_viewport_size({"width": width, "height": height})
    _open(page, style)
    expect(page.locator("#tasks-page")).to_have_attribute("data-tasks-style", style)
    expect(page.get_by_role("combobox", name="Task type filter")).to_have_value("tasting")
    expect(page.get_by_role("button", name="Tasting stock", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "No sideways document scroll"
    assert page.locator("#tasks-page").evaluate("el => el.scrollWidth <= el.clientWidth+1"), "Content fits workspace"
    assert_clean_page(page)


def test_invalid_end_time_keeps_the_form_open_and_explains_the_problem(logged_in_page, tasting_world):
    page = logged_in_page
    _open(page)
    before = page.locator(".tasks-card").count()
    page.get_by_role("button", name="New task", exact=True).first.click()
    form = page.locator("#tasting-form")
    form.get_by_label("Tasting name").fill("A visit with an invalid time")
    form.get_by_label("Venue name", exact=True).fill("Bottle store")
    form.get_by_label("Venue address").fill("10 Test Street")
    form.get_by_label("Rep", exact=True).select_option(tasting_world["rep_id"])
    form.get_by_label("Ends · NZ time").fill(form.get_by_label("Starts · NZ time").input_value())
    form.get_by_role("button", name="Save tasting", exact=True).click()
    expect(page.locator("[data-tasting-form-error]")).to_be_visible()
    expect(page.locator("#tasting-editor")).to_be_visible()
    expect(page.locator(".tasks-card")).to_have_count(before)


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
        expect(page.locator("#tasks-page")).to_have_attribute("aria-busy", "false")
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


def test_task_type_switch_preserves_common_and_specialized_unsaved_fields(logged_in_page, tasting_world):
    page = logged_in_page
    page.goto("/crm/tasks?view=list")
    expect(page.locator("#tasks-page")).to_have_attribute("aria-busy", "false")
    page.get_by_role("button", name="New task", exact=True).first.click()
    page.get_by_label("Title", exact=False).fill("Carry my draft to a tasting")
    page.get_by_label("Due", exact=True).fill("2026-11-06")
    page.get_by_label("Assigned to", exact=True).select_option(tasting_world["rep_id"])
    page.get_by_label("Notes", exact=True).fill("Bring a display")
    page.get_by_label("Type", exact=True).select_option("tasting")
    form = page.locator("#tasting-form")
    expect(form.get_by_label("Tasting name")).to_have_value("Carry my draft to a tasting")
    expect(form.get_by_label("Starts · NZ time")).to_have_value("2026-11-06T17:00")
    expect(form.get_by_label("Rep", exact=True)).to_have_value(tasting_world["rep_id"])
    expect(form.get_by_label("Notes · optional")).to_have_value("Bring a display")
    form.get_by_label("Venue name", exact=True).fill("Retain venue without saving")
    form.get_by_label("Starts · NZ time").fill("2026-11-06T18:30")
    form.get_by_label("Task type", exact=True).select_option("call")
    expect(page.locator("#task-title")).to_have_value("Carry my draft to a tasting")
    expect(page.locator("#task-type")).to_have_value("call")
    page.locator("#task-title").fill("Changed common field")
    page.get_by_label("Type", exact=True).select_option("tasting")
    expect(form.get_by_label("Tasting name")).to_have_value("Changed common field")
    expect(form.get_by_label("Venue name", exact=True)).to_have_value("Retain venue without saving")
    expect(form.get_by_label("Starts · NZ time")).to_have_value("2026-11-06T18:30")
    assert_clean_page(page)


def test_type_filter_survives_all_views_without_fetching_tasting_lists_or_choices(logged_in_page, tasting_world):
    page = logged_in_page
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    _open(page)
    for label, value in [("List", "2"), ("Week", "3"), ("Board", "1")]:
        page.get_by_role("button", name=label, exact=True).click()
        expect(page.locator("#tasks-page")).to_have_attribute("data-tasks-style", value)
        expect(page.get_by_label("Task type filter")).to_have_value("tasting")
        assert "type=tasting" in page.url
    assert not any("/api/crm/tastings" in url for url in requests)
    assert_clean_page(page)


def test_simple_call_task_still_creates_edits_and_completes(logged_in_page, tasting_world):
    page = logged_in_page
    page.goto("/crm/tasks?view=list")
    expect(page.locator("#tasks-page")).to_have_attribute("aria-busy", "false")
    page.get_by_role("button", name="New task", exact=True).first.click()
    title = "Follow up call " + uuid4().hex[:6]
    page.locator("#task-title").fill(title)
    page.locator("#task-type").select_option("call")
    page.get_by_role("button", name="Create task", exact=True).click()
    row = page.locator(".tasks-row").filter(has_text=title)
    expect(row).to_contain_text("Call")
    row.locator(".tasks-row__main").click()
    page.locator("#task-type").select_option("email")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(row).to_contain_text("Email")
    row.get_by_role("button", name="Mark done: " + title, exact=True).click()
    expect(row).to_have_count(0)
    assert_clean_page(page)


def test_direct_task_link_opens_tasting_when_not_in_initial_list(logged_in_page, tasting_world):
    page = logged_in_page
    response = page.request.get("/api/crm/tastings/" + tasting_world["event_id"])
    assert response.status == 200
    task_id = response.json()["tasting"]["task_id"]
    # Archived/otherwise excluded initial list: the deep link must fetch its own scoped task.
    page.route(
        "**/api/crm/tasks",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"tasks":[]}'),
    )
    page.goto("/crm/tasks?task_id=" + task_id)
    expect(page.locator("#tasting-detail-title")).to_have_text("Bottle-store brand tasting")
    expect(page.locator("#tasting-detail")).to_be_visible()
    assert_clean_page(page)


def test_specialized_task_dialog_inherits_dark_workspace_tokens(logged_in_page, tasting_world):
    page = logged_in_page
    _open(page, "2")
    page.evaluate("document.documentElement.dataset.spaTheme = 'dark'")
    page.get_by_role("button").filter(has_text="Bottle-store brand tasting").first.click()
    dialog = page.locator("#tasting-detail")
    expect(dialog).to_be_visible()
    background = dialog.evaluate("el => getComputedStyle(el).backgroundColor")
    title_color = page.locator("#tasting-detail-title").evaluate("el => getComputedStyle(el).color")
    assert background != "rgb(255, 255, 255)", "Dark task dialog must use its workspace surface"
    assert background != title_color, "Heading must remain visible against the dialog"
    assert_clean_page(page)


def test_stock_pagination_failure_is_visible_and_retries_same_page(logged_in_page, tasting_world):
    page = logged_in_page
    offsets = []
    failed = False

    def pool_response(route):
        nonlocal failed
        offset = 50 if "offset=50" in route.request.url else 0
        offsets.append(offset)
        if offset and not failed:
            failed = True
            route.fulfill(status=503, json={"error": "Stock temporarily unavailable"})
            return
        route.fulfill(
            json={
                "lots": [
                    {
                        "id": "pool-" + str(offset),
                        "product": "First batch" if not offset else "Next batch",
                        "available_volume_ml": "100",
                    }
                ],
                "has_more": not offset,
            }
        )

    page.route("**/api/crm/tastings/pool*", pool_response)
    _open(page)
    page.get_by_role("button", name="Tasting stock", exact=True).click()
    dialog = page.locator("#tasting-stock")
    expect(dialog).to_contain_text("First batch")
    dialog.get_by_role("button", name="More batches", exact=True).click()
    expect(dialog.get_by_role("alert")).to_have_text("Stock temporarily unavailable")
    dialog.get_by_role("button", name="Try again", exact=True).click()
    expect(dialog).to_contain_text("Next batch")
    expect(dialog).to_contain_text("First batch")
    expect(dialog.get_by_role("alert")).to_be_hidden()
    assert offsets == [0, 50, 50]


def test_type_switch_keeps_people_missing_from_ordinary_options(logged_in_page, tasting_world):
    page = logged_in_page
    contact_id = str(uuid4())
    rep_id = tasting_world["rep_id"]
    page.route("**/api/crm/customers?*", lambda route: route.fulfill(json={"customers": []}))
    page.route("**/org/users", lambda route: route.fulfill(json={"users": []}))

    def choices_response(route):
        route.fulfill(
            json={
                "stock": [],
                "reps": [{"id": rep_id, "name": "Selected tasting rep"}],
                "contacts": [{"id": contact_id, "name": "Customer beyond first page"}],
            }
        )

    page.route("**/api/crm/tastings/choices*", choices_response)
    _open(page)
    page.get_by_role("button", name="New task", exact=True).first.click()
    form = page.locator("#tasting-form")
    form.get_by_label("Tasting name").fill("Preserve selected people")
    form.get_by_label("Customer", exact=True).select_option(contact_id)
    form.get_by_label("Rep", exact=True).select_option(rep_id)
    form.get_by_label("Task type", exact=True).select_option("call")
    expect(page.locator("#task-customer")).to_have_value(contact_id)
    expect(page.locator("#task-customer option:checked")).to_have_text("Customer beyond first page")
    expect(page.locator("#task-who")).to_have_value(rep_id)
    expect(page.locator("#task-who option:checked")).to_have_text("Selected tasting rep")
    page.locator("#task-type").select_option("tasting")
    expect(form.get_by_label("Customer", exact=True)).to_have_value(contact_id)
    form.get_by_label("Task type", exact=True).select_option("email")
    with page.expect_request(
        lambda request: request.method == "POST" and request.url.endswith("/api/crm/tasks")
    ) as sent:
        page.route(
            "**/api/crm/tasks",
            lambda route: route.fulfill(
                status=201,
                json={
                    "task": {
                        "id": str(uuid4()),
                        "title": "Preserve selected people",
                        "task_type": "email",
                        "status": "pending",
                    }
                },
            ),
        )
        page.get_by_role("button", name="Create task", exact=True).click()
    assert sent.value.post_data_json["contact_id"] == contact_id
    assert sent.value.post_data_json["assigned_to_user_id"] == rep_id
    assert_clean_page(page)
