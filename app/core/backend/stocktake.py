"""Stocktakes: count reality and resolve every difference (plan item 2.6).

Customs requires at least an annual stocktake of a licensed (Customs-controlled) area;
discrepancies must be investigated and resolved, and a confirmed unexplained loss is
dutiable and must be reported. This module runs the count and turns each difference into
ordinary dated stock operations, so the excise figures (plan 2.1) follow automatically:

Counted less than expected:
- found_elsewhere: move the stock to where it is. Outside the licensed area, that's a
  removal on the date it left (carried into the current draft if that period is lodged).
- removed_unrecorded (tasting, samples, gift, missed sale): moved to the system place
  "Removed without a sale record" (outside the licensed area), so it's a dutiable removal.
- broken (damaged, faulty): recorded as wastage and flagged so the owner can claim
  remission (pre-authorised licensees in the entry, otherwise form NZCS 277).
- investigating: held open (default 14 days) with no stock change; the line can be
  recounted.
- unexplained_loss: moved to the system place "Unaccounted loss" (outside): dutiable, and
  flagged to advise Customs.

Counted more than expected:
- returned: moved back from the place it was (e.g. a rep's car); excise lists it as a
  return, a possible credit to raise with Customs, never claimed automatically.
- removal_not_happened: added back, flagged as a correction to raise with Customs.
- under_recorded: added back (production was under-recorded).
- unexplained_gain: added back and flagged for review.

Customs' published guidance doesn't cover surpluses; the plan records that their
treatment should be confirmed with Customs. Bulk liquid can have a measurement tolerance
(``stocktake_bulk_tolerance_percent``); counted goods never do.

The expected quantity is taken when each line is counted, not when the stocktake starts,
so sales made during a count don't show up as variances.

Kept in its own blueprint so backend.py doesn't grow.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import Blueprint, Response, g, jsonify, render_template, request
from sqlalchemy import func

from app.core.db import db_session
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.inventory_wastage import InventoryWastage
from app.core.db.models.organisation import Organisation
from app.core.db.models.stock_location import StockLocation
from app.core.db.models.stocktake import Stocktake, StocktakeLine, StocktakeResolution
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.wastage_repo import WastageRepository
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.core.security.permissions import requires_auth
from app.core.utils.inventory_quantity import coerce_stored_quantity
from app.core.utils.log_action import log_action
from app.core.utils.unit_conversion import is_count_unit, normalize_unit, whole_count_error
from app.features.compliant.platform import stock_measures

stocktake_bp = Blueprint("stocktake", __name__, template_folder="../frontend")

SHORTFALL_REASONS = ("found_elsewhere", "removed_unrecorded", "broken", "investigating", "unexplained_loss")
SURPLUS_REASONS = ("returned", "removal_not_happened", "under_recorded", "unexplained_gain")
REMOVED_PLACE = "Removed without a sale record"
LOSS_PLACE = "Unaccounted loss"
INVESTIGATE_DAYS = 14
DEFAULT_BULK_TOLERANCE_PERCENT = Decimal("0.5")
FREQUENCY_MONTHS = {"monthly": 1, "quarterly": 3, "six_monthly": 6, "annual": 12}
_COUNTED_TYPES = (InventoryType.FINAL_PRODUCT.value, InventoryType.WORK_IN_PROGRESS.value)
_MAIN = "Licensed area (main)"


def _d(value) -> Decimal:
    return Decimal(str(value))


def _s(value) -> str:
    return f"{_d(value).normalize():f}"


def _batch(item: InventoryItem):
    return item.supplier_batch_number or (item.extra_data or {}).get("batch_number")


def _measure(session, org_id: UUID, pairs: list, on: date) -> list[dict]:
    """What an installed compliance module measures on this stock (blank when none)."""
    return stock_measures.measure(session, org_id, pairs, on)


def _locations(session, org_id: UUID) -> dict:
    return {loc.id: loc for loc in session.query(StockLocation).filter(StockLocation.org_id == org_id)}


def _place(item: InventoryItem, locations: dict) -> tuple[str, bool]:
    loc = locations.get(item.location_id)
    if loc is None:
        return _MAIN, True
    return loc.name, bool(loc.inside_licensed_area)


# --- stock position ------------------------------------------------------------------------


def stock_position(session, org_id: UUID, today: date) -> dict:
    """Finished goods and work in progress by place and batch, e.g. for a regulator's visit."""
    locations = _locations(session, org_id)
    items = (
        session.query(InventoryItem)
        .filter(
            InventoryItem.org_id == org_id,
            InventoryItem.inventory_type.in_(_COUNTED_TYPES),
            InventoryItem.quantity > 0,
        )
        .order_by(InventoryItem.name.asc(), InventoryItem.supplier_batch_number.asc())
        .all()
    )
    measures = _measure(session, org_id, [(i, i.quantity) for i in items], today)
    places: dict = {}
    for item, m in zip(items, measures, strict=True):
        name, inside = _place(item, locations)
        place = places.setdefault(
            str(item.location_id) if item.location_id else "main",
            {
                "location_id": str(item.location_id) if item.location_id else None,
                "name": name,
                "inside_licensed_area": inside,
                "lots": [],
                "total_measure": Decimal("0"),
            },
        )
        place["lots"].append(
            {
                "id": str(item.id),
                "name": item.name,
                "batch": _batch(item),
                "stage": "In progress" if item.inventory_type == InventoryType.WORK_IN_PROGRESS.value else "Finished",
                "quantity": _s(item.quantity),
                "unit": item.unit,
                "measure": m["measure"],
                "detail": m["detail"],
            }
        )
        if m["measure"] is not None:
            place["total_measure"] += _d(m["measure"])
    ordered = sorted(
        places.values(),
        key=lambda p: (p["location_id"] is not None, not p["inside_licensed_area"], p["name"].lower()),
    )
    for place in ordered:
        place["total_measure"] = _s(place["total_measure"])
    return {
        "as_at": today.isoformat(),
        "labels": stock_measures.labels(session, org_id),
        "places": ordered,
        "declared": stock_measures.declared_periods(session, org_id),
    }


