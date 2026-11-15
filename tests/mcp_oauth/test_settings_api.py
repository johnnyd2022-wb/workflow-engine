"""AC22-AC23 and GET /api/core/mcp/me: settings, connected apps, the `workflow mcp` CLI."""

from __future__ import annotations

from uuid import uuid4

from click.testing import CliRunner

from app.core.db.models.org_role import OrgRole
from app.core.db.models.user import User, UserRole
from app.features.mcp_oauth.models import McpAllowedRole, McpOrgSettings, OAuthGrant, OAuthToken
from tests.mcp_oauth.support import bearer, make_client, mint_grant


def _settings(db, org_id):
    db.expire_all()
    row = db.get(McpOrgSettings, org_id)
    keys = sorted(r.role_key for r in db.query(McpAllowedRole).filter_by(org_id=org_id))
    return row, keys


# --- GET /settings ------------------------------------------------------------------------------


def test_a_new_org_is_off_with_no_roles(world, db):
    db.query(McpAllowedRole).filter_by(org_id=world.org.id).delete()
    db.query(McpOrgSettings).filter_by(org_id=world.org.id).delete()
    db.commit()
    body = world.session("admin").get("/api/core/mcp/settings").get_json()
    assert body["enabled"] is False
    assert body["allowed_roles"] == []
    keys = {r["key"] for r in body["roles"]}
    assert keys == {f"builtin:{r.value}" for r in UserRole}
    labels = {r["key"]: r["label"] for r in body["roles"]}
    assert labels["builtin:member"] == "Staff"
    assert all(r["custom"] is False for r in body["roles"])


def test_the_roles_list_includes_this_orgs_custom_roles_and_no_other_orgs(world, db):
    mine = OrgRole(org_id=world.org.id, name="Mine", base_role="member", permissions=[])
    theirs = OrgRole(org_id=world.other_org.id, name="Theirs", base_role="member", permissions=[])
    db.add_all([mine, theirs])
    db.commit()
    body = world.session("admin").get("/api/core/mcp/settings").get_json()
    custom = [r for r in body["roles"] if r["custom"]]
    assert [r["key"] for r in custom] == [f"custom:{mine.id}"]
    assert custom[0]["label"] == "Mine"


def test_only_users_manage_can_read_the_settings(world):
    assert world.session("member").get("/api/core/mcp/settings").status_code == 403
    assert world.session("sales").get("/api/core/mcp/settings").status_code == 403


# --- AC22 ---------------------------------------------------------------------------------------


