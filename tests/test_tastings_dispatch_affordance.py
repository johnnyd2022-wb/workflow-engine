"""The Tasks page only offers stock removal to people the endpoint will let do it.

Finding F2 of ``.agents/reports/tastings/html-js-review.md``: the dispatch form was
shown to anyone holding ``inventory.adjust``, but ``POST /api/crm/tastings/<id>/dispatch``
also needs ``sales.record``, so a stock-only role saw a form that could only return 403.
``data-can-dispatch`` on the Tastings root is what ``tastings.js`` reads to decide, so
this checks it against the endpoint's actual answer rather than restating the rule.
"""

import re
from uuid import uuid4

import pytest

from app.core.db.models.org_role import OrgRole
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User
from app.features.compliant.service import ComplianceService
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export

# name -> permissions. "Stockroom" is the finding's role: it can adjust stock and read sales,
# but cannot record a sale, so the dispatch POST is refused by the policy table.
ROLES = {
    "Counter": ["sales.view", "sales.record"],
    "Stockroom": ["sales.view", "inventory.adjust"],
    "Counter and stockroom": ["sales.view", "sales.record", "inventory.adjust"],
}


def _flag(html: str, name: str) -> bool:
    found = re.search(rf'<div class="tasting-workspace"[^>]*\bdata-{name}="(true|false)"', html, re.S)
    assert found, f"data-{name} missing: the Tastings root was not rendered on /crm/tasks"
    return found.group(1) == "true"


def _login(flask_app, email):  # noqa: F811
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200
    return client


@pytest.fixture
def tasting_org(db, flask_app):  # noqa: F811
    org, admin = _admin_client(db, flask_app)
    ComplianceService(db).upsert_profile(org.id, {"enabled": True, "industry_module": "nz_alcohol"})
    db.commit()
    yield org, admin
    db.rollback()
    db.query(User).filter(User.org_id == org.id).update({User.custom_role_id: None}, synchronize_session=False)
    db.query(OrgRole).filter(OrgRole.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    clear_org_synthetic_data(db, org.id)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def _person_with(admin, name, permissions):
    made = admin.post("/org/roles", json={"name": name, "base_role": "sales", "permissions": permissions})
    assert made.status_code == 201, made.get_json()
    role = next(r for r in made.get_json()["custom_roles"] if r["name"] == name)
    email = f"tasting-{uuid4()}@test.com"
    created = admin.post("/org/users", json={"email": email, "password": DEFAULT_TEST_PASSWORD, "role": role["value"]})
    assert created.status_code == 201, created.get_json()
    return email


def _dispatch_is_refused(client) -> bool:
    """Whether the real endpoint answers 403. An unknown tasting is a 4xx other than 403 once let through."""
    response = client.post(
        f"/api/crm/tastings/{uuid4()}/dispatch",
        json={"actual_date": "2026-10-20"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code < 500, response.get_data(as_text=True)
    return response.status_code == 403


def test_dispatch_form_is_offered_only_when_the_endpoint_will_accept_it(tasting_org, flask_app):  # noqa: F811
    _org, admin = tasting_org
    clients = {"Admin": admin}
    clients.update({name: _login(flask_app, _person_with(admin, name, perms)) for name, perms in ROLES.items()})

    offered = {}
    for name, client in clients.items():
        page = client.get("/crm/tasks")
        assert page.status_code == 200, name
        offered[name] = _flag(page.get_data(as_text=True), "can-dispatch")
        assert offered[name] is (not _dispatch_is_refused(client)), name

    # Pin the cases the finding is about, so the comparison above cannot pass by every role agreeing.
    assert offered == {"Admin": True, "Counter": False, "Stockroom": False, "Counter and stockroom": True}
