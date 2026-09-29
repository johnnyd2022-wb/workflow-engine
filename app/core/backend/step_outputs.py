"""Rules applied to a completed step's outputs before they become stock (execution slice).

Plan item 1.2: counted goods (bottles, cans, kegs, cases...) are recorded in whole
numbers. When a run doesn't divide into whole units, the remainder is recorded as
**Library stock** for that product, in mL, with the same lineage as the batch, instead of
as a fraction of a bottle. Library stock can then be mapped to a Xero item and sold,
used in a later batch, or written off.

Kept out of backend.py (which must not grow; see scripts/check_backend_size.py).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.core.utils.unit_conversion import is_count_unit, whole_count_error

DEFAULT_LIBRARY_STOCK_NAME = "Library stock"
LIBRARY_STOCK_UNIT = "ml"


def library_stock_name(product_name: str, process_settings: dict | None) -> str:
    """ "<product> - Library stock", where the category name is a per-workflow setting."""
    category = (process_settings or {}).get("library_stock_name") or DEFAULT_LIBRARY_STOCK_NAME
    return f"{product_name} - {str(category).strip() or DEFAULT_LIBRARY_STOCK_NAME}"


def parse_output_batch_number(output: dict, output_name: str, extra_data: dict, warnings: list[str]) -> None:
    """Optional: tag this specific output with a lot/label-batch number (e.g. a physical
    run of 500 pre-printed labels). Purely descriptive metadata -- unlike
    supplier_batch_number, this is not unique per (org, name): several outputs across
    different steps/executions can and do share one batch number when a single physical
    batch spans multiple production runs."""
    batch_number_raw = output.get("batch_number")
    if batch_number_raw is None:
        return
    try:
        extra_data["batch_number"] = int(batch_number_raw)
    except (TypeError, ValueError):
        warnings.append(f"Output '{output_name}': ignoring non-integer batch_number {batch_number_raw!r}.")


def _library_remainder(output: dict) -> Decimal | None:
    raw = output.get("library_remainder_ml")
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("NaN")
    return value


def apply_whole_unit_rules(
    output_creations: list[dict], actual_outputs: list[dict], process_settings: dict | None = None
) -> list[str]:
    """Check counted outputs are whole and add Library stock lines for any remainder.

    Mutates ``output_creations`` (appends Library stock creations) and returns the
    validation errors, which block the step like any other output error.
    """
    errors: list[str] = []
    by_name = {}
    for output in actual_outputs or []:
        if isinstance(output, dict):
            by_name.setdefault(str(output.get("name") or "Unknown"), output)

    library_lines = []
    for creation in output_creations:
        name = creation.get("name", "Unknown")
        unit = creation.get("unit") or "units"
        quantity = creation.get("quantity_decimal")
        if quantity is None:
            try:
                quantity = Decimal(str(creation.get("quantity")))
            except (InvalidOperation, ValueError, TypeError):
                continue
        message = whole_count_error(quantity, unit, what=f"Output '{name}'")
        if message:
            errors.append(message + " Record the full ones and put the rest in Library stock (mL).")
            continue

        remainder = _library_remainder(by_name.get(name, {}))
        if remainder is None:
            continue
        if not remainder.is_finite() or remainder < 0:
            errors.append(f"Output '{name}': Library stock must be a number of mL, 0 or more.")
            continue
        if remainder == 0:
            continue
        if not is_count_unit(unit):
            errors.append(f"Output '{name}': Library stock is only for counted outputs such as bottles.")
            continue
        extra = dict(creation.get("extra_data") or {})
        # Same batch lineage (source execution/step, label run) as the bottles it came from.
        extra.update({"library_stock": True, "library_stock_of": name})
        library_lines.append(
            {
                **creation,
                "name": library_stock_name(name, process_settings),
                "quantity": str(remainder),
                "quantity_decimal": remainder,
                "unit": LIBRARY_STOCK_UNIT,
                "extra_data": extra,
                # Library stock is new stock, never reconciled against an untracked item.
                "untracked_item_id": None,
            }
        )
    output_creations.extend(library_lines)
    return errors
