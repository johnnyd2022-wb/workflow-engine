"""Install-time registration for the NZ Alcohol module."""

from datetime import date, timedelta
from urllib.parse import quote
from uuid import UUID

from sqlalchemy.orm import Session

from app.features.compliance_checks.routes.corechecks import CheckResult
from app.features.compliant.service import ComplianceService
from app.utils.config_loader import config

CHECK_ID = "compliant.nz_alcohol"


def _np3_system_alerts(queue: list[dict], overall_alert: dict | None, label: str = "NP3") -> list[dict]:
    """Describe national-programme work in the generic Core finding/notification contract."""
    alerts = []
    if overall_alert:
        alerts.append({"id": "np3-overall", **overall_alert, "action_label": f"Open {label}"})
    for index, action in enumerate(queue):
        control_id = str(action.get("control_id") or "")
        if not control_id:
            continue
        suffix = str(action.get("person") or action.get("kind") or index)
        alerts.append(
            {
                "id": f"np3-{control_id}-{suffix}",
                "title": str(action.get("title") or f"{label} action"),
                "description": str(
                    action.get("description") or f"Open the tailored {label} check to complete this action."
                ),
                "due_date": action.get("due_date"),
                "href": f"/compliant/nz-alcohol/np3-audit/check/{quote(control_id, safe='')}",
                "action_label": f"Open {label} check",
            }
        )
    return alerts


def _verification_milestone(session: Session, org_id: UUID, profile) -> dict | None:
    from app.features.compliant.modules.nz_alcohol import verification

    choices = []
    for current in verification.statuses_for_org(session, org_id, profile, date.today()):
        entry = verification.milestone(current)
        if entry is not None:
            if current.get("registration_name"):
                entry["detail"] = " · ".join(filter(None, (current["registration_name"], entry.get("detail"))))
            choices.append(entry)
    return min(choices, key=lambda item: item.get("date") or "9999-12-31") if choices else None