def _cell(value) -> str:
    value = "" if value is None else str(value)
    return "'" + value if value and value[0] in ("=", "+", "-", "@", "\t", "\r") else value


def position_csv(position: dict) -> str:
    labels = position["labels"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f"Stock position as at {position['as_at']}"])
    header = ["Place", "Controlled area", "Stage", "Product", "Batch", "Quantity", "Unit"]
    if labels:
        header += ["Detail", labels["measure"]]
    w.writerow(header)
    for place in position["places"]:
        for lot in place["lots"]:
            row = [
                _cell(place["name"]),
                "yes" if place["inside_licensed_area"] else "no",
                lot["stage"],
                _cell(lot["name"]),
                _cell(lot["batch"]),
                lot["quantity"],
                lot["unit"],
            ]
            if labels:
                row += [lot["detail"] or "", lot["measure"] or ""]
            w.writerow(row)
    if labels:
        w.writerow([])
        w.writerow([labels["declared_long"][:1].upper() + labels["declared_long"][1:]])
        w.writerow(["Period start", "Period end", "Declared on", "Reference", labels["measure"], labels["cost"], "Nil"])
        for x in position["declared"]:
            w.writerow(
                [
                    x["period_start"],
                    x["period_end"],
                    x["declared_on"],
                    _cell(x["reference"]),
                    x["measure"],
                    x["cost"],
                    "yes" if x["nil"] else "no",
                ]
            )
    return buf.getvalue()


# --- counting and resolving ----------------------------------------------------------------


def start_stocktake(session, org_id: UUID, counted_on: date, kind: str, location_id, user_id) -> Stocktake:
    if kind not in ("scheduled", "customs_visit"):
        raise ValueError("kind must be scheduled or customs_visit")
    query = session.query(InventoryItem).filter(
        InventoryItem.org_id == org_id,
        InventoryItem.inventory_type.in_(_COUNTED_TYPES),
        InventoryItem.quantity > 0,
    )
    if location_id is not None:
        query = query.filter(InventoryItem.location_id == location_id)
    items = query.all()
    if not items:
        raise ValueError("There's no finished or in-progress stock to count here")
    stocktake = Stocktake(org_id=org_id, counted_on=counted_on, kind=kind, created_by_user_id=user_id)
    session.add(stocktake)
    session.flush()
    session.add_all(
        [
            StocktakeLine(
                org_id=org_id,
                stocktake_id=stocktake.id,
                inventory_item_id=item.id,
                expected_quantity=item.quantity,
                unit=item.unit,
            )
            for item in items
        ]
    )
    session.flush()
    return stocktake


def _tolerance(unit: str, settings: dict | None) -> Decimal:
    if is_count_unit(unit):
        return Decimal("0")
    try:
        value = Decimal(str((settings or {}).get("stocktake_bulk_tolerance_percent", DEFAULT_BULK_TOLERANCE_PERCENT)))
    except InvalidOperation:
        return DEFAULT_BULK_TOLERANCE_PERCENT
    return value if value.is_finite() and value >= 0 else DEFAULT_BULK_TOLERANCE_PERCENT


