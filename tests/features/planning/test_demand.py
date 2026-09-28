"""Persisted demand validation and hostile tenant/permission boundaries."""

from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from app.core.db.models.audit_log import AuditLog
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.step import Step
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.access_policy import allows, requirement_for
from app.core.security.auth_service import AuthService
from app.features.planning import demand_service as service
from app.features.planning.models import PlanningDemand
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.test_compliant_routes import flask_app  # noqa: F401 -- existing app fixture


@pytest.fixture
def demand_world(db):
    org_a = Organisation(id=uuid4(), name=f"Planning A {uuid4()}")
    org_b = Organisation(id=uuid4(), name=f"Planning B {uuid4()}")
    db.add_all([org_a, org_b])
    db.flush()
    outputs = {}
    for org in (org_a, org_b):
        process = Process(id=uuid4(), org_id=org.id, name="Bottle gin", is_draft=False)
        db.add(process)
        db.flush()
        output_id = uuid4()
        outputs[org.id] = output_id
        db.add(
            Step(
                org_id=org.id,
                process_id=process.id,
                step_number=1,
                position=1000,
                name="Bottle",
                outputs=[{"id": str(output_id), "name": "Gin", "quantity": "100", "unit": "bottles"}],
                inputs=[],
                execution_prompts=[],
            )
        )
    db.flush()
    try:
        yield org_a.id, org_b.id, outputs
    finally:
        db.rollback()


def payload(output_id, **changes):
    return {
        "reference": "ORDER-600",
        "source_output_id": str(output_id),
        "quantity": "600",
        "due_date": "2026-10-10",
        "priority": 10,
        **changes,
    }


def test_demand_persists_exact_quantity_and_server_owned_unit(db, demand_world):
    org_a, _, outputs = demand_world
    row = service.create_demand(db, org_a, payload(outputs[org_a]))
    assert row.quantity == Decimal(600)
    assert row.unit == "bottles"
    assert row.due_date == date(2026, 10, 10)
    assert row.status == "open"
    assert service.list_demands(db, org_a)[0]["id"] == str(row.id)


def test_foreign_output_and_scope_injection_refused(db, demand_world):
    org_a, org_b, outputs = demand_world
    with pytest.raises(ValueError, match="this business"):
        service.create_demand(db, org_a, payload(outputs[org_b]))
    with pytest.raises(ValueError, match="Unexpected"):
        service.create_demand(db, org_a, payload(outputs[org_a], org_id=str(org_b)))
    with pytest.raises(ValueError, match="Unexpected"):
        service.create_demand(db, org_a, payload(outputs[org_a], unit="cases"))
    assert db.query(PlanningDemand).count() == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": "NaN"},
        {"quantity": "Infinity"},
        {"quantity": "-1"},
        {"quantity": "0"},
        {"quantity": "1.5"},
        {"quantity": "1.00001"},
        {"quantity": "100000000000000"},
        {"quantity": True},
        {"due_date": "2026-02-31"},
        {"due_date": None},
        {"priority": True},
        {"priority": "1"},
        {"priority": -1},
        {"priority": 101},
        {"reference": ""},
        {"reference": " "},
        {"reference": "x" * 201},
        {"source_output_id": "invalid"},
    ],
)
def test_invalid_demand_does_not_create_rows(db, demand_world, changes):
    org_a, _, outputs = demand_world
    with pytest.raises(ValueError):
        service.create_demand(db, org_a, payload(outputs[org_a], **changes))
    assert db.query(PlanningDemand).count() == 0


def test_lists_and_cancellation_require_same_org(db, demand_world):
    org_a, org_b, outputs = demand_world
    row = service.create_demand(db, org_a, payload(outputs[org_a]))
    assert service.list_demands(db, org_b) == []
    assert service.cancel_demand(db, org_b, row.id) is None
    assert row.status == "open"
    assert service.cancel_demand(db, org_a, row.id).status == "cancelled"
    assert service.cancel_demand(db, org_a, row.id).status == "cancelled"


def test_fulfilled_demand_is_not_cancelled(db, demand_world):
    org_a, _, outputs = demand_world
    row = service.create_demand(db, org_a, payload(outputs[org_a]))
    row.status = "fulfilled"
    db.flush()
    with pytest.raises(ValueError, match="fulfilled"):
        service.cancel_demand(db, org_a, row.id)
    assert row.status == "fulfilled"


