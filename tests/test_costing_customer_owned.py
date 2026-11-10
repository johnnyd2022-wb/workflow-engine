"""Live-cogs 8.1a AC23: customer-owned (contract) material costs nothing and can't be priced."""

import pytest

from tests.costing_helpers import D, lot_cost, price
from tests.test_compliant_routes import flask_app  # noqa: F401
from tests.test_contract_material_ownership import lot, owned, receipt  # noqa: F401
from tests.test_contract_orders import world  # noqa: F401


def test_ac23_customer_owned_is_zero_and_not_priceable(owned, db):  # noqa: F811
    from app.features.costing.service import CostingError

    org_id = owned["orgs"][0].id
    theirs = lot(db, owned, receipt(owned))
    assert theirs.contract_customer_id is not None
    cost = lot_cost(db, org_id, theirs.id)
    assert (D(cost["unit_cost"]), cost["status"], cost["source"]) == (D("0"), "actual", "customer_owned")
    assert cost["editable"] is False
    with pytest.raises(CostingError):
        price(db, org_id, theirs.id, 10, 2)
    db.rollback()
