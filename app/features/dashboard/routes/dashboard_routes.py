"""Core dashboard composition routes registered on the Core blueprint."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from flask import g, jsonify, render_template, request
from sqlalchemy import func

from app.core.db import db_session
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.execution import Execution, ExecutionStatus
from app.core.db.models.inventory_item import InventoryType
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.security.permissions import has_permission, requires_auth
from app.features.activity_log.routes.activity_routes import _human_summary
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)
_APP_TZ = ZoneInfo("Pacific/Auckland")


def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=_APP_TZ)


def _local_date_expr(col):
    """Convert a timestamptz to a date in the app's local timezone."""
    return func.date(func.timezone("Pacific/Auckland", col))


@requires_auth
def dashboard():
    return render_template("dashboard/dashboard.html", active_page="dashboard")


def _dashboard_parse_due_date(raw: Any) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _dashboard_priority_rank(priority: Any) -> int:
    p = str(priority or "").strip().lower()
    if p == "high":
        return 0
    if p == "medium":
        return 1
    if p == "low":
        return 2
    return 3


def _dashboard_summarize_tasks(
    open_tasks: list[dict[str, Any]],
    today: date,
    week_start: date | None = None,
    week_end_exclusive: date | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for task in open_tasks or []:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "").strip().lower()
        if status not in {"pending", "in_progress"}:
            continue
        due = _dashboard_parse_due_date(task.get("due_date"))
        rows.append(
            {
                "id": task.get("id"),
                "title": task.get("title"),
                "due_date": due.isoformat() if due else None,
                "priority": task.get("priority"),
                "status": status,
                "contact_name": task.get("contact_name"),
                "_due_obj": due,
            }
        )

    due_today_count = sum(1 for t in rows if t["_due_obj"] == today)
    overdue_count = sum(1 for t in rows if t["_due_obj"] is not None and t["_due_obj"] < today)
    due_this_week_count = 0
    if week_start is not None and week_end_exclusive is not None:
        due_this_week_count = sum(
            1
            for t in rows
            if t["_due_obj"] is not None and week_start <= t["_due_obj"] and t["_due_obj"] < week_end_exclusive
        )

    sorted_rows = sorted(
        rows,
        key=lambda t: (
            t["_due_obj"] is None,
            t["_due_obj"] or date.max,
            _dashboard_priority_rank(t.get("priority")),
            str(t.get("title") or "").lower(),
        ),
    )
    top_tasks = [
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "due_date": t.get("due_date"),
            "priority": t.get("priority"),
            "status": t.get("status"),
            "contact_name": t.get("contact_name"),
        }
        for t in sorted_rows[:5]
    ]

    return {
        "enabled": True,
        "open_count": len(rows),
        "due_today_count": due_today_count,
        "overdue_count": overdue_count,
        "due_this_week_count": due_this_week_count,
        "top_tasks": top_tasks,
    }


def _dashboard_count_red_amber(items: list[dict[str, Any]] | None) -> tuple[int, int]:
    red = 0
    amber = 0
    for item in items or []:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "").strip().lower()
        if severity == "red":
            red += 1
        elif severity == "amber":
            amber += 1
    return red, amber


def _dashboard_build_compliance_summary(results: list[Any], system_status: dict[str, Any]) -> dict[str, Any]:
    by_id = {r.check_id: r for r in results}

    expired_data = (by_id.get("expired_materials").data or {}) if by_id.get("expired_materials") else {}
    untracked_data = (by_id.get("untracked_items").data or {}) if by_id.get("untracked_items") else {}
    output_expiry_data = (by_id.get("output_expiry").data or {}) if by_id.get("output_expiry") else {}
    output_ready_data = (by_id.get("output_ready_date").data or {}) if by_id.get("output_ready_date") else {}

    expired_raw = len(expired_data.get("expired_raw_materials") or [])
    expired_impacted = len(expired_data.get("impacted_items") or [])
    untracked_count = len(untracked_data.get("untracked_items") or [])
    output_expiry_red, output_expiry_amber = _dashboard_count_red_amber(output_expiry_data.get("output_expiry_items"))
    output_ready_red, output_ready_amber = _dashboard_count_red_amber(output_ready_data.get("output_ready_date_items"))

    expired_penalty = min(40, (25 if expired_raw > 0 else 0) + (2 * expired_impacted))
    untracked_penalty = min(25, 3 * untracked_count)
    output_expiry_penalty = min(20, (4 * output_expiry_red) + output_expiry_amber)
    output_ready_penalty = min(15, (2 * output_ready_red) + output_ready_amber)
    total_penalty = expired_penalty + untracked_penalty + output_expiry_penalty + output_ready_penalty
    score = max(0, min(100, 100 - total_penalty))

    drivers = [
        {"key": "expired_materials", "label": "Expired materials", "penalty": expired_penalty},
        {"key": "untracked_items", "label": "Untracked inventory", "penalty": untracked_penalty},
        {"key": "output_expiry", "label": "Output expiry", "penalty": output_expiry_penalty},
        {"key": "output_ready_date", "label": "Output ready-date", "penalty": output_ready_penalty},
    ]
    drivers = [d for d in drivers if d["penalty"] > 0]
    drivers.sort(key=lambda d: d["penalty"], reverse=True)

    active_use_risk_count = 0
    if isinstance(system_status, dict) and system_status.get("mode") == "health":
        signals = system_status.get("signals") or []
        active_use_risk_count = sum(
            1 for s in signals if isinstance(s, dict) and s.get("has_issue") and s.get("in_active_use")
        )

    return {
        "score": score,
        "score_version": "v1",
        "trend_delta_7d": None,
        "state": (system_status or {}).get("state", "unknown"),
        "top_drivers": drivers[:3],
        "findings": {
            "expired_materials": {"count": expired_raw, "impacted_count": expired_impacted},
            "untracked_items": {"count": untracked_count},
            "output_expiry": {"red_count": output_expiry_red, "amber_count": output_expiry_amber},
            "output_ready_date": {"red_count": output_ready_red, "amber_count": output_ready_amber},
            "active_use_risk_count": active_use_risk_count,
        },
    }


