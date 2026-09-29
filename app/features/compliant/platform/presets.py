"""Product presets: what a compliance module preconfigures for a product type (plan 2.4c).

A starter pack creates a workflow, then asks here for the module's fields and checks for
that product type, for example an ABV field on the workflow's final product. The caller
passes only generic facts (a product type and the final output names); it never names an
industry.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session


def apply_product_preset(session: Session, org_id: UUID, product_type: str, final_outputs: list[str]) -> list[str]:
    """Preconfigure the installed module for a product type; returns what changed, in words."""
    from app.features.compliant.modules.nz_alcohol.presets import apply_preset

    return apply_preset(session, org_id, product_type, final_outputs)


def describe_checks(control_ids: list[str]) -> dict[str, Any]:
    """Titles for check ids, so a pack can link the checks that matter for its product type."""
    from app.features.compliant.modules.nz_alcohol.np3_audit import NP3_AUDIT_CATEGORIES

    titles: dict[str, str] = {}
    for _category, topics in NP3_AUDIT_CATEGORIES:
        for control_id, title in topics:
            titles.setdefault(control_id, title)
    return {cid: titles.get(cid) for cid in control_ids}
