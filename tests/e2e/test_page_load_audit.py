"""Opt-in paired browser navigation measurements on the seeded test app."""

import os

import pytest

from app.core.db import db_session
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from tests.e2e.page_load_audit import measure_page
from tests.e2e.test_mobile_page_audit import (
    APP_PAGES,
    PUBLIC_PAGES,
    mobile_audit_subscription,  # noqa: F401
    mobile_detail_records,  # noqa: F401
)
from tests.e2e.test_perf_budgets import instrument_performance
from tests.e2e.test_process_wizard_flow import _create_process_with_step

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("PAGE_LOAD_AUDIT") != "1", reason="set PAGE_LOAD_AUDIT=1 to collect browser metrics"
    ),
]
APP_ROUTES = [
    *APP_PAGES,
    "/core/costing/costs",
    "/core/costing/margins",
    "/core/costing/purchases",
    "/core/costing/rules",
    "/compliant/nz-alcohol/wine",
]


@pytest.fixture(scope="module", autouse=True)
def page_audit_server_metrics(app_url):
    if os.environ.get("E2E_BASE_URL"):
        yield
    else:
        yield from instrument_performance()


@pytest.mark.parametrize("route", PUBLIC_PAGES)
def test_public_page_load(browser, app_url, route):
    measure_page(browser, app_url, route)


@pytest.fixture(scope="module")
def costing_access(e2e_user):
    db = db_session()
    FeatureSubscriptionRepository(db).grant(e2e_user["org_id"], "costing")
    db.commit()


@pytest.mark.parametrize("route", APP_ROUTES)
def test_app_page_load(browser, app_url, storage_state_path, costing_access, route):
    measure_page(browser, app_url, route, storage_state_path)


@pytest.mark.parametrize(
    ("label", "index", "suffix"),
    [
        ("/crm/customers/<contact_id>", 0, ""),
        ("/core/cases/<case_id>", 1, ""),
        ("/core/contracts/<order_id>", 2, ""),
        ("/core/contracts/<order_id>/portal-sharing", 2, "/portal-sharing"),
        ("/invite/<token>", 6, ""),
    ],
)
def test_seeded_detail_page_load(browser, app_url, storage_state_path, mobile_detail_records, label, index, suffix):  # noqa: F811
    prefix = label.split("<", 1)[0]
    state = None if prefix == "/invite/" else storage_state_path
    measure_page(browser, app_url, f"{prefix}{mobile_detail_records[index]}{suffix}", state, label=label)


@pytest.mark.parametrize(
    ("label", "path"),
    [
        ("/compliant/nz-alcohol/customs/records/<control_id>", "/compliant/nz-alcohol/customs/records/product-mapping"),
        ("/compliant/nz-alcohol/np3-audit/check/<control_id>", "/compliant/nz-alcohol/np3-audit/check/recall-policy"),
    ],
)
def test_compliance_control_page_load(browser, app_url, storage_state_path, label, path):
    measure_page(browser, app_url, path, storage_state_path, label=label)


def test_record_page_load(browser, app_url, storage_state_path, mobile_detail_records):  # noqa: F811
    _, _, _, execution, step, inventory, _ = mobile_detail_records
    measure_page(
        browser,
        app_url,
        f"/core/executions/{execution}/steps/{step}/record",
        storage_state_path,
        label="/core/executions/<execution_id>/steps/<step_id>/record",
    )
    measure_page(
        browser,
        app_url,
        f"/core/inventory/dispose/confirm?inventory_item_id={inventory}&quantity_wasted=1",
        storage_state_path,
        label="/core/inventory/dispose/confirm",
    )


def test_wizard_page_load(browser, app_url, storage_state_path):
    routes = {
        f"/core/flows/create/{step}": ""
        for step in ("step-name", "inputs", "outputs", "evidence-and-prompts", "summary", "next-steps")
    }
    routes["/core/flows/batches/start"] = "&draft=1&step_id={step_id}"
    selected = os.environ.get("PAGE_LOAD_ROUTES", "").split()
    if selected and not set(selected) & routes.keys():
        return
    with browser.new_context(base_url=app_url, ignore_https_errors=True, storage_state=storage_state_path) as context:
        page = context.new_page()
        page.goto("/core/flows")
        process_id, step_id = _create_process_with_step(page, "Page audit workflow")
    for path, suffix in routes.items():
        measure_page(
            browser,
            app_url,
            f"{path}?id={process_id}" + suffix.format(step_id=step_id),
            storage_state_path,
            label=path,
        )
