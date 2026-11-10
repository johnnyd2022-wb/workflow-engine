"""Shared setup for the live-cogs (roadmap 8.1a) cost engine tests.

Spec: .agents/specs/live-cogs.md. Lots are created through InventoryRepository so the Core
hooks write their cost_flows rows; steps are completed through the real HTTP route so the
consumption / output / reconciliation hooks run exactly as in production.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.core.db.models.inventory_item import InventoryType
from app.core.db.models.org_role import OrgRole
from app.core.db.models.user import UserRole
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

FEATURE = "costing"
D = Decimal


def login(flask_app, email):
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    response = client.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD})
    assert response.status_code == 200, response.get_json()
    return client


def new_org(db, *, grant=True):
    org = OrganisationFactory()
    if grant:
        FeatureSubscriptionRepository(db).grant(org.id, FEATURE)
    db.commit()
    return org


def user_client(db, flask_app, org, role=UserRole.ADMIN, permissions=None):
    """A signed-in client for a new user in ``org``. ``permissions`` makes a custom role."""
    email = f"costing-{uuid4()}@test.com"
    user = UserRepository(db).create_user(
        org_id=org.id,
        email=email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        role=role,
        is_active=True,
    )
    if permissions is not None:
        custom = OrgRole(
            id=uuid4(), org_id=org.id, name=f"Custom {uuid4().hex[:6]}", base_role="member", permissions=permissions
        )
        db.add(custom)
        db.flush()
        user.custom_role_id = custom.id
    db.commit()
    return login(flask_app, email)


def lot(db, org_id, name, quantity, unit, *, inventory_type=InventoryType.RAW_MATERIAL.value, **kwargs):
    return InventoryRepository(db).create_inventory_item(
        org_id=org_id, name=name, quantity=str(quantity), unit=unit, inventory_type=inventory_type, **kwargs
    )


def flows(db, org_id, item_id, kind=None):
    from app.features.costing.models import CostFlow

    q = db.query(CostFlow).filter(CostFlow.org_id == org_id, CostFlow.inventory_item_id == item_id)
    if kind:
        q = q.filter(CostFlow.kind == kind)
    return q.order_by(CostFlow.created_at, CostFlow.id).all()


def price(db, org_id, item_id, amount, quantity, *, kind="manual", cost_flow_id=None):
    """Enter a manual / free price (a lot_cost_entries row) through the costing service."""
    from app.features.costing import service

    entry = service.set_lot_price(
        db,
        org_id,
        item_id,
        amount=D(str(amount)),
        quantity=D(str(quantity)),
        kind=kind,
        cost_flow_id=cost_flow_id,
    )
    db.commit()
    return entry


def lot_cost(db, org_id, item_id):
    from app.features.costing.engine import CostEngine

    db.expire_all()
    return CostEngine(db, org_id).lot(item_id)


def execution_cost(db, org_id, execution_id):
    from app.features.costing.engine import CostEngine

    db.expire_all()
    return CostEngine(db, org_id).execution(execution_id)


def set_last_known_price(db, org_id, value):
    from app.features.costing import service

    service.set_settings(db, org_id, use_last_known_price=value)
    db.commit()


def workflow(db, org_id, steps):
    """``steps``: list of lists of output definitions, one list per step, e.g.
    ``[[{"name": "Gin", "unit": "bottles"}]]``. Each definition gets a stable ``id`` unless
    it brings one. Returns (execution, [execution_step per step number]).
    """
    repo = ProcessRepository(db)
    process = repo.create_process(org_id=org_id, name=f"Costing {uuid4().hex[:6]}", description="", is_draft=False)
    for number, outputs in enumerate(steps, start=1):
        defs = []
        for out in outputs:
            d = {"quantity": "1", **out}
            d.setdefault("id", str(uuid4()))
            defs.append(d)
        repo.add_step(
            process_id=process.id,
            org_id=org_id,
            step_number=number,
            position=number * 1000,
            name=f"Step {number}",
            inputs=[],
            outputs=defs,
            execution_prompts=[],
        )
    db.commit()
    execution = ExecutionRepository(db).create_execution(org_id=org_id, process_id=process.id)
    db.commit()
    ordered = sorted(execution.execution_steps, key=lambda s: s.step_number)
    return execution, ordered


def output_defs(execution_step):
    return list(execution_step.step.outputs or [])


def complete(client, execution, execution_step, inputs=(), outputs=(), expect=200):
    """``inputs``: (lot, quantity, unit) tuples. ``outputs``: dicts for actual_outputs."""
    response = client.post(
        f"/api/core/executions/{execution.id}/steps/{execution_step.id}/complete",
        json={
            "actual_inputs": [
                {"name": item.name, "quantity": str(q), "unit": u, "inventory_item_id": str(item.id)}
                for item, q, u in inputs
            ],
            "actual_outputs": [{k: (str(v) if k == "quantity" else v) for k, v in o.items()} for o in outputs],
            "execution_data": {},
        },
    )
    assert response.status_code == expect, response.get_json()
    return response


def produced_lots(db, org_id, execution_step_id):
    from app.core.db.models.inventory_item import InventoryItem

    db.expire_all()
    return (
        db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.source_execution_step_id == execution_step_id)
        .order_by(InventoryItem.created_at, InventoryItem.id)
        .all()
    )


def by_name(rows, key="name"):
    return {r[key]: r for r in rows}


def purge(db, *orgs):
    from tests.org_purge import purge_orgs

    db.rollback()
    purge_orgs(db, [o.id for o in orgs])
    db.commit()
