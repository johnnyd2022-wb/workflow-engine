"""Write-side org_id enforcement: a ``before_flush`` guard asserting every new, dirty, or
deleted ``TenantScoped`` instance belongs to the current tenant before it reaches the
database.

This is deliberately a separate listener from ``app/core/domain/inventory_quantity_guard.py``
(different concern — quantity-write authorization vs tenant ownership) even though both hook
``before_flush`` on the same ``Session`` class; multiple ``before_flush`` listeners coexist
fine (SQLAlchemy invokes each registered listener in turn) and neither cares about the other's
target attribute, so registration order doesn't matter here.

Why this exists alongside the read-side filter (``tenant_filter.py``): ``with_loader_criteria``
does not cover every path an object can reach the session by. Confirmed empirically in
``tests/test_tenant_filter_spike.py``: ``Session.get()``/legacy ``Query.get()`` return an
already-loaded instance straight from the identity map without re-querying, bypassing the
read-side filter entirely for that call. This guard is the backstop — if an object from the
wrong tenant somehow ends up dirty or new in this session (identity-map bypass, an
``unscoped()`` fetch followed by a mutation outside that block, a bug in a repository), the
flush is rejected before it reaches Postgres, rather than silently committing a cross-tenant
write.

Policy mirrors the read side: when no tenant context is set, this guard does not block the
flush (fail-open) — signup (creating the first ``Organisation`` + ``User`` for a brand-new
tenant, before any context exists) and the admin CLI's ``unscoped()`` paths both legitimately
flush ``TenantScoped`` rows with no ambient org_id context to check against. What it does
enforce, whenever context IS present and the block isn't ``unscoped()``: every affected
instance's ``org_id`` must be set, and must equal the current tenant.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.db.models.tenant_mixin import TenantScoped
from app.core.security.tenant_scope import get_current_org_id, is_bypassed


class TenantScopeViolationError(RuntimeError):
    """Raised when a flush would write a TenantScoped row outside the current tenant."""


def _before_flush(session: Session, _flush_context, _instances) -> None:
    if is_bypassed():
        return
    org_id = get_current_org_id()
    if org_id is None:
        return

    affected = set(session.new) | set(session.dirty) | set(session.deleted)
    for obj in affected:
        if not isinstance(obj, TenantScoped):
            continue
        obj_org_id = obj.org_id
        if obj_org_id is None:
            raise TenantScopeViolationError(
                f"{type(obj).__name__} flushed with no org_id while tenant context is set "
                f"(current tenant={org_id}). Set org_id explicitly at creation, or wrap "
                "genuinely tenant-less writes in tenant_scope.unscoped()."
            )
        if obj_org_id != org_id:
            raise TenantScopeViolationError(
                f"{type(obj).__name__} id={getattr(obj, 'id', None)} belongs to org "
                f"{obj_org_id}, but the current tenant context is {org_id}. This blocks a "
                "cross-tenant write — if it's intentional (admin tooling), wrap it in "
                "tenant_scope.unscoped()."
            )


def register_tenant_flush_guard() -> None:
    """Idempotently register the write-side tenant guard on the Session class."""
    if getattr(register_tenant_flush_guard, "_registered", False):
        return
    event.listen(Session, "before_flush", _before_flush, propagate=True)
    register_tenant_flush_guard._registered = True  # type: ignore[attr-defined]