def record_count(session, line: StocktakeLine, counted, settings: dict | None = None) -> None:
    """Record a count against what the system holds right now.

    Recounting a line that's under investigation drops the investigation: the new count
    is compared with the stock as it stands after any parts already resolved.
    """
    if line.status == "resolved":
        raise ValueError("This line's difference has already been resolved")
    try:
        value = _d(counted)
    except (InvalidOperation, ValueError):
        raise ValueError("Count must be a number") from None
    if not value.is_finite() or value < 0:
        raise ValueError("Count must be 0 or more")
    message = whole_count_error(value, line.unit, what="Count")
    if message:
        raise ValueError(message)
    if line.status == "investigating":
        session.query(StocktakeResolution).filter(
            StocktakeResolution.line_id == line.id, StocktakeResolution.reason == "investigating"
        ).delete(synchronize_session=False)
        line.investigate_until = None
    item = session.get(InventoryItem, line.inventory_item_id)
    line.expected_quantity = item.quantity
    line.counted_quantity = value
    expected = _d(line.expected_quantity)
    allowed = expected * _tolerance(line.unit, settings) / 100
    line.status = "matched" if abs(value - expected) <= allowed else "open"
    session.flush()


def _system_place(session, org_id: UUID, name: str) -> StockLocation:
    loc = session.query(StockLocation).filter(StockLocation.org_id == org_id, StockLocation.name == name).one_or_none()
    if loc is None:
        loc = StockLocation(org_id=org_id, name=name, inside_licensed_area=False)
        session.add(loc)
        session.flush()
    return loc


def _parse_parts(line: StocktakeLine, parts: list[dict], variance: Decimal) -> list:
    allowed = SHORTFALL_REASONS if variance < 0 else SURPLUS_REASONS
    cleaned = []
    for part in parts or []:
        reason = str(part.get("reason") or "")
        if reason not in allowed:
            label = reason.replace("_", " ") or "A reason"
            raise ValueError(f"{label} doesn't apply when stock is {'short' if variance < 0 else 'over'}")
        try:
            qty = _d(part.get("quantity"))
        except (InvalidOperation, ValueError):
            raise ValueError("Each reason needs a quantity") from None
        if not qty.is_finite() or qty <= 0:
            raise ValueError("Each reason needs a quantity above 0")
        message = whole_count_error(qty, line.unit, what="Quantity")
        if message:
            raise ValueError(message)
        try:
            occurred = date.fromisoformat(part["occurred_on"]) if part.get("occurred_on") else None
        except (TypeError, ValueError):
            raise ValueError("Dates must be YYYY-MM-DD") from None
        loc_id = None
        if part.get("location_id"):
            try:
                loc_id = UUID(str(part["location_id"]))
            except ValueError:
                raise ValueError("Unknown place") from None
        note = (str(part.get("note") or "").strip()[:500]) or None
        cleaned.append((reason, qty, occurred, loc_id, note))
    if sum(q for _, q, *_ in cleaned) != abs(variance):
        raise ValueError(f"The reasons must add up to {_s(abs(variance))} {line.unit}")
    if sum(1 for r, *_ in cleaned if r == "investigating") > 1:
        raise ValueError("Investigate the difference once")
    return cleaned


