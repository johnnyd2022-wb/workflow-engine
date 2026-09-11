"""Surface due Core and CRM work in notifications and overdue system findings."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.corechecks import CheckResult
from app.core.backend.tasks import task_due_summary

CHECK_ID = "tasks_due"


def run_tasks_due_check(org_id: UUID, session: Session) -> CheckResult:
    summary = task_due_summary(session, org_id)
    overdue = summary["overdue_tasks"]
    due_soon = summary["due_soon_tasks"]
    message = None
    if overdue:
        message = f"{len(overdue)} task(s) are overdue."
    elif due_soon:
        message = f"{len(due_soon)} task(s) are due soon."
    return CheckResult(
        check_id=CHECK_ID,
        # Due-soon work is a notification. Only overdue work changes system health.
        flagged=bool(overdue),
        message=message,
        data=summary,
    )
