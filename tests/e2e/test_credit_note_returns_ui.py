"""Sales overview asks for a return decision on mapped credit-note lines."""

import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from app.core.db.models.audit_log import AuditLog
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.xero_credit_note import XeroCreditNote
from app.features.crm.models.xero_credit_note_line import XeroCreditNoteLine
from tests.e2e.test_crm_contact_sync_ui import client, sales_page  # noqa: F401

pytestmark = pytest.mark.e2e


@pytest.fixture()
def org(db):
    organisation = OrganisationRepository(db).create_org(f"Credit return UI {uuid4()}")
    db.commit()
    yield organisation
    db.rollback()
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.lot_hold import LotHold
    from app.features.crm.models.sales_return import SalesReturn

    for model in (SalesReturn, LotHold, InventoryItem):
        db.query(model).filter(model.org_id == organisation.id).delete(synchronize_session=False)
    db.query(XeroCreditNoteLine).filter(XeroCreditNoteLine.org_id == organisation.id).delete(synchronize_session=False)
    db.query(XeroCreditNote).filter(XeroCreditNote.org_id == organisation.id).delete(synchronize_session=False)
    db.query(ProductMapping).filter(ProductMapping.org_id == organisation.id).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.org_id == organisation.id).delete(synchronize_session=False)
    db.query(User).filter(User.org_id == organisation.id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == organisation.id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture()
def user(db, org):
    user = UserRepository(db).create_user(
        org_id=org.id,
        email=f"credit-return-{uuid4()}@test.com",
        password_hash=AuthService.hash_password("TestPass123!"),
    )
    db.commit()
    return user


def test_sales_overview_records_credit_only_return_decision(sales_page, db, org):  # noqa: F811
    mapping = ProductMapping(
        org_id=org.id,
        biz_e_product_name="Dry gin 700ml",
        xero_description_pattern="Dry gin",
        match_type="exact",
    )
    note = XeroCreditNote(
        org_id=org.id,
        xero_credit_note_id="ui-credit-note-1",
        xero_tenant_id="tenant",
        number="CN-UI-1",
        contact="Kererū Botanicals",
        date=date(2026, 10, 12),
        status="AUTHORISED",
        total=Decimal("25"),
        currency="NZD",
    )
    db.add_all([mapping, note])
    db.flush()
    line = XeroCreditNoteLine(
        org_id=org.id,
        credit_note_id=note.id,
        line_key="ui-line-1",
        description="Dry gin 700ml",
        quantity=Decimal("1"),
        line_amount=Decimal("25"),
        product_mapping_id=mapping.id,
    )
    db.add(line)
    db.commit()

    page = sales_page
    page.goto("https://crm.test/crm")
    section = page.get_by_role("region", name="Did stock come back?")
    expect(section.get_by_text("Dry gin 700ml", exact=True)).to_be_visible()
    screenshot_dir = os.environ.get("CRM_SHOTS_DIR")
    if screenshot_dir:
        destination = Path(screenshot_dir)
        destination.mkdir(parents=True, exist_ok=True)
        for name, width, theme_name in (
            ("desktop-light", 1440, "light"),
            ("desktop-dark", 1440, "dark"),
            ("phone-light", 390, "light"),
            ("phone-dark", 390, "dark"),
        ):
            page.set_viewport_size({"width": width, "height": 900 if width > 480 else 844})
            page.evaluate("mode => document.documentElement.setAttribute('data-spa-theme', mode)", theme_name)
            page.wait_for_timeout(300)
            page.screenshot(path=str(destination / f"credit-note-returns-{name}.png"), full_page=True)
    section.get_by_label("Why no goods returned for Dry gin 700ml").fill("Customer kept the goods")
    section.get_by_role("button", name="Credit only · no goods").click()
    expect(section.get_by_text("Dry gin 700ml", exact=True)).to_have_count(0)
    expect(section.get_by_text("No mapped credit-note lines need a return decision.")).to_be_visible()


def test_sales_overview_records_goods_that_came_back(sales_page, db, org):  # noqa: F811
    """GL-P01b: two of three bottles back damaged; the line stays until all three are accounted for."""
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.services import lot_holds
    from app.features.crm.models.sales_return import SalesReturn

    mapping = ProductMapping(
        org_id=org.id, biz_e_product_name="Dry gin 700ml", xero_description_pattern="Dry gin", match_type="exact"
    )
    note = XeroCreditNote(
        org_id=org.id,
        xero_credit_note_id="ui-credit-note-2",
        xero_tenant_id="tenant",
        number="CN-UI-2",
        contact="Kererū Botanicals",
        date=date(2026, 10, 12),
        status="AUTHORISED",
        total=Decimal("75"),
        currency="NZD",
    )
    db.add_all([mapping, note])
    db.flush()
    db.add(
        XeroCreditNoteLine(
            org_id=org.id,
            credit_note_id=note.id,
            line_key="ui-line-2",
            description="Dry gin 700ml",
            quantity=Decimal("3"),
            line_amount=Decimal("75"),
            product_mapping_id=mapping.id,
        )
    )
    db.commit()

    page = sales_page
    logs = []
    page.on("console", lambda m: logs.append(m.text) if m.type in ("error", "warning") else None)
    page.goto("https://crm.test/crm")
    section = page.get_by_role("region", name="Did stock come back?")
    expect(section.get_by_text("NZ$75.00").or_(section.get_by_text("$75.00"))).to_be_visible()
    # The app runs Alpine's CSP build: a template that calls a global (Number, Math) fails silently.
    assert not [m for m in logs if "Alpine Expression Error" in m], logs
    expect(section.get_by_label("How many Dry gin 700ml came back")).to_have_value("3")
    section.get_by_label("How many Dry gin 700ml came back").fill("2")
    section.get_by_label("Condition of returned Dry gin 700ml").select_option("damaged")
    section.get_by_label("Note on returned Dry gin 700ml").fill("Broken seals")
    # No sale line is known for this credit, and no lot carries this product's unit yet.
    section.get_by_role("button", name="Record return").click()
    expect(section.get_by_role("alert")).to_contain_text("unit")
    # Once the product has stock (so its unit is known), the return records.
    from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write

    with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_CREATE):
        db.add(
            InventoryItem(
                org_id=org.id, name="Dry gin 700ml", quantity=Decimal("10"), unit="each", inventory_type="final_product"
            )
        )
        db.commit()
    section.get_by_role("button", name="Record return").click()
    expect(section.get_by_text("2 of 3 already back")).to_be_visible()
    expect(section.get_by_label("How many Dry gin 700ml came back")).to_have_value("1")

    db.expire_all()
    ret = db.query(SalesReturn).filter(SalesReturn.org_id == org.id).one()
    assert (ret.condition, ret.quantity, ret.note) == ("damaged", Decimal("2.0000"), "Broken seals")
    assert (
        lot_holds.open_holds(db, org.id, [ret.resulting_lot_id])[ret.resulting_lot_id].reason
        == "Returned damaged: Broken seals"
    )

    screenshot_dir = os.environ.get("CRM_SHOTS_DIR")
    if screenshot_dir:
        destination = Path(screenshot_dir)
        destination.mkdir(parents=True, exist_ok=True)
        for name, width, theme_name in (
            ("desktop-light", 1440, "light"),
            ("phone-light", 390, "light"),
            ("desktop-dark", 1440, "dark"),
        ):
            page.set_viewport_size({"width": width, "height": 900 if width > 480 else 844})
            page.evaluate("mode => document.documentElement.setAttribute('data-spa-theme', mode)", theme_name)
            page.wait_for_timeout(300)
            section.screenshot(path=str(destination / f"goods-back-{name}.png"))

    section.get_by_label("Condition of returned Dry gin 700ml").select_option("destroyed")
    section.get_by_role("button", name="Record return").click()
    expect(section.get_by_text("No mapped credit-note lines need a return decision.")).to_be_visible()
