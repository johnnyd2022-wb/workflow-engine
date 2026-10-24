#!/usr/bin/env python3
"""Screenshot harness for page design work (the page-design skill).

Looking at a page is the only way to judge it, and a design pass needs the same views
re-shot after every change. This seeds a throwaway org with realistic stock, boots the
app from the current checkout over TLS (the same in-process boot tests/e2e/conftest.py
uses), signs in through the real login form, and runs screenshot scenarios you write.

Run from the checkout whose code you want to see, with ENVIRONMENT unset (local.ini, the
test database on :8401):

    env -u ENVIRONMENT uv run python scripts/ui_shots.py seed stock lineage [compliance]
    env -u ENVIRONMENT uv run python scripts/ui_shots.py shoot OUT --scenarios FILE [NAME ...]
    env -u ENVIRONMENT uv run python scripts/ui_shots.py upload OUT/a.png OUT/b.png
    env -u ENVIRONMENT uv run python scripts/ui_shots.py purge
    env -u ENVIRONMENT uv run python scripts/ui_shots.py status [--json]

The app logs every request to stdout; this script's own lines start with "ui-shots:", so
pipe through `grep '^ui-shots:'` to read just the result.

A scenario file is a Python module of functions taking (page, out). `shoot` runs the names
given, or every public function in file order. See
.claude/skills/page-design/scenarios.example.py.

Exit codes: 0 ok; 1 a scenario failed or the page logged a console error; 2 usage or
state problem (nothing seeded, already seeded, wrong environment).
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import json
import os
import pkgutil
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("UI_SHOTS_HOME", Path.home() / ".cache" / "workflow-engine-ui-shots"))
STATE = HOME / "state.json"
ORG_PREFIX = "UI Shots "
SEED_KINDS = (
    "stock",
    "lineage",
    "compliance",
    "production",
    "sales",
    "planner",
    "board",
    "contracts",
    "stocktake",
    "customers",
    "suppliers",
    "excise",
    "np3",
    "customer",
)


def say(*parts) -> None:
    print("ui-shots:", *parts, flush=True)


def _require_local() -> None:
    """The seed writes rows and the purge deletes them: only ever against the local test database."""
    env = os.getenv("ENVIRONMENT", "local")
    if env != "local":
        say(f"refusing to run with ENVIRONMENT={env}; unset it (env -u ENVIRONMENT ...)")
        raise SystemExit(2)


def _state() -> dict:
    if not STATE.exists():
        say("nothing seeded; run `seed` first")
        raise SystemExit(2)
    return json.loads(STATE.read_text())


# ── Helpers for scenario files ──────────────────────────────────────────────────────────


def settle(page, extra_ms: int = 400) -> None:
    """Wait for the network to go quiet, then a beat for the last render."""
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(extra_ms)


def shot(page, out: Path, name: str, *, full: bool = False) -> Path:
    """Save OUT/<name>.png. `full` captures the whole scroll height (the fixed shell repeats in it)."""
    path = Path(out) / f"{name}.png"
    page.screenshot(path=str(path), full_page=full)
    return path


def theme(page, mode: str) -> None:
    """Switch the app shell between "light" and "dark" without a reload."""
    page.evaluate("mode => document.documentElement.setAttribute('data-spa-theme', mode)", mode)
    page.wait_for_timeout(300)


DESKTOP = {"width": 1440, "height": 900}
TABLET = {"width": 1024, "height": 800}
PHONE = {"width": 390, "height": 844}
WALL = {"width": 1920, "height": 1080}  # a TV on the wall


# ── Seeding ─────────────────────────────────────────────────────────────────────────────


def _seed_stock(db, org_id, inv) -> None:
    """Raw, intermediate and finished lines with suppliers, batches, expiries and quantity history."""
    today = date.today()

    def day(offset):
        return today + timedelta(days=offset) if offset is not None else None

    raw = [
        ("Juniper berries", "18.5", "kg", "Davis Trading", "JB-2291", 40, 320),
        ("Juniper berries", "4.2", "kg", "Davis Trading", "JB-2104", 190, 21),
        ("Coriander seed", "9", "kg", "Davis Trading", "CS-0931", 62, 410),
        ("Angelica root", "2.75", "kg", "Moore Wilson", "AR-7710", 120, -6),
        ("Orris root powder", "1.1", "kg", "Moore Wilson", "OR-5512", 88, 240),
        ("Dried orange peel", "3.4", "kg", "Moore Wilson", "OP-1180", 30, 150),
        ("Kawakawa leaf", "0.85", "kg", "Wairarapa Foragers", "KK-0044", 12, 9),
        ("Cardamom pods", "0.6", "kg", "Moore Wilson", "CP-8801", 200, -31),
        ("Lemon myrtle", "0.4", "kg", "Wairarapa Foragers", None, 20, 60),
        ("Neutral grain spirit 96%", "820", "L", "Pure Spirits NZ", "NGS-240917", 22, None),
        ("Demineralised water", "1200", "L", None, None, 5, None),
        ("Glass bottle 700 mL", "2880", "units", "Glassworks Pacific", "GB-700-118", 48, None),
        ("Natural cork stopper", "3400", "units", "Corticeira Imports", "NC-5521", 110, None),
        ("Front label — Dry Gin", "2100", "units", "Print House Wellington", "LBL-DG-17", 34, None),
        ("Shipping carton 6-pack", "410", "units", "Opal Packaging", "SC6-3301", 60, None),
        ("Tamper seal", "5200", "units", "Opal Packaging", None, 60, None),
    ]
    made = [
        ("Rested gin 42%", "412", "L", "work_in_progress", "Dry Gin", "Dilute and rest"),
        ("Honey liqueur base", "64", "L", "work_in_progress", "Manuka Honey Liqueur", "Blend"),
        ("Whistlebird Navy Strength 700 mL", "144", "units", "final_product", "Navy Strength Gin", "Bottle and label"),
        ("Manuka Honey Liqueur 500 mL", "96", "units", "final_product", "Manuka Honey Liqueur", "Bottle and label"),
    ]
    created = []
    for name, qty, unit, supplier, batch, bought, expires in raw:
        created.append(
            inv.create_inventory_item(
                org_id,
                name,
                qty,
                unit,
                "raw_material",
                supplier=supplier,
                supplier_batch_number=batch,
                purchase_date=day(-bought),
                expiry_date=day(expires),
            )
        )
    for name, qty, unit, kind, process, step in made:
        created.append(
            inv.create_inventory_item(
                org_id,
                name,
                qty,
                unit,
                kind,
                source_step_name=step,
                extra_data={"producing_process_name": process, "producing_step_name": step},
            )
        )
    # A few edits each, so trend lines have something to draw. Every third line is left flat.
    for index, item in enumerate(created):
        if index % 3 == 2:
            continue
        final = Decimal(str(item.quantity))
        whole = item.unit == "units"
        for factor in ("1.9", "1.6", "1.35", "1.1", "1"):
            value = final * Decimal(factor)
            inv.update_inventory_item(item.id, org_id, quantity=str(value.quantize(Decimal("1" if whole else "0.1"))))
    db.commit()


def _seed_lineage(db, org_id, inv) -> None:
    """Two gin batches sharing a juniper lot, through three steps, sold on six invoices to four customers."""
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.process import ProcessCategory
    from app.core.db.repositories.execution_repo import ExecutionRepository
    from app.core.db.repositories.process_repo import ProcessRepository
    from app.features.crm.models.product_mapping import ProductMapping  # noqa: F401 -- FK target
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice
    from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem

    procs, execs = ProcessRepository(db), ExecutionRepository(db)
    today = date.today()
    product = "Whistlebird Dry Gin 700 mL"

    def raw(name, qty, unit, supplier, batch, bought, expires=None):
        return inv.create_inventory_item(
            org_id,
            name,
            qty,
            unit,
            "raw_material",
            supplier=supplier,
            supplier_batch_number=batch,
            purchase_date=today - timedelta(days=bought),
            expiry_date=(today + timedelta(days=expires)) if expires is not None else None,
        )

    juniper_fresh = raw("Juniper berries", "12", "kg", "Davis Trading", "JB-3301", 60, 320)
    juniper_old = raw("Juniper berries", "3.5", "kg", "Davis Trading", "JB-3188", 190, -4)
    coriander = raw("Coriander seed", "7", "kg", "Davis Trading", "CS-1042", 62, 410)
    spirit = raw("Neutral grain spirit 96%", "640", "L", "Pure Spirits NZ", "NGS-241003", 45)
    bottles = raw("Glass bottle 700 mL", "2400", "units", "Glassworks Pacific", "GB-700-131", 48)
    labels = raw("Front label — Dry Gin", "1900", "units", "Print House Wellington", "LBL-DG-21", 34)

    steps = [
        ("Macerate botanicals", "Botanical maceration", 185, "L"),
        ("Distil", "Gin distillate 78%", 120, "L"),
        ("Bottle and label", product, 300, "units"),
    ]
    process = procs.create_process(
        org_id, "Whistlebird Dry Gin", category=ProcessCategory.MANUFACTURING, is_draft=False
    )
    for number, (step_name, output, qty, unit) in enumerate(steps, start=1):
        procs.add_step(
            process_id=process.id,
            org_id=org_id,
            step_number=number,
            position=number * 1000,
            name=step_name,
            inputs=[],
            outputs=[{"name": output, "quantity": qty, "unit": unit}],
        )
    db.commit()

    def ref(item, qty, unit):
        return {"name": item.name, "quantity": qty, "unit": unit, "inventory_item_id": str(item.id)}

    def batch(code, juniper, bottled):
        execution = execs.create_execution(org_id, process.id)
        rows = (
            db.query(ExecutionStep)
            .filter(ExecutionStep.execution_id == execution.id)
            .order_by(ExecutionStep.step_number)
            .all()
        )

        def made(index, qty, kind, prefix):
            _step, name, _qty, unit = steps[index]
            return inv.create_inventory_item(
                org_id,
                name,
                str(qty),
                unit,
                kind,
                supplier_batch_number=f"{prefix}-{code}",
                source_execution_id=execution.id,
                source_execution_step_id=rows[index].id,
                source_step_name=steps[index][0],
            )

        execs.complete_step(
            rows[0].id,
            org_id,
            actual_inputs=[
                ref(juniper, 4, "kg"),
                ref(juniper_fresh, 1, "kg"),
                ref(coriander, 2, "kg"),
                ref(spirit, 180, "L"),
            ],
            actual_outputs=[{"name": steps[0][1], "quantity": 185, "unit": "L"}],
        )
        maceration = made(0, 185, "work_in_progress", "MAC")
        execs.complete_step(
            rows[1].id,
            org_id,
            actual_inputs=[ref(maceration, 185, "L")],
            actual_outputs=[{"name": steps[1][1], "quantity": 120, "unit": "L"}],
        )
        distillate = made(1, 120, "work_in_progress", "DIS")
        execs.complete_step(
            rows[2].id,
            org_id,
            actual_inputs=[ref(distillate, 120, "L"), ref(bottles, bottled, "units"), ref(labels, bottled, "units")],
            actual_outputs=[{"name": product, "quantity": bottled, "unit": "units"}],
        )
        made(2, bottled, "final_product", "WDG")
        db.commit()

    batch("2609", juniper_fresh, 300)
    batch("2610", juniper_old, 288)

    contacts = []
    for name, email, phone in [
        ("Regional Wines & Spirits", "orders@regionalwines.example", "04 385 6952"),
        ("Hawthorn Lounge", "sam@hawthorn.example", "021 555 0142"),
        ("Moore Wilson's Fresh", "priya@moorewilsons.example", None),
        ("The Bottle-O Greytown", None, None),
    ]:
        contact = XeroContact(
            org_id=org_id,
            xero_contact_id=str(uuid.uuid4()),
            xero_tenant_id="ui-shots",
            name=name,
            email_address=email,
            phone_number=phone,
        )
        db.add(contact)
        contacts.append(contact)
    db.commit()

    sales = [(0, 120, 12), (1, 24, 9), (2, 60, 6), (0, 96, 4), (3, 36, 2), (1, 48, 1)]
    for number, (who, qty, days_ago) in enumerate(sales, start=1):
        invoice_number = f"INV-{1040 + number}"
        invoice = XeroInvoice(
            org_id=org_id,
            xero_invoice_id=str(uuid.uuid4()),
            xero_tenant_id="ui-shots",
            contact_id=contacts[who].id,
            invoice_number=invoice_number,
            invoice_type="ACCREC",
            status="AUTHORISED",
            date=today - timedelta(days=days_ago),
        )
        db.add(invoice)
        db.flush()
        db.add(
            XeroInvoiceLineItem(
                org_id=org_id, invoice_id=invoice.id, xero_line_item_id="L1", description=product, quantity=qty
            )
        )
        for allocation in inv.consume_final_product_fifo(
            org_id, product, str(qty), reference=invoice_number, commit=False
        ):
            db.add(
                SalesFifoAllocation(
                    org_id=org_id,
                    xero_invoice_id=invoice.xero_invoice_id,
                    xero_line_key="L1",
                    inventory_item_id=uuid.UUID(allocation["inventory_item_id"]),
                    product_name=product,
                    quantity=Decimal(allocation["quantity_consumed"]),
                    unit="units",
                )
            )
        db.commit()


def _seed_sales(db, org_id, inv) -> None:
    """Six months of local sales, receivables and realistic customer follow-ups."""
    from app.features.crm.models.crm_task import CRMTask
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice
    from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem

    contacts = db.query(XeroContact).filter(XeroContact.org_id == org_id).order_by(XeroContact.name).all()
    if not contacts:
        raise ValueError("sales requires the lineage seed for realistic customer contacts")
    today = date.today()
    invoices = db.query(XeroInvoice).filter(XeroInvoice.org_id == org_id).all()
    for number, invoice in enumerate(invoices):
        invoice.sub_total = Decimal(900 + number * 225)
        invoice.total_tax = invoice.sub_total * Decimal("0.15")
        invoice.total = invoice.sub_total + invoice.total_tax
        invoice.amount_due = invoice.total if number % 2 else Decimal(0)
        invoice.amount_paid = invoice.total - invoice.amount_due
        invoice.due_date = today + timedelta(days=7 - number * 2)
        for line in db.query(XeroInvoiceLineItem).filter(XeroInvoiceLineItem.invoice_id == invoice.id).all():
            line.line_amount = invoice.sub_total
            line.unit_amount = invoice.sub_total / line.quantity
    for months_back in range(1, 6):
        serial = today.year * 12 + today.month - 1 - months_back
        month_date = date(serial // 12, serial % 12 + 1, 8)
        db.add(
            XeroInvoice(
                org_id=org_id,
                xero_invoice_id=str(uuid.uuid4()),
                xero_tenant_id="ui-shots",
                contact_id=contacts[months_back % len(contacts)].id,
                invoice_type="ACCREC",
                invoice_number=f"INV-{1030 - months_back}",
                status="PAID",
                date=month_date,
                sub_total=Decimal(6500 + months_back * 850),
                total=Decimal(6500 + months_back * 850),
                amount_paid=Decimal(6500 + months_back * 850),
                amount_due=Decimal(0),
            )
        )
    for number, (title, status, priority, due) in enumerate(
        [
            ("Confirm summer gin order — Regional Wines", "pending", "high", -1),
            ("Send cocktail range samples — Hawthorn Lounge", "pending", "medium", 2),
            ("Follow up tasting — Moore Wilson’s", "pending", "medium", 4),
            ("Agree delivery window — Bottle-O Greytown", "in_progress", "high", 0),
            ("Review wholesale price list", "in_progress", "medium", 5),
        ]
    ):
        db.add(
            CRMTask(
                org_id=org_id,
                contact_id=contacts[number % len(contacts)].id,
                title=title,
                description="Customer follow-up for the next wholesale order.",
                status=status,
                priority=priority,
                due_date=today + timedelta(days=due),
            )
        )
    db.commit()


def _seed_customer(db, org_id, inv) -> None:
    """One customer as a sales rep knows them after a year: contact details and addresses,
    a 20th-of-the-month payment term, notes from calls and tastings, and follow-ups open
    and done. Uses the customer with the most invoices from the lineage and sales seeds."""
    from datetime import UTC, datetime

    from sqlalchemy import func

    from app.core.db.models.user import User
    from app.features.crm.models.crm_note import CRMNote
    from app.features.crm.models.crm_task import CRMTask
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice

    top = (
        db.query(XeroInvoice.contact_id, func.count(XeroInvoice.id))
        .filter(XeroInvoice.org_id == org_id)
        .group_by(XeroInvoice.contact_id)
        .order_by(func.count(XeroInvoice.id).desc())
        .first()
    )
    if top is None:
        raise ValueError("customer requires the lineage and sales seeds for invoices")
    contact = db.get(XeroContact, top[0])
    user = db.query(User).filter(User.org_id == org_id).first()
    user.first_name, user.last_name = "Jordan", "Lee"
    contact.first_name, contact.last_name = "Aroha", "Wilson"
    contact.email_address, contact.phone_number = "aroha@moorewilsons.example", "04 385 6952"
    contact.contact_status = "ACTIVE"
    contact.payment_terms = {"sales": {"day": 20, "type": "OFFOLLOWINGMONTH"}}
    contact.addresses = [
        {
            "type": "POBOX",
            "line1": "PO Box 3210",
            "city": "Wellington",
            "postal_code": "6140",
            "country": "New Zealand",
        },
        {
            "type": "STREET",
            "line1": "15 Ellice Street",
            "line2": "Mount Victoria",
            "city": "Wellington",
            "postal_code": "6011",
            "country": "New Zealand",
        },
    ]
    now = datetime.now(UTC)
    for days, text in (
        (2, "Called Aroha: summer order likely to double last year's. Wants the Navy Strength in 500 ml."),
        (16, "Tasting with the shop team went well; they'll put the gin in the front fridge."),
        (41, "Pays on the 20th of the month after. Prefers invoices emailed to accounts@."),
        (90, "First order. Met at the Harbourside Market."),
    ):
        db.add(
            CRMNote(
                org_id=org_id,
                contact_id=contact.id,
                content=text,
                created_by_user_id=user.id,
                created_at=now - timedelta(days=days),
                updated_at=now - timedelta(days=days),
            )
        )
    today = date.today()
    for title, status, priority, due, done in (
        ("Send the summer price list", "pending", "high", 1, None),
        ("Drop off a Navy Strength sample", "in_progress", "medium", 4, None),
        ("Check the front-fridge placement", "pending", "low", 12, None),
        ("Book the staff tasting", "completed", "medium", -14, 15),
    ):
        db.add(
            CRMTask(
                org_id=org_id,
                contact_id=contact.id,
                title=title,
                status=status,
                priority=priority,
                due_date=today + timedelta(days=due),
                assigned_to_user_id=user.id,
                created_by_user_id=user.id,
                completed_at=now - timedelta(days=done) if done else None,
            )
        )
    db.commit()


def _seed_suppliers(db, org_id, inv) -> None:
    """Supplier records for the names `stock` puts on its lines, some with every detail and some
    missing a phone, email or address, plus one with no stock yet. Corticeira Imports is left
    off on purpose, so "Import from inventory" has a name to add. Seed after `stock`."""
    from app.core.db.models.supplier import Supplier

    rows = [
        (
            "Davis Trading",
            "Priya Shah",
            "04 384 2210",
            "orders@davistrading.co.nz",
            "12 Kingsford Smith St, Rongotai, Wellington 6022",
            "Botanicals by the kilo. Order by Tuesday for Thursday delivery.",
        ),
        (
            "Moore Wilson",
            None,
            "04 384 9906",
            None,
            "Corner Tory and College St, Te Aro, Wellington 6011",
            "Cash-and-carry. Trade card under the company name.",
        ),
        (
            "Wairarapa Foragers",
            "Hemi Walker",
            "027 455 0193",
            "hemi@wairarapaforagers.nz",
            None,
            "Kawakawa and lemon myrtle in season. Text before you visit.",
        ),
        (
            "Pure Spirits NZ",
            "Accounts team",
            "09 270 4410",
            "trade@purespirits.co.nz",
            "48 Kerwyn Ave, East Tamaki, Auckland 2013",
            "Neutral spirit in 1000 L IBCs. Excise paid on dispatch.",
        ),
        (
            "Glassworks Pacific",
            "Daniel Ng",
            None,
            "daniel.ng@glassworkspacific.com",
            "Unit 4, 9 Mahunga Dr, Mangere Bridge, Auckland 2022",
            None,
        ),
        ("Print House Wellington", None, None, None, None, None),
        (
            "Opal Packaging",
            "Sales desk",
            "0800 676 251",
            "sales@opalpackaging.co.nz",
            "1 Opal Rd, Penrose, Auckland 1061",
            "Cartons on a 10-day lead time.",
        ),
        (
            "Southern Hops Ltd",
            "Kate Moreau",
            "03 545 1288",
            "kate@southernhops.co.nz",
            "220 Main Rd, Riwaka, Motueka 7198",
            "Trial order for a hopped gin. Nothing bought yet.",
        ),
    ]
    for name, contact, phone, email, address, notes in rows:
        db.add(
            Supplier(
                org_id=org_id, name=name, contact_name=contact, phone=phone, email=email, address=address, notes=notes
            )
        )
    db.commit()


def _seed_customers(db, org_id, inv) -> None:
    """A fictional trade directory with complete, missing, archived and unsent contacts.

    Works alone; use lineage + sales first when customer activity is also needed.
    Every address is reserved .example data. No Xero connection or API call is made.
    """
    from app.core.utils.time import utc_now
    from app.features.crm.models.xero_contact import XeroContact

    names = [
        "Aro Valley Wine Bar",
        "Beacon Bottle Shop",
        "Coastal Kitchen",
        "Dune Trading Co.",
        "Elm & Harbour Hospitality",
        "Fernhill Lodge",
        "Golden Bay Grocer",
        "Hilltop Cellar",
        "Island Social Club",
        "Juniper House",
        "Kererū Botanicals",
        "Laneway Drinks",
        "Mānuka Restaurant",
        "North Wharf Hotel",
        "Orchard Lane",
        "Portside Provisions",
        "Quay Street Deli",
        "Riverbend Retreat",
        "Southern Table",
        "The Long Afternoon",
    ]
    for index, name in enumerate(names):
        local = index % 5 == 0
        db.add(
            XeroContact(
                org_id=org_id,
                name=name,
                source="bize" if local else "xero",
                xero_contact_id=None if local else str(uuid.uuid4()),
                xero_tenant_id=None if local else "ui-shots",
                email_address=None if index % 6 == 0 else f"orders@customer-{index + 1}.example",
                phone_number=None if index % 7 == 0 else f"021 555 {1000 + index}",
                contact_status="ARCHIVED" if index in (3, 12, 18) else "ACTIVE",
                last_synced_at=None if local else utc_now() - timedelta(days=index % 9),
                xero_push_status="failed" if index == 10 else None,
                xero_push_error="Fixture: connection unavailable" if index == 10 else None,
            )
        )
    db.commit()


def _seed_compliance(db, org_id, inv) -> None:
    """Subscribe the org to Compliance and put it on the NP3 food control programme, so pages
    that summarise compliance (the dashboard) have a module with a score to show."""
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.compliant.models import ComplianceProfile

    FeatureSubscriptionRepository(db).grant(org_id, "compliant")
    profile = db.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).one_or_none()
    if profile is None:
        profile = ComplianceProfile(org_id=org_id)
        db.add(profile)
    profile.enabled = True
    profile.settings = {
        **(profile.settings or {}),
        "alcohol_product_types": ["spirits"],
        "food_control_programme": "np3",
    }
    db.commit()


def _seed_np3(db, org_id, inv) -> None:
    """NP3 food safety evidence in the shape a working distillery has after a year: most
    checks signed off (some overdue, some due within the month, a fifth never done), cleaning,
    pest and receiving logs with one follow-up still open, a training register, and an
    acceptable verification nine months ago with one corrective action outstanding."""
    from datetime import UTC, datetime

    from app.core.db.models.user import User
    from app.features.compliant.models import ComplianceProfile
    from app.features.compliant.models.compliance_record import ComplianceRecord
    from app.features.compliant.modules.nz_alcohol import verification
    from app.features.compliant.modules.nz_alcohol.np3_audit import NP3_AUDIT_CATEGORIES, np3_log_template

    profile = db.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).one_or_none()
    if profile is None:
        raise ValueError("np3 requires the compliance seed")
    user = db.query(User).filter(User.org_id == org_id).first()
    user.first_name, user.last_name = "Jordan", "Lee"  # a name, not an email, on every record
    today = date.today()

    def at(day: date) -> datetime:
        return datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=9)

    def add(control_id, record_type, status, title, created, due=None, details=None, period=None):
        db.add(
            ComplianceRecord(
                org_id=org_id,
                framework_slug="np3-food-control",
                control_id=control_id,
                record_type=record_type,
                status=status,
                title=title,
                period_start=period,
                due_date=due,
                source_refs=[],
                details=details or {},
                created_by_user_id=user.id,
                owner_user_id=user.id if record_type != "attestation" else None,
                created_at=at(created),
                updated_at=at(created),
            )
        )

    seen = []
    for _section, controls in NP3_AUDIT_CATEGORIES:
        for control_id, title in controls:
            if control_id not in [c for c, _t in seen]:
                seen.append((control_id, title))
    for number, (control_id, title) in enumerate(seen):
        kind = number % 5
        if kind == 0:
            continue  # never signed off
        signed = today - timedelta(days={1: 215, 2: 160}.get(kind, 30 + number * 3))
        due = {1: today - timedelta(days=20 + number), 2: today + timedelta(days=9 + number % 14)}.get(
            kind, today + timedelta(days=120 + number * 2)
        )
        add(
            control_id,
            "attestation",
            "complete",
            f"NP3 review: {title}",
            signed,
            due,
            {
                "how_we_meet": f"{title}: checked against our written routine and the records kept on the shared drive.",
                "review_interval_months": 6,
                "np3_guidance_version": "2025-v2",
                "attestation_confirmed": True,
                "evidence_fields": {},
            },
        )

    def log_fields(control_id, day, follow_up=False):
        template = np3_log_template(control_id)
        fields = {}
        for field in template["fields"]:
            kind = field.get("type")
            if kind == "date":
                fields[field["key"]] = day.isoformat()
            elif kind == "select":
                options = [o[0] for o in field.get("options", ())]
                pick = "action-required" if follow_up and "action-required" in options else options[0]
                fields[field["key"]] = pick
            elif kind == "user":
                fields[field["key"]] = str(user.id)
            elif kind == "person":
                fields[field["key"]] = ("Aroha Ngata", "Jordan Lee", "Sam Patel")[day.day % 3]
            elif field.get("required") or field["key"] in ("corrective_action", "cause_and_action", "notes"):
                key = field["key"]
                fields[key] = {
                    "corrective_action": "Bait station B2 replaced; floor drain resealed.",
                    "cause_and_action": "Seal on the cold store door split; replacement ordered.",
                }.get(key) or next(
                    (
                        value
                        for word, value in (
                            ("area", ("Bottling line", "Still room floor", "Botanicals store")[day.day % 3]),
                            ("equipment", ("Bottling line", "Still room floor", "Botanicals store")[day.day % 3]),
                            ("method", "Hot water rinse, then food-grade sanitiser at label strength"),
                            ("supplier", ("Moore Wilson's", "Davis Trading", "Hawke's Bay Botanicals")[day.day % 3]),
                            (
                                "product",
                                ("Juniper berries 5 kg", "Neutral spirit 200 L", "Glass 700 mL x 600")[day.day % 3],
                            ),
                            ("pest", "Rodent bait stations B1-B4 checked"),
                            ("location", "Bait stations B1-B4"),
                            ("finding", "No activity"),
                            ("temperature", "4.2 °C"),
                        )
                        if word in key
                    ),
                    "Checked by the duty manager",
                )
        return template, fields

    for control_id, days in (
        ("cleaning-and-hygiene", (3, 10, 17, 24, 38, 52)),
        ("pest-animal-control", (6, 36, 66)),
        ("receiving-food", (2, 9, 23, 41)),
        ("staff-competency", (14, 120)),
    ):
        for position, back in enumerate(days):
            day = today - timedelta(days=back)
            follow_up = control_id == "pest-animal-control" and position == 0
            template, fields = log_fields(control_id, day, follow_up)
            add(
                control_id,
                template["record_type"],
                "open" if follow_up else "complete",
                f"NP3 log: {template['title']}",
                day,
                day + timedelta(days=30) if follow_up else None,
                {"np3_log_type": template["key"], "log_fields": fields, "np3_guidance_version": "2025-v2"},
                day,
            )
    db.commit()

    visited = today - timedelta(days=270)
    verification.record(
        db,
        org_id,
        profile,
        {
            "verified_on": visited.isoformat(),
            "verifier_name": "Sam Rivers",
            "verifier_agency": "Hutt City Council",
            "report_reference": "FV-2026-0142",
            "outcome": "acceptable",
            "initial": True,
            "actions": [
                {
                    "description": "Add the cold store to the daily temperature log",
                    "due_on": (visited + timedelta(days=60)).isoformat(),
                    "owner_user_id": str(user.id),
                }
            ],
        },
        user.id,
        today,
    )
    db.commit()


def _seed_excise(db, org_id, inv) -> None:
    """Sales -> Excise: the lineage gin and a limoncello set up for excise (pack size, ABV,
    Customs product type), mapped from Xero lines across the sales seed's months, with one
    unmapped line so "Needs attention" shows."""
    from app.core.db.models.inventory_item import InventoryItem
    from app.features.compliant.models import ComplianceProfile
    from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
    from app.features.compliant.modules.nz_alcohol import excise
    from app.features.crm.models.product_mapping import ProductMapping
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_invoice import XeroInvoice
    from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem

    gin, limoncello = "Whistlebird Dry Gin 700 mL", "Whistlebird Limoncello 500 mL"
    lot = (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.name == gin)
        .order_by(InventoryItem.created_at.asc())
        .first()
    )
    for name, ml, abv, category in ((gin, 700, 42, "gin"), (limoncello, 500, 25, "liqueur")):
        db.add(
            AlcoholProductProfile(
                org_id=org_id,
                inventory_name=name,
                product_type="spirits",
                pack_volume_ml=Decimal(ml),
                abv_percent=Decimal(abv),
                excise_category=category,
            )
        )
        db.add(ProductMapping(org_id=org_id, biz_e_product_name=name, xero_description_pattern=name))
    older = (
        db.query(XeroInvoice)
        .filter(XeroInvoice.org_id == org_id, XeroInvoice.invoice_number.like("INV-102%"))
        .order_by(XeroInvoice.date.desc())
        .all()
    )
    if not older:
        raise ValueError("excise requires the lineage and sales seeds")
    for number, invoice in enumerate(older):
        lines = [(gin, 48 + number * 18), (limoncello, 12 + number * 6)]
        if number == 0:
            lines.append(("Distillery tour and tasting", 1))
        for position, (description, qty) in enumerate(lines, start=1):
            db.add(
                XeroInvoiceLineItem(
                    org_id=org_id,
                    invoice_id=invoice.id,
                    xero_line_item_id=f"X{position}",
                    description=description,
                    quantity=qty,
                )
            )
        if lot is not None:  # the gin line came from a batch, so Customs counts it as removed
            db.add(
                SalesFifoAllocation(
                    org_id=org_id,
                    xero_invoice_id=invoice.xero_invoice_id,
                    xero_line_key="X1",
                    inventory_item_id=lot.id,
                    product_name=gin,
                    quantity=Decimal(48 + number * 18),
                    unit=lot.unit,
                )
            )
    db.commit()

    # Excise reminders on from four months back, the months before that lodged: a backlog of two.
    profile = db.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).one_or_none()
    if profile is not None:
        today = date.today()
        serial = today.year * 12 + today.month - 1 - 4
        profile.settings = {
            **(profile.settings or {}),
            "excise_frequency": "monthly",
            "excise_tracking_from": date(serial // 12, serial % 12 + 1, 1).isoformat(),
        }
        db.commit()
        for back, reference in ((5, "EX-25-0811"), (4, "EX-25-0912")):
            serial = today.year * 12 + today.month - 1 - back
            start = date(serial // 12, serial % 12 + 1, 1)
            excise.lodge(db, org_id, start, "monthly", start + timedelta(days=45), reference, None)
        db.commit()
    stocked = (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.name == gin, InventoryItem.quantity > 20)
        .order_by(InventoryItem.quantity.desc())
        .first()
    )
    if stocked is not None:
        _seed_customs_stock(db, org_id, stocked)
    _seed_customs_records(db, org_id)


def _seed_customs_records(db, org_id) -> None:
    """Records for Customs beyond the lodgements: a monthly reconciliation, the retention
    attestation, and a movement record still open."""
    from datetime import UTC, datetime

    from app.core.db.models.user import User
    from app.features.compliant.models.compliance_record import ComplianceRecord

    user = db.query(User).filter(User.org_id == org_id).first()
    today = date.today()
    serial = today.year * 12 + today.month - 1 - 5
    start = date(serial // 12, serial % 12 + 1, 1)
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1) - timedelta(days=1)
    rows = (
        (
            "reconciliation",
            "reading",
            "complete",
            f"Stock reconciled: {start:%B %Y}",
            (start, end),
            "Drive / Customs / Reconciliations",
            {"declared_litres_of_alcohol": "35.280"},
            40,
        ),
        (
            "record-retention",
            "attestation",
            "complete",
            "Records kept 7 years, backed up in NZ",
            (None, None),
            "Google Workspace (NZ) and nightly backup",
            {},
            60,
        ),
        (
            "movement-evidence",
            "attestation",
            "open",
            "Delivery dockets for Sam's car transfers",
            (None, None),
            None,
            {},
            6,
        ),
    )
    for control, kind, status, title, period, ref, details, back in rows:
        at = datetime.combine(today - timedelta(days=back), datetime.min.time(), tzinfo=UTC).replace(hour=10)
        db.add(
            ComplianceRecord(
                org_id=org_id,
                framework_slug="customs-alcohol",
                control_id=control,
                record_type=kind,
                status=status,
                title=title,
                period_start=period[0],
                period_end=period[1],
                evidence_reference=ref,
                source_refs=[],
                details=details,
                created_by_user_id=user.id if user else None,
                created_at=at,
                updated_at=at,
            )
        )
    db.commit()


def _seed_customs_stock(db, org_id, lot) -> None:
    """Customs -> Stock: a rep's car outside the licensed area with gin in it, library stock
    kept back from the batch, and a finished stocktake whose differences were a tasting
    (on the entry), a dropped bottle (a remission) and bottles found in the car."""
    from datetime import UTC, datetime

    from flask import Flask

    from app.core.backend import stocktake
    from app.core.db.models.inventory_item import InventoryItem, InventoryType
    from app.core.db.models.stock_location import StockLocation
    from app.core.db.models.stocktake import StocktakeLine
    from app.core.db.repositories.inventory_repo import InventoryRepository

    repo = InventoryRepository(db)
    today = date.today()
    car = StockLocation(org_id=org_id, name="Sam's car", inside_licensed_area=False)
    db.add(car)
    db.commit()
    abv = (lot.extra_data or {}).get("abv_percent")
    repo.create_inventory_item(
        org_id=org_id,
        name=f"{lot.name} - Library stock",
        quantity="1400",
        unit="mL",
        inventory_type=InventoryType.FINAL_PRODUCT.value,
        supplier_batch_number=lot.supplier_batch_number,
        extra_data={"library_stock": True, **({"abv_percent": abv} if abv else {})},
    )
    repo.move_lot(org_id, lot.id, "6", car.id, today - timedelta(days=12), "Tasting run, Wellington", None)
    db.commit()
    if Decimal(str(db.get(InventoryItem, lot.id).quantity)) < 12:
        return
    # resolve_line reads the signed-in user from flask.g for the wastage record.
    with Flask(__name__).app_context():
        counted_on = today - timedelta(days=9)
        st = stocktake.start_stocktake(db, org_id, counted_on, "scheduled", None, None)
        db.flush()
        for line in db.query(StocktakeLine).filter(StocktakeLine.stocktake_id == st.id).all():
            item = db.get(InventoryItem, line.inventory_item_id)
            on_hand = Decimal(str(item.quantity))
            if item.id == lot.id:
                stocktake.record_count(db, line, str(on_hand - 5))
                parts = [
                    {"reason": "removed_unrecorded", "quantity": "2", "note": "Cellar door tasting"},
                    {"reason": "broken", "quantity": "1", "note": "Dropped on the bottling line"},
                    {"reason": "found_elsewhere", "quantity": "2", "location_id": str(car.id)},
                ]
                stocktake.resolve_line(db, org_id, line, parts, None, counted_on)
            else:
                stocktake.record_count(db, line, str(on_hand))
        st.status = "done"
        st.completed_at = datetime.combine(counted_on, datetime.min.time(), tzinfo=UTC)
        db.commit()


def _seed_production(db, org_id, inv) -> None:
    """A working week on the floor: three product workflows with seven batches under way, at
    different steps and ages, one of them not yet started. For pages that show what is in
    production right now."""
    from datetime import UTC, datetime

    from app.core.db.models.execution import Execution
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.process import ProcessCategory
    from app.core.db.repositories.execution_repo import ExecutionRepository
    from app.core.db.repositories.process_repo import ProcessRepository

    procs, execs = ProcessRepository(db), ExecutionRepository(db)
    now = datetime.now(UTC)
    gin = ["Macerate botanicals", "Distil", "Bottle and label"]
    workflows = {
        "Whistlebird Navy Strength Gin": gin,
        "Whistlebird Pink Gin": gin[:2] + ["Infuse raspberry", "Bottle and label"],
        "Limoncello": ["Infuse lemon peel", "Blend and sweeten", "Bottle and label"],
    }
    made = {}
    for name, steps in workflows.items():
        process = procs.create_process(org_id, name, category=ProcessCategory.MANUFACTURING, is_draft=False)
        for number, step_name in enumerate(steps, start=1):
            procs.add_step(
                process_id=process.id,
                org_id=org_id,
                step_number=number,
                position=number * 1000,
                name=step_name,
                inputs=[],
                outputs=[{"name": f"{name}: {step_name.lower()}", "quantity": 100, "unit": "L"}],
            )
        made[name] = process
    db.commit()

    def start(name, done, hours):
        execution = execs.create_execution(org_id, made[name].id)
        rows = (
            db.query(ExecutionStep)
            .filter(ExecutionStep.execution_id == execution.id)
            .order_by(ExecutionStep.step_number)
            .all()
        )
        started = now - timedelta(hours=hours)
        for index in range(done):
            execs.complete_step(
                rows[index].id,
                org_id,
                actual_inputs=[],
                actual_outputs=[],
                completed_at_override=started + timedelta(hours=(index + 1) * max(1, hours // (done + 1))),
            )
        if hours:
            db.query(Execution).filter(Execution.id == execution.id).update({"started_at": started})
        db.commit()

    # (workflow, steps already done, hours since it started)
    start("Whistlebird Navy Strength Gin", 2, 76)
    start("Whistlebird Navy Strength Gin", 1, 27)
    start("Whistlebird Navy Strength Gin", 0, 2)
    start("Whistlebird Pink Gin", 3, 120)
    start("Whistlebird Pink Gin", 1, 20)
    start("Limoncello", 1, 190)
    start("Limoncello", 0, 0)


def _seed_planner(db, org_id, inv) -> None:
    """Demand for the Planner: orders and forecasts against the production workflows' outputs,
    overdue, due this week, due later and cancelled. Needs `production` seeded first."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.core.db.models.step import Step
    from app.features.planning import demand_service

    # The planner only offers outputs that carry an id, as the workflow editor gives them.
    for step in db.query(Step).filter(Step.org_id == org_id).all():
        if any(isinstance(o, dict) and not o.get("id") for o in step.outputs or []):
            step.outputs = [{**o, "id": o.get("id") or str(uuid.uuid4())} for o in step.outputs]
            flag_modified(step, "outputs")
    db.commit()
    outputs = demand_service.output_catalog(db, org_id)
    if not outputs:
        raise SystemExit("ui-shots: `planner` needs the `production` seed before it (seed production planner)")
    today = date.today()

    def pick(word):
        return next((row for row in outputs if word.lower() in row["name"].lower()), outputs[0])

    # (reference, output it is for, quantity, days until due, priority)
    orders = [
        ("Regional Wines — summer order", "navy strength gin: bottle", 240, -2, 80),
        ("Moore Wilson's — standing order", "pink gin: bottle", 120, 1, 60),
        ("Hawthorn Lounge — cocktail range", "limoncello: bottle", 60, 3, 40),
        ("Bottle-O Greytown — restock", "navy strength gin: bottle", 180, 6, 50),
        ("Cellar door — December forecast", "pink gin: bottle", 300, 21, 20),
        ("Christmas gift packs — forecast", "limoncello: bottle", 150, 35, 30),
        ("Trade show samples", "navy strength gin: distil", 40, 12, 10),
    ]
    made = []
    for reference, word, quantity, days, priority in orders:
        output = pick(word)
        row = demand_service.create_demand(
            db,
            org_id,
            {
                "reference": reference,
                "source_output_id": output["id"],
                "quantity": str(quantity),
                "due_date": (today + timedelta(days=max(days, 0))).isoformat(),
                "priority": priority,
            },
        )
        if days < 0:  # the service refuses past dates on entry; an order goes overdue by time passing
            row.due_date = today + timedelta(days=days)
        made.append(row)
    db.commit()
    demand_service.cancel_demand(db, org_id, made[-1].id)


