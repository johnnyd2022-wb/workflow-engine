"""NZ Alcohol workflow rules contributed to Core through the Compliant platform."""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from app.features.compliant.models import ComplianceProfile
from app.features.compliant.platform.workflow_rules import WorkflowConstraint, WorkflowRule

_CAPTURE_MODES: Final = {"off", "recommended", "required"}
_NP3_EVIDENCE_RULE_ID: Final = "nz-alcohol.np3.execution-evidence"
_NZ_ALCOHOL_EVIDENCE_RULE_ID: Final = "nz-alcohol.execution-evidence"


def validate_workflow_settings(settings: dict) -> str | None:
    """Validate settings owned by this module at the generic profile write boundary."""
    mode = settings.get("np3_execution_evidence_mode")
    if mode is not None and mode not in _CAPTURE_MODES:
        return "np3_execution_evidence_mode must be off, recommended, or required"
    return None


def rules_for_profile(profile: ComplianceProfile | None) -> tuple[WorkflowRule, ...]:
    """Map NZ Alcohol configuration to generic workflow rules.

    The returned ``active_evidence`` constraint has no NP3 behaviour embedded in Core:
    Core simply verifies the active evidence fact for whatever module supplied it.
    """
    if profile is None or not profile.enabled:
        return ()
    settings = profile.settings or {}
    is_np3 = settings.get("food_control_programme", "np3") == "np3"
    mode = settings.get("np3_execution_evidence_mode", "recommended") if is_np3 else "recommended"
    if mode not in _CAPTURE_MODES:
        mode = "recommended"
    if is_np3 and mode == "off":
        return ()

    if is_np3:
        required = mode == "required"
        help_text = (
            "An active photo or PDF is required before this Core step can be completed under your NP3 policy."
            if required
            else "Upload a photo or PDF against this Core step. It will be linked to the NP3 evidence register."
        )
        constraints = (
            WorkflowConstraint(
                requirement="active_evidence",
                code="compliance_requirement_not_met",
                message="An active evidence file is required before completing this step.",
                action="Upload a photo or PDF in the NP3 operational evidence section.",
            ),
        ) if required else ()
        return (
            WorkflowRule(
                rule_id=_NP3_EVIDENCE_RULE_ID,
                prompt={
                    "type": "evidence",
                    "label": "NP3 operational evidence",
                    "required": required,
                    "help": help_text,
                },
                constraints=constraints,
            ),
        )

    return (
        WorkflowRule(
            rule_id=_NZ_ALCOHOL_EVIDENCE_RULE_ID,
            prompt={
                "type": "evidence",
                "label": "Compliance evidence",
                "required": False,
                "help": "Upload a photo or PDF against this Core step to retain it with your operational evidence.",
            },
        ),
    )


class NZAlcoholWorkflowRules:
    """Provider registered by the Compliant platform, not by Core."""

    def workflow_rules(self, session: Session, org_id: UUID) -> tuple[WorkflowRule, ...]:
        profile = session.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).one_or_none()
        return rules_for_profile(profile)
