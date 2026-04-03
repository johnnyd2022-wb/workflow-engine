"""
Aggregate core check results into a single system_status payload for the core2 status bar.

Reuses CheckResult data from CoreChecksRunner.run_all_checks() — no duplicate business rules.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.checks.output_expiry_check import SEVERITY_EXPIRED as OUTPUT_EXPIRY_SEVERITY_EXPIRED
from app.core.backend.checks.output_ready_date_check import CHECK_ID as OUTPUT_READY_DATE_CHECK_ID
from app.core.backend.corechecks import CheckResult
from app.core.db.models.execution import Execution
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.process import Process


def _safe_qty_positive(raw: Any) -> bool:
    try:
        if raw is None:
            return False
        return Decimal(str(raw)) > 0
    except Exception:
        return False


def compute_onboarding_complete(org_id: UUID, session: Session) -> dict[str, Any]:
    """Match core2.html journey: inventory row exists, process exists, execution exists."""
    has_inventory = (
        session.query(InventoryItem.id).filter(InventoryItem.org_id == org_id).limit(1).first() is not None
    )
    has_process = session.query(Process.id).filter(Process.org_id == org_id).limit(1).first() is not None
    has_execution = session.query(Execution.id).filter(Execution.org_id == org_id).limit(1).first() is not None

    milestones = [
        {
            "key": "inventory",
            "complete": has_inventory,
            "label": "Inventory populated" if has_inventory else "Populate inventory",
        },
        {
            "key": "process",
            "complete": has_process,
            "label": "Product workflow created" if has_process else "Create product workflow",
        },
        {
            "key": "execution",
            "complete": has_execution,
            "label": "Executions recorded" if has_execution else "Record product workflow",
        },
        {
            "key": "traceability",
            "complete": has_execution,
            "label": "Traceability unlocked",
        },
    ]
    filled = sum(1 for m in milestones if m["complete"])
    return {
        "complete": has_inventory and has_process and has_execution,
        "completion": int(round(100.0 * filled / len(milestones))) if milestones else 0,
        "steps": milestones,
    }


def _signals_from_results(results: list[CheckResult]) -> list[dict[str, Any]]:
    """Normalize check results into UI signals.

    Categories (expiry/validity, process timing, traceability) are labels — not severity.

    ``in_active_use`` means the finding reflects impact on active production (constraint
    violated in a way that touches live production / downstream product), per status-bar
    model: severity is only meaningful at the event level, not per category name.
    """
    by_id = {r.check_id: r for r in results}
    signals: list[dict[str, Any]] = []

    untracked_r = by_id.get("untracked_items")
    if untracked_r and untracked_r.data:
        items = untracked_r.data.get("untracked_items") or []
        n = len(items)
        any_qty = any(_safe_qty_positive((it or {}).get("quantity")) for it in items if isinstance(it, dict))
        if n > 0:
            msg = f"{n} untracked item{'s' if n != 1 else ''}"
            if any_qty:
                msg += " in stock"
            signals.append(
                {
                    "type": "UNTRACKED_ITEMS",
                    "category": "traceability",
                    "breach_type": "TRACEABILITY_BREACH",
                    "has_issue": True,
                    # Untracked with positive on-hand qty: material in circulation (production-impacting traceability).
                    "in_active_use": any_qty,
                    "count": n,
                    "message": msg,
                }
            )

    expired_r = by_id.get("expired_materials")
    if expired_r and expired_r.data:
        raw_list = expired_r.data.get("expired_raw_materials") or []
        impacted = expired_r.data.get("impacted_items") or []
        raw_n = len(raw_list)
        imp_n = len(impacted)
        if raw_n > 0 or imp_n > 0:
            parts = []
            if raw_n:
                parts.append(f"{raw_n} expired raw material{'s' if raw_n != 1 else ''}")
            if imp_n:
                parts.append(f"{imp_n} impacted product{'s' if imp_n != 1 else ''} from expired inputs")
            signals.append(
                {
                    "type": "EXPIRED_RAW_MATERIALS",
                    "category": "inventory_validity",
                    "breach_type": "QUALITY_BREACH",
                    "has_issue": True,
                    # Impacted downstream products => expired input entered the production graph.
                    "in_active_use": imp_n > 0,
                    "count": raw_n,
                    "impacted_count": imp_n,
                    "message": "; ".join(parts) if parts else "Expired raw materials",
                }
            )

    oe_r = by_id.get("output_expiry")
    if oe_r and oe_r.data:
        oe_items = oe_r.data.get("output_expiry_items") or []
        if oe_items:
            expired_n = sum(
                1 for x in oe_items if isinstance(x, dict) and x.get("severity") == OUTPUT_EXPIRY_SEVERITY_EXPIRED
            )
            near_n = len(oe_items) - expired_n
            parts = []
            if expired_n:
                parts.append(f"{expired_n} expired output{'s' if expired_n != 1 else ''}")
            if near_n:
                parts.append(f"{near_n} near-expiry output{'s' if near_n != 1 else ''}")
            signals.append(
                {
                    "type": "EXPIRED_OUTPUTS",
                    "category": "inventory_validity",
                    "breach_type": "QUALITY_BREACH",
                    "has_issue": True,
                    # Shelf / validity warnings only unless chain proves consumption (not duplicated here).
                    "in_active_use": False,
                    "count": len(oe_items),
                    "message": "; ".join(parts) if parts else "Custom output expiry issues",
                }
            )

    ord_r = by_id.get(OUTPUT_READY_DATE_CHECK_ID)
    if ord_r and ord_r.data:
        rd_items = ord_r.data.get("output_ready_date_items") or []
        if rd_items:
            n = len(rd_items)
            signals.append(
                {
                    "type": "NOT_READY_OUTPUTS",
                    "category": "availability",
                    "breach_type": "QUALITY_BREACH",
                    "has_issue": True,
                    # Outputs not yet ready: readiness rule surface; "used before ready" would be a consumption event.
                    "in_active_use": False,
                    "count": n,
                    "message": f"{n} output{'s' if n != 1 else ''} not yet ready for use",
                }
            )

    return signals


def derive_health_state(signals: list[dict[str, Any]]) -> str:
    """Severity is system-wide only: critical if any production-impacted violation; else degraded if any issue."""
    if not any(s.get("has_issue") for s in signals):
        return "healthy"
    if any(s.get("has_issue") and s.get("in_active_use") for s in signals):
        return "critical"
    return "degraded"


def build_system_status_payload(org_id: UUID, session: Session, results: list[CheckResult]) -> dict[str, Any]:
    """Full system_status object for /api/core/system-findings and similar."""
    onboarding = compute_onboarding_complete(org_id, session)

    if not onboarding["complete"]:
        return {
            "mode": "activation",
            "completion": onboarding["completion"],
            "steps": onboarding["steps"],
        }

    signals = _signals_from_results(results)
    state = derive_health_state(signals)
    return {
        "mode": "health",
        "state": state,
        "signals": signals,
    }