def _seed_contracts(db, org_id, inv) -> None:
    """Contract manufacturing: four brand customers (one inactive) with orders overdue, due this
    week, later, completed and cancelled, across producer-, customer- and mixed-supplied lines."""
    from app.features.contract_manufacturing.models.orders import ContractOrder
    from app.features.contract_manufacturing.services.orders import ContractOrderService

    service = ContractOrderService(db, org_id)
    customers = {}
    for name, active in [
        ("Harbour Spirits Co.", True),
        ("Kererū Botanicals", True),
        ("Southern Cross Liqueurs", True),
        ("Old Mill Brewing (paused)", False),
    ]:
        row = service.save_customer({"name": name, "is_active": active})
        customers[name] = row.id
    db.commit()
    today = date.today()

    # (reference, customer, days until due, status, duty, [(product, quantity, unit, materials)])
    orders = [
        (
            "HS-1042",
            "Harbour Spirits Co.",
            -3,
            "confirmed",
            "producer_licensee",
            [("Harbour Navy Gin 700 mL", 600, "bottles", "producer")],
        ),
        (
            "KB-0217",
            "Kererū Botanicals",
            2,
            "confirmed",
            "customer_licensee",
            [
                ("Kawakawa Bitters 200 mL", 240, "bottles", "customer"),
                ("Horopito Tincture 50 mL", 480, "bottles", "mixed"),
            ],
        ),
        (
            "SC-0088",
            "Southern Cross Liqueurs",
            5,
            "confirmed",
            "customer_underbond",
            [("Feijoa Liqueur bulk", 900, "L", "customer")],
        ),
        (
            "HS-1043",
            "Harbour Spirits Co.",
            19,
            "draft",
            "producer_licensee",
            [("Harbour Pink Gin 700 mL", 300, "bottles", "producer")],
        ),
        (
            "KB-0216",
            "Kererū Botanicals",
            -20,
            "completed",
            "customer_licensee",
            [("Kawakawa Bitters 200 mL", 240, "bottles", "customer")],
        ),
        (
            "SC-0085",
            "Southern Cross Liqueurs",
            9,
            "cancelled",
            "customer_underbond",
            [("Boysenberry Liqueur bulk", 400, "L", "customer")],
        ),
    ]
    for reference, customer, days, status, duty, lines in orders:
        created = service.create_order(
            {
                "customer_id": str(customers[customer]),
                "reference": reference,
                "due_date": (today + timedelta(days=max(days, 1))).isoformat(),
                "status": "draft" if status in ("completed", "cancelled") else status,
                "duty_responsibility": duty,
                "customer_cca_reference": None if duty == "producer_licensee" else f"CCA-{reference}",
                "lines": [
                    {"product_name": product, "quantity": str(qty), "unit": unit, "materials_source": source}
                    for product, qty, unit, source in lines
                ],
            }
        )
        row = (
            created
            if isinstance(created, ContractOrder)
            else db.query(ContractOrder).filter_by(org_id=org_id, reference=reference).one()
        )
        row.due_date = today + timedelta(days=days)
        if status in ("completed", "cancelled"):
            row.status = status
    db.commit()