def resolve_line(session, org_id: UUID, line: StocktakeLine, parts: list[dict], user_id, today: date) -> list:
    """Apply one or more reasons that together explain the line's difference."""
    if line.counted_quantity is None:
        raise ValueError("Record the count first")
    if line.status != "open":
        raise ValueError("This line has nothing left to resolve")
    variance = _d(line.counted_quantity) - _d(line.expected_quantity)
    if variance == 0:
        raise ValueError("Nothing to resolve")
    cleaned = _parse_parts(line, parts, variance)
    known = _locations(session, org_id)
    item = session.get(InventoryItem, line.inventory_item_id)
    siblings = {  # the same batch at other places, for "returned"
        lot.location_id: lot
        for lot in session.query(InventoryItem).filter(
            InventoryItem.org_id == org_id,
            InventoryItem.name == item.name,
            InventoryItem.supplier_batch_number == item.supplier_batch_number,
            InventoryItem.id != item.id,
        )
    }
    repo = InventoryRepository(session)
    records = []
    investigating = False
    for reason, qty, occurred, loc_id, note in cleaned:
        occurred = occurred or today
        if occurred > today:
            raise ValueError("Dates can't be in the future")
        if loc_id is not None and loc_id not in known:
            raise ValueError("Unknown place")
        res = StocktakeResolution(
            org_id=org_id,
            line_id=line.id,
            reason=reason,
            quantity=qty,
            occurred_on=occurred,
            note=note,
            created_by_user_id=user_id,
        )
        if reason == "found_elsewhere":
            if loc_id is None:
                raise ValueError("Say where the stock was found")
            if loc_id == item.location_id:
                raise ValueError("That's where it was counted: pick the place it was found")
            _new, transfer = repo.move_lot(
                org_id, item.id, qty, loc_id, occurred, note or "Found at stocktake", user_id, commit=False
            )
            res.location_id = loc_id
            res.dutiable = transfer.direction == "out"
        elif reason in ("removed_unrecorded", "unexplained_loss"):
            label = REMOVED_PLACE if reason == "removed_unrecorded" else LOSS_PLACE
            place = _system_place(session, org_id, label)
            repo.move_lot(
                org_id, item.id, qty, place.id, occurred, note or f"{label} (stocktake)", user_id, commit=False
            )
            res.location_id = place.id
            res.dutiable = True
            res.raise_with_customs = reason == "unexplained_loss"
        elif reason == "broken":
            WastageRepository(session).create_wastage_record(
                org_id=org_id,
                inventory_item_id=item.id,
                quantity_wasted=_s(qty),
                unit=item.unit,
                reason=note or "Broken or damaged (found at stocktake); remission may apply",
                recorded_by=getattr(g, "user_email", None) or getattr(g, "username", None),
            )
            with allow_inventory_quantity_write(InventoryQuantityWriteReason.WASTAGE_RECORD):
                item.quantity = coerce_stored_quantity(_d(item.quantity) - qty)
                session.flush()
            res.raise_with_customs = True  # claim remission
        elif reason == "investigating":
            investigating = True
            line.investigate_until = today + timedelta(days=INVESTIGATE_DAYS)
        elif reason == "returned":
            if loc_id is None:
                raise ValueError("Say where the stock came back from")
            source = siblings.get(loc_id)
            if source is None or _d(source.quantity) < qty:
                raise ValueError("That place doesn't hold enough of this batch to have returned it")
            repo.move_lot(
                org_id,
                source.id,
                qty,
                item.location_id,
                occurred,
                note or "Returned (stocktake)",
                user_id,
                commit=False,
            )
            res.location_id = loc_id
            res.raise_with_customs = True  # possible credit if duty was paid when it left
        else:  # removal_not_happened | under_recorded | unexplained_gain
            with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
                item.quantity = coerce_stored_quantity(_d(item.quantity) + qty)
                session.flush()
            res.raise_with_customs = reason in ("removal_not_happened", "unexplained_gain")
        session.add(res)
        records.append(res)
    line.status = "investigating" if investigating else "resolved"
    session.flush()
    return records


# --- reading a stocktake -------------------------------------------------------------------


