"""Browser pins for the remaining live-cogs purchase and inventory flows."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from app.features.costing.models import PurchaseAllocation, PurchaseDocument, PurchaseLine
from app.features.costing.purchase_sources import nz_today
from tests.costing_helpers import lot, lot_cost, price
from tests.e2e.conftest import csrf_headers, login_through_ui
from tests.e2e.test_costing_purchases_browser import _org_with_purchases

pytestmark = pytest.mark.e2e

PURCHASES = "/core/costing/purchases"


@pytest.fixture
def manager(fresh_user, page, app_url):
    user = fresh_user(UserRole.ADMIN)
    login_through_ui(page, user["email"], user["password"])
    return UUID(user["org_id"])


def _open_purchases(page, app_url):
    page.goto(app_url + PURCHASES)
    page.locator("[data-purchases-root][aria-busy='false']").wait_for()


def _refund_line(db, org_id, source_line):
    """Create a real open Xero refund line sharing the source account."""
    refund_doc = PurchaseDocument(
        org_id=org_id,
        source="xero_bank",
        external_id=f"e2e-refund-{uuid4()}",
        kind="refund",
        payee_name="Botanical Supply Co",
        document_date=nz_today(),
        currency_code="NZD",
        status="active",
        total_ex_tax=Decimal("20"),
        total_tax=Decimal("0"),
    )
    db.add(refund_doc)
    db.flush()
    refund = PurchaseLine(
        org_id=org_id,
        document_id=refund_doc.id,
        account_id=source_line.account_id,
        line_key=f"refund-{uuid4()}",
        position=0,
        fingerprint=f"refund-{uuid4().hex}",
        description="Returned juniper",
        account_code=source_line.account_code,
        account_name=source_line.account_name,
        amount_ex_tax=Decimal("-20"),
        tax_amount=Decimal("0"),
        treatment="stock",
        state="open",
    )
    db.add(refund)
    db.commit()
    return refund


def test_refund_picker_lowers_the_selected_lots_cost(manager, page, app_url, db):
    (source_line_id,) = _org_with_purchases(db, manager, ["40"])
    source_line = db.get(PurchaseLine, source_line_id)
    item = lot(db, manager, "Refund picker juniper", 2, "kg", purchase_date=nz_today())
    price(db, manager, item.id, 40, 2)
    refund = _refund_line(db, manager, source_line)

    _open_purchases(page, app_url)
    card = page.locator(".pu-card", has_text="Refund")
    card.get_by_role("button", name="Lower the cost of…").click()
    dialog = page.locator("[data-purchases-dialog]")
    expect(dialog.get_by_text("Refund picker juniper", exact=False)).to_be_visible()
    dialog.get_by_role("checkbox", name="Refund picker juniper").check()
    dialog.get_by_label("Amount for Refund picker juniper").fill("-10")
    dialog.locator("[data-dialog-save]").click()
    expect(dialog).to_be_hidden()

    assert Decimal(lot_cost(db, manager, item.id)["unit_cost"]) == Decimal("15")
    allocation = db.query(PurchaseAllocation).filter_by(org_id=manager, purchase_line_id=refund.id).one()
    assert Decimal(str(allocation.amount)) == Decimal("-10")


def test_already_in_stock_shows_quantity_and_links_without_creating_lot(manager, page, app_url, db):
    (line_id,) = _org_with_purchases(db, manager, ["30"])
    item = lot(db, manager, "Existing juniper lot", 7, "kg", purchase_date=nz_today())
    before_ids = {row[0] for row in db.query(PurchaseAllocation.inventory_item_id).all()}

    _open_purchases(page, app_url)
    page.locator(".pu-card").first.get_by_role("button", name="Already in stock").click()
    dialog = page.locator("[data-purchases-dialog]")
    expect(dialog.get_by_text("Existing juniper lot · 7 kg", exact=False)).to_be_visible()
    expect(dialog.get_by_label("Quantity of Existing juniper lot this paid for")).to_have_value("7")
    dialog.get_by_role("checkbox", name="Existing juniper lot").check()
    dialog.get_by_label("Amount for Existing juniper lot").fill("30")
    dialog.locator("[data-dialog-save]").click()
    expect(dialog).to_be_hidden()

    db.expire_all()
    assert (
        db.query(PurchaseAllocation).filter_by(org_id=manager, purchase_line_id=line_id).one().inventory_item_id
        == item.id
    )
    assert {row[0] for row in db.query(PurchaseAllocation.inventory_item_id).all()} == before_ids | {item.id}
    assert db.query(PurchaseLine).filter_by(org_id=manager, state="recorded").count() == 1


def test_edit_amounts_saves_and_reopens_with_the_recorded_value(manager, page, app_url, db):
    (line_id,) = _org_with_purchases(db, manager, ["40"])
    _open_purchases(page, app_url)
    dialog = page.locator("[data-purchases-dialog]")
    page.locator(".pu-card").first.get_by_role("button", name="Record stock").click()
    dialog.get_by_label("What").fill("Edited juniper")
    dialog.get_by_label("Quantity").fill("2")
    dialog.get_by_label("Unit").fill("kg")
    dialog.locator("[data-dialog-save]").click()
    expect(dialog).to_be_hidden()

    line = db.get(PurchaseLine, line_id)
    line.review_reason = "amount_changed"
    db.commit()
    page.reload()
    page.locator("[data-purchases-root][aria-busy='false']").wait_for()
    page.locator(".pu-card").first.get_by_role("button", name="Edit amounts").click()
    dialog.get_by_label("Amount for Edited juniper").fill("25")
    dialog.locator("[data-dialog-save]").click()
    expect(dialog).to_be_hidden()
    expect(page.locator("[data-purchases-toast]")).to_contain_text("Amounts updated")

    page.locator(".pu-card").first.get_by_role("button", name="Edit amounts").click()
    expect(dialog.get_by_label("Amount for Edited juniper")).to_have_value("25.00")
    db.expire_all()
    allocation = db.query(PurchaseAllocation).filter_by(org_id=manager, purchase_line_id=line_id).one()
    assert Decimal(str(allocation.amount)) == Decimal("25")


def test_record_dialog_focuses_first_field_and_cancel_and_escape_return_focus(manager, page, app_url, db):
    _org_with_purchases(db, manager, ["40"])
    _open_purchases(page, app_url)
    opener = page.locator(".pu-card").first.get_by_role("button", name="Record stock")
    opener.click()
    dialog = page.locator("[data-purchases-dialog]")
    expect(dialog.get_by_label("What")).to_be_focused()
    dialog.get_by_role("button", name="Cancel").click()
    expect(opener).to_be_focused()

    opener.click()
    expect(dialog.get_by_label("What")).to_be_focused()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(opener).to_be_focused()


def test_historical_run_can_return_to_the_new_purchase_list(manager, page, app_url, db):
    _org_with_purchases(db, manager, ["40"])
    _open_purchases(page, app_url)
    page.route("**/api/core/costing/purchases/historical-run", lambda route: route.fulfill(json={"documents": 0}))
    page.locator("[data-history-open]").click()
    dialog = page.locator("[data-history-dialog]")
    dialog.locator('[name="from"]').fill("2026-01-01")
    dialog.locator('[name="to"]').fill("2026-01-31")
    dialog.get_by_role("button", name="Load purchases").click()
    expect(dialog).to_be_hidden()
    expect(page.locator("[data-purchases-history]")).to_be_visible()
    expect(page.locator("[data-history-range]")).to_contain_text("Earlier purchases")
    page.locator("[data-history-exit]").click()
    expect(page.locator("[data-purchases-history]")).to_be_hidden()
    expect(page.locator("[data-purchases-root]")).to_have_attribute("aria-busy", "false")


def test_rules_conflict_focuses_and_marks_matchers_invalid(manager, page, app_url, db):
    _org_with_purchases(db, manager, [])
    page.goto(app_url + "/core/costing/rules")
    page.locator("[data-rules-root][aria-busy='false']").wait_for()
    add = page.locator("[data-rules-add]")
    add.click()
    dialog = page.locator("[data-rules-dialog]")
    payee = dialog.locator('[name="payee_pattern"]')
    payee.fill("Duplicate supplier")
    dialog.locator("[data-rules-save]").click()
    expect(dialog).to_be_hidden()

    add.click()
    payee = dialog.locator('[name="payee_pattern"]')
    payee.fill("Duplicate supplier")
    dialog.locator("[data-rules-save]").click()
    expect(dialog.locator("[data-rules-dialog-error]")).to_contain_text("exactly these purchases already exists")
    expect(payee).to_be_focused()
    expect(payee).to_have_attribute("aria-invalid", "true")
    expect(dialog.locator('[name="description_pattern"]')).to_have_attribute("aria-invalid", "true")
    expect(dialog.locator('[name="account_code"]')).to_have_attribute("aria-invalid", "true")


def test_csv_commit_replay_same_key_creates_rows_once(manager, page, app_url):
    page.goto(app_url + "/core/inventory/add/csv")
    key = str(uuid4())
    name = f"Concurrent CSV {uuid4().hex[:8]}"
    rows = [{"row_index": 2, "name": name, "quantity": "3", "unit": "kg"}]
    results = page.evaluate(
        """async ({key, rows}) => {
          const options = {method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name=csrf-token]').content,
              'Idempotency-Key': key}, body: JSON.stringify({rows})};
          const first = await fetch('/api/core/inventory/csv-commit', options);
          const firstResult = {status: first.status, body: await first.json(), replay: first.headers.get('Idempotent-Replay')};
          const second = await fetch('/api/core/inventory/csv-commit', options);
          const secondResult = {status: second.status, body: await second.json(), replay: second.headers.get('Idempotent-Replay')};
          return [firstResult, secondResult];
        }""",
        {"key": key, "rows": rows},
    )
    assert [result["status"] for result in results] == [200, 200]
    assert sorted(result["replay"] == "true" for result in results) == [False, True]
    assert all(len(result["body"]["created"]) == 1 for result in results)
    inventory = page.request.get("/api/core/inventory")
    assert inventory.status == 200
    matches = [item for item in inventory.json()["inventory_items"] if item["name"] == name]
    assert len(matches) == 1


def test_csv_review_locks_add_button_after_first_activation(manager, page, app_url):
    page.goto(app_url + "/core/inventory/add/csv")
    page.locator("#csv-file-input").set_input_files(
        {
            "name": "one-row.csv",
            "mimeType": "text/csv",
            "buffer": b"Item Name,Quantity,Unit\nCSV review lock,1,kg\n",
        }
    )
    add = page.locator("#csv-review-accept")
    expect(add).to_be_visible()
    add.click()
    expect(add).to_be_disabled()


def test_concurrent_barcode_deliveries_with_distinct_keys_both_add_quantity(manager, page, app_url):
    page.goto(app_url + "/core/inventory/add/barcode")
    headers = csrf_headers(page)
    name = f"Concurrent barcode {uuid4().hex[:8]}"
    barcode = f"BC-{uuid4().hex[:12]}"
    initial = page.request.post(
        "/api/core/inventory",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        data={"name": name, "quantity": "5", "unit": "kg", "barcode": barcode},
    )
    assert initial.status in (200, 201), initial.text()
    keys = [str(uuid4()), str(uuid4())]
    payloads = [
        {"name": name, "quantity": quantity, "unit": "kg", "barcode": barcode, "source_method": "barcode_scan"}
        for quantity in ("2", "3")
    ]
    results = page.evaluate(
        """async ({keys, payloads}) => Promise.all(payloads.map((body, index) => fetch('/api/core/inventory', {
          method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('meta[name=csrf-token]').content, 'Idempotency-Key': keys[index]},
          body: JSON.stringify(body)
        }).then(async response => ({status: response.status, body: await response.json()}))))""",
        {"keys": keys, "payloads": payloads},
    )
    assert [result["status"] for result in results] == [200, 200], results
    listing = page.request.get("/api/core/inventory")
    assert listing.status == 200
    items = [item for item in listing.json()["inventory_items"] if item["barcode"] == barcode]
    assert len(items) == 1
    assert Decimal(str(items[0]["quantity"])) == Decimal("10")