def _seed_stocktake(db, org_id, inv) -> None:
    """Stocktakes over the stock seed's finished goods: one finished in July with every line
    matching, and one under way today with a line short, one over, one under investigation and
    the rest still to count. Needs `stock` first."""
    from datetime import UTC, datetime

    from app.core.backend import stocktake as stocktake_service
    from app.core.db.models.stocktake import StocktakeLine
    from app.core.db.models.user import User

    def lines_of(stocktake):
        return db.query(StocktakeLine).filter(StocktakeLine.stocktake_id == stocktake.id).all()

    user = db.query(User).filter(User.org_id == org_id).first()
    user.first_name, user.last_name = "Jordan", "Lee"  # a name, not an email, on every record
    today = date.today()

    earlier = stocktake_service.start_stocktake(db, org_id, today - timedelta(days=97), "scheduled", None, user.id)
    for line in lines_of(earlier):
        stocktake_service.record_count(db, line, line.expected_quantity)
    earlier.status = "done"
    earlier.completed_at = datetime.now(UTC) - timedelta(days=97)
    db.commit()

    current = stocktake_service.start_stocktake(db, org_id, today, "scheduled", None, user.id)
    lines = sorted(lines_of(current), key=lambda line: str(line.inventory_item_id))
    if len(lines) < 4:
        raise SystemExit("ui-shots: `stocktake` needs the `stock` seed's finished goods first")
    stocktake_service.record_count(db, lines[0], lines[0].expected_quantity)  # matches
    stocktake_service.record_count(db, lines[1], lines[1].expected_quantity - 6)  # six short
    stocktake_service.record_count(db, lines[2], lines[2].expected_quantity + 2)  # two over
    stocktake_service.record_count(db, lines[3], lines[3].expected_quantity - 1)
    stocktake_service.resolve_line(db, org_id, lines[3], [{"reason": "investigating", "quantity": "1"}], user.id, today)
    db.commit()


