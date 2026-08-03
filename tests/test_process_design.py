"""Fast unit-test coverage for process-design (`.agents/specs/process-design.md`).

Before this file, process/step CRUD (backend.py:1201-1694), the wizard helpers
(backend.py:139-424), and the create-wizard pages (backend.py:855-1022) had ZERO
fast unit-test coverage — only the e2e Playwright suites
(`tests/e2e/test_process_steps_flow.py`, `test_process_wizard_flow.py`,
`test_process_docs_flow.py`, all written earlier in this same review) touched this
code, and pytest-cov can't see a separately-started dev server process. This file is
the fast-feedback-layer gap fill: validation/error branches on process/step CRUD,
reorder, and process-docs MIME detection, exercised through Flask's test client
in-process rather than a browser against a live server.

Happy-path CRUD and org-isolation of process CRUD are already covered by
test_executions.py / test_corechecks.py / test_multi_tenant_isolation.py (see
.agents/test-map.md row 9) and by the e2e suites above — this file does not
re-duplicate those; it targets the specific 400/404/409 branches pytest-cov flagged
as unreached.
"""

from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.step import Step
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

PASSWORD = DEFAULT_TEST_PASSWORD


def _make_logged_in_client(db, role):
    org = OrganisationFactory()
    db.commit()
    org_id = org.id

    email = f"user_{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org_id,
        email=email,
        password_hash=AuthService.hash_password(PASSWORD),
        role=role,
        is_active=True,
    )
    db.commit()

    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    with flask_app.app_context():
        client = flask_app.test_client()
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        login_resp = client.post("/auth/login", json={"email": email, "password": PASSWORD})
        assert login_resp.status_code == 200, login_resp.data
        yield client

    db.rollback()
    # Tests in this file create processes/steps/versions under this org (process CRUD
    # is exactly what's under test) — process_versions.org_id has no ON DELETE CASCADE
    # from organisations, so those rows must go before the org, or the FK blocks it.
    process_ids = [p.id for p in db.query(Process.id).filter(Process.org_id == org_id).all()]
    if process_ids:
        db.query(Step).filter(Step.process_id.in_(process_ids)).delete(synchronize_session=False)
        db.query(ProcessVersion).filter(ProcessVersion.process_id.in_(process_ids)).delete(synchronize_session=False)
        db.query(Process).filter(Process.id.in_(process_ids)).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def authed_client(db):
    """A single org + MEMBER user, logged into a real Flask test client.

    Mirrors tests/test_reconciliation_routes.py / tests/test_org_routes.py: process
    and step CRUD/reorder require only @requires_auth (no role gate — see spec's
    "Users & permissions" section), so a MEMBER is sufficient here. delete_process is
    the one exception (ADMIN-gated, review/process-design 2026-08-03) — use
    `admin_client` for that.
    """
    from app.core.db.models.user import UserRole

    yield from _make_logged_in_client(db, UserRole.MEMBER)


@pytest.fixture
def admin_client(db):
    """Same as `authed_client` but ADMIN role — required for delete_process only."""
    from app.core.db.models.user import UserRole

    yield from _make_logged_in_client(db, UserRole.ADMIN)


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def _create_process(client, name=None, **extra) -> dict:
    payload = {"name": name or f"Test Process {uuid4().hex[:8]}", **extra}
    resp = client.post("/api/core/processes", json=payload)
    assert resp.status_code == 201, resp.data
    return resp.get_json()


def _add_step(client, process_id, step_number, name, **extra):
    payload = {"step_number": step_number, "name": name, **extra}
    return client.post(f"/api/core/processes/{process_id}/steps", json=payload)


def _get_process(client, process_id) -> dict:
    resp = client.get(f"/api/core/processes/{process_id}")
    assert resp.status_code == 200, resp.data
    return resp.get_json()


def _reorder(client, process_id, orders):
    return client.post(f"/api/core/processes/{process_id}/steps/reorder", json={"orders": orders})


# --------------------------------------------------------------------------------------
# AC2: create_process
# --------------------------------------------------------------------------------------


