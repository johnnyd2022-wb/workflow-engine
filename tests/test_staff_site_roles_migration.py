"""Migration backfill and downgrade authorization safety on real PostgreSQL."""

from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db.migrations.versions import staff_site_roles_001 as migration


def test_existing_roles_backfill_all_without_guessed_grants(db):
    org_id, role_id = uuid4(), uuid4()
    with db.bind.connect() as conn:
        transaction = conn.begin()
        try:
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade()
                conn.execute(
                    text(
                        "INSERT INTO organisations (id,name,status,created_at,updated_at) VALUES (:id,'Migration site role','ACTIVE',now(),now())"
                    ),
                    {"id": org_id},
                )
                conn.execute(
                    text("INSERT INTO org_roles (id,org_id,name,base_role) VALUES (:id,:org,'Legacy','member')"),
                    {"id": role_id, "org": org_id},
                )
                migration.upgrade()
                assert (
                    conn.scalar(text("SELECT site_access_mode FROM org_roles WHERE id=:id"), {"id": role_id}) == "all"
                )
                assert conn.scalar(text("SELECT count(*) FROM org_role_sites WHERE role_id=:id"), {"id": role_id}) == 0
                migration.downgrade()
        finally:
            transaction.rollback()


def test_downgrade_refuses_assigned_selected_role(db):
    org_id, role_id, user_id = uuid4(), uuid4(), uuid4()
    with db.bind.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(
                text(
                    "INSERT INTO organisations (id,name,status,created_at,updated_at) VALUES (:id,'Migration scoped role','ACTIVE',now(),now())"
                ),
                {"id": org_id},
            )
            conn.execute(
                text(
                    "INSERT INTO org_roles (id,org_id,name,base_role,site_access_mode) VALUES (:id,:org,'Restricted','member','selected')"
                ),
                {"id": role_id, "org": org_id},
            )
            conn.execute(
                text(
                    "INSERT INTO users (id,org_id,email,password_hash,role,is_active,custom_role_id,created_at) VALUES (:id,:org,:email,'invalid','MEMBER',true,:role,now())"
                ),
                {"id": user_id, "org": org_id, "email": f"migration-{user_id}@test.com", "role": role_id},
            )
            with pytest.raises(DBAPIError, match="Remove selected-site role assignments"):
                with conn.begin_nested():
                    with Operations.context(MigrationContext.configure(conn)):
                        migration.downgrade()
            assert (
                conn.scalar(text("SELECT site_access_mode FROM org_roles WHERE id=:id"), {"id": role_id}) == "selected"
            )
        finally:
            transaction.rollback()
