"""A trace's header and Map carry the recall figures: what was sold, to whom, what is left."""

from uuid import uuid4

import pytest
from playwright.sync_api import expect

from app.features.crm.models.xero_contact import XeroContact
from tests.e2e.source_to_sale.conftest import PRODUCT

pytestmark = pytest.mark.e2e


def _contact(org_id, name, **details):
    return XeroContact(org_id=org_id, xero_contact_id=str(uuid4()), xero_tenant_id="scenario", name=name, **details)


def test_customers_are_the_last_column_and_the_header_matches_the_recall_tab(alcohol_scenario):
    world = alcohol_scenario
    page, db, org_id = world["page"], world["db"], world["org_id"]
    known = _contact(org_id, "Harbour bottles", email_address="alex@example.test", phone_number="0211234567")
    silent = _contact(org_id, "Hill shop")
    db.add_all([known, silent])
    db.commit()
    world["sell"](3, "MAP-INV-1", known)
    world["sell"](2, "MAP-INV-2", known)
    world["sell"](1, "MAP-INV-3", silent)

    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("/core/sourcemap")
    page.locator(".sm-browse-card", has_text="Bulk spirit").first.click()

    columns = page.locator(".sm-lineage__column")
    expect(columns).to_have_count(3)
    expect(columns.nth(1).locator(".sm-lineage__name")).to_have_text([PRODUCT])
    customers = columns.nth(2)
    expect(customers.locator(".sm-lineage__title")).to_contain_text("Customers")

    # One node per customer, however many invoices: Harbour bottles holds two.
    expect(customers.locator(".sm-lineage__node--customer")).to_have_count(2)
    harbour = customers.locator(".sm-lineage__node--customer", has_text="Harbour bottles")
    expect(harbour).to_contain_text("5 bottles · 2 invoices")
    expect(harbour.locator(".sm-lineage__flag")).to_have_count(0)
    hill = customers.locator(".sm-lineage__node--customer", has_text="Hill shop")
    expect(hill).to_contain_text("1 bottles · 1 invoice")
    expect(hill.locator(".sm-lineage__flag")).to_have_text("No contact details")

    figures = dict(
        zip(
            page.locator(".sm-impact-figure dt").all_inner_texts(),
            page.locator(".sm-impact-figure dd").all_inner_texts(),
            strict=True,
        )
    )
    assert figures == {"Batch": "1", "Sold": "6 bottles", "Customers": "2", "On hand": "44 bottles"}

    # The Recall tab states the same three figures in its own summary line.
    page.get_by_role("tab", name="Recall").click()
    summary = page.locator(".sm-recall-summary")
    expect(summary).to_contain_text("6 bottles sold")
    expect(summary).to_contain_text("2 customers")
    expect(summary).to_contain_text("44 bottles on hand")