def test_ac2_create_process_requires_name(authed_client):
    resp = authed_client.post("/api/core/processes", json={"description": "no name given"})
    assert resp.status_code == 400
    assert "name" in resp.get_json()["error"].lower()


def test_ac2_create_process_rejects_invalid_category(authed_client):
    resp = authed_client.post("/api/core/processes", json={"name": "Bad Category", "category": "not-a-category"})
    assert resp.status_code == 400
    assert "category" in resp.get_json()["error"].lower()


def test_ac2_create_process_success_returns_expected_fields(authed_client):
    resp = authed_client.post(
        "/api/core/processes",
        json={"name": "Mix Batch", "description": "mixing SOP", "category": "manufacturing", "is_draft": True},
    )
    assert resp.status_code == 201, resp.data
    body = resp.get_json()
    assert body["name"] == "Mix Batch"
    assert body["description"] == "mixing SOP"
    assert body["category"] == "manufacturing"
    assert body["is_draft"] is True
    assert body["id"]
    assert body["created_at"]


# --------------------------------------------------------------------------------------
# AC3: update_process
# --------------------------------------------------------------------------------------


def test_ac3_update_process_not_found_is_404(authed_client):
    resp = authed_client.put(f"/api/core/processes/{uuid4()}", json={"name": "New Name"})
    assert resp.status_code == 404


def test_ac3_update_process_rejects_invalid_uuid(authed_client):
    resp = authed_client.put("/api/core/processes/not-a-uuid", json={"name": "New Name"})
    assert resp.status_code == 400


def test_ac3_update_process_rejects_invalid_category(authed_client):
    pid = _create_process(authed_client)["id"]
    resp = authed_client.put(f"/api/core/processes/{pid}", json={"category": "not-a-category"})
    assert resp.status_code == 400
    assert "category" in resp.get_json()["error"].lower()


def test_ac3_update_process_noop_returns_200_without_new_version(authed_client, db):
    pid = _create_process(authed_client, name="Untouched Process")["id"]
    version_count_before = db.query(ProcessVersion).filter(ProcessVersion.process_id == pid).count()
    assert version_count_before == 1  # written by create_process

    resp = authed_client.put(f"/api/core/processes/{pid}", json={})
    assert resp.status_code == 200, resp.data
    assert resp.get_json()["name"] == "Untouched Process"

    version_count_after = db.query(ProcessVersion).filter(ProcessVersion.process_id == pid).count()
    assert version_count_after == version_count_before, "no-op update must not write a new ProcessVersion"


# --------------------------------------------------------------------------------------
# AC4: delete_process
# --------------------------------------------------------------------------------------


def test_ac4_delete_process_not_found_is_404(admin_client):
    resp = admin_client.delete(f"/api/core/processes/{uuid4()}")
    assert resp.status_code == 404


def test_ac4_delete_process_cascades_to_steps(admin_client, db):
    pid = _create_process(admin_client)["id"]
    step = _add_step(admin_client, pid, 1, "Only step").get_json()

    resp = admin_client.delete(f"/api/core/processes/{pid}")
    assert resp.status_code == 200, resp.data

    assert admin_client.get(f"/api/core/processes/{pid}").status_code == 404
    remaining = db.query(Step).filter(Step.id == step["id"]).first()
    assert remaining is None, "deleting a process must cascade-delete its steps"


def test_ac4_delete_process_rejected_for_non_admin_member(authed_client):
    """FIXED (was security-audit F3, escalated and resolved by founder decision
    2026-08-03): delete_process now requires ADMIN, matching process-docs delete's
    existing ADMIN gate — closing the asymmetry where the more destructive action
    (cascades to all steps + all ProcessVersion history) had the weaker gate."""
    pid = _create_process(authed_client)["id"]

    resp = authed_client.delete(f"/api/core/processes/{pid}")
    assert resp.status_code == 403

    assert authed_client.get(f"/api/core/processes/{pid}").status_code == 200, (
        "process should still exist after a rejected non-admin delete"
    )


# --------------------------------------------------------------------------------------
# AC5: get_process
# --------------------------------------------------------------------------------------