def _seed_board(db, org_id, inv) -> None:
    """Planned batches for the Production board: batch sizes and timings for each output the
    Planner's demand asks for, every open demand planned, the batches spread over this week and
    next, one pinned, and a still with too few minutes so one day is overloaded. Needs
    `production planner` seeded first."""
    from app.core.db.models.organisation import Organisation
    from app.features.planning import batch_service, capacity_service
    from app.features.planning.batch_models import PlanningBatch
    from app.features.planning.models import PlanningDemand

    demands = (
        db.query(PlanningDemand)
        .filter(PlanningDemand.org_id == org_id, PlanningDemand.status == "open")
        .order_by(PlanningDemand.due_date)
        .all()
    )
    if not demands:
        raise SystemExit("ui-shots: `board` needs `production planner` before it (seed production planner board)")
    catalog = {row["id"]: row for row in batch_service.workflow_catalog(db, org_id)}
    configured = set()
    for demand in demands:
        output = catalog.get(str(demand.source_output_id))
        if output is None or output["id"] in configured:
            continue
        configured.add(output["id"])
        batch_service.save_setting(
            db,
            org_id,
            uuid.UUID(output["process_id"]),
            {
                "source_output_id": output["id"],
                "batch_quantity": "120" if output["unit"] != "L" else "40",
                "steps": [
                    {"step_id": step["step_id"], "duration_minutes": 180, "waiting_minutes": 60}
                    for step in output["steps"]
                ],
                "expected_revision": 0,
            },
        )
    db.commit()
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    offset = 0
    for demand in demands:
        if str(demand.source_output_id) not in configured:
            continue
        rows, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=today)
        for row in rows:  # one batch a working day, so the week reads as a schedule
            day = monday + timedelta(days=offset % 10 + (offset % 10 >= 5) * 2)
            shift = day - row.proposed_start_date
            row.proposed_start_date = day
            if row.theoretical_ready_date is not None:
                row.theoretical_ready_date += shift
            offset += 1
    db.commit()
    first = (
        db.query(PlanningBatch)
        .filter(PlanningBatch.org_id == org_id)
        .order_by(PlanningBatch.proposed_start_date)
        .first()
    )
    if first is not None:
        first.pinned = True
        db.commit()
    org = db.query(Organisation).filter(Organisation.id == org_id).one()
    site = batch_service.resolve_planning_site(db, org, None)
    if site is not None:
        still = str(uuid.uuid4())
        steps = {step["step_id"] for row in catalog.values() for step in row["steps"][:1]}
        capacity_service.save_setting(
            db,
            org_id,
            site.id,
            {
                "groups": [{"id": still, "name": "Still", "minutes_per_day": 300}],
                "assignments": [{"step_id": step, "group_id": still} for step in steps],
                "expected_revision": 0,
            },
        )
        db.commit()


