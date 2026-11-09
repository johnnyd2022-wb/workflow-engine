"""What a production step is in winemaking, without asking the winemaker.

A step's role decides which wine records it captures (rules.py) and how composition is read
back through the trace (composition.py). Roles are inferred from names the winemaker already
typed -- the process, the step and its outputs -- so switching wine on needs no setup. The
operator can correct an inference per step in configuration (`wine_step_roles`), and that
override always wins. No column on `steps`: Core stays industry-agnostic.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.process import Process
from app.core.db.models.step import Step

ROLES: Final = ("intake", "crush", "ferment", "blend", "cellar", "bottle")
ROLE_LABELS: Final = {
    "intake": "Grape intake",
    "crush": "Crush and press",
    "ferment": "Ferment",
    "blend": "Blend",
    "cellar": "Cellar",
    "bottle": "Bottle",
}
OVERRIDE_SETTING: Final = "wine_step_roles"  # {step_id: role | "none"}

# A process is winemaking when anything in it names grapes, must or wine. Checked on the
# process name, its step names and its output names, so "Pinot 2026" with a "Grape intake"
# step counts, while a gin "Bottling" process does not.
_WINE_WORDS = re.compile(r"\b(grapes?|must|wines?|vintage|vineyard|crush)\b", re.I)

# First match wins; blend is checked before cellar so "Racking, blending or stabilisation"
# reads as a blend (it still gets the cellar fields, see rules.py).
_ROLE_PATTERNS: Final = (
    ("intake", re.compile(r"\b(intake|harvest|grape (?:delivery|receipt)|receive grapes?|pick(?:ing)?)\b", re.I)),
    ("crush", re.compile(r"\b(crush|press(?:ing)?|destem)", re.I)),
    ("ferment", re.compile(r"\bferment", re.I)),
    ("blend", re.compile(r"\bblend", re.I)),
    ("bottle", re.compile(r"\b(bottl|packag|fill(?:ing)?\b|canning|kegging)", re.I)),
    ("cellar", re.compile(r"\b(cellar|rack|stabili|fining|filter|barrel|matur|age(?:ing)?\b|ageing)", re.I)),
)


def _names(step: Step) -> list[str]:
    names = [step.name or ""]
    names += [str(o.get("name") or "") for o in (step.outputs or []) if isinstance(o, dict)]
    return names


def is_wine_process(process_name: str, steps: Iterable[Step]) -> bool:
    if _WINE_WORDS.search(process_name or ""):
        return True
    return any(_WINE_WORDS.search(name) for step in steps for name in _names(step))


def infer_role(step: Step) -> str | None:
    """Role from the step's own name first, then its outputs ("Grape lot" -> intake)."""
    for text in (step.name or "", " ".join(_names(step)[1:])):
        for role, pattern in _ROLE_PATTERNS:
            if pattern.search(text):
                return role
    if any(re.search(r"\bgrape lot\b", name, re.I) for name in _names(step)):
        return "intake"
    return None


def role_for_step(session: Session, org_id: UUID, step_id: UUID, settings: dict | None) -> str | None:
    """The wine role of one step definition, or None when it isn't a winemaking step."""
    override = ((settings or {}).get(OVERRIDE_SETTING) or {}).get(str(step_id))
    if override in ROLES:
        return override
    if override == "none":
        return None
    step = session.query(Step).filter(Step.org_id == org_id, Step.id == step_id).one_or_none()
    if step is None:
        return None
    process = session.query(Process).filter(Process.org_id == org_id, Process.id == step.process_id).one_or_none()
    siblings = session.query(Step).filter(Step.org_id == org_id, Step.process_id == step.process_id).all()
    if not is_wine_process(process.name if process else "", siblings):
        return None
    return infer_role(step)


def roles_for_org(session: Session, org_id: UUID, settings: dict | None) -> dict[UUID, str]:
    """Every winemaking step's role, for reading the trace back without a query per step."""
    overrides = (settings or {}).get(OVERRIDE_SETTING) or {}
    steps = session.query(Step).filter(Step.org_id == org_id).all()
    by_process: dict[UUID, list[Step]] = {}
    for step in steps:
        by_process.setdefault(step.process_id, []).append(step)
    names = dict(session.query(Process.id, Process.name).filter(Process.org_id == org_id).all())
    out: dict[UUID, str] = {}
    for process_id, members in by_process.items():
        wine = is_wine_process(names.get(process_id, ""), members)
        for step in members:
            override = overrides.get(str(step.id))
            if override in ROLES:
                out[step.id] = override
            elif override != "none" and wine:
                role = infer_role(step)
                if role:
                    out[step.id] = role
    return out
