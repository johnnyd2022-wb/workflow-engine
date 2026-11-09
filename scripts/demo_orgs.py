#!/usr/bin/env python3
"""Load the two demo organisations used by docs/demo-script.md (GL-C06).

  load     create both orgs and print their sign-ins
  status   say whether they exist
  purge    delete them (only orgs this script created, by name)

The orgs:

  Demo · Kōwhai Distillery (new)        signed up a minute ago: no stock, no workflows. For
                                        "how fast do I get value": the setup guide, opening
                                        stock, the first workflow, the first batch.
  Demo · Harbour Spirits (established)  months of history: stock with suppliers and expiries,
                                        gin and limoncello batches traced to Xero sales, excise
                                        periods (two lodged, a backlog), a sale to a duty free
                                        shop, NP3 evidence, licences, contract orders, a
                                        stocktake, and the exception loop: a lot on quality
                                        hold, a credit note with goods back damaged, and a
                                        recall drill half worked. For specific questions.

Both are built from the screenshot harness's seeds (scripts/ui_shots.py), which are realistic
but synthetic. Whistlebird's own replay (scripts/replay_whistlebird.sh) has real customers and
suppliers, so it is not used for demos.

Local test database only, like the harness:

  env -u ENVIRONMENT uv run python scripts/demo_orgs.py load
"""

from __future__ import annotations

import argparse
import secrets
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import ui_shots  # noqa: E402 -- the seeds and the purge live there

PREFIX = "Demo · "
NEW = PREFIX + "Kōwhai Distillery (new)"
ESTABLISHED = PREFIX + "Harbour Spirits (established)"
# The established org's history, in the order the seeds depend on each other.
ESTABLISHED_SEEDS = (
    "stock", "lineage", "sales", "customers", "suppliers", "compliance", "excise", "transfers",
    "production", "planner", "contracts", "np3", "licensing", "tasks",
)  # fmt: skip


def _seed_exceptions(db, org_id, user) -> None:
    """The exception loop (GL-C06): a quality hold and one released, a credit note with goods
    back damaged and one line still to decide, and a recall drill half worked. Built through
    the real services, on stock and sales the other seeds made."""
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from app.core.db.models.inventory_item import InventoryItem
    from app.core.services import lot_holds
    from app.features.crm.models.product_mapping import ProductMapping
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_credit_note import XeroCreditNote
    from app.features.crm.models.xero_credit_note_line import XeroCreditNoteLine
    from app.features.crm.models.xero_invoice import XeroInvoice
    from app.features.crm.services import sales_returns
    from app.features.recalls import service as recalls
    from app.features.recalls.models import RecallContact

    now = datetime.now(UTC)
    sold = (
        db.query(SalesFifoAllocation, XeroInvoice)
        .join(
            XeroInvoice,
            (XeroInvoice.org_id == SalesFifoAllocation.org_id)
            & (XeroInvoice.xero_invoice_id == SalesFifoAllocation.xero_invoice_id),
        )
        .filter(SalesFifoAllocation.org_id == org_id, SalesFifoAllocation.tasting_allocation_id.is_(None))
        .order_by(SalesFifoAllocation.created_at.desc())
        .all()
    )
    finished = (
        db.query(InventoryItem)
        .filter(
            InventoryItem.org_id == org_id,
            InventoryItem.inventory_type == "final_product",
            InventoryItem.quantity > 0,
        )
        .order_by(InventoryItem.created_at)
        .all()
    )
    sold_lots = {a.inventory_item_id for a, _ in sold}

    # Quality: one lot on hold now, one held last month and released with a note.
    unsold = [i for i in finished if i.id not in sold_lots] or finished
    if unsold:
        lot_holds.place_hold(db, org_id, unsold[0].id, "Haze after bottling; waiting on a lab turbidity check", user.id)
    if len(unsold) > 1:
        old = lot_holds.place_hold(db, org_id, unsold[1].id, "Label batch code smudged", user.id)[0]
        old.placed_at = now - timedelta(days=30)
        released = lot_holds.release_hold(db, org_id, old.id, "Relabelled and checked by the duty manager", user.id)
        # release_hold stamps now; the script calls it last month's hold, so date it then.
        released.released_at = now - timedelta(days=25)
    db.flush()

    # Money and goods: a credit note on a real sale, two cases' worth credited, one back damaged.
    # The script promises one bottle back damaged and one still to decide: that needs a sale
    # of at least two. Fail loudly rather than seed a demo that contradicts its own script.
    returnable = [(a, inv) for a, inv in sold if Decimal(str(a.quantity)) >= 2]
    if sold and not returnable:
        raise RuntimeError("demo seed: no sale of 2+ bottles to credit; the exception loop needs one")
    if returnable:
        allocation, invoice = returnable[0]
        mapping = (
            db.query(ProductMapping)
            .filter(ProductMapping.org_id == org_id, ProductMapping.biz_e_product_name == allocation.product_name)
            .first()
        )
        if mapping is None:
            mapping = ProductMapping(
                org_id=org_id,
                biz_e_product_name=allocation.product_name,
                xero_description_pattern=allocation.product_name,
                match_type="exact",
            )
            db.add(mapping)
            db.flush()
        qty = Decimal("2")
        note = XeroCreditNote(
            org_id=org_id,
            xero_credit_note_id=f"demo-cn-{uuid.uuid4().hex[:8]}",
            xero_tenant_id="demo",
            number="CN-0007",
            contact="Demo customer",
            date=(now - timedelta(days=3)).date(),
            status="AUTHORISED",
            total=Decimal("96.00"),
            allocated_invoice_ids=[invoice.xero_invoice_id],
        )
        db.add(note)
        db.flush()
        line = XeroCreditNoteLine(
            org_id=org_id,
            credit_note_id=note.id,
            line_key="demo-line-1",
            description=allocation.product_name,
            quantity=qty,
            line_amount=Decimal("96.00"),
            product_mapping_id=mapping.id,
        )
        db.add(line)
        db.flush()
        sales_returns.record_return(
            db,
            org_id,
            user.id,
            condition="damaged",
            quantity="1",
            received_on=(now - timedelta(days=1)).date(),
            note="Carton crushed in transit",
            credit_note_line_id=line.id,
        )
    db.flush()

    # A recall drill on a sold lot: two customers' notices sent, one acknowledged.
    if sold:
        drill = recalls.open_recall(
            db,
            org_id,
            user,
            lot_id=sold[-1][0].inventory_item_id,
            reason="Supplier warns of possible glass in one pallet of bottles (drill)",
            risk="health",
            owner_id=user.id,
            due_at=now + timedelta(days=2),
            is_drill=True,
        )
        contacts = (
            db.query(RecallContact)
            .filter(RecallContact.org_id == org_id, RecallContact.recall_id == drill.id)
            .order_by(RecallContact.customer_name, RecallContact.product_name)
            .all()
        )
        for contact in contacts[:2]:
            recalls.record_notice_sent(db, org_id, user.id, drill.id, contact.id, channel="email", sent_at=now)
        if contacts:
            recalls.record_acknowledgement(
                db, org_id, user.id, drill.id, contacts[0].id, by="Store manager", note="Pulled from shelf", at=now
            )
    db.commit()


