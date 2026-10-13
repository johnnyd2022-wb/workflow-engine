"""Workflow editor design and temporary concept comparisons."""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


# CONCEPT ONLY: delete style-persistence coverage with the preview switch.
def test_workflow_editor_stage_and_style_persist(logged_in_page):
    page = logged_in_page
    page.goto("/core/flows/create/process-overview?fresh=1&style=1")
    root = page.locator("#workflow-editor")
    expect(root).to_have_attribute("data-workflow-editor-style", "1")
    expect(root.locator('[aria-current="step"]')).to_have_text("1Workflow")
    page.get_by_role("button", name="Style 2", exact=True).click()
    page.locator("#guided-process-workflow-name").fill("Design review workflow")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page).to_have_url(re.compile(r"/core/flows/create/step-name"))
    expect(page.locator("#workflow-editor")).to_have_attribute("data-workflow-editor-style", "2")
    expect(page.get_by_label("Step Name", exact=False)).to_be_visible()
    expect(page.locator('#workflow-editor [aria-current="step"]')).to_have_text("2Step name")


# CONCEPT ONLY: delete these comparisons when one style is selected.
@pytest.mark.parametrize("style", [1, 2, 3])
@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_workflow_editor_concept_regions_fit(logged_in_page, style, width):
    page = logged_in_page
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"/core/flows/create/process-overview?fresh=1&style={style}")
    root = page.locator("#workflow-editor")
    expect(root).to_have_attribute("data-workflow-editor-style", str(style))
    for selector in [".workflow-editor__journey", ".workflow-editor__form", ".workflow-editor__guide"]:
        expect(root.locator(selector)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    form, guide = [root.locator(s).bounding_box() for s in [".workflow-editor__form", ".workflow-editor__guide"]]
    assert form and guide
    assert form["x"] + form["width"] <= guide["x"] + 1 or form["y"] + form["height"] <= guide["y"] + 1


def test_existing_workflow_editor_keeps_saved_step_fields(logged_in_page):
    from tests.e2e.conftest import csrf_headers

    page = logged_in_page
    proc = page.request.post(
        "/api/core/processes",
        headers=csrf_headers(page),
        data={"name": "Botanical gin editor", "category": "manufacturing"},
    )
    assert proc.status == 201
    pid = proc.json()["id"]
    step = page.request.post(
        f"/api/core/processes/{pid}/steps",
        headers=csrf_headers(page),
        data={"step_number": 1, "name": "Blend botanicals", "description": "Weigh and verify the blend."},
    )
    assert step.status == 201
    sid = step.json()["id"]
    page.goto(f"/core/flows/create/step-name?id={pid}&edit={sid}&style=1")
    expect(page.get_by_label("Step Name", exact=False)).to_have_value("Blend botanicals")
    expect(page.get_by_label("Description", exact=True)).to_have_value("Weigh and verify the blend.")
    expect(page.locator("#workflow-editor")).to_contain_text("Editing workflow")
    page.get_by_label("Step Name", exact=False).fill("Blend and verify botanicals")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page).to_have_url(re.compile(r"/core/flows/create/inputs"))
    page.goto(f"/core/flows/create/step-name?id={pid}&edit={sid}")
    expect(page.get_by_label("Step Name", exact=False)).to_have_value("Blend and verify botanicals")
