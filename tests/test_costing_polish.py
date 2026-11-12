"""Live-cogs polish (after 8.1f): small wins from .agents/plans/live-cogs-polish.md."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.costing_helpers import lot, price, user_client
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_readiness import _gin_batch, _products, world  # noqa: F401 -- fixture re-export

D = Decimal


def test_a_ready_product_shows_what_one_unit_cost_on_the_list(world, db):  # noqa: F811
    org, client = world
    juniper, coriander = lot(db, org.id, "Juniper", 2, "kg"), lot(db, org.id, "Coriander", 2, "kg")
    price(db, org.id, juniper.id, 90, 2)
    execution, _step = _gin_batch(db, org, client, juniper, coriander)
    (gin,) = [p for p in _products(client) if p["name"] == "Gin"]
    assert gin["ready"] is False and gin["unit_cost"] is None, "an incomplete cost is never shown as the cost"
    price(db, org.id, coriander.id, 20, 2)
    (gin,) = [p for p in _products(client) if p["name"] == "Gin"]
    assert gin["ready"] is True and gin["unit"] == "bottles"
    card = client.get(f"/api/core/costing/executions/{execution.id}/cost").get_json()
    (bottles,) = [o for o in card["outputs"] if o["name"] == "Gin"]
    assert D(gin["unit_cost"]) == D(bottles["unit_cost"]) > 0  # the same figure the batch card shows


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("$1,234.50", "1234.50"),
        ("NZ$ 80", "80"),
        ("1 234.50", "1234.50"),
        ("  42 ", "42"),
        ("1,23", "1,23"),  # not a thousands pattern: left for the check to refuse
        ("", None),
    ],
)
def test_csv_total_paid_reads_money_as_typed(raw, clean):
    from app.core.backend.inventory_upload_routes import _check_total_paid, _clean_money

    assert _clean_money(raw) == clean
    if clean == "1,23":
        assert _check_total_paid(clean)[0] == "error"
    elif clean is not None:
        assert _check_total_paid(clean) == ("ok", None)


def test_excise_public_helpers_match_what_duty_uses():
    from app.features.compliant.modules.nz_alcohol import excise

    assert excise.product_base_name("Navy Gin - Library stock") == excise._base_name("Navy Gin - Library stock")
    assert excise.litres_of(D("1500"), "ml", None) == excise._litres(D("1500"), "ml", None) == D("1.5")


def test_costs_page_settings_sheet_is_for_managers_only(flask_app, db):  # noqa: F811
    from tests.costing_helpers import new_org, purge

    org = new_org(db)
    try:
        manager = user_client(db, flask_app, org)
        assert "data-costs-settings" in manager.get("/core/costing/costs").get_data(as_text=True)
        viewer = user_client(db, flask_app, org, permissions=["costs.view", "production.view", "inventory.view"])
        assert "data-costs-settings" not in viewer.get("/core/costing/costs").get_data(as_text=True)
        assert viewer.put("/api/core/costing/settings", json={"split_basis": "litres"}).status_code == 403
    finally:
        purge(db, org)