def test_ac5_get_process_rejects_invalid_uuid(authed_client):
    resp = authed_client.get("/api/core/processes/not-a-uuid")
    assert resp.status_code == 400


def test_ac5_get_process_not_found_is_404(authed_client):
    resp = authed_client.get(f"/api/core/processes/{uuid4()}")
    assert resp.status_code == 404


# --------------------------------------------------------------------------------------
# AC6: add_step
# --------------------------------------------------------------------------------------


def test_ac6_add_step_requires_step_number_and_name(authed_client):
    pid = _create_process(authed_client)["id"]
    assert _add_step(authed_client, pid, 1, None).status_code == 400
    resp = authed_client.post(f"/api/core/processes/{pid}/steps", json={"name": "Mix"})
    assert resp.status_code == 400


def test_ac6_add_step_rejects_non_int_step_number(authed_client):
    pid = _create_process(authed_client)["id"]
    resp = _add_step(authed_client, pid, "not-an-int", "Mix")
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "bad_position",
    [1500, -1000, 0, "NaN", "Infinity", "1e31"],
    ids=["off-grid", "negative", "zero", "nan", "infinity", "over-magnitude"],
)
def test_ac6_add_step_rejects_invalid_positions(authed_client, bad_position):
    pid = _create_process(authed_client)["id"]
    resp = _add_step(authed_client, pid, 1, "Mix", position=bad_position)
    assert resp.status_code == 400, f"position={bad_position!r} should 400, got {resp.status_code}: {resp.data}"


def test_ac6_add_step_rejects_expiry_shorter_than_ready_date(authed_client):
    """_validate_step_outputs_expiry_after_ready: when both ready_date and custom_expiry
    use fixed_duration mode, expiry duration must be >= ready duration."""
    pid = _create_process(authed_client)["id"]
    outputs = [
        {
            "name": "Batch",
            "extra_data": {
                "ready_date": {"enabled": True, "mode": "fixed_duration", "duration_value": 10, "duration_unit": "days"},
                "custom_expiry": {
                    "enabled": True,
                    "mode": "fixed_duration",
                    "duration_value": 2,
                    "duration_unit": "days",
                },
            },
        }
    ]
    resp = _add_step(authed_client, pid, 1, "Mix", outputs=outputs)
    assert resp.status_code == 400
    assert "expiry" in resp.get_json()["error"].lower()


def test_ac6_add_step_process_not_found_is_404(authed_client):
    resp = _add_step(authed_client, str(uuid4()), 1, "Mix")
    assert resp.status_code == 404


def test_ac6_add_step_integrity_error_returns_409(authed_client):
    pid = _create_process(authed_client)["id"]
    fake_err = IntegrityError("INSERT INTO steps ...", {}, Exception("duplicate key value"))
    with patch.object(ProcessRepository, "add_step", side_effect=fake_err):
        resp = _add_step(authed_client, pid, 1, "Mix")
    assert resp.status_code == 409


# --------------------------------------------------------------------------------------
# AC7: update_step
# --------------------------------------------------------------------------------------


def test_ac7_update_step_partial_update_only_touches_provided_fields(authed_client):
    pid = _create_process(authed_client)["id"]
    step = _add_step(authed_client, pid, 1, "Original Name", description="original description").get_json()

    resp = authed_client.put(
        f"/api/core/processes/{pid}/steps/{step['id']}", json={"description": "updated description"}
    )
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body["description"] == "updated description"
    assert body["name"] == "Original Name"


def test_ac7_update_step_rejects_invalid_uuids(authed_client):
    resp = authed_client.put("/api/core/processes/not-a-uuid/steps/also-not-a-uuid", json={"name": "x"})
    assert resp.status_code == 400


def test_ac7_update_step_not_found_is_404(authed_client):
    pid = _create_process(authed_client)["id"]
    resp = authed_client.put(f"/api/core/processes/{pid}/steps/{uuid4()}", json={"name": "x"})
    assert resp.status_code == 404


