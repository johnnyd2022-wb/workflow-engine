"""
Expired materials check: raw materials with expiry_date < today and quantity > 0,
plus products made with them (via DAG traversal).
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.corechecks import CheckResult
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.observability import get_logger

_log = get_logger(__name__)


def run_expired_materials_check(org_id: UUID, session: Session) -> CheckResult:
    """
    Find expired raw materials (with stock) and products made with them.
    Uses DAG traversal (find_impacted_by_expired_raw) for impacted items.
    """
    from app.core.backend.dagtraversal import find_impacted_by_expired_raw

    # Impacted items are products produced by executions that consumed expired raw
    # materials while stock was present. This aligns with compliance and recall semantics.
    today = date.today()
    # Compliance/recall check — must find ALL expired raw materials in the org, not a page of
    # them; a LIMIT here would silently under-report a recall-relevant result.
    expired_raw_materials = (  # nosemgrep: sqlalchemy-all-without-limit
        session.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id)
        .filter(InventoryItem.inventory_type == InventoryType.RAW_MATERIAL.value)
        .filter(InventoryItem.expiry_date.isnot(None))
        .filter(InventoryItem.expiry_date < today)
        .all()
    )

    # Only flag items with quantity > 0. Invalid numeric quantity surfaces as ValueError.
    expired_with_stock: list[InventoryItem] = []
    for item in expired_raw_materials:
        if item.quantity is None:
            continue
        try:
            if float(item.quantity) > 0:
                expired_with_stock.append(item)
        except (TypeError, ValueError) as e:
            _log.warning("Invalid quantity for inventory item %s: %r", item.id, item.quantity, exc_info=True)
            raise ValueError(f"Invalid quantity for inventory item {item.id}: {item.quantity!r}") from e

    result_expired: list[dict[str, Any]] = []
    result_impacted: list[dict[str, Any]] = []
    seen_connection_keys: set[tuple[str, str, str]] = set()
    result_connections: list[dict[str, Any]] = []
    impacted_item_ids: set[str] = set()

    for raw_material in expired_with_stock:
        result_expired.append(
            {
                "id": str(raw_material.id),
                "name": raw_material.name,
                "quantity": raw_material.quantity,
                "unit": raw_material.unit,
                "inventory_type": raw_material.inventory_type,
                "supplier": raw_material.supplier,
                "purchase_date": raw_material.purchase_date.isoformat() if raw_material.purchase_date else None,
                "supplier_batch_number": raw_material.supplier_batch_number,
                "expiry_date": raw_material.expiry_date.isoformat() if raw_material.expiry_date else None,
                "created_at": raw_material.created_at.isoformat() if raw_material.created_at else None,
                "extra_data": raw_material.extra_data if raw_material.extra_data else {},
                "is_expired": True,
            }
        )
        data = find_impacted_by_expired_raw(org_id, session, raw_material)
        for item in data["impacted_items"]:
            item_id = item.get("id")
            if not item_id or item_id in impacted_item_ids:
                continue
            impacted_item_ids.add(item_id)
            result_impacted.append(item)
        for conn in data["connections"]:
            key = (
                str(conn.get("from_id")) if conn.get("from_id") else "",
                str(conn.get("to_id")) if conn.get("to_id") else "",
                str(conn.get("execution_id")) if conn.get("execution_id") else "",
            )
            if key not in seen_connection_keys:
                seen_connection_keys.add(key)
                result_connections.append(
                    {
                        "from_id": conn.get("from_id"),
                        "to_id": conn.get("to_id"),
                        "execution_id": conn.get("execution_id") or None,
                    }
                )

    flagged = len(result_expired) > 0
    message = None
    if flagged:
        message = f"{len(result_expired)} expired raw material(s) with stock; {len(result_impacted)} impacted item(s)."

    return CheckResult(
        check_id="expired_materials",
        flagged=flagged,
        message=message,
        data={
            "expired_raw_materials": result_expired,
            "impacted_items": result_impacted,
            "connections": result_connections,
        },
    )
