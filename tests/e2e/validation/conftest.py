"""Assertions shared by browser form validation tests."""

import pytest


@pytest.fixture
def assert_json_field_error():
    """Check a direct browser request to the server for a field-level error."""

    def check(page, method, path, payload, field, *, headers=None):
        response = page.request.fetch(path, method=method, data=payload, headers=headers)
        assert response.status in {400, 422}
        errors = response.json()["errors"]
        assert field in errors
        assert isinstance(errors[field], str) and errors[field]
        return response

    return check
