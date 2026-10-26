"""NZ Alcohol's step on the Getting started path (GL-P09): tell Compliance what you make.

Registered with Core's guide by the Compliance blueprint; applies only to an org running the
NZ Alcohol module, and is done once the profile names its alcohol product types.
"""

from __future__ import annotations

from uuid import UUID

from app.core.backend.getting_started import ProvidedStep


def what_you_make(session, org_id: UUID) -> ProvidedStep | None:
    from app.features.compliant.service import ComplianceService, nz_alcohol_active

    if not nz_alcohol_active(session, org_id):
        return None
    profile = ComplianceService(session).get_profile(org_id)
    types = ((profile.settings if profile else None) or {}).get("alcohol_product_types") or []
    return ProvidedStep(
        key="business",
        group="Your business",
        title="Tell us what you make",
        why="Gin, beer, wine or more: it decides which rules and records Compliance shows you.",
        href="/compliant/nz-alcohol",
        action="Choose your products",
        done=bool(types),
        fact=", ".join(str(t).replace("_", " ") for t in types[:3]) or None,
    )
