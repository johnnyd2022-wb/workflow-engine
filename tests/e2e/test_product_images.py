"""Product photos through the workflow editor, production and stock."""

from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from playwright.sync_api import expect

from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e


def _photo(color):
    out = BytesIO()
    with Image.new("RGB", (96, 144), color) as image:
        image.save(out, "JPEG")
    return {"name": "product.jpg", "mimeType": "image/jpeg", "buffer": out.getvalue()}


def _assert_loaded(locator):
    expect(locator).to_be_visible()
    expect(locator).to_have_js_property("complete", True)
    assert locator.evaluate("image => image.naturalWidth > 0")


def test_ac1_ac2_ac3_ac4_ac5_product_image_journey(strict_csp_page, fresh_user, browser, app_url):
    page = strict_csp_page
    page.set_viewport_size({"width": 390, "height": 844})
    name = f"Wildflower gin {uuid4().hex[:6]}"
    output = f"Finished blend {uuid4().hex[:6]}"
    page.goto("/core/processes")
    headers = csrf_headers(page)
    made = page.request.post("/api/core/processes", headers=headers, data={"name": name})
    assert made.status == 201
    pid = made.json()["id"]
    step = page.request.post(
        f"/api/core/processes/{pid}/steps",
        headers=headers,
        data={"name": "Bottle", "step_number": 1, "outputs": [{"name": output, "quantity": 1, "unit": "L"}]},
    )
    assert step.status == 201, step.text()
    sid = step.json()["id"]
    workflow_url = f"/api/core/processes/{pid}/product-image"
    page.goto(f"/core/flows?id={pid}")

    add = page.get_by_role("button", name="Add final product image")
    expect(add).to_be_visible()
    add.click()
    sheet = page.get_by_role("dialog", name="Final product image")
    expect(sheet).to_be_visible()
    expect(sheet.get_by_role("button", name="Remove image")).not_to_be_visible()
    sheet.get_by_label("Photo").set_input_files(
        {"name": "invalid.jpg", "mimeType": "image/jpeg", "buffer": b"not an image"}
    )
    sheet.get_by_role("button", name="Save image").click()
    expect(sheet.get_by_role("alert")).to_have_text("Choose a valid JPEG, PNG or WebP image.")
    assert page.request.get(workflow_url).status == 404

    sheet.get_by_label("Photo").set_input_files(_photo("darkgreen"))
    sheet.get_by_role("button", name="Save image").click()
    expect(sheet).not_to_be_visible()
    workflow_photo = page.get_by_role("img", name="Final product", exact=True)
    _assert_loaded(workflow_photo)
    photo_box = workflow_photo.bounding_box()
    edit = page.get_by_role("button", name="Change final product image")
    edit_box = edit.bounding_box()
    assert photo_box["height"] >= 180
    assert abs(photo_box["width"] / photo_box["height"] - 96 / 144) < 0.02
    assert abs(photo_box["x"] + photo_box["width"] / 2 - page.viewport_size["width"] / 2) < 10
    expect(edit.get_by_text("Add final product image")).not_to_be_visible()
    assert 0 < photo_box["x"] + photo_box["width"] - edit_box["x"] - edit_box["width"] <= 12
    assert 0 < edit_box["y"] - photo_box["y"] <= 12
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    page.goto("/core/processes")
    card = page.get_by_role("link", name=f"Open workflow: {name}", exact=True)
    _assert_loaded(card.locator("img"))
    card.click()
    expect(page.get_by_role("button", name="Change final product image")).to_be_visible()
    _assert_loaded(page.get_by_role("img", name="Final product", exact=True))
    page.goto(f"/core/flows/batches/start?id={pid}&draft=1&step_id={sid}")
    _assert_loaded(page.get_by_role("img", name="Final product", exact=True))

    headers = csrf_headers(page)
    batch = page.request.post("/api/core/executions", headers=headers, data={"process_id": pid})
    assert batch.status == 201, batch.text()
    eid = batch.json()["id"]
    execution = page.request.get(f"/api/core/executions/{eid}").json()
    step_id = execution["execution_steps"][0]["id"]

    page.goto("/core/executions/live")
    _assert_loaded(page.locator(f'[data-core2-execution-id="{eid}"] img').first)

    headers = csrf_headers(page)
    recorded = page.request.post(
        f"/api/core/executions/{eid}/steps/{step_id}/complete",
        headers=headers,
        data={"actual_inputs": [], "actual_outputs": [{"name": output, "quantity": 1, "unit": "L"}]},
    )
    assert recorded.status == 200, recorded.text()
    page.goto(f"/core/executions/{eid}/steps/{step_id}/record")
    _assert_loaded(page.get_by_role("img", name="Final product", exact=True))

    raw = page.request.post(
        "/api/core/inventory",
        headers=csrf_headers(page),
        data={
            "name": f"Raw botanicals {uuid4().hex[:6]}",
            "quantity": 1,
            "unit": "kg",
            "inventory_type": "raw_material",
        },
    )
    assert raw.status == 201, raw.text()
    raw_name = raw.json()["name"]
    page.goto("/core/inventory/view")
    expect(page.get_by_role("row", name=raw_name, exact=False).locator(".product-image")).to_be_visible()
    expect(page.get_by_role("row", name=raw_name, exact=False).locator("img")).to_have_count(0)
    lot = page.get_by_role("row", name=output, exact=False)
    _assert_loaded(lot.locator("img"))
    expect(lot.locator("img")).to_have_attribute("loading", "lazy")
    lot.get_by_role("button", name=output).click()
    drawer = page.get_by_role("dialog", name=output, exact=True)
    _assert_loaded(drawer.get_by_role("img", name="Final product"))
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    page.goto("/core/inventory/live")
    group = page.get_by_role("button", name=f"{output}, 1 L in stock across 1 lot. Open lots.", exact=True)
    _assert_loaded(group.locator("img"))
    group.click()
    _assert_loaded(page.get_by_role("dialog").get_by_role("img", name="Final product"))
    page.get_by_role("dialog").get_by_role("button", name="Close").click()
    page.get_by_role("tab", name="By process").click()
    finished_card = page.get_by_role("article").filter(has=page.get_by_role("heading", name=output, exact=True))
    _assert_loaded(finished_card.locator("img"))

    item = next(i for i in page.request.get("/api/core/inventory").json()["inventory_items"] if i["name"] == output)
    lot_url = f"/api/core/inventory/{item['id']}/product-image"
    assert page.request.get(lot_url).status == 200
    first_image = page.request.get(lot_url).body()
    assert first_image == page.request.get(workflow_url).body()

    other = fresh_user()
    with browser.new_context(base_url=app_url, ignore_https_errors=True) as context:
        other_page = context.new_page()
        login_through_ui(other_page, other["email"], other["password"])
        assert other_page.request.get(workflow_url).status == 404
        assert other_page.request.get(lot_url).status == 404

    page.goto(f"/core/flows?id={pid}")
    change = page.get_by_role("button", name="Change final product image")
    change.click()
    sheet.get_by_label("Photo").set_input_files(_photo("darkblue"))
    sheet.get_by_role("button", name="Save image").click()
    expect(sheet).not_to_be_visible()
    assert page.request.get(lot_url).body() != first_image

    change.click()
    sheet.get_by_role("button", name="Remove image").click()
    expect(add).to_be_visible()
    assert page.request.get(lot_url).status == 404