def serialise(session, stocktake: Stocktake) -> dict:
    rows = (
        session.query(StocktakeLine, InventoryItem)
        .join(InventoryItem, InventoryItem.id == StocktakeLine.inventory_item_id)
        .filter(StocktakeLine.stocktake_id == stocktake.id)
        .order_by(InventoryItem.name.asc(), InventoryItem.supplier_batch_number.asc())
        .all()
    )
    locations = _locations(session, stocktake.org_id)
    resolutions: dict = {}
    line_ids = [ln.id for ln, _ in rows]
    if line_ids:
        found = (
            session.query(StocktakeResolution)
            .filter(StocktakeResolution.line_id.in_(line_ids))
            .order_by(StocktakeResolution.created_at.asc())
            .all()
        )
        for r in found:
            resolutions.setdefault(r.line_id, []).append(
                {
                    "reason": r.reason,
                    "quantity": _s(r.quantity),
                    "occurred_on": r.occurred_on.isoformat() if r.occurred_on else None,
                    "place": locations[r.location_id].name if r.location_id in locations else None,
                    "dutiable": r.dutiable,
                    "raise_with_customs": r.raise_with_customs,
                    "note": r.note,
                }
            )
    variances = [
        (_d(ln.counted_quantity) - _d(ln.expected_quantity)) if ln.counted_quantity is not None else Decimal("0")
        for ln, _ in rows
    ]
    measures = _measure(
        session,
        stocktake.org_id,
        [(item, v) for (_, item), v in zip(rows, variances, strict=True)],
        stocktake.counted_on,
    )
    out_lines = []
    for (line, item), variance, m in zip(rows, variances, measures, strict=True):
        place, inside = _place(item, locations)
        counted = line.counted_quantity is not None
        out_lines.append(
            {
                "id": str(line.id),
                "item_id": str(item.id),
                "name": item.name,
                "batch": _batch(item),
                "place": place,
                "place_id": str(item.location_id) if item.location_id else None,
                "inside_licensed_area": inside,
                "unit": line.unit,
                "whole_units": is_count_unit(line.unit),
                "bulk": normalize_unit(line.unit) in ("l", "ml"),
                "expected": _s(line.expected_quantity),
                "counted": _s(line.counted_quantity) if counted else None,
                "variance": _s(variance) if counted else None,
                "variance_measure": m["measure"] if counted and variance else None,
                "variance_cost": m["cost"] if counted and variance else None,
                "status": line.status,
                "investigate_until": line.investigate_until.isoformat() if line.investigate_until else None,
                "resolutions": resolutions.get(line.id, []),
            }
        )
    out_lines.sort(
        key=lambda ln: (ln["place_id"] is not None, ln["place"].lower(), ln["name"].lower(), ln["batch"] or "")
    )
    return {
        "id": str(stocktake.id),
        "counted_on": stocktake.counted_on.isoformat(),
        "kind": stocktake.kind,
        "status": stocktake.status,
        "completed_at": stocktake.completed_at.isoformat() if stocktake.completed_at else None,
        "labels": stock_measures.labels(session, stocktake.org_id),
        "lines": out_lines,
        "places": [
            {"id": str(loc.id), "name": loc.name, "inside_licensed_area": bool(loc.inside_licensed_area)}
            for loc in sorted(locations.values(), key=lambda x: x.name.lower())
            if loc.name not in (REMOVED_PLACE, LOSS_PLACE)
        ],
        "summary": {
            "lines": len(out_lines),
            "not_counted": sum(1 for ln in out_lines if ln["counted"] is None),
            "to_resolve": sum(1 for ln in out_lines if ln["status"] == "open" and ln["counted"] is not None),
            "investigating": sum(1 for ln in out_lines if ln["status"] == "investigating"),
            "raise_with_customs": sum(1 for ln in out_lines for r in ln["resolutions"] if r["raise_with_customs"]),
        },
    }


def last_completed(session, org_id: UUID, before: date | None = None) -> Stocktake | None:
    query = session.query(Stocktake).filter(Stocktake.org_id == org_id, Stocktake.status == "done")
    if before is not None:
        query = query.filter(Stocktake.counted_on < before)
    return query.order_by(Stocktake.counted_on.desc(), Stocktake.completed_at.desc()).first()


