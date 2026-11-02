"""A planned batch is short of a material: say what to order, from whom and by when (GL-P07 B2b).

Reads the latest materials check on the Production board. Each shortage on a batch it still
describes becomes a notification through the generic `system_alerts` contract. It's due on the
order-by date from the supplier's lead time, or on the batch's start when there's no lead time.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.features.compliance_checks.routes.corechecks import CheckResult

CHECK_ID = "planned_material_shortages"


def _day(value):
    """3 Nov, not 2026-11-03."""
    from datetime import date

    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError):
        return value or "soon"
    return f"{day.day} {day.strftime('%b')}"


def _amount(value):
    text = format(float(value), "f").rstrip("0").rstrip(".") if value is not None else ""
    return text or "0"


def run_planned_material_shortages_check(org_id: UUID, session: Session) -> CheckResult:
    from app.features.planning.material_adapter import latest

    assessment = latest(session, org_id)
    alerts = []
    for batch in (assessment or {}).get("batches", []):
        if batch.get("stale"):
            continue
        for index, short in enumerate(batch.get("shortages") or []):
            material = short.get("material")
            if not material:
                continue  # a lot the owner chose; the board explains it
            supplier = short.get("supplier")
            if short.get("order_by"):
                when = f"Order from {supplier} by {_day(short['order_by'])} ({short['lead_time_days']}-day lead time)"
            elif supplier:
                when = f"Usually from {supplier}; set their lead time to get an order-by date"
            else:
                when = "No supplier on record for it"
            alerts.append(
                {
                    "id": f"{batch['batch_id']}:{index}",
                    "area": "Production",
                    "title": f"Order {_amount(short['quantity'])} {short['unit']} of {material}",
                    "description": f"{when}. A planned batch is short of it.",
                    "due_date": short.get("order_by"),
                    "href": "/core/planner/board",
                    "action_label": "Open the board",
                }
            )
    return CheckResult(
        check_id=CHECK_ID,
        # Only an order that should already have gone out changes system health.
        flagged=any(
            short.get("order_now")
            for batch in (assessment or {}).get("batches", [])
            for short in batch.get("shortages") or []
        ),
        message=f"{len(alerts)} planned material shortage(s)." if alerts else None,
        data={"system_alerts": alerts, "system_finding": {"area": "Production"}},
    )
