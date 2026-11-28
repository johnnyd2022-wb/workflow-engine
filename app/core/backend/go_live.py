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
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from flask import Blueprint, g, jsonify, render_template
from pydantic import Field, StringConstraints

from app.core.db import db_session
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.step import Step
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason
from app.core.security.permissions import requires_auth
from app.core.utils.log_action import log_action
from app.core.utils.unit_conversion import is_count_unit, whole_count_error
from app.observability import get_logger
from app.utils.request_validation import CleanName, CleanText, InvalidInputError, JsonInput, read_json

logger = get_logger(__name__)

_OPENING_TYPES = {
    "final_product": InventoryType.FINAL_PRODUCT.value,
    "work_in_progress": InventoryType.WORK_IN_PROGRESS.value,
}
_MAX_ITEMS = 200


class GoLiveDateInput(JsonInput):
    go_live_date: date


class OpeningStockRow(JsonInput):
    name: Annotated[CleanName, StringConstraints(max_length=255)]
    inventory_type: Literal["final_product", "work_in_progress"] = "final_product"
    unit: Annotated[CleanText, StringConstraints(max_length=50)] | None = None
    quantity: Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=4)]
    abv_percent: Annotated[Decimal, Field(ge=0, le=100, decimal_places=4)] | Literal[""] | None = None
    bottled_on: date | Literal[""] | None = None
    batch_id: Annotated[CleanText, StringConstraints(max_length=255)] | None = None


class OpeningStockInput(JsonInput):
    items: Annotated[list[OpeningStockRow], Field(min_length=1, max_length=_MAX_ITEMS)]
    site_id: UUID | None = None


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


def _opening_row_values(row: OpeningStockRow, index: int, known_finals: dict) -> dict:
    unit = row.unit or known_finals.get(row.name.casefold(), {}).get("unit")
    if not unit:
        raise InvalidInputError({f"items.{index}.unit": f"Row {index + 1}: unit is required."})
    if whole_count_error(row.quantity, unit):
        raise InvalidInputError({f"items.{index}.quantity": f"Row {index + 1}: Enter a quantity in whole numbers."})
    return {
        "name": row.name,
        "unit": unit,
        "quantity": row.quantity,
        "inventory_type": _OPENING_TYPES[row.inventory_type],
        "batch_id": row.batch_id or None,
        "abv_percent": f"{row.abv_percent.normalize():f}" if isinstance(row.abv_percent, Decimal) else None,
        "bottled_on": row.bottled_on.isoformat() if row.bottled_on else None,
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
        try:
            go_live = read_json(GoLiveDateInput).go_live_date
        except InvalidInputError as exc:
            return exc.response()
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
        try:
            rows = read_json(OpeningStockInput).items
            known = {o["name"].casefold(): o for o in workflow_outputs(db_session, org_id)["final_outputs"]}
            parsed = [_opening_row_values(row, i, known) for i, row in enumerate(rows)]
        except InvalidInputError as exc:
            return exc.response()
        repo = InventoryRepository(db_session)
        created = []
        try:
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
                    site_id=getattr(g, "validated_site_id", None),
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
