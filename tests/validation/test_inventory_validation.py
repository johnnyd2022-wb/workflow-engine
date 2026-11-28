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
        ({"purchase_date": "1700000000"}, "purchase_date"),
        ({"expiry_date": "2026-02-29"}, "expiry_date"),
    ],
)
def test_create_inventory_validates_writes(app_client, values, field):  # noqa: F811
    response = app_client.post(
        "/api/core/inventory",
        json={"name": "Validation lot", "quantity": "1", "unit": "kg", **values},
    )
    assert response.status_code == 400
    assert field in response.json["errors"]


@pytest.mark.parametrize(
    ("purchase", "expiry"),
    [
        ("20261020", "20271121"),
        ("2026-10-20", "2027-11-21"),
        ("20261020T234500Z", "2027-11-21T23:45:00-05:00"),
    ],
)
@pytest.mark.parametrize("operation", ["create", "edit", "reconcile"])
def test_inventory_round_trips_iso_lot_dates(app_client, purchase, expiry, operation):  # noqa: F811
    path = "/api/core/inventory"
    lot = {"name": "Dated lot", "quantity": "1", "unit": "kg"}
    dates = {"purchase_date": purchase, "expiry_date": expiry}

    if operation == "edit":
        created = app_client.post(path, json=lot)
        assert created.status_code == 201
        response = app_client.put(f"{path}/{created.json['id']}", json={**lot, **dates})
        assert response.status_code == 200, response.json
    else:
        create_path = f"{path}/reconcile/via-addition" if operation == "reconcile" else path
        response = app_client.post(create_path, json={**lot, **dates})
        assert response.status_code == 201, response.json

    listing = app_client.get(path)
    assert listing.status_code == 200
    stored = next(item for item in listing.json["inventory_items"] if item["id"] == response.json["id"])
    assert (stored["purchase_date"], stored["expiry_date"]) == ("2026-10-20", "2027-11-21")


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


def test_csv_commit_rejects_browser_review_state(app_client):  # noqa: F811
    row = {"row_index": 2, "name": "CSV lot", "quantity": "1", "unit": "kg", "_duplicateCommit": False}
    response = app_client.post("/api/core/inventory/csv-commit", json={"rows": [row]})
    assert response.status_code == 400
    assert response.json["errors"]["rows.0"] == "Unknown field."


def test_csv_preview_and_commit_reject_excess_quantity_precision(app_client):  # noqa: F811
    path = "/api/core/inventory"
    csv = "Item Name,Quantity,Unit\nValid precision,12.3456,kg\nExcess precision,12.34567,kg\n"
    preview = app_client.post(f"{path}/csv-validate", data=csv, content_type="text/csv")
    assert preview.status_code == 200

    commit = app_client.post(f"{path}/csv-commit", json={"rows": preview.json["rows"]})
    assert commit.status_code == 400, commit.json
    assert commit.json["created"] == []
    assert commit.json["errors"] == [{"row_index": 3, "error": "Quantity must have at most 4 decimal places"}]
    assert [row["status"] for row in preview.json["validation"]] == ["ok", "error"]
    assert preview.json["validation"][1]["message"] == commit.json["errors"][0]["error"]


def test_dilution_rejects_an_integer_that_cannot_be_represented_as_float():
    from app.features.compliant.tools.calculators.dilution import DilutionValidationError, solve

    with pytest.raises(DilutionValidationError, match="starting_volume_ml.*finite number"):
        solve({"solve_for": "final_volume_ml", "starting_volume_ml": 10**400, "starting_abv": 70, "final_abv": 40})
