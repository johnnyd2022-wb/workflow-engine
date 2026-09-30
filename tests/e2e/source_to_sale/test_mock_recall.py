"""A recall reaches every allocated customer and exports their contacts."""

import csv
import time
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from app.features.crm.models.xero_contact import XeroContact
from tests.e2e.source_to_sale.conftest import BATCH, PRODUCT

pytestmark = pytest.mark.e2e

# Plan 1.4 "done when": the timed mock recall is under five minutes. This is the scripted stopwatch, from
# opening the source map to the exported contact list and the backward trace from an invoice.
RECALL_DRILL_LIMIT_SECONDS = 300


def test_mock_recall_from_supplier_lot_and_invoice(alcohol_scenario):
    world = alcohol_scenario
    page, db, org_id = world["page"], world["db"], world["org_id"]
    known = XeroContact(
        org_id=org_id,
        xero_contact_id=str(uuid4()),
        xero_tenant_id="scenario",
        name="Harbour bottles",
        first_name="Alex",
        last_name="Smith",
        email_address="alex@example.test",
        phone_number="0211234567",
    )
    incomplete = XeroContact(
        org_id=org_id,
        xero_contact_id=str(uuid4()),
        xero_tenant_id="scenario",
        name="Hill shop",
        email_address="hill@example.test",
    )
    db.add_all([known, incomplete])
    db.commit()
    first = world["sell"](3, "SCENARIO-INV-1", known)
    world["sell"](2, "SCENARIO-INV-2", known)
    world["sell"](1, "SCENARIO-INV-3", incomplete)

    response = page.request.get(f"/api/core/inventory/trace-graph/{world['raw'].id}")
    assert response.status == 200, response.text()
    body = response.json()
    sale_nodes = [item for item in body["all_items"] if item.get("node_type") == "sale"]
    assert {item["invoice_number"] for item in sale_nodes} == {"SCENARIO-INV-1", "SCENARIO-INV-2", "SCENARIO-INV-3"}

    drill_started = time.monotonic()
    page.goto("/core/sourcemap")
    page.locator(".sm-browse-card", has_text="Bulk spirit").first.click()
    page.get_by_role("tab", name="Recall").click()
    page.get_by_role("switch", name="Recall mode").check()
    expect(page.locator(".sm-recall-summary")).to_contain_text("6 bottles sold")
    expect(page.locator(".sm-recall-summary")).to_contain_text("2 customers")
    expect(page.locator(".sm-recall-summary")).to_contain_text("44 bottles on hand")
    expect(page.locator(".sm-recall-sales")).to_contain_text("Alex Smith")
    expect(page.locator(".sm-recall-sales")).to_contain_text("0211234567")
    expect(page.locator(".sm-recall-customer--missing-contact")).to_contain_text("Hill shop")
    expect(page.locator(".sm-recall-customer--missing-contact")).to_contain_text("Phone missing")
    expect(page.locator(".sm-recall-workflow").first).to_contain_text("Bottle")

    with page.expect_download() as download_info:
        page.get_by_role("button", name="Export CSV", exact=True).click()
    rows = list(csv.reader(open(download_info.value.path(), encoding="utf-8-sig", newline="")))
    assert any(
        row and row[0] == "Harbour bottles" and "5 bottles" in row and "alex@example.test" in row for row in rows
    )
    assert any(row and row[0] == "Hill shop" and "1 bottles" in row for row in rows)
    assert ["On hand", "44 bottles"] in rows

    # The same batch is reachable backward from a sold invoice.
    page.goto(f"/core/sourcemap?invoice={first.xero_invoice_id}")
    expect(page.locator(".sm-recall-header__batch")).to_contain_text("SCENARIO-INV-1")
    expect(page.locator(".sm-recall-header__product")).to_have_text(PRODUCT)
    expect(page.locator(".sm-recall-header__batch")).to_contain_text(BATCH)

    elapsed = time.monotonic() - drill_started
    print(f"mock recall drill took {elapsed:.1f}s (limit {RECALL_DRILL_LIMIT_SECONDS}s)")
    assert elapsed < RECALL_DRILL_LIMIT_SECONDS, (
        f"mock recall took {elapsed:.0f}s; plan 1.4 requires under five minutes"
    )
