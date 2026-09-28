"""Module-owned decisions for trusted Core stock-movement contexts.

Core constructs the context from locked stock and transfer records, enforces the
returned decision before changing quantities, and persists the evidence atomically.
Neither this seam nor a module commits the caller's transaction.
"""

from dataclasses import dataclass
from typing import Protocol

from app.features.compliant.models.compliance_profile import ComplianceProfile


@dataclass(frozen=True)
class MovementDecision:
    allowed: bool
    reason: str
    # JSON text is immutable and suitable for an append-only movement snapshot.
    evidence: str = "{}"


class MovementPolicyProvider(Protocol):
    module_id: str

    def evaluate(self, session, org_id, context) -> MovementDecision: ...


def _providers():
    from app.features.compliant.modules.nz_alcohol.stock_movements import NZAlcoholMovementPolicy

    return (NZAlcoholMovementPolicy(),)


def evaluate_stock_movement(session, org_id, context) -> MovementDecision:
    """Evaluate a server-built context; configured but unsupported modules deny."""
    profile = session.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).one_or_none()
    if profile is None or not profile.enabled:
        return MovementDecision(True, "No applicable compliance module")
    provider = next((p for p in _providers() if p.module_id == profile.industry_module), None)
    if provider is None:
        return MovementDecision(False, "The configured compliance module has no stock movement policy")
    return provider.evaluate(session, org_id, context)
