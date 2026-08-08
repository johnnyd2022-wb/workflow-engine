"""Fixtures for the traceability (sourcemap) E2E suite.

Seeds a real R1 -> W1 -> F1 production chain through the same repository code the app
itself uses (`tests/dag_traversal_helpers.build_linear_dag` -- already the shared helper
`tests/test_dag_traversal.py` builds synthetic DAGs with) rather than re-driving the full
multi-step execution UI: that spine is already proven end to end by
`tests/e2e/test_workflow_flow.py` / `tests/e2e/test_execution_flow.py`. This suite is about
what the sourcemap page does with an existing chain, not about re-proving execution
completion.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from tests.dag_traversal_helpers import build_linear_dag
from tests.e2e.conftest import attach_probe, login_through_ui


@pytest.fixture()
def traced_chain(browser, app_url, fresh_user):
    """A fresh org with its own logged-in page, seeded with a real R1->W1->F1 chain.

    Yields (page, dag, user). `dag` has r1_id/w1_id/f1_id/process_id/execution_id (see
    build_linear_dag). `fresh_user`'s own teardown purges every row this creates -- it
    walks the schema by org_id/user_id -- so no extra cleanup is needed here.
    """
    from app.core.db import db_session

    user = fresh_user()
    dag = build_linear_dag(db_session(), UUID(user["org_id"]))

    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    try:
        yield page, dag, user
    finally:
        context.close()


@pytest.fixture()
def two_tenants_with_chains(browser, app_url, fresh_user):
    """Two orgs, each with its own logged-in page and its own R1->W1->F1 chain.

    The cross-tenant twin of `traced_chain` -- org A's dag ids are handed to org B's
    authenticated `page.request` so probes exercise the real browser session's cookies,
    not a bypass.
    """
    from app.core.db import db_session

    def _build():
        user = fresh_user()
        dag = build_linear_dag(db_session(), UUID(user["org_id"]))
        context = browser.new_context(base_url=app_url, ignore_https_errors=True)
        page = context.new_page()
        attach_probe(page)
        login_through_ui(page, user["email"], user["password"])
        return {"user": user, "dag": dag, "page": page, "context": context}

    org_a = _build()
    org_b = _build()
    try:
        yield {"a": org_a, "b": org_b}
    finally:
        org_a["context"].close()
        org_b["context"].close()
