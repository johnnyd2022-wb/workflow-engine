"""National programmes 1 and 2 alongside NP3 (plan 2.4b).

MPI's national programme guidance (December 2025, version 2) is written as the same set
of cards for every programme: Setup, Day jobs, Producing/processing/handling and
Troubleshooting, each with Know / Do / Show. NP2 adds process-control cards (cooking or
pasteurising, defrosting and reheating, water activity, pickling/fermenting/acidifying).
NP3 organisations use the topic list from their verifier's confirmation instead
(``np3_audit.NP3_AUDIT_CATEGORIES``).

Each card maps to the same check ids the NP3 workspace already uses, so the evidence
playbooks, logs, training register and evidence register work unchanged.

Who uses which programme (MPI): NP1 is for storing or transporting food only, or selling
only packaged shelf-stable food (e.g. a cellar door or warehouse that doesn't make
anything); NP2 adds selling chilled or frozen food; brewing, distilling and making
alcoholic beverages is NP3.
"""

from __future__ import annotations

PROGRAMMES = ("np1", "np2", "np3")

GUIDANCE = {
    "np1": {
        "label": "National Programme 1",
        "short": "NP1",
        "version": "2025-v2",
        "url": "https://www.mpi.govt.nz/dmsdocument/21847/direct",
    },
    "np2": {
        "label": "National Programme 2",
        "short": "NP2",
        "version": "2025-v2",
        "url": "https://www.mpi.govt.nz/dmsdocument/21850/direct",
    },
    "np3": {
        "label": "National Programme 3",
        "short": "NP3",
        "version": "2025-v2",
        "url": "https://www.mpi.govt.nz/dmsdocument/21853/direct",
    },
}

_SETUP = (
    "Setup",
    (
        ("registration-scope", "Taking responsibility: registration and scope"),
        ("delegation", "Taking responsibility: who does what"),
        ("operator-verification", "Checking the programme is working well"),
        ("premises-services", "Managing places and equipment"),
        ("water-supply", "Ensuring your water is suitable"),
        ("staff-competency", "Ensuring staff are trained and competent"),
    ),
)
_DAY_JOBS = (
    "Day jobs",
    (
        ("cleaning-and-hygiene", "Cleaning and sanitising"),
        ("pest-animal-control", "Controlling pests"),
        ("maintenance", "Maintaining equipment and facilities"),
        ("personal-hygiene", "Managing personal hygiene"),
        ("health-and-sickness", "Managing health and sickness"),
    ),
)
_HANDLING_COMMON = (
    ("suppliers-and-purchasing", "Sourcing food"),
    ("receiving-food", "Receiving food"),
    ("trace-and-recall", "Tracing food"),
    ("storage-stock-rotation", "Safe storage and display"),
    ("allergen-management", "Allergens and knowing what is in your food"),
    ("cross-contamination", "Preventing contamination of food"),
    ("physical-hazards", "Keeping foreign matter out of food"),
    ("food-labelling-advertising", "Packaging and labelling your food"),
    ("transporting-food", "Transporting food"),
)
_NP2_PROCESS = (
    ("manufacturing-process-description", "Producing, processing or handling food"),
    ("display-temperature", "Chilled and frozen food on display"),
    ("time-temperature-processing", "Thoroughly cooking or pasteurising food"),
    ("defrosting-reheating", "Defrosting and reheating food safely"),
    ("water-activity-control", "Using water activity to control bugs"),
    ("acidification-fermentation-control", "Pickling, fermenting or acidifying food"),
)
_TROUBLESHOOTING = (
    "Troubleshooting",
    (
        ("corrective-actions", "Taking action when something goes wrong"),
        ("unsafe-unsuitable-food", "Managing unsafe or unsuitable food"),
        ("recall-policy", "Recalling your food"),
    ),
)

NP1_AUDIT_CATEGORIES = (
    _SETUP,
    _DAY_JOBS,
    (
        "Producing, processing or handling",
        (("manufacturing-process-description", "Producing, processing or handling food"),) + _HANDLING_COMMON,
    ),
    _TROUBLESHOOTING,
)
NP2_AUDIT_CATEGORIES = (
    _SETUP,
    _DAY_JOBS,
    ("Producing, processing or handling", _NP2_PROCESS[:2] + _HANDLING_COMMON + _NP2_PROCESS[2:]),
    _TROUBLESHOOTING,
)


def framework_slug(programme: str) -> str:
    return f"{programme}-food-control"


def topic_ids(categories) -> list[str]:
    seen: list[str] = []
    for _category, topics in categories:
        for control_id, _title in topics:
            if control_id not in seen:
                seen.append(control_id)
    return seen
