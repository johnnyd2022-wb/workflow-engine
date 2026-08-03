"""Step CRUD unhappy paths (AC6-AC8) and reordering (AC9).

test_workflow_flow.py covers the step-add happy path already; this file is the
gap-fill pass: validation rejections on create/update, 404s on cross-process step
mutation, and — the confirmed zero-coverage item from this review — the reorder
endpoint (POST /api/core/processes/<id>/steps/reorder), which no test at all (unit or
e2e) touched before this file.

Cross-tenant probes mirror test_tenant_isolation.py: reorder/update/delete on another
org's process must 404 (ProcessRepository.get_process_by_id / the reorder endpoint's own
IDOR guard are both org-scoped lookups, so a miss is indistinguishable from a bad id —
never a distinguishable 403, which would let an attacker enumerate valid ids).
"""

import uuid
from decimal import Decimal

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e


def _create_process(page, name: str) -> str:
    resp = page.request.post(
        "/api/core/processes",
        headers=csrf_headers(page),
        data={"name": name, "category": "manufacturing"},
    )
    assert resp.status == 201, f"process setup failed: {resp.status} {resp.text()}"
    return resp.json()["id"]


def _add_step(page, process_id: str, step_number: int, name: str, **extra):
    return page.request.post(
        f"/api/core/processes/{process_id}/steps",
        headers=csrf_headers(page),
        data={"step_number": step_number, "name": name, **extra},
    )


def _get_process(page, process_id: str) -> dict:
    resp = page.request.get(f"/api/core/processes/{process_id}")
    assert resp.status == 200, f"get process failed: {resp.status} {resp.text()}"
    return resp.json()


def _reorder(page, process_id: str, orders: list[dict]):
    return page.request.post(
        f"/api/core/processes/{process_id}/steps/reorder",
        headers=csrf_headers(page),
        data={"orders": orders},
    )


# --------------------------------------------------------------------------------------
# AC6: add_step validation
# --------------------------------------------------------------------------------------


def test_ac6_add_step_requires_step_number_and_name(logged_in_page: Page):
    page = logged_in_page
    pid = _create_process(page, f"E2E Step Validation {uuid.uuid4().hex[:8]}")

    missing_name = _add_step(page, pid, 1, None)
    assert missing_name.status == 400

    missing_number = page.request.post(
        f"/api/core/processes/{pid}/steps",
        headers=csrf_headers(page),
        data={"name": "Mix"},
    )
    assert missing_number.status == 400


def test_ac6_add_step_rejects_non_grid_position(logged_in_page: Page):
    """Positions must be multiples of 1000 (the 'Option B' fractional-position grid)."""
    page = logged_in_page
    pid = _create_process(page, f"E2E Step Grid {uuid.uuid4().hex[:8]}")
    resp = _add_step(page, pid, 1, "Mix", position=1500)
    assert resp.status == 400, f"expected 400 for off-grid position, got {resp.status}: {resp.text()}"


@pytest.mark.parametrize("bad_position", ["NaN", "Infinity", "-1000", "0"])
def test_ac6_add_step_rejects_invalid_positions(logged_in_page: Page, bad_position):
    page = logged_in_page
    pid = _create_process(page, f"E2E Step BadPos {uuid.uuid4().hex[:8]}")
    resp = _add_step(page, pid, 1, "Mix", position=bad_position)
    assert resp.status == 400, f"expected 400 for position={bad_position!r}, got {resp.status}: {resp.text()}"


def test_ac6_add_step_defaults_to_appended_position(logged_in_page: Page):
    page = logged_in_page
    pid = _create_process(page, f"E2E Step Append {uuid.uuid4().hex[:8]}")
    first = _add_step(page, pid, 1, "First")
    assert first.status == 201
    second = _add_step(page, pid, 2, "Second")
    assert second.status == 201

    assert Decimal(first.json()["position"]) == Decimal("1000")
    assert Decimal(second.json()["position"]) == Decimal("2000")


