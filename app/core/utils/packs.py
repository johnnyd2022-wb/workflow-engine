"""Packs: what one unit of a lot holds, so a workflow can use it in its own units.

A lot bought as cases of 24 × 200 mL tonic is stocked in ``cases``; a step that uses "12 bottles"
or "2.4 L" of it must take half a case, and cost half a case's price. The pack definition lives on
the lot (``extra_data["pack"]``): ``count`` containers per lot unit, each holding ``size``
``size_unit`` (count 1 when a lot unit is a single container, e.g. a 700 mL bottle bought as units).
A pack with no size is just a count: a box of 500 labels is ``{"count": 500}``.

Ordinary conversions (kg↔g, L↔mL) always win; the pack is only used where they can't apply:
counted lot ↔ containers, counted lot ↔ volume or mass, measured lot ↔ containers.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.utils.unit_conversion import (
    COUNT_UNITS,
    MASS_UNITS,
    VOLUME_UNITS,
    _quantize_inventory_decimal,
    are_units_compatible,
    convert_quantity_decimal,
    normalize_unit,
)

PACK_KEY = "pack"
_SIZE_UNITS = {
    "ml": "ml",
    "millilitre": "ml",
    "millilitres": "ml",
    "l": "l",
    "litre": "l",
    "litres": "l",
    "liter": "l",
    "liters": "l",
    "g": "g",
    "gram": "g",
    "grams": "g",
    "kg": "kg",
    "kilo": "kg",
    "kilos": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
}
_NUMBER = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d*[.,]?\d+)"
_UNIT = r"(millilitres?|milliliters?|ml|litres?|liters?|l|grams?|g|kilograms?|kilos?|kg)"
_PACK_RE = re.compile(
    r"(?:(\d+)\s*[x×]\s*)?(?<![\d.,])"
    + _NUMBER
    + r"\s*"
    + _UNIT
    + r"(?![a-z])(?!\s*/)(?:\s*[x×]\s*(\d+)(?!\s*[a-z]))?",
    re.IGNORECASE,
)


def _number(raw: str) -> Decimal:
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", raw):
        return Decimal(raw.replace(",", ""))
    return Decimal(raw.replace(",", "."))


def parse_pack(text: str | None) -> dict | None:
    """'24 x 200 mL', '6x700ml', '700ml x 6', '25 kg', '1,000 mL' -> a pack; anything else -> None.
    The last size in the text wins (a name like "Gin 40% 700ml" reads as 700 mL)."""
    if not text:
        return None
    last = None
    for match in _PACK_RE.finditer(str(text).replace(" ", " ")):
        last = match
    if last is None:
        return None
    try:
        size = _number(last.group(2))
    except InvalidOperation:
        return None
    count = int(last.group(1) or last.group(4) or 1)
    if size <= 0 or count <= 0:
        return None
    return {"count": count, "size": f"{size.normalize():f}", "size_unit": _SIZE_UNITS[last.group(3).lower()]}


# A count with no size, typed by a person: "500", "500 labels", "24 bottles", "500 per box".
_COUNT_ONLY_RE = re.compile(r"^\s*(\d{1,6})\s*(?:[x×]\s*)?(?:[a-z][a-z .\-]{0,30})?\s*$", re.IGNORECASE)
_UNREADABLE_MEASURES = frozenset(
    {
        "oz",
        "lb",
        "lbs",
        "gal",
        "mg",
        "cl",
        "dl",
        "pt",
        "qt",
        "ton",
        "tonne",
        "m",
        "cm",
        "mm",
        "ft",
        "in",
        "l",
        "ml",
        "g",
        "kg",
    }
)
_PACK_HELP = "Pack size must look like '24 x 200 mL', '700 mL', '25 kg' or '500 pcs'"


def _whole(raw) -> int:
    number = Decimal(str(raw))
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError
    return int(number)


def clean_pack(raw) -> dict | None:
    """A pack from an API body: text ('24 x 200 mL', '500 pcs') or a dict. Raises ValueError when unusable."""
    if raw in (None, ""):
        return None
    if isinstance(raw, str):
        pack = parse_pack(raw)
        if pack is not None:
            return pack
        counted = _COUNT_ONLY_RE.match(raw.replace("\u00a0", " "))
        word = re.sub(r"^\s*\d+\s*(?:[x\u00d7]\s*)?", "", raw).strip().lower().split(" ")[0]
        # "12 oz" is a weight we can't read, not twelve of something: say so rather than guess.
        if counted and int(counted.group(1)) > 1 and word not in _UNREADABLE_MEASURES:
            return {"count": int(counted.group(1))}
        raise ValueError(_PACK_HELP)
    if isinstance(raw, dict):
        try:
            count = _whole(raw.get("count", 1))
            has_size = raw.get("size") not in (None, "") or raw.get("size_unit") not in (None, "")
            size = Decimal(str(raw.get("size"))) if has_size else None
        except (TypeError, ValueError, InvalidOperation):
            raise ValueError("Pack needs a whole count and a size") from None
        if not has_size:
            if count <= 1:
                raise ValueError("A pack with no size needs a count above 1")
            return {"count": count}
        unit = _SIZE_UNITS.get(str(raw.get("size_unit", "")).strip().lower())
        if count <= 0 or not size.is_finite() or size <= 0 or unit is None:
            raise ValueError("Pack needs a whole count and a size in mL, L, g or kg")
        return {"count": count, "size": f"{size.normalize():f}", "size_unit": unit}
    raise ValueError("Pack must be text like '24 x 200 mL'")


def lot_pack(item) -> dict | None:
    pack = (getattr(item, "extra_data", None) or {}).get(PACK_KEY)
    try:
        return clean_pack(pack) if pack else None
    except ValueError:
        return None


def has_size(pack: dict | None) -> bool:
    return bool(pack) and "size" in pack


def describe_pack(pack: dict | None) -> str | None:
    if not pack:
        return None
    if not has_size(pack):
        return f"{pack['count']} pcs"
    size = f"{pack['size']} {'mL' if pack['size_unit'] == 'ml' else 'L' if pack['size_unit'] == 'l' else pack['size_unit']}"
    return size if int(pack["count"]) == 1 else f"{pack['count']} × {size}"


# Counted units a pack can stand behind: the core COUNT_UNITS plus the container words the
# Add Inventory hint already treats as counted (cost-ui.js COUNT_UNITS), singular or plural.
_CONTAINER_WORDS = {
    "each",
    "ea",
    "unit",
    "bottle",
    "case",
    "can",
    "jar",
    "jars",
    "pack",
    "packs",
    "bag",
    "bags",
    "box",
    "piece",
    "sack",
    "sacks",
    "tub",
    "tubs",
    "pallet",
    "container",
    "keg",
    "pc",
}
COUNTED_UNITS = frozenset(COUNT_UNITS | _CONTAINER_WORDS)


def _same_word(a: str, b: str) -> bool:
    return a.rstrip("s") == b.rstrip("s") or a.removesuffix("es") == b.removesuffix("es")


def _measured(unit: str) -> bool:
    return unit in MASS_UNITS or unit in VOLUME_UNITS


def convert_for_lot(quantity: Decimal, unit: str | None, item, *, exact: bool = False) -> Decimal:
    """``quantity`` of ``unit`` expressed in ``item``'s own unit, through its pack when ordinary
    conversion can't. Raises ValueError when neither can (the caller's existing 'incompatible'
    message then applies). ``exact`` skips rounding to storage precision on the pack paths, for
    sums (a twenty-fourth of a case is not a 4-decimal number)."""
    rounded = (lambda v: v) if exact else _quantize_inventory_decimal
    lot_unit = item.unit or ""
    if not (unit or "").strip() or normalize_unit(unit) == normalize_unit(lot_unit):
        return _quantize_inventory_decimal(Decimal(str(quantity)))
    if are_units_compatible(unit, lot_unit):
        return convert_quantity_decimal(Decimal(str(quantity)), unit, lot_unit)
    pack = lot_pack(item)
    if pack is None:
        raise ValueError(f"Cannot convert between incompatible units: {unit} and {lot_unit}")
    q, used, held = Decimal(str(quantity)), normalize_unit(unit), normalize_unit(lot_unit)
    count = Decimal(pack["count"])
    size, size_unit = (Decimal(pack["size"]), pack["size_unit"]) if has_size(pack) else (None, None)
    if held in COUNTED_UNITS:
        if used in COUNTED_UNITS and _same_word(used, held):  # "bag" of a lot in "bags"
            return rounded(q)
        if used in COUNTED_UNITS and count > 1:  # bottles from a lot of cases: containers ÷ per case
            return rounded(q / count)
        if size and _measured(used) and are_units_compatible(used, size_unit):  # 2.4 L from cases of 24 × 200 mL
            in_size_unit = convert_quantity_decimal(q, used, size_unit) if used != size_unit else q
            return rounded(in_size_unit / (count * size))
    elif size and _measured(held) and used in COUNTED_UNITS and are_units_compatible(size_unit, held):
        # bottles of 700 mL from a lot held in litres
        return rounded(convert_quantity_decimal(q * size, size_unit, held))
    raise ValueError(f"Cannot convert {unit} to {lot_unit} with pack {describe_pack(pack)}")


def can_convert_for_lot(unit: str | None, item) -> bool:
    try:
        convert_for_lot(Decimal("1"), unit, item)
    except (ValueError, InvalidOperation, ZeroDivisionError):
        return False
    return True


def breakdown(unit_cost: Decimal, item) -> dict | None:
    """What a lot's cost per lot unit comes to per container and per litre or kg, from its pack.

    $48.00 a case of 24 × 200 mL: $2.00 a bottle, $10.00 a litre (4.8 L a case). A lot held in
    litres of 700 mL bottles: $10.00 a litre is $7.00 a bottle. None when the lot has no pack."""
    pack = lot_pack(item)
    if pack is None or unit_cost is None:
        return None
    held = normalize_unit(item.unit or "")
    count = Decimal(pack["count"])
    out = {"pack": describe_pack(pack), "containers": None, "per_container": None, "per_litre": None, "per_kg": None}
    if held in COUNTED_UNITS:
        if count > 1:
            out["containers"] = int(count)
            out["per_container"] = unit_cost / count
        if has_size(pack):
            bulk_unit = "l" if pack["size_unit"] in ("ml", "l") else "kg"
            bulk = convert_quantity_decimal(count * Decimal(pack["size"]), pack["size_unit"], bulk_unit)
            out["per_litre" if bulk_unit == "l" else "per_kg"] = unit_cost / bulk
    elif has_size(pack) and _measured(held) and are_units_compatible(pack["size_unit"], held):
        out["containers"] = 1
        out["per_container"] = unit_cost * convert_quantity_decimal(Decimal(pack["size"]), pack["size_unit"], held)
    else:
        return None
    return out


def containers_per_unit(item) -> Decimal | None:
    """Containers in one unit of a counted lot that holds multipacks (24 for cases of 24), else None."""
    pack = lot_pack(item)
    if pack is None or int(pack["count"]) <= 1 or normalize_unit(item.unit or "") not in COUNTED_UNITS:
        return None
    return Decimal(int(pack["count"]))


def settle_take(current: Decimal, take: Decimal, item) -> Decimal:
    """What to take from a multipack lot so what's left is a whole number of containers.

    A bottle of a case of 24 is 0.0417 of a case at storage precision; taken 24 times that is
    1.0008 cases, and the last bottle would look like more than is left. When what remains is
    within rounding of a whole container, it is set to exactly that container count (stored to
    4 decimals) and the take is whatever gets there. Any other lot, or a take that leaves part
    of a container open, is returned as is."""
    per = containers_per_unit(item)
    if per is None:
        return take
    left = (current - take) * per
    whole = left.to_integral_value(rounding=ROUND_HALF_UP)
    if whole < 0 or abs(left - whole) > _tolerance(per):
        return take  # more than is there stays more than is there; the caller refuses it
    remaining = _quantize_inventory_decimal(whole / per)
    return current - remaining


def whole_containers(quantity: Decimal, item) -> Decimal | None:
    """``quantity`` of a multipack lot as a container count, when it is (within rounding) whole."""
    per = containers_per_unit(item)
    if per is None:
        return None
    containers = quantity * per
    whole = containers.to_integral_value(rounding=ROUND_HALF_UP)
    return whole if abs(containers - whole) <= _tolerance(per) else None


# Storage rounding is at most 0.00005 of a lot unit per write; twice that, in containers, is
# still a tiny fraction of one container for any real pack size.
_SNAP = Decimal("0.0002")


def _tolerance(per: Decimal) -> Decimal:
    return min(per * _SNAP, Decimal("0.25"))
