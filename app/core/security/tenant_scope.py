"""Tenant context propagation for the global ORM-level org_id filter (see tenant_filter.py,
tenant_flush_guard.py).

ContextVar-based, not ``flask.g``: repository-level tests (``tests/test_multi_tenant_
isolation.py``) and the admin CLI (``app/cli/admin.py``) call repositories with no Flask
app/request context at all, so ``g`` isn't available there. A ContextVar works identically
in and out of a request, and — same as ``inventory_quantity_guard.py``'s ContextVars — is
per-thread/per-task, not global, so concurrent requests never see each other's tenant.

Concurrency note: a ContextVar's value persists for the lifetime of the thread/task that set
it unless explicitly reset — it is not auto-cleared between requests on a reused thread. The
Flask middleware (``app/api/middleware/tenant_context.py``) uses
``activate_request_org_id``/``clear_request_org_id`` (unconditional set, not a
``Token``-paired reset) for exactly this reason — see those functions' docstring for why the
obvious token-based design is actually unsafe here: Flask reuses (does not re-push) the
current app context when a request runs while one is already manually active for the same
app, which is exactly what happens in this codebase's own test fixtures that wrap
``client.post(...)``/``client.get(...)`` in a ``with app.app_context():`` block (e.g.
``tests/test_wastage.py``'s ``app_client`` fixture, ``tests/test_org_routes.py``'s
``two_org_world``, ``tests/test_corechecks_routes.py``'s ``flask_app``). Confirmed via a
minimal repro before writing this fix, not by inspection alone. Three failure modes were
found this way, each needing its own clear point — dropping any one of them reintroduces a
real leak:

1. ``teardown_appcontext`` only fires when the app context is genuinely popped by whoever
   pushed it. Under context reuse, a request doesn't own the push, so its
   ``teardown_appcontext`` never fires — only the *outer*, manually-pushed context's does,
   once, at the end of the whole test. If ``before_request`` used a ``Token``-paired
   ``reset()``, multiple un-reset ``.set()`` calls before that point would mean the *last*
   reset only reverses the *last* set, restoring the var to the *previous* set's value (that
   test's org_id) instead of ``None`` — silently poisoning everything that runs afterwards on
   the same thread. Fixed by making ``clear_request_org_id`` an unconditional ``.set(None)``,
   not a token reset: regardless of how many un-paired sets happened, the last operation for a
   given app-context lifecycle is always "clear it".
2. Because ``teardown_appcontext`` doesn't fire per-request under reuse, the *middleware's
   own* ``get_user_by_id`` bootstrap lookup for a **second** authenticated user in the same
   test (e.g. logging in as org B right after org A) ran under org A's still-active filter,
   hiding org B's own user row and 403ing a legitimate login. Fixed by calling
   ``clear_request_org_id()`` at the very *start* of ``before_request``, before that lookup.
3. Even with (1) and (2), the org set by the *last* request in a reused context stays active
   after that request returns — into the test body's own subsequent code (assertions, fixture
   cleanup running `db.query(...).delete()` across both orgs). ``teardown_appcontext`` can't
   help here either, for the same reuse reason. Fixed by also clearing in ``after_request``,
   which — unlike ``teardown_appcontext`` — fires once per actual request regardless of
   app-context reuse, so nothing outside a request ever observes a request's org context.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from collections.abc import Iterator

_current_org_id: ContextVar[UUID | None] = ContextVar("_tenant_scope_current_org_id", default=None)
_bypass: ContextVar[bool] = ContextVar("_tenant_scope_bypass", default=False)


def get_current_org_id() -> UUID | None:
    """The tenant the global filter should scope queries to, or None if unset."""
    return _current_org_id.get()


def is_bypassed() -> bool:
    """True inside an ``unscoped()`` block — the global filter must not add a WHERE clause."""
    return _bypass.get()


def activate_request_org_id(org_id: UUID) -> None:
    """Set the current org_id for the Flask middleware. Deliberately not ``Token``-paired
    with a reset — see this module's docstring for why: request/app-context reuse under test
    clients (and potentially some WSGI server configurations) breaks the 1:1 pairing a
    ``Token`` needs. Pair with ``clear_request_org_id()`` in ``teardown_appcontext``, not
    ``reset()``. Prefer the ``tenant_scope()`` context manager everywhere else — its
    single-``with``-block usage doesn't have this hazard.
    """
    _current_org_id.set(org_id)


def clear_request_org_id() -> None:
    """Unconditionally clear the org_id set by ``activate_request_org_id``. Always safe to
    call — including when nothing was set (public/unauthenticated requests) or when it's
    already been called for this app-context lifecycle."""
    _current_org_id.set(None)


@contextmanager
def tenant_scope(org_id: UUID) -> Iterator[None]:
    """Scope every tenant-scoped ORM query inside this block to ``org_id``. For non-request
    call sites (tests, one-off scripts) that need the global filter active — most repository
    tests don't need this, since they already pass ``org_id`` explicitly per call and the
    global filter is additive on top of that.
    """
    token = _current_org_id.set(org_id)
    try:
        yield
    finally:
        _current_org_id.reset(token)


@contextmanager
def unscoped() -> Iterator[None]:
    """Explicit, auditable escape hatch for legitimate cross-tenant access: the admin CLI
    (``app/cli/admin.py``), and any other call site that genuinely needs to see every org.
    Every use of this should be able to explain why in a nearby comment — it is the one place
    the global filter is deliberately turned off, not silently absent.
    """
    token = _bypass.set(True)
    try:
        yield
    finally:
        _bypass.reset(token)