def test_due_date_then_priority_order(db, demand_world):
    org_a, _, outputs = demand_world
    service.create_demand(db, org_a, payload(outputs[org_a], reference="later", due_date="2026-10-11", priority=100))
    service.create_demand(db, org_a, payload(outputs[org_a], reference="normal", priority=0))
    service.create_demand(db, org_a, payload(outputs[org_a], reference="urgent", priority=50))
    assert [row["reference"] for row in service.list_demands(db, org_a)] == ["urgent", "normal", "later"]


def test_demand_route_policy_preserves_staff_role_boundaries():
    class Actor:
        def __init__(self, role):
            self.role = role

    assert requirement_for("planning.get_demands", "GET") == "production.view"
    assert requirement_for("planning.add_demand", "POST") == "production.record"
    assert allows(Actor(UserRole.PRODUCTION), "planning.add_demand", "POST")
    assert allows(Actor(UserRole.AUDITOR), "planning.get_demands", "GET")
    assert not allows(Actor(UserRole.AUDITOR), "planning.add_demand", "POST")
    assert not allows(Actor(UserRole.SALES), "planning.get_demands", "GET")


def test_mutation_and_audit_roll_back_together(db, demand_world):
    org_a, _, outputs = demand_world
    row = service.create_demand(db, org_a, payload(outputs[org_a]))
    row_id = row.id
    db.add(AuditLog(org_id=org_a, action="planning_demand_created", entity="planning_demand", entity_id=row_id))
    db.flush()
    db.rollback()
    assert db.query(PlanningDemand).filter(PlanningDemand.id == row_id).first() is None
    assert db.query(AuditLog).filter(AuditLog.entity_id == row_id).first() is None


@pytest.fixture
def demand_clients(db, flask_app):  # noqa: F811
    org_ids = []
    clients = []
    for role in (UserRole.PRODUCTION, UserRole.PRODUCTION, UserRole.AUDITOR):
        org = Organisation(id=uuid4(), name=f"Planning HTTP {uuid4()}")
        db.add(org)
        db.commit()
        org_ids.append(org.id)
        output_id = uuid4()
        process = Process(id=uuid4(), org_id=org.id, name="Gin", is_draft=False)
        db.add(process)
        db.flush()
        db.add(
            Step(
                org_id=org.id,
                process_id=process.id,
                step_number=1,
                position=1000,
                name="Bottle",
                outputs=[{"id": str(output_id), "name": "Gin", "unit": "bottles"}],
                inputs=[],
                execution_prompts=[],
            )
        )
        email = f"planner-{uuid4()}@test.com"
        UserRepository(db).create_user(
            org_id=org.id,
            email=email,
            role=role,
            is_active=True,
            password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        )
        db.commit()
        client = flask_app.test_client()
        client.environ_base.update({"wsgi.url_scheme": "https", "HTTP_X_FORWARDED_PROTO": "https"})
        assert client.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200
        clients.append((client, org.id, output_id))
    try:
        yield clients
    finally:
        db.rollback()
        for model in (PlanningDemand, AuditLog, Step, Process, User, Organisation):
            column = model.id if model is Organisation else model.org_id
            db.query(model).filter(column.in_(org_ids)).delete(synchronize_session=False)
        db.commit()


def test_actual_routes_create_list_cancel_and_audit(db, demand_clients):
    client, org_id, output_id = demand_clients[0]
    assert client.get("/core/planner").status_code == 200
    response = client.post("/api/core/planner/demands", json=payload(output_id))
    assert response.status_code == 201
    demand_id = response.get_json()["id"]
    rows = client.get("/api/core/planner/demands").get_json()["demands"]
    assert [row["id"] for row in rows] == [demand_id]
    assert client.post(f"/api/core/planner/demands/{demand_id}/cancel").status_code == 200
    audit = db.query(AuditLog).filter(AuditLog.org_id == org_id, AuditLog.entity_id == demand_id).all()
    assert {row.action for row in audit} == {"planning_demand_created", "planning_demand_cancelled"}
    assert all(row.user_id is not None for row in audit)