def cmd_seed(args) -> int:
    _require_local()
    if STATE.exists():
        say(f"already seeded ({json.loads(STATE.read_text())['email']}); run `purge` first")
        return 2
    sys.path.insert(0, str(REPO))
    from app.core.db import db_session
    from app.core.db.models.user import UserRole
    from app.core.db.repositories.inventory_repo import InventoryRepository
    from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory, UserFactory

    run_id = uuid.uuid4().hex[:8]
    db = db_session()
    org = OrganisationFactory(name=f"{ORG_PREFIX}{run_id}")
    user = UserFactory(org_id=org.id, email=f"ui-shots-{run_id}@example.test", role=UserRole.ADMIN)
    db.commit()
    # Written before any stock, so a seed that fails half way can still be purged.
    HOME.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps(
            {
                "email": user.email,
                "password": DEFAULT_TEST_PASSWORD,
                "org_id": str(org.id),
                "user_id": str(user.id),
                "kinds": args.kinds,
            }
        )
    )
    inv = InventoryRepository(db)
    for kind in args.kinds:
        {
            "stock": _seed_stock,
            "lineage": _seed_lineage,
            "compliance": _seed_compliance,
            "production": _seed_production,
            "sales": _seed_sales,
            "excise": _seed_excise,
            "np3": _seed_np3,
            "customer": _seed_customer,
            "stocktake": _seed_stocktake,
            "planner": _seed_planner,
            "board": _seed_board,
            "contracts": _seed_contracts,
            "customers": _seed_customers,
            "suppliers": _seed_suppliers,
        }[kind](db, org.id, inv)
        say(f"seeded {kind}")
    say(f"org {org.name!r}, sign-in {user.email}")
    return 0


