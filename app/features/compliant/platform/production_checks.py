"""What a compliance module needs in place before production starts at a site (GL-P07 B4).

The planner's start check asks this before a planned batch becomes an execution. The installed
module answers with plain-words reasons, one per missing thing; none means it has nothing to
stop. Core never names a module: with no compliance profile, or a module without production
checks, there is nothing to stop.
"""

from datetime import date
from typing import Protocol

from app.features.compliant.models.compliance_profile import ComplianceProfile


class ProductionChecks(Protocol):
    module_id: str

    def start_blockers(self, session, org_id, site, on: date) -> list[str]: ...


def _providers():
    from app.features.compliant.modules.nz_alcohol.production_checks import NZAlcoholProductionChecks

    return (NZAlcoholProductionChecks(),)


def start_blockers(session, org_id, site, on: date) -> list[str]:
    """Reasons production can't start at ``site`` (a Site row, or None) on ``on``."""
    profile = session.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).one_or_none()
    if profile is None or not profile.enabled:
        return []
    provider = next((p for p in _providers() if p.module_id == profile.industry_module), None)
    if provider is None:
        return []
    return list(provider.start_blockers(session, org_id, site, on))
