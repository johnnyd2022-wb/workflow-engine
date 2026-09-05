"""Install-time registration for the NZ Alcohol module."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.corechecks import CheckResult
from app.features.compliant.service import ComplianceService
from app.utils.config_loader import config

CHECK_ID = "compliant.nz_alcohol"


def run_check(org_id: UUID, session: Session) -> CheckResult:
    frameworks = ComplianceService(session).evaluate(org_id)
    attention = [framework for framework in frameworks if framework["state"] == "attention"]
    if not frameworks:
        return CheckResult(check_id=CHECK_ID, flagged=False, data={"frameworks": []})
    message = None
    attention_controls = [
        control for framework in attention for control in framework["controls"] if control["state"] == "attention"
    ]
    training_controls = {"staff-competency", "certified-manager"}
    if any(control["control_id"] in training_controls for control in attention_controls):
        message = "NZ Alcohol staff training or competency evidence needs attention"
    elif attention:
        message = f"{len(attention)} NZ Alcohol compliance framework(s) need attention"
    return CheckResult(
        check_id=CHECK_ID,
        flagged=bool(attention),
        message=message,
        data={"frameworks": frameworks, "attention_controls": attention_controls},
    )


def register_checks(runner) -> None:
    if config.compliant_enabled:
        runner.register_check(CHECK_ID, run_check)
