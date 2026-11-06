"""GL-P03: open, work and close a product recall (or a drill).

A recall reuses the operational-case machinery for what every case needs (owner, due date,
acknowledge -> in progress -> resolved -> independently verified, an event history) and adds
what a recall needs on top (see ``models``). The case can't be resolved or verified until the
recall is complete: every customer reached has acknowledged (or is recorded as unreachable, with
why), and every unit supplied to them is accounted for as recovered or disposed of.

Nothing is sent from here. Biz-E drafts each customer's notice; a person sends it and records
that they did. A drill works the same way but places no quality holds and is labelled a drill
everywhere, so it can't be mistaken for, or disrupt, real operations.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.backend.event_writer import EventWriter
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.user import User
from app.core.services import lot_holds
from app.core.utils.time import utc_now
from app.features.operational_cases.models.operational_case import CaseSeverity, CaseStatus, OperationalCase
from app.features.operational_cases.models.operational_case_link import CaseLinkRelation
from app.features.operational_cases.repositories.operational_case_event_repo import OperationalCaseEventRepository
from app.features.operational_cases.repositories.operational_case_link_repo import OperationalCaseLinkRepository
from app.features.recalls.models import RISKS, Recall, RecallContact

SOURCE_TYPE = "recall"
CHECK_ID = "product_recall"
MAX_TEXT = 2000


class RecallError(ValueError):
    """A recall action that can't be done as asked; the message is shown as-is."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _text(value, field: str, required: bool = True, max_len: int = MAX_TEXT) -> str | None:
    text = (value or "").strip() if isinstance(value, str) or value is None else None
    if text is None:
        raise RecallError(f"{field} must be text")
    if not text:
        if required:
            raise RecallError(f"Add {field}")
        return None
    if len(text) > max_len:
        raise RecallError(f"Keep {field} under {max_len} characters")
    return text


def _qty(value, field: str) -> Decimal:
    try:
        qty = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise RecallError(f"{field} must be a number") from None
    if not qty.is_finite() or qty < 0:
        raise RecallError(f"{field} must be zero or more")
    return qty


def _plain(value) -> str:
    return format(Decimal(str(value)).normalize(), "f")


# --- scope --------------------------------------------------------------------------------------


def scope_for(session: Session, org_id: UUID, lot_id: UUID) -> tuple[list[dict], list[dict]]:
    """The lots a recall of ``lot_id`` reaches (it and everything made from it) and the customers
    those lots were sold to, by product, with the quantity each received."""
    from app.core.backend.dagtraversal import trace_forward
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice

    nodes = trace_forward(org_id, session, lot_id, include_quantity_filter=False)["items"]
    lots = [
        {
            "id": n["id"],
            "name": n.get("display_label") or n.get("name"),
            "quantity": n.get("quantity"),
            "unit": n.get("unit"),
        }
        for n in nodes
    ]
    lot_ids = [UUID(n["id"]) for n in nodes] or [lot_id]
    rows = (
        session.query(SalesFifoAllocation, XeroInvoice, XeroContact)
        .join(
            XeroInvoice,
            (XeroInvoice.org_id == SalesFifoAllocation.org_id)
            & (XeroInvoice.xero_invoice_id == SalesFifoAllocation.xero_invoice_id),
        )
        .outerjoin(XeroContact, (XeroContact.org_id == XeroInvoice.org_id) & (XeroContact.id == XeroInvoice.contact_id))
        .filter(SalesFifoAllocation.org_id == org_id, SalesFifoAllocation.inventory_item_id.in_(lot_ids))
        .all()
    )
    grouped: dict = defaultdict(lambda: {"quantity": Decimal(0), "invoices": set()})
    for allocation, invoice, contact in rows:
        name = (contact.name if contact else None) or "Unknown customer"
        key = (contact.id if contact else None, name, allocation.product_name, allocation.unit)
        qty = Decimal(str(allocation.quantity))
        if not qty.is_finite():
            continue  # NUMERIC can hold NaN; a corrupt sale line must not poison the customer's total
        grouped[key]["quantity"] += qty
        grouped[key]["invoices"].add(invoice.invoice_number or invoice.xero_invoice_id)
    customers = [
        {
            "contact_id": contact_id,
            "customer_name": name,
            "product_name": product,
            "unit": unit,
            "quantity": data["quantity"],
            "invoices": sorted(data["invoices"]),
        }
        for (contact_id, name, product, unit), data in grouped.items()
        if data["quantity"] > 0
    ]
    customers.sort(key=lambda c: (c["customer_name"].casefold(), c["product_name"]))
    return lots, customers


# --- open ---------------------------------------------------------------------------------------


