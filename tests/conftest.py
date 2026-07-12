"""Shared pytest fixtures.

Before this file, every test that needed a DB session or an isolated org/user pair
redefined its own local `db` fixture and hand-rolled the setup/teardown (see
.agents/conventions.md §6). This is the single source going forward; owned by the
test-fixtures skill. Existing per-file `db` fixtures still work (a local fixture shadows
this one), so nothing already passing needed to change.
"""

import pytest

from app.core.db import db_session
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User
from tests.factories import OrganisationFactory, UserFactory


@pytest.fixture
def db():
    """Per-test DB session, closed and removed after the test regardless of outcome."""
    session = db_session()
    try:
        yield session
    finally:
        session.close()
        db_session.remove()


@pytest.fixture
def two_org_two_user(db):
    """The seeded two-org/two-user world that tenant-isolation tests need: a hostile
    neighbor org must exist to prove a query can't see across it. security-audit's
    isolation checks and e2e-playwright's cross-tenant probe both assume this shape —
    use this fixture rather than reseeding it per test file.
    """
    org_a = OrganisationFactory()
    org_b = OrganisationFactory()
    user_a = UserFactory(org_id=org_a.id)
    user_b = UserFactory(org_id=org_b.id)
    db.commit()

    yield {"org_a": org_a, "org_b": org_b, "user_a": user_a, "user_b": user_b}

    db.query(User).filter(User.org_id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
    db.commit()