def _dashboard_event_log_period(
    org_id: UUID, session, period_start: datetime, period_end: datetime, limit: int = 10
) -> dict[str, Any]:
    q = (
        session.query(EntityEvent)
        .filter(EntityEvent.org_id == org_id)
        .filter(EntityEvent.created_at >= period_start, EntityEvent.created_at < period_end)
        .filter(EntityEvent.event_type.notin_(["user.login", "user.login_failed"]))
    )
    sync_job_expr = EntityEvent.payload["sync_job_id"].astext
    is_sale_adjustment = (
        (EntityEvent.event_type == "inventory_item.quantity_adjusted")
        & func.coalesce(
            EntityEvent.payload["reason"].astext.in_(["sales_fifo_consumption", "sales_fifo_reversal"]), False
        )
        & sync_job_expr.isnot(None)
    )
    sale_events_q = q.filter(is_sale_adjustment)
    sale_sync_job_ids = sale_events_q.with_entities(sync_job_expr).distinct()
    completed_sync_without_sales = (EntityEvent.event_type == "crm_xero.sync_completed") & (
        sync_job_expr.is_(None) | ~sync_job_expr.in_(sale_sync_job_ids)
    )
    q = q.filter(~completed_sync_without_sales)
    raw_total = q.count()
    sale_events_q = q.filter(is_sale_adjustment)
    sale_event_count = sale_events_q.count()
    events = q.filter(~is_sale_adjustment).order_by(EntityEvent.created_at.desc()).limit(limit).all()
    sync_events = {
        str((event.payload or {}).get("sync_job_id")): event
        for event in events
        if event.event_type in {"crm_xero.sync_completed", "crm_xero.sync_failed"}
        and (event.payload or {}).get("sync_job_id")
    }
    sales_by_sync: dict[str, list[Any]] = {}
    if sync_events:
        for event in sale_events_q.filter(sync_job_expr.in_(sync_events)).order_by(EntityEvent.created_at.desc()).all():
            sync_job_id = str((event.payload or {}).get("sync_job_id"))
            sales_by_sync.setdefault(sync_job_id, []).append(event)
    ordinary_events = [
        event
        for event in events
        if not (
            event.event_type in {"crm_xero.sync_completed", "crm_xero.sync_failed"}
            and str((event.payload or {}).get("sync_job_id")) in sales_by_sync
        )
    ]

    items = [
        {
            "id": str(event.id),
            "event_type": event.event_type,
            "summary": _human_summary(event),
            "at": event.created_at.isoformat() if event.created_at else None,
            "actor": event.actor_label or "System",
            "entity_type": event.entity_type,
            "entity_id": str(event.entity_id) if event.entity_id else None,
            "_sort_at": event.created_at,
        }
        for event in ordinary_events
    ]
    for sync_job_id, sale_events in sales_by_sync.items():
        sync_event = sync_events.get(sync_job_id)
        sales_by_line: dict[tuple[str, str], dict[str, Any]] = {}
        for event in sale_events:
            payload = event.payload or {}
            sale = payload.get("sale") or {}
            reference = str(payload.get("reference") or event.id)
            action = str(sale.get("action") or "sale")
            line = sales_by_line.setdefault(
                (reference, action),
                {
                    "action": action,
                    "product_name": sale.get("product_name") or payload.get("name") or "product",
                    "quantity_sold": None if action == "reversal" else sale.get("quantity_sold"),
                    "invoice_number": sale.get("invoice_number"),
                    "customer_name": sale.get("customer_name"),
                    "batches": {},
                },
            )
            if action == "reversal" and sale.get("quantity_sold"):
                line["quantity_sold"] = (line["quantity_sold"] or Decimal("0")) + Decimal(str(sale["quantity_sold"]))
            batch = str(sale.get("batch_number") or "unlabelled batch")
            batch_quantity = Decimal(str(sale.get("quantity_from_batch") or 0))
            line["batches"][batch] = line["batches"].get(batch, Decimal("0")) + batch_quantity

        details = []
        for line in sales_by_line.values():
            batch_text = ", ".join(
                f"{('batch ' + name) if name != 'unlabelled batch' else name} ({format(quantity.normalize(), 'f')})"
                for name, quantity in sorted(line["batches"].items())
            )
            quantity = line["quantity_sold"] or sum(line["batches"].values(), Decimal("0"))
            quantity_text = format(Decimal(str(quantity)).normalize(), "f")
            text = (
                f"{'Sale reversed' if line['action'] == 'reversal' else 'Sold'} "
                f"{quantity_text} × {line['product_name']} ({batch_text})"
            )
            if line["invoice_number"]:
                text += f", {line['invoice_number']}"
            if line["customer_name"]:
                text += f", {line['customer_name']}"
            details.append(text)

        event_source = sync_event or sale_events[0]
        timestamp = max((event.created_at for event in sale_events if event.created_at), default=None)
        if sync_event and sync_event.created_at and (timestamp is None or sync_event.created_at > timestamp):
            timestamp = sync_event.created_at
        failed = sync_event and sync_event.event_type == "crm_xero.sync_failed"
        sync_summary = (
            f"Xero sync {'failed' if failed else 'sales activity'}: "
            f"{len(details)} sale line{'s' if len(details) != 1 else ''} across "
            f"{len(sale_events)} batch update{'s' if len(sale_events) != 1 else ''}"
        )
        items.append(
            {
                "id": str(event_source.id),
                "event_type": "crm_xero.sales_activity",
                "summary": sync_summary,
                "at": timestamp.isoformat() if timestamp else None,
                "actor": (sync_event.actor_label if sync_event else None) or "System",
                "entity_type": "xero_sync_job",
                "entity_id": str(sync_event.entity_id) if sync_event else sync_job_id,
                "details": details,
                "_sort_at": timestamp,
            }
        )
    items.sort(key=lambda item: item["_sort_at"] or datetime.min.replace(tzinfo=UTC), reverse=True)
    total = raw_total - sale_event_count
    return {
        "total": total,
        "items": [{key: value for key, value in item.items() if key != "_sort_at"} for item in items[:limit]],
    }


