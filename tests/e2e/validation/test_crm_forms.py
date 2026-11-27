import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e


def test_crm_task_title_length_matches_server(logged_in_page, app_url, assert_json_field_error):
    page = logged_in_page
    page.goto("/crm/tasks")
    page.get_by_role("button", name="New task").click()
    title = page.locator("#task-title")
    expect(title).to_have_attribute("maxlength", "500")
    title.fill("A" * 501)
    assert len(title.input_value()) == 500
    assert_json_field_error(page, "POST", "/api/crm/tasks", {"title": "A" * 501}, "title", headers=csrf_headers(page))
