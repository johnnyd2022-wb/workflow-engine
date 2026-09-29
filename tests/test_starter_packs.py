"""Plan item 2.4c: a starter pack per producer type, with its compliance fields preconfigured."""

from uuid import uuid4

import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.step import Step
from app.core.db.models.user import UserRole
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.features.compliant.modules.nz_alcohol.catalogue import framework_by_slug
from app.features.compliant.modules.nz_alcohol.presets import PRODUCT_TYPES
from app.features.compliant.platform.workflow_rules import completion_constraints
from app.features.compliant.service import ComplianceService
from app.features.process_templates.catalog.registry import FAMILY_METADATA
from app.features.process_templates.catalog.starter_packs import STARTER_PACKS
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export


def test_every_pack_is_well_formed():
    checks = dict(framework_by_slug("np3-food-control")["controls"])
    assert {p.product_type for p in STARTER_PACKS} == {"spirits", "beer", "wine", "cider", "mead", "rtd"}
    for pack in STARTER_PACKS:
        assert pack.product_type in PRODUCT_TYPES and pack.family in FAMILY_METADATA
        assert not pack.steps[0].takes_previous and len(pack.steps) >= 3
        assert all(control_id in checks for control_id, _ in pack.key_checks), pack.id
    assert len({p.final_output for p in STARTER_PACKS}) == len(STARTER_PACKS)


@pytest.fixture
def org(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    client.put("/api/compliant/profile", json={"enabled": True, "industry_module": "nz_alcohol", "settings": {}})
    yield org, client
    db.rollback()
    clear_org_synthetic_data(db, org.id)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def test_apply_a_pack_builds_a_chained_workflow_and_requires_abv(org, db):
    o, client = org
    packs = client.get("/api/core/process-templates/starter-packs").get_json()["packs"]
    assert {p["id"] for p in packs} == {p.id for p in STARTER_PACKS}
    resp = client.post("/api/core/process-templates/starter-packs/cider/apply")
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["created"] and "ABV is now required on “Packaged cider”" in body["compliance_changes"]

    steps = db.query(Step).filter(Step.process_id == body["process_id"]).order_by(Step.position).all()
    assert [s.name for s in steps][0] == "Receive fruit or juice" and len(steps) == 5
    for earlier, later in zip(steps, steps[1:], strict=False):
        assert later.inputs[0]["source_output_id"] == earlier.outputs[0]["id"]
    process = db.get(Process, steps[0].process_id)
    assert process.is_draft

    settings = ComplianceService(db).get_profile(o.id).settings
    assert "cider" in settings["alcohol_product_types"]
    assert {"pattern": "Packaged cider", "match_type": "exact"} in settings["abv_product_rules"]
    labels = {c.prompt_label for c in completion_constraints(db, o.id, steps[-1].id)}
    assert "ABV (%)" in labels
    assert "ABV (%)" not in {c.prompt_label for c in completion_constraints(db, o.id, steps[1].id)}

    again = client.post("/api/core/process-templates/starter-packs/cider/apply")
    assert again.status_code == 200 and again.get_json()["created"] is False
    assert again.get_json()["process_id"] == body["process_id"] and again.get_json()["compliance_changes"] == []
    assert client.post("/api/core/process-templates/starter-packs/nope/apply").status_code == 404


def test_packs_need_the_alcohol_module_and_staff_cant_change_compliance(org, db, flask_app):  # noqa: F811
    o, client = org
    email = f"staff-{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=o.id,
        email=email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        role=UserRole.MEMBER,
        is_active=True,
    )
    db.commit()
    staff = flask_app.test_client()
    staff.environ_base["wsgi.url_scheme"] = "https"
    staff.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert staff.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200
    resp = staff.post("/api/core/process-templates/starter-packs/beer/apply")
    assert resp.status_code == 201 and resp.get_json()["compliance_skipped"] is True
    settings = ComplianceService(db).get_profile(o.id).settings or {}
    assert not settings.get("abv_product_rules")

    client.put("/api/compliant/profile", json={"enabled": False})
    assert client.get("/api/core/process-templates/starter-packs").get_json()["packs"] == []
    assert client.post("/api/core/process-templates/starter-packs/beer/apply").status_code == 404