def open_recall(
    session: Session,
    org_id: UUID,
    actor: User,
    *,
    lot_id: UUID,
    reason,
    risk: str,
    owner_id: UUID,
    due_at: datetime,
    is_drill: bool = False,
) -> Recall:
    """Open a recall (or drill) on a lot. Caller commits."""
    reason = _text(reason, "the reason for the recall")
    if risk not in RISKS:
        raise RecallError("Choose how serious it is: health, quality or regulatory")
    if due_at <= utc_now():
        raise RecallError("The due date must be in the future")
    lot = session.query(InventoryItem).filter(InventoryItem.org_id == org_id, InventoryItem.id == lot_id).one_or_none()
    if lot is None:
        raise RecallError("Lot not found", 404)
    owner = (
        session.query(User).filter(User.org_id == org_id, User.id == owner_id, User.is_active.is_(True)).one_or_none()
    )
    if owner is None:
        raise RecallError("Choose an owner from your team")

    lots, customers = scope_for(session, org_id, lot.id)
    label = lot.display_label or lot.name
    title = f"{'Recall drill' if is_drill else 'Recall'}: {label}"[:200]
    snapshot = {
        "item_name": label,
        "reason": reason,
        "risk": risk,
        "drill": bool(is_drill),
        "lots_in_scope": len(lots),
        "customers": len({c["customer_name"] for c in customers}),
    }
    case = OperationalCase(
        org_id=org_id,
        title=title,
        severity=CaseSeverity.CRITICAL,
        source_type=SOURCE_TYPE,
        check_id=CHECK_ID,
        source_entity_type="inventory_item",
        source_entity_id=lot.id,
        source_snapshot=snapshot,
        status=CaseStatus.OPEN,
        owner_id=owner.id,
        due_at=due_at,
        next_action=(
            f"Send the drafted notice to {snapshot['customers']} customer(s) and record each acknowledgement"
            if customers
            else "No customer received affected stock: confirm the held stock and close"
        ),
        version=1,
        created_by=actor.id,
    )
    try:
        with session.begin_nested():  # the active-source unique index is the race guard
            session.add(case)
            session.flush()
    except IntegrityError:
        raise RecallError("This lot already has an open recall", 409) from None
    OperationalCaseLinkRepository(session).add(
        org_id=org_id,
        case_id=case.id,
        relation=CaseLinkRelation.SOURCE,
        entity_type="inventory_item",
        entity_id=lot.id,
        created_by=actor.id,
    )

    # A real recall stops the affected stock being used, sold or dispatched (GL-P02). A drill
    # must not disrupt operations, so it holds nothing.
    hold_ids = []
    if not is_drill:
        held = lot_holds.open_holds(session, org_id, [UUID(x["id"]) for x in lots])
        for entry in lots:
            entry_id = UUID(entry["id"])
            in_stock = lot_holds._positive(entry.get("quantity"))
            if entry_id in held or not (in_stock or entry_id == lot.id):
                continue
            hold = lot_holds.place_hold(session, org_id, entry_id, f"Recall: {reason}"[:500], actor.id)[0]
            hold_ids.append(str(hold.id))

    recall = Recall(
        org_id=org_id,
        case_id=case.id,
        root_lot_id=lot.id,
        reason=reason,
        risk=risk,
        is_drill=bool(is_drill),
        scope_lots=lots,
        hold_ids=hold_ids,
        opened_by=actor.id,
        opened_at=utc_now(),
    )
    session.add(recall)
    session.flush()
    for c in customers:
        session.add(
            RecallContact(
                org_id=org_id,
                recall_id=recall.id,
                contact_id=c["contact_id"],
                customer_name=c["customer_name"][:255],
                product_name=c["product_name"][:500],
                unit=c["unit"],
                quantity_supplied=c["quantity"],
                invoices=c["invoices"],
                updated_at=utc_now(),
            )
        )

    payload = {
        "case_id": str(case.id),
        "version": 1,
        "source_type": SOURCE_TYPE,
        "check_id": CHECK_ID,
        "source_entity_type": "inventory_item",
        "source_entity_id": str(lot.id),
        "recall_id": str(recall.id),
        "drill": bool(is_drill),
        "holds_placed": len(hold_ids),
    }
    entity_event = EventWriter(session, org_id).emit(
        event_type="operational_case.created",
        entity_type="operational_case",
        entity_id=case.id,
        payload=payload,
        actor_id=actor.id,
    )
    OperationalCaseEventRepository(session).add(
        org_id=org_id,
        case_id=case.id,
        case_version=1,
        event_type="operational_case.created",
        actor_id=actor.id,
        actor_label=actor.email,
        payload=payload,
        entity_event_id=entity_event.id,
    )
    session.flush()
    return recall


# --- progress -----------------------------------------------------------------------------------


