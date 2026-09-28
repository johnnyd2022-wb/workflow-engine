"""Install-time registration for the NZ Alcohol module."""

from urllib.parse import quote
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.corechecks import CheckResult
from app.features.compliant.service import ComplianceService
from app.utils.config_loader import config

CHECK_ID = "compliant.nz_alcohol"


def _np3_system_alerts(queue: list[dict], overall_alert: dict | None) -> list[dict]:
    """Describe NP3 work in the generic Core finding/notification contract."""
    alerts = []
    if overall_alert:
        alerts.append({"id": "np3-overall", **overall_alert, "action_label": "Open NP3"})
    for index, action in enumerate(queue):
        control_id = str(action.get("control_id") or "")
        if not control_id:
            continue
        suffix = str(action.get("person") or action.get("kind") or index)
        alerts.append(
            {
                "id": f"np3-{control_id}-{suffix}",
                "title": str(action.get("title") or "NP3 action"),
                "description": str(action.get("description") or "Open the tailored NP3 check to complete this action."),
                "due_date": action.get("due_date"),
                "href": f"/compliant/nz-alcohol/np3-audit/check/{quote(control_id, safe='')}",
                "action_label": "Open NP3 check",
            }
        )
    return alerts


def _np3_workspace_summary(health: dict) -> dict:
    """Describe NP3 health for the generic shared-Dashboard workspace contract."""
    evidence_ready = int(health.get("ok") or 0)
    needs_attention = int(health.get("needs_attention") or 0)
    total_controls = evidence_ready + needs_attention
    return {
        "workspace": "compliant",
        "module_name": "NP3",
        "href": "/compliant/nz-alcohol/food-safety",
        "action_label": "Open NP3",
        "score": round((evidence_ready / total_controls) * 100) if total_controls else 0,
        "current_controls": evidence_ready,
        "total_controls": total_controls,
        "evidence_ready": evidence_ready,
        "needs_attention": needs_attention,
        "overdue": int(health.get("overdue") or 0),
    }


def run_check(org_id: UUID, session: Session) -> CheckResult:
    service = ComplianceService(session)
    frameworks = service.evaluate(org_id)
    attention = [framework for framework in frameworks if framework["state"] == "attention"]
    if not frameworks:
        return CheckResult(check_id=CHECK_ID, flagged=False, data={"frameworks": []})
    message = None
    attention_controls = [
        control for framework in attention for control in framework["controls"] if control["state"] == "attention"
    ]
    profile = service.get_profile(org_id)
    np3_audit = (
        service.np3_audit(org_id)
        if (profile.settings or {}).get("food_control_programme") == "np3"
        else {"work_queue": [], "health": {}}
    )
    queue = np3_audit["work_queue"]
    health = np3_audit["health"]
    needs_attention = health.get("needs_attention", 0)
    np3_alert = (
        {
            "title": "NP3 compliance needs attention",
            "description": f"{needs_attention} NP3 check{'s' if needs_attention != 1 else ''} require evidence or a response.",
            "href": "/compliant/nz-alcohol/food-safety",
        }
        if needs_attention
        else None
    )
    system_alerts = _np3_system_alerts(queue, np3_alert)
    system_finding = (
        {
            "category": "NP3 compliance",
            "action": {"href": "/compliant/nz-alcohol/food-safety", "label": "Open NP3"},
            "details": system_alerts[:6],
        }
        if system_alerts
        else None
    )
    critical_actions = [action for action in queue if action["severity"] in {"attention", "overdue"}]
    if np3_alert:
        message = np3_alert["description"]
    elif any(action["kind"] == "overdue-review" for action in critical_actions):
        message = "An NP3 evidence review is overdue"
    elif any(action["kind"] == "guidance-update" for action in critical_actions):
        message = "NP3 guidance changed after a signed review"
    elif any(action["kind"] == "due-soon-review" for action in queue):
        message = "An NP3 evidence review is due soon"
    elif any(control["control_id"] in {"staff-competency", "certified-manager"} for control in attention_controls):
        message = "NZ Alcohol staff training or competency evidence needs attention"
    elif attention:
        message = f"{len(attention)} NZ Alcohol compliance framework(s) need attention"
    return CheckResult(
        check_id=CHECK_ID,
        # NP3 is a live (uncached) system check, so due-soon work becomes visible as
        # soon as it is actionable rather than waiting until the review is overdue.
        flagged=bool(attention or queue or np3_alert),
        message=message,
        data={
            "frameworks": frameworks,
            "attention_controls": attention_controls,
            "np3_health": health,
            "np3_work_queue": queue,
            "workspace_summary": _np3_workspace_summary(health) if health else None,
            "system_finding": system_finding,
            "system_alerts": system_alerts,
        },
    )


EXCISE_CHECK_ID = "compliant.nz_alcohol.excise"


def run_excise_check(org_id: UUID, session: Session) -> CheckResult:
    """Plan 2.1: an excise entry (or nil return) to lodge, until it's recorded as lodged."""
    from app.features.compliant.modules.nz_alcohol import excise

    profile = ComplianceService(session).get_profile(org_id)
    alert = excise.reminder(session, org_id, profile) if profile is not None and profile.enabled else None
    if alert is None:
        return CheckResult(check_id=EXCISE_CHECK_ID, flagged=False, data={})
    overdue = alert.pop("overdue")
    return CheckResult(
        check_id=EXCISE_CHECK_ID,
        flagged=True,
        message=alert["title"],
        data={
            "system_finding": {
                "category": "Customs excise" + (" (overdue)" if overdue else ""),
                "action": {"href": alert["href"], "label": "Open excise"},
                "details": [alert],
            },
            "system_alerts": [alert],
        },
    )


def register_checks(runner) -> None:
    if config.compliant_enabled:
        runner.register_check(CHECK_ID, run_check)
        runner.register_check(EXCISE_CHECK_ID, run_excise_check)
