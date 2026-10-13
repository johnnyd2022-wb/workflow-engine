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
    expect(page.get_by_role("textbox", name="Step name", exact=False)).to_be_visible()
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
    expect(page.locator("#guided-step-name")).to_have_value("Blend botanicals")
    expect(page.locator("#guided-step-description")).to_have_value("Weigh and verify the blend.")
    expect(page.locator("#workflow-editor")).to_contain_text("Editing workflow")
    page.wait_for_load_state("networkidle")
    page.locator("#guided-step-name").fill("Blend and verify botanicals")
    expect(page.locator("#guided-step-name")).to_have_value("Blend and verify botanicals")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page).to_have_url(re.compile(r"/core/flows/create/inputs"))
    page.wait_for_load_state("networkidle")
    page.goto(f"/core/flows/create/step-name?id={pid}&edit={sid}")
    expect(page.locator("#guided-step-name")).to_have_value("Blend and verify botanicals")


def _start_step(page, style=1):
    page.goto(f"/core/flows/create/process-overview?fresh=1&style={style}")
    page.locator("#guided-process-workflow-name").fill("Stage progress workflow")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page).to_have_url(re.compile(r"/core/flows/create/step-name"))
    # The wizard restores its saved state after load; typing before that settles would be overwritten.
    page.wait_for_load_state("networkidle")


def _name_step(page, name):
    field = page.locator("#guided-step-name")
    field.fill(name)
    expect(field).to_have_value(name)
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page).to_have_url(re.compile(r"/core/flows/create/inputs"))
    page.wait_for_load_state("networkidle")


def test_finished_stages_are_marked_and_back_keeps_what_was_entered(logged_in_page):
    page = logged_in_page
    _start_step(page)
    stages = page.locator("#workflow-editor .workflow-editor__journey li")
    expect(stages.nth(0)).to_have_attribute("data-stage-done", "")
    expect(stages.nth(0)).to_contain_text("(done)")
    expect(stages.nth(1)).to_have_attribute("aria-current", "step")
    expect(page.locator("#workflow-editor [data-stage-done]")).to_have_count(1)
    _name_step(page, "Macerate botanicals")
    expect(page.locator("#workflow-editor [data-stage-done]")).to_have_count(2)
    # Back is beside Next, and returning does not lose the step name.
    back = page.locator(".flow-wizard-sticky-back")
    next_button = page.get_by_role("button", name="Next", exact=True)
    assert back.bounding_box()["x"] < next_button.bounding_box()["x"]
    back.click()
    expect(page).to_have_url(re.compile(r"/core/flows/create/step-name"))
    expect(page.locator("#guided-step-name")).to_have_value("Macerate botanicals")


def test_first_stage_has_no_back_and_guidance_has_no_click_instruction(logged_in_page):
    page = logged_in_page
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("/core/flows/create/process-overview?fresh=1&style=1")
    expect(page.locator(".flow-wizard-sticky-back")).to_have_count(0)
    guide = page.locator("#workflow-editor .workflow-editor__guide")
    expect(guide).not_to_contain_text("As you build")
    expect(guide.locator(".flow-wizard-example-disclosure__hint")).to_be_hidden()
    # Beside the form there is room, so the stage's guidance is already open.
    assert guide.locator("details").evaluate("node => node.open")
    page.get_by_role("button", name="Style 2", exact=True).click()
    assert not guide.locator("details").evaluate("node => node.open")


def test_inputs_stage_filters_materials_by_name(logged_in_page):
    page = logged_in_page
    _start_step(page)
    _name_step(page, "Macerate botanicals")
    search = page.get_by_role("searchbox", name="Search materials", exact=True)
    # A short or empty list is quicker to read than to search, so the box waits for six rows.
    expect(search).to_be_hidden()
    # A new organisation holds no stock, so stand in three rows where the wizard renders its own.
    page.evaluate(
        """() => {
          const list = document.querySelector('#guided-inventory-cards-container');
          ['Juniper berries', 'Coriander seed', 'Glass bottle 700 mL', 'Angelica root', 'Orris root', 'Lemon myrtle'].forEach(name => {
            const row = document.createElement('div');
            row.className = 'filter-probe';
            row.textContent = name;
            list.appendChild(row);
          });
        }"""
    )
    expect(search).to_be_visible()
    search.fill("juni")
    expect(page.locator(".filter-probe:visible")).to_have_text(["Juniper berries"])
    search.fill("zzz")
    expect(page.locator(".filter-probe:visible")).to_have_count(0)
    expect(page.get_by_role("status").filter(has_text="No materials match")).to_be_visible()
    search.fill("")
    expect(page.locator(".filter-probe:visible")).to_have_count(6)


def test_phone_shows_one_line_of_progress(logged_in_page):
    page = logged_in_page
    page.set_viewport_size({"width": 390, "height": 844})
    _start_step(page)
    journey = page.locator("#workflow-editor .workflow-editor__journey")
    expect(journey.locator("li:visible")).to_have_count(1)
    expect(journey.locator('[aria-current="step"]')).to_be_visible()
    assert journey.locator("ol").evaluate("node => getComputedStyle(node, '::before').content") == '"Stage 2 of 7"'
    assert journey.bounding_box()["height"] < 80
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
