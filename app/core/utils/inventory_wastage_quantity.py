"""Central policy for parsing and validating inventory wastage quantities."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.core.utils.inventory_quantity import STORAGE_QUANTIZE_EXP
from app.core.utils.unit_conversion import normalize_unit

# Same quantize as NUMERIC(18,4) on-hand storage.
INVENTORY_WASTAGE_QUANTIZE = STORAGE_QUANTIZE_EXP

# Reject pathological magnitudes (DoS / storage); normal inventory stays well below this.
MAX_WASTAGE_MAGNITUDE = Decimal("1e18")


def quantize_wastage_quantity(d: Decimal) -> Decimal:
    return d.quantize(INVENTORY_WASTAGE_QUANTIZE)


def parse_wastage_unit_field(raw: object | None) -> tuple[str | None, str | None]:
    """Normalize optional quantity_unit / unit; single source of truth with hash (None = same as inventory line)."""
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        return None, "quantity_unit must be a string when provided"
    u = normalize_unit(raw)
    return (None if u == "" else u), None


def _wastage_unit_for_hash(raw: object | None) -> str:
    """Canonical unit string for idempotency (must stay aligned with parse_wastage_unit_field)."""
    u, _ = parse_wastage_unit_field(raw)
    return u or ""


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
    Each entry must have inventory_item_id (UUID str), quantity_wasted (Decimal), and reason (str).
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
        qu = _wastage_unit_for_hash(raw_u)
        norm.append({"inventory_item_id": iid, "quantity_wasted": str(q), "quantity_unit": qu, "reason": str(e.get("reason") or "").replace("\x00", "").strip()})
    norm.sort(key=lambda x: x["inventory_item_id"])
    canonical = json.dumps(norm, separators=(",", ":"), ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
