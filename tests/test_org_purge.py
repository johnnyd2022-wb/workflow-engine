"""The test DB must not keep the organisations a run creates (finding 4ff460ee).

`tests/org_purge.py` records every org inserted in the process and `tests/conftest.py` purges
the survivors at session end. These tests pin the three parts: the tracker sees every way an
org gets created, the purge removes an org with everything it owns and nothing of anyone
else's, and the session-end backstop is actually wired in.
"""

import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import MetaData, func, select

from app.core.db.models.audit_log import AuditLog
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.process_repo import ProcessRepository
from tests import org_purge
from tests.factories import (
    ExecutionFactory,
    InventoryItemFactory,
    OrganisationFactory,
    ProcessFactory,
    UserFactory,
)
from tests.org_purge import created_org_ids, purge_orgs, purge_orgs_named

REPO_ROOT = Path(__file__).resolve().parents[1]


def _org_row_counts(db, org_id) -> dict[str, int]:
    """table -> rows belonging to the org, for every table in the live schema."""
    metadata = MetaData()
    metadata.reflect(bind=db.get_bind())
    counts = {}
    for table in metadata.tables.values():
        if table.name == "organisations":
            counts[table.name] = db.scalar(select(func.count()).select_from(table).where(table.c.id == org_id))
        elif "org_id" in table.c:
            counts[table.name] = db.scalar(select(func.count()).select_from(table).where(table.c.org_id == org_id))
    return counts


def _populate(db, org):
    """A user who has logged something, a process with steps, an execution, and stock."""
    # A unique email, not the factory's per-process sequence: its test-user-0 restarts at 0 in every
    # process, and a user leaked by an earlier run still holds that address.
    user = UserFactory(org_id=org.id, email=f"purge-{uuid4().hex[:8]}@example.test")
    process = ProcessFactory(org_id=org.id, name=f"Purge Process {uuid4().hex[:8]}")
    for number in (1, 2):
        ProcessRepository(db).add_step(
            process_id=process.id,
            org_id=org.id,
            step_number=number,
            position=number * 1000,
            name=f"Step {number}",
            inputs=[{"name": "In", "quantity": 1, "unit": "kg"}],
            outputs=[{"name": "Out", "quantity": 1, "unit": "kg"}],
        )
    ExecutionFactory(org_id=org.id, process_id=process.id)
    InventoryItemFactory(org_id=org.id)
    db.add(AuditLog(org_id=org.id, user_id=user.id, action="login", entity="user"))
    db.commit()


def test_tracker_records_an_org_however_it_is_created_through_the_orm(db):
    via_factory = OrganisationFactory()
    via_repository = OrganisationRepository(db).create_org(f"Purge Repo Org {uuid4()}")
    via_model = Organisation(name=f"Purge Model Org {uuid4()}")
    db.add(via_model)
    db.commit()

    ids = [via_factory.id, via_repository.id, via_model.id]
    try:
        assert set(ids) <= created_org_ids()
    finally:
        purge_orgs(db, ids)


def test_purge_removes_an_org_and_everything_it_owns_and_nothing_else(db):
    doomed = OrganisationFactory()
    neighbour = OrganisationFactory()
    _populate(db, doomed)
    _populate(db, neighbour)
    doomed_id, neighbour_id = doomed.id, neighbour.id
    neighbour_before = _org_row_counts(db, neighbour_id)

    try:
        before = _org_row_counts(db, doomed_id)
        # The assertion below would hold vacuously on an empty org; make sure this one owns rows
        # across the user, audit, process, step, execution and inventory tables.
        populated = {name for name, count in before.items() if count}
        assert {"organisations", "users", "audit_logs", "processes", "execution_steps", "inventory_items"} <= populated

        assert purge_orgs(db, [doomed_id]) == 1

        leftovers = {name: count for name, count in _org_row_counts(db, doomed_id).items() if count}
        assert leftovers == {}
        assert _org_row_counts(db, neighbour_id) == neighbour_before
    finally:
        purge_orgs(db, [doomed_id, neighbour_id])


def test_purge_by_name_finds_orgs_a_server_process_created(db):
    name = f"Purge Named Org {uuid4()}"
    org = OrganisationFactory(name=name)
    bystander = OrganisationFactory()
    db.commit()
    org_id, bystander_id = org.id, bystander.id

    try:
        assert purge_orgs_named(db, [name]) == 1
        assert db.get(Organisation, org_id) is None
        assert db.get(Organisation, bystander_id) is not None
    finally:
        purge_orgs(db, [org_id, bystander_id])