def reconcile(session, org_id: UUID, stocktake: Stocktake) -> dict:
    """Per product since the last completed stocktake: opening + in − removed − losses = expected.

    Opening is what the previous stocktake counted. Removals and the declared figure come
    from the installed compliance module (for excise: the same removals the entries use,
    and the LAL lodged for those periods), so a count ties back to what was declared.
    "Produced and other in" is the balancing figure when there's an opening count.

    When a module tracks regulated flows, the equation covers the controlled area only:
    stock at an outside place has already left (it was a removal when it moved there).
    "Explained" is the part of the difference already resolved with a reason.
    """
    previous = last_completed(session, org_id, before=stocktake.counted_on)
    locations = _locations(session, org_id)
    start = previous.counted_on + timedelta(days=1) if previous else None
    end = stocktake.counted_on + timedelta(days=1)
    table: dict = {}

    def row(item: InventoryItem, unit: str) -> dict:
        name = stock_measures.product_key(session, org_id, item.name)
        return table.setdefault(
            name,
            {
                "unit": unit,
                "opening": None,
                "removed": Decimal("0"),
                "returned": Decimal("0"),
                "losses": Decimal("0"),
                "expected": Decimal("0"),
                "counted": Decimal("0"),
                "explained": Decimal("0"),
                "uncounted": 0,
            },
        )

    flows = stock_measures.flows(session, org_id, start or date.min, end)

    def counts(item: InventoryItem) -> bool:
        return flows is None or _place(item, locations)[1]

    if previous is not None:
        prior = (
            session.query(StocktakeLine, InventoryItem)
            .join(InventoryItem, InventoryItem.id == StocktakeLine.inventory_item_id)
            .filter(StocktakeLine.stocktake_id == previous.id)
            .order_by(StocktakeLine.id)
        )
        for line, item in prior:
            if not counts(item):
                continue
            r = row(item, line.unit)
            r["opening"] = (r["opening"] or Decimal("0")) + _d(line.counted_quantity or 0)

    for flow in flows or []:
        r = row(flow.item, flow.item.unit)
        r["returned" if flow.direction == "in" else "removed"] += flow.quantity

    wastage = (
        session.query(InventoryWastage, InventoryItem)
        .join(InventoryItem, InventoryItem.id == InventoryWastage.inventory_item_id)
        .filter(
            InventoryWastage.org_id == org_id,
            InventoryItem.inventory_type.in_(_COUNTED_TYPES),
            func.date(InventoryWastage.recorded_at) < end,
        )
    )
    if start is not None:
        wastage = wastage.filter(func.date(InventoryWastage.recorded_at) >= start)
    for waste, item in wastage.all():
        if not counts(item):
            continue
        try:
            row(item, item.unit)["losses"] += _d(waste.quantity_wasted)
        except InvalidOperation:
            continue

    current = (
        session.query(StocktakeLine, InventoryItem)
        .join(InventoryItem, InventoryItem.id == StocktakeLine.inventory_item_id)
        .filter(StocktakeLine.stocktake_id == stocktake.id)
        .order_by(StocktakeLine.id)
    )
    resolved: dict = {}
    done = (
        session.query(StocktakeResolution)
        .join(StocktakeLine, StocktakeLine.id == StocktakeResolution.line_id)
        .filter(StocktakeLine.stocktake_id == stocktake.id, StocktakeResolution.reason != "investigating")
        .order_by(StocktakeResolution.id)
        .all()
    )
    for res in done:
        signed = _d(res.quantity) * (-1 if res.reason in SHORTFALL_REASONS else 1)
        resolved[res.line_id] = resolved.get(res.line_id, Decimal("0")) + signed
    for line, item in current:
        if not counts(item):
            continue
        r = row(item, line.unit)
        r["explained"] += resolved.get(line.id, Decimal("0"))
        r["expected"] += _d(line.expected_quantity)
        if line.counted_quantity is None:
            r["uncounted"] += 1
        else:
            r["counted"] += _d(line.counted_quantity)

    declared = stock_measures.declared(session, org_id, start, end)
    out = []
    for name in sorted(table, key=str.lower):
        r = table[name]
        produced = None
        if r["opening"] is not None and flows is not None:
            produced = r["expected"] - r["opening"] + r["removed"] - r["returned"] + r["losses"]
        out.append(
            {
                "product": name,
                "unit": r["unit"],
                "opening": _s(r["opening"]) if r["opening"] is not None else None,
                "produced_and_in": _s(produced) if produced is not None else None,
                "removed": _s(r["removed"] - r["returned"]),
                "losses": _s(r["losses"]),
                "expected": _s(r["expected"]),
                "counted": _s(r["counted"]) if not r["uncounted"] else None,
                "variance": _s(r["counted"] - r["expected"]) if not r["uncounted"] else None,
                "explained": _s(r["explained"]),
                "declared": declared.get(name),
            }
        )
    return {
        "since": previous.counted_on.isoformat() if previous else None,
        "to": stocktake.counted_on.isoformat(),
        "tracks_flows": flows is not None,
        "labels": stock_measures.labels(session, org_id),
        "products": out,
    }


# --- schedule and alerts ---------------------------------------------------------------------


def _add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(day.day, days[month - 1]))


def schedule(session, org_id: UUID, settings: dict | None, today: date) -> dict:
    """When the next stocktake is due. Customs' minimum is once a year."""
    frequency = (settings or {}).get("stocktake_frequency")
    frequency = frequency if frequency in FREQUENCY_MONTHS else "annual"
    last = last_completed(session, org_id)
    anchor = last.counted_on if last else None
    if anchor is None:
        org = session.get(Organisation, org_id)
        anchor = org.go_live_date if org is not None else None  # the go-live count (plan 1.3)
    due = _add_months(anchor, FREQUENCY_MONTHS[frequency]) if anchor else None
    return {
        "frequency": frequency,
        "last_completed_on": last.counted_on.isoformat() if last else None,
        "next_due": due.isoformat() if due else None,
        "overdue": bool(due and today > due),
    }