def test_ac7_update_step_process_not_found_is_404(authed_client):
    pid = _create_process(authed_client)["id"]
    step = _add_step(authed_client, pid, 1, "Mix").get_json()
    resp = authed_client.put(f"/api/core/processes/{uuid4()}/steps/{step['id']}", json={"name": "x"})
    assert resp.status_code == 404


def test_ac7_update_step_rejects_invalid_position(authed_client):
    pid = _create_process(authed_client)["id"]
    step = _add_step(authed_client, pid, 1, "Mix").get_json()
    resp = authed_client.put(f"/api/core/processes/{pid}/steps/{step['id']}", json={"position": 1234})
    assert resp.status_code == 400


def test_ac7_update_step_rejects_expiry_shorter_than_ready_date(authed_client):
    pid = _create_process(authed_client)["id"]
    step = _add_step(authed_client, pid, 1, "Mix").get_json()
    outputs = [
        {
            "name": "Batch",
            "extra_data": {
                "ready_date": {"enabled": True, "mode": "fixed_duration", "duration_value": 10, "duration_unit": "days"},
                "custom_expiry": {
                    "enabled": True,
                    "mode": "fixed_duration",
                    "duration_value": 2,
                    "duration_unit": "days",
                },
            },
        }
    ]
    resp = authed_client.put(f"/api/core/processes/{pid}/steps/{step['id']}", json={"outputs": outputs})
    assert resp.status_code == 400


def test_ac7_update_step_noop_returns_200_without_new_version(authed_client, db):
    pid = _create_process(authed_client)["id"]
    step = _add_step(authed_client, pid, 1, "Mix").get_json()
    version_count_before = db.query(ProcessVersion).filter(ProcessVersion.process_id == pid).count()
    assert version_count_before == 2  # create_process + add_step

    resp = authed_client.put(f"/api/core/processes/{pid}/steps/{step['id']}", json={})
    assert resp.status_code == 200, resp.data
    assert resp.get_json()["name"] == "Mix"

    version_count_after = db.query(ProcessVersion).filter(ProcessVersion.process_id == pid).count()
    assert version_count_after == version_count_before, "no-op step update must not write a new ProcessVersion"


def test_ac7_update_step_integrity_error_returns_409(authed_client):
    pid = _create_process(authed_client)["id"]
    step = _add_step(authed_client, pid, 1, "Mix").get_json()
    fake_err = IntegrityError("UPDATE steps ...", {}, Exception("duplicate key value"))
    with patch.object(ProcessRepository, "update_step", side_effect=fake_err):
        resp = authed_client.put(f"/api/core/processes/{pid}/steps/{step['id']}", json={"name": "Renamed"})
    assert resp.status_code == 409


# --------------------------------------------------------------------------------------
# AC8: delete_step
# --------------------------------------------------------------------------------------


def test_ac8_delete_step_rejects_invalid_uuids(authed_client):
    resp = authed_client.delete("/api/core/processes/not-a-uuid/steps/also-not-a-uuid")
    assert resp.status_code == 400


def test_ac8_delete_step_not_found_is_404(authed_client):
    pid = _create_process(authed_client)["id"]
    resp = authed_client.delete(f"/api/core/processes/{pid}/steps/{uuid4()}")
    assert resp.status_code == 404


def test_ac8_delete_step_process_not_found_is_404(authed_client):
    pid = _create_process(authed_client)["id"]
    step = _add_step(authed_client, pid, 1, "Mix").get_json()
    resp = authed_client.delete(f"/api/core/processes/{uuid4()}/steps/{step['id']}")
    assert resp.status_code == 404


# --------------------------------------------------------------------------------------
# AC9: reorder_steps
# --------------------------------------------------------------------------------------


def test_ac9_reorder_rejects_invalid_process_uuid(authed_client):
    resp = authed_client.post("/api/core/processes/not-a-uuid/steps/reorder", json={"orders": []})
    assert resp.status_code == 400


def test_ac9_reorder_rejects_missing_orders(authed_client):
    pid = _create_process(authed_client)["id"]
    _add_step(authed_client, pid, 1, "Only step")
    resp = authed_client.post(f"/api/core/processes/{pid}/steps/reorder", json={})
    assert resp.status_code == 400
    assert "orders" in resp.get_json()["error"].lower()