def _dashboard_operations_summary(
    org_id: UUID, session, day_start: datetime, next_day_start: datetime
) -> dict[str, int]:
    active_executions = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status.in_([ExecutionStatus.PENDING, ExecutionStatus.IN_PROGRESS]))
        .count()
    )
    completed_today = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status == ExecutionStatus.COMPLETED)
        .filter(Execution.completed_at.isnot(None))
        .filter(Execution.completed_at >= day_start, Execution.completed_at < next_day_start)
        .count()
    )
    failed_or_cancelled_today = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status.in_([ExecutionStatus.FAILED, ExecutionStatus.CANCELLED]))
        .filter(Execution.updated_at >= day_start, Execution.updated_at < next_day_start)
        .count()
    )
    return {
        "active_executions": active_executions,
        "completed_today": completed_today,
        "failed_or_cancelled_today": failed_or_cancelled_today,
    }


def _dashboard_week_boundaries(today: date) -> tuple[datetime, datetime, datetime]:
    week_start_date = today - timedelta(days=today.weekday())
    # each boundary built from its own date so a DST change inside the window can't skew it
    week_start = _local_midnight(week_start_date)
    next_week_start = _local_midnight(week_start_date + timedelta(days=7))
    prev_week_start = _local_midnight(week_start_date - timedelta(days=7))
    return week_start, next_week_start, prev_week_start


