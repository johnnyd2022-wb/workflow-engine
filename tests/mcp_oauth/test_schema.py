"""The six tables: tenant scoping, hashes only, reversible migration."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from app.core.db import engine
from app.core.db.models.tenant_mixin import TenantScoped
from app.core.security.tenant_scope import tenant_scope
from app.features.mcp_oauth.models import (
    McpAllowedRole,
    McpOrgSettings,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthGrant,
    OAuthToken,
)
from tests.mcp_oauth.support import mint_grant

TENANT_TABLES = {
    "mcp_org_settings": McpOrgSettings,
    "mcp_allowed_roles": McpAllowedRole,
    "oauth_grants": OAuthGrant,
    "oauth_authorization_codes": OAuthAuthorizationCode,
    "oauth_tokens": OAuthToken,
}


def _fks(table):
    return {
        fk["name"]: (tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
        for fk in inspect(engine).get_foreign_keys(table)
    }


def test_oauth_clients_is_the_one_global_table():
    assert "org_id" not in {c["name"] for c in inspect(engine).get_columns("oauth_clients")}
    assert not issubclass(OAuthClient, TenantScoped)


@pytest.mark.parametrize("table,model", TENANT_TABLES.items())
def test_every_other_table_is_tenant_scoped_with_a_not_null_org_id(table, model):
    columns = {c["name"]: c for c in inspect(engine).get_columns(table)}
    assert columns["org_id"]["nullable"] is False
    assert issubclass(model, TenantScoped)
    assert _fks(table)  # at least the organisations FK


def test_children_use_composite_org_foreign_keys():
    grants = _fks("oauth_grants")
    assert (("org_id", "user_id"), "users", ("org_id", "id")) in grants.values()
    codes = _fks("oauth_authorization_codes")
    assert (("org_id", "grant_id"), "oauth_grants", ("org_id", "id")) in codes.values()
    tokens = _fks("oauth_tokens")
    assert (("org_id", "grant_id"), "oauth_grants", ("org_id", "id")) in tokens.values()
    assert (("org_id", "replaced_by_id"), "oauth_tokens", ("org_id", "id")) in tokens.values()
    settings = _fks("mcp_org_settings")
    assert (("org_id", "updated_by_user_id"), "users", ("org_id", "id")) in settings.values()


def test_only_hashes_of_codes_and_tokens_are_stored():
    token_columns = {c["name"] for c in inspect(engine).get_columns("oauth_tokens")}
    code_columns = {c["name"] for c in inspect(engine).get_columns("oauth_authorization_codes")}
    assert "token_hash" in token_columns and "token" not in token_columns
    assert "code_hash" in code_columns and "code" not in code_columns
    assert "code_verifier" not in code_columns  # only the challenge is kept


def test_a_second_live_grant_for_the_same_person_and_client_is_refused_by_the_database(world, db):
    from sqlalchemy.exc import IntegrityError

    grant, _a, _r = mint_grant(db, world.users["member"], world.client_row)
    duplicate = OAuthGrant(
        org_id=world.org.id,
        user_id=world.users["member"].id,
        client_pk=world.client_row.id,
        resource=grant.resource,
        auth_stamp="x",
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_a_grant_cannot_point_at_a_user_of_another_org(world, db):
    from sqlalchemy.exc import IntegrityError

    bad = OAuthGrant(
        org_id=world.org.id,
        user_id=world.other_admin.id,  # belongs to the other org
        client_pk=world.client_row.id,
        resource="x",
        auth_stamp="x",
    )
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_a_token_cannot_point_at_a_grant_of_another_org(world, db):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.exc import IntegrityError

    grant, _a, _r = mint_grant(db, world.users["member"], world.client_row)
    bad = OAuthToken(
        org_id=world.other_org.id,
        grant_id=grant.id,
        kind="access",
        token_hash="h" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_the_global_tenant_filter_hides_other_orgs_grants(world, db):
    mine, _a, _r = mint_grant(db, world.users["member"], world.client_row)
    theirs, _a2, _r2 = mint_grant(db, world.other_admin, world.client_row)
    with tenant_scope(world.org.id):
        ids = {g.id for g in db.query(OAuthGrant).all()}
    assert mine.id in ids
    assert theirs.id not in ids


def test_deleting_an_org_removes_its_settings_grants_and_tokens(world, db):
    from app.core.db.models.organisation import Organisation

    grant, _a, _r = mint_grant(db, world.users["member"], world.client_row)
    grant_id, org_id = grant.id, world.org.id
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()
    db.expire_all()
    assert db.query(OAuthGrant).filter_by(id=grant_id).count() == 0
    assert db.query(OAuthToken).filter_by(grant_id=grant_id).count() == 0
    assert db.query(McpAllowedRole).filter_by(org_id=org_id).count() == 0
    assert db.get(McpOrgSettings, org_id) is None
    assert db.get(OAuthClient, world.client_row.id) is not None  # the global client stays