def test_ac6_add_step_rejects_expiry_shorter_than_ready_date(logged_in_page: Page):
    """_validate_step_outputs_expiry_after_ready: when both ready_date and custom_expiry
    use fixed_duration mode, expiry duration must be >= ready duration."""
    page = logged_in_page
    pid = _create_process(page, f"E2E Step Expiry {uuid.uuid4().hex[:8]}")
    outputs = [
        {
            "name": "Batch",
            "extra_data": {
                "ready_date": {
                    "enabled": True,
                    "mode": "fixed_duration",
                    "duration_value": 10,
                    "duration_unit": "days",
                },
                "custom_expiry": {
                    "enabled": True,
                    "mode": "fixed_duration",
                    "duration_value": 2,
                    "duration_unit": "days",
                },
            },
        }
    ]
    resp = page.request.post(
        f"/api/core/processes/{pid}/steps",
        headers=csrf_headers(page),
        data={"step_number": 1, "name": "Mix", "outputs": outputs},
    )
    assert resp.status == 400, f"expected 400 for expiry shorter than ready date, got {resp.status}: {resp.text()}"


def test_ac6_add_step_to_nonexistent_process_is_404(logged_in_page: Page):
    page = logged_in_page
    resp = _add_step(page, str(uuid.uuid4()), 1, "Mix")
    assert resp.status == 404


# --------------------------------------------------------------------------------------
# AC7: update_step
# --------------------------------------------------------------------------------------


def test_ac7_update_step_partial_update_only_touches_provided_fields(logged_in_page: Page):
    page = logged_in_page
    pid = _create_process(page, f"E2E Step Partial {uuid.uuid4().hex[:8]}")
    step = _add_step(page, pid, 1, "Original Name", description="original description").json()

    resp = page.request.put(
        f"/api/core/processes/{pid}/steps/{step['id']}",
        headers=csrf_headers(page),
        data={"description": "updated description"},
    )
    assert resp.status == 200, f"partial update failed: {resp.status} {resp.text()}"
    body = resp.json()
    assert body["description"] == "updated description"
    assert body["name"] == "Original Name", "partial update must not clobber untouched fields"


def test_ac7_update_step_404_for_unknown_step(logged_in_page: Page):
    page = logged_in_page
    pid = _create_process(page, f"E2E Step Update404 {uuid.uuid4().hex[:8]}")
    resp = page.request.put(
        f"/api/core/processes/{pid}/steps/{uuid.uuid4()}",
        headers=csrf_headers(page),
        data={"description": "does not matter"},
    )
    assert resp.status == 404


def test_ac7_update_step_404_when_process_id_does_not_own_the_step(logged_in_page: Page):
    page = logged_in_page
    pid_a = _create_process(page, f"E2E Step Update Owner A {uuid.uuid4().hex[:8]}")
    pid_b = _create_process(page, f"E2E Step Update Owner B {uuid.uuid4().hex[:8]}")
    step_b = _add_step(page, pid_b, 1, "Belongs to B").json()

    resp = page.request.put(
        f"/api/core/processes/{pid_a}/steps/{step_b['id']}",
        headers=csrf_headers(page),
        data={"description": "trying to edit through the wrong process"},
    )
    assert resp.status == 404, f"expected 404 for step/process mismatch, got {resp.status}"


def test_ac7_update_step_rejects_non_grid_position(logged_in_page: Page):
    page = logged_in_page
    pid = _create_process(page, f"E2E Step Update Grid {uuid.uuid4().hex[:8]}")
    step = _add_step(page, pid, 1, "Mix").json()
    resp = page.request.put(
        f"/api/core/processes/{pid}/steps/{step['id']}",
        headers=csrf_headers(page),
        data={"position": 1234},
    )
    assert resp.status == 400


# --------------------------------------------------------------------------------------
# AC8: delete_step
# --------------------------------------------------------------------------------------


