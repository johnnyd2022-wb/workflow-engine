"""GL-P02: place, enforce and release a quality hold on a lot.

Enforcement lives at the one place every stock quantity change already passes: the ORM
flush, inside ``allow_inventory_quantity_write(reason)``. When the reason is a *use* of
stock (production, a sale, a tasting, a contract dispatch, splitting a lot to move part of
it) and a held lot's quantity would go down, the flush raises :class:`LotOnHoldError`. Every
current and future path that uses stock is covered without each one remembering to check.

Allowed on a held lot: counting it (manual correction, stocktake), moving it whole,
disposing of it as waste, reversing a sale, and receiving more into it.

Selection paths (FIFO sales matching, the planner) skip held lots up front so a sale falls
through to the next lot instead of failing; the flush guard is the backstop.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.lot_hold import LotHold
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, inventory_quantity_write_reason
from app.core.utils.time import utc_now

# Quantity going down for one of these reasons is a use of the stock, which a hold stops.
USE_REASONS = frozenset(
    {
        InventoryQuantityWriteReason.EXECUTION_STEP_INVENTORY.value,
        InventoryQuantityWriteReason.SALES_FIFO_CONSUMPTION.value,
        InventoryQuantityWriteReason.TASTING_DISPATCH.value,
        InventoryQuantityWriteReason.CONTRACT_DISPATCH.value,
        InventoryQuantityWriteReason.STOCK_TRANSFER.value,
    }
)

MAX_REASON = 500


class LotHoldError(ValueError):
    """A hold request that can't be done as asked (shown to the person as-is)."""


class LotOnHoldError(ValueError):
    """Stock on a held lot was about to be used. A ValueError, so routes answer 400 with the message."""

    def __init__(self, item_name: str, reason: str):
        self.item_name = item_name
        self.reason = reason
        super().__init__(f"{item_name} is on quality hold ({reason}). Release the hold before using it.")


def open_holds(session: Session, org_id: UUID, item_ids=None) -> dict[UUID, LotHold]:
    """Open holds for this org, keyed by lot id; limited to ``item_ids`` when given."""
    query = select(LotHold).where(LotHold.org_id == org_id, LotHold.released_at.is_(None))
    if item_ids is not None:
        ids = list(item_ids)
        if not ids:
            return {}
        query = query.where(LotHold.inventory_item_id.in_(ids))
    return {hold.inventory_item_id: hold for hold in session.execute(query).scalars()}


def held_lot_ids_subquery(org_id: UUID):
    """``InventoryItem.id NOT IN (this)`` keeps held lots out of a selection."""
    return select(LotHold.inventory_item_id).where(LotHold.org_id == org_id, LotHold.released_at.is_(None))


def _item(session: Session, org_id: UUID, item_id: UUID) -> InventoryItem:
    item = session.execute(
        select(InventoryItem).where(InventoryItem.org_id == org_id, InventoryItem.id == item_id)
    ).scalar_one_or_none()
    if item is None:
        raise LookupError("Lot not found")
    return item


def made_from(session: Session, org_id: UUID, item_id: UUID) -> list[dict]:
    """Lots made from this one, at any depth, with whether each is already held."""
    from app.core.backend.dagtraversal import trace_forward

    _item(session, org_id, item_id)
    nodes = trace_forward(org_id, session, item_id, include_quantity_filter=False)["items"]
    ids = [UUID(n["id"]) for n in nodes if n["id"] != str(item_id)]
    held = open_holds(session, org_id, ids)
    out = []
    for node in nodes:
        node_id = UUID(node["id"])
        if node_id == item_id:
            continue
        out.append(
            {
                "id": str(node_id),
                "name": node.get("display_label") or node.get("name"),
                "quantity": node.get("quantity"),
                "unit": node.get("unit"),
                "inventory_type": node.get("inventory_type"),
                "in_stock": _positive(node.get("quantity")),
                "on_hold": node_id in held,
            }
        )
    return out


def _positive(value) -> bool:
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def _emit(session: Session, org_id: UUID, event_type: str, hold: LotHold, user_id: UUID | None, payload: dict):
    from app.core.backend.event_writer import EventWriter

    EventWriter(session, org_id).emit(
        event_type=event_type,
        entity_type="inventory_item",
        entity_id=hold.inventory_item_id,
        payload={"hold_id": str(hold.id), **payload},
        actor_id=user_id,
    )