def test_purge_of_orgs_that_are_already_gone_is_a_no_op(db):
    assert purge_orgs(db, [uuid4(), uuid4()]) == 0


def test_a_deliberately_persistent_org_is_not_tracked(db, monkeypatch):
    """Fixtures that create "Whistlebird Demo" if absent rely on it persisting, and another session
    sharing the database may be using it: the backstop must not take it away at session end."""
    name = f"Purge Persistent Org {uuid4()}"
    monkeypatch.setattr(org_purge, "_PERSISTENT_ORG_NAMES", frozenset({name}))
    persistent = OrganisationFactory(name=name)
    ordinary = OrganisationFactory()
    db.commit()
    persistent_id, ordinary_id = persistent.id, ordinary.id

    try:
        assert persistent_id not in created_org_ids()
        assert ordinary_id in created_org_ids()
    finally:
        purge_orgs(db, [persistent_id, ordinary_id])


def test_purge_works_through_every_chunk(db, monkeypatch):
    monkeypatch.setattr(org_purge, "_CHUNK", 1)
    orgs = [OrganisationFactory() for _ in range(3)]
    db.commit()
    ids = [org.id for org in orgs]

    assert purge_orgs(db, ids) == 3
    assert db.scalar(select(func.count()).select_from(Organisation).where(Organisation.id.in_(ids))) == 0


def test_a_failing_chunk_is_reported_but_does_not_strand_the_others(db, monkeypatch):
    monkeypatch.setattr(org_purge, "_CHUNK", 1)
    orgs = [OrganisationFactory() for _ in range(3)]
    db.commit()
    ids = [org.id for org in orgs]
    real_purge_chunk = org_purge._purge_chunk
    calls = []

    def fail_the_first_chunk(session, metadata, chunk):
        calls.append(chunk)
        if len(calls) == 1:
            raise RuntimeError("boom")
        real_purge_chunk(session, metadata, chunk)

    monkeypatch.setattr(org_purge, "_purge_chunk", fail_the_first_chunk)
    try:
        with pytest.raises(RuntimeError, match="still present after purge.*boom"):
            purge_orgs(db, ids)
        survivors = db.scalars(select(Organisation.id).where(Organisation.id.in_(ids))).all()
        assert len(calls) == 3
        assert survivors == calls[0]
    finally:
        monkeypatch.setattr(org_purge, "_purge_chunk", real_purge_chunk)
        purge_orgs(db, ids)


def test_a_purge_that_leaves_an_org_behind_raises_instead_of_going_quiet(db, monkeypatch):
    org = OrganisationFactory()
    db.commit()
    org_id = org.id

    monkeypatch.setattr(org_purge, "_purge_chunk", lambda session, metadata, chunk: None)
    try:
        with pytest.raises(RuntimeError, match="still present after purge"):
            purge_orgs(db, [org_id])
    finally:
        monkeypatch.undo()
        purge_orgs(db, [org_id])


def test_purge_with_nothing_tracked_never_touches_the_database():
    """A session that inserted no org (a pure-unit selection, or no database reachable) must not
    error at teardown: the purge returns before it asks the session for anything."""

    class NoDatabase:
        def __getattr__(self, name):
            raise AssertionError(f"touched the database: {name}")

    assert purge_orgs(NoDatabase(), []) == 0


def test_the_session_end_backstop_removes_an_org_a_test_left_behind(db, tmp_path):
    """Run a probe that leaks an org and a user, then look in the database once its pytest
    session has ended. This is the test that goes red if the autouse fixture in
    tests/conftest.py is removed or stops purging."""
    out = tmp_path / "leaked_org_id"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/_org_leak_probe.py", "-q", "-p", "no:cacheprovider"],
        cwd=REPO_ROOT,
        env={**os.environ, "ORG_PURGE_PROBE_OUT": str(out)},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    leaked_id = UUID(out.read_text())
    try:
        assert (
            db.execute(select(func.count()).select_from(Organisation).where(Organisation.id == leaked_id)).scalar() == 0
        )
    finally:
        purge_orgs(db, [leaked_id])
