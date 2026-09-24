"""Generic workflow-rule contracts for pluggable Compliant modules.

Core owns execution state and evidence storage.  Compliant modules own the rules that
augment a workflow and describe their own failure copy.  This platform layer is the
composition seam: it normalises rules for Core without teaching Core about industries,
frameworks, or regulator programmes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class WorkflowConstraint:
    """A module-owned rule Core can enforce using an operational fact it owns."""

    requirement: str
    code: str
    message: str
    action: str
    # For ``prompt_value``: the execution-prompt label whose submitted value Core checks,
    # and optional inclusive numeric bounds. Unused by other requirement kinds.
    prompt_label: str | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None


@dataclass(frozen=True)
class WorkflowRule:
    """One module contribution to the execution UI and completion policy."""

    rule_id: str
    prompt: dict[str, Any] | None = None
    constraints: tuple[WorkflowConstraint, ...] = ()


class WorkflowRuleProvider(Protocol):
    """Contract implemented by each installed Compliant industry module.

    ``step_id`` is the step *definition* being executed, when the caller knows it. A
    module may return rules that apply only to particular steps (for example a field
    required on a workflow's final step); with no step it must return only rules that
    apply to every step.
    """

    def workflow_rules(
        self, session: Session, org_id: UUID, step_id: UUID | None = None
    ) -> tuple[WorkflowRule, ...]: ...


def _providers() -> tuple[WorkflowRuleProvider, ...]:
    """Explicit install-time composition; add an industry pack here, never in Core."""
    from app.features.compliant.modules.nz_alcohol.workflow_rules import NZAlcoholWorkflowRules

    return (NZAlcoholWorkflowRules(),)


def workflow_rules_for_org(session: Session, org_id: UUID, step_id: UUID | None = None) -> tuple[WorkflowRule, ...]:
    """Collect all applicable rule contributions for this tenant (and step, if known)."""
    return tuple(rule for provider in _providers() for rule in provider.workflow_rules(session, org_id, step_id))


def workflow_context(session: Session, org_id: UUID, step_id: UUID | None = None) -> dict[str, Any]:
    """Return a Core-safe UI projection; module rule internals remain server-side."""
    rules = workflow_rules_for_org(session, org_id, step_id)
    extensions = [
        {"rule_id": rule.rule_id, "prompt": rule.prompt}
        for rule in rules
        if isinstance(rule.prompt, dict) and rule.prompt.get("type")
    ]
    return {
        "enabled": bool(extensions),
        "extensions": extensions,
        # Kept as a generic empty-state contract for existing Core clients. Module copy
        # is carried only by an extension prompt, never hard-coded by Core.
        "label": "Compliance workflow extensions",
        "help": "Applicable compliance modules can add workflow evidence and constraints here.",
    }


def completion_constraints(
    session: Session, org_id: UUID, step_id: UUID | None = None
) -> tuple[WorkflowConstraint, ...]:
    """Return every applicable rule Core must check before completing a step."""
    return tuple(
        constraint for rule in workflow_rules_for_org(session, org_id, step_id) for constraint in rule.constraints
    )
