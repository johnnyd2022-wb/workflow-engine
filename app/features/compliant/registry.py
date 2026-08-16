"""Trusted, install-time registration for Compliant modules."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.corechecks import CheckResult
from app.features.compliant.service import ComplianceService
from app.utils.config_loader import config

CHECK_ID = "compliant.nz_alcohol"


def run_nz_alcohol_check(org_id: UUID, session: Session) -> CheckResult:
    frameworks = ComplianceService(session).evaluate(org_id)
    attention = [framework for framework in frameworks if framework["state"] == "attention"]
    if not frameworks:
        return CheckResult(check_id=CHECK_ID, flagged=False, data={"frameworks": []})
    message = None
    if attention:
        message = f"{len(attention)} NZ Alcohol compliance framework(s) need attention"
    return CheckResult(check_id=CHECK_ID, flagged=bool(attention), message=message, data={"frameworks": frameworks})


def register_compliant_checks(runner) -> None:
    """Register enabled product checks without leaking module IDs into core."""
    if config.compliant_enabled:
        runner.register_check(CHECK_ID, run_nz_alcohol_check)
