"""Wine records captured as part of production (plan §3.2).

The winemaker records the step they were already going to record; the fields the Wine Act
trace and the label checks depend on appear on it, with sensible defaults so most are a tap.
Only intake blocks completion: grower, variety and vintage are what every later check reads
back through the trace. Everything else is captured but never stops a cellar or bottling run;
gaps surface on the Wine page instead.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from app.features.compliant.platform.workflow_rules import WorkflowConstraint, WorkflowRule

from . import roles

# Prompt labels double as the execution_data keys Core stores values under, and the keys
# composition.py and label.py read back. Change them only with a data migration.
GROWER: Final = "Grower or block"
VARIETY: Final = "Variety"
VINTAGE: Final = "Vintage"
REGION: Final = "Region"
SPRAY_DIARY: Final = "Spray diary received"
SO2_ADDED: Final = "SO2 added"
FINING: Final = "Fining agent"
BOTTLE_SIZE: Final = "Bottle size"

VARIETIES: Final = (
    "Sauvignon blanc", "Pinot noir", "Chardonnay", "Pinot gris", "Riesling", "Merlot", "Syrah",
    "Gewürztraminer", "Cabernet Sauvignon", "Albariño", "Grüner Veltliner", "Chenin blanc",
    "Malbec", "Viognier", "Other",
)  # fmt: skip
# Registered NZ wine geographical indications (IPONZ), broadest last. A region on intake is a
# record of where the grapes grew; whether a label may use it is the claim check's job.
REGIONS: Final = (
    "Marlborough", "Central Otago", "Hawke's Bay", "Central Hawke's Bay", "Gisborne", "Nelson",
    "Wairarapa", "Martinborough", "Gladstone", "North Canterbury", "Waipara Valley", "Canterbury",
    "Waitaki Valley North Otago", "Auckland", "Matakana", "Kumeu", "Waiheke Island", "Northland",
    "New Zealand",
)  # fmt: skip
FINING_AGENTS: Final = ("None", "Egg (albumin)", "Milk (casein)", "Fish (isinglass)", "Bentonite", "Other")


def current_vintage(today: date | None = None) -> int:
    """NZ harvest runs Feb-May, so from February the vintage is this calendar year."""
    today = today or date.today()
    return today.year if today.month >= 2 else today.year - 1


def _required(label: str, message: str, action: str) -> WorkflowConstraint:
    return WorkflowConstraint(
        requirement="prompt_value",
        code="compliance_requirement_not_met",
        message=message,
        action=action,
        prompt_label=label,
    )


def _rule(key: str, prompt: dict, *constraints: WorkflowConstraint) -> WorkflowRule:
    return WorkflowRule(rule_id=f"nz-alcohol.wine.{key}", prompt=prompt, constraints=constraints)


def _intake_rules() -> tuple[WorkflowRule, ...]:
    trace = "Needed to trace this wine back to its grapes and to check label claims."
    return (
        _rule(
            "intake.grower",
            {"type": "text", "label": GROWER, "required": True, "help": "Who grew it, or which of your blocks."},
            _required(GROWER, f"{GROWER} is required for wine traceability.", "Enter the grower or vineyard block."),
        ),
        _rule(
            "intake.variety",
            {"type": "select", "label": VARIETY, "required": True, "options": list(VARIETIES), "help": trace},
            _required(VARIETY, f"{VARIETY} is required for wine traceability.", "Choose the grape variety."),
        ),
        _rule(
            "intake.vintage",
            {
                "type": "number",
                "label": VINTAGE,
                "required": True,
                "min": 1990,
                "max": current_vintage() + 1,
                "default": current_vintage(),
                "help": trace,
            },
            WorkflowConstraint(
                requirement="prompt_value",
                code="compliance_requirement_not_met",
                message=f"{VINTAGE} is required for wine traceability.",
                action="Enter the harvest year.",
                prompt_label=VINTAGE,
                minimum=Decimal(1990),
                maximum=Decimal(current_vintage() + 1),
            ),
        ),
        _rule(
            "intake.region",
            {
                "type": "select",
                "label": REGION,
                "required": False,
                "options": list(REGIONS),
                "help": "Where the grapes grew. Used for regional label claims.",
            },
        ),
        _rule(
            "intake.spray-diary",
            {
                "type": "select",
                "label": SPRAY_DIARY,
                "required": False,
                "options": ["Yes", "No", "Own block (on file)"],
                "help": "The grower's spray and withholding record for this fruit.",
            },
        ),
    )


def _cellar_rules() -> tuple[WorkflowRule, ...]:
    return (
        _rule(
            "cellar.so2",
            {
                "type": "number",
                "label": SO2_ADDED,
                "unit": "mg/L",
                "required": False,
                "min": 0,
                "max": 400,
                "help": "Sulphite added at this step. 10 mg/L or more means the label must declare sulphites.",
            },
        ),
        _rule(
            "cellar.fining",
            {
                "type": "select",
                "label": FINING,
                "required": False,
                "options": list(FINING_AGENTS),
                "default": "None",
                "help": "Egg, milk or fish fining may need an allergen statement on the label.",
            },
        ),
    )


def _bottle_rules() -> tuple[WorkflowRule, ...]:
    from app.features.compliant.modules.nz_alcohol.workflow_rules import _abv_rule

    return (
        _abv_rule(),
        _rule(
            "bottle.size",
            {
                "type": "number",
                "label": BOTTLE_SIZE,
                "unit": "mL",
                "required": True,
                "min": 1,
                "max": 30000,
                "default": 750,
                "help": "Used to work out standard drinks for the label.",
            },
        ),
    )


_BY_ROLE = {
    "intake": _intake_rules,
    "cellar": _cellar_rules,
    "blend": _cellar_rules,
    "bottle": _bottle_rules,
}


def wine_enabled(settings: dict | None) -> bool:
    return "wine" in ((settings or {}).get("alcohol_product_types") or [])


def rules_for_step(
    session: Session, org_id: UUID, settings: dict | None, step_id: UUID | None
) -> tuple[WorkflowRule, ...]:
    if step_id is None or not wine_enabled(settings):
        return ()
    role = roles.role_for_step(session, org_id, step_id, settings)
    factory = _BY_ROLE.get(role or "")
    return factory() if factory else ()
