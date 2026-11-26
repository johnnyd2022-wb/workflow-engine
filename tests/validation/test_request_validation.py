from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated
from uuid import UUID

import pytest
from flask import Flask, jsonify
from pydantic import Field, StringConstraints

from app.utils.request_validation import CleanName, InvalidInputError, JsonInput, read_json


class Stage(str, Enum):
    OPEN = "open"


class Sample(JsonInput):
    name: Annotated[CleanName, StringConstraints(max_length=15)]
    count: Annotated[int, Field(ge=0, le=100)]
    amount: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
    stage: Stage
    day: date
    time: datetime
    ids: Annotated[list[UUID], Field(min_length=1, max_length=5)]
    active: bool = False


@pytest.fixture
def sample_client():
    app = Flask(__name__)

    @app.post("/")
    def sample():
        try:
            payload = read_json(Sample)
        except InvalidInputError as error:
            return error.response()
        return jsonify(payload.model_dump(mode="json"))

    return app.test_client()


@pytest.fixture
def payload():
    return {
        "name": "  Batch A  ",
        "count": 0,
        "amount": "10.12",
        "stage": "open",
        "day": "2026-11-27",
        "time": "2026-11-27T02:03:04Z",
        "ids": ["ec7fca0e-5546-4a20-a916-fe795f1544be"],
    }


def test_valid_input(sample_client, payload):
    response = sample_client.post("/", json=payload)
    assert response.status_code == 200
    assert response.json == {**payload, "name": "Batch A", "active": False}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", 12),
        ("name", "   "),
        ("name", "n" * 16),
        ("name", "batch\u0085a"),
        ("count", "12"),
        ("count", True),
        ("count", 101),
        ("amount", "10.123"),
        ("amount", "NaN"),
        ("amount", "Infinity"),
        ("amount", -1),
        ("amount", True),
        ("stage", "closed"),
        ("day", "2026-02-29"),
        ("day", "2026-11-27T00:00:00"),
        ("time", 123),
        ("ids", []),
        ("ids", ["not an ID"]),
        ("active", "false"),
    ],
)
def test_field_errors(sample_client, payload, field, value):
    response = sample_client.post("/", json={**payload, field: value})
    assert response.status_code == 400
    assert set(response.json["errors"]) == {field}


def test_missing_field(sample_client, payload):
    del payload["name"]
    response = sample_client.post("/", json=payload)
    assert response.status_code == 400
    assert response.json["errors"] == {"name": "This field is required."}


def test_extra_field_name_and_value_are_not_reflected(sample_client, payload):
    response = sample_client.post("/", json={**payload, "key-from-caller": "value-from-caller"})
    assert response.status_code == 400
    assert response.json["errors"] == {"_body": "Unknown field."}
    assert b"from-caller" not in response.data


@pytest.mark.parametrize("data", ["", "{", "null", "[]", "1", '"text"'])
def test_json_object_required(sample_client, data):
    response = sample_client.post("/", data=data, content_type="application/json")
    assert response.status_code == 400
    assert set(response.json["errors"]) == {"_body"}


def test_json_content_type_required(sample_client):
    response = sample_client.post("/", data="{}", content_type="text/plain")
    assert response.status_code == 400
    assert set(response.json["errors"]) == {"_body"}
