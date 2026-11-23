"""Seeded data for the response-validation test (AC37), and the call each assistant operation is made with.

One organisation, built once per module and removed with the test session's organisations, holds a little
of everything the first-wave operations read: stock in several states, a finished batch, a hold, a
costed purchase, a sale, an excise period, a stocktake and a planner demand. Each ``SEEDS`` entry says which
path and query to call an operation with, and which parts of the response must come back non-empty so a
seed that quietly produced nothing cannot pass for proof.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import pytest

from app.core.db import db_session
from app.core.db.models.user import UserRole
from app.core.services import lot_holds
from app.features.inventory.stocktake import start_stocktake
from tests.costing_helpers import complete, login, lot, price, produced_lots, workflow
from tests.factories import FeatureSubscriptionFactory, OrganisationFactory, UserFactory
from tests.mcp_oauth.support import RESOURCE, bearer, make_client, mint_grant, unique_addr  # noqa: F401


@dataclass
class Call:
    params: dict = field(default_factory=dict)  # path parameters
    query: dict = field(default_factory=dict)
    nonempty: tuple[str, ...] = ()  # dotted body paths the seed must have produced


@dataclass
class Showcase:
    app: object
    db: object
    org: object
    admin: object
    ids: dict = field(default_factory=dict)
    token_headers: dict = field(default_factory=dict)

    def _client(self):
        client = self.app.test_client()
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        client.environ_base["REMOTE_ADDR"] = unique_addr()
        return client

    @property
    def token_client(self):
        return self._client()

    @property
    def session_client(self):
        return login(self.app, self.admin.email)


SEEDS: dict[str, Callable[[Showcase], Call]] = {
    "core_list_inventory": lambda w: Call(nonempty=("inventory_items",)),
    "stocktake_get_stock_position": lambda w: Call(nonempty=("places",)),
    "stocktake_get_stocktake_reconciliation": lambda w: Call(
        {"stocktake_id": w.ids["stocktake"]}, nonempty=("products",)
    ),
    "lot_holds_list_open_holds": lambda w: Call(nonempty=("holds",)),
    "lot_holds_get_lot_holds": lambda w: Call({"item_id": w.ids["gin_lot"]}, nonempty=("open", "history")),
    "core_list_expired_materials": lambda w: Call(),
    "core_list_output_ready_date": lambda w: Call(),
    "core_list_processes": lambda w: Call(query={"include_steps": "true"}, nonempty=("processes",)),
    "core_get_process": lambda w: Call({"process_id": w.ids["process"]}, nonempty=("steps",)),
    "core_list_executions": lambda w: Call(nonempty=("executions",)),
    "core_get_execution": lambda w: Call({"execution_id": w.ids["execution"]}, nonempty=("execution_steps",)),
    "core_trace_inventory_backward": lambda w: Call(
        {"inventory_item_id": w.ids["gin_lot"]}, nonempty=("raw_materials", "connections")
    ),
    "core_trace_raw_material": lambda w: Call(
        {"raw_material_id": w.ids["juniper"]}, nonempty=("finals", "connections")
    ),
    "core_trace_inventory_to_sale_graph": lambda w: Call(
        {"inventory_item_id": w.ids["gin_lot"]}, nonempty=("all_items",)
    ),
    "compliant_compliant_api_list_records": lambda w: Call(),
    "compliant_compliant_api_get_excise_position": lambda w: Call(nonempty=("year",)),
    "compliant_compliant_api_get_excise_period": lambda w: Call(nonempty=("draft",)),
    "compliant_compliant_api_list_excise_periods": lambda w: Call(nonempty=("periods",)),
    "crm_crm_api_get_org_invoices": lambda w: Call(query={"kind": "all"}),
    "crm_crm_api_monthly_sales": lambda w: Call(query={"months": "6"}),
    "costing_get_lot_cost": lambda w: Call({"item_id": w.ids["juniper"]}, nonempty=("entries",)),
    "costing_get_execution_cost": lambda w: Call({"execution_id": w.ids["execution"]}, nonempty=("inputs", "outputs")),
    "costing_readiness_list": lambda w: Call(nonempty=("products",)),
    "costing_readiness_detail": lambda w: Call({"key": w.ids["product_key"]}, nonempty=("materials",)),
    "costing_margins_report": lambda w: Call(),
    "costing_get_stock_value": lambda w: Call(nonempty=("lines", "total")),
    "planning_get_stock_cover": lambda w: Call(query={"weeks": "8"}),
    "planning_get_planning_batches": lambda w: Call(),
}


@pytest.fixture(scope="module")
def showcase_world(flask_app):
    """The seeded organisation, with an admin and a live assistant token for that admin."""
    from app.features.mcp_oauth.models import McpAllowedRole, McpOrgSettings

    db = db_session()
    org = OrganisationFactory()
    for feature in ("costing", "compliant"):
        FeatureSubscriptionFactory(org_id=org.id, feature_key=feature)
    admin = UserFactory(org_id=org.id, email=f"showcase-{org.id.hex[:8]}@example.test", role=UserRole.ADMIN)
    db.add(McpOrgSettings(org_id=org.id, enabled=True))
    db.add(McpAllowedRole(org_id=org.id, role_key="builtin:admin"))
    db.commit()
    client_row = make_client(db)
    _grant, access, _refresh = mint_grant(db, admin, client_row)
    world = Showcase(app=flask_app, db=db, org=org, admin=admin, token_headers=bearer(access))
    with flask_app.app_context():
        session = login(flask_app, admin.email)
        juniper = lot(db, org.id, "Juniper", 2, "kg")
        price(db, org.id, juniper.id, 90, 2)
        coriander = lot(db, org.id, "Coriander", 2, "kg")  # deliberately never priced
        execution, (s1, s2) = workflow(
            db, org.id, [[{"name": "Macerate", "unit": "L"}], [{"name": "Gin", "unit": "bottles"}]]
        )
        process_id = execution.process_id
        complete(
            session,
            execution,
            s1,
            [(juniper, 1, "kg"), (coriander, 1, "kg")],
            [{"name": "Macerate", "quantity": 10, "unit": "L"}],
        )
        (macerate,) = produced_lots(db, org.id, s1.id)
        complete(session, execution, s2, [(macerate, 10, "L")], [{"name": "Gin", "quantity": 20, "unit": "bottles"}])
        (gin,) = produced_lots(db, org.id, s2.id)
        lot_holds.place_hold(db, org.id, gin.id, "Failed ABV check", admin.id)
        stocktake = start_stocktake(db, org.id, date.today(), "scheduled", None, admin.id)
        db.commit()
        products = session.get("/api/core/costing/readiness").get_json()["products"]
        world.ids.update(
            gin_lot=str(gin.id),
            juniper=str(juniper.id),
            coriander=str(coriander.id),
            execution=str(execution.id),
            process=str(process_id),
            stocktake=str(stocktake.id),
            product_key=products[0]["key"] if products else "none",
        )
        yield world
    db.rollback()
    db.close()
    db_session.remove()
