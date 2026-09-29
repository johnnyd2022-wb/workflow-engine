"""What NZ Alcohol preconfigures for a producer type's starter pack (plan 2.4c)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.features.compliant.modules.nz_alcohol.workflow_rules import ABV_RULES_SETTING, validate_abv_rules
from app.features.compliant.service import ComplianceService

PRODUCT_TYPES = ("spirits", "beer", "wine", "cider", "mead", "rtd", "other")


def apply_preset(session: Session, org_id: UUID, product_type: str, final_outputs: list[str]) -> list[str]:
    """Add the product type (so its frameworks apply) and require ABV on the final products.

    Never removes anything the org already configured, and changes nothing if Compliant
    isn't switched on.
    """
    if product_type not in PRODUCT_TYPES:
        raise ValueError(f"Unknown product type {product_type!r}")
    service = ComplianceService(session)
    profile = service.get_profile(org_id)
    if profile is None or not profile.enabled:
        return []
    settings = dict(profile.settings or {})
    changes = []
    types = list(settings.get("alcohol_product_types") or [])
    if product_type not in types:
        types.append(product_type)
        settings["alcohol_product_types"] = types
        changes.append(f"Added {product_type} to your product types")
    rules = list(settings.get(ABV_RULES_SETTING) or [])
    have = {(r["pattern"].strip().casefold(), r["match_type"]) for r in rules}
    for name in final_outputs:
        if (name.strip().casefold(), "exact") not in have:
            rules.append({"pattern": name, "match_type": "exact"})
            have.add((name.strip().casefold(), "exact"))
            changes.append(f"ABV is now required on “{name}”")
    error = validate_abv_rules(rules)
    if error:
        raise ValueError(error)
    settings[ABV_RULES_SETTING] = rules
    if changes:
        service.upsert_profile(org_id, {"settings": settings})
    return changes