def _np3_workspace_summary(health: dict, milestone: dict | None = None, label: str = "NP3") -> dict:
    """Describe national-programme health for the generic shared-Dashboard workspace contract."""
    evidence_ready = int(health.get("ok") or 0)
    needs_attention = int(health.get("needs_attention") or 0)
    total_controls = evidence_ready + needs_attention
    return {
        "workspace": "compliant",
        "module_name": label,
        "href": "/compliant/nz-alcohol/food-safety",
        "action_label": f"Open {label}",
        "score": round((evidence_ready / total_controls) * 100) if total_controls else 0,
        "current_controls": evidence_ready,
        "total_controls": total_controls,
        "evidence_ready": evidence_ready,
        "needs_attention": needs_attention,
        "overdue": int(health.get("overdue") or 0),
        "milestone": milestone,  # plan 2.2: next verification, always on screen
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
    programme = (profile.settings or {}).get("food_control_programme")
    label = programme.upper() if programme in ("np1", "np2", "np3") else "NP3"
    np3_audit = service.np3_audit(org_id) if programme in ("np1", "np2", "np3") else {"work_queue": [], "health": {}}
    queue = np3_audit["work_queue"]
    health = np3_audit["health"]
    needs_attention = health.get("needs_attention", 0)
    np3_alert = (
        {
            "title": f"{label} compliance needs attention",
            "description": f"{needs_attention} {label} check{'s' if needs_attention != 1 else ''} require evidence or a response.",
            "href": "/compliant/nz-alcohol/food-safety",
        }
        if needs_attention
        else None
    )
    system_alerts = _np3_system_alerts(queue, np3_alert, label)
    system_finding = (
        {
            "category": f"{label} compliance",
            "action": {"href": "/compliant/nz-alcohol/food-safety", "label": f"Open {label}"},
            "details": system_alerts[:6],
        }
        if system_alerts
        else None
    )
    critical_actions = [action for action in queue if action["severity"] in {"attention", "overdue"}]
    if np3_alert:
        message = np3_alert["description"]
    elif any(action["kind"] == "overdue-review" for action in critical_actions):
        message = f"An {label} evidence review is overdue"
    elif any(action["kind"] == "guidance-update" for action in critical_actions):
        message = f"{label} guidance changed after a signed review"
    elif any(action["kind"] == "due-soon-review" for action in queue):
        message = f"An {label} evidence review is due soon"
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
            "workspace_summary": _np3_workspace_summary(
                health, _verification_milestone(session, org_id, profile), label
            )
            if health
            else None,
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


STOCKTAKE_CHECK_ID = "compliant.nz_alcohol.stocktake"
STOCKTAKE_REMIND_DAYS = 14


def stocktake_alerts(session: Session, org_id: UUID, settings: dict | None, today: date) -> list[dict]:
    """Plan 2.6: the next stocktake coming due, and every unresolved variance with its LAL and duty."""
    from app.core.backend import stocktake

    alerts = []
    plan = stocktake.schedule(session, org_id, settings, today)
    if plan["next_due"]:
        due = date.fromisoformat(plan["next_due"])
        if today >= due - timedelta(days=STOCKTAKE_REMIND_DAYS):
            alerts.append(
                {
                    "id": f"stocktake-due-{plan['next_due']}",
                    "title": f"Stocktake due {due.strftime('%-d %b %Y')}",
                    "description": (
                        f"{'Overdue: ' if plan['overdue'] else ''}Count finished goods and work in progress "
                        f"({plan['frequency'].replace('_', '-')} schedule; Customs' minimum is once a year)."
                    ),
                    "due_date": plan["next_due"],
                    "href": "/core/stocktake",
                    "action_label": "Start stocktake",
                    "overdue": plan["overdue"],
                }
            )
    for v in stocktake.open_variances(session, org_id, today):
        sign = "" if v["variance"].startswith("-") else "+"
        lal, duty = (v["measure"] or "").lstrip("-"), (v["cost"] or "").lstrip("-")
        money = (f", {lal} LAL" + (f", ${duty} duty" if duty else "")) if lal else ""
        what = (
            f"under investigation until {v['investigate_until']}" if v["status"] == "investigating" else "not resolved"
        )
        alerts.append(
            {
                "id": f"stocktake-variance-{v['line_id']}",
                "title": f"Stocktake variance: {v['product']} {sign}{v['variance']} {v['unit']}",
                "description": f"Counted {v['counted_on']} (batch {v['batch'] or 'n/a'}{money}), {what}.",
                "due_date": v["investigate_until"] or v["counted_on"],
                "href": f"/core/stocktake?id={v['stocktake_id']}",
                "action_label": "Resolve",
                "overdue": v["overdue"] or v["status"] == "open",
            }
        )
    return alerts


def run_stocktake_check(org_id: UUID, session: Session) -> CheckResult:
    profile = ComplianceService(session).get_profile(org_id)
    if profile is None or not profile.enabled:
        return CheckResult(check_id=STOCKTAKE_CHECK_ID, flagged=False, data={})
    alerts = stocktake_alerts(session, org_id, profile.settings or {}, date.today())
    if not alerts:
        return CheckResult(check_id=STOCKTAKE_CHECK_ID, flagged=False, data={})
    for alert in alerts:
        alert.pop("overdue", None)
    return CheckResult(
        check_id=STOCKTAKE_CHECK_ID,
        flagged=True,
        message=alerts[0]["title"],
        data={
            "system_finding": {
                "category": "Customs stocktake",
                "action": {"href": "/core/stocktake", "label": "Open stocktake"},
                "details": alerts,
            },
            "system_alerts": alerts,
        },
    )


VERIFICATION_CHECK_ID = "compliant.nz_alcohol.verification"


def run_verification_check(org_id: UUID, session: Session) -> CheckResult:
    """Plan 2.2: the next verification coming due, and corrective actions due."""
    from app.features.compliant.modules.nz_alcohol import verification

    profile = ComplianceService(session).get_profile(org_id)
    if profile is None or not profile.enabled:
        return CheckResult(check_id=VERIFICATION_CHECK_ID, flagged=False, data={})
    alerts = verification.alerts_for_org(session, org_id, profile, date.today())
    if not alerts:
        return CheckResult(check_id=VERIFICATION_CHECK_ID, flagged=False, data={})
    return CheckResult(
        check_id=VERIFICATION_CHECK_ID,
        flagged=True,
        message=alerts[0]["title"],
        data={
            "system_finding": {
                "category": "Food safety verification",
                "action": {"href": "/compliant/nz-alcohol/food-safety#verification", "label": "Open verification"},
                "details": alerts,
            },
            "system_alerts": alerts,
        },
    )


LICENSING_CHECK_ID = "compliant.nz_alcohol.licensing"


def run_licensing_check(org_id: UUID, session: Session) -> CheckResult:
    """Plan 2.5: licence renewals, managers' certificates, annual fees, events and check reviews."""
    from app.features.compliant.modules.nz_alcohol import licensing

    profile = ComplianceService(session).get_profile(org_id)
    if profile is None or not profile.enabled:
        return CheckResult(check_id=LICENSING_CHECK_ID, flagged=False, data={})
    alerts = licensing.alerts(session, org_id, date.today())
    if not alerts:
        return CheckResult(check_id=LICENSING_CHECK_ID, flagged=False, data={})
    return CheckResult(
        check_id=LICENSING_CHECK_ID,
        flagged=True,
        message=alerts[0]["title"],
        data={
            "system_finding": {
                "category": "Alcohol licensing",
                "action": {"href": "/compliant/nz-alcohol/licensing", "label": "Open licensing"},
                "details": alerts,
            },
            "system_alerts": alerts,
        },
    )


def register_checks(runner) -> None:
    if config.compliant_enabled:
        runner.register_check(CHECK_ID, run_check)
        runner.register_check(EXCISE_CHECK_ID, run_excise_check)
        runner.register_check(STOCKTAKE_CHECK_ID, run_stocktake_check)
        runner.register_check(VERIFICATION_CHECK_ID, run_verification_check)
        runner.register_check(LICENSING_CHECK_ID, run_licensing_check)