def _dashboard_parse_date_like(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _dashboard_short_date_label(day: date) -> str:
    return f"{day.strftime('%b')} {day.day}"


def _dashboard_series_from_date_counts(
    day_counts: dict[date, int],
    *,
    start_day: date | None = None,
    end_day: date | None = None,
    cumulative: bool = True,
) -> dict[str, Any]:
    if start_day is None and day_counts:
        start_day = min(day_counts)
    if end_day is None and day_counts:
        end_day = max(day_counts)
    if start_day is None:
        start_day = date.today()
    if end_day is None:
        end_day = start_day
    if end_day < start_day:
        end_day = start_day

    points: list[dict[str, Any]] = []
    cursor = start_day
    running = 0
    while cursor <= end_day:
        value = int(day_counts.get(cursor) or 0)
        if cumulative:
            running += value
            y = running
        else:
            y = value
        points.append({"date": cursor.isoformat(), "value": y})
        cursor = cursor + timedelta(days=1)

    return {
        "start": start_day.isoformat(),
        "end": end_day.isoformat(),
        "start_label": _dashboard_short_date_label(start_day),
        "end_label": _dashboard_short_date_label(end_day),
        "points": points,
    }


def _dashboard_event_counts_by_day(
    org_id: UUID, session, start_dt: datetime, end_dt: datetime, actor_type: str | None = None
) -> dict[date, int]:
    q = (
        session.query(
            _local_date_expr(EntityEvent.created_at).label("event_day"), func.count(EntityEvent.id).label("total")
        )
        .filter(EntityEvent.org_id == org_id)
        .filter(EntityEvent.created_at >= start_dt, EntityEvent.created_at < end_dt)
        .filter(EntityEvent.event_type.notin_(["user.login", "user.login_failed"]))
    )
    if actor_type:
        q = q.filter(EntityEvent.actor_type == actor_type)
    rows = q.group_by(_local_date_expr(EntityEvent.created_at)).all()
    out: dict[date, int] = {}
    for row in rows:
        day = _dashboard_parse_date_like(getattr(row, "event_day", None))
        if day is None:
            continue
        out[day] = int(getattr(row, "total", 0) or 0)
    return out


def _dashboard_execution_counts_by_day(
    org_id: UUID, session, start_dt: datetime, end_dt: datetime, column: str
) -> dict[date, int]:
    if column == "completed":
        day_col = Execution.completed_at
        q = (
            session.query(_local_date_expr(day_col).label("event_day"), func.count(Execution.id).label("total"))
            .filter(Execution.org_id == org_id)
            .filter(Execution.status == ExecutionStatus.COMPLETED)
            .filter(day_col.isnot(None))
            .filter(day_col >= start_dt, day_col < end_dt)
        )
    else:
        day_col = Execution.started_at
        q = (
            session.query(_local_date_expr(day_col).label("event_day"), func.count(Execution.id).label("total"))
            .filter(Execution.org_id == org_id)
            .filter(day_col.isnot(None))
            .filter(day_col >= start_dt, day_col < end_dt)
        )
    rows = q.group_by(_local_date_expr(day_col)).all()
    out: dict[date, int] = {}
    for row in rows:
        day = _dashboard_parse_date_like(getattr(row, "event_day", None))
        if day is None:
            continue
        out[day] = int(getattr(row, "total", 0) or 0)
    return out


def _dashboard_open_action_item_dates(
    check_results: list[Any], open_tasks: list[dict[str, Any]], today: date
) -> list[date]:
    by_id = {r.check_id: r for r in check_results or []}
    dates: list[date] = []

    expired_data = (by_id.get("expired_materials").data or {}) if by_id.get("expired_materials") else {}
    for item in expired_data.get("expired_raw_materials") or []:
        if not isinstance(item, dict):
            continue
        d = _dashboard_parse_date_like(item.get("expiry_date")) or _dashboard_parse_date_like(item.get("created_at"))
        if d:
            dates.append(d)

    untracked_data = (by_id.get("untracked_items").data or {}) if by_id.get("untracked_items") else {}
    for item in untracked_data.get("untracked_items") or []:
        if not isinstance(item, dict):
            continue
        d = _dashboard_parse_date_like(item.get("created_at"))
        if d:
            dates.append(d)

    output_expiry_data = (by_id.get("output_expiry").data or {}) if by_id.get("output_expiry") else {}
    for item in output_expiry_data.get("output_expiry_items") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("severity") or "").strip().lower() != "red":
            continue
        d = _dashboard_parse_date_like(item.get("detected_at")) or _dashboard_parse_date_like(item.get("expiry_at"))
        if d:
            dates.append(d)

    for task in open_tasks or []:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "").strip().lower()
        if status not in {"pending", "in_progress"}:
            continue
        due = _dashboard_parse_date_like(task.get("due_date"))
        if due is not None and due < today:
            dates.append(due)

    return dates


