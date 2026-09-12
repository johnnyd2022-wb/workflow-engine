"""Install-time registration for the NZ Alcohol module."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.corechecks import CheckResult
from app.features.compliant.service import ComplianceService
from app.utils.config_loader import config

CHECK_ID = "compliant.nz_alcohol"


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
        if (profile.settings or {}).get("food_control_programme", "np3") == "np3"
        else {"work_queue": [], "health": {}}
    )
    queue = np3_audit["work_queue"]
    critical_actions = [action for action in queue if action["severity"] in {"attention", "overdue"}]
    training_actions = [action for action in queue if action["kind"] == "staff-training"]
    if training_actions:
        message = f"{len(training_actions)} active staff member(s) need NP3 training and competency records"
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
        flagged=bool(attention or queue),
        message=message,
        data={
            "frameworks": frameworks,
            "attention_controls": attention_controls,
            "np3_health": np3_audit["health"],
            "np3_work_queue": queue,
        },
    )


def register_checks(runner) -> None:
    if config.compliant_enabled:
        runner.register_check(CHECK_ID, run_check)