def cmd_purge(_args) -> int:
    _require_local()
    state = _state()
    sys.path.insert(0, str(REPO))
    import app.features as features
    from app.core.db import db_session
    from app.core.db.models.organisation import Organisation
    from app.core.db.models.user import User
    from tests.e2e.conftest import purge_org

    # purge_org walks Base.metadata, which only knows the tables whose models are imported.
    for module in pkgutil.walk_packages(features.__path__, features.__name__ + "."):
        if module.name.rsplit(".", 1)[-1].endswith("models") or ".models." in module.name:
            try:
                importlib.import_module(module.name)
            except Exception:  # an optional feature that will not import has no rows here either
                pass

    org_id, user_id = uuid.UUID(state["org_id"]), uuid.UUID(state["user_id"])
    db = db_session()
    org = db.get(Organisation, org_id)
    if org is not None:
        if not org.name.startswith(ORG_PREFIX):
            say(f"refusing to purge {org.name!r}: not an org this script created")
            return 2
        # Lots at a place reference it, and purge_org can't order that cycle: detach them first.
        from sqlalchemy import String, func

        from app.core.db.models.inventory_item import InventoryItem

        # A throwaway org: rename them so detaching can't collide on (name, batch, place).
        placed = InventoryItem.org_id == org_id, InventoryItem.location_id.isnot(None)
        db.query(InventoryItem).filter(*placed).update(
            {InventoryItem.name: InventoryItem.name + " @" + func.cast(InventoryItem.id, String)},
            synchronize_session=False,
        )
        db.query(InventoryItem).filter(InventoryItem.org_id == org_id).update(
            {InventoryItem.location_id: None}, synchronize_session=False
        )
        # A stocktake's breakage is a wastage record plus its movement: clear those first too.
        from app.core.db.models.inventory_movement import InventoryMovement
        from app.core.db.models.inventory_wastage import InventoryWastage

        db.query(InventoryMovement).filter(InventoryMovement.org_id == org_id).delete(synchronize_session=False)
        db.query(InventoryWastage).filter(InventoryWastage.org_id == org_id).delete(synchronize_session=False)
        db.commit()
        purge_org(db, org_id, user_id)
        db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
        db.commit()
    STATE.unlink()
    say("purged")
    return 0