def open_variances(session, org_id: UUID, today: date) -> list[dict]:
    """Lines still open or under investigation, for the alert list."""
    rows = (
        session.query(StocktakeLine, Stocktake, InventoryItem)
        .join(Stocktake, Stocktake.id == StocktakeLine.stocktake_id)
        .join(InventoryItem, InventoryItem.id == StocktakeLine.inventory_item_id)
        .filter(
            StocktakeLine.org_id == org_id,
            StocktakeLine.status.in_(("open", "investigating")),
            StocktakeLine.counted_quantity.isnot(None),
        )
        .order_by(Stocktake.counted_on.asc(), InventoryItem.name.asc())
        .all()
    )
    pairs = [(item, _d(line.counted_quantity) - _d(line.expected_quantity)) for line, _st, item in rows]
    measures = _measure(session, org_id, pairs, today)
    out = []
    for (line, st, item), (_i, variance), m in zip(rows, pairs, measures, strict=True):
        if variance == 0:
            continue
        out.append(
            {
                "stocktake_id": str(st.id),
                "line_id": str(line.id),
                "counted_on": st.counted_on.isoformat(),
                "product": item.name,
                "batch": _batch(item),
                "variance": _s(variance),
                "unit": line.unit,
                "measure": m["measure"],
                "cost": m["cost"],
                "status": line.status,
                "investigate_until": line.investigate_until.isoformat() if line.investigate_until else None,
                "overdue": bool(line.investigate_until and today > line.investigate_until),
            }
        )
    return out


# --- routes ------------------------------------------------------------------------------------


def _org() -> UUID:
    return UUID(str(g.org_id))


def _settings() -> dict:
    from app.features.compliant.service import ComplianceService

    profile = ComplianceService(db_session).get_profile(_org())
    return (profile.settings or {}) if profile is not None else {}


def _load(stocktake_id: str) -> Stocktake | None:
    try:
        sid = UUID(stocktake_id)
    except ValueError:
        return None
    return db_session.query(Stocktake).filter(Stocktake.id == sid, Stocktake.org_id == _org()).one_or_none()


def _line(st: Stocktake | None, line_id: str) -> StocktakeLine | None:
    if st is None:
        return None
    try:
        lid = UUID(line_id)
    except ValueError:
        return None
    return (
        db_session.query(StocktakeLine)
        .filter(StocktakeLine.id == lid, StocktakeLine.stocktake_id == st.id)
        .one_or_none()
    )


@stocktake_bp.route("/core/stocktake", methods=["GET"])
@requires_auth
def stocktake_page():
    return render_template("stocktake/stocktake.html", active_page="core")


@stocktake_bp.route("/api/core/stock-position", methods=["GET"])
@requires_auth
def get_stock_position():
    position = stock_position(db_session, _org(), date.today())
    if request.args.get("format") == "csv":
        return Response(
            position_csv(position),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="stock-position-{position["as_at"]}.csv"'},
        )
    return jsonify(position), 200


@stocktake_bp.route("/api/core/stocktakes", methods=["GET"])
@requires_auth
def list_stocktakes():
    today = date.today()
    rows = (
        db_session.query(Stocktake)
        .filter(Stocktake.org_id == _org())
        .order_by(Stocktake.counted_on.desc(), Stocktake.created_at.desc())
        .limit(20)
        .all()
    )
    return jsonify(
        {
            "stocktakes": [
                {"id": str(s.id), "counted_on": s.counted_on.isoformat(), "kind": s.kind, "status": s.status}
                for s in rows
            ],
            "labels": stock_measures.labels(db_session, _org()),
            "schedule": schedule(db_session, _org(), _settings(), today),
            "open_variances": open_variances(db_session, _org(), today),
        }
    ), 200


@stocktake_bp.route("/api/core/stocktakes", methods=["POST"])
@requires_auth
def create_stocktake():
    data = request.get_json(silent=True) or {}
    try:
        counted_on = date.fromisoformat(str(data.get("counted_on") or date.today().isoformat()))
        if counted_on > date.today():
            raise ValueError("A stocktake can't be dated in the future")
        location = UUID(str(data["location_id"])) if data.get("location_id") else None
        st = start_stocktake(
            db_session, _org(), counted_on, data.get("kind") or "scheduled", location, g.current_user.id
        )
        db_session.commit()
    except ValueError as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 400
    log_action("start_stocktake", "stocktake", st.id, {"kind": st.kind, "counted_on": st.counted_on.isoformat()})
    return jsonify(serialise(db_session, st)), 201


