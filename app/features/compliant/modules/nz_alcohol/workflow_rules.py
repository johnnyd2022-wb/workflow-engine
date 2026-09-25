"""NZ Alcohol workflow rules contributed to Core through the Compliant platform."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.process import Process
from app.core.db.models.step import Step
from app.features.compliant.models import ComplianceProfile
from app.features.compliant.platform.workflow_rules import WorkflowConstraint, WorkflowRule

_CAPTURE_MODES: Final = {"off", "recommended", "required"}
_NP3_EVIDENCE_RULE_ID: Final = "nz-alcohol.np3.execution-evidence"
_NZ_ALCOHOL_EVIDENCE_RULE_ID: Final = "nz-alcohol.execution-evidence"

# ABV on alcohol products: the operator says which workflows produce an alcohol product
# by matching the final step's output names -- the same phrase + exact/contains,
# case-insensitive rule shape the CRM uses to map Xero items to products, so a broad
# "contains" phrase also covers workflows created later. A matched final step gets a
# required ABV field, enforced by Core at completion.
ABV_RULES_SETTING: Final = "abv_product_rules"
ABV_MATCH_TYPES: Final = ("exact", "contains")
ABV_PROMPT_LABEL: Final = "ABV (%)"
_ABV_RULE_ID: Final = "nz-alcohol.abv-required"
_ABV_MAX_RULES: Final = 100


def validate_abv_rules(rules: Any) -> str | None:
    if not isinstance(rules, list):
        return f"{ABV_RULES_SETTING} must be a list"
    if len(rules) > _ABV_MAX_RULES:
        return f"{ABV_RULES_SETTING} can hold at most {_ABV_MAX_RULES} rules"
    seen: set[tuple[str, str]] = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) - {"pattern", "match_type"}:
            return f"each {ABV_RULES_SETTING} entry must be an object with pattern and match_type"
        pattern = rule.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip() or len(pattern) > 255:
            return f"{ABV_RULES_SETTING} pattern must be 1-255 characters"
        if rule.get("match_type") not in ABV_MATCH_TYPES:
            return f"{ABV_RULES_SETTING} match_type must be exact or contains"
        key = (pattern.strip().casefold(), rule["match_type"])
        if key in seen:
            return f"{ABV_RULES_SETTING} has a duplicate rule: {rule['match_type']} {pattern.strip()!r}"
        seen.add(key)
    return None


def validate_workflow_settings(settings: dict) -> str | None:
    """Validate settings owned by this module at the generic profile write boundary."""
    mode = settings.get("np3_execution_evidence_mode")
    if mode is not None and mode not in _CAPTURE_MODES:
        return "np3_execution_evidence_mode must be off, recommended, or required"
    if ABV_RULES_SETTING in settings:
        return validate_abv_rules(settings[ABV_RULES_SETTING])
    return None


def matching_abv_rule(output_name: str, rules: list[dict]) -> dict | None:
    """The first rule matching this output name, case-insensitively; exact beats contains."""
    name = (output_name or "").strip().casefold()
    if not name:
        return None
    exact = next(
        (rule for rule in rules if rule["match_type"] == "exact" and rule["pattern"].strip().casefold() == name),
        None,
    )
    if exact is not None:
        return exact
    return next(
        (rule for rule in rules if rule["match_type"] == "contains" and rule["pattern"].strip().casefold() in name),
        None,
    )


def _output_names(step: Step) -> list[str]:
    return [str(output.get("name") or "").strip() for output in (step.outputs or []) if isinstance(output, dict)]


def terminal_steps(session: Session, org_id: UUID) -> list[tuple[Process, Step]]:
    """Every workflow's final step, in the order executions run them (position)."""
    steps = (
        session.query(Step)
        .filter(Step.org_id == org_id)
        .order_by(Step.process_id, Step.position.desc(), Step.step_number.desc())
        .all()
    )
    last_by_process: dict[UUID, Step] = {}
    for step in steps:
        last_by_process.setdefault(step.process_id, step)
    if not last_by_process:
        return []
    processes = {
        process.id: process
        for process in session.query(Process)
        .filter(Process.org_id == org_id, Process.id.in_(list(last_by_process)))
        .all()
    }
    return sorted(
        ((processes[pid], step) for pid, step in last_by_process.items() if pid in processes),
        key=lambda pair: (pair[0].name.casefold(), str(pair[0].id)),
    )


def _abv_required_for_step(session: Session, org_id: UUID, step_id: UUID, rules: list[dict]) -> bool:
    step = session.query(Step).filter(Step.org_id == org_id, Step.id == step_id).one_or_none()
    if step is None:
        return False
    later = (
        session.query(Step.id)
        .filter(
            Step.org_id == org_id,
            Step.process_id == step.process_id,
            Step.id != step.id,
            (Step.position > step.position)
            | ((Step.position == step.position) & (Step.step_number > step.step_number)),
        )
        .first()
    )
    if later is not None:
        return False
    return any(matching_abv_rule(name, rules) for name in _output_names(step))


def _abv_rule() -> WorkflowRule:
    return WorkflowRule(
        rule_id=_ABV_RULE_ID,
        prompt={
            "type": "number",
            "label": ABV_PROMPT_LABEL,
            "required": True,
            "min": 0,
            "max": 100,
            "help": "Alcohol by volume of this batch, as it will be labelled. Required because this "
            "workflow's final product is mapped as an alcohol product in NZ Alcohol configuration.",
        },
        constraints=(
            WorkflowConstraint(
                requirement="prompt_value",
                code="compliance_requirement_not_met",
                message=f"{ABV_PROMPT_LABEL} is required to complete this step.",
                action="Enter the batch's ABV as a percentage between 0 and 100.",
                prompt_label=ABV_PROMPT_LABEL,
                minimum=Decimal("0"),
                maximum=Decimal("100"),
            ),
        ),
    )


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


def step_rules_for_profile(
    session: Session, org_id: UUID, profile: ComplianceProfile | None, step_id: UUID | None
) -> tuple[WorkflowRule, ...]:
    """Rules that apply only to particular steps -- today, ABV on a mapped final step.

    Independent of the NP3 evidence mode: turning the evidence shelf off must not stop an
    alcohol product's ABV being recorded.
    """
    if step_id is None or profile is None or not profile.enabled:
        return ()
    rules = (profile.settings or {}).get(ABV_RULES_SETTING) or []
    if not rules or validate_abv_rules(rules) is not None:
        return ()
    return (_abv_rule(),) if _abv_required_for_step(session, org_id, step_id, rules) else ()


class NZAlcoholWorkflowRules:
    """Provider registered by the Compliant platform, not by Core."""

    def workflow_rules(self, session: Session, org_id: UUID, step_id: UUID | None = None) -> tuple[WorkflowRule, ...]:
        profile = session.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).one_or_none()
        return rules_for_profile(profile) + step_rules_for_profile(session, org_id, profile, step_id)
