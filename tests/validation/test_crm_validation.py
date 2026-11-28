import pytest

from tests.test_org_routes import org_world  # noqa: F401


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        ("/api/crm/customers", [True], "_body"),
        ("/api/crm/customers/600e31d7-a34c-41b0-90e0-59d30b6c68c2/notes", {"content": False}, "content"),
        ("/api/crm/tasks", {"title": {"name": "Follow up"}}, "title"),
        ("/api/crm/tasks", {"title": "Follow up", "priority": True}, "priority"),
        (
            "/api/crm/product-mappings",
            {"biz_e_product_name": "Gin", "xero_description_pattern": True},
            "xero_description_pattern",
        ),
        ("/api/crm/matching/confirm", {"invoice_id": 5, "line_key": "example"}, "invoice_id"),
    ],
)
def test_crm_rejects_invalid_write_fields(org_world, path, payload, field):  # noqa: F811
    response = org_world["admin_client"].post(path, json=payload)
    assert response.status_code == 400
    assert field in response.json["errors"]


def test_crm_customer_page_bounds(org_world):  # noqa: F811
    response = org_world["admin_client"].get("/api/crm/customers", query_string={"page": "999999999999999999999"})
    assert response.status_code == 400
    assert "page" in response.json["errors"]


def test_xero_sync_rejects_unknown_mode(org_world):  # noqa: F811
    response = org_world["admin_client"].post("/api/crm/xero/sync", query_string={"mode": "example"})
    assert response.status_code == 400
    assert "mode" in response.json["errors"]
