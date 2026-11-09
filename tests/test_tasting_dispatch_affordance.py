"""The Tasks page offers "Confirm stock removal" only to people the server will let dispatch.

Dispatch is two checks on the server: ``sales.record`` from the policy table (every non-read
``tastings.*`` endpoint) and ``inventory.adjust`` from the route. ``can()`` in a template is
any-of, so ``data-can-dispatch`` has to spell out both. A person holding only
``inventory.adjust`` was once shown the form and answered 403
(``.agents/reports/tastings/html-js-review.md`` F2).
"""

import re
from uuid import uuid4

import pytest

from app.features.compliant.models.compliance_profile import ComplianceProfile
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_sales_matching import world  # noqa: F401 -- fixture re-export

READ = ("sales.view", "inventory.view")


@pytest.fixture
def tastings_world(world):  # noqa: F811
    db = world["db"]
    db.add(ComplianceProfile(org_id=world["org"].id, enabled=True, industry_module="nz_alcohol"))
    db.commit()
    return world


def _flags(person):
    page = person.get("/crm/tasks?type=tasting", headers={"Accept": "text/html"})
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    found = {name: re.search(rf'data-can-{name}="(true|false)"', html) for name in ("record", "dispatch")}
    assert all(found.values()), "the Tastings workspace was not rendered on the Tasks page"
    return {name: match.group(1) == "true" for name, match in found.items()}


def _server_lets_dispatch_through(person):
    """Reached the event lookup (404 for an id that does not exist) rather than a 403."""
    response = person.post(
        f"/api/crm/tastings/{uuid4()}/dispatch",
        json={"actual_date": "2026-10-20"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code in (403, 404), response.get_data(as_text=True)
    return response.status_code != 403


@pytest.mark.parametrize(
    ("permissions", "can_record", "can_dispatch"),
    [
        pytest.param((*READ, "sales.record", "inventory.adjust"), True, True, id="both-write-permissions"),
        pytest.param((*READ, "inventory.adjust"), False, False, id="stock-only-the-reported-case"),
        pytest.param((*READ, "sales.record"), True, False, id="sales-only"),
        pytest.param(READ, False, False, id="read-only"),
    ],
)
def test_dispatch_is_offered_exactly_when_the_server_would_allow_it(
    tastings_world, permissions, can_record, can_dispatch
):
    person = tastings_world["login_as"](tastings_world["custom_role"](*permissions))

    assert _flags(person) == {"record": can_record, "dispatch": can_dispatch}
    assert _server_lets_dispatch_through(person) is can_dispatch


def test_the_built_in_sales_role_is_not_shown_a_dispatch_it_cannot_make(tastings_world):
    sales = tastings_world["login_as"]("sales")  # sales.record, no inventory.adjust

    assert _flags(sales) == {"record": True, "dispatch": False}
    assert _server_lets_dispatch_through(sales) is False
