"""GL-P02 in a browser: hold a lot from its panel, see it marked everywhere, release it.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui), so this runs
against this checkout's code with no live server.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from playwright.sync_api import expect

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.lot_hold import LotHold
from app.core.db.models.user import UserRole
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org  # noqa: F401 -- fixture re-export
from tests.test_crm import user as _member  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

HOST = "https://crm.test"


@pytest.fixture()
def role():
    return UserRole.ADMIN


@pytest.fixture()
def user(_member, db, role):  # noqa: F811
    _member.role = role
    db.commit()
    return _member


@pytest.fixture()
def lot(db, org):  # noqa: F811
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_CREATE):
        item = InventoryItem(
            org_id=org.id, name="Juniper berries", quantity=Decimal("18.5"), unit="kg", inventory_type="raw_material"
        )
        db.add(item)
        db.commit()
    yield item
    db.rollback()
    db.query(LotHold).filter(LotHold.org_id == org.id).delete(synchronize_session=False)
    db.query(InventoryItem).filter(InventoryItem.org_id == org.id).delete(synchronize_session=False)
    db.commit()


def _open_lot(page):
    page.goto(HOST + "/core/inventory/view")
    page.get_by_role("button", name="Juniper berries").click()
    expect(page.get_by_role("dialog", name="Juniper berries")).to_be_visible()


def test_hold_then_release_a_lot(sales_page, lot, db):  # noqa: F811
    page = sales_page
    _open_lot(page)
    page.get_by_role("button", name="Hold…").click()
    dialog = page.locator("[data-hold-dialog]")
    expect(dialog.get_by_role("heading", name="Hold Juniper berries")).to_be_visible()
    expect(dialog.get_by_text("Nothing has been made from it yet.")).to_be_visible()
    dialog.get_by_role("button", name="Hold lot").click()
    expect(dialog.get_by_role("alert")).to_have_text("Say why the lot is held.")
    dialog.get_by_label("Why is it held?").fill("Cloudy after bottling")
    dialog.get_by_role("button", name="Hold lot").click()
    expect(dialog).to_have_count(0)

    row = page.locator("#inv-view-tbody tr", has_text="Juniper berries")
    expect(row.locator(".inv-row__hold")).to_have_text("On hold")
    _open_lot(page)
    panel = page.get_by_role("dialog", name="Juniper berries")
    expect(panel.locator(".inv-drawer__qhold")).to_contain_text("Cloudy after bottling")
    expect(panel.get_by_role("button", name="Hold…")).to_have_count(0)

    panel.get_by_role("button", name="Release…").click()
    dialog = page.locator("[data-hold-dialog]")
    dialog.get_by_label("What was checked?").fill("Re-filtered and retested")
    dialog.get_by_role("button", name="Release lot").click()
    expect(dialog).to_have_count(0)
    expect(row.locator(".inv-row__hold")).to_have_count(0)
    _open_lot(page)
    history = page.get_by_role("dialog", name="Juniper berries").locator(".inv-drawer__qhistory")
    expect(history).to_contain_text("Released")
    expect(history).to_contain_text("Re-filtered and retested")


@pytest.mark.parametrize("role", [UserRole.MEMBER])
def test_staff_can_hold_but_not_release(sales_page, lot, db, org):  # noqa: F811
    from app.core.services import lot_holds

    lot_holds.place_hold(db, org.id, lot.id, "Smells off", None)
    db.commit()
    _open_lot(sales_page)
    panel = sales_page.get_by_role("dialog", name="Juniper berries")
    expect(panel.locator(".inv-drawer__qhold")).to_contain_text("Smells off")
    expect(panel.get_by_role("button", name="Release…")).to_have_count(0)


@pytest.mark.parametrize("role", [UserRole.COMPLIANCE])
def test_a_compliance_role_without_stock_edit_can_release(sales_page, lot, db, org):  # noqa: F811
    """Release is its own permission (compliance.manage), not part of editing stock."""
    from app.core.services import lot_holds

    lot_holds.place_hold(db, org.id, lot.id, "Smells off", None)
    db.commit()
    _open_lot(sales_page)
    panel = sales_page.get_by_role("dialog", name="Juniper berries")
    expect(panel.get_by_role("button", name="Edit this line")).to_have_count(0)
    panel.get_by_role("button", name="Release…").click()
    dialog = sales_page.locator("[data-hold-dialog]")
    dialog.get_by_label("What was checked?").fill("Retested: passed")
    dialog.get_by_role("button", name="Release lot").click()
    expect(dialog).to_have_count(0)
    expect(
        sales_page.locator("#inv-view-tbody tr", has_text="Juniper berries").locator(".inv-row__hold")
    ).to_have_count(0)