def _contacts(session: Session, org_id: UUID, recall_id: UUID) -> list[RecallContact]:
    return (
        session.query(RecallContact)
        .filter(RecallContact.org_id == org_id, RecallContact.recall_id == recall_id)
        .order_by(RecallContact.customer_name, RecallContact.product_name)
        .all()
    )


def _contact_done(c: RecallContact) -> bool:
    if c.unreachable_note:
        return True
    accounted = Decimal(str(c.recovered_qty)) + Decimal(str(c.disposed_qty))
    return c.acknowledged_at is not None and accounted >= Decimal(str(c.quantity_supplied))


def blockers(session: Session, org_id: UUID, recall: Recall) -> list[str]:
    """What still stops this recall being closed, in plain words. Empty means complete."""
    out = []
    for c in _contacts(session, org_id, recall.id):
        if c.unreachable_note:
            continue
        if c.acknowledged_at is None:
            out.append(f"{c.customer_name} hasn't acknowledged the notice ({c.product_name})")
        left = Decimal(str(c.quantity_supplied)) - Decimal(str(c.recovered_qty)) - Decimal(str(c.disposed_qty))
        if left > 0:
            out.append(
                f"{_plain(left)} {c.unit} of {c.product_name} at {c.customer_name} not yet recovered or disposed of"
            )
    return out


def assert_complete_for_case(session: Session, org_id: UUID, case: OperationalCase) -> None:
    """Called by the operational-case transitions: a recall resolves only when it is complete."""
    from app.features.operational_cases.services.operational_case_service import CaseError

    recall = session.query(Recall).filter(Recall.org_id == org_id, Recall.case_id == case.id).one_or_none()
    if recall is None:
        raise CaseError(409, "recall_missing", "recall record not found for this case")
    left = blockers(session, org_id, recall)
    if left:
        raise CaseError(409, "recall_incomplete", "the recall isn't complete yet", extra={"blockers": left})


# --- contact actions ------------------------------------------------------------------------------


def _contact(session: Session, org_id: UUID, recall_id: UUID, contact_id: UUID) -> tuple[Recall, RecallContact]:
    recall = session.query(Recall).filter(Recall.org_id == org_id, Recall.id == recall_id).one_or_none()
    if recall is None:
        raise RecallError("Recall not found", 404)
    case = session.get(OperationalCase, recall.case_id)
    if case is None or case.status not in CaseStatus.ACTIVE or case.status == CaseStatus.RESOLVED:
        raise RecallError("This recall is closed", 409)
    contact = (
        session.query(RecallContact)
        .filter(RecallContact.org_id == org_id, RecallContact.recall_id == recall.id, RecallContact.id == contact_id)
        .with_for_update()
        .one_or_none()
    )
    if contact is None:
        raise RecallError("Customer not found on this recall", 404)
    return recall, contact


def _log(session: Session, org_id: UUID, recall: Recall, contact: RecallContact, action: str, user_id, detail: dict):
    EventWriter(session, org_id).emit(
        event_type=f"recall.{action}",
        entity_type="operational_case",
        entity_id=recall.case_id,
        payload={
            "recall_id": str(recall.id),
            "contact_id": str(contact.id),
            "customer": contact.customer_name,
            **detail,
        },
        actor_id=user_id,
    )


def record_notice_sent(session, org_id, user_id, recall_id, contact_id, *, channel, sent_at: datetime) -> RecallContact:
    recall, c = _contact(session, org_id, recall_id, contact_id)
    c.notice_channel = _text(channel, "how it was sent (email, phone, visit)", max_len=100)
    if sent_at > utc_now():
        raise RecallError("It can't have been sent in the future")
    c.notice_sent_at = sent_at
    c.updated_by = user_id
    _log(session, org_id, recall, c, "notice_sent", user_id, {"channel": c.notice_channel})
    session.flush()
    return c


def record_acknowledgement(session, org_id, user_id, recall_id, contact_id, *, by, note, at: datetime) -> RecallContact:
    recall, c = _contact(session, org_id, recall_id, contact_id)
    c.acknowledged_by = _text(by, "who acknowledged it", max_len=255)
    c.ack_note = _text(note, "a note", required=False)
    if at > utc_now():
        raise RecallError("It can't have been acknowledged in the future")
    c.acknowledged_at = at
    c.unreachable_note = None
    c.updated_by = user_id
    _log(session, org_id, recall, c, "acknowledged", user_id, {"by": c.acknowledged_by})
    session.flush()
    return c


def record_unreachable(session, org_id, user_id, recall_id, contact_id, *, note) -> RecallContact:
    recall, c = _contact(session, org_id, recall_id, contact_id)
    if c.acknowledged_at is not None:
        raise RecallError("This customer already acknowledged the notice", 409)
    c.unreachable_note = _text(note, "what was tried to reach them")
    c.updated_by = user_id
    _log(session, org_id, recall, c, "unreachable", user_id, {"note": c.unreachable_note})
    session.flush()
    return c