def place_hold(
    session: Session,
    org_id: UUID,
    item_id: UUID,
    reason: str,
    user_id: UUID | None,
    also_hold: list[UUID] | tuple = (),
) -> list[LotHold]:
    """Hold a lot, and any of the lots made from it named in ``also_hold``. Caller commits."""
    reason = (reason or "").strip()
    if not reason:
        raise LotHoldError("Say why the lot is held")
    if len(reason) > MAX_REASON:
        raise LotHoldError(f"Keep the reason under {MAX_REASON} characters")
    item = _item(session, org_id, item_id)
    if open_holds(session, org_id, [item.id]):
        raise LotHoldError(f"{item.display_label or item.name} is already on hold")

    extra = list(dict.fromkeys(UUID(str(i)) for i in also_hold))
    if extra:
        allowed = {UUID(d["id"]) for d in made_from(session, org_id, item.id)}
        stray = [i for i in extra if i not in allowed]
        if stray:
            raise LotHoldError("Only lots made from this one can be held with it")

    root = LotHold(org_id=org_id, inventory_item_id=item.id, reason=reason, placed_by=user_id, placed_at=utc_now())
    session.add(root)
    session.flush()
    holds = [root]
    already = open_holds(session, org_id, extra)
    for other in extra:
        if other in already:
            continue
        hold = LotHold(
            org_id=org_id,
            inventory_item_id=other,
            reason=reason,
            source_hold_id=root.id,
            placed_by=user_id,
            placed_at=root.placed_at,
        )
        session.add(hold)
        holds.append(hold)
    session.flush()
    for hold in holds:
        _emit(session, org_id, "inventory_item.hold_placed", hold, user_id, {"reason": reason})
    return holds


def release_hold(session: Session, org_id: UUID, hold_id: UUID, note: str, user_id: UUID | None) -> LotHold:
    """Close an open hold with a note. Caller commits."""
    note = (note or "").strip()
    if not note:
        raise LotHoldError("Say why the lot can be released (e.g. retested and passed)")
    if len(note) > MAX_REASON:
        raise LotHoldError(f"Keep the note under {MAX_REASON} characters")
    hold = session.execute(
        select(LotHold).where(LotHold.org_id == org_id, LotHold.id == hold_id).with_for_update()
    ).scalar_one_or_none()
    if hold is None:
        raise LookupError("Hold not found")
    if hold.released_at is not None:
        raise LotHoldError("This hold was already released")
    hold.released_at = utc_now()
    hold.released_by = user_id
    hold.release_note = note
    session.flush()
    _emit(session, org_id, "inventory_item.hold_released", hold, user_id, {"note": note})
    return hold


def history(session: Session, org_id: UUID, item_id: UUID) -> list[LotHold]:
    _item(session, org_id, item_id)
    return list(
        session.execute(
            select(LotHold)
            .where(LotHold.org_id == org_id, LotHold.inventory_item_id == item_id)
            .order_by(LotHold.placed_at.desc())
        ).scalars()
    )


def serialise(hold: LotHold) -> dict:
    return {
        "id": str(hold.id),
        "inventory_item_id": str(hold.inventory_item_id),
        "reason": hold.reason,
        "source_hold_id": str(hold.source_hold_id) if hold.source_hold_id else None,
        "placed_by": str(hold.placed_by) if hold.placed_by else None,
        "placed_at": hold.placed_at.isoformat() if hold.placed_at else None,
        "released_by": str(hold.released_by) if hold.released_by else None,
        "released_at": hold.released_at.isoformat() if hold.released_at else None,
        "release_note": hold.release_note,
        "open": hold.released_at is None,
    }


# --- enforcement ----------------------------------------------------------------------------------


def _before_flush(session: Session, _flush_context, _instances) -> None:
    if inventory_quantity_write_reason() not in USE_REASONS:
        return
    lowered: dict[tuple, InventoryItem] = {}
    for obj in session.dirty:
        if not isinstance(obj, InventoryItem):
            continue
        hist = sa_inspect(obj).attrs.quantity.history
        if not hist.has_changes() or not hist.deleted or not hist.added:
            continue
        before, after = hist.deleted[0], hist.added[0]
        try:
            if Decimal(str(after)) >= Decimal(str(before)):
                continue
        except (InvalidOperation, TypeError, ValueError):
            pass
        lowered[(obj.org_id, obj.id)] = obj
    if not lowered:
        return
    with session.no_autoflush:
        for org_id in {org for org, _ in lowered}:
            ids = [item_id for org, item_id in lowered if org == org_id]
            for item_id, hold in open_holds(session, org_id, ids).items():
                item = lowered[(org_id, item_id)]
                raise LotOnHoldError(item.display_label or item.name, hold.reason)


def register_lot_hold_guard() -> None:
    if not getattr(register_lot_hold_guard, "_registered", False):
        event.listen(Session, "before_flush", _before_flush, propagate=True)
        register_lot_hold_guard._registered = True  # type: ignore[attr-defined]
