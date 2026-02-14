"""
Untracked items check: inventory items with extra_data.untracked = True (recorded in-flow
without full upstream traceability). Surfaces in banners, sourcemap "Check needed", and
execution dropdowns. Reconciliation (clearing untracked) updates alerts in real time.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.corechecks import CheckResult
from app.core.db.models.inventory_item import InventoryItem

_log = logging.getLogger(__name__)

# JSONB contains: match rows where extra_data @> {"untracked": true}
_UNTRACKED_FILTER = {"untracked": True}


def run_untracked_items_check(org_id: UUID, session: Session) -> CheckResult:
    """
    Find inventory items flagged as untracked (no upstream source / reconciliation required).
    Uses same pattern as expired_materials: return list for banners and sourcemap "Check needed".
    """
    try:
        q = (
            session.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id)
            .filter(InventoryItem.extra_data.isnot(None))
            .filter(InventoryItem.extra_data.contains(_UNTRACKED_FILTER))
        )
        untracked_orm = q.all()
    except Exception as e:
        _log.warning("JSONB untracked filter not supported, falling back to in-memory filter: %s", e)
        untracked_orm = (
            session.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id)
            .filter(InventoryItem.extra_data.isnot(None))
            .all()
        )
        untracked_orm = [i for i in untracked_orm if (i.extra_data or {}).get("untracked") is True]

    untracked_items: list[dict[str, Any]] = []
    for item in untracked_orm:
        untracked_items.append(
            {
                "id": str(item.id),
                "name": item.name,
                "quantity": item.quantity,
                "unit": item.unit,
                "inventory_type": item.inventory_type,
                "supplier": item.supplier,
                "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                "supplier_batch_number": item.supplier_batch_number,
                "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                "source_execution_id": str(item.source_execution_id) if item.source_execution_id else None,
                "source_execution_step_id": str(item.source_execution_step_id)
                if item.source_execution_step_id
                else None,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "extra_data": item.extra_data if item.extra_data else {},
                "check_reason": "Untracked inventory item",
                "reconciliation_required": True,
            }
        )

    flagged = len(untracked_items) > 0
    message = None
    if flagged:
        message = f"{len(untracked_items)} untracked item(s) — reconciliation required."

    return CheckResult(
        check_id="untracked_items",
        flagged=flagged,
        message=message,
        data={
            "untracked_items": untracked_items,
            "connections": [],  # Optional: forward connections to downstream steps
        },
    )