def test_ac22_admin_saves_the_settings_and_an_audit_row_is_written(world, db):
    from app.core.db.models.audit_log import AuditLog

    world.enable(enabled=False, roles=[])
    resp = world.session("admin").put(
        "/api/core/mcp/settings", json={"enabled": True, "allowed_roles": ["builtin:admin", "builtin:sales"]}
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["enabled"] is True
    assert sorted(body["allowed_roles"]) == ["builtin:admin", "builtin:sales"]
    row, keys = _settings(db, world.org.id)
    assert row.enabled is True
    assert row.updated_by_user_id == world.users["admin"].id
    assert keys == ["builtin:admin", "builtin:sales"]
    audit = db.query(AuditLog).filter_by(org_id=world.org.id, action="mcp_settings_updated").all()
    assert len(audit) == 1
    assert audit[0].user_id == world.users["admin"].id
    assert audit[0].meta_data["enabled"] is True


def test_ac22_saving_replaces_the_role_list_and_can_turn_it_off(world, db):
    session = world.session("admin")
    assert (
        session.put("/api/core/mcp/settings", json={"enabled": True, "allowed_roles": ["builtin:admin"]}).status_code
        == 200
    )
    assert (
        session.put("/api/core/mcp/settings", json={"enabled": False, "allowed_roles": ["builtin:member"]}).status_code
        == 200
    )
    row, keys = _settings(db, world.org.id)
    assert row.enabled is False
    assert keys == ["builtin:member"]


def test_ac22_a_custom_role_of_this_org_can_be_ticked(world, db):
    role = OrgRole(org_id=world.org.id, name="Bottling", base_role="production", permissions=["production.view"])
    db.add(role)
    db.commit()
    resp = world.session("admin").put(
        "/api/core/mcp/settings", json={"enabled": True, "allowed_roles": [f"custom:{role.id}"]}
    )
    assert resp.status_code == 200
    assert _settings(db, world.org.id)[1] == [f"custom:{role.id}"]


def test_ac22_a_member_gets_403_and_nothing_changes(world, db):
    world.enable(enabled=False, roles=[])
    resp = world.session("member").put(
        "/api/core/mcp/settings", json={"enabled": True, "allowed_roles": ["builtin:member"]}
    )
    assert resp.status_code == 403
    row, keys = _settings(db, world.org.id)
    assert row.enabled is False and keys == []


def test_ac22_a_token_gets_403_even_for_an_admin(world, db):
    _g, access, _r = mint_grant(db, world.users["admin"], world.client_row)
    resp = world.anon().put(
        "/api/core/mcp/settings", json={"enabled": True, "allowed_roles": ["builtin:admin"]}, headers=bearer(access)
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "insufficient_scope"
    assert world.anon().get("/api/core/mcp/settings", headers=bearer(access)).status_code == 403


def test_ac22_a_custom_role_key_from_another_org_is_400(world, db):
    foreign = OrgRole(org_id=world.other_org.id, name="Foreign", base_role="member", permissions=[])
    db.add(foreign)
    db.commit()
    world.enable(enabled=False, roles=[])
    resp = world.session("admin").put(
        "/api/core/mcp/settings", json={"enabled": True, "allowed_roles": [f"custom:{foreign.id}"]}
    )
    assert resp.status_code == 400
    row, keys = _settings(db, world.org.id)
    assert row.enabled is False and keys == []


def test_ac22_bad_bodies_are_400(world):
    session = world.session("admin")
    bad = [
        {"enabled": True, "allowed_roles": ["builtin:wizard"]},
        {"enabled": True, "allowed_roles": ["custom:not-a-uuid"]},
        {"enabled": True, "allowed_roles": [f"custom:{uuid4()}"]},  # no such role
        {"enabled": True, "allowed_roles": ["admin"]},  # not a key
        {"enabled": "yes", "allowed_roles": []},
        {"enabled": True, "allowed_roles": "builtin:admin"},
        {"enabled": True, "allowed_roles": [1]},
        {"allowed_roles": []},
        {"enabled": True},
        {"enabled": True, "allowed_roles": [], "surprise": 1},
    ]
    for body in bad:
        assert session.put("/api/core/mcp/settings", json=body).status_code == 400, body
    assert session.put("/api/core/mcp/settings", data="x", content_type="text/plain").status_code == 400


def test_ac22_the_saved_settings_apply_to_a_token_at_once(world, db):
    _g, access, _r = mint_grant(db, world.users["member"], world.client_row)
    assert world.anon().get("/api/core/inventory", headers=bearer(access)).status_code == 200
    resp = world.session("admin").put(
        "/api/core/mcp/settings", json={"enabled": True, "allowed_roles": ["builtin:admin"]}
    )
    assert resp.status_code == 200
    assert world.anon().get("/api/core/inventory", headers=bearer(access)).status_code == 403


def test_deleting_a_custom_role_removes_its_key_from_the_allowed_roles(world, db):
    role = OrgRole(org_id=world.org.id, name="Short lived", base_role="production", permissions=[])
    db.add(role)
    db.commit()
    world.enable(roles=["admin"], extra_keys=[f"custom:{role.id}"])
    resp = world.session("admin").delete(f"/org/roles/{role.id}")
    assert resp.status_code == 200, resp.get_json()
    assert _settings(db, world.org.id)[1] == ["builtin:admin"]


# --- AC23 ---------------------------------------------------------------------------------------


def _grant_row(rows, grant):
    return next((r for r in rows if r["id"] == str(grant.id)), None)


def test_ac23_an_admin_sees_all_of_the_orgs_grants_and_a_member_only_their_own(world, db):
    g_member, _a, _r = mint_grant(db, world.users["member"], world.client_row)
    other_client = make_client(db, name="MCPTEST Second", verified=True)
    g_sales, _a2, _r2 = mint_grant(db, world.users["sales"], other_client)
    g_foreign, _a3, _r3 = mint_grant(db, world.other_admin, world.client_row)

    admin_rows = world.session("admin").get("/api/core/mcp/grants").get_json()["grants"]
    ids = {r["id"] for r in admin_rows}
    assert str(g_member.id) in ids and str(g_sales.id) in ids
    assert str(g_foreign.id) not in ids  # another org's, never

    member_rows = world.session("member").get("/api/core/mcp/grants").get_json()["grants"]
    assert {r["id"] for r in member_rows} == {str(g_member.id)}

    row = _grant_row(admin_rows, g_sales)
    assert row["client_name"] == "MCPTEST Second"
    assert row["verified"] is True
    assert row["scope"] == "bize.read"
    assert row["user"]["email"] == world.users["sales"].email
    assert row["created_at"] and "last_used_at" in row
    assert "token" not in " ".join(row).lower()


def test_ac23_revoked_grants_are_not_listed(world, db):
    from datetime import UTC, datetime

    grant, _a, _r = mint_grant(db, world.users["member"], world.client_row)
    db.get(OAuthGrant, grant.id).revoked_at = datetime.now(UTC)
    db.commit()
    assert world.session("admin").get("/api/core/mcp/grants").get_json()["grants"] == []


def test_ac23_revoking_makes_the_grants_tokens_get_401_and_writes_an_audit_row(world, db):
    from app.core.db.models.audit_log import AuditLog

    grant, access, refresh = mint_grant(db, world.users["member"], world.client_row)
    assert world.anon().get("/api/core/inventory", headers=bearer(access)).status_code == 200
    resp = world.session("member").post(f"/api/core/mcp/grants/{grant.id}/revoke")
    assert resp.status_code == 200
    assert world.anon().get("/api/core/inventory", headers=bearer(access)).status_code == 401
    db.expire_all()
    assert db.get(OAuthGrant, grant.id).revoked_at is not None
    assert all(t.revoked_at is not None for t in db.query(OAuthToken).filter_by(grant_id=grant.id))
    assert (
        db.query(AuditLog).filter_by(org_id=world.org.id, action="mcp_grant_revoked", entity_id=grant.id).count() == 1
    )
    again = world.session("member").post(f"/api/core/mcp/grants/{grant.id}/revoke")
    assert again.status_code == 404
    assert refresh


def test_ac23_an_admin_can_revoke_anyones_grant_in_the_org(world, db):
    grant, access, _r = mint_grant(db, world.users["sales"], world.client_row)
    assert world.session("admin").post(f"/api/core/mcp/grants/{grant.id}/revoke").status_code == 200
    assert world.anon().get("/api/core/inventory", headers=bearer(access)).status_code == 401


def test_ac23_a_member_cannot_revoke_someone_elses_grant(world, db):
    grant, access, _r = mint_grant(db, world.users["sales"], world.client_row)
    resp = world.session("member").post(f"/api/core/mcp/grants/{grant.id}/revoke")
    assert resp.status_code == 404
    assert world.anon().get("/api/core/inventory", headers=bearer(access)).status_code == 200


def test_ac23_nobody_can_revoke_another_orgs_grant(world, db):
    grant, access, _r = mint_grant(db, world.other_admin, world.client_row)
    resp = world.session("admin").post(f"/api/core/mcp/grants/{grant.id}/revoke")
    assert resp.status_code == 404
    db.expire_all()
    assert db.get(OAuthGrant, grant.id).revoked_at is None
    assert world.session("admin").post("/api/core/mcp/grants/not-a-uuid/revoke").status_code == 404
    assert access


def test_ac23_revoking_through_a_token_is_refused(world, db):
    grant, access, _r = mint_grant(db, world.users["admin"], world.client_row)
    resp = world.anon().post(f"/api/core/mcp/grants/{grant.id}/revoke", headers=bearer(access))
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "insufficient_scope"


# --- GET /api/core/mcp/me -----------------------------------------------------------------------


def test_me_returns_the_token_users_read_permissions_org_and_name(world, db):
    db.get(User, world.users["sales"].id).first_name = "Sam"
    db.get(User, world.users["sales"].id).last_name = "Seller"
    db.commit()
    _g, access, _r = mint_grant(db, world.users["sales"], world.client_row)
    resp = world.anon().get("/api/core/mcp/me", headers=bearer(access))
    assert resp.status_code == 200
    body = resp.get_json()
    assert sorted(body["permissions"]) == ["inventory.view", "sales.view"]  # sales.record is not a read permission
    assert body["org"]["name"] == world.org.name
    assert body["user"]["name"] == "Sam Seller"
    assert body["scope"] == "bize.read"
    assert body["auth"] == "mcp"


def test_me_for_an_admin_is_the_five_view_permissions_and_never_the_manage_ones(world, db):
    _g, access, _r = mint_grant(db, world.users["admin"], world.client_row)
    body = world.anon().get("/api/core/mcp/me", headers=bearer(access)).get_json()
    assert sorted(body["permissions"]) == sorted(
        ["production.view", "inventory.view", "sales.view", "compliance.view", "costs.view"]
    )


def test_me_works_for_a_session_too(world):
    body = world.session("auditor").get("/api/core/mcp/me").get_json()
    assert sorted(body["permissions"]) == ["compliance.view", "inventory.view", "production.view", "sales.view"]
    assert body["auth"] == "session"


def test_me_needs_a_sign_in(world):
    assert world.anon().get("/api/core/mcp/me").status_code in {401, 302}


def test_a_token_use_stamps_last_used_at_at_most_once_a_minute(world, db):
    grant, access, _r = mint_grant(db, world.users["member"], world.client_row)
    client = world.anon()
    client.get("/api/core/mcp/me", headers=bearer(access))
    db.expire_all()
    first = db.get(OAuthGrant, grant.id).last_used_at
    assert first is not None
    client.get("/api/core/mcp/me", headers=bearer(access))
    db.expire_all()
    assert db.get(OAuthGrant, grant.id).last_used_at == first


# --- CLI ----------------------------------------------------------------------------------------


def _run(*args):
    from app.cli import cli

    return CliRunner().invoke(cli, ["mcp", *args])


def test_cli_enable_sets_the_switch_and_the_roles(world, db):
    world.enable(enabled=False, roles=[])
    result = _run("enable", "--org-id", str(world.org.id), "--roles", "admin,member")
    assert result.exit_code == 0, result.output
    row, keys = _settings(db, world.org.id)
    assert row.enabled is True
    assert keys == ["builtin:admin", "builtin:member"]


def test_cli_enable_rejects_an_unknown_role_and_an_unknown_org(world, db):
    world.enable(enabled=False, roles=[])
    bad_role = _run("enable", "--org-id", str(world.org.id), "--roles", "admin,wizard")
    assert bad_role.exit_code != 0
    assert _settings(db, world.org.id)[0].enabled is False
    bad_org = _run("enable", "--org-id", str(uuid4()), "--roles", "admin")
    assert bad_org.exit_code != 0
    not_a_uuid = _run("enable", "--org-id", "nope", "--roles", "admin")
    assert not_a_uuid.exit_code != 0


def test_cli_disable_turns_it_off_and_keeps_the_roles(world, db):
    world.enable(enabled=True, roles=["admin"])
    result = _run("disable", "--org-id", str(world.org.id))
    assert result.exit_code == 0, result.output
    row, keys = _settings(db, world.org.id)
    assert row.enabled is False
    assert keys == ["builtin:admin"]