def test_ac9_reorder_rejects_empty_orders_list(authed_client):
    pid = _create_process(authed_client)["id"]
    _add_step(authed_client, pid, 1, "Only step")
    resp = _reorder(authed_client, pid, [])
    assert resp.status_code == 400


def test_ac9_reorder_rejects_non_dict_row(authed_client):
    pid = _create_process(authed_client)["id"]
    _add_step(authed_client, pid, 1, "Only step")
    resp = authed_client.post(f"/api/core/processes/{pid}/steps/reorder", json={"orders": ["not-a-dict"]})
    assert resp.status_code == 400


def test_ac9_reorder_rejects_row_missing_id(authed_client):
    pid = _create_process(authed_client)["id"]
    _add_step(authed_client, pid, 1, "Only step")
    resp = _reorder(authed_client, pid, [{"position": 1000}])
    assert resp.status_code == 400


def test_ac9_reorder_rejects_row_missing_position(authed_client):
    pid = _create_process(authed_client)["id"]
    step = _add_step(authed_client, pid, 1, "Only step").get_json()
    resp = _reorder(authed_client, pid, [{"id": step["id"]}])
    assert resp.status_code == 400


def test_ac9_reorder_rejects_invalid_id_type(authed_client):
    pid = _create_process(authed_client)["id"]
    _add_step(authed_client, pid, 1, "Only step")
    resp = _reorder(authed_client, pid, [{"id": "not-a-uuid", "position": 1000}])
    assert resp.status_code == 400


def test_ac9_reorder_rejects_invalid_position_type(authed_client):
    pid = _create_process(authed_client)["id"]
    step = _add_step(authed_client, pid, 1, "Only step").get_json()
    resp = _reorder(authed_client, pid, [{"id": step["id"], "position": "not-a-number"}])
    assert resp.status_code == 400


def test_ac9_reorder_process_not_found_is_404(authed_client):
    resp = _reorder(authed_client, str(uuid4()), [{"id": str(uuid4()), "position": 1000}])
    assert resp.status_code == 404


def test_ac9_reorder_rejects_step_id_not_belonging_to_process(authed_client):
    pid_a = _create_process(authed_client)["id"]
    pid_b = _create_process(authed_client)["id"]
    _add_step(authed_client, pid_a, 1, "In A")
    step_b = _add_step(authed_client, pid_b, 1, "In B").get_json()

    resp = _reorder(authed_client, pid_a, [{"id": step_b["id"], "position": 2000}])
    assert resp.status_code == 404


def test_ac9_reorder_steps_alias_key_works_like_orders(authed_client):
    """The 'steps' key is documented as an alias for 'orders'."""
    pid = _create_process(authed_client)["id"]
    step = _add_step(authed_client, pid, 1, "Only step").get_json()

    resp = authed_client.post(
        f"/api/core/processes/{pid}/steps/reorder", json={"steps": [{"id": step["id"], "position": 5000}]}
    )
    assert resp.status_code == 200, resp.data
    after = _get_process(authed_client, pid)
    assert Decimal(after["steps"][0]["position"]) == Decimal("5000")


def test_ac9_reorder_normal_in_grid_reorder_succeeds_and_persists(authed_client):
    """Normal-path coverage: valid grid-aligned positions reorder and persist. The
    off-grid-position 500 and the SessionLocal() leak on early returns that this
    review found have since been fixed (see backend.py's reorder_steps +
    ProcessRepository.reorder_steps, and
    tests/e2e/test_process_steps_flow.py::test_ac9_reorder_to_non_grid_position_returns_400)."""
    pid = _create_process(authed_client)["id"]
    s1 = _add_step(authed_client, pid, 1, "First").get_json()
    s2 = _add_step(authed_client, pid, 2, "Second").get_json()

    resp = _reorder(authed_client, pid, [{"id": s1["id"], "position": 9000}, {"id": s2["id"], "position": 1000}])
    assert resp.status_code == 200, resp.data

    after = _get_process(authed_client, pid)
    ordered_ids = [s["id"] for s in after["steps"]]
    assert ordered_ids == [s2["id"], s1["id"]]
    positions = {s["id"]: Decimal(s["position"]) for s in after["steps"]}
    assert positions[s1["id"]] == Decimal("9000")
    assert positions[s2["id"]] == Decimal("1000")