def test_ac8_delete_step_404_when_process_id_does_not_own_the_step(logged_in_page: Page):
    page = logged_in_page
    pid_a = _create_process(page, f"E2E Step Delete Owner A {uuid.uuid4().hex[:8]}")
    pid_b = _create_process(page, f"E2E Step Delete Owner B {uuid.uuid4().hex[:8]}")
    step_b = _add_step(page, pid_b, 1, "Belongs to B").json()

    resp = page.request.delete(f"/api/core/processes/{pid_a}/steps/{step_b['id']}", headers=csrf_headers(page))
    assert resp.status == 404, f"expected 404 for step/process mismatch, got {resp.status}"

    # And it must still exist under its real, owning process.
    still_there = _get_process(page, pid_b)
    assert any(s["id"] == step_b["id"] for s in still_there["steps"])


def test_ac8_delete_step_404_for_unknown_step(logged_in_page: Page):
    page = logged_in_page
    pid = _create_process(page, f"E2E Step Delete404 {uuid.uuid4().hex[:8]}")
    resp = page.request.delete(f"/api/core/processes/{pid}/steps/{uuid.uuid4()}", headers=csrf_headers(page))
    assert resp.status == 404


# --------------------------------------------------------------------------------------
# AC9: reorder — the confirmed zero-coverage endpoint.
# --------------------------------------------------------------------------------------


def test_ac9_reorder_happy_path_updates_positions_and_ordering(logged_in_page: Page):
    """Renumber all three steps onto fresh grid slots to move the third step to the
    front. A single non-grid position (e.g. 500 to slot between nothing and 1000) is not
    used here — reorder requires every position to land on the 1000-grid, same as
    add_step/update_step; see test_ac9_reorder_to_non_grid_position_returns_400 below."""
    page = logged_in_page
    pid = _create_process(page, f"E2E Reorder {uuid.uuid4().hex[:8]}")
    s1 = _add_step(page, pid, 1, "First").json()
    s2 = _add_step(page, pid, 2, "Second").json()
    s3 = _add_step(page, pid, 3, "Third").json()
    assert [Decimal(s["position"]) for s in (s1, s2, s3)] == [Decimal(1000), Decimal(2000), Decimal(3000)]

    # Move the third step to the front by renumbering all three onto fresh grid slots.
    resp = _reorder(
        page,
        pid,
        [
            {"id": s3["id"], "position": 1000},
            {"id": s1["id"], "position": 2000},
            {"id": s2["id"], "position": 3000},
        ],
    )
    assert resp.status == 200, f"reorder failed: {resp.status} {resp.text()}"
    assert "reorder" in resp.json().get("message", "").lower()

    after = _get_process(page, pid)
    ordered_ids = [s["id"] for s in after["steps"]]
    assert ordered_ids == [s3["id"], s1["id"], s2["id"]], f"reorder did not re-sort steps: {ordered_ids}"


def test_ac9_reorder_multiple_steps_in_one_call(logged_in_page: Page):
    page = logged_in_page
    pid = _create_process(page, f"E2E Reorder Multi {uuid.uuid4().hex[:8]}")
    s1 = _add_step(page, pid, 1, "First").json()
    s2 = _add_step(page, pid, 2, "Second").json()

    resp = _reorder(page, pid, [{"id": s1["id"], "position": 9000}, {"id": s2["id"], "position": 1000}])
    assert resp.status == 200, f"reorder failed: {resp.status} {resp.text()}"

    after = _get_process(page, pid)
    ordered_ids = [s["id"] for s in after["steps"]]
    assert ordered_ids == [s2["id"], s1["id"]], f"multi-step reorder produced wrong order: {ordered_ids}"


def test_ac9_reorder_accepts_steps_alias_key(logged_in_page: Page):
    """The 'steps' key is documented as an alias for 'orders'."""
    page = logged_in_page
    pid = _create_process(page, f"E2E Reorder Alias {uuid.uuid4().hex[:8]}")
    step = _add_step(page, pid, 1, "Only step").json()

    resp = page.request.post(
        f"/api/core/processes/{pid}/steps/reorder",
        headers=csrf_headers(page),
        data={"steps": [{"id": step["id"], "position": 5000}]},
    )
    assert resp.status == 200, f"'steps' alias rejected: {resp.status} {resp.text()}"
    after = _get_process(page, pid)
    assert Decimal(after["steps"][0]["position"]) == Decimal("5000")


