from uuid import uuid4

import pytest

from tests.test_inventory import app_client, org, user  # noqa: F401


@pytest.mark.parametrize(
    ("values", "field"),
    [
        ({"name": 1}, "name"),
        ({"quantity": True}, "quantity"),
        ({"quantity": "1.00001"}, "quantity"),
        ({"quantity": "NaN"}, "quantity"),
        ({"metadata": ["entry"]}, "metadata"),
        ({"purchase_date": 100}, "purchase_date"),
    ],
)
def test_create_inventory_validates_writes(app_client, values, field):  # noqa: F811
    response = app_client.post(
        "/api/core/inventory",
        json={"name": "Validation lot", "quantity": "1", "unit": "kg", **values},
    )
    assert response.status_code == 400
    assert field in response.json["errors"]


def test_adjust_rejects_excess_precision(app_client):  # noqa: F811
    response = app_client.post(f"/api/core/inventory/{uuid4()}/adjust", json={"new_quantity": "1.00001"})
    assert response.status_code == 400
    assert "new_quantity" in response.json["errors"]


@pytest.mark.parametrize("path", ["/api/core/stocktakes", "/api/core/inventory/reconcile/via-addition"])
def test_inventory_commands_require_json_objects(app_client, path):  # noqa: F811
    response = app_client.post(path, json=["unexpected"])
    assert response.status_code == 400
    assert "_body" in response.json["errors"]


def test_csv_commit_rejects_non_object_rows(app_client):  # noqa: F811
    response = app_client.post("/api/core/inventory/csv-commit", json={"rows": [True]})
    assert response.status_code == 400
    assert "rows.0" in response.json["errors"]


def test_dilution_rejects_an_integer_that_cannot_be_represented_as_float():
    from app.features.compliant.tools.calculators.dilution import DilutionValidationError, solve

    with pytest.raises(DilutionValidationError, match="starting_volume_ml.*finite number"):
        solve({"solve_for": "final_volume_ml", "starting_volume_ml": 10**400, "starting_abv": 70, "final_abv": 40})
