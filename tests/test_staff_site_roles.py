"""Staff-site role foundation: tenant grants, staging and fail-closed HTTP coverage."""

# ruff: noqa: F811 -- re-exported pytest fixtures
from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.db.models.org_role import OrgRole
from app.core.db.models.org_role_site import OrgRoleSite
from app.core.db.models.site import Site
from app.core.db.models.user import User
from app.core.security.staff_site_endpoint_registry import ENDPOINT_COVERAGE
from app.core.security.staff_site_policy import coverage_for
from app.core.security.staff_site_roles import lock_role_administration
from app.core.security.staff_site_scope import StaffSiteScope, load_staff_site_scope
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.test_compliant_routes import flask_app  # noqa: F401
from tests.test_custom_roles import _login, org  # noqa: F401


def _sites(db, org_id):
    a = Site(org_id=org_id, name=f"A-{uuid4()}")
    b = Site(org_id=org_id, name=f"B-{uuid4()}")
    db.add_all([a, b])
    db.commit()
    return a, b


def _role(admin, **kwargs):
    response = admin.post("/org/roles", json={"name": f"Scope-{uuid4()}", "base_role": "member", **kwargs})
    assert response.status_code == 201, response.get_json()
    return response.get_json()["custom_roles"][-1]


def _person(admin, role):
    email = f"scoped-{uuid4()}@test.com"
    response = admin.post("/org/users", json={"email": email, "password": DEFAULT_TEST_PASSWORD, "role": role})
    assert response.status_code == 201, response.get_json()
    return response.get_json()["user"], email


def test_scope_is_immutable_and_transfer_requires_both_ends():
    a, b = uuid4(), uuid4()
    scope = StaffSiteScope(uuid4(), uuid4(), "selected", frozenset([a]))
    assert scope.permits(a) and not scope.permits(b) and not scope.permits(None)
    assert scope.permits_transfer(a, a) and not scope.permits_transfer(a, b) and not scope.permits_transfer(b, a)
    assert not StaffSiteScope(scope.org_id, scope.user_id, "selected").permits(a)
    assert not StaffSiteScope(scope.org_id, scope.user_id, "deny").permits_transfer(a, a)
    with pytest.raises(FrozenInstanceError):
        scope.mode = "all"


def test_endpoint_registry_covers_live_methods_and_new_routes_deny(flask_app):
    live = {(r.endpoint, m) for r in flask_app.url_map.iter_rules() for m in r.methods - {"HEAD", "OPTIONS"}}
    assert not live - set(ENDPOINT_COVERAGE)
    assert set(ENDPOINT_COVERAGE.values()) == {"blocked"}
    assert coverage_for("core.new_export", "GET") == "unclassified"
    assert coverage_for("core.get_inventory", "HEAD") == coverage_for("core.get_inventory", "GET")
    assert coverage_for("compliant.compliant_cca_movements.get_period_review", "GET") == "blocked"
    assert coverage_for("planning.get_capacity", "GET") == "blocked"
    assert coverage_for("planning.save_capacity", "POST") == "blocked"


def test_default_all_preserves_existing_assignment(org, db, flask_app):
    o, admin = org
    role = _role(admin)
    assert role["site_access_mode"] == "all" and role["site_ids"] == [] and role["assignable"]
    person, email = _person(admin, role["value"])
    scope = load_staff_site_scope(db, o.id, UUID(person["id"]))
    assert scope.mode == "all"
    staff = _login(flask_app, email)
    assert staff.get("/auth/me").status_code == 200
    assert staff.get("/api/core/inventory").status_code == 200


def test_configurable_selected_role_cannot_be_assigned_or_invited(org, db):
    o, admin = org
    a, b = _sites(db, o.id)
    role = _role(admin, site_access_mode="selected", site_ids=[str(a.id), str(a.id)])
    assert role["site_ids"] == [str(a.id)] and not role["assignable"]
    for password in ("", DEFAULT_TEST_PASSWORD):
        response = admin.post(
            "/org/users", json={"email": f"x-{uuid4()}@test.com", "password": password, "role": role["value"]}
        )
        assert response.status_code == 400 and "cannot be assigned" in response.get_json()["error"]
    person, _ = _person(admin, "member")
    assert admin.patch("/org/users/" + person["id"], json={"role": role["value"]}).status_code == 400
    response = admin.patch("/org/roles/" + role["id"], json={"site_ids": [str(b.id)]})
    assert response.status_code == 200
    saved = next(r for r in response.get_json()["custom_roles"] if r["id"] == role["id"])
    assert saved["site_ids"] == [str(b.id)]


def test_occupied_role_cannot_switch_to_selected_and_rolls_back(org, db):
    o, admin = org
    a, _ = _sites(db, o.id)
    role = _role(admin)
    _person(admin, role["value"])
    response = admin.patch(
        "/org/roles/" + role["id"], json={"name": "Changed", "site_access_mode": "selected", "site_ids": [str(a.id)]}
    )
    assert response.status_code == 400
    db.expire_all()
    persisted = db.get(OrgRole, UUID(role["id"]))
    assert persisted.name == role["name"] and persisted.site_access_mode == "all"
    assert not db.scalars(select(OrgRoleSite).where(OrgRoleSite.role_id == persisted.id)).all()


