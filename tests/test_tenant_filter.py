"""Tests proving the global ORM tenant filter (app/core/db/tenant_filter.py) and write-side
guard (app/core/db/tenant_flush_guard.py) actually enforce org scoping -- not just that the
per-query `.filter(Model.org_id == org_id)` calls already in every repository do (those are
covered by tests/test_multi_tenant_isolation.py). These tests prove the global filter closes
the gap even when a query has NO manual org filter at all -- the exact shape of the confirmed
CRITICAL/MEDIUM findings in .agents/reports/{inventory,execution}/security-audit.md.
"""

import pytest

from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.process import Process
from app.core.db.models.step import Step
from app.core.db.models.user import User
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.db.tenant_flush_guard import TenantScopeViolationError
from app.core.security.tenant_scope import tenant_scope, unscoped
from tests.factories import ExecutionFactory, ProcessFactory


@pytest.fixture
def cleanup_processes(db):
    """Process (and its Step/Execution/ExecutionStep children) aren't cascade-deleted when
    two_org_two_user tears down the orgs -- process_versions.process_id is the only
    DB-level ON DELETE CASCADE in this chain (confirmed against the live schema); steps,
    executions, and execution_steps are not. Mirrors the cleanup tests/test_multi_tenant_
    isolation.py's `world` fixture already does for Execution/InventoryItem/Process, extended
    with Step/ExecutionStep since these tests create real steps (world's processes never do).
    Tests that create a Process under two_org_two_user append its org_id here.
    """
    org_ids: list = []
    yield org_ids
    if not org_ids:
        return
    db.rollback()
    db.query(ExecutionStep).filter(ExecutionStep.org_id.in_(org_ids)).delete(synchronize_session=False)
    db.query(Execution).filter(Execution.org_id.in_(org_ids)).delete(synchronize_session=False)
    db.query(Step).filter(Step.org_id.in_(org_ids)).delete(synchronize_session=False)
    db.query(Process).filter(Process.org_id.in_(org_ids)).delete(synchronize_session=False)
    db.commit()


def test_unfiltered_query_blocked_across_tenants(db, two_org_two_user):
    """Fetch org B's user via a query with NO manual org filter at all, org A's context
    active. This is the core proof: the global filter, not a per-query .filter(), is what
    blocks it."""
    org_a = two_org_two_user["org_a"]
    user_b = two_org_two_user["user_b"]

    with tenant_scope(org_a.id):
        result = db.query(User).filter(User.id == user_b.id).first()

    assert result is None, "global filter did not block a cross-org fetch with no manual filter"


def test_unfiltered_query_allows_own_tenant(db, two_org_two_user):
    """Control: org A's own user, no manual filter, org A context active -- must succeed,
    proving the filter scopes rather than blanket-denies."""
    org_a = two_org_two_user["org_a"]
    user_a = two_org_two_user["user_a"]

    with tenant_scope(org_a.id):
        result = db.query(User).filter(User.id == user_a.id).first()

    assert result is not None and result.id == user_a.id


