"""Plan item 0.4: staff roles, permissions, and the endpoint policy table.

The policy table (app/core/security/access_policy.py) is default-deny, so the most
important test here is the first: every route the app serves has an explicit rule.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.access_policy import (
    DENY,
    PERMISSIONS,
    POLICY,
    PORTAL_SIGNED_IN,
    PUBLIC,
    ROLE_PERMISSIONS,
    SIGNED_IN,
    allows,
    requirement_for,
)
from app.core.security.auth_service import AuthService
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

PASSWORD = DEFAULT_TEST_PASSWORD


def _all_routes():
    # app/app.py adds the top-level pages (/, /dashboard, /healthcheck, /initialize) on
    # top of create_app(); import it so those are covered too.
    import app.app as app_module

    for rule in app_module.app.url_map.iter_rules():
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            yield rule.endpoint, method, rule.rule


def test_every_route_has_an_explicit_rule():
    """Default deny means an unclassified route is unusable. Add a POLICY rule for it."""
    unclassified = [(e, m, r) for e, m, r in _all_routes() if requirement_for(e, m) == DENY]
    assert unclassified == []


def test_policy_only_names_real_permissions():
    for _pattern, _methods, requirement in POLICY:
        required = requirement if isinstance(requirement, tuple) else (requirement,)
        for req in required:
            assert req in PERMISSIONS or req in (PUBLIC, SIGNED_IN, PORTAL_SIGNED_IN), req


def test_every_role_has_a_permission_set_and_admin_has_everything():
    assert set(ROLE_PERMISSIONS) == set(UserRole)
    assert ROLE_PERMISSIONS[UserRole.ADMIN] == frozenset(PERMISSIONS)
    for perms in ROLE_PERMISSIONS.values():
        assert perms <= set(PERMISSIONS)


class _FakeUser:
    def __init__(self, role):
        self.role = role


def _matrix():
    """role x route -> allowed, generated from the one table (plan 0.4 f)."""
    return {
        (role, endpoint, method): allows(_FakeUser(role), endpoint, method)
        for role in UserRole
        for endpoint, method, _rule in _all_routes()
    }


def test_role_route_matrix_respects_the_role_boundaries():
    matrix = _matrix()

    def allowed(role, endpoint, method="GET"):
        return matrix[(role, endpoint, method)]

    # Production: records batches and stock, never sees sales or revenue.
    assert allowed(UserRole.PRODUCTION, "core.complete_step", "POST")
    assert allowed(UserRole.PRODUCTION, "core.create_inventory_item", "POST")
    assert not allowed(UserRole.PRODUCTION, "crm.crm_api.crm_overview")
    assert not allowed(UserRole.PRODUCTION, "crm.crm_api.get_org_invoices")
    assert not allowed(UserRole.PRODUCTION, "core.create_process", "POST")  # no design

    # Sales: customers and finished stock on hand; no recipes, no production records.
    assert allowed(UserRole.SALES, "crm.crm_api.list_customers")
    assert allowed(UserRole.SALES, "core.list_inventory")
    assert allowed(UserRole.SALES, "core.sourcemap_trace", "POST")  # recall tracing
    assert not allowed(UserRole.SALES, "core.get_process")
    assert not allowed(UserRole.SALES, "core.list_executions")
    assert not allowed(UserRole.SALES, "core.flows_create")

    # Auditor: read-only everywhere.
    assert allowed(UserRole.AUDITOR, "core.list_executions")
    assert allowed(UserRole.AUDITOR, "crm.crm_api.list_customers")
    assert allowed(UserRole.AUDITOR, "compliant.compliant_api.np3_audit")
    for (role, endpoint, method), ok in matrix.items():
        if role == UserRole.AUDITOR and ok and method != "GET":
            assert requirement_for(endpoint, method) in (PUBLIC, SIGNED_IN) or endpoint in {
                # POST endpoints that only read
                "core.sourcemap_trace",
                "core.decode_barcode",
                "compliant.compliant_tools.tools_solve",
            }, (endpoint, method)

    # Staff (member) keeps exactly what a member could do before roles.
    assert allowed(UserRole.MEMBER, "crm.crm_oauth.xero_sync", "POST")
    assert allowed(UserRole.MEMBER, "core.create_process", "POST")
    assert not allowed(UserRole.MEMBER, "org.create_user", "POST")
    assert not allowed(UserRole.MEMBER, "compliant.compliant_api.update_profile", "PUT")


# --- HTTP-level ---------------------------------------------------------------------------


@pytest.fixture
def org(db):
    org = OrganisationFactory()
    db.commit()
    org_id = org.id
    repo = UserRepository(db)
    users = {}
    for role in UserRole:
        email = f"{role.value}_{uuid4()}@test.com"
        u = repo.create_user(org_id=org_id, email=email, password_hash=AuthService.hash_password(PASSWORD), role=role)
        db.commit()
        users[role] = {"email": email, "id": u.id}

    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    def client_for(role):
        c = flask_app.test_client()
        c.environ_base["wsgi.url_scheme"] = "https"
        c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        resp = c.post("/auth/login", json={"email": users[role]["email"], "password": PASSWORD})
        assert resp.status_code == 200, resp.get_json()
        return c

    with flask_app.app_context():
        yield {"users": users, "client_for": client_for, "app": flask_app, "org_id": org_id}

    db.rollback()
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


def test_production_user_gets_403_from_sales_and_sees_no_revenue(org):
    c = org["client_for"](UserRole.PRODUCTION)
    for path in ("/api/crm/overview", "/api/crm/customers", "/api/crm/invoices", "/api/crm/analytics/monthly-sales"):
        resp = c.get(path)
        assert resp.status_code == 403, path
        assert resp.get_json()["code"] == "permission_denied"
    summary = c.get("/api/core/dashboard/summary").get_json()
    assert summary["sales"]["enabled"] is False
    assert summary["sales"]["current_month_revenue"] == 0.0
    page = c.get("/core/dashboard").get_data(as_text=True)
    assert "Commercial pulse" not in page
    assert 'href="/crm"' not in page  # nav and workspace card hidden
    me = c.get("/auth/me").get_json()["user"]
    assert "sales.view" not in me["permissions"]
    assert me["role_label"] == "Production"


def test_sales_user_cannot_open_process_design_but_sees_stock(org):
    c = org["client_for"](UserRole.SALES)
    assert c.post("/api/core/processes", json={"name": "x"}).status_code == 403
    assert c.get("/api/core/processes").status_code == 403
    assert c.get("/api/core/inventory").status_code == 200
    denied_page = c.get("/core/flows/create", headers={"Accept": "text/html"})
    assert denied_page.status_code == 302
    assert "/core/dashboard" in denied_page.headers["Location"]


def test_auditor_is_read_only_and_expires(org, db):
    c = org["client_for"](UserRole.AUDITOR)
    assert c.get("/api/core/executions").status_code == 200
    assert c.post("/api/core/executions", json={}).status_code == 403

    user = db.get(User, org["users"][UserRole.AUDITOR]["id"])
    user.access_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    resp = c.get("/api/core/executions")
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "access_expired"
    # And signing in again doesn't help.
    again = org["app"].test_client()
    again.environ_base["wsgi.url_scheme"] = "https"
    again.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    login = again.post("/auth/login", json={"email": org["users"][UserRole.AUDITOR]["email"], "password": PASSWORD})
    assert login.status_code == 401
    assert login.get_json()["code"] == "access_expired"


def test_member_keeps_todays_access(org):
    c = org["client_for"](UserRole.MEMBER)
    assert c.get("/api/crm/overview").status_code == 200
    assert c.get("/api/core/processes").status_code == 200
    assert c.post("/org/users", json={"email": "x@example.test"}).status_code == 403
