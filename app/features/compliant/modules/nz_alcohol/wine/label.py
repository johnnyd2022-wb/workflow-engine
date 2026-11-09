"""Bottling pre-flight: what this lot's label has to say, from what production recorded.

Each item is a fact the label depends on, worked out rather than typed: standard drinks from
ABV and bottle size, a sulphite statement from the SO2 added in the cellar, allergen
statements from the fining agents used, and the 85% claims from the trace. It checks what can
be checked; it doesn't review artwork, and it says "review" rather than inventing a pass.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from . import composition as comp_mod
from . import rules

SULPHITE_THRESHOLD_MG_PER_L: Final = Decimal(10)  # FSANZ Standard 1.2.3: added sulphites >= 10 mg/kg
PREGNANCY_WARNING_ABV: Final = Decimal("1.15")  # FSANZ: packaged alcohol for retail above 1.15% ABV
ETHANOL_DENSITY: Final = Decimal("0.789")


def standard_drinks(volume_ml: Decimal, abv: Decimal) -> Decimal:
    """NZ standard drink = 10 g ethanol: mL x ABV% / 100 x 0.789 / 10, to one decimal."""
    return (volume_ml * abv / 100 * ETHANOL_DENSITY / 10).quantize(Decimal("0.1"))


def _item(key: str, label: str, status: str, detail: str) -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail}


def preflight(bottle_data: dict, comp: comp_mod.Composition | None) -> dict:
    """Statuses: ok (nothing to do), declare (must be on the label), review, missing."""
    from app.features.compliant.modules.nz_alcohol.workflow_rules import ABV_PROMPT_LABEL

    abv = comp_mod._num(bottle_data.get(ABV_PROMPT_LABEL))
    size = comp_mod._num(bottle_data.get(rules.BOTTLE_SIZE))
    items = []
    if abv is None:
        items.append(_item("abv", "Alcohol content", "missing", "No ABV was recorded at bottling."))
    else:
        items.append(_item("abv", "Alcohol content", "declare", f"{abv.normalize():f}% ABV"))
    if abv is not None and size:
        drinks = standard_drinks(size, abv)
        items.append(
            _item(
                "standard-drinks",
                "Standard drinks",
                "declare",
                f"Approx. {drinks:f} standard drinks ({size.normalize():f} mL)",
            )
        )
    else:
        items.append(_item("standard-drinks", "Standard drinks", "missing", "Needs ABV and bottle size from bottling."))
    if abv is None or abv > PREGNANCY_WARNING_ABV:
        items.append(_item("pregnancy", "Pregnancy warning", "declare", "Required on packaged alcohol over 1.15% ABV."))

    if comp is None:
        items.append(
            _item("sulphites", "Sulphites", "review", "This lot doesn't trace back to recorded winemaking steps.")
        )
        items.append(_item("claims", "Variety, vintage and region", "review", "No intake records found for this lot."))
        return {"items": items, "status": _overall(items)}

    if comp.so2_mg_per_l >= SULPHITE_THRESHOLD_MG_PER_L:
        items.append(
            _item(
                "sulphites",
                "Sulphites",
                "declare",
                f"About {comp.so2_mg_per_l:.0f} mg/L added: declare “contains sulphites”.",
            )
        )
    else:
        items.append(
            _item(
                "sulphites",
                "Sulphites",
                "review",
                "Under 10 mg/L added was recorded. Check before leaving the statement off; most wine needs it.",
            )
        )
    allergens = sorted({comp_mod.ALLERGEN_FINING[f] for f in comp.fining if f in comp_mod.ALLERGEN_FINING})
    if allergens:
        items.append(
            _item(
                "allergens",
                "Allergens",
                "review",
                f"Fined with {', '.join(allergens)}: check whether the label must declare it.",
            )
        )
    claim = comp_mod.claims(comp)
    names = {"variety": "Variety", "vintage": "Vintage", "region": "Region"}
    for attr, result in claim.items():
        if result["status"] == "pass":
            text = f"May name {result['value']} ({result['share'] * 100:.0f}%)."
            status = "ok"
        elif result["status"] == "review":
            text = f"{result['value']} is {result['share'] * 100:.0f}%, but part of the trace is estimated or missing."
            status = "review"
        elif result["status"] == "fail":
            text = f"Top {attr} is {result['value']} at {result['share'] * 100:.0f}%: under 85%, so don't name a single {attr}."
            status = "review"
        else:
            text = f"No {attr} recorded at intake."
            status = "missing" if attr != "region" else "review"
        items.append(_item(f"claim-{attr}", f"{names[attr]} claim", status, text))
    return {"items": items, "status": _overall(items)}


def _overall(items: list[dict]) -> str:
    statuses = {i["status"] for i in items}
    return "missing" if "missing" in statuses else "review" if "review" in statuses else "ready"
