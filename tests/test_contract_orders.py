"""Contract demand, hostile reference checks and staff permission boundaries (7.2a)."""

import re
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.organisation import Organisation
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.user import UserRole
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.security.access_policy import DENY, POLICY, requirement_for
from app.features.contract_manufacturing.models import (
    ContractCustomer,
    ContractOrder,
    ContractOrderExecution,
    ContractOrderLine,
)
from app.features.contract_manufacturing.services.demand import contract_demand
from app.features.contract_manufacturing.services.orders import ContractOrderService
from app.features.crm.models.xero_contact import XeroContact
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.factories import DEFAULT_TEST_PASSWORD, ExecutionFactory, OrganisationFactory, ProcessFactory, UserFactory
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture

API = "/api/core/contract-orders"
CUSTOMERS = "/api/core/contract-customers"


def _login(app, user):
    client = app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    response = client.post("/auth/login", json={"email": user.email, "password": DEFAULT_TEST_PASSWORD})
    assert response.status_code == 200, response.get_json()
    return client


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    organisations = [OrganisationFactory(), OrganisationFactory()]
    clients = []
    for org in organisations:
        user = UserFactory(org_id=org.id, role=UserRole.ADMIN, email=f"contract-{uuid4()}@test.com")
        clients.append(_login(flask_app, user))
    yield {"orgs": organisations, "clients": clients, "app": flask_app}
    db.rollback()
    org_ids = [org.id for org in organisations]
    for model in (ContractOrderExecution, ContractOrderLine, ContractOrder, ContractCustomer):
        db.query(model).filter(model.org_id.in_(org_ids)).delete(synchronize_session=False)
    db.query(XeroContact).filter(XeroContact.org_id.in_(org_ids)).delete(synchronize_session=False)
    db.commit()
    for org_id in org_ids:
        clear_org_synthetic_data(db, org_id)
    db.query(Organisation).filter(Organisation.id.in_(org_ids)).delete(synchronize_session=False)
    db.commit()


def _customer(client, name="Brand owner"):
    response = client.post(CUSTOMERS, json={"name": name})
    assert response.status_code == 201, response.get_json()
    return response.get_json()["customer"]


def _order(client, customer_id, **changes):
    body = {
        "customer_id": customer_id,
        "reference": f"CO-{uuid4().hex[:8]}",
        "due_date": "2026-11-20",
        "status": "confirmed",
        "duty_responsibility": "producer_licensee",
        "lines": [{"product_name": "Gin", "quantity": "600", "unit": "bottles", "materials_source": "mixed"}],
    }
    body.update(changes)
    response = client.post(API, json=body)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["order"]


def _recipe(db, org_id, name="Private recipe"):
    process = ProcessFactory(org_id=org_id, name=name)
    output_id = uuid4()
    ProcessRepository(db).add_step(
        org_id=org_id,
        process_id=process.id,
        step_number=1,
        position=1000,
        name="Bottle",
        inputs=[],
        outputs=[{"id": str(output_id), "name": "Gin", "quantity": 600, "unit": "bottles"}],
    )
    version = (
        db.query(ProcessVersion)
        .filter(ProcessVersion.process_id == process.id)
        .order_by(ProcessVersion.version_number.desc())
        .first()
    )
    return process, version, output_id