def cmd_status(args) -> int:
    seeded = json.loads(STATE.read_text()) if STATE.exists() else None
    report = {"home": str(HOME), "seeded": bool(seeded)}
    if seeded:
        report.update({"email": seeded["email"], "org_id": seeded["org_id"], "kinds": seeded.get("kinds", [])})
    if args.json:
        print(json.dumps(report))
    else:
        say(f"home {HOME}")
        say(f"seeded as {seeded['email']} ({', '.join(seeded.get('kinds', []))})" if seeded else "nothing seeded")
    return 0


# ── Shooting ────────────────────────────────────────────────────────────────────────────


def _boot():
    from werkzeug.serving import make_server

    from app.app import app  # the composed app, not create_app(): see tests/e2e/conftest.py

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(REPO / "app/tls/app_cert.pem"), str(REPO / "app/tls/app_cert.key"))
    # As in tests/e2e/conftest.py: TLS 1.3 closes from the dev server fail random stylesheets.
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = make_server("127.0.0.1", port, app, threaded=True, ssl_context=context)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.3)
    return server, f"https://127.0.0.1:{port}"


def _load_scenarios(path: Path, names: list[str]):
    spec = importlib.util.spec_from_file_location("ui_shots_scenarios", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    available = {
        name: fn
        for name, fn in vars(module).items()
        if inspect.isfunction(fn) and fn.__module__ == module.__name__ and not name.startswith("_")
    }
    missing = [name for name in names if name not in available]
    if missing:
        say(f"no such scenario: {', '.join(missing)}; have {', '.join(available)}")
        raise SystemExit(2)
    return [(name, available[name]) for name in (names or available)]


def cmd_shoot(args) -> int:
    _require_local()
    state = _state()
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(Path(__file__).parent))  # so a scenario file can `from ui_shots import ...`
    scenarios = _load_scenarios(Path(args.scenarios).resolve(), args.names)
    if args.list:
        for name, _fn in scenarios:
            say(name)
        return 0

    from playwright.sync_api import sync_playwright

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    server, url = _boot()
    failed, errors = [], []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(base_url=url, ignore_https_errors=True, locale="en-NZ", viewport=DESKTOP)
            page = context.new_page()
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: errors.append(f"uncaught: {error}"))
            page.goto("/")
            page.get_by_role("button", name="Sign In").first.click()
            page.locator("#login-email").fill(state["email"])
            page.locator("#login-password").fill(state["password"])
            page.locator("#login-submit-btn").click()
            page.wait_for_url(re.compile(r"/(core/)?dashboard"), timeout=20_000)
            for name, scenario in scenarios:
                page.set_viewport_size(DESKTOP)
                try:
                    scenario(page, out)
                    say("ok", name)
                except Exception as error:  # keep going: one broken view should not hide the rest
                    failed.append(name)
                    say("FAILED", name, repr(error)[:500])
            browser.close()
    finally:
        server.shutdown()
    # A 4xx fetch logs "Failed to load resource" too; that is a status, not a script fault.
    errors = [e for e in dict.fromkeys(errors) if not re.search(r"Failed to load resource: .*status of \d{3}", e)]
    for error in errors:
        say("console error:", error[:300])
    say(f"screenshots in {out}")
    return 1 if failed or (errors and not args.allow_console_errors) else 0


