import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_sourcemap_checks_search_length_in_browser_and_api(logged_in_page, app_url):
    page = logged_in_page
    page.goto("/core/sourcemap")
    search = page.get_by_role("textbox", name="Filter inventory to trace")
    expect(search).to_have_attribute("maxlength", "255")
    search.fill("A" * 256)
    assert len(search.input_value()) == 255

    response = page.request.get("/api/core/sourcemap/objects", params={"q": "A" * 256})
    assert response.status == 400
    assert "q" in response.json()["errors"]
