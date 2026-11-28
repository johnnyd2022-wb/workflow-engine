import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e


def test_workflow_name_constraints_match_the_api(logged_in_page, app_url, assert_json_field_error):
    page = logged_in_page
    page.goto("/core/flows/create/process-overview?fresh=1")
    name = page.get_by_role("textbox", name="Name this workflow")
    expect(name).to_have_attribute("maxlength", "255")
    expect(name).to_have_attribute("required", "")
    assert name.evaluate("(input) => input.validity.valueMissing")
    name.fill("A" * 256)
    assert len(name.input_value()) == 255

    assert_json_field_error(
        page,
        "POST",
        "/api/core/processes",
        {"name": "A" * 256},
        "name",
        headers=csrf_headers(page),
    )
