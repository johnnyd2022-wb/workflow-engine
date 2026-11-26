from uuid import uuid4

import pytest

from tests.test_traceability import app_client, org, user  # noqa: F401


@pytest.mark.parametrize(
    ("path", "query", "field"),
    [
        ("/api/core/sourcemap/objects", {"limit": "-1"}, "limit"),
        ("/api/core/sourcemap/objects", {"page": "12345678901234567890"}, "page"),
        ("/api/core/sourcemap/objects", {"q": "x" * 256}, "q"),
        ("/api/core/entities/activity", {"offset": "-1"}, "offset"),
        ("/api/core/entities/activity", {"from_date": "2026-02-29"}, "from_date"),
        ("/api/core/dashboard/summary", [("window_days", "30"), ("window_days", "90")], "window_days"),
    ],
)
def test_trace_list_validates_query_fields(app_client, path, query, field):  # noqa: F811
    response = app_client.get(path, query_string=query)
    assert response.status_code == 400
    assert field in response.json["errors"]


@pytest.mark.parametrize(
    ("values", "field"), [({"depth": True}, "depth"), ({"as_of": 1}, "as_of"), ({"depth": 11}, "depth")]
)
def test_trace_rejects_invalid_request_fields(app_client, values, field):  # noqa: F811
    response = app_client.post("/api/core/sourcemap/trace", json={"root_id": str(uuid4()), **values})
    assert response.status_code == 400
    assert field in response.json["errors"]