@stocktake_bp.route("/api/core/stocktakes/<stocktake_id>", methods=["GET"])
@requires_auth
def get_stocktake(stocktake_id: str):
    st = _load(stocktake_id)
    if st is None:
        return jsonify({"error": "Stocktake not found"}), 404
    return jsonify(serialise(db_session, st)), 200


@stocktake_bp.route("/api/core/stocktakes/<stocktake_id>/reconciliation", methods=["GET"])
@requires_auth
def get_stocktake_reconciliation(stocktake_id: str):
    st = _load(stocktake_id)
    if st is None:
        return jsonify({"error": "Stocktake not found"}), 404
    return jsonify(reconcile(db_session, _org(), st)), 200


@stocktake_bp.route("/api/core/stocktakes/<stocktake_id>/lines/<line_id>", methods=["PUT"])
@requires_auth
def count_stocktake_line(stocktake_id: str, line_id: str):
    st = _load(stocktake_id)
    line = _line(st, line_id)
    if line is None:
        return jsonify({"error": "Line not found"}), 404
    if st.status == "done" and line.status != "investigating":
        return jsonify({"error": "This stocktake is finished"}), 409
    try:
        record_count(db_session, line, (request.get_json(silent=True) or {}).get("counted"), _settings())
        db_session.commit()
    except ValueError as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 400
    return jsonify(serialise(db_session, st)), 200


@stocktake_bp.route("/api/core/stocktakes/<stocktake_id>/lines/<line_id>/resolve", methods=["POST"])
@requires_auth
def resolve_stocktake_line(stocktake_id: str, line_id: str):
    st = _load(stocktake_id)
    line = _line(st, line_id)
    if line is None:
        return jsonify({"error": "Line not found"}), 404
    try:
        records = resolve_line(
            db_session,
            _org(),
            line,
            (request.get_json(silent=True) or {}).get("reasons") or [],
            g.current_user.id,
            date.today(),
        )
        db_session.commit()
    except ValueError as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 400
    log_action(
        "resolve_stocktake_line",
        "stocktake",
        st.id,
        {"line_id": str(line.id), "reasons": [{"reason": r.reason, "quantity": _s(r.quantity)} for r in records]},
    )
    return jsonify(serialise(db_session, st)), 200


@stocktake_bp.route("/api/core/stocktakes/<stocktake_id>/complete", methods=["POST"])
@requires_auth
def complete_stocktake(stocktake_id: str):
    st = _load(stocktake_id)
    if st is None:
        return jsonify({"error": "Stocktake not found"}), 404
    if st.status == "done":
        return jsonify({"error": "This stocktake is already finished"}), 409
    body = serialise(db_session, st)
    if body["summary"]["not_counted"] or body["summary"]["to_resolve"]:
        return jsonify({"error": "Count every line and resolve or investigate every difference first"}), 409
    st.status = "done"
    st.completed_at = datetime.now(UTC)
    db_session.commit()
    log_action("complete_stocktake", "stocktake", st.id, body["summary"])
    return jsonify(serialise(db_session, st)), 200


@stocktake_bp.route("/api/core/stocktake-settings", methods=["PUT"])
@requires_auth
def update_stocktake_settings():
    """How often to count (Customs' minimum is annual) and the bulk measurement tolerance."""
    from app.features.compliant.service import ComplianceService

    data = request.get_json(silent=True) or {}
    frequency = data.get("frequency", "annual")
    if frequency not in FREQUENCY_MONTHS:
        return jsonify({"error": "frequency must be monthly, quarterly, six_monthly or annual"}), 400
    try:
        tolerance = Decimal(str(data.get("bulk_tolerance_percent", DEFAULT_BULK_TOLERANCE_PERCENT)))
    except InvalidOperation:
        return jsonify({"error": "bulk_tolerance_percent must be a number"}), 400
    if not tolerance.is_finite() or tolerance < 0 or tolerance > 5:
        return jsonify({"error": "bulk_tolerance_percent must be between 0 and 5"}), 400
    service = ComplianceService(db_session)
    profile = service.get_profile(_org())
    if profile is None:
        return jsonify({"error": "Configure Compliant before setting a stocktake schedule"}), 409
    settings = {
        **(profile.settings or {}),
        "stocktake_frequency": frequency,
        "stocktake_bulk_tolerance_percent": _s(tolerance),
    }
    service.upsert_profile(_org(), {"settings": settings})
    log_action("update", "compliance_profile", profile.id, {"stocktake_frequency": frequency})
    return jsonify({"schedule": schedule(db_session, _org(), settings, date.today())}), 200