def test_ac9_reorder_writes_process_version_and_emits_event(authed_client, db):
    """FIXED (was a review-found gap): unlike add_step/update_step/delete_step, reorder
    previously wrote no ProcessVersion snapshot and emitted no event — reordering was
    invisible to traceability/activity-log despite being a real state mutation.
    ProcessRepository.reorder_steps now inserts a version + emits
    'process.steps_reordered', same as every other step mutation."""
    pid = _create_process(authed_client)["id"]
    s1 = _add_step(authed_client, pid, 1, "First").get_json()
    s2 = _add_step(authed_client, pid, 2, "Second").get_json()

    version_count_before = db.query(ProcessVersion).filter(ProcessVersion.process_id == pid).count()

    resp = _reorder(authed_client, pid, [{"id": s1["id"], "position": 500 * 20}, {"id": s2["id"], "position": 1000}])
    assert resp.status_code == 200, resp.data

    version_count_after = db.query(ProcessVersion).filter(ProcessVersion.process_id == pid).count()
    assert version_count_after == version_count_before + 1, "reorder must write exactly one new ProcessVersion"

    latest_version = (
        db.query(ProcessVersion)
        .filter(ProcessVersion.process_id == pid)
        .order_by(ProcessVersion.version_number.desc())
        .first()
    )
    assert latest_version.change_summary == "Reordered steps"

    event = (
        db.query(EntityEvent)
        .filter(EntityEvent.entity_id == pid, EntityEvent.event_type == "process.steps_reordered")
        .order_by(EntityEvent.created_at.desc())
        .first()
    )
    assert event is not None, "reorder must emit a process.steps_reordered event"


# --------------------------------------------------------------------------------------
# Wizard helper: _next_step_position (backend.py:316-333)
# --------------------------------------------------------------------------------------


def test_next_step_position_first_step_defaults_to_1000(authed_client):
    from app.core.backend.backend import _next_step_position

    pid = _create_process(authed_client)["id"]
    assert _next_step_position(pid) == Decimal("1000")


def test_next_step_position_continues_the_1000_grid(authed_client):
    from app.core.backend.backend import _next_step_position

    pid = _create_process(authed_client)["id"]
    _add_step(authed_client, pid, 1, "First")
    assert _next_step_position(pid) == Decimal("2000")


def test_next_step_position_rounds_up_when_current_max_is_not_grid_aligned():
    """The DB's chk_steps_position_grid CHECK constraint means a real off-grid row can
    never actually persist (see the AC9 GAP notes on reorder for the one place that
    tries and 500s) — so this defensive rounding branch is exercised here by mocking
    the position lookup rather than seeding an impossible row."""
    from app.core.backend import backend

    with patch.object(backend.db_session, "query") as mock_query:
        mock_query.return_value.filter.return_value.order_by.return_value.limit.return_value.scalar.return_value = (
            Decimal("1500")
        )
        result = backend._next_step_position(uuid4())

    # mp=1500, rem=500, rounds up to 2000, then appends one more grid slot -> 3000.
    assert result == Decimal("3000")


# --------------------------------------------------------------------------------------
# process_docs_validation.py (68% covered per this review's coverage sweep)
# --------------------------------------------------------------------------------------