def say(*parts) -> None:
    print("demo:", *parts)


def _orgs(db):
    from app.core.db.models.organisation import Organisation

    return db.query(Organisation).filter(Organisation.name.like(PREFIX + "%")).all()


def _make_org(db, name: str, email: str, password: str):
    from app.core.db.models.user import UserRole
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.core.security.auth_service import AuthService
    from tests.factories import OrganisationFactory, UserFactory

    org = OrganisationFactory(name=name)
    user = UserFactory(org_id=org.id, email=email, role=UserRole.ADMIN)
    user.password_hash = AuthService.hash_password(password)
    # The offer being demonstrated is Compliance (NZ Alcohol).
    FeatureSubscriptionRepository(db).grant(org.id, "compliant")
    db.commit()
    return org, user


def cmd_load(_args) -> int:
    ui_shots._require_local()
    from app.core.db import db_session
    from app.core.db.repositories.inventory_repo import InventoryRepository

    db = db_session()
    if _orgs(db):
        say("the demo orgs already exist; run `purge` first")
        return 2
    run = uuid.uuid4().hex[:6]
    password = secrets.token_urlsafe(12)
    new_org, new_user = _make_org(db, NEW, f"demo-new-{run}@example.test", password)
    org, user = _make_org(db, ESTABLISHED, f"demo-established-{run}@example.test", password)
    inv = InventoryRepository(db)
    for kind in ESTABLISHED_SEEDS:
        getattr(ui_shots, f"_seed_{kind}")(db, org.id, inv)
        say(f"seeded {kind}")
    _seed_exceptions(db, org.id, user)
    say("seeded exceptions (hold, credit and return, recall drill)")
    say("ready. Sign in at /, with the password below for both:")
    say(f"  {NEW}: {new_user.email}")
    say(f"  {ESTABLISHED}: {user.email}")
    say(f"  password: {password}")
    return 0


def cmd_status(_args) -> int:
    ui_shots._require_local()
    from app.core.db import db_session
    from app.core.db.models.user import User

    db = db_session()
    orgs = _orgs(db)
    if not orgs:
        say("no demo orgs loaded")
    for org in orgs:
        emails = [u.email for u in db.query(User).filter(User.org_id == org.id)]
        say(f"{org.name}: {', '.join(emails)}")
    return 0


def cmd_purge(_args) -> int:
    ui_shots._require_local()
    from app.core.db import db_session
    from app.core.db.models.user import User

    db = db_session()
    for org in _orgs(db):
        if not org.name.startswith(PREFIX):  # the query already says so; checked again before deleting
            continue
        admin = db.query(User).filter(User.org_id == org.id).first()
        ui_shots.purge_seeded_org(db, org.id, admin.id if admin else None)
        say(f"purged {org.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("load", "status", "purge"))
    args = parser.parse_args()
    return {"load": cmd_load, "status": cmd_status, "purge": cmd_purge}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
