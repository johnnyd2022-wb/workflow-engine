"""Go live with a stocktake instead of reconstructing history (plan item 1.3).

A new producer records their next batches as normal. What they already hold is entered
once, as **opening stock** counted on a go-live date:

- finished goods, one row per workflow's final output (whole units for bottles), with
  the org's own batch ID and, if known, bottling date and ABV;
- spirit (or beer, wine...) still in tank or barrel, as opening work in progress that a
  later step can take as an input, so nobody rebuilds past production;
- raw materials through the existing add-stock screens.

Opening stock is written with its own reason (``OPENING_BALANCE``), carries
``extra_data.opening_stock`` and the as-of date, and is not a traceability gap. Xero sales
dated before the go-live date are left out of batch matching (see
``SalesTraceabilityService``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import Blueprint, g, jsonify, render_template, request

from app.core.db import db_session
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.step import Step
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason
from app.core.security.permissions import requires_auth
from app.core.utils.log_action import log_action
from app.core.utils.unit_conversion import is_count_unit
from app.observability import get_logger

logger = get_logger(__name__)

_OPENING_TYPES = {
    "final_product": InventoryType.FINAL_PRODUCT.value,
    "work_in_progress": InventoryType.WORK_IN_PROGRESS.value,
}
_MAX_ITEMS = 200


def _org_id() -> UUID:
    return UUID(g.org_id)


def workflow_outputs(session, org_id: UUID) -> dict:
    """Final outputs (one per workflow's last step) and intermediate outputs, by name."""
    processes = session.query(Process).filter(Process.org_id == org_id).order_by(Process.name.asc()).all()
    steps = session.query(Step).filter(Step.org_id == org_id).yield_per(200)
    by_process: dict = {}
    for step in steps:
        by_process.setdefault(step.process_id, []).append(step)

    finals, intermediates, seen_final, seen_mid = [], [], set(), set()
    for process in processes:
        ordered = sorted(
            by_process.get(process.id, []),
            key=lambda s: (s.position if s.position is not None else 0, s.step_number or 0),
        )
        for index, step in enumerate(ordered):
            last = index == len(ordered) - 1
            for output in step.outputs or []:
                if not isinstance(output, dict) or not (output.get("name") or "").strip():
                    continue
                name = output["name"].strip()
                entry = {"name": name, "unit": (output.get("unit") or "units").strip(), "workflow": process.name}
                entry["counted"] = is_count_unit(entry["unit"])
                if last and name.casefold() not in seen_final:
                    seen_final.add(name.casefold())
                    finals.append(entry)
                elif not last and name.casefold() not in seen_mid:
                    seen_mid.add(name.casefold())
                    intermediates.append(entry)
    return {"final_outputs": finals, "intermediate_outputs": intermediates, "workflow_count": len(processes)}


def _opening_items(session, org_id: UUID) -> list[dict]:
    rows = (
        session.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.extra_data.contains({"opening_stock": True}))
        .order_by(InventoryItem.name.asc(), InventoryItem.created_at.asc())
        .all()
    )
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "quantity": f"{Decimal(str(r.quantity)).normalize():f}",
            "unit": r.unit,
            "inventory_type": r.inventory_type,
            "batch_id": r.supplier_batch_number,
            "abv_percent": (r.extra_data or {}).get("abv_percent"),
            "bottled_on": (r.extra_data or {}).get("bottled_on"),
        }
        for r in rows
    ]


def go_live_status(session, org_id: UUID) -> dict:
    org = session.get(Organisation, org_id)
    outputs = workflow_outputs(session, org_id)
    raw_count = (
        session.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.inventory_type == InventoryType.RAW_MATERIAL.value)
        .count()
    )
    return {
        "go_live_date": org.go_live_date.isoformat() if org and org.go_live_date else None,
        **outputs,
        "raw_material_count": raw_count,
        "opening_items": _opening_items(session, org_id),
    }