# ── Uploading to the merge request ──────────────────────────────────────────────────────


def cmd_upload(args) -> int:
    """Upload images to this project's GitLab uploads and print the markdown to paste into an MR."""

    def glab(*argv):
        return subprocess.run(["glab", *argv], capture_output=True, text=True, cwd=REPO).stdout.strip()

    token = glab("config", "get", "token", "--host", "gitlab.com")
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"], capture_output=True, text=True, cwd=REPO
    ).stdout.strip()
    match = re.search(r"gitlab\.com[:/](.+?)(?:\.git)?$", remote)
    if not token or not match:
        say("need a glab login for gitlab.com and a gitlab.com origin remote")
        return 2
    endpoint = f"https://gitlab.com/api/v4/projects/{urllib.parse.quote(match.group(1), safe='')}/uploads"
    status = 0
    for name in args.files:
        path = Path(name)
        boundary = uuid.uuid4().hex
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
            + path.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        # glab holds an OAuth token: it goes in Authorization, and PRIVATE-TOKEN answers 401.
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 -- fixed https host
                say(json.load(response)["markdown"])
        except Exception as error:
            status = 1
            say("FAILED", path.name, repr(error)[:200])
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed", help="create the throwaway org and its data")
    seed.add_argument("kinds", nargs="+", choices=SEED_KINDS)
    seed.set_defaults(run=cmd_seed)
    shoot = sub.add_parser("shoot", help="boot the app from this checkout and run scenarios")
    shoot.add_argument("out")
    shoot.add_argument("names", nargs="*")
    shoot.add_argument("--scenarios", required=True)
    shoot.add_argument("--list", action="store_true", help="print the scenario names and exit")
    shoot.add_argument("--allow-console-errors", action="store_true")
    shoot.set_defaults(run=cmd_shoot)
    upload = sub.add_parser("upload", help="upload images for a merge request description")
    upload.add_argument("files", nargs="+")
    upload.set_defaults(run=cmd_upload)
    sub.add_parser("purge", help="delete the throwaway org").set_defaults(run=cmd_purge)
    status = sub.add_parser("status", help="say whether an org is seeded")
    status.add_argument("--json", action="store_true")
    status.set_defaults(run=cmd_status)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