def test_http_cross_tenant_ids_and_auditor_writes_are_refused(demand_clients):
    first, _, output_id = demand_clients[0]
    other, _, other_output = demand_clients[1]
    auditor, _, auditor_output = demand_clients[2]
    created = first.post("/api/core/planner/demands", json=payload(output_id)).get_json()
    assert other.get("/api/core/planner/demands").get_json()["demands"] == []
    assert other.post(f"/api/core/planner/demands/{created['id']}/cancel").status_code == 404
    assert first.post("/api/core/planner/demands", json=payload(other_output)).status_code == 400
    assert auditor.get("/api/core/planner/demands").status_code == 200
    assert auditor.post("/api/core/planner/demands", json=payload(auditor_output)).status_code == 403


def test_phone_workspace_creates_and_cancels_demand_without_overflow(demand_clients, browser):
    client, _, output_id = demand_clients[0]
    page = browser.new_page(viewport={"width": 390, "height": 844})

    def proxy(route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.netloc != "planner.test":
            route.abort()
            return
        response = client.open(
            parsed.path + ("?" + parsed.query if parsed.query else ""),
            method=request.method,
            data=request.post_data,
            headers={"Content-Type": request.headers.get("content-type", "application/json")},
        )
        route.fulfill(status=response.status_code, body=response.data, headers={"Content-Type": response.content_type})

    page.route("**/*", proxy)
    try:
        page.goto("https://planner.test/core/planner")
        page.locator('[data-output-select] option[value="' + str(output_id) + '"]').wait_for(state="attached")
        page.locator('[name="reference"]').fill("Phone order <script>alert(1)</script>")
        page.locator('[name="source_output_id"]').select_option(str(output_id))
        page.locator('[name="quantity"]').fill("600")
        page.locator('[name="due_date"]').fill("2026-10-10")
        page.get_by_role("button", name="Add demand").click()
        page.get_by_role("heading", name="Phone order <script>alert(1)</script>").wait_for()
        assert page.locator("[data-demand-list] script").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.locator("[data-planning-root] input, [data-planning-root] select").evaluate_all(
            "elements => elements.every(el => { const r = el.getBoundingClientRect(); "
            "return r.left >= 0 && r.right <= window.innerWidth; })"
        )
        page.get_by_role("button", name="Cancel demand").click()
        page.get_by_text("Due 2026-10-10 · Priority 0 · cancelled", exact=True).wait_for()
        assert page.get_by_role("button", name="Cancel demand").count() == 0
    finally:
        page.close()


def test_csrf_required_for_real_demand_mutation(demand_clients, flask_app):  # noqa: F811
    from html.parser import HTMLParser

    class TokenParser(HTMLParser):
        token = None

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == "meta" and attributes.get("name") == "csrf-token":
                self.token = attributes.get("content")

    client, _, output_id = demand_clients[0]
    previous = flask_app.config["WTF_CSRF_ENABLED"]
    flask_app.config["WTF_CSRF_ENABLED"] = True
    try:
        assert client.post("/api/core/planner/demands", json=payload(output_id)).status_code == 400
        parser = TokenParser()
        parser.feed(client.get("/core/planner").get_data(as_text=True))
        assert parser.token
        response = client.post(
            "/api/core/planner/demands",
            json=payload(output_id),
            headers={"X-CSRFToken": parser.token, "Referer": "https://localhost/core/planner"},
        )
        assert response.status_code == 201
    finally:
        flask_app.config["WTF_CSRF_ENABLED"] = previous


@pytest.mark.parametrize("invalid_unit", ["x" * 51, "", "   ", {"unit": "bottles"}, 42])
def test_invalid_workflow_unit_is_not_offered_or_persisted(db, demand_world, invalid_unit):
    org_a, _, outputs = demand_world
    step = db.query(Step).filter(Step.org_id == org_a).one()
    step.outputs = [{"id": str(outputs[org_a]), "name": "Gin", "unit": invalid_unit}]
    db.flush()
    assert service.output_catalog(db, org_a) == []
    with pytest.raises(ValueError, match="this business"):
        service.create_demand(db, org_a, payload(outputs[org_a]))
    assert db.query(PlanningDemand).count() == 0