def test_orders_work_without_crm_and_export_stable_gross_demand(world, db):
    org = world["orgs"][0]
    client = world["clients"][0]
    customer = _customer(client)
    process, version, output_id = _recipe(db, org.id)
    order = _order(
        client,
        customer["id"],
        lines=[
            {
                "product_name": "Gin",
                "quantity": "600",
                "unit": "bottles",
                "materials_source": "customer",
                "spec_reference": "Brand spec v3",
                "process_version_id": str(version.id),
                "source_output_id": str(output_id),
            },
            {"product_name": "Botanical spirit", "quantity": "1.2500", "unit": "L", "materials_source": "producer"},
        ],
    )
    assert order["planned_ready_date"] is None and order["forecast_ready_date"] is None
    assert order["lines"][0]["process_id"] == str(process.id)
    demand = contract_demand(db, org.id)
    assert {row["demand_id"] for row in demand} == {line["id"] for line in order["lines"]}
    assert demand[0]["product_key"] == str(output_id)
    assert demand[1]["product_key"] is None
    assert Decimal(demand[0]["quantity"]) == 600 and demand[0]["execution_ids"] == []
    changed = client.patch(f"{API}/{order['id']}", json={"due_date": "2026-11-25"})
    assert changed.status_code == 200
    assert contract_demand(db, org.id)[0]["demand_id"] == demand[0]["demand_id"]
    assert contract_demand(db, org.id)[0]["due_date"] == "2026-11-25"
    assert client.patch(f"{API}/{order['id']}", json={"status": "cancelled"}).status_code == 200
    assert contract_demand(db, org.id) == []
    events = db.query(EntityEvent).filter(EntityEvent.org_id == org.id, EntityEvent.event_type.like("contract.%")).all()
    assert any(event.payload.get("materials_source") == "customer" for event in events)
    assert any(event.payload.get("duty_responsibility") == "producer_licensee" for event in events)
    page = client.get("/core/contracts")
    assert page.status_code == 200 and b"Contract orders" in page.data
    assert client.get(f"/core/contracts/{order['id']}").status_code == 200


@pytest.mark.parametrize("duty", ["producer_licensee", "customer_licensee", "customer_underbond"])
def test_material_and_duty_declarations_are_per_line_and_order(world, duty):
    client = world["clients"][0]
    customer = _customer(client)
    order = _order(
        client,
        customer["id"],
        duty_responsibility=duty,
        customer_cca_reference="CCA-123" if duty != "producer_licensee" else None,
    )
    assert order["duty_responsibility"] == duty
    for source in ("producer", "customer", "mixed"):
        line = client.post(
            f"{API}/{order['id']}/lines",
            json={"product_name": source, "quantity": "6", "unit": "bottles", "materials_source": source},
        )
        assert line.status_code == 201, line.get_json()
        assert line.get_json()["line"]["materials_source"] == source
    # These declarations must not accidentally create stock movements or manufacturing.
    assert all(not line["batches"] for line in client.get(f"{API}/{order['id']}").get_json()["order"]["lines"])


def test_cross_org_and_wrong_parent_references_are_refused(world, db):
    first, second = world["clients"]
    org_a, org_b = world["orgs"]
    a = _customer(first)
    b = _customer(second)
    order_a = _order(first, a["id"])
    order_b = _order(second, b["id"])
    for url in (f"{API}/{order_b['id']}", f"/core/contracts/{order_b['id']}"):
        assert first.get(url).status_code == 404
    assert first.patch(f"{API}/{order_b['id']}", json={"due_date": "2026-12-01"}).status_code == 404
    assert first.get(API, query_string={"customer_id": b["id"]}).status_code == 404
    assert first.patch(f"{CUSTOMERS}/{b['id']}", json={"name": "stolen"}).status_code == 404
    invalid = first.post(
        API,
        json={
            "customer_id": b["id"],
            "reference": "foreign",
            "due_date": "2026-12-01",
            "duty_responsibility": "producer_licensee",
            "lines": [],
        },
    )
    assert invalid.status_code == 404
    other_order = _order(first, a["id"])
    wrong_parent = first.patch(f"{API}/{order_a['id']}/lines/{other_order['lines'][0]['id']}", json={"quantity": "99"})
    assert wrong_parent.status_code == 404
    foreign_process, foreign_version, foreign_output = _recipe(db, org_b.id)
    for fields in (
        {"process_id": str(foreign_process.id)},
        {"process_version_id": str(foreign_version.id)},
        {"process_version_id": str(foreign_version.id), "source_output_id": str(foreign_output)},
    ):
        response = first.patch(f"{API}/{order_a['id']}/lines/{order_a['lines'][0]['id']}", json=fields)
        assert response.status_code == 404
    contact = XeroContact(org_id=org_b.id, xero_contact_id=str(uuid4()), xero_tenant_id="test", name="Foreign CRM")
    db.add(contact)
    db.commit()
    assert first.patch(f"{CUSTOMERS}/{a['id']}", json={"crm_contact_id": str(contact.id)}).status_code == 404
    assert first.get(CUSTOMERS).get_json()["customers"][0]["crm_contact_id"] is None
    own = XeroContact(org_id=org_a.id, xero_contact_id=str(uuid4()), xero_tenant_id="test", name="Own CRM")
    db.add(own)
    db.commit()
    assert first.patch(f"{CUSTOMERS}/{a['id']}", json={"crm_contact_id": str(own.id)}).status_code == 200
    assert first.get(API).get_json()["orders"][0]["customer_id"] == a["id"]


