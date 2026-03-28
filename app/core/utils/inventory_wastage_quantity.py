"""Central policy for parsing and validating inventory wastage quantities."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.core.utils.unit_conversion import normalize_unit

# Universal quantize step for wastage lines (align with inventory quantity strings).
INVENTORY_WASTAGE_QUANTIZE = Decimal("0.0001")

# Reject pathological magnitudes (DoS / storage); normal inventory stays well below this.
MAX_WASTAGE_MAGNITUDE = Decimal("1e18")


def quantize_wastage_quantity(d: Decimal) -> Decimal:
    return d.quantize(INVENTORY_WASTAGE_QUANTIZE)


def parse_wastage_quantity(raw) -> tuple[Decimal | None, str | None]:
    """
    Parse client quantity_wasted into a finite Decimal within bounds.
    Returns (decimal, None) or (None, error_message).
    """
    try:
        d = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None, "quantity_wasted must be a number"
    if not d.is_finite():
        return None, "quantity_wasted must be a finite number"
    if d.is_zero() and d.is_signed():
        return None, "quantity_wasted must be positive"
    try:
        d = d.quantize(INVENTORY_WASTAGE_QUANTIZE)
    except InvalidOperation:
        return None, "quantity_wasted must be a number"
    if d <= 0:
        return None, "quantity_wasted must be positive"
    if d.copy_abs() > MAX_WASTAGE_MAGNITUDE:
        return None, "quantity_wasted is out of allowed range"
    return d, None


def wastage_entries_payload_hash(entries: list[dict]) -> str:
    """
    Canonical SHA-256 of normalized entries for idempotency (sorted by item id).
    Each entry must have inventory_item_id (UUID str) and quantity_wasted (Decimal).
    Optional quantity_unit: unit of quantity_wasted (normalized); omit or empty = same as inventory line.
    """
    norm: list[dict[str, str]] = []
    for e in entries:
        iid = str(UUID(str(e["inventory_item_id"])))
        q = e["quantity_wasted"]
        if not isinstance(q, Decimal):
            q = Decimal(str(q))
        q = q.quantize(INVENTORY_WASTAGE_QUANTIZE)
        raw_u = e.get("quantity_unit")
        if raw_u is not None and raw_u != "":
            qu = normalize_unit(str(raw_u))
        else:
            qu = ""
        norm.append({"inventory_item_id": iid, "quantity_wasted": str(q), "quantity_unit": qu})
    norm.sort(key=lambda x: x["inventory_item_id"])
    canonical = json.dumps(norm, separators=(",", ":"), ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
