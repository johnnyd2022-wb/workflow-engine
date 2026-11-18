"""Live-cogs 8.1g AC131: customer-owned (contract) material is never the org's stock to value."""

from tests.test_compliant_routes import flask_app  # noqa: F401
from tests.test_contract_material_ownership import lot, owned, receipt  # noqa: F401
from tests.test_contract_orders import world  # noqa: F401


def test_ac131_customer_owned_material_is_left_out(owned, db):  # noqa: F811
    from app.features.costing import stock_value

    org_id = owned["orgs"][0].id
    theirs = lot(db, owned, receipt(owned))
    assert theirs.contract_customer_id is not None
    valuation = stock_value.value_stock(db, org_id)
    assert theirs.id not in {line.item_id for line in valuation.lines}