def test_execution_step_bulk_lookup_pattern_is_closed_without_manual_filter(
    db, two_org_two_user, cleanup_processes
):
    """Regression for the confirmed CRITICAL/MEDIUM finding class in .agents/reports/
    {inventory,execution}/security-audit.md: a query fetched ExecutionStep/Execution by ID
    with no join back to the owning org's org_id. dagtraversal.py's _enrich_items_bulk and
    add_step_order_connections already carry manual org filters as defense-in-depth today
    (see their comments) -- this test proves the *global* filter independently closes the
    same class of bug, using the exact vulnerable query shape (join ExecutionStep ->
    Execution, filter by ID only) with the manual org clause deliberately omitted.
    """
    org_a, org_b = two_org_two_user["org_a"], two_org_two_user["org_b"]
    cleanup_processes.append(org_b.id)

    process_repo = ProcessRepository(db)
    process_b = ProcessFactory(org_id=org_b.id)
    process_repo.add_step(process_id=process_b.id, org_id=org_b.id, step_number=1, position=1000, name="Step B1")
    execution_b = ExecutionFactory(org_id=org_b.id, process_id=process_b.id)
    db.commit()

    exec_step_ids = [
        es.id for es in db.query(ExecutionStep).filter(ExecutionStep.execution_id == execution_b.id).all()
    ]
    assert exec_step_ids, "fixture setup produced no execution_steps"

    with tenant_scope(org_a.id):
        # Deliberately the vulnerable shape: join back to Execution, filter by ID only, NO
        # Execution.org_id clause -- what the confirmed finding looked like before its manual
        # fix. The global filter must still block it via both ExecutionStep and Execution
        # (both TenantScoped), independent of any per-query filter.
        leaked = (
            db.query(ExecutionStep)
            .join(Execution, ExecutionStep.execution_id == Execution.id)
            .filter(ExecutionStep.id.in_(exec_step_ids))
            .all()
        )

    assert leaked == [], "global filter did not close the confirmed cross-tenant bug class"


def test_unscoped_admin_access_still_crosses_tenants(db, two_org_two_user):
    """unscoped() must still allow legitimate cross-tenant access (admin CLI) -- the global
    filter is an opt-out escape hatch, not an unconditional wall."""
    org_a = two_org_two_user["org_a"]
    user_b = two_org_two_user["user_b"]

    with tenant_scope(org_a.id), unscoped():
        result = db.query(User).filter(User.id == user_b.id).first()

    assert result is not None and result.id == user_b.id


def test_flush_guard_blocks_cross_tenant_write(db, two_org_two_user, cleanup_processes):
    """Write-side backstop: mutating and flushing a row that belongs to a different org than
    the active tenant context must be rejected, even though it was fetched successfully
    (defense-in-depth for the identity-map bypass documented in tenant_filter.py)."""
    org_a = two_org_two_user["org_a"]
    org_b = two_org_two_user["org_b"]
    cleanup_processes.append(org_b.id)
    process_b = ProcessFactory(org_id=org_b.id)
    db.commit()

    with tenant_scope(org_a.id):
        process_b.name = "renamed under org A context"
        with pytest.raises(TenantScopeViolationError):
            db.commit()

    db.rollback()


def test_flush_guard_allows_same_tenant_write(db, two_org_two_user, cleanup_processes):
    """Control: a write under the write-side guard succeeds when org context matches."""
    org_a = two_org_two_user["org_a"]
    cleanup_processes.append(org_a.id)
    process_a = ProcessFactory(org_id=org_a.id)
    db.commit()

    with tenant_scope(org_a.id):
        process_a.name = "renamed under matching org context"
        db.commit()

    db.refresh(process_a)
    assert process_a.name == "renamed under matching org context"


def test_flush_guard_allows_unscoped_admin_write(db, two_org_two_user, cleanup_processes):
    """unscoped() must also bypass the write-side guard, matching the read-side escape
    hatch, for legitimate cross-tenant admin writes."""
    org_a = two_org_two_user["org_a"]
    org_b = two_org_two_user["org_b"]
    cleanup_processes.append(org_b.id)
    process_b = ProcessFactory(org_id=org_b.id)
    db.commit()

    with tenant_scope(org_a.id), unscoped():
        process_b.name = "renamed by admin tooling"
        db.commit()

    db.refresh(process_b)
    assert process_b.name == "renamed by admin tooling"


def test_no_context_is_fail_open(db, two_org_two_user):
    """Documented policy: with no tenant context set at all (the admin-CLI/no-Flask-context
    case), the global filter does not add a WHERE clause -- behaves exactly like before this
    mechanism existed. This is the deliberate fail-open default, not an oversight."""
    user_b = two_org_two_user["user_b"]

    result = db.query(User).filter(User.id == user_b.id).first()

    assert result is not None and result.id == user_b.id