def _dashboard_operations_weekly_summary(org_id: UUID, session, now_dt: datetime, today: date) -> dict[str, Any]:
    week_start, next_week_start, prev_week_start = _dashboard_week_boundaries(today)

    active_executions = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status.in_([ExecutionStatus.PENDING, ExecutionStatus.IN_PROGRESS]))
        .count()
    )
    started_this_week = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.started_at >= week_start, Execution.started_at < next_week_start)
        .count()
    )
    completed_this_week = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status == ExecutionStatus.COMPLETED)
        .filter(Execution.completed_at.isnot(None))
        .filter(Execution.completed_at >= week_start, Execution.completed_at < next_week_start)
        .count()
    )
    completed_last_week = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status == ExecutionStatus.COMPLETED)
        .filter(Execution.completed_at.isnot(None))
        .filter(Execution.completed_at >= prev_week_start, Execution.completed_at < week_start)
        .count()
    )
    failed_or_cancelled_this_week = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status.in_([ExecutionStatus.FAILED, ExecutionStatus.CANCELLED]))
        .filter(Execution.updated_at >= week_start, Execution.updated_at < next_week_start)
        .count()
    )
    stalled_active_over_48h = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status.in_([ExecutionStatus.PENDING, ExecutionStatus.IN_PROGRESS]))
        .filter(Execution.started_at < (now_dt - timedelta(hours=48)))
        .count()
    )
    completed_vs_last_week_pct = None
    if completed_last_week > 0:
        completed_vs_last_week_pct = round(((completed_this_week - completed_last_week) / completed_last_week) * 100, 1)

    return {
        "window": "week_to_date",
        "active_executions": active_executions,
        "started_this_week": started_this_week,
        "completed_this_week": completed_this_week,
        "failed_or_cancelled_this_week": failed_or_cancelled_this_week,
        "stalled_active_over_48h": stalled_active_over_48h,
        "completed_last_week": completed_last_week,
        "completed_vs_last_week_pct": completed_vs_last_week_pct,
    }


def _dashboard_module_workspace_summaries(check_results: list[Any], workspace: str) -> list[dict[str, Any]]:
    """Project module-owned Dashboard summaries without knowing module check IDs."""
    summaries = []
    for result in check_results:
        data = result.data if isinstance(getattr(result, "data", None), dict) else {}
        summary = data.get("workspace_summary") if isinstance(data, dict) else None
        if not isinstance(summary, dict) or summary.get("workspace") != workspace:
            continue
        href = str(summary.get("href") or "")
        if not href.startswith("/") or href.startswith("//"):
            continue
        try:
            summaries.append(
                {
                    "module_name": str(summary.get("module_name") or "Module"),
                    "href": href,
                    "action_label": str(summary.get("action_label") or "Open module"),
                    "score": max(0, min(100, int(summary.get("score") or 0))),
                    "current_controls": max(0, int(summary.get("current_controls") or 0)),
                    "total_controls": max(0, int(summary.get("total_controls") or 0)),
                    "evidence_ready": max(0, int(summary.get("evidence_ready") or 0)),
                    "needs_attention": max(0, int(summary.get("needs_attention") or 0)),
                    "overdue": max(0, int(summary.get("overdue") or 0)),
                }
            )
        except (TypeError, ValueError):
            continue
    return summaries


