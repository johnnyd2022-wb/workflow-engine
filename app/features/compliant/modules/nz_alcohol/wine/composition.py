"""What a wine lot is made of, read back through the trace (plan §3.3).

Nobody types a blend sheet. Every production step already records the lots and quantities
it consumed (`ExecutionStep.actual_inputs`), and intake steps record variety, vintage and
region (rules.py). Walking back from a lot and weighting each input by the quantity used
gives its composition, and with it the 85% label-claim check.

Also carried along the same walk, because the label needs them: sulphite added (mg/L,
volume-weighted through blends) and any allergenic fining agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem

from . import rules

CLAIM_THRESHOLD: Final = Decimal("0.85")  # Wine Regulations 2021; MPI label guide (vintage 2007 on)
CLAIM_SOURCE: Final = (
    "https://www.mpi.govt.nz/food-business/labelling-composition-food-drinks/specific-product-labelling/"
    "labelling-requirements-alcoholic-drinks-including-wine"
)
_MAX_DEPTH: Final = 25
ALLERGEN_FINING: Final = {"Egg (albumin)": "egg", "Milk (casein)": "milk", "Fish (isinglass)": "fish"}


def _num(value) -> Decimal | None:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() and number >= 0 else None


@dataclass
class Composition:
    variety: dict[str, Decimal] = field(default_factory=dict)
    vintage: dict[str, Decimal] = field(default_factory=dict)
    region: dict[str, Decimal] = field(default_factory=dict)
    growers: set[str] = field(default_factory=set)
    so2_mg_per_l: Decimal = Decimal(0)
    fining: set[str] = field(default_factory=set)
    estimated: bool = False  # inputs in different units were weighted equally
    unknown_share: Decimal = Decimal(0)  # share traced to no intake record

    def as_dict(self) -> dict:
        def shares(d):
            return [
                {"value": k, "share": float(round(v, 4))} for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))
            ]

        return {
            "variety": shares(self.variety),
            "vintage": shares(self.vintage),
            "region": shares(self.region),
            "growers": sorted(self.growers),
            "so2_mg_per_l": float(round(self.so2_mg_per_l, 1)),
            "fining": sorted(self.fining),
            "allergens": sorted({ALLERGEN_FINING[f] for f in self.fining if f in ALLERGEN_FINING}),
            "estimated": self.estimated,
            "unknown_share": float(round(self.unknown_share, 4)),
            "claims": claims(self),
        }


def _add(into: dict[str, Decimal], source: dict[str, Decimal], weight: Decimal) -> None:
    for key, share in source.items():
        into[key] = into.get(key, Decimal(0)) + share * weight


def claims(comp: Composition) -> dict:
    """The 85% rule per attribute: which single value (if any) the label may name."""
    out = {}
    for attr in ("variety", "vintage", "region"):
        shares = getattr(comp, attr)
        top = max(shares.items(), key=lambda kv: kv[1], default=None)
        if top is None:
            out[attr] = {"status": "unknown", "value": None, "share": 0.0}
            continue
        value, share = top
        status = "pass" if share >= CLAIM_THRESHOLD else "fail"
        if status == "pass" and (comp.estimated or comp.unknown_share > 0):
            status = "review"  # the maths passes, but part of the trace is weighted or missing
        out[attr] = {"status": status, "value": value, "share": float(round(share, 4))}
    return out


class _Walker:
    def __init__(self, session: Session, org_id: UUID, role_map: dict[UUID, str]):
        self.session, self.org_id, self.role_map = session, org_id, role_map
        self.memo: dict[UUID, Composition | None] = {}

    def lot(self, item_id: UUID, depth: int = 0) -> Composition | None:
        if item_id in self.memo:
            return self.memo[item_id]
        self.memo[item_id] = None  # cycle guard
        if depth > _MAX_DEPTH:
            return None
        item = (
            self.session.query(InventoryItem)
            .filter(InventoryItem.org_id == self.org_id, InventoryItem.id == item_id)
            .one_or_none()
        )
        if item is None or item.source_execution_step_id is None:
            return None
        step = (
            self.session.query(ExecutionStep)
            .filter(ExecutionStep.org_id == self.org_id, ExecutionStep.id == item.source_execution_step_id)
            .one_or_none()
        )
        result = self._step(step, depth) if step is not None else None
        self.memo[item_id] = result
        return result

    def _step(self, step: ExecutionStep, depth: int) -> Composition | None:
        role = self.role_map.get(step.step_id)
        data = step.execution_data or {}
        if role is None:
            return None  # not a winemaking step: yeast, packaging and the like add no composition
        if role == "intake":
            comp = Composition()
            for attr, label in (("variety", rules.VARIETY), ("vintage", rules.VINTAGE), ("region", rules.REGION)):
                value = str(data.get(label) or "").strip()
                if value.endswith(".0"):
                    value = value[:-2]  # a number prompt may come back as "2026.0"
                if value:
                    getattr(comp, attr)[value] = Decimal(1)
            grower = str(data.get(rules.GROWER) or "").strip()
            if grower:
                comp.growers.add(grower)
            if not comp.variety and not comp.vintage:
                comp.unknown_share = Decimal(1)
            return comp

        parts: list[tuple[Composition, Decimal | None, str]] = []
        for entry in step.actual_inputs or []:
            if not isinstance(entry, dict) or not entry.get("inventory_item_id"):
                continue
            try:
                child_id = UUID(str(entry["inventory_item_id"]))
            except ValueError:
                continue
            child = self.lot(child_id, depth + 1)
            if child is not None:
                parts.append((child, _num(entry.get("quantity")), str(entry.get("unit") or "")))
        if not parts:
            return None
        comp = Composition()
        units = {unit for _, _, unit in parts}
        quantities = [qty for _, qty, _ in parts]
        if len(units) == 1 and all(q is not None and q > 0 for q in quantities):
            total = sum(quantities)
            weights = [q / total for q in quantities]
        else:
            weights = [Decimal(1) / len(parts)] * len(parts)
            comp.estimated = len(parts) > 1
        for (child, _, _), weight in zip(parts, weights, strict=True):
            for attr in ("variety", "vintage", "region"):
                _add(getattr(comp, attr), getattr(child, attr), weight)
            comp.growers |= child.growers
            comp.fining |= child.fining
            comp.so2_mg_per_l += child.so2_mg_per_l * weight
            comp.unknown_share += child.unknown_share * weight
            comp.estimated = comp.estimated or child.estimated
        so2 = _num(data.get(rules.SO2_ADDED))
        if so2:
            comp.so2_mg_per_l += so2
        fining = str(data.get(rules.FINING) or "").strip()
        if fining and fining != "None":
            comp.fining.add(fining)
        return comp


def composition(session: Session, org_id: UUID, item_id: UUID, role_map: dict[UUID, str]) -> Composition | None:
    """A lot's composition, or None when no winemaking step made it."""
    return _Walker(session, org_id, role_map).lot(item_id)
