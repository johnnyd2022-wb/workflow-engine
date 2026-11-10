"""What a purchase is, decided from the Xero account it was coded to (live-cogs 8.1b).

Layer 1 of spec .agents/specs/live-cogs.md, "Deciding what is a stock purchase". One vocabulary
everywhere: ``stock`` | ``not_stock`` | ``duty`` | ``overhead``. Pure functions, no database.
"""

from __future__ import annotations

import re

STOCK = "stock"
NOT_STOCK = "not_stock"
DUTY = "duty"
OVERHEAD = "overhead"
TREATMENTS = (STOCK, NOT_STOCK, DUTY, OVERHEAD)

# Xero account types that are spending. ``DIRECTCOSTS`` is cost of sales, the only type that can be
# stock; the rest are expenses that never are by default. Spending on any other account (assets,
# liabilities, revenue, equity, bank transfers) is not a purchase and is not stored.
DIRECT_COSTS = "DIRECTCOSTS"
EXPENSE_TYPES = frozenset({DIRECT_COSTS, "EXPENSE", "OVERHEADS", "DEPRECIATN", "WAGESEXPENSE"})
EXPENSE_CLASS = "EXPENSE"

# Whole-word starts, so "Current" or "Parent" is not "rent" and "Highlight" is not "light".
_DUTY = re.compile(r"\b(excise|duty|duties)")
_OVERHEAD = re.compile(r"\b(rent|wages?|salar(y|ies)|power|light|heating|fuel|vehicle|freight|courier|postage)")


def _upper(value) -> str:
    return str(getattr(value, "value", value) or "").strip().upper()


def is_expense(type_, account_class) -> bool:
    """True for accounts whose lines are stored (whatever their treatment)."""
    return _upper(account_class) == EXPENSE_CLASS or _upper(type_) in EXPENSE_TYPES


def default_treatment(type_, account_class, name) -> str | None:
    """The account's default treatment, or ``None`` when it is not an expense account."""
    if not is_expense(type_, account_class):
        return None
    if _upper(type_) != DIRECT_COSTS:
        return NOT_STOCK
    lowered = " ".join(str(name or "").lower().split())
    if _DUTY.search(lowered):
        return DUTY
    if _OVERHEAD.search(lowered):
        return OVERHEAD
    return STOCK
