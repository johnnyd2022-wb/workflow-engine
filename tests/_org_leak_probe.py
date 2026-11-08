"""Driven only by tests/test_org_purge.py, in a subprocess: leaves an org behind on purpose.

Not collected by a normal run (the name does not match `test_*.py`; the same convention as
`_sql_probe.py`). It only runs when asked for by path, so the backstop in tests/conftest.py
can be shown to remove an org that a test's own teardown never did.
"""

import os
from pathlib import Path
from uuid import uuid4

import pytest

from tests.factories import OrganisationFactory, UserFactory

_OUT = os.environ.get("ORG_PURGE_PROBE_OUT")


@pytest.mark.skipif(not _OUT, reason="run by tests/test_org_purge.py, which sets ORG_PURGE_PROBE_OUT")
def test_leaves_an_org_and_a_user_behind(db):
    org = OrganisationFactory()
    UserFactory(org_id=org.id, email=f"probe-{uuid4().hex[:8]}@example.test")
    db.commit()
    Path(_OUT).write_text(str(org.id))
    # no teardown: that is the point
