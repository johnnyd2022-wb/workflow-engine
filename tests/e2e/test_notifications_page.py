"""Notifications (/core/notifications): late first, and each notification's fix one click away.

The page used to sort newest-first, hide every action behind an "Actions" menu, and its
"Dispose of inventory item" did nothing on a full load (its function only existed on two other
pages). These pin what it does now.
"""

import re
from datetime import date, timedelta
from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import attach_probe, login_through_ui
from tests.factories import InventoryItemFactory

pytestmark = pytest.mark.e2e

UUID_TEXT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\b[0-9a-f]{8}\b")


@pytest.fixture
def busy(browser, app_url, fresh_user, db):
    """An org with two expired lots (one without a batch number), a late task and one due soon."""
    from app.core.db.models.core_task import CoreTask

    user = fresh_user(UserRole.ADMIN)
    org_id = UUID(user["org_id"])
    today = date.today()
    lot = InventoryItemFactory(
        org_id=org_id, name="Juniper berries", quantity="4.0000", unit="kg",
        supplier_batch_number="JB-0412", expiry_date=today - timedelta(days=6),
    )  # fmt: skip
    InventoryItemFactory(
        org_id=org_id, name="Orris root", quantity="2", unit="kg", expiry_date=today - timedelta(days=2)
    )
    db.add(CoreTask(org_id=org_id, title="Clean the still", due_date=today - timedelta(days=3)))
    db.add(CoreTask(org_id=org_id, title="Order bottles", due_date=today + timedelta(days=2)))
    db.commit()

    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    try:
        yield {"page": page, "lot": lot}
    finally:
        context.close()


def _open(page, style="1"):
    page.goto(f"/core/notifications?style={style}")
    page.locator("[data-notifications-page][aria-busy='false']").wait_for(timeout=20_000)


def _row(page, text):
    return page.locator(".nt-row", has_text=text)


def test_late_work_comes_first_with_its_action_on_the_row(busy):
    page = busy["page"]
    _open(page)
    sections = page.locator(".nt-section__title").all_inner_texts()
    assert sections[0].startswith("Late")
    late = page.locator(".nt-section--late .nt-row__title").all_inner_texts()
    assert "Clean the still" in late and "Order bottles" not in late
    task = _row(page, "Clean the still")
    expect(task.locator(".nt-when")).to_have_text("3 days late")
    # The action is a visible button on the row, not inside a menu.
    expect(task.get_by_role("link", name="Open the task")).to_be_visible()
    expect(task.get_by_role("link", name="Open the task")).to_have_attribute("href", "/core/tasks")
    expect(_row(page, "Order bottles").locator(".nt-when")).to_have_text("Due in 2 days")


def test_dispose_opens_record_disposal_with_the_lot_ready(busy):
    page, lot = busy["page"], busy["lot"]
    _open(page)
    row = _row(page, "Juniper berries · lot JB-0412 has expired")
    expect(row.locator(".nt-row__detail")).to_contain_text("4 kg still in stock")
    row.get_by_role("link", name="Dispose").click()
    page.wait_for_url(re.compile(r"/core/inventory/dispose\?item_ids="))
    assert str(lot.id) in page.url
    card = page.locator(f".dispose-list__item[data-inventory-id='{lot.id}']")
    expect(card).to_be_visible()
    expect(page.locator(".dispose-list__item")).to_have_count(1)
    expect(card.locator(".wastage-qty-input")).to_have_value("4")
    expect(page.locator("#dispose-bulk-reason")).to_have_value("Expired")


def test_no_database_id_is_shown(busy):
    page = busy["page"]
    _open(page)
    expect(_row(page, "Orris root has expired")).to_be_visible()  # no batch number: named, not numbered
    for style in ("1", "2", "3"):
        _open(page, style)
        assert not UUID_TEXT.search(page.locator("#page-content").inner_text())


def test_hiding_moves_a_notification_to_hidden_and_back(busy):
    page = busy["page"]
    _open(page)
    row = _row(page, "Clean the still")
    row.locator(".nt-more__toggle").click()
    page.get_by_role("menuitem", name="Hide until tomorrow").click()
    expect(_row(page, "Clean the still")).to_have_count(0)
    page.locator("[data-nt-view=archive]").click()
    expect(_row(page, "Clean the still")).to_be_visible()
    _row(page, "Clean the still").locator(".nt-more__toggle").click()
    page.get_by_role("menuitem", name="Show again").click()
    page.locator("[data-nt-view=active]").click()
    expect(_row(page, "Clean the still")).to_be_visible()


# CONCEPT ONLY: deleted with the two styles not chosen. ─────────────────────────────────────


@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("size", [(390, 844), (1440, 900), (1920, 1080)], ids=["phone", "laptop", "wall"])
def test_each_style_fits_and_shows_every_notification(busy, style, size):
    page = busy["page"]
    page.set_viewport_size({"width": size[0], "height": size[1]})
    _open(page, style)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    item = ".nt-inbox__item" if style == "2" else ".nt-row"
    assert page.locator(item).count() == 4
    if style == "2":
        expect(page.locator("[data-nt-detail]")).to_be_visible()
        expect(page.locator("[data-nt-detail]").get_by_role("link").first).to_be_visible()
