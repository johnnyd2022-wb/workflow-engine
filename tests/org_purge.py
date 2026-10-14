"""Remove every organisation a test run created, and everything it owns.

The shared test database kept thousands of "Test Org N-…" / "TestOrg_…" rows, because each
test file hand-rolled its own teardown and many didn't (finding 4ff460ee). Per-file
teardown cannot be audited from one place, so this is a backstop: `track_created_orgs()`
records the id of every `Organisation` this process inserts through the ORM (factory,
repository, a bare model), and `tests/conftest.py` purges whatever is still there when the
session ends. A fixture that cleans up for itself is unaffected.

What it does not see: an org a *server process* creates (live-server signup tests purge
those by name with `purge_orgs_named`), and anything inserted by Core `insert()`, bulk
mappings or raw SQL, none of which fire the ORM event. No test does that to `organisations`
today.

Choices worth not re-deriving:

- **The live schema is walked, not `Base.metadata`.** A unit-test process only has the
  model modules it imported, so a metadata walk silently misses a table and the org delete
  then dies on a foreign key. Reflecting the database covers every table the migrations
  made, the day it is added.
- **Scope is `org_id` and nothing else.** Every tenant table carries a non-null `org_id`, so
  that is the whole of what an org owns. A row of *another* org that points into a purged
  org is not ours to delete: the purge fails loudly on it instead.
- **`app.migration_mode` is set for the purge**, as the contract-material and site-transfer
  fixtures already do for their own teardown: customer stock evidence is immutable by
  trigger in production, and a test org's evidence has to be discardable here.
- **One bad chunk does not strand the rest.** Failures are collected and raised together.
- **Orgs a suite deliberately keeps are not tracked** (`_PERSISTENT_ORG_NAMES`): several
  fixtures create "Whistlebird Demo" if absent and rely on it persisting, and another
  session sharing the database may be using it.

`tests/e2e/conftest.py::purge_org` is the older, single-user version of the same walk. It
imports Playwright, so the unit suite cannot use it; the two should be merged once that
file is free to change.

`purge_orgs` only touches ids it is given, and the session-end fixture only gives it ids
this process inserted, so a real tenant or another session's org is never matched.
`purge_orgs_named` trusts its caller: pass only names the test generated itself.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import MetaData, event, select, text
from sqlalchemy.exc import IntegrityError, SAWarning

from app.core.db.models.organisation import Organisation

# Org ids per delete pass: keeps each statement's `IN (...)` list small.
_CHUNK = 100

# Created if absent by several fixtures, which then rely on it persisting for later runs and for
# other sessions sharing the database. Never tracked, so never purged.
_PERSISTENT_ORG_NAMES = frozenset({"Whistlebird Demo"})

_created_org_ids: set[UUID] = set()
_installed = False
_reflected: MetaData | None = None


def track_created_orgs() -> None:
    """Record the id of every Organisation this process inserts. Idempotent."""
    global _installed
    if _installed:
        return
    event.listen(Organisation, "after_insert", _track)
    _installed = True


def _track(_mapper, _connection, org: Organisation) -> None:
    if org.name not in _PERSISTENT_ORG_NAMES:
        _created_org_ids.add(org.id)


def created_org_ids() -> frozenset[UUID]:
    return frozenset(_created_org_ids)


def _schema(session) -> MetaData:
    """The database's own tables and foreign keys, reflected once per process."""
    global _reflected
    if _reflected is None:
        metadata = MetaData()
        metadata.reflect(bind=session.get_bind())
        _reflected = metadata
    return _reflected


def _children_first(metadata: MetaData) -> list:
    # A foreign-key cycle (inventory_items <-> contract_material_receipts) makes SQLAlchemy
    # warn that no order is exact; the retry loop in _purge_chunk is what copes with that.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SAWarning)
        return list(reversed(metadata.sorted_tables))


def _purge_chunk(session, metadata: MetaData, org_ids: list[UUID]) -> None:
    # A row some other connection still holds must fail the purge, not hang the suite's teardown.
    session.execute(text("SET LOCAL lock_timeout = '15s'"))
    session.execute(text("SELECT set_config('app.migration_mode', '1', true)"))
    statements = [
        (table.name, table.delete().where(table.c.org_id.in_(org_ids)))
        for table in _children_first(metadata)
        if "org_id" in table.c
    ]
    # No single order is safe where tables reference each other (the site transfer tables, the
    # inventory/receipt cycle). Postpone a delete the database refuses and retry after the rest;
    # give up only when a whole pass makes no progress.
    while statements:
        postponed = []
        for name, statement in statements:
            try:
                with session.begin_nested():
                    session.execute(statement)
            except IntegrityError:
                postponed.append((name, statement))
        if len(postponed) == len(statements):
            raise RuntimeError(
                f"cannot purge orgs {org_ids}: no delete order works; blocked tables {[n for n, _ in postponed]}"
            )
        statements = postponed
    organisations = metadata.tables["organisations"]
    session.execute(organisations.delete().where(organisations.c.id.in_(org_ids)))
    session.commit()


def _existing(session, organisations, ids: list[UUID]) -> list[UUID]:
    return [
        row[0]
        for start in range(0, len(ids), _CHUNK)
        for row in session.execute(
            select(organisations.c.id).where(organisations.c.id.in_(ids[start : start + _CHUNK]))
        )
    ]


def purge_orgs(session, org_ids: Iterable[UUID]) -> int:
    """Delete these orgs and everything they own. Returns how many existed.

    Raises if any is still present afterwards: a cleanup that cannot finish must be visible,
    not swallowed, or the leak this exists to stop just goes quiet again.
    """
    wanted = list(org_ids)
    if not wanted:
        # A session that inserted no org (a pure-unit selection) must not need a database at teardown.
        return 0
    session.rollback()
    metadata = _schema(session)
    organisations = metadata.tables["organisations"]
    present = _existing(session, organisations, wanted)
    failures = []
    for start in range(0, len(present), _CHUNK):
        chunk = present[start : start + _CHUNK]
        try:
            _purge_chunk(session, metadata, chunk)
        except Exception as error:  # noqa: BLE001 - collected and re-raised below, never swallowed
            session.rollback()
            failures.append(f"{chunk}: {error}")
    survivors = _existing(session, organisations, present)
    if survivors:
        detail = "; ".join(failures) or "no error was raised"
        raise RuntimeError(f"organisations still present after purge: {survivors} ({detail})")
    return len(present)


def purge_orgs_named(session, names: Iterable[str]) -> int:
    """Purge orgs by exact name: for orgs a separate server process created, which the
    in-process tracker never sees (the live-server signup tests)."""
    wanted = list(names)
    if not wanted:
        return 0
    session.rollback()
    organisations = _schema(session).tables["organisations"]
    ids = [row[0] for row in session.execute(select(organisations.c.id).where(organisations.c.name.in_(wanted)))]
    return purge_orgs(session, ids)