@pytest.mark.parametrize(
    "values",
    [
        {"site_access_mode": None},
        {"site_access_mode": "bogus"},
        {"site_ids": None},
        {"site_ids": "all"},
        {"site_access_mode": "selected", "site_ids": [True]},
        {"site_access_mode": "selected", "site_ids": ["bad"]},
        {"site_access_mode": "selected", "site_ids": [str(uuid4())]},
    ],
)
def test_invalid_site_configuration_is_rejected(org, values):
    _, admin = org
    response = admin.post("/org/roles", json={"name": f"Bad-{uuid4()}", "base_role": "member", **values})
    assert response.status_code == 400


def test_inactive_foreign_and_all_mode_grants_are_rejected(org, db):
    o, admin = org
    a, _ = _sites(db, o.id)
    a.is_active = False
    db.commit()
    for mode in ("all", "selected"):
        assert (
            admin.post(
                "/org/roles",
                json={
                    "name": f"Bad-{uuid4()}",
                    "base_role": "member",
                    "site_access_mode": mode,
                    "site_ids": [str(a.id)],
                },
            ).status_code
            == 400
        )
    # Wrong-org role/site relation is rejected by the database too.
    role = _role(admin)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(OrgRoleSite(org_id=uuid4(), role_id=UUID(role["id"]), site_id=a.id))
            db.flush()


def test_empty_selected_raw_assignment_is_denied_and_org_optout_is_no_bypass(org, db, flask_app):
    o, admin = org
    role = _role(admin, site_access_mode="selected", site_ids=[])
    person, email = _person(admin, "member")
    uid = UUID(person["id"])
    db.query(User).filter(User.id == uid).update({User.custom_role_id: UUID(role["id"])}, synchronize_session=False)
    db.commit()
    assert load_staff_site_scope(db, o.id, uid).mode == "deny"
    staff = _login(flask_app, email)
    for path in (
        "/auth/me",
        "/api/core/inventory",
        "/api/core/executions",
        "/api/core/changes",
        "/api/core/evidence/config",
        "/api/planning/demands",
    ):
        response = staff.get(path)
        # Unknown URLs are 404; registered unsupported data handlers always refuse.
        assert response.status_code in (403, 404), (path, response.status_code)
    assert staff.post("/auth/logout").status_code == 200


def test_fresh_scope_ignores_cached_role_and_foreign_custom_role(org, db):
    o, admin = org
    a, b = _sites(db, o.id)
    role = _role(admin)
    person, _ = _person(admin, role["value"])
    cached = db.get(OrgRole, UUID(role["id"]))
    # Raw SQL simulates a privileged assignment outside the staged API; the request
    # projection must not reuse the cached all-mode ORM role.
    db.execute(text("UPDATE org_roles SET site_access_mode='selected' WHERE id=:id"), {"id": cached.id})
    db.add(OrgRoleSite(org_id=o.id, role_id=cached.id, site_id=a.id))
    db.flush()
    assert cached.site_access_mode == "all"
    scope = load_staff_site_scope(db, o.id, UUID(person["id"]))
    assert scope.mode == "selected" and scope.site_ids == frozenset([a.id])
    assert not scope.permits_transfer(a.id, b.id)
    assert load_staff_site_scope(db, uuid4(), UUID(person["id"])).mode == "deny"
    db.rollback()


def test_role_administration_uses_no_key_update_not_fk_conflicting_update(org, db):
    o, _ = org
    lock_role_administration(db, o.id)
    locks = (
        db.execute(text("SELECT mode FROM pg_locks WHERE pid=pg_backend_pid() AND relation='organisations'::regclass"))
        .scalars()
        .all()
    )
    assert "RowShareLock" in locks
    db.rollback()


def test_valid_selected_raw_principal_cannot_access_private_public_handlers(org, db, flask_app):
    o, admin = org
    a, _ = _sites(db, o.id)
    role = _role(admin, site_access_mode="selected", site_ids=[str(a.id)])
    person, email = _person(admin, "member")
    db.query(User).filter(User.id == UUID(person["id"])).update(
        {User.custom_role_id: UUID(role["id"])}, synchronize_session=False
    )
    db.commit()
    scope = load_staff_site_scope(db, o.id, UUID(person["id"]))
    assert scope.mode == "selected" and scope.permits(a.id)
    staff = _login(flask_app, email)
    for path in ("/auth/me", "/api/core/inventory", "/api/core/executions", "/core/dashboard", "/core/people"):
        response = staff.get(path)
        assert response.status_code == 403, (path, response.status_code)
        assert response.get_json()["code"] == "site_scope_not_available"
    assert staff.post("/auth/logout").status_code == 200
    # The same Flask app context must not keep the prior principal's restriction.
    assert admin.get("/org/roles").status_code == 200


