"""Every authenticated page renders clean, for a logged-in member of a real org.

Stage 2/3 render coverage. Cheap and broad: a page that throws in its JS still "works"
as far as a unit test is concerned, because the template rendered and the route returned
200. This is the check that notices.

Deliberately parametrised over the real route table rather than a curated list — a new
page gets covered by adding one line, and a page nobody thought to test is visible as an
absence here rather than as silence.
"""

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import assert_clean_page

pytestmark = pytest.mark.e2e

CORE_PAGES = [
    "/core",
    "/core/dashboard",
    "/core/processes",
    "/core/flows",
    "/core/flows/create",
    "/core/inventory/view",
    "/core/inventory/live",
    "/core/inventory/add",
    "/core/inventory/add/manual",
    "/core/inventory/add/csv",
    "/core/inventory/add/barcode",
    "/core/inventory/dispose",
    "/core/executions/live",
    "/core/notifications",
    "/core/settings",
    "/core/integrations",
]

CRM_PAGES = [
    "/crm",
    "/crm/customers",
    "/crm/tasks",
    "/crm/analytics",
    "/crm/configuration",
]


@pytest.mark.parametrize("path", CORE_PAGES)
def test_core_page_renders_clean(logged_in_page: Page, path: str):
    response = logged_in_page.goto(path)
    assert response is not None, f"no response for {path}"
    assert response.status < 400, f"{path} returned {response.status}"
    logged_in_page.wait_for_load_state("networkidle")
    assert_clean_page(logged_in_page)


@pytest.mark.parametrize("path", CRM_PAGES)
def test_crm_page_renders_clean(logged_in_page: Page, path: str):
    """CRM is feature-flagged; the E2E boot asserts it is on rather than skipping (spec
    Stage 3), so a flag regression shows up here as a failure, not as silent absence."""
    response = logged_in_page.goto(path)
    assert response is not None, f"no response for {path}"
    assert response.status < 400, f"{path} returned {response.status}"
    logged_in_page.wait_for_load_state("networkidle")
    assert_clean_page(logged_in_page)
