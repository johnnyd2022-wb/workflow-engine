"""GL-P03 in a browser: start a recall from a lot, work the customer checklist until it can resolve.

Requests are routed into the Flask test client (see test_crm_contact_sync_ui), so this runs
against this checkout's code with no live server.
"""

from __future__ import annotations

import os
import re
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.lot_hold import LotHold
from app.core.db.models.user import UserRole
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.xero_contact import XeroContact
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.operational_cases.models.operational_case import OperationalCase
from app.features.operational_cases.models.operational_case_event import OperationalCaseEvent
from app.features.operational_cases.models.operational_case_link import OperationalCaseLink
from app.features.recalls.models import Recall, RecallContact
from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org  # noqa: F401 -- fixture re-export
from tests.test_crm import user as _member  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e
HOST = "https://crm.test"


@pytest.fixture()
def user(_member, db):  # noqa: F811
    _member.role = UserRole.ADMIN
    db.commit()
    return _member


@pytest.fixture()
def lot(db, org):  # noqa: F811
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_CREATE):
        item = InventoryItem(
            org_id=org.id, name="Navy Gin batch 12", quantity=Decimal("40"), unit="each", inventory_type="final_product"
        )
        db.add(item)
        db.flush()
    contact = XeroContact(org_id=org.id, xero_contact_id=f"c-{uuid4()}", name="Harbour Bar")
    db.add(contact)
    db.flush()
    db.add(
        XeroInvoice(
            org_id=org.id,
            xero_tenant_id="t",
            xero_invoice_id="inv-r1",
            invoice_number="INV-0103",
            contact_id=contact.id,
            invoice_type="ACCREC",
            status="AUTHORISED",
        )
    )
    db.add(
        SalesFifoAllocation(
            org_id=org.id,
            xero_invoice_id="inv-r1",
            xero_line_key="inv-r1:1",
            inventory_item_id=item.id,
            product_name="Navy Gin 700ml",
            quantity=Decimal("4"),
            unit="each",
        )
    )
    db.commit()
    yield item
    db.rollback()
    for model in (
        RecallContact,
        Recall,
        OperationalCaseEvent,
        OperationalCaseLink,
        OperationalCase,
        LotHold,
        SalesFifoAllocation,
        XeroInvoice,
        XeroContact,
    ):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.query(InventoryItem).filter(InventoryItem.org_id == org.id).delete(synchronize_session=False)
    db.commit()


def test_start_a_recall_from_a_lot_and_work_it_to_ready(sales_page, lot, db):  # noqa: F811
    page = sales_page
    page.goto(HOST + "/core/inventory/view")
    page.get_by_role("button", name="Navy Gin batch 12").click()
    page.get_by_role("button", name="Recall…").click()
    start = page.locator("[data-rc-start]")
    start.get_by_label("Why").fill("Glass fragments found in one bottle")
    start.get_by_role("button", name="Start recall").click()
    page.wait_for_url("**/core/cases/*")

    # Due in three days: not overdue (the badge ignored its hidden attribute before GL-P03).
    expect(page.locator("[data-oc-overdue-badge]")).to_be_hidden()
    section = page.get_by_role("region", name="Recall")
    expect(section.get_by_role("heading", name="Recall", exact=True)).to_be_visible()
    expect(section).to_contain_text("Risk to health: Glass fragments found in one bottle")
    expect(section).to_contain_text("1 on quality hold")
    expect(section.locator(".rc-blockers")).to_contain_text("Harbour Bar hasn't acknowledged the notice")
    card = section.locator("[data-rc-contact]")
    expect(card).to_contain_text("4 each of Navy Gin 700ml · INV-0103")
    expect(card.locator(".rc-chip")).to_have_text("Not contacted")

    card.get_by_role("button", name="Notice to send").click()
    notice = page.locator(".rc-notice")
    expect(notice.get_by_label("Subject")).to_have_value("Product recall: Navy Gin 700ml")
    expect(notice.get_by_label("Message")).to_have_value(re.compile(r"^Dear Harbour Bar,"))
    notice.get_by_role("button", name="Close").click()

    card.get_by_role("button", name="Mark notice sent").click()
    page.locator("[data-rc-dialog]").get_by_role("button", name="Record it").click()
    expect(card.locator(".rc-chip")).to_have_text("Notice sent")
    card.get_by_role("button", name="Acknowledged…").click()
    dialog = page.locator("[data-rc-dialog]")
    dialog.get_by_label("Who acknowledged it").fill("Mere (bar manager)")
    dialog.get_by_role("button", name="Record acknowledgement").click()
    card.get_by_role("button", name="Recovered / disposed…").click()
    dialog = page.locator("[data-rc-dialog]")
    dialog.get_by_label("Came back to you").fill("3")
    dialog.get_by_label("Disposed of by them").fill("1")
    dialog.get_by_role("button", name="Save").click()
    expect(card.locator(".rc-chip")).to_have_text("Accounted for")
    expect(section).to_contain_text("Ready to resolve")
    expect(section.locator(".rc-blockers")).to_have_count(0)

    shots = os.environ.get("RECALL_SHOTS_DIR")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        for name, width, mode in (
            ("desktop-light", 1440, "light"),
            ("phone-light", 390, "light"),
            ("desktop-dark", 1440, "dark"),
        ):
            page.set_viewport_size({"width": width, "height": 900 if width > 480 else 844})
            page.evaluate("mode => document.documentElement.setAttribute('data-spa-theme', mode)", mode)
            page.wait_for_timeout(300)
            page.screenshot(path=str(Path(shots) / f"recall-case-{name}.png"), full_page=True)