class TestDetectMimeFromPath:
    """Pure function — no DB, no Flask context needed."""

    def _write(self, tmp_path, content: bytes, suffix=".tmp"):
        p = tmp_path / f"upload{suffix}"
        p.write_bytes(content)
        return p

    def test_pdf_magic_bytes(self, tmp_path):
        from app.core.backend.process_docs.process_docs_validation import _detect_mime_from_path

        path = self._write(tmp_path, b"%PDF-1.4 rest of file")
        assert _detect_mime_from_path(path) == "application/pdf"

    def test_doc_magic_bytes(self, tmp_path):
        from app.core.backend.process_docs.process_docs_validation import _detect_mime_from_path

        path = self._write(tmp_path, b"\xd0\xcf\x11\xe0" + b"\x00" * 20)
        assert _detect_mime_from_path(path) == "application/msword"

    def test_zip_based_docx_extension_inference(self, tmp_path):
        from app.core.backend.process_docs.process_docs_validation import _detect_mime_from_path

        path = self._write(tmp_path, b"PK\x03\x04" + b"\x00" * 20)
        mime = _detect_mime_from_path(path, original_filename="sop.docx")
        assert mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def test_zip_based_md_extension_inference(self, tmp_path):
        from app.core.backend.process_docs.process_docs_validation import _detect_mime_from_path

        path = self._write(tmp_path, b"PK\x03\x04" + b"\x00" * 20)
        mime = _detect_mime_from_path(path, original_filename="notes.md")
        assert mime == "text/markdown"

    def test_zip_based_txt_extension_inference(self, tmp_path):
        from app.core.backend.process_docs.process_docs_validation import _detect_mime_from_path

        path = self._write(tmp_path, b"PK\x03\x04" + b"\x00" * 20)
        mime = _detect_mime_from_path(path, original_filename="readme.txt")
        assert mime == "text/plain"

    def test_zip_based_unknown_extension_falls_back_to_octet_stream(self, tmp_path):
        from app.core.backend.process_docs.process_docs_validation import _detect_mime_from_path

        path = self._write(tmp_path, b"PK\x03\x04" + b"\x00" * 20)
        mime = _detect_mime_from_path(path, original_filename="archive.zip")
        assert mime == "application/octet-stream"

    def test_no_magic_match_returns_none(self, tmp_path):
        from app.core.backend.process_docs.process_docs_validation import _detect_mime_from_path

        path = self._write(tmp_path, b"just some plain bytes with no magic header")
        assert _detect_mime_from_path(path) is None


class TestNormalizeContentType:
    def test_strips_charset_parameter(self):
        from app.core.backend.process_docs.process_docs_validation import _normalize_content_type

        assert _normalize_content_type("application/pdf; charset=utf-8") == "application/pdf"

    def test_lowercases_and_strips_whitespace(self):
        from app.core.backend.process_docs.process_docs_validation import _normalize_content_type

        assert _normalize_content_type("  APPLICATION/PDF  ") == "application/pdf"

    def test_none_and_empty_return_empty_string(self):
        from app.core.backend.process_docs.process_docs_validation import _normalize_content_type

        assert _normalize_content_type(None) == ""
        assert _normalize_content_type("") == ""


def test_validate_process_and_step_rejects_step_not_in_process(db):
    from app.core.backend.process_docs.process_docs_validation import validate_process_and_step

    org = OrganisationFactory()
    db.commit()
    repo = ProcessRepository(db)
    process_a = repo.create_process(org_id=org.id, name="Process A")
    process_b = repo.create_process(org_id=org.id, name="Process B")
    step_b = repo.add_step(process_id=process_b.id, org_id=org.id, step_number=1, position=Decimal("1000"), name="B1")

    ok, err = validate_process_and_step(org.id, process_a.id, step_b.id)
    assert ok is False
    assert "does not belong" in err.lower() or "not found" in err.lower()

    # Sanity: the step against its real, owning process passes.
    ok2, err2 = validate_process_and_step(org.id, process_b.id, step_b.id)
    assert ok2 is True
    assert err2 == ""

    db.query(Step).filter(Step.process_id.in_([process_a.id, process_b.id])).delete(synchronize_session=False)
    db.query(ProcessVersion).filter(ProcessVersion.process_id.in_([process_a.id, process_b.id])).delete(
        synchronize_session=False
    )
    db.query(type(process_a)).filter(type(process_a).id.in_([process_a.id, process_b.id])).delete(
        synchronize_session=False
    )
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()
