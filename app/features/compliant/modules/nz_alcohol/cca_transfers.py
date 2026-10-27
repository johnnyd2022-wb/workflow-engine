"""Sales to another business's Customs-controlled area, and their movement register (GL-P08).

Goods leaving the CCA are either transferred to another CCA or entered for duty. A sale is a
transfer when its customer is linked to a destination CCA (a duty free shop, an export
warehouse, a contract customer's licensed area), or when it was marked as one by hand. The
excise draft leaves transfers out of the duty lines (``excise.removals_between``).

Each transfer needs a register row (Customs operational policy *Product movement excise unpaid
- alcohol*, v2.0, para 15): when it moved, who carried it, and when the destination
acknowledged receipt (para 16). Until the receipt is recorded the goods are still this CCA's
responsibility (para 11), so the status says so.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from app.features.compliant.models.cca_transfers import DESTINATION_KINDS, CcaDeparture, CcaDestination

KIND_LABELS = {
    "duty_free": "Duty free shop",
    "export_warehouse": "Export warehouse",
    "manufacturer": "Manufacturer (further manufacture or contract)",
    "storage": "Off-site storage",
    "other": "Other CCA",
}
NZ = ZoneInfo("Pacific/Auckland")  # moves are entered and dated in NZ time
# A receipt not acknowledged after this many days is called out, so it is chased.
RECEIPT_OVERDUE_DAYS = 14


def _text(data: dict, field: str, limit: int, label: str, required: bool = True) -> str | None:
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"Enter the {label}")
        return None
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise ValueError(f"The {label} must be text of at most {limit} characters")
    return value.strip()


def _when(value, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Enter {label}")
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"{label.capitalize()} must be a date and time like 2026-10-01T14:30") from None
    return moment.replace(tzinfo=NZ) if moment.tzinfo is None else moment


def _nz_day(moment: datetime) -> date:
    return moment.astimezone(NZ).date()


def _day(value, label: str) -> date:
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{label.capitalize()} must be a date like 2026-10-01") from None


# --- destinations ----------------------------------------------------------------------------


def destination_dict(row: CcaDestination, contact_name: str | None = None) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "cca_code": row.cca_code,
        "address": row.address,
        "kind": row.kind,
        "kind_label": KIND_LABELS[row.kind],
        "contact_id": str(row.contact_id) if row.contact_id else None,
        "contact_name": contact_name,
    }


def destinations(session, org_id: UUID) -> list[dict]:
    from app.features.crm.models.xero_contact import XeroContact

    rows = session.query(CcaDestination).filter(CcaDestination.org_id == org_id).order_by(CcaDestination.name).all()
    contact_ids = {r.contact_id for r in rows if r.contact_id}
    names = (
        {
            c.id: c.name
            for c in session.query(XeroContact).filter(XeroContact.org_id == org_id, XeroContact.id.in_(contact_ids))
        }
        if contact_ids
        else {}
    )
    return [destination_dict(r, names.get(r.contact_id)) for r in rows]


def customers(session, org_id: UUID, limit: int = 2000) -> list[dict]:
    """Customers a destination can be linked to, by name."""
    from app.features.crm.models.xero_contact import XeroContact

    rows = (
        session.query(XeroContact.id, XeroContact.name)
        .filter(XeroContact.org_id == org_id, XeroContact.is_customer.is_(True))
        .order_by(XeroContact.name)
        .limit(limit)
    )
    return [{"id": str(i), "name": n} for i, n in rows]


def save_destination(session, org_id: UUID, data: dict, destination_id: UUID | None = None) -> CcaDestination:
    from app.features.crm.models.xero_contact import XeroContact

    if not isinstance(data, dict):
        raise ValueError("Send the destination as an object")
    row = None
    if destination_id is not None:
        row = (
            session.query(CcaDestination)
            .filter(CcaDestination.org_id == org_id, CcaDestination.id == destination_id)
            .one_or_none()
        )
        if row is None:
            raise LookupError("No such destination")
    name = _text(data, "name", 200, "destination's name")
    code = _text(data, "cca_code", 100, "destination's CCA code")
    address = _text(data, "address", 500, "destination's address")
    kind = data.get("kind")
    if kind not in DESTINATION_KINDS:
        raise ValueError("Choose what kind of CCA the destination is")
    contact_id = data.get("contact_id") or None
    if contact_id is not None:
        try:
            contact_id = UUID(str(contact_id))
        except ValueError:
            raise ValueError("Choose a customer from the list") from None
        contact = (
            session.query(XeroContact).filter(XeroContact.org_id == org_id, XeroContact.id == contact_id).one_or_none()
        )
        if contact is None:
            raise ValueError("Choose a customer from the list")
        taken = (
            session.query(CcaDestination)
            .filter(
                CcaDestination.org_id == org_id,
                CcaDestination.contact_id == contact_id,
                CcaDestination.id != (row.id if row else None),
            )
            .first()
        )
        if taken is not None:
            raise ValueError(f"{contact.name} is already linked to {taken.name}")
    clash = (
        session.query(CcaDestination)
        .filter(
            CcaDestination.org_id == org_id,
            CcaDestination.cca_code == code,
            CcaDestination.id != (row.id if row else None),
        )
        .first()
    )
    if clash is not None:
        raise ValueError(f"CCA code {code} is already recorded for {clash.name}")
    if row is None:
        row = CcaDestination(org_id=org_id)
        session.add(row)
    row.name, row.cca_code, row.address, row.kind, row.contact_id = name, code, address, kind, contact_id
    session.flush()
    return row


# --- which sales are transfers -----------------------------------------------------------------


def _status(departure: CcaDeparture | None, today: date) -> str:
    if departure is None:
        return "needs_details"
    if departure.received_on is None:
        moved = _nz_day(departure.moved_at)
        return "receipt_overdue" if (today - moved).days > RECEIPT_OVERDUE_DAYS else "awaiting_receipt"
    return "received"


def departure_dict(row: CcaDeparture) -> dict:
    return {
        "id": str(row.id),
        "moved_at": row.moved_at.astimezone(NZ).isoformat(),
        "carrier": row.carrier,
        "consignment_note": row.consignment_note,
        "received_on": row.received_on.isoformat() if row.received_on else None,
        "receipt_reference": row.receipt_reference,
        "notes": row.notes,
    }


def for_invoices(session, org_id: UUID, invoices, today: date | None = None) -> dict[str, dict]:
    """``{xero_invoice_id: transfer}`` for the invoices that went to another CCA.

    A register row decides (it names its destination); otherwise the customer's link does.
    """
    invoices = list({inv.xero_invoice_id: inv for inv in invoices}.values())
    if not invoices:
        return {}
    today = today or date.today()
    dests = {d.id: d for d in session.query(CcaDestination).filter(CcaDestination.org_id == org_id)}
    if not dests:
        return {}
    by_contact = {d.contact_id: d for d in dests.values() if d.contact_id}
    departures = {
        d.xero_invoice_id: d
        for d in session.query(CcaDeparture).filter(
            CcaDeparture.org_id == org_id,
            CcaDeparture.xero_invoice_id.in_([inv.xero_invoice_id for inv in invoices]),
        )
    }
    out = {}
    for inv in invoices:
        departure = departures.get(inv.xero_invoice_id)
        dest = dests.get(departure.destination_id) if departure else by_contact.get(inv.contact_id)
        if dest is None:
            continue
        out[inv.xero_invoice_id] = {
            "xero_invoice_id": inv.xero_invoice_id,
            "destination": destination_dict(dest),
            "status": _status(departure, today),
            "departure": departure_dict(departure) if departure else None,
        }
    return out


def _sales_rows(session, org_id: UUID, since: date, invoice_ids: list[str] | None = None):
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_invoice import XeroInvoice

    q = (
        session.query(SalesFifoAllocation, XeroInvoice)
        .join(
            XeroInvoice,
            (XeroInvoice.org_id == SalesFifoAllocation.org_id)
            & (XeroInvoice.xero_invoice_id == SalesFifoAllocation.xero_invoice_id),
        )
        .filter(SalesFifoAllocation.org_id == org_id)
    )
    if invoice_ids is not None:
        q = q.filter(XeroInvoice.xero_invoice_id.in_(invoice_ids))
    else:
        q = q.filter(XeroInvoice.date >= since)
    return q.all()


def register(session, org_id: UUID, since: date | None = None, today: date | None = None) -> dict:
    """Every sale to another CCA since ``since`` (a year by default), with what moved and its status.

    Transfers still waiting on details or a receipt are listed whatever their date, since
    they are the ones to act on.
    """
    from app.core.db.models.inventory_item import InventoryItem
    from app.features.compliant.modules.nz_alcohol.excise import _base_name
    from app.features.crm.models.xero_contact import XeroContact

    today = today or date.today()
    since = since or today - timedelta(days=365)
    rows = _sales_rows(session, org_id, since)
    open_ids = [
        d.xero_invoice_id
        for d in session.query(CcaDeparture).filter(CcaDeparture.org_id == org_id, CcaDeparture.received_on.is_(None))
    ]
    seen = {inv.xero_invoice_id for _, inv in rows}
    extra = [i for i in open_ids if i not in seen]
    if extra:
        rows += _sales_rows(session, org_id, since, extra)
    transfers = for_invoices(session, org_id, [inv for _, inv in rows], today)
    rows = [(a, inv) for a, inv in rows if inv.xero_invoice_id in transfers]
    items = (
        {
            i.id: i
            for i in session.query(InventoryItem).filter(
                InventoryItem.org_id == org_id, InventoryItem.id.in_({a.inventory_item_id for a, _ in rows})
            )
        }
        if rows
        else {}
    )
    contact_ids = {inv.contact_id for _, inv in rows if inv.contact_id}
    contacts = (
        {c.id: c.name for c in session.query(XeroContact).filter(XeroContact.id.in_(contact_ids))}
        if contact_ids
        else {}
    )
    sales: dict[str, dict] = {}
    for allocation, inv in rows:
        transfer = transfers[inv.xero_invoice_id]
        departure = transfer["departure"]
        sale = sales.setdefault(
            inv.xero_invoice_id,
            {
                **transfer,
                "kind": "sale",
                "receipt_url": f"/api/compliant/nz-alcohol/cca-transfers/{departure['id']}/receipt"
                if departure
                else None,
                "reference": inv.invoice_number or inv.xero_invoice_id,
                "invoice_date": inv.date.isoformat() if inv.date else None,
                "customer": contacts.get(inv.contact_id),
                "goods": {},
            },
        )
        item = items.get(allocation.inventory_item_id)
        product = _base_name(item.name) if item else "Unknown item"
        unit = item.unit if item else ""
        line = sale["goods"].setdefault((product, unit), {"product": product, "unit": unit, "quantity": Decimal("0")})
        line["quantity"] += Decimal(str(allocation.quantity))
    out = []
    for sale in sales.values():
        sale["goods"] = [
            {**g, "quantity": format(g["quantity"].normalize(), "f")}
            for g in sorted(sale["goods"].values(), key=lambda g: g["product"])
        ]
        out.append(sale)
    out.extend(_contract_rows(session, org_id, since, today))
    order = {"needs_details": 0, "receipt_overdue": 1, "awaiting_receipt": 2, "received": 3}
    out.sort(key=lambda s: (order[s["status"]], s["invoice_date"] or ""), reverse=False)
    counts = {k: sum(1 for s in out if s["status"] == k) for k in order}
    return {"since": since.isoformat(), "transfers": out, "counts": counts}


def _contract_rows(session, org_id: UUID, since: date, today: date) -> list[dict]:
    """Contract goods dispatched to the customer's CCA (GL-P08 part 2), shaped like a sale's row."""
    from datetime import datetime as _dt

    from sqlalchemy import or_

    from app.features.compliant.modules.nz_alcohol.excise import _base_name
    from app.features.contract_manufacturing.models.dispatch import ContractDispatch
    from app.features.contract_manufacturing.models.orders import ContractOrder
    from app.features.contract_manufacturing.services.dispatches import dispatch_dict

    rows = (
        session.query(ContractDispatch, ContractOrder.reference)
        .join(
            ContractOrder,
            (ContractOrder.org_id == ContractDispatch.org_id) & (ContractOrder.id == ContractDispatch.order_id),
        )
        .filter(
            ContractDispatch.org_id == org_id,
            ContractDispatch.treatment == "cca_transfer",
            or_(
                ContractDispatch.moved_at >= _dt.combine(since, _dt.min.time(), tzinfo=NZ),
                ContractDispatch.received_on.is_(None),
            ),
        )
        .all()
    )
    out = []
    for row, reference in rows:
        d = dispatch_dict(row, today)
        goods: dict = {}
        for line in d["lines"]:
            key = (_base_name(line["product_name"]), line["unit"])
            g = goods.setdefault(key, {"product": key[0], "unit": key[1], "quantity": Decimal("0")})
            g["quantity"] += Decimal(line["quantity"])
        out.append(
            {
                "kind": "contract",
                "xero_invoice_id": f"contract-{d['id']}",
                "order_id": d["order_id"],
                "destination": {
                    "id": None,
                    "name": row.destination_name,
                    "cca_code": row.destination_cca,
                    "address": "",
                    "kind": "manufacturer",
                    "kind_label": "Contract customer",
                },
                "status": d["status"],
                "departure": {
                    "id": d["id"],
                    **{
                        k: d[k] for k in ("moved_at", "carrier", "consignment_note", "received_on", "receipt_reference")
                    },
                    "notes": None,
                },
                "receipt_url": f"/api/core/contract-orders/{d['order_id']}/dispatches/{d['id']}/receipt",
                "reference": f"{reference} dispatch",
                "invoice_date": _nz_day(row.moved_at).isoformat(),
                "customer": row.destination_name,
                "goods": [
                    {**g, "quantity": format(g["quantity"].normalize(), "f")}
                    for g in sorted(goods.values(), key=lambda g: g["product"])
                ],
            }
        )
    return out


# --- the register row -----------------------------------------------------------------------------


def _invoice(session, org_id: UUID, xero_invoice_id: str):
    from app.features.crm.models.xero_invoice import XeroInvoice

    inv = (
        session.query(XeroInvoice)
        .filter(XeroInvoice.org_id == org_id, XeroInvoice.xero_invoice_id == xero_invoice_id)
        .one_or_none()
    )
    if inv is None:
        raise ValueError("Choose a sale from the list")
    return inv


def record_departure(session, org_id: UUID, data: dict, user_id) -> CcaDeparture:
    """Record (or correct) when a sale left for another CCA, and who carried it."""
    if not isinstance(data, dict):
        raise ValueError("Send the movement as an object")
    invoice_id = _text(data, "xero_invoice_id", 100, "sale")
    inv = _invoice(session, org_id, invoice_id)
    try:
        destination_id = UUID(str(data.get("destination_id")))
    except ValueError:
        raise ValueError("Choose the CCA the goods went to") from None
    dest = (
        session.query(CcaDestination)
        .filter(CcaDestination.org_id == org_id, CcaDestination.id == destination_id)
        .one_or_none()
    )
    if dest is None:
        raise ValueError("Choose the CCA the goods went to")
    moved_at = _when(data.get("moved_at"), "when the goods left")
    if inv.date and _nz_day(moved_at) < inv.date - timedelta(days=60):
        raise ValueError("The goods can't have left more than 60 days before the sale")
    row = (
        session.query(CcaDeparture)
        .filter(CcaDeparture.org_id == org_id, CcaDeparture.xero_invoice_id == invoice_id)
        .one_or_none()
    )
    if row is None:
        row = CcaDeparture(org_id=org_id, xero_invoice_id=invoice_id, recorded_by_user_id=user_id)
        session.add(row)
    row.destination_id = dest.id
    row.moved_at = moved_at
    row.carrier = _text(data, "carrier", 200, "carrier")
    row.consignment_note = _text(data, "consignment_note", 200, "consignment note", required=False)
    row.notes = _text(data, "notes", 2000, "notes", required=False)
    session.flush()
    return row


def record_receipt(session, org_id: UUID, departure_id: UUID, data: dict) -> CcaDeparture:
    """The destination's written acknowledgement that the goods arrived (para 16)."""
    if not isinstance(data, dict):
        raise ValueError("Send the receipt as an object")
    row = (
        session.query(CcaDeparture).filter(CcaDeparture.org_id == org_id, CcaDeparture.id == departure_id).one_or_none()
    )
    if row is None:
        raise LookupError("No such movement")
    received = _day(data.get("received_on"), "the date it was received")
    if received < _nz_day(row.moved_at):
        raise ValueError("The goods can't be received before they left")
    if received > date.today() + timedelta(days=1):
        raise ValueError("The receipt date can't be in the future")
    row.received_on = received
    row.receipt_reference = _text(data, "receipt_reference", 500, "receipt (who acknowledged it, or the document)")
    session.flush()
    return row