def record_quantities(session, org_id, user_id, recall_id, contact_id, *, recovered, disposed) -> RecallContact:
    """Set the totals so far (not deltas): what came back to you, and what the customer disposed of."""
    recall, c = _contact(session, org_id, recall_id, contact_id)
    rec = _qty(recovered, "Recovered")
    dis = _qty(disposed, "Disposed of")
    supplied = Decimal(str(c.quantity_supplied))
    if rec + dis > supplied:
        raise RecallError(f"Only {_plain(supplied)} {c.unit} were supplied to {c.customer_name}")
    c.recovered_qty = rec
    c.disposed_qty = dis
    c.updated_by = user_id
    _log(session, org_id, recall, c, "quantities", user_id, {"recovered": str(rec), "disposed": str(dis)})
    session.flush()
    return c


# --- the notice (drafted, never sent) -------------------------------------------------------------


def draft_notice(org_name: str, recall: Recall, c: RecallContact) -> dict:
    drill = "THIS IS A RECALL DRILL. NO ACTION IS NEEDED WITH REAL STOCK.\n\n" if recall.is_drill else ""
    invoices = ", ".join(c.invoices or []) or "your recent order"
    why = {
        "health": "a possible risk to health",
        "quality": "a quality problem",
        "regulatory": "a regulatory requirement",
    }[recall.risk]
    body = (
        f"{drill}Dear {c.customer_name},\n\n"
        f"We are recalling {c.product_name} supplied to you ({_plain(c.quantity_supplied)} {c.unit}, {invoices}) "
        f"because of {why}: {recall.reason}\n\n"
        "Please stop selling or using it straight away, keep it separate, and reply to confirm you have received "
        "this notice and how many you still hold. We will arrange collection or tell you how to dispose of it, and "
        "credit you for it.\n\n"
        f"Thank you,\n{org_name}"
    )
    subject = f"{'[DRILL] ' if recall.is_drill else ''}Product recall: {c.product_name}"
    return {"subject": subject, "body": body}


# --- reading --------------------------------------------------------------------------------------


def serialise_contact(c: RecallContact) -> dict:
    return {
        "id": str(c.id),
        "contact_id": str(c.contact_id) if c.contact_id else None,
        "customer_name": c.customer_name,
        "product_name": c.product_name,
        "unit": c.unit,
        "quantity_supplied": _plain(c.quantity_supplied),
        "invoices": c.invoices or [],
        "notice_sent_at": c.notice_sent_at.isoformat() if c.notice_sent_at else None,
        "notice_channel": c.notice_channel,
        "acknowledged_at": c.acknowledged_at.isoformat() if c.acknowledged_at else None,
        "acknowledged_by": c.acknowledged_by,
        "ack_note": c.ack_note,
        "unreachable_note": c.unreachable_note,
        "recovered_qty": _plain(c.recovered_qty),
        "disposed_qty": _plain(c.disposed_qty),
        "done": _contact_done(c),
    }


def serialise(session: Session, org_id: UUID, recall: Recall) -> dict:
    from app.features.operational_cases.services.operational_case_service import serialize_case_compact

    case = session.get(OperationalCase, recall.case_id)
    contacts = _contacts(session, org_id, recall.id)
    supplied = sum((Decimal(str(c.quantity_supplied)) for c in contacts), Decimal(0))
    accounted = sum((Decimal(str(c.recovered_qty)) + Decimal(str(c.disposed_qty)) for c in contacts), Decimal(0))
    left = blockers(session, org_id, recall)
    return {
        "id": str(recall.id),
        "case": serialize_case_compact(case),
        "root_lot_id": str(recall.root_lot_id),
        "reason": recall.reason,
        "risk": recall.risk,
        "is_drill": recall.is_drill,
        "lots_in_scope": recall.scope_lots or [],
        "holds_placed": len(recall.hold_ids or []),
        "opened_at": recall.opened_at.isoformat(),
        "contacts": [serialise_contact(c) for c in contacts],
        "progress": {
            "customers": len(contacts),
            "acknowledged": sum(1 for c in contacts if c.acknowledged_at is not None),
            "unreachable": sum(1 for c in contacts if c.unreachable_note),
            "supplied": _plain(supplied),
            "accounted": _plain(accounted),
            "complete": not left,
            "blockers": left,
        },
    }


def list_recalls(session: Session, org_id: UUID, limit: int = 100) -> list[Recall]:
    return session.query(Recall).filter(Recall.org_id == org_id).order_by(Recall.opened_at.desc()).limit(limit).all()