def _dashboard_compliant_workspace_summary(
    org_id: UUID, session, *, module_summaries: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Return the small, dashboard-safe summary of the optional Compliant workspace.

    This deliberately avoids ``ComplianceService.overview()``: that view calculates the
    full evidence plan and scans Core movements, which belongs on the Compliant workbench.
    Dashboard needs only enough information to tell a user whether to go there and why.
    """
    unavailable = {
        "available": False,
        "state": "unavailable",
        "label": "Compliance is not enabled for this organisation.",
        "attention_count": 0,
        "modules": [],
    }
    if not config.compliant_enabled or not has_permission(g.current_user, "compliance.view"):
        return unavailable

    try:
        from app.core.security.entitlements import org_has_feature

        if not org_has_feature(session, org_id, "compliant"):
            return unavailable

        from app.features.compliant.models import ComplianceProfile, ComplianceRecord

        profile = session.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).one_or_none()
        if profile is None or not profile.enabled:
            return {
                "available": True,
                "state": "setup",
                "label": "Set up the evidence plan for your operation.",
                "attention_count": 0,
                "modules": [],
            }

        if module_summaries:
            attention_count = sum(item["needs_attention"] for item in module_summaries)
            return {
                "available": True,
                "state": "attention" if attention_count else "ready",
                "label": (
                    f"{attention_count} compliance check{'s' if attention_count != 1 else ''} need attention."
                    if attention_count
                    else "All current compliance evidence is ready."
                ),
                "attention_count": attention_count,
                "modules": module_summaries,
            }

        status_counts = dict(
            session.query(ComplianceRecord.status, func.count(ComplianceRecord.id))
            .filter(ComplianceRecord.org_id == org_id)
            .filter(ComplianceRecord.status.in_(["open", "failed"]))
            .group_by(ComplianceRecord.status)
            .all()
        )
        open_count = int(status_counts.get("open") or 0)
        failed_count = int(status_counts.get("failed") or 0)
        attention_count = open_count + failed_count
        if attention_count:
            return {
                "available": True,
                "state": "attention",
                "label": f"{attention_count} evidence record{'s' if attention_count != 1 else ''} need attention.",
                "attention_count": attention_count,
                "modules": [],
            }
        return {
            "available": True,
            "state": "ready",
            "label": "No open or failed evidence records.",
            "attention_count": 0,
            "modules": [],
        }
    except Exception:
        # Compliant is an optional workspace. A failed summary must not take the shared
        # dashboard down, and the Compliant workspace remains its source of truth.
        logger.exception("Failed to assemble Compliant dashboard summary for org_id=%s", org_id)
        return unavailable


def _dashboard_build_action_board(
    tasks_summary: dict[str, Any],
    compliance: dict[str, Any],
    compliant_workspace: dict[str, Any] | None = None,
    *,
    check_results: list[Any] | None = None,
    stalled_batches: int = 0,
    today: date | None = None,
) -> dict[str, Any]:
    findings = (compliance or {}).get("findings") or {}
    output_expiry = findings.get("output_expiry") or {}
    output_ready = findings.get("output_ready_date") or {}

    candidates = [
        {
            "key": "expired_raw",
            "label": "Expired raw materials with stock",
            "count": (findings.get("expired_materials") or {}).get("count") or 0,
            "severity": "critical",
            "href": "/core/inventory/view",
            "workspace": "Production",
        },
        {
            "key": "untracked_items",
            "label": "Untracked items needing reconciliation",
            "count": (findings.get("untracked_items") or {}).get("count") or 0,
            "severity": "high",
            "href": "/core/notifications",
            "workspace": "Production",
        },
        {
            "key": "output_expired",
            "label": "Expired outputs",
            "count": output_expiry.get("red_count") or 0,
            "severity": "critical",
            "href": "/core/notifications",
            "workspace": "Production",
        },
        {
            "key": "output_not_ready",
            "label": "Outputs waiting for ready date",
            "count": output_ready.get("red_count") or 0,
            "severity": "informational",
            "href": "/core/notifications",
            "workspace": "Production",
        },
        {
            "key": "overdue_tasks",
            "label": "Overdue Sales tasks",
            "count": (tasks_summary or {}).get("overdue_count") or 0,
            "severity": "high",
            "href": "/crm/tasks",
            "workspace": "Sales",
        },
        {
            "key": "tasks_due_today",
            "label": "Customer tasks due today",
            "count": (tasks_summary or {}).get("due_today_count") or 0,
            "severity": "medium",
            "href": "/crm/tasks",
            "workspace": "Sales",
        },
        {
            "key": "stalled_batches",
            "label": "Production batches idle for more than 48 hours",
            "count": stalled_batches,
            "severity": "medium",
            "href": "/core/executions/live",
            "workspace": "Production",
        },
        {
            "key": "compliant_evidence",
            "label": "Compliance evidence records needing attention",
            "count": (compliant_workspace or {}).get("attention_count") or 0,
            "severity": "high",
            "href": "/compliant",
            "workspace": "Compliance",
        },
    ]

    today = today or date.today()
    for result in check_results or []:
        data = result.data if isinstance(getattr(result, "data", None), dict) else {}
        alerts = data.get("system_alerts") if isinstance(data, dict) else None
        for alert in alerts if isinstance(alerts, list) else []:
            if not isinstance(alert, dict):
                continue
            due = _dashboard_parse_due_date(alert.get("due_date"))
            if due is None or due > today + timedelta(days=30):
                continue
            href = alert.get("href")
            if not isinstance(href, str) or not href.startswith("/") or href.startswith("//"):
                href = "/core/notifications"
            due_label = "overdue" if due < today else "due " + due.isoformat()
            candidates.append(
                {
                    "key": "compliance_due_" + str(alert.get("id") or len(candidates)),
                    "label": str(alert.get("title") or "Compliance review") + " · " + due_label,
                    "count": 1,
                    "severity": "high" if due < today else "medium",
                    "href": href,
                    "workspace": "Compliance",
                }
            )

    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}
    items = [item for item in candidates if (item.get("count") or 0) > 0]
    items.sort(key=lambda item: (severity_rank.get(str(item.get("severity") or "low"), 4), -(item.get("count") or 0)))
    critical_actions_total = sum(
        int(item.get("count") or 0) for item in items if str(item.get("severity") or "").lower() != "informational"
    )

    return {"critical_actions_total": critical_actions_total, "items": items[:6]}


@requires_auth
def get_dashboard_summary():
    org_id = UUID(g.org_id)
    window_days_raw = (request.args.get("window_days") or "30").strip()
    try:
        window_days = int(window_days_raw)
    except ValueError:
        return jsonify({"error": "window_days must be an integer"}), 400
    if window_days < 7 or window_days > 180:
        return jsonify({"error": "window_days must be between 7 and 180"}), 400

    today = date.today()
    now_dt = datetime.now(_APP_TZ)
    day_start = _local_midnight(today)
    next_day_start = _local_midnight(today + timedelta(days=1))
    week_start, next_week_start, _prev_week_start = _dashboard_week_boundaries(today)

    # The DAG-heavy expired_materials check is served from the per-org system-findings
    # cache (fresh until NZ midnight, invalidated on inventory/execution/process
    # mutations, pre-warmed by the warm-system-findings job); the cheap checks run live.
    # Same result set as CoreChecksRunner.run_all_checks() without the ~640ms DAG cost on
    # every landing-page load.
    from app.features.compliance_checks.system_findings_cache import get_check_results

    check_results = get_check_results(org_id, db_session)

    from app.features.compliance_checks.system_status import build_system_status_payload

    system_status = build_system_status_payload(org_id, db_session, check_results)
    compliance = _dashboard_build_compliance_summary(check_results, system_status)

    operations_day_summary = _dashboard_operations_summary(org_id, db_session, day_start, next_day_start)
    operations_week_summary = _dashboard_operations_weekly_summary(org_id, db_session, now_dt, today)
    operator_actions_this_week = (
        db_session.query(EntityEvent)
        .filter(EntityEvent.org_id == org_id)
        .filter(EntityEvent.created_at >= week_start, EntityEvent.created_at < next_week_start)
        .filter(EntityEvent.actor_type == "user")
        .filter(EntityEvent.event_type.notin_(["user.login", "user.login_failed"]))
        .count()
    )
    audit_log = {
        "limit": 10,
        "day": _dashboard_event_log_period(org_id, db_session, day_start, next_day_start, limit=10),
        "week": _dashboard_event_log_period(org_id, db_session, week_start, next_week_start, limit=10),
    }

    tasks_summary: dict[str, Any] = {
        "enabled": False,
        "open_count": 0,
        "due_today_count": 0,
        "overdue_count": 0,
        "due_this_week_count": 0,
        "top_tasks": [],
    }
    open_tasks_for_insights: list[dict[str, Any]] = []
    sales_summary: dict[str, Any] = {
        "enabled": False,
        "current_month_revenue": 0.0,
        "outstanding_receivables": 0.0,
        "revenue_vs_last_month_pct": None,
        "baseline_target_mtd": None,
        "baseline_variance_mtd": None,
        "baseline_attainment_pct": None,
    }
    revenue_daily_mtd: list[dict[str, Any]] = []

    if config.crm_enabled and has_permission(g.current_user, "sales.view"):
        try:
            from app.features.crm.services.crm_service import CRMService

            crm_service = CRMService(db_session)
            crm_overview = crm_service.get_overview(org_id)
            trace_cfg = crm_service.get_traceability_config(org_id)
            open_tasks_for_insights = crm_overview.get("open_tasks") or []
            tasks_summary = _dashboard_summarize_tasks(
                open_tasks_for_insights,
                today,
                week_start=week_start.date(),
                week_end_exclusive=next_week_start.date(),
            )
            month_start = today.replace(day=1)
            revenue_daily_mtd = crm_service.daily_sales_for_period(org_id, month_start, today + timedelta(days=1))
            baseline_target = trace_cfg.get("revenue_baseline_target_mtd")
            baseline_variance = None
            baseline_attainment = None
            if baseline_target is not None:
                try:
                    baseline_target = float(baseline_target)
                    baseline_variance = float((crm_overview.get("current_month_revenue") or 0.0) - baseline_target)
                    if baseline_target > 0:
                        baseline_attainment = round(
                            ((crm_overview.get("current_month_revenue") or 0.0) / baseline_target) * 100, 1
                        )
                except (TypeError, ValueError):
                    baseline_target = None
            sales_summary = {
                "enabled": True,
                "current_month_revenue": crm_overview.get("current_month_revenue") or 0.0,
                "outstanding_receivables": crm_overview.get("outstanding_receivables") or 0.0,
                "revenue_vs_last_month_pct": crm_overview.get("revenue_vs_last_month_pct"),
                "baseline_target_mtd": baseline_target,
                "baseline_variance_mtd": baseline_variance,
                "baseline_attainment_pct": baseline_attainment,
            }
        except Exception:
            logger.exception("Failed to assemble CRM summary for org_id=%s", org_id)

    compliant_workspace = _dashboard_compliant_workspace_summary(
        org_id,
        db_session,
        module_summaries=_dashboard_module_workspace_summaries(check_results, "compliant"),
    )
    action_board = _dashboard_build_action_board(
        tasks_summary,
        compliance,
        compliant_workspace,
        check_results=check_results,
        stalled_batches=int(operations_week_summary.get("stalled_active_over_48h") or 0),
        today=today,
    )
    operator_series = _dashboard_series_from_date_counts(
        _dashboard_event_counts_by_day(org_id, db_session, week_start, next_week_start, actor_type="user"),
        start_day=week_start.date(),
        end_day=today,
        cumulative=True,
    )

    open_action_dates = _dashboard_open_action_item_dates(check_results, open_tasks_for_insights, today)
    open_action_counts: dict[date, int] = {}
    for d in open_action_dates:
        open_action_counts[d] = int(open_action_counts.get(d, 0)) + 1
    open_action_series = _dashboard_series_from_date_counts(
        open_action_counts,
        start_day=min(open_action_counts) if open_action_counts else (today - timedelta(days=6)),
        end_day=max(open_action_counts) if open_action_counts else today,
        cumulative=True,
    )

    execution_started_series = _dashboard_series_from_date_counts(
        _dashboard_execution_counts_by_day(org_id, db_session, week_start, next_week_start, column="started"),
        start_day=week_start.date(),
        end_day=today,
        cumulative=True,
    )
    execution_completed_series = _dashboard_series_from_date_counts(
        _dashboard_execution_counts_by_day(org_id, db_session, week_start, next_week_start, column="completed"),
        start_day=week_start.date(),
        end_day=today,
        cumulative=True,
    )

    tasks_due_counts: dict[date, int] = {}
    for task in open_tasks_for_insights:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "").strip().lower()
        if status not in {"pending", "in_progress"}:
            continue
        due = _dashboard_parse_date_like(task.get("due_date"))
        if due is None:
            continue
        if week_start.date() <= due < next_week_start.date():
            tasks_due_counts[due] = int(tasks_due_counts.get(due, 0)) + 1
    tasks_due_series = _dashboard_series_from_date_counts(
        tasks_due_counts,
        start_day=week_start.date(),
        end_day=today,
        cumulative=True,
    )

    revenue_day_counts: dict[date, int] = {}
    for row in revenue_daily_mtd:
        if not isinstance(row, dict):
            continue
        d = _dashboard_parse_date_like(row.get("day"))
        if d is None:
            continue
        revenue_day_counts[d] = int(round(float(row.get("total") or 0)))
    month_start_date = today.replace(day=1)
    revenue_series = _dashboard_series_from_date_counts(
        revenue_day_counts,
        start_day=month_start_date,
        end_day=today,
        cumulative=True,
    )

    return (
        jsonify(
            {
                "generated_at": datetime.now().isoformat(),
                "window_days": window_days,
                "tasks": tasks_summary,
                "compliance": compliance,
                "compliant_workspace": compliant_workspace,
                "action_board": action_board,
                "operator_actions": {"week_to_date": operator_actions_this_week},
                "audit_log": audit_log,
                "operations": operations_week_summary,
                "operations_today": operations_day_summary,
                "sales": sales_summary,
                "insight_series": {
                    "operator_actions_week": operator_series,
                    "open_action_items": open_action_series,
                    "active_batches_week": execution_started_series,
                    "batch_completion_week": execution_completed_series,
                    "tasks_due_week": tasks_due_series,
                    "revenue_goal_mtd": revenue_series,
                },
            }
        ),
        200,
    )


@requires_auth
def get_metrics():
    """Get summary metrics for the dashboard"""
    org_id = UUID(g.org_id)

    process_repo = ProcessRepository(db_session)
    execution_repo = ExecutionRepository(db_session)
    inventory_repo = InventoryRepository(db_session)

    # Total processes
    processes = process_repo.list_processes(org_id)
    total_processes = len(processes)

    # Counted in SQL rather than len(list_executions(...)) -- that fetched every
    # execution's joined steps (twice: once per status) just to discard the objects
    # and keep a count, which got slower as an org's execution history grew.
    executions_by_status = execution_repo.count_executions_by_status(org_id)
    active_executions = executions_by_status.get(ExecutionStatus.IN_PROGRESS.value, 0)
    completed_count = executions_by_status.get(ExecutionStatus.COMPLETED.value, 0)

    # Same reasoning: counted in SQL rather than filtering list_inventory_items(...)
    # (every column, including extra_data) in Python.
    items_by_type = inventory_repo.count_inventory_items_by_type(org_id)
    raw_materials_count = items_by_type.get(InventoryType.RAW_MATERIAL.value, 0)
    wip_count = items_by_type.get(InventoryType.WORK_IN_PROGRESS.value, 0)
    final_products_count = items_by_type.get(InventoryType.FINAL_PRODUCT.value, 0)

    return (
        jsonify(
            {
                "total_processes": total_processes,
                "active_executions": active_executions,
                "completed_executions": completed_count,
                "inventory_items": {
                    "total": sum(items_by_type.values()),
                    "raw_materials": raw_materials_count,
                    "work_in_progress": wip_count,
                    "final_products": final_products_count,
                },
            }
        ),
        200,
    )


def register_routes(bp):
    """Keep dashboard URLs and endpoint names on core_bp."""
    bp.add_url_rule("/core/dashboard", view_func=dashboard, methods=["GET"])
    bp.add_url_rule("/api/core/dashboard/summary", view_func=get_dashboard_summary, methods=["GET"])
    bp.add_url_rule("/api/core/metrics", view_func=get_metrics, methods=["GET"])
