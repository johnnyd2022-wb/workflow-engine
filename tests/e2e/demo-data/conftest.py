"""Fixtures for the demo-data slice's E2E suite.

`reset_demo_db`'s target org is not a throwaway per-test org (unlike `fresh_user`) — it
is the fixed "Whistlebird Demo" org owning `demo@whistlebird.co.nz`
(`app.features.demo_data.services.resetdb.DEMO_USER_EMAIL`). `demo_org_member` adds a
disposable user to that *existing* org so a "caller who legitimately belongs to the demo
org" can be represented. The fixture creates the demo org on a fresh CI database and
removes it afterward; only that user, and a cross-tenant `fresh_user`, should be able to
trigger the reset.
"""

from __future__ import annotations

import uuid

import pytest

from app.features.demo_data.services.resetdb import DEMO_USER_EMAIL


@pytest.fixture()
def demo_org_member(app_url):
    """A disposable user in the SAME org as demo@whistlebird.co.nz.

    Only the newly created user row is torn down — the demo org and its
    process/execution/inventory rows are the shared fixture `reset_demo_db` itself
    manages, and are left in whatever state the test run leaves them (the same steady
    state a real demo-reset click leaves them in).
    """
    from app.core.db import db_session
    from app.core.db.models.organisation import Organisation
    from app.core.db.models.user import User
    from app.core.db.repositories.user_repo import UserRepository
    from tests.e2e.conftest import purge_org
    from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory, UserFactory

    session = db_session()
    user_repo = UserRepository(session)
    demo_user = user_repo.get_user_by_email(DEMO_USER_EMAIL)
    created_demo_org = demo_user is None
    if created_demo_org:
        demo_org = OrganisationFactory(name="E2E Demo Org")
        demo_user = UserFactory(org_id=demo_org.id, email=DEMO_USER_EMAIL)
        session.commit()
    demo_org_id = demo_user.org_id
    demo_user_id = demo_user.id

    run_id = uuid.uuid4().hex[:8]
    member = UserFactory(org_id=demo_org_id, email=f"e2e-demo-org-member-{run_id}@example.test")
    session.commit()

    record = {"email": member.email, "password": DEFAULT_TEST_PASSWORD, "org_id": str(demo_org_id)}
    member_id = member.id
    try:
        yield record
    finally:
        session.rollback()
        _purge_user_only(session, member_id)
        session.query(User).filter(User.id == member_id).delete(synchronize_session=False)
        if created_demo_org:
            purge_org(session, demo_org_id, demo_user_id)
            session.query(User).filter(User.id == demo_user_id).delete(synchronize_session=False)
            session.query(Organisation).filter(Organisation.id == demo_org_id).delete(synchronize_session=False)
        session.commit()
        db_session.remove()


def _purge_user_only(session, user_id) -> None:
    """Delete rows referencing `user_id` (e.g. the login's audit_logs row), scoped to
    this one throwaway user — never by org_id, which here is the shared, pre-existing
    demo org and must not be touched. Mirrors tests/e2e/conftest.py's `purge_org`
    user_id branch, narrowed to skip the org_id branch entirely."""
    from app.core.db.models.models import Base

    for table in reversed(Base.metadata.sorted_tables):
        if table.name in ("organisations", "users") or "user_id" not in table.c:
            continue
        session.execute(table.delete().where(table.c.user_id == user_id))
    session.commit()
