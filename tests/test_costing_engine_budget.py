"""CostEngine out of budget part-way: nothing half-walked may stay "being worked on" (review !700/!705)."""

from __future__ import annotations

import pytest

from app.features.costing import engine as engine_module
from tests.costing_helpers import complete, lot, new_org, price, produced_lots, purge, user_client, workflow
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export


def test_a_lot_reached_inside_an_overflowed_walk_still_costs_as_itself(flask_app, db, monkeypatch):  # noqa: F811
    org = new_org(db)
    try:
        client = user_client(db, flask_app, org)
        spirit = lot(db, org.id, "Base spirit", 10, "L")
        price(db, org.id, spirit.id, 100, 10)
        first, (step1,) = workflow(db, org.id, [[{"name": "Gin", "unit": "bottles"}]])
        complete(client, first, step1, [(spirit, 1, "L")], [{"name": "Gin", "quantity": 2, "unit": "bottles"}])
        (gin,) = produced_lots(db, org.id, step1.id)
        second, (step2,) = workflow(db, org.id, [[{"name": "Gin blend", "unit": "bottles"}]])
        complete(
            client, second, step2, [(gin, 1, "bottles")], [{"name": "Gin blend", "quantity": 1, "unit": "bottles"}]
        )
        (blend,) = produced_lots(db, org.id, step2.id)
        own = engine_module.CostEngine(db, org.id)._solve(("lot", gin.id)).status
        assert own == "actual"

        monkeypatch.setattr(engine_module, "MAX_NODES", 4)  # the blend's walk overflows with gin half-walked
        engine = engine_module.CostEngine(db, org.id)
        with pytest.raises(engine_module.TooLargeError):
            engine._solve(("lot", blend.id))
        assert not engine._active, "an overflow leaves nothing marked as being worked on"
        monkeypatch.setattr(engine_module, "MAX_NODES", 20_000)
        assert engine._solve(("lot", gin.id)).status == own, "not mistaken for a cycle"
    finally:
        purge(db, org)