def test_batch_links_use_trusted_tenant_recipe_and_one_order_line(world, db):
    org_a, org_b = world["orgs"]
    client = world["clients"][0]
    customer = _customer(client)
    process, version, output = _recipe(db, org_a.id)
    batch = ExecutionFactory(org_id=org_a.id, process_id=process.id)
    order = _order(
        client,
        customer["id"],
        lines=[
            {
                "product_name": "Gin",
                "quantity": "600",
                "unit": "bottles",
                "materials_source": "customer",
                "process_version_id": str(version.id),
                "source_output_id": str(output),
            }
        ],
    )
    url = f"{API}/{order['id']}/lines/{order['lines'][0]['id']}/batches"
    foreign_process, _, _ = _recipe(db, org_b.id)
    foreign_batch = ExecutionFactory(org_id=org_b.id, process_id=foreign_process.id)
    assert client.post(url, json={"execution_id": str(foreign_batch.id)}).status_code == 404
    mismatched, _, _ = _recipe(db, org_a.id, "Other private recipe")
    mismatched_batch = ExecutionFactory(org_id=org_a.id, process_id=mismatched.id)
    assert client.post(url, json={"execution_id": str(mismatched_batch.id)}).status_code == 400
    assert client.post(url, json={"execution_id": str(batch.id)}).status_code == 201
    assert client.post(url, json={"execution_id": str(batch.id)}).status_code == 201  # idempotent
    assert client.get(f"{API}/{order['id']}").get_json()["order"]["lines"][0]["batch_count"] == 1
    assert db.query(ContractOrderExecution).filter(ContractOrderExecution.execution_id == batch.id).count() == 1
    another = _order(client, customer["id"])
    other_url = f"{API}/{another['id']}/lines/{another['lines'][0]['id']}/batches"
    assert client.post(other_url, json={"execution_id": str(batch.id)}).status_code == 409
    assert (
        client.patch(
            f"{API}/{order['id']}",
            json={"duty_responsibility": "customer_underbond", "customer_cca_reference": "CCA-X"},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"{API}/{order['id']}/lines/{order['lines'][0]['id']}", json={"materials_source": "producer"}
        ).status_code
        == 409
    )
    assert client.patch(f"{API}/{order['id']}", json={"status": "completed"}).status_code == 409
    assert client.patch(f"{API}/{order['id']}", json={"status": "draft"}).status_code == 409
    assert client.delete(f"{url}/{batch.id}").status_code == 204
    assert client.post(url, json={"execution_id": str(batch.id)}).status_code == 201
    step = db.query(ExecutionStep).filter(ExecutionStep.execution_id == batch.id).one()
    ExecutionRepository(db).complete_step(step.id, org_a.id)
    assert client.delete(f"{url}/{batch.id}").status_code == 409
    assert client.patch(f"{API}/{order['id']}", json={"status": "completed"}).status_code == 200
    assert client.patch(f"{API}/{order['id']}", json={"status": "confirmed"}).status_code == 409


