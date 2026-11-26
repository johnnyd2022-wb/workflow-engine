from io import BytesIO
from uuid import uuid4

import pytest

from tests.test_evidence import app_client, org_process_execution  # noqa: F401
from tests.test_process_design import authed_client  # noqa: F401


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ([{}], "_body"),
        ({"process_id": True}, "process_id"),
        ({"process_id": "invalid"}, "process_id"),
        ({"unrelated": True}, "process_id"),
    ],
)
def test_batch_creation_rejects_invalid_fields(authed_client, payload, field):  # noqa: F811
    response = authed_client.post("/api/core/executions", json=payload)
    assert response.status_code == 400
    assert field in response.json["errors"]


def test_batch_list_rejects_unknown_status_without_reflecting_it(authed_client):  # noqa: F811
    response = authed_client.get("/api/core/executions", query_string={"status": "example-status"})
    assert response.status_code == 400
    assert set(response.json["errors"]) == {"status"}
    assert b"example-status" not in response.data


def test_evidence_requires_matching_file_content(app_client, org_process_execution):  # noqa: F811
    execution = org_process_execution["execution"]
    response = app_client.post(
        "/api/core/evidence/upload",
        data={"execution_id": str(execution.id), "file": (BytesIO(b"Text document"), "record.png", "image/png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert set(response.json["errors"]) == {"file"}
    listed = app_client.get("/api/core/evidence/list", query_string={"execution_id": str(execution.id)})
    assert listed.status_code == 200
    assert listed.json["evidence"] == []


def test_evidence_metadata_rejects_non_uuid_before_file_validation(app_client):  # noqa: F811
    response = app_client.post(
        "/api/core/evidence/upload",
        data={"execution_id": str(uuid4()), "step_id": "example"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert set(response.json["errors"]) == {"step_id"}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "note\x00value"])
def test_execution_record_values_are_storable_json(value):
    from app.features.execution.complete_step_payload import validate_json_blob

    with pytest.raises(ValueError):
        validate_json_blob({"entry": value})
