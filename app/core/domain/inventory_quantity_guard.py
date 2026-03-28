"""Enforce a single authorized path for mutating inventory_items.quantity (ORM-level).

HARD RULE — record_wastage and any handler that runs inside the same database transaction as
inventory writes MUST NOT perform external I/O, message publishing, HTTP callbacks, or fire-and-forget
async work. Those side effects belong after commit or in out-of-band workers. Violating this breaks the
dual-write guarantee under rollback and retry.

Bulk SQL (session.execute UPDATE inventory_items) bypasses this guard; avoid it or extend with triggers.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from enum import Enum

from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session

_inventory_writes_allowed: ContextVar[bool] = ContextVar("_inventory_writes_allowed", default=False)
_reason: ContextVar[str | None] = ContextVar("_inventory_quantity_write_reason", default=None)


class InventoryQuantityWriteReason(str, Enum):
    """Allowed reasons for mutating inventory_items.quantity (grep these + allow_inventory_quantity_write)."""

    WASTAGE_RECORD = "wastage_record"
    EXECUTION_STEP_INVENTORY = "execution_step_inventory"
    REPOSITORY_CREATE = "repository_create"
    REPOSITORY_ADD_QUANTITY = "repository_add_quantity"
    REPOSITORY_UPDATE = "repository_update"
    MANUAL_API_UPDATE = "manual_api_update"
    RESETDB_DEV = "resetdb_dev"


class InventoryQuantityWriteForbiddenError(RuntimeError):
    """Raised when inventory_items.quantity would change outside allow_inventory_quantity_write(...)."""


@contextmanager
def allow_inventory_quantity_write(reason: InventoryQuantityWriteReason | str):
    """Authorize quantity mutations for this block (per-thread / async task)."""
    tok_a: Token[bool] = _inventory_writes_allowed.set(True)
    tok_r: Token[str | None] = _reason.set(str(reason))
    try:
        yield
    finally:
        _inventory_writes_allowed.reset(tok_a)
        _reason.reset(tok_r)


def _before_flush(session: Session, _flush_context, _instances) -> None:
    if _inventory_writes_allowed.get():
        return
    from app.core.db.models.inventory_item import InventoryItem

    combined = set(session.new) | set(session.dirty)
    for obj in combined:
        if not isinstance(obj, InventoryItem):
            continue
        insp = sa_inspect(obj)
        if not insp.attrs.quantity.history.has_changes():
            continue
        raise InventoryQuantityWriteForbiddenError(
            "inventory_items.quantity may only change inside allow_inventory_quantity_write(...) "
            f"(reason). Use InventoryRepository or another authorized path. "
            f"Offending object id={getattr(obj, 'id', None)}."
        )


def register_inventory_quantity_guard() -> None:
    if getattr(register_inventory_quantity_guard, "_registered", False):
        return
    event.listen(Session, "before_flush", _before_flush, propagate=True)
    register_inventory_quantity_guard._registered = True  # type: ignore[attr-defined]