def test_ac9_reorder_rejects_missing_orders(logged_in_page: Page):
    page = logged_in_page
    pid = _create_process(page, f"E2E Reorder NoBody {uuid.uuid4().hex[:8]}")
    _add_step(page, pid, 1, "Only step")

    resp = page.request.post(f"/api/core/processes/{pid}/steps/reorder", headers=csrf_headers(page), data={})
    assert resp.status == 400
    assert "orders" in resp.json()["error"].lower()


def test_ac9_reorder_rejects_unknown_step_id(logged_in_page: Page):
    page = logged_in_page
    pid = _create_process(page, f"E2E Reorder Unknown {uuid.uuid4().hex[:8]}")
    step = _add_step(page, pid, 1, "Real step").json()

    resp = _reorder(page, pid, [{"id": str(uuid.uuid4()), "position": 1000}])
    assert resp.status == 404, f"expected 404 for unknown step id, got {resp.status}: {resp.text()}"

    # The real step's position must be untouched by the rejected call.
    after = _get_process(page, pid)
    assert Decimal(after["steps"][0]["position"]) == Decimal(step["position"])


def test_ac9_reorder_rejects_step_from_a_different_process(logged_in_page: Page):
    page = logged_in_page
    pid_a = _create_process(page, f"E2E Reorder Cross A {uuid.uuid4().hex[:8]}")
    pid_b = _create_process(page, f"E2E Reorder Cross B {uuid.uuid4().hex[:8]}")
    _add_step(page, pid_a, 1, "In A")
    step_b = _add_step(page, pid_b, 1, "In B").json()

    resp = _reorder(page, pid_a, [{"id": step_b["id"], "position": 1000}])
    assert resp.status == 404, f"expected 404 reordering another process's step, got {resp.status}: {resp.text()}"

    # step B must be untouched.
    b_after = _get_process(page, pid_b)
    assert Decimal(b_after["steps"][0]["position"]) == Decimal(step_b["position"])


def test_ac9_reorder_process_not_found_is_404(logged_in_page: Page):
    page = logged_in_page
    resp = _reorder(page, str(uuid.uuid4()), [{"id": str(uuid.uuid4()), "position": 1000}])
    assert resp.status == 404


def test_ac9_reorder_position_collision_does_not_error(logged_in_page: Page):
    """No uniqueness is enforced on position (documented review gap): two steps can be
    given the same (grid-valid) position without the request failing. This test pins
    that actual behavior rather than assuming an error that the endpoint doesn't
    produce."""
    page = logged_in_page
    pid = _create_process(page, f"E2E Reorder Collision {uuid.uuid4().hex[:8]}")
    s1 = _add_step(page, pid, 1, "First").json()
    s2 = _add_step(page, pid, 2, "Second").json()

    resp = _reorder(page, pid, [{"id": s1["id"], "position": 1000}, {"id": s2["id"], "position": 1000}])
    assert resp.status == 200, f"expected a colliding reorder to still succeed, got {resp.status}: {resp.text()}"

    after = _get_process(page, pid)
    positions = {s["id"]: Decimal(s["position"]) for s in after["steps"]}
    assert positions[s1["id"]] == Decimal("1000")
    assert positions[s2["id"]] == Decimal("1000")