def test_archived_existing_grant_survives_role_edit_but_new_inactive_grant_is_refused(org, db):
    o, admin = org
    a, b = _sites(db, o.id)
    role = _role(admin, site_access_mode="selected", site_ids=[str(a.id)])
    a.is_active = False
    b.is_active = False
    db.commit()
    assert admin.patch("/org/roles/" + role["id"], json={"name": "Archived history reader"}).status_code == 200
    assert admin.patch("/org/roles/" + role["id"], json={"site_ids": [str(a.id), str(b.id)]}).status_code == 400
    response = admin.patch("/org/roles/" + role["id"], json={"site_access_mode": "all"})
    assert response.status_code == 200
    saved = next(r for r in response.get_json()["custom_roles"] if r["id"] == role["id"])
    assert saved["site_ids"] == [] and saved["assignable"]


def test_role_mode_check_and_compound_site_fk(org, db):
    from tests.factories import OrganisationFactory

    o, admin = org
    a, _ = _sites(db, o.id)
    role = _role(admin)
    other = OrganisationFactory()
    other_site = Site(org_id=other.id, name=f"Foreign-{uuid4()}")
    db.add(other_site)
    db.commit()
    try:
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.add(OrgRoleSite(org_id=o.id, role_id=UUID(role["id"]), site_id=other_site.id))
                db.flush()
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.execute(
                    text("UPDATE org_roles SET site_access_mode='unknown' WHERE id=:id"), {"id": UUID(role["id"])}
                )
    finally:
        db.query(Site).filter(Site.org_id == other.id).delete(synchronize_session=False)
        from app.core.db.models.organisation import Organisation

        db.query(Organisation).filter(Organisation.id == other.id).delete(synchronize_session=False)
        db.commit()


def test_role_configuration_and_assignment_serialized_on_org(org, db):
    """Real PG wait proves an assignment cannot race occupied-role configuration."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from time import monotonic

    from sqlalchemy.orm import Session

    from app.core.security.people import PeopleError, parse_role_choice
    from app.core.security.staff_site_roles import replace_site_config

    o, admin = org
    a, _ = _sites(db, o.id)
    role_data = _role(admin)
    person, _ = _person(admin, "member")
    db.rollback()
    first = Session(db.bind)
    second = Session(db.bind)
    started = threading.Event()
    try:
        lock_role_administration(first, o.id)
        role = first.get(OrgRole, UUID(role_data["id"]))
        replace_site_config(first, role, "selected", frozenset([a.id]))
        first.flush()
        role_id = role.id
        second_pid = second.scalar(text("SELECT pg_backend_pid()"))

        def assign():
            started.set()
            lock_role_administration(second, o.id)
            fresh = second.get(OrgRole, role_id)
            with pytest.raises(PeopleError, match="cannot be assigned"):
                parse_role_choice(role_data["value"], [fresh])
            second.rollback()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(assign)
            try:
                assert started.wait(2)
                deadline = monotonic() + 5
                blocked = False
                while monotonic() < deadline:
                    blocked = bool(
                        first.scalar(text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": second_pid})
                    )
                    if blocked:
                        break
                    threading.Event().wait(0.01)
                assert blocked and not future.done()
            finally:
                first.commit()
            future.result(timeout=5)
        assert db.get(User, UUID(person["id"])).custom_role_id is None
    finally:
        first.rollback()
        first.close()
        second.rollback()
        second.close()


def test_corrupt_all_mode_grants_and_foreign_custom_role_never_fall_back(org, db):
    from app.core.db.models.organisation import Organisation
    from tests.factories import OrganisationFactory

    o, admin = org
    a, _ = _sites(db, o.id)
    role = _role(admin)
    person, _ = _person(admin, role["value"])
    uid = UUID(person["id"])
    db.add(OrgRoleSite(org_id=o.id, role_id=UUID(role["id"]), site_id=a.id))
    db.flush()
    assert load_staff_site_scope(db, o.id, uid).reason == "invalid_site_grants"
    db.rollback()
    other = OrganisationFactory()
    foreign = OrgRole(org_id=other.id, name=f"Foreign-{uuid4()}", base_role="member", permissions=["inventory.view"])
    db.add(foreign)
    db.flush()
    db.query(User).filter(User.id == uid).update({User.custom_role_id: foreign.id}, synchronize_session=False)
    db.flush()
    assert load_staff_site_scope(db, o.id, uid).reason == "invalid_custom_role"
    db.rollback()
    db.query(OrgRole).filter(OrgRole.org_id == other.id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == other.id).delete(synchronize_session=False)
    db.commit()


def test_custom_admin_and_base_mismatch_are_denied(org, db):
    o, admin = org
    role = _role(admin)
    person, _ = _person(admin, role["value"])
    uid = UUID(person["id"])
    for base in ("admin", "production"):
        db.execute(text("UPDATE org_roles SET base_role=:base WHERE id=:id"), {"base": base, "id": UUID(role["id"])})
        assert load_staff_site_scope(db, o.id, uid).reason == "invalid_custom_role"
    db.rollback()
