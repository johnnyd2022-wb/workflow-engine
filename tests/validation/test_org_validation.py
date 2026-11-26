from uuid import uuid4

import pytest

from tests.test_admin_site import _signed_in, site  # noqa: F401
from tests.test_org_routes import org_world  # noqa: F401


@pytest.mark.parametrize(
    ("method", "path", "payload", "field"),
    [
        ("PATCH", "/org", ["unexpected"], "_body"),
        ("PATCH", "/org", {"name": "  "}, "name"),
        ("PATCH", "/org", {"name": "a" * 256}, "name"),
        ("PATCH", "/org", {"status": "other"}, "status"),
        ("PATCH", "/org", {"name": "Example", "other": True}, "_body"),
        ("POST", "/org/users", {"email": True}, "email"),
        ("POST", "/org/users", {"email": "no-address"}, "email"),
        ("POST", "/org/users", {"email": "person@example.test", "first_name": []}, "first_name"),
        ("POST", "/org/roles", {"name": "Role", "base_role": "member", "permissions": [[]]}, "permissions.0"),
        ("POST", "/api/core/stock-locations", {"name": "Bay", "inside_licensed_area": "false"}, "inside_licensed_area"),
        ("POST", "/api/core/stock-locations", {"name": 123}, "name"),
    ],
)
def test_org_configuration_request_fields(org_world, method, path, payload, field):  # noqa: F811
    client = org_world["admin_client"]
    response = client.open(path, method=method, json=payload)
    assert response.status_code == 400
    assert field in response.json["errors"]


@pytest.mark.parametrize(("value", "field"), [({"quantity": "0.00001"}, "quantity"), ({"note": []}, "note")])
def test_stock_move_request_checks_fields(org_world, value, field):  # noqa: F811
    path = f"/api/core/inventory/{uuid4()}/move"
    response = org_world["admin_client"].post(path, json={"quantity": "1", **value})
    assert response.status_code == 400
    assert field in response.json["errors"]


@pytest.mark.parametrize("page", ["0", "banana", "9000000000000000000"])
def test_staff_organisations_rejects_out_of_range_page(site, page):  # noqa: F811
    _, client = site
    _signed_in(client)
    response = client.get("/organisations", query_string={"page": page})
    assert response.status_code == 400
    assert b"page" in response.data.lower()