def test_ac9_reorder_to_non_grid_position_returns_400(logged_in_page: Page):
    """FIXED (was a review-found gap): add_step/update_step both run every position
    through _coerce_step_position, which 400s on anything that isn't a positive
    multiple of 1000 — matching the DB's chk_steps_position_grid CHECK constraint
    (normalize_steps_position_grid_001 migration). reorder_steps previously skipped
    that validator, so an off-grid value sailed past the API layer and died on the DB
    constraint as an uncaught IntegrityError -> 500. reorder_steps now runs every
    position through the same `_is_valid_step_position` grid check before touching the
    DB (see backend.py's reorder_steps and `_is_valid_step_position`), returning a
    clean 400 like every other step-position endpoint."""
    page = logged_in_page
    pid = _create_process(page, f"E2E Reorder OffGrid {uuid.uuid4().hex[:8]}")
    step = _add_step(page, pid, 1, "Only step").json()

    resp = _reorder(page, pid, [{"id": step["id"], "position": 500}])
    assert resp.status == 400, f"expected a clean 400 for an off-grid position, got {resp.status}: {resp.text()}"
    assert "chk_steps_position_grid" not in resp.text(), "must not leak the DB constraint name to the client"

    # And the step itself must be untouched by the rejected write.
    after = _get_process(page, pid)
    assert Decimal(after["steps"][0]["position"]) == Decimal(step["position"])


# --------------------------------------------------------------------------------------
# Cross-tenant probes.
# --------------------------------------------------------------------------------------


@pytest.fixture()
def two_tenants(browser, app_url, fresh_user):
    org_a, org_b = fresh_user(), fresh_user()
    contexts = []

    def _sign_in(user):
        context = browser.new_context(base_url=app_url, ignore_https_errors=True)
        contexts.append(context)
        page = context.new_page()
        login_through_ui(page, user["email"], user["password"])
        return page

    pages = {"a": _sign_in(org_a), "b": _sign_in(org_b)}
    yield pages
    for context in contexts:
        context.close()


def test_org_b_cannot_reorder_org_a_process_steps(two_tenants):
    page_a, page_b = two_tenants["a"], two_tenants["b"]
    pid = _create_process(page_a, f"E2E Cross Reorder {uuid.uuid4().hex[:8]}")
    step = _add_step(page_a, pid, 1, "org A step").json()

    resp = _reorder(page_b, pid, [{"id": step["id"], "position": 1000}])
    assert resp.status == 404, f"org B reordered org A's process steps: {resp.status}"

    after = _get_process(page_a, pid)
    assert Decimal(after["steps"][0]["position"]) == Decimal(step["position"]), "org A's step position changed"


def test_org_b_cannot_update_org_a_step(two_tenants):
    page_a, page_b = two_tenants["a"], two_tenants["b"]
    pid = _create_process(page_a, f"E2E Cross Update {uuid.uuid4().hex[:8]}")
    step = _add_step(page_a, pid, 1, "org A step").json()

    resp = page_b.request.put(
        f"/api/core/processes/{pid}/steps/{step['id']}",
        headers=csrf_headers(page_b),
        data={"name": "hijacked by org B"},
    )
    assert resp.status == 404, f"org B updated org A's step: {resp.status}"

    after = _get_process(page_a, pid)
    assert after["steps"][0]["name"] == "org A step"


def test_org_b_cannot_delete_org_a_step(two_tenants):
    page_a, page_b = two_tenants["a"], two_tenants["b"]
    pid = _create_process(page_a, f"E2E Cross Delete {uuid.uuid4().hex[:8]}")
    step = _add_step(page_a, pid, 1, "org A step").json()

    resp = page_b.request.delete(f"/api/core/processes/{pid}/steps/{step['id']}", headers=csrf_headers(page_b))
    assert resp.status == 404, f"org B deleted org A's step: {resp.status}"

    after = _get_process(page_a, pid)
    assert any(s["id"] == step["id"] for s in after["steps"]), "org A's step vanished after org B's rejected delete"


def test_org_b_cannot_list_org_a_process_via_reorder_process_lookup(two_tenants):
    """The reorder endpoint's own IDOR guard (repo.get_process_by_id) must 404, not leak
    whether the process exists at all."""
    page_a, page_b = two_tenants["a"], two_tenants["b"]
    pid = _create_process(page_a, f"E2E Cross ProcessProbe {uuid.uuid4().hex[:8]}")

    resp = _reorder(page_b, pid, [{"id": str(uuid.uuid4()), "position": 1000}])
    assert resp.status == 404
    assert "not found" in resp.json()["error"].lower()