def test_recipe_version_mismatch_and_unmapped_output_are_refused(world, db):
    org = world["orgs"][0]
    client = world["clients"][0]
    customer = _customer(client)
    process, first_version, output = _recipe(db, org.id)
    batch = ExecutionFactory(org_id=org.id, process_id=process.id)
    ProcessRepository(db).update_process(process.id, org.id, name="Recipe changed")
    later = (
        db.query(ProcessVersion)
        .filter(ProcessVersion.process_id == process.id)
        .order_by(ProcessVersion.version_number.desc())
        .first()
    )
    order = _order(
        client,
        customer["id"],
        lines=[
            {
                "product_name": "Gin",
                "quantity": "600",
                "unit": "bottles",
                "materials_source": "mixed",
                "process_version_id": str(later.id),
                "source_output_id": str(output),
            }
        ],
    )
    assert first_version.id != later.id
    url = f"{API}/{order['id']}/lines/{order['lines'][0]['id']}"
    assert client.post(url + "/batches", json={"execution_id": str(batch.id)}).status_code == 400
    assert client.patch(url, json={"source_output_id": str(uuid4())}).status_code == 400
    assert client.get(f"{API}/{order['id']}").get_json()["order"]["lines"][0]["source_output_id"] == str(output)


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": "0"},
        {"quantity": "-1"},
        {"quantity": "NaN"},
        {"quantity": "Infinity"},
        {"quantity": "1.5"},
        {"quantity": "1.00001"},
        {"quantity": "1e30"},
        {"materials_source": "unknown"},
        {"product_name": ""},
        {"org_id": str(uuid4())},
    ],
)
def test_invalid_line_rejects_entire_order_atomically(world, db, changes):
    client = world["clients"][0]
    org = world["orgs"][0]
    customer = _customer(client)
    invalid = {"product_name": "Gin", "quantity": "6", "unit": "bottles", "materials_source": "producer", **changes}
    response = client.post(
        API,
        json={
            "customer_id": customer["id"],
            "reference": "atomic",
            "due_date": "2026-12-01",
            "duty_responsibility": "producer_licensee",
            "lines": [
                {"product_name": "Good", "quantity": "6", "unit": "bottles", "materials_source": "customer"},
                invalid,
            ],
        },
    )
    assert response.status_code == 400, response.get_json()
    assert db.query(ContractOrder).filter(ContractOrder.org_id == org.id).count() == 0
    assert db.query(ContractOrderLine).filter(ContractOrderLine.org_id == org.id).count() == 0
    assert (
        db.query(EntityEvent)
        .filter(EntityEvent.org_id == org.id, EntityEvent.event_type == "contract.line_created")
        .count()
        == 0
    )


def test_duty_validation_inactive_customer_unknown_fields_and_conflicts(world):
    client = world["clients"][0]
    customer = _customer(client)
    for body in ([], None, {"name": "x", "is_active": "false"}, {"name": "x", "org_id": str(uuid4())}):
        assert client.post(CUSTOMERS, json=body).status_code == 400
    assert client.post(CUSTOMERS, json={"name": customer["name"]}).status_code == 409
    for changes in (
        {"due_date": "tomorrow"},
        {"status": "manufactured"},
        {"duty_responsibility": "skip_duty"},
        {"duty_responsibility": "customer_licensee"},
        {"duty_responsibility": "customer_underbond", "customer_cca_reference": " "},
    ):
        response = client.post(
            API,
            json={
                "customer_id": customer["id"],
                "reference": "invalid",
                "due_date": "2026-12-01",
                "duty_responsibility": "producer_licensee",
                "lines": [{"product_name": "Gin", "quantity": "6", "unit": "bottles", "materials_source": "producer"}],
                **changes,
            },
        )
        assert response.status_code == 400
    order = _order(client, customer["id"])
    assert client.patch(f"{API}/{order['id']}", json={"customer_id": str(uuid4())}).status_code == 400
    assert client.patch(f"{CUSTOMERS}/{customer['id']}", json={"is_active": False}).status_code == 200
    response = client.post(
        API,
        json={
            "customer_id": customer["id"],
            "reference": "inactive",
            "due_date": "2026-12-01",
            "duty_responsibility": "producer_licensee",
            "lines": [],
        },
    )
    assert response.status_code == 409


