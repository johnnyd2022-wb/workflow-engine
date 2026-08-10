"""Global read-side org_id enforcement: automatically scopes every ORM SELECT/UPDATE/DELETE
touching a ``TenantScoped`` model to the current tenant, instead of relying on each repository
method to remember its own ``.filter(Model.org_id == org_id)``.

Mechanism: SQLAlchemy's ``do_orm_execute`` event + ``with_loader_criteria`` — the documented
recipe for exactly this (row-level tenant filtering), not a novel approach. Verified against
this app's real SQLAlchemy 2.0.51 + Postgres test DB in ``tests/test_tenant_filter_spike.py``:
fires for the legacy ``Query`` API this codebase uses exclusively, covers bulk
``Query.update()``/``.delete()``, and covers lazy-loaded relationships (the last of these is
why ``Step``/``ExecutionStep`` — transitively tenant-scoped via a join today — get their own
denormalized ``org_id`` column rather than a correlated-subquery criteria: the spike also
proved ``with_loader_criteria``'s lambda-caching layer rejects a Session/Query object as a
closure variable, which a subquery approach would need).

Policy when no tenant context is set (``tenant_scope.get_current_org_id()`` is None): fail
OPEN, not closed, with a structured warning log. A real HTTP request always has context by
the time repositories run (the tenant-context middleware sets it before any route body
executes); genuine no-context paths are legitimate today — most notably the login/middleware
user lookup that runs *before* org_id is known, since that lookup is how it becomes known —
and requiring every such path to be pre-audited and wrapped in ``unscoped()`` before this can
ship was an explicit, deliberate tradeoff (see the plan this shipped from). This makes the
filter purely additive defense-in-depth on top of existing per-query filters: it closes the
"forgot the filter" bug class (the confirmed CRITICAL/MEDIUM cross-tenant reads in
``.agents/reports/{inventory,execution,reconciliation}/security-audit.md``) wherever tenant
context is present, without a big-bang break of every currently-unscoped call site.

Known residual gap (empirically confirmed, not theoretical): ``Session.get()``/legacy
``Query.get()`` return an already-loaded instance straight from the identity map without
re-querying, bypassing this filter entirely for that call. Sessions here are per-request
(``scoped_session``, torn down in ``teardown_appcontext``), so this isn't a cross-request
leak — the exposure is a same-session ``unscoped()`` fetch followed by a scoped ``.get()`` of
that same row. ``tenant_flush_guard.py`` is the write-side backstop for this gap, not just
extra caution.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.orm.session import ORMExecuteState

from app.core.db.models.tenant_mixin import TenantScoped
from app.core.security.tenant_scope import get_current_org_id, is_bypassed
from app.observability import get_logger

logger = get_logger(__name__)


def _apply_tenant_filter(execute_state: ORMExecuteState) -> None:
    if is_bypassed():
        return
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return
    # Only ORM-mapped statements carry loader criteria; a raw text()/Core statement executed
    # via session.execute() has no mapper to bind TenantScoped criteria to and would error if
    # with_loader_criteria were applied regardless. Raw SQL bypassing this filter entirely is
    # a known, separate gap — tracked in the global-wins findings index, not solved here.
    if not execute_state.is_orm_statement:
        return

    org_id = get_current_org_id()
    if org_id is None:
        logger.warning(
            "tenant_filter.no_context",
            statement_type=("select" if execute_state.is_select else "update" if execute_state.is_update else "delete"),
        )
        return

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(TenantScoped, lambda cls: cls.org_id == org_id, include_aliases=True)
    )


def register_tenant_filter() -> None:
    """Idempotently register the global tenant filter on the Session class. Mirrors the
    registration pattern in ``app/core/domain/inventory_quantity_guard.py`` — this codebase's
    existing precedent for a global, class-level Session event.
    """
    if getattr(register_tenant_filter, "_registered", False):
        return
    event.listen(Session, "do_orm_execute", _apply_tenant_filter, propagate=True)
    register_tenant_filter._registered = True  # type: ignore[attr-defined]
