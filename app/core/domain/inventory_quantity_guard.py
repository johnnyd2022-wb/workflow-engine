"""Enforce a single authorized path for mutating inventory_items.quantity (ORM + PostgreSQL).

HARD RULE — record_wastage and any handler that runs inside the same database transaction as
inventory writes MUST NOT perform external I/O, message publishing, HTTP callbacks, or fire-and-forget
async work. Those side effects belong after commit or in out-of-band workers. Violating this breaks the
dual-write guarantee under rollback and retry.

Defense in depth (PostgreSQL):
- Engine ``before_cursor_execute`` sets transaction-local GUC ``app.inventory_qty_guard`` before every
  statement on that engine, so bulk ``session.execute(update(...))`` / raw SQL see the same flag as ORM
  flushes (before_flush alone is not guaranteed to run first).
- ``before_flush`` still enforces the ORM-only rule: dirty/new ``InventoryItem`` rows cannot change
  ``quantity`` outside ``allow_inventory_quantity_write``.
- A DB trigger rejects unauthorized INSERT or quantity-changing UPDATE when migration mode and guard are off.
- Alembic sets ``app.migration_mode=1`` for the migration transaction (see migrations/env.py).

This module does not enforce multi-column semantic invariants (quantity + flags); that remains
application/repository responsibility.

ContextVar note: ``allow_inventory_quantity_write`` is scoped per async task / thread. Do not share one
Session across concurrent tasks; nested ``allow`` blocks are rejected, but concurrent overlapping allows in
different tasks are not automatically detected—keep sessions task-scoped.

Policy: avoid raw UPDATE/INSERT into inventory_items outside migrations; run scripts/ci_inventory_quantity_sql_scan.py in CI (heuristic only).

``prepare_inventory_qty_guard_for_raw_sql`` is optional when the app engine is registered with
``register_inventory_quantity_guard(engine)``; use it in tests or custom connections if statements bypass
that engine's listeners.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from enum import Enum

from sqlalchemy import event, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

_inventory_writes_allowed: ContextVar[bool] = ContextVar("_inventory_writes_allowed", default=False)
_reason: ContextVar[str | None] = ContextVar("_inventory_quantity_write_reason", default=None)
_allow_nesting_depth: ContextVar[int] = ContextVar("_allow_nesting_depth", default=0)
_guc_sync_depth: ContextVar[int] = ContextVar("_guc_sync_depth", default=0)


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
    """Authorize quantity mutations for this block (per-thread / async task). Nested blocks are forbidden."""
    if _allow_nesting_depth.get() != 0:
        raise RuntimeError("Nested allow_inventory_quantity_write is not allowed (ContextVar safety).")
    tok_n: Token[int] = _allow_nesting_depth.set(1)
    tok_a: Token[bool] = _inventory_writes_allowed.set(True)
    tok_r: Token[str | None] = _reason.set(str(reason))
    try:
        yield
    finally:
        _allow_nesting_depth.reset(tok_n)
        _inventory_writes_allowed.reset(tok_a)
        _reason.reset(tok_r)


def _sync_pg_qty_guard_guc(session: Session) -> None:
    bind = session.get_bind()
    if not bind or getattr(bind.dialect, "name", None) != "postgresql":
        return
    flag = "1" if _inventory_writes_allowed.get() else "0"
    session.execute(text("SELECT set_config('app.inventory_qty_guard', :v, true)"), {"v": flag})


def prepare_inventory_qty_guard_for_raw_sql(session: Session) -> None:
    """Explicitly sync app.inventory_qty_guard on this session's connection (inside allow_inventory_quantity_write only).

    When ``register_inventory_quantity_guard(engine)`` is used for the app's Engine, ``before_cursor_execute``
    already syncs the GUC before each statement—this helper is optional (tests, scripts, or engines without
    the listener).
    """
    if not _inventory_writes_allowed.get():
        raise RuntimeError(
            "prepare_inventory_qty_guard_for_raw_sql() must only be used inside allow_inventory_quantity_write(...)"
        )
    _sync_pg_qty_guard_guc(session)


def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Set app.inventory_qty_guard before every PostgreSQL statement (re-entrancy-safe for our own set_config)."""
    if getattr(conn.dialect, "name", None) != "postgresql":
        return
    if _guc_sync_depth.get() > 0:
        return
    tok = _guc_sync_depth.set(1)
    try:
        flag = "1" if _inventory_writes_allowed.get() else "0"
        cursor.execute("SELECT set_config('app.inventory_qty_guard', %s, true)", (flag,))
    finally:
        _guc_sync_depth.reset(tok)


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


def register_inventory_quantity_guard(engine: Engine | None = None) -> None:
    """Register ORM flush guard and (recommended) per-statement GUC sync on ``engine``."""
    if not getattr(register_inventory_quantity_guard, "_session_registered", False):
        event.listen(Session, "before_flush", _before_flush, propagate=True)
        register_inventory_quantity_guard._session_registered = True  # type: ignore[attr-defined]
    if engine is not None and not getattr(register_inventory_quantity_guard, "_engine_registered", False):
        event.listen(engine, "before_cursor_execute", _before_cursor_execute)
        register_inventory_quantity_guard._engine_registered = True  # type: ignore[attr-defined]
