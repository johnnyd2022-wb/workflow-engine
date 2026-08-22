"""Fixtures for the Compliant platform E2E suite (.agents/specs/compliant-platform.md).

Seeds through the real APIs (`page.request`, the same authenticated browser-session
cookies a real user has) rather than writing rows directly, so every test proves the whole
stack (route -> service -> org_id filter), not just the service function.

No `__init__.py` here on purpose: the directory name mirrors the spec slug
(`compliant-platform`, hyphenated), which is not a valid Python package identifier. Without
an `__init__.py`, pytest's default "prepend" import mode collects and imports each file
here by file path under its own basename instead of walking it as a package, so the hyphen
is never asked to be a dotted import segment. The seed helpers below are therefore plain
fixtures (auto-discovered by every test file in this directory) rather than functions a
test file would need to `import` from this module by dotted path -- that import is exactly
what the hyphen would break.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.db.models.user import UserRole
from tests.e2e.conftest import attach_probe, csrf_headers, login_through_ui

# customs-alcohol/product-mapping carries no CONTROL_REQUIREMENTS entry (see
# app/features/compliant/modules/nz_alcohol/catalogue.py), so it is the simplest control
# for a happy-path record: only the always-required fields (record_type, status, title)
# apply, with no period/evidence/source_ref/field capture requirements to also satisfy.
SIMPLE_FRAMEWORK_SLUG = "customs-alcohol"
SIMPLE_CONTROL_ID = "product-mapping"


@pytest.fixture()
def admin_page(browser, app_url, fresh_user):
    """A single logged-in page for an ADMIN in its own fresh org.

    Most Compliant writes (`PUT /profile`, `POST /alcohol-products`) require ADMIN, and a
    plain member can still do everything else through the same session, so this is the
    default identity for single-org flow tests.
    """
    user = fresh_user(role=UserRole.ADMIN)
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    yield page
    context.close()


@pytest.fixture()
def member_page(browser, app_url, fresh_user):
    """A logged-in page for a plain MEMBER, in its own fresh org -- for the ADMIN-gate
    (403) checks on `PUT /profile` and `POST /alcohol-products`."""
    user = fresh_user(role=UserRole.MEMBER)
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    yield page
    context.close()


@pytest.fixture()
def admin_and_member_pages(browser, app_url, fresh_user):
    """An ADMIN and a plain MEMBER logged in as separate pages, *in the same org* --
    `fresh_user` alone always mints a brand-new org per call, which cannot prove a
    same-org, cross-role flow like "an ADMIN enables Compliant, then a MEMBER attests a
    record" (the ADMIN-gated PUT /profile has to succeed on the SAME org the MEMBER's
    later POST /records is scoped to).
    """
    from app.core.db import db_session
    from app.core.db.models.organisation import Organisation
    from app.core.db.models.user import User
    from tests.e2e.conftest import purge_org
    from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory, UserFactory

    session = db_session()
    run_id = uuid.uuid4().hex[:8]
    org = OrganisationFactory(name=f"E2E Compliant Same-Org {run_id}")
    admin_user = UserFactory(org_id=org.id, email=f"e2e-compliant-admin-{run_id}@example.test", role=UserRole.ADMIN)
    member_user = UserFactory(org_id=org.id, email=f"e2e-compliant-member-{run_id}@example.test", role=UserRole.MEMBER)
    session.commit()

    contexts = []

    def _sign_in(email: str):
        context = browser.new_context(base_url=app_url, ignore_https_errors=True)
        contexts.append(context)
        page = context.new_page()
        attach_probe(page)
        login_through_ui(page, email, DEFAULT_TEST_PASSWORD)
        return page

    admin_page_ = _sign_in(admin_user.email)
    member_page_ = _sign_in(member_user.email)
    try:
        yield {"admin": admin_page_, "member": member_page_}
    finally:
        for context in contexts:
            context.close()
        session.rollback()
        purge_org(session, org.id, admin_user.id)
        session.query(User).filter(User.id.in_([admin_user.id, member_user.id])).delete(synchronize_session=False)
        session.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        session.commit()


@pytest.fixture()
def two_tenants(browser, app_url, fresh_user):
    """Two orgs, each with its own ADMIN-role logged-in page.

    ADMIN on both sides so either side can exercise the admin-gated writes (profile,
    alcohol products) that seed the cross-tenant probes in test_tenant_isolation.py.
    """
    contexts = []

    def _sign_in():
        user = fresh_user(role=UserRole.ADMIN)
        context = browser.new_context(base_url=app_url, ignore_https_errors=True)
        contexts.append(context)
        page = context.new_page()
        attach_probe(page)
        login_through_ui(page, user["email"], user["password"])
        return page

    pages = {"a": _sign_in(), "b": _sign_in()}
    yield pages
    for context in contexts:
        context.close()


@pytest.fixture()
def enable_profile():
    """`PUT /api/compliant/profile`. Returns the refreshed profile view."""

    def _enable(page, *, enabled: bool = True, settings: dict | None = None, **extra) -> dict:
        payload: dict = {"enabled": enabled}
        if settings is not None:
            payload["settings"] = settings
        payload.update(extra)
        response = page.request.put("/api/compliant/profile", headers=csrf_headers(page), data=payload)
        assert response.status == 200, f"enable_profile failed: {response.status} {response.text()}"
        return response.json()["profile"]

    return _enable


@pytest.fixture()
def create_alcohol_product():
    def _create(
        page,
        inventory_name: str,
        *,
        product_type: str = "spirits",
        abv_percent: str = "40",
        customs_product_code: str | None = None,
    ) -> str:
        payload = {"inventory_name": inventory_name, "product_type": product_type, "abv_percent": abv_percent}
        if customs_product_code is not None:
            payload["customs_product_code"] = customs_product_code
        response = page.request.post("/api/compliant/alcohol-products", headers=csrf_headers(page), data=payload)
        assert response.status == 201, f"create_alcohol_product failed: {response.status} {response.text()}"
        return response.json()["product"]["id"]

    return _create


@pytest.fixture()
def create_record():
    def _create(
        page,
        *,
        framework_slug: str = SIMPLE_FRAMEWORK_SLUG,
        control_id: str = SIMPLE_CONTROL_ID,
        record_type: str = "attestation",
        title: str,
        status: str = "complete",
        **extra,
    ) -> dict:
        payload = {
            "framework_slug": framework_slug,
            "control_id": control_id,
            "record_type": record_type,
            "status": status,
            "title": title,
            **extra,
        }
        response = page.request.post("/api/compliant/records", headers=csrf_headers(page), data=payload)
        assert response.status == 201, f"create_record failed: {response.status} {response.text()}"
        return response.json()["record"]

    return _create


@pytest.fixture()
def create_core_execution():
    """A real Core Execution to use as a `source_refs` target -- `invalid_core_source_references`
    (service.py) checks a claimed source_ref against the actual Execution/ExecutionEvidence/
    ExecutionStep/InventoryMovement tables, filtered by org_id, so the cross-tenant
    source_refs probe needs a genuine org-scoped Core row, not just any UUID-shaped string.
    Mirrors tests/e2e/dashboard/conftest.py's create_process/start_execution.
    """

    def _create(page) -> str:
        process_resp = page.request.post(
            "/api/core/processes",
            headers=csrf_headers(page),
            data={
                "name": f"Compliant e2e process {uuid.uuid4().hex[:8]}",
                "category": "manufacturing",
                "is_draft": True,
            },
        )
        assert process_resp.status in (200, 201), f"seed process failed: {process_resp.status} {process_resp.text()}"
        process_id = process_resp.json()["id"]

        execution_resp = page.request.post(
            "/api/core/executions", headers=csrf_headers(page), data={"process_id": process_id}
        )
        assert execution_resp.status in (200, 201), (
            f"seed execution failed: {execution_resp.status} {execution_resp.text()}"
        )
        execution_id = execution_resp.json().get("id")
        assert execution_id, f"no execution id in response: {execution_resp.text()}"
        return execution_id

    return _create


@pytest.fixture()
def create_report():
    def _create(page, framework_slug: str = SIMPLE_FRAMEWORK_SLUG, **body) -> dict:
        response = page.request.post(f"/api/compliant/reports/{framework_slug}", headers=csrf_headers(page), data=body)
        assert response.status == 201, f"create_report failed: {response.status} {response.text()}"
        return response.json()

    return _create
