from uuid import uuid4

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_past_case_due_date_is_rejected_before_submitting(logged_in_page, app_url):
    page = logged_in_page
    submissions = []

    def unexpected_submission(route):
        submissions.append(route.request.url)
        route.fulfill(status=400, json={"error": "Reached the server"})

    page.route("**/api/core/cases/from-finding", unexpected_submission)
    page.goto(f"/core/cases/new?source_entity_id={uuid4()}")
    owner = page.get_by_label("Owner")
    expect(owner.locator("option").nth(1)).to_be_attached()
    owner.select_option(index=1)
    page.get_by_label("Due date (UTC)").fill("2020-02-01")
    page.get_by_label("Due time (UTC)").fill("15:30")
    page.get_by_label("Next action").fill("Check the quantity")
    page.get_by_role("button", name="Create case").click()
    expect(page.locator("[data-oc-new-error]")).to_have_text("Choose a due date and time in the future.")
    assert submissions == []