def test_role_permissions_recipe_redaction_and_default_deny(world, db):
    org = world["orgs"][0]
    admin = world["clients"][0]
    customer = _customer(admin)
    _, version, output = _recipe(db, org.id)
    order = _order(
        admin,
        customer["id"],
        lines=[
            {
                "product_name": "Gin",
                "quantity": "6",
                "unit": "bottles",
                "materials_source": "producer",
                "spec_reference": "Confidential recipe instructions",
                "process_version_id": str(version.id),
                "source_output_id": str(output),
            }
        ],
    )
    for role in (UserRole.PRODUCTION, UserRole.SALES, UserRole.AUDITOR):
        user = UserFactory(
            org_id=org.id,
            role=role,
            email=f"contract-{uuid4()}@test.com",
        )
        client = _login(world["app"], user)
        result = client.get(f"{API}/{order['id']}")
        assert result.status_code == 200
        line = result.get_json()["order"]["lines"][0]
        if role == UserRole.SALES:
            for key in ("spec_reference", "process_id", "process_version_id", "source_output_id"):
                assert key not in line
            assert b"Confidential recipe" not in client.get(f"/core/contracts/{order['id']}").data
            assert (
                client.patch(f"{API}/{order['id']}/lines/{line['id']}", json={"spec_reference": "recipe"}).status_code
                == 403
            )
            for field in ("spec_reference", "process_id", "process_version_id", "source_output_id"):
                assert client.patch(f"{API}/{order['id']}/lines/{line['id']}", json={field: None}).status_code == 403
            assert (
                client.post(
                    f"{API}/{order['id']}/lines/{line['id']}/batches", json={"execution_id": str(uuid4())}
                ).status_code
                == 403
            )
        else:
            assert line["spec_reference"] == "Confidential recipe instructions"
        if role == UserRole.PRODUCTION:
            assert client.get(CUSTOMERS).status_code == 403
            assert client.post(API, json={}).status_code == 403
            assert b"New contract customer" not in client.get("/core/contracts").data
        if role == UserRole.AUDITOR:
            assert client.patch(f"{API}/{order['id']}", json={"due_date": "2026-12-01"}).status_code == 403
            assert client.post(f"{API}/{order['id']}/lines/{line['id']}/batches", json={}).status_code == 403
    anonymous = world["app"].test_client()
    anonymous.environ_base["wsgi.url_scheme"] = "https"
    anonymous.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert anonymous.get(API).status_code == 401
    for rule in world["app"].url_map.iter_rules():
        if rule.endpoint.startswith("contracts."):
            for method in rule.methods - {"OPTIONS", "HEAD"}:
                assert requirement_for(rule.endpoint, method) != DENY
                if rule.endpoint != "contracts.static":
                    assert any(pattern == rule.endpoint for pattern, _, _ in POLICY)


def test_database_blocks_cross_org_customer_and_wrong_parent_line(world, db):
    org_a, _org_b = world["orgs"]
    first, second = world["clients"]
    a, b = _customer(first), _customer(second)
    own_order = _order(first, a["id"])
    service = ContractOrderService(db, org_a.id)
    db.add(
        ContractOrder(
            org_id=org_a.id,
            customer_id=b["id"],
            reference="forged",
            due_date=date(2026, 12, 1),
            duty_responsibility="producer_licensee",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert service.order(own_order["id"]).reference == own_order["reference"]


def test_json_writes_require_the_flask_wtf_csrf_header(world, db):
    app = world["app"]
    client = world["clients"][0]
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        page = client.get("/core/contracts")
        token = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.get_data(as_text=True)).group(1)
        referer = {"Referer": "https://localhost/core/contracts"}
        missing = client.post(CUSTOMERS, json={"name": "Missing token"}, headers=referer)
        assert missing.status_code == 400 and b"CSRF token is missing" in missing.data
        assert db.query(ContractCustomer).filter(ContractCustomer.org_id == world["orgs"][0].id).count() == 0
        accepted = client.post(CUSTOMERS, json={"name": "With token"}, headers={**referer, "X-CSRFToken": token})
        assert accepted.status_code == 201, accepted.get_data(as_text=True)
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