def remove_departure(session, org_id: UUID, departure_id: UUID) -> None:
    """Undo a register row recorded by mistake. A sale to a linked customer stays a transfer."""
    row = (
        session.query(CcaDeparture).filter(CcaDeparture.org_id == org_id, CcaDeparture.id == departure_id).one_or_none()
    )
    if row is None:
        raise LookupError("No such movement")
    session.delete(row)
    session.flush()


def sales_to_mark(session, org_id: UUID, search: str = "", limit: int = 20) -> list[dict]:
    """Recent sales that took stock and aren't transfers yet, for marking one by hand."""
    from sqlalchemy import or_

    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice

    q = (
        session.query(XeroInvoice, XeroContact.name)
        .outerjoin(XeroContact, (XeroContact.org_id == XeroInvoice.org_id) & (XeroContact.id == XeroInvoice.contact_id))
        .filter(
            XeroInvoice.org_id == org_id,
            session.query(SalesFifoAllocation.id)
            .filter(
                SalesFifoAllocation.org_id == org_id,
                SalesFifoAllocation.xero_invoice_id == XeroInvoice.xero_invoice_id,
            )
            .exists(),
        )
    )
    search = (search or "").strip()[:100]
    if search:
        like = f"%{search}%"
        q = q.filter(or_(XeroInvoice.invoice_number.ilike(like), XeroContact.name.ilike(like)))
    rows = q.order_by(XeroInvoice.date.desc().nullslast(), XeroInvoice.invoice_number).limit(limit * 3).all()
    taken = for_invoices(session, org_id, [inv for inv, _ in rows])
    out = []
    for inv, customer in rows:
        if inv.xero_invoice_id in taken:
            continue
        out.append(
            {
                "xero_invoice_id": inv.xero_invoice_id,
                "reference": inv.invoice_number or inv.xero_invoice_id,
                "invoice_date": inv.date.isoformat() if inv.date else None,
                "customer": customer,
            }
        )
        if len(out) == limit:
            break
    return out
