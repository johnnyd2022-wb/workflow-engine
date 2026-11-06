"""Plan item 1.1: owners choose how sales are matched to batches (FIFO, hybrid, manual)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.org_role import OrgRole
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.sales_traceability_config import SalesTraceabilityConfig
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
from app.features.crm.services.sales_traceability_service import SalesTraceabilityService
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export

PRODUCT = "Gin - final product"


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    repo = InventoryRepository(db)

    def lot(batch, qty, bottled_on):
        item = repo.create_inventory_item(
            org_id=org.id,
            name=PRODUCT,
            quantity=str(qty),
            unit="bottles",
            inventory_type=InventoryType.FINAL_PRODUCT.value,
            supplier_batch_number=batch,
            purchase_date=bottled_on,
            extra_data={"bottled_on": bottled_on.isoformat()},
            commit=True,
        )
        return item

    def mode(strategy, review_days=7):
        client.put(
            "/api/crm/traceability-config",
            json={"matching_strategy": strategy, "manual_review_days": review_days, "strict_mapping": False},
        )

    def invoice(day, qty, description="Gin 700ml"):
        inv = XeroInvoice(
            org_id=org.id,
            xero_invoice_id=f"inv-{uuid4()}",
            xero_tenant_id="t",
            invoice_type="ACCREC",
            status="AUTHORISED",
            invoice_number=f"INV-{uuid4().hex[:4]}",
            date=day,
        )
        db.add(inv)
        db.flush()
        line = XeroInvoiceLineItem(
            org_id=org.id,
            invoice_id=inv.id,
            xero_line_item_id=f"l-{uuid4()}",
            description=description,
            quantity=Decimal(qty),
        )
        db.add(line)
        db.commit()
        return inv, line

    def reconcile():
        summary = SalesTraceabilityService(db).reconcile_org(org.id)
        db.commit()
        return summary

    def allocations():
        return db.query(SalesFifoAllocation).filter(SalesFifoAllocation.org_id == org.id).all()

    def login_as(role):
        """A client signed in as a new person in this org; ``role`` is a built-in role or ``custom:<id>``."""
        email = f"matching-{uuid4()}@test.com"
        made = client.post("/org/users", json={"email": email, "password": DEFAULT_TEST_PASSWORD, "role": role})
        assert made.status_code == 201, made.get_json()
        person = flask_app.test_client()
        person.environ_base["wsgi.url_scheme"] = "https"
        person.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        signed_in = person.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD})
        assert signed_in.status_code == 200, signed_in.get_json()
        return person

    def custom_role(*permissions):
        name = f"Role {uuid4().hex[:6]}"
        made = client.post("/org/roles", json={"name": name, "base_role": "sales", "permissions": list(permissions)})
        assert made.status_code == 201, made.get_json()
        # The reply lists every custom role in the org, so pick this one out by name.
        return next(role["value"] for role in made.get_json()["custom_roles"] if role["name"] == name)

    client.post(
        "/api/crm/product-mappings",
        json={"biz_e_product_name": PRODUCT, "xero_description_pattern": "Gin 700ml", "match_type": "exact"},
    )
    yield {
        "org": org,
        "client": client,
        "login_as": login_as,
        "custom_role": custom_role,
        "lot": lot,
        "mode": mode,
        "invoice": invoice,
        "reconcile": reconcile,
        "allocations": allocations,
        "db": db,
    }

    db.rollback()
    db.query(User).filter(User.org_id == org.id).update({User.custom_role_id: None}, synchronize_session=False)
    db.query(OrgRole).filter(OrgRole.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    for model in (SalesFifoAllocation, XeroInvoiceLineItem, XeroInvoice, ProductMapping, SalesTraceabilityConfig):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    clear_org_synthetic_data(db, org.id)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def test_fifo_marks_a_presale_but_just_works(world):
    world["mode"]("fifo")
    world["lot"]("VAT44", 10, date(2026, 10, 20))  # bottled after the invoice
    world["invoice"](date(2026, 10, 5), "4")
    summary = world["reconcile"]()
    assert summary["allocated"] == 1 and summary["presold"] == 1
    (allocation,) = world["allocations"]()
    assert allocation.presold is True and allocation.status == "confirmed"


def test_hybrid_holds_presales_for_review_then_confirms_them(world):
    world["mode"]("hybrid", review_days=3)
    world["lot"]("VAT40", 10, date(2026, 9, 1))
    world["lot"]("VAT44", 10, date(2026, 10, 20))
    world["invoice"](date(2026, 10, 1), "4")  # VAT40 existed: normal
    presold_inv, _ = world["invoice"](date(2026, 10, 2), "10")  # needs VAT44: pre-sold
    world["reconcile"]()
    by_invoice = {}
    for a in world["allocations"]():
        by_invoice.setdefault(a.xero_invoice_id, []).append(a)
    statuses = {inv: {a.status for a in rows} for inv, rows in by_invoice.items()}
    assert statuses[presold_inv.xero_invoice_id] == {"pending_review"}
    assert sum(1 for s in statuses.values() if s == {"confirmed"}) == 1

    queue = world["client"].get("/api/crm/matching").get_json()
    assert queue["mode"] == "hybrid"
    (line,) = queue["pending_review"]
    assert line["presold"] is True and line["invoice_id"] == presold_inv.xero_invoice_id

    # After the review window, the match confirms itself on the next run.
    for a in by_invoice[presold_inv.xero_invoice_id]:
        a.review_due_at = datetime.now(UTC) - timedelta(minutes=1)
    world["db"].commit()
    summary = world["reconcile"]()
    assert summary.get("auto_confirmed") == 1
    assert {a.status for a in world["allocations"]()} == {"confirmed"}


def test_hybrid_reviews_loose_mappings_and_owner_can_confirm(world):
    world["mode"]("hybrid")
    world["client"].post(
        "/api/crm/product-mappings",
        json={"biz_e_product_name": PRODUCT, "xero_description_pattern": "Wildflower", "match_type": "contains"},
    )
    world["lot"]("VAT40", 10, date(2026, 9, 1))
    inv, line = world["invoice"](date(2026, 10, 1), "2", description="Whistlebird Wildflower 700ml - x1")
    world["reconcile"]()
    assert {a.status for a in world["allocations"]()} == {"pending_review"}
    ok = world["client"].post(
        "/api/crm/matching/confirm", json={"invoice_id": inv.xero_invoice_id, "line_key": line.xero_line_item_id}
    )
    assert ok.status_code == 200
    assert {a.status for a in world["allocations"]()} == {"confirmed"}


def test_manual_mode_waits_for_the_owner_to_pick_batches(world):
    world["mode"]("manual")
    old = world["lot"]("VAT40", 10, date(2026, 9, 1))
    new = world["lot"]("VAT44", 10, date(2026, 10, 20))
    inv, line = world["invoice"](date(2026, 10, 25), "6")
    summary = world["reconcile"]()
    assert summary.get("awaiting_assignment") == 1 and world["allocations"]() == []

    client = world["client"]
    queue = client.get("/api/crm/matching").get_json()
    assert [row["invoice_id"] for row in queue["to_assign"]] == [inv.xero_invoice_id]
    assert queue["to_assign"][0]["quantity"] == "6"

    candidates = client.get(f"/api/crm/matching/candidates?product={PRODUCT}").get_json()["batches"]
    assert [c["batch"] for c in candidates] == ["VAT40", "VAT44"]  # oldest first

    ref = {"invoice_id": inv.xero_invoice_id, "line_key": line.xero_line_item_id}
    short = client.post(
        "/api/crm/matching/assign", json={**ref, "picks": [{"inventory_item_id": str(new.id), "quantity": "5"}]}
    )
    assert short.status_code == 400 and "add up to 6" in short.get_json()["error"]
    too_much = client.post(
        "/api/crm/matching/assign", json={**ref, "picks": [{"inventory_item_id": str(old.id), "quantity": "11"}]}
    )
    assert too_much.status_code == 400

    ok = client.post(
        "/api/crm/matching/assign",
        json={
            **ref,
            "picks": [
                {"inventory_item_id": str(new.id), "quantity": "4"},
                {"inventory_item_id": str(old.id), "quantity": "2"},
            ],
        },
    )
    assert ok.status_code == 200, ok.get_json()
    rows = {str(a.inventory_item_id): Decimal(str(a.quantity)) for a in world["allocations"]()}
    assert rows == {str(new.id): 4, str(old.id): 2}
    db = world["db"]
    db.expire_all()
    assert Decimal(str(db.get(InventoryItem, new.id).quantity)) == 6
    # A later run leaves the owner's choice alone.
    assert world["reconcile"]().get("already_allocated") == 1


def test_owner_can_change_the_batch_on_an_automatic_match(world):
    world["mode"]("fifo")
    old = world["lot"]("VAT40", 10, date(2026, 9, 1))
    new = world["lot"]("VAT44", 10, date(2026, 9, 20))
    inv, line = world["invoice"](date(2026, 10, 1), "3")
    world["reconcile"]()
    assert {str(a.inventory_item_id) for a in world["allocations"]()} == {str(old.id)}  # FIFO took the oldest

    moved = world["client"].post(
        "/api/crm/matching/assign",
        json={
            "invoice_id": inv.xero_invoice_id,
            "line_key": line.xero_line_item_id,
            "picks": [{"inventory_item_id": str(new.id), "quantity": "3"}],
        },
    )
    assert moved.status_code == 200
    db = world["db"]
    db.expire_all()
    assert Decimal(str(db.get(InventoryItem, old.id).quantity)) == 10  # put back
    assert Decimal(str(db.get(InventoryItem, new.id).quantity)) == 7


def _stock(world, item):
    world["db"].expire_all()
    return Decimal(str(world["db"].get(InventoryItem, item.id).quantity))


def test_picking_a_batch_changes_stock_so_it_needs_inventory_adjust(world):
    """crm-security-audit F1: Sales holds sales.record but not inventory.adjust, and /assign moves stock."""
    world["mode"]("manual")
    lot = world["lot"]("VAT40", 10, date(2026, 9, 1))
    inv, line = world["invoice"](date(2026, 10, 25), "6")
    world["reconcile"]()
    pick = {
        "invoice_id": inv.xero_invoice_id,
        "line_key": line.xero_line_item_id,
        "picks": [{"inventory_item_id": str(lot.id), "quantity": "6"}],
    }

    sales = world["login_as"]("sales")
    denied = sales.post("/api/crm/matching/assign", json=pick)
    assert denied.status_code == 403 and denied.get_json()["code"] == "permission_denied"
    assert world["allocations"]() == [] and _stock(world, lot) == 10

    assert world["client"].post("/api/crm/matching/assign", json=pick).status_code == 200
    assert _stock(world, lot) == 4


def test_rerunning_matching_changes_stock_so_it_needs_inventory_adjust(world):
    world["mode"]("fifo")
    lot = world["lot"]("VAT40", 10, date(2026, 9, 1))
    world["invoice"](date(2026, 10, 1), "3")  # never reconciled: only a run will consume it

    denied = world["login_as"]("sales").post("/api/crm/matching/run")
    assert denied.status_code == 403 and denied.get_json()["code"] == "permission_denied"
    assert world["allocations"]() == [] and _stock(world, lot) == 10

    ran = world["client"].post("/api/crm/matching/run")
    assert ran.status_code == 200 and ran.get_json()["summary"]["allocated"] == 1
    assert _stock(world, lot) == 7


def test_sales_can_still_review_matching_without_moving_stock(world):
    world["mode"]("hybrid")
    world["client"].post(
        "/api/crm/product-mappings",
        json={"biz_e_product_name": PRODUCT, "xero_description_pattern": "Wildflower", "match_type": "contains"},
    )
    lot = world["lot"]("VAT40", 10, date(2026, 9, 1))
    inv, line = world["invoice"](date(2026, 10, 1), "2", description="Whistlebird Wildflower 700ml - x1")
    world["reconcile"]()

    sales = world["login_as"]("sales")
    queue = sales.get("/api/crm/matching")
    assert queue.status_code == 200 and len(queue.get_json()["pending_review"]) == 1
    assert sales.get(f"/api/crm/matching/candidates?product={PRODUCT}").status_code == 200
    confirmed = sales.post(
        "/api/crm/matching/confirm", json={"invoice_id": inv.xero_invoice_id, "line_key": line.xero_line_item_id}
    )
    assert confirmed.status_code == 200 and confirmed.get_json()["confirmed"] == 1
    assert _stock(world, lot) == 8  # the match already held these bottles; confirming moves nothing


def test_a_custom_role_needs_inventory_adjust_itself_to_drive_matching(world):
    """sales.manage (Xero, mappings) is not a stock permission, so it does not stand in for inventory.adjust."""
    world["mode"]("fifo")
    lot = world["lot"]("VAT40", 10, date(2026, 9, 1))
    world["invoice"](date(2026, 10, 1), "3")

    manager = world["login_as"](world["custom_role"]("sales.view", "sales.record", "sales.manage", "inventory.view"))
    assert manager.post("/api/crm/matching/run").status_code == 403
    assert _stock(world, lot) == 10

    keeper = world["login_as"](world["custom_role"]("sales.view", "sales.record", "inventory.view", "inventory.adjust"))
    assert keeper.post("/api/crm/matching/run").status_code == 200
    assert _stock(world, lot) == 7


def test_matching_page_only_offers_stock_changing_buttons_to_people_who_can_use_them(world):
    page = {"headers": {"Accept": "text/html"}}
    sales = world["login_as"]("sales").get("/crm/matching", **page)
    owner = world["client"].get("/crm/matching", **page)
    assert sales.status_code == 200 and owner.status_code == 200
    sales_html, owner_html = sales.get_data(as_text=True), owner.get_data(as_text=True)
    for button in (">Re-run matching</button>", ">Choose batch</button>", ">Change batch</button>"):
        assert button in owner_html, button
        assert button not in sales_html, button
    assert ">Looks right</button>" in sales_html  # confirming a match moves no stock, so Sales keeps it


def test_matching_page_needs_both_permissions_to_offer_the_buttons(world):
    """The server wants sales.record (policy table) and inventory.adjust (route check); can() is any-of,
    so a person holding only inventory.adjust must not be shown buttons that answer 403."""
    stock_only = world["login_as"](world["custom_role"]("sales.view", "inventory.view", "inventory.adjust"))
    resp = stock_only.get("/crm/matching", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    for button in (">Re-run matching</button>", ">Choose batch</button>", ">Change batch</button>"):
        assert button not in resp.get_data(as_text=True), button
    assert stock_only.post("/api/crm/matching/run").status_code == 403  # the policy table stops it first


def test_sale_nodes_carry_presold_and_review_status(world):
    from app.features.crm.services.sales_traceability_service import append_sales_to_dag

    world["mode"]("hybrid")
    lot = world["lot"]("VAT44", 10, date(2026, 10, 20))
    world["invoice"](date(2026, 10, 2), "1")
    world["reconcile"]()
    nodes, _edges = append_sales_to_dag(world["db"], world["org"].id, {str(lot.id)})
    (node,) = nodes
    assert node["presold"] is True and node["match_status"] == "pending_review"


# --- GL-S01 (founder, 2026-10-26): in FIFO mode a sale always takes its stock off ---------------


@pytest.fixture
def draft_invoice(world, monkeypatch):
    """A draft invoice that Xero authorises. The stubbed sync does what the real one ends with:
    reconcile every invoice against stock (XeroSyncService._sync_invoices)."""
    from app.features.crm.services.xero_api_client import XeroAPIClient
    from app.features.crm.services.xero_sync_service import XeroSyncService

    inv, _line = world["invoice"](date(2026, 10, 25), "4")
    inv.status = "DRAFT"
    world["db"].commit()
    monkeypatch.setattr(XeroAPIClient, "__init__", lambda self, db, org_id: None)
    monkeypatch.setattr(
        XeroAPIClient, "authorise_invoice", lambda self, xero_invoice_id: type("X", (), {"status": "AUTHORISED"})()
    )

    def sync(self, org_id, triggered_by="manual"):
        SalesTraceabilityService(self.db).reconcile_org(org_id)
        self.db.commit()

    monkeypatch.setattr(XeroSyncService, "incremental_sync", sync)
    return inv


def test_in_fifo_mode_a_sales_person_authorising_an_invoice_takes_its_stock_off(world, draft_invoice):
    world["mode"]("fifo")
    lot = world["lot"]("VAT40", 10, date(2026, 9, 1))
    sales = world["login_as"]("sales")  # sales.record, no inventory.adjust

    resp = sales.post(f"/api/crm/invoices/{draft_invoice.id}/authorise")
    assert resp.status_code == 200, resp.get_json()
    (allocation,) = world["allocations"]()
    assert allocation.inventory_item_id == lot.id and Decimal(str(allocation.quantity)) == 4
    assert _stock(world, lot) == 6


def test_in_manual_mode_authorising_leaves_stock_until_someone_with_stock_access_picks(world, draft_invoice):
    world["mode"]("manual")
    lot = world["lot"]("VAT40", 10, date(2026, 9, 1))
    sales = world["login_as"]("sales")

    assert sales.post(f"/api/crm/invoices/{draft_invoice.id}/authorise").status_code == 200
    assert world["allocations"]() == [] and _stock(world, lot) == 10
    queue = world["client"].get("/api/crm/matching").get_json()
    assert [row["invoice_id"] for row in queue["to_assign"]] == [draft_invoice.xero_invoice_id]


def test_the_sales_permission_says_an_invoice_takes_stock_off():
    from app.core.security.access_policy import PERMISSIONS

    assert "takes its stock off" in PERMISSIONS["sales.record"]


# --- SALES-PERM (2026-11-06, findings 0286511e / e085bb41): what sales.manage may do to stock ---


def _mode(world):
    return world["client"].get("/api/crm/traceability-config").get_json()["matching_strategy"]


def _manager(world):
    """Connects Xero and configures sales (sales.manage) but holds no stock permission."""
    return world["login_as"](world["custom_role"]("sales.view", "sales.record", "sales.manage", "inventory.view"))


def test_switching_manual_to_fifo_without_stock_access_is_refused_and_moves_nothing(world):
    world["mode"]("manual")
    lot = world["lot"]("VAT40", 10, date(2026, 9, 1))
    world["invoice"](date(2026, 10, 1), "3")
    world["reconcile"]()
    assert _stock(world, lot) == 10  # manual: the sale waits for someone to pick its batch

    manager = _manager(world)
    resp = manager.put(
        "/api/crm/traceability-config",
        json={"matching_strategy": "fifo", "manual_review_days": 7, "strict_mapping": False},
    )
    assert resp.status_code == 403, resp.get_json()
    assert resp.get_json()["code"] == "permission_denied"
    assert _mode(world) == "manual"
    world["reconcile"]()  # the next sync, whoever triggers it
    assert _stock(world, lot) == 10 and world["allocations"]() == []


def test_without_stock_access_the_other_matching_settings_still_save(world):
    world["mode"]("manual")
    manager = _manager(world)
    resp = manager.put(
        "/api/crm/traceability-config",
        json={"matching_strategy": "manual", "manual_review_days": 12, "strict_mapping": True},
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["manual_review_days"] == 12 and _mode(world) == "manual"


def test_with_stock_access_the_matching_mode_can_change(world):
    world["mode"]("manual")
    lot = world["lot"]("VAT40", 10, date(2026, 9, 1))
    world["invoice"](date(2026, 10, 1), "3")
    keeper = world["login_as"](
        world["custom_role"]("sales.view", "sales.record", "sales.manage", "inventory.view", "inventory.adjust")
    )
    resp = keeper.put(
        "/api/crm/traceability-config",
        json={"matching_strategy": "fifo", "manual_review_days": 7, "strict_mapping": False},
    )
    assert resp.status_code == 200, resp.get_json()
    world["reconcile"]()
    assert _stock(world, lot) == 7


def test_a_save_that_leaves_out_the_mode_keeps_it(world):
    """It used to fall back to fifo, which would also have slipped past the mode check."""
    world["mode"]("manual")
    manager = _manager(world)
    resp = manager.put("/api/crm/traceability-config", json={"task_done_archive_days": 9})
    assert resp.status_code == 200, resp.get_json()
    assert _mode(world) == "manual"


def test_in_fifo_mode_a_manual_xero_sync_under_sales_manage_applies_authorised_sales(world, monkeypatch):
    """e085bb41, decided: a sync only brings in sales Xero already holds, and applies them to stock
    as authorising does under sales.record (GL-S01). It is not a stock permission of its own."""
    from types import SimpleNamespace

    from app.features.crm.services.xero_sync_service import XeroSyncService

    def full_sync(self, org_id, triggered_by="manual"):
        summary = SalesTraceabilityService(self.db).reconcile_org(org_id)
        self.db.commit()
        return SimpleNamespace(
            success=True,
            partial=False,
            contacts_synced=0,
            invoices_synced=0,
            sales_allocated=summary.get("allocated", 0),
            sales_unmapped=0,
            sales_insufficient_stock=0,
            errors=[],
        )

    monkeypatch.setattr(XeroSyncService, "full_sync", full_sync)
    world["mode"]("fifo")
    lot = world["lot"]("VAT40", 10, date(2026, 9, 1))
    world["invoice"](date(2026, 10, 1), "3")

    manager = world["login_as"](world["custom_role"]("sales.view", "sales.manage", "inventory.view"))
    resp = manager.post("/api/crm/xero/sync")
    assert resp.status_code == 200, resp.get_json()
    assert _stock(world, lot) == 7


def test_the_settings_page_locks_the_matching_mode_without_stock_access(world):
    manager = _manager(world)
    page = manager.get("/crm/configuration").get_data(as_text=True)
    assert 'data-testid="matching-mode-locked"' in page
    assert 'value="fifo" x-model="draft.matching.mode" disabled' in page

    owner_page = world["client"].get("/crm/configuration").get_data(as_text=True)
    assert 'data-testid="matching-mode-locked"' not in owner_page
    assert 'value="fifo" x-model="draft.matching.mode">' in owner_page


def test_the_sales_manage_permission_says_what_it_does_to_stock():
    from app.core.security.access_policy import PERMISSIONS

    text = PERMISSIONS["sales.manage"]
    assert "applies authorised sales to stock" in text and "inventory.adjust" in text


def test_a_mode_change_committed_mid_request_is_not_overwritten_without_stock_access(world, monkeypatch):
    """Breaker review (!629): the mode check ran in the route, before and outside the write.

    A sales.manage-only person saves with the mode they saw (manual). Between the route's check
    and the write, someone allowed to commits fifo. Round 1 had already checked "manual" and wrote
    manual back over fifo (200). Now the check runs inside the write's transaction, after taking the
    config lock, against the committed fifo, and refuses.
    """
    from sqlalchemy import text
    from sqlalchemy.orm import Session as SASession

    from app.features.crm.services.crm_service import CRMService

    world["mode"]("manual")
    org_id = world["org"].id
    manager = _manager(world)

    original = CRMService.update_traceability_config

    def concurrent_fifo_then_save(self, *args, **kwargs):
        other = SASession(bind=world["db"].get_bind())
        try:
            other.execute(
                text("UPDATE crm_sales_traceability_config SET matching_strategy = 'fifo' WHERE org_id = :org"),
                {"org": org_id},
            )
            other.commit()
        finally:
            other.close()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(CRMService, "update_traceability_config", concurrent_fifo_then_save)
    resp = manager.put(
        "/api/crm/traceability-config",
        json={"matching_strategy": "manual", "manual_review_days": 7, "strict_mapping": False},
    )
    monkeypatch.undo()

    assert resp.status_code == 403, resp.get_json()
    assert _mode(world) == "fifo"


def test_two_first_saves_for_an_org_queue_on_the_config_lock(world):
    """No config row yet: FOR UPDATE has nothing to lock, so the advisory lock serialises them."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session as SASession

    from app.features.crm.models.sales_traceability_config import SalesTraceabilityConfig
    from app.features.crm.repositories.sales_traceability_repo import SalesTraceabilityConfigRepository

    org_id = world["org"].id
    world["db"].query(SalesTraceabilityConfig).filter(SalesTraceabilityConfig.org_id == org_id).delete()
    world["db"].commit()
    try_lock = text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))")
    key = {"key": f"crm_traceability_config:{org_id}"}

    first = SASession(bind=world["db"].get_bind())
    second = SASession(bind=world["db"].get_bind())
    try:
        assert SalesTraceabilityConfigRepository(first).lock_for_update(org_id) is None  # no row yet
        assert second.execute(try_lock, key).scalar() is False  # held by the first save
        first.rollback()  # first save ends
        assert second.execute(try_lock, key).scalar() is True
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()