def _parse_date(value, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError(f"{field} must be a date like 2026-10-01") from None


def _parse_opening_row(row: dict, index: int, known_finals: dict) -> dict:
    where = f"Row {index + 1}"
    if not isinstance(row, dict):
        raise ValueError(f"{where}: each row must be an object")
    name = (row.get("name") or "").strip()
    if not name:
        raise ValueError(f"{where}: name is required")
    kind = row.get("inventory_type") or "final_product"
    if kind not in _OPENING_TYPES:
        raise ValueError(f"{where}: inventory_type must be final_product or work_in_progress")
    unit = (row.get("unit") or (known_finals.get(name.casefold(), {}).get("unit")) or "").strip()
    if not unit:
        raise ValueError(f"{where}: unit is required")
    try:
        quantity = Decimal(str(row.get("quantity")))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{where}: quantity must be a number") from None
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError(f"{where}: quantity must be more than 0")
    abv = row.get("abv_percent")
    if abv not in (None, ""):
        try:
            abv = Decimal(str(abv))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(f"{where}: ABV must be a number") from None
        if not (Decimal("0") <= abv <= Decimal("100")):
            raise ValueError(f"{where}: ABV must be between 0 and 100")
    else:
        abv = None
    bottled_on = _parse_date(row.get("bottled_on"), f"{where}: bottled date")
    batch_id = (row.get("batch_id") or "").strip()[:255] or None
    return {
        "name": name,
        "unit": unit,
        "quantity": quantity,
        "inventory_type": _OPENING_TYPES[kind],
        "batch_id": batch_id,
        "abv_percent": f"{abv.normalize():f}" if abv is not None else None,
        "bottled_on": bottled_on.isoformat() if bottled_on else None,
    }


def register_routes(bp):
    @bp.route("/core/go-live", methods=["GET"])
    @requires_auth
    def go_live_page():
        return render_template("go_live/go_live.html", active_page="core")

    @bp.route("/api/core/go-live", methods=["GET"])
    @requires_auth
    def get_go_live():
        return jsonify(go_live_status(db_session, _org_id())), 200

    @bp.route("/api/core/go-live", methods=["PUT"])
    @requires_auth
    def set_go_live_date():
        data = request.get_json(silent=True) or {}
        try:
            go_live = _parse_date(data.get("go_live_date"), "go_live_date")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if go_live is None:
            return jsonify({"error": "go_live_date is required"}), 400
        org = db_session.get(Organisation, _org_id())
        before = org.go_live_date.isoformat() if org.go_live_date else None
        org.go_live_date = go_live
        db_session.commit()
        log_action(
            "set_go_live_date",
            "organisation",
            org.id,
            {"before": before, "after": go_live.isoformat()},
            org.id,
            g.current_user.id,
        )
        return jsonify(go_live_status(db_session, org.id)), 200

    @bp.route("/api/core/opening-stock", methods=["POST"])
    @requires_auth
    def create_opening_stock():
        """Record what's on hand at go-live. All rows or none."""
        org_id = _org_id()
        org = db_session.get(Organisation, org_id)
        if org is None or org.go_live_date is None:
            return jsonify({"error": "Set your go-live date first."}), 409
        data = request.get_json(silent=True) or {}
        rows = data.get("items")
        if not isinstance(rows, list) or not rows:
            return jsonify({"error": "items must be a non-empty list"}), 400
        if len(rows) > _MAX_ITEMS:
            return jsonify({"error": f"At most {_MAX_ITEMS} rows at a time"}), 400

        known = {o["name"].casefold(): o for o in workflow_outputs(db_session, org_id)["final_outputs"]}
        repo = InventoryRepository(db_session)
        created = []
        try:
            parsed = [_parse_opening_row(row, i, known) for i, row in enumerate(rows)]
            for row in parsed:
                extra = {"opening_stock": True, "opening_as_of": org.go_live_date.isoformat()}
                if row["abv_percent"] is not None:
                    extra["abv_percent"] = row["abv_percent"]
                if row["bottled_on"]:
                    extra["bottled_on"] = row["bottled_on"]
                item = repo.create_inventory_item(
                    org_id=org_id,
                    name=row["name"],
                    quantity=row["quantity"],
                    unit=row["unit"],
                    inventory_type=row["inventory_type"],
                    supplier_batch_number=row["batch_id"],
                    purchase_date=date.fromisoformat(row["bottled_on"]) if row["bottled_on"] else org.go_live_date,
                    extra_data=extra,
                    commit=False,
                    write_reason=InventoryQuantityWriteReason.OPENING_BALANCE,
                )
                created.append(item)
            db_session.commit()
        except ValueError as exc:
            db_session.rollback()
            return jsonify({"error": str(exc)}), 400
        except Exception:
            db_session.rollback()
            logger.exception("opening_stock_failed", org_id=str(org_id))
            return jsonify({"error": "Failed to record opening stock"}), 500

        log_action("opening_stock", "organisation", org_id, {"rows": len(created)}, org_id, g.current_user.id)
        return jsonify({"created": len(created), **go_live_status(db_session, org_id)}), 201


# Its own blueprint so backend.py doesn't grow.
go_live_bp = Blueprint("go_live", __name__, template_folder="../frontend")
register_routes(go_live_bp)
