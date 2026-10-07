"""scripts/tenant_copy.py: one organisation moves between databases, and nothing else does.

The copy seeds production from a database that also holds thousands of test organisations,
so the properties that matter are isolation (no other tenant's row crosses), completeness
(every tenant table, verified) and that a failed or repeated copy changes nothing.
"""

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from app.utils.config_loader import config

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import tenant_copy  # noqa: E402

SCHEMA = """
CREATE TABLE alembic_version (version_num varchar(64) PRIMARY KEY);
CREATE TABLE organisations (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE users (
    id uuid PRIMARY KEY, org_id uuid NOT NULL REFERENCES organisations(id), email text NOT NULL,
    password_hash text, is_active boolean NOT NULL DEFAULT true, totp_secret text,
    two_factor_enabled boolean NOT NULL DEFAULT false, invite_token_hash text
);
CREATE TABLE notes (
    id serial PRIMARY KEY, org_id uuid NOT NULL REFERENCES organisations(id),
    author_id uuid REFERENCES users(id), parent_id integer REFERENCES notes(id), body text
);
CREATE TABLE xero_oauth_tokens (id uuid PRIMARY KEY, org_id uuid NOT NULL REFERENCES organisations(id), token text);
CREATE TABLE global_settings (id serial PRIMARY KEY, value text);
"""


def _url(database: str) -> str:
    from sqlalchemy.engine import URL

    return URL.create(
        "postgresql+psycopg2",
        username=config.db_user,
        password=config.db_password,
        host=config.db_host,
        port=config.db_port,
        database=database,
    ).render_as_string(hide_password=False)


@pytest.fixture
def databases():
    """Two throwaway databases with the same small tenant-shaped schema."""
    admin = create_engine(_url(config.db_name), isolation_level="AUTOCOMMIT")
    names = [f"tenant_copy_{uuid4().hex[:10]}_{side}" for side in ("src", "dst")]
    engines = []
    try:
        with admin.connect() as conn:
            for name in names:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
        for name in names:
            engine = create_engine(_url(name))
            with engine.begin() as conn:
                conn.execute(text(SCHEMA))
                conn.execute(text("INSERT INTO alembic_version VALUES ('rev_1')"))
            engines.append(engine)
        yield engines[0], engines[1]
    finally:
        for engine in engines:
            engine.dispose()
        with admin.connect() as conn:
            for name in names:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _seed(engine):
    ours, theirs = str(uuid4()), str(uuid4())
    owner, tester, stranger = str(uuid4()), str(uuid4()), str(uuid4())
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO organisations VALUES (:a, 'Ours'), (:b, 'Theirs')"), {"a": ours, "b": theirs})
        conn.execute(
            text(
                "INSERT INTO users (id, org_id, email, password_hash, totp_secret, two_factor_enabled) VALUES "
                "(:o, :a, 'owner@ours.example', 'hash-owner', NULL, false), "
                "(:t, :a, 'tester@ours.test', 'hash-tester', 'totp', true), "
                "(:s, :b, 'someone@theirs.example', 'hash-stranger', NULL, false)"
            ),
            {"o": owner, "t": tester, "s": stranger, "a": ours, "b": theirs},
        )
        conn.execute(
            text(
                "INSERT INTO notes (org_id, author_id, parent_id, body) VALUES "
                "(:a, :t, NULL, 'first'), (:a, :o, 1, 'reply to first'), (:b, :s, NULL, 'not ours')"
            ),
            {"a": ours, "b": theirs, "o": owner, "t": tester, "s": stranger},
        )
        conn.execute(
            text("INSERT INTO xero_oauth_tokens VALUES (:i, :a, 'secret-token')"), {"i": str(uuid4()), "a": ours}
        )
        conn.execute(text("INSERT INTO global_settings (value) VALUES ('shared')"))
    return ours, theirs


def test_dependency_order_puts_parents_first_and_survives_cycles():
    edges = [("child", "parent"), ("grandchild", "child"), ("a", "b"), ("b", "a"), ("child", "child"), ("x", "gone")]
    order = tenant_copy.dependency_order(["grandchild", "child", "parent", "a", "b", "x"], edges)
    assert order.index("parent") < order.index("child") < order.index("grandchild")
    assert sorted(order) == ["a", "b", "child", "grandchild", "parent", "x"]


def test_plan_lists_only_tenant_tables_and_reads_nothing_else(databases):
    source, _target = databases
    ours, _theirs = _seed(source)

    result = tenant_copy.plan(source, "Ours", frozenset({"xero_oauth_tokens"}))

    assert result["org_id"] == ours
    assert result["tables"] == {"organisations": 1, "users": 2, "notes": 2}
    assert result["skipped_tables"] == ["xero_oauth_tokens"]
    assert result["never_copied_no_org_id"] == ["alembic_version", "global_settings"]


def test_copy_moves_one_organisation_and_nothing_from_any_other(databases):
    source, target = databases
    ours, theirs = _seed(source)

    result = tenant_copy.copy(
        source,
        target,
        "Ours",
        skip_tables=frozenset({"xero_oauth_tokens"}),
        disable_users=frozenset({"tester@ours.test"}),
    )

    assert result["verified"] and result["copied_rows"] == 5 and result["other_organisations_in_target"] == 0
    with target.connect() as conn:
        assert conn.execute(text("SELECT name FROM organisations")).scalars().all() == ["Ours"]
        assert conn.execute(text("SELECT count(*) FROM users WHERE org_id = :b"), {"b": theirs}).scalar_one() == 0
        assert conn.execute(text("SELECT body FROM notes ORDER BY id")).scalars().all() == ["first", "reply to first"]
        assert conn.execute(text("SELECT count(*) FROM xero_oauth_tokens")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM global_settings")).scalar_one() == 0
        # The locked account stays, because a note refers to it, but can never sign in.
        tester = conn.execute(
            text(
                "SELECT is_active, password_hash, totp_secret, two_factor_enabled FROM users WHERE email = 'tester@ours.test'"
            )
        ).one()
        assert tester.is_active is False and tester.password_hash.startswith("!disabled-")
        assert tester.totp_secret is None and tester.two_factor_enabled is False
        owner = conn.execute(
            text("SELECT is_active, password_hash FROM users WHERE email = 'owner@ours.example'")
        ).one()
        assert owner.is_active is True and owner.password_hash == "hash-owner"
        # New rows must not collide with the copied serial ids.
        new_id = conn.execute(
            text("INSERT INTO notes (org_id, body) VALUES (:a, 'after copy') RETURNING id"), {"a": ours}
        ).scalar_one()
        assert new_id > 2
    # The source is never written to.
    with source.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM organisations")).scalar_one() == 2
        assert conn.execute(text("SELECT is_active FROM users WHERE email = 'tester@ours.test'")).scalar_one() is True


def test_copy_refuses_an_existing_organisation_unless_replacing(databases):
    source, target = databases
    ours, _theirs = _seed(source)
    tenant_copy.copy(source, target, "Ours")
    with target.begin() as conn:
        conn.execute(text("INSERT INTO notes (org_id, body) VALUES (:a, 'made in the target')"), {"a": ours})

    with pytest.raises(tenant_copy.TenantCopyError, match="already holds"):
        tenant_copy.copy(source, target, "Ours")
    with target.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM notes")).scalar_one() == 3, "a refused copy changes nothing"

    result = tenant_copy.copy(source, target, "Ours", replace=True)
    assert result["replaced_rows_deleted"] == 7
    with target.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM notes")).scalar_one() == 2


def test_copy_refuses_a_target_on_a_different_migration(databases):
    source, target = databases
    _seed(source)
    with target.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = 'rev_0'"))

    with pytest.raises(tenant_copy.TenantCopyError, match="migrate the target"):
        tenant_copy.copy(source, target, "Ours")
    with target.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM organisations")).scalar_one() == 0


def test_copy_commits_nothing_when_a_named_account_does_not_exist(databases):
    source, target = databases
    _seed(source)

    with pytest.raises(tenant_copy.TenantCopyError, match="--disable-user"):
        tenant_copy.copy(source, target, "Ours", disable_users=frozenset({"nobody@ours.example"}))
    with target.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM organisations")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 0


def test_unknown_or_ambiguous_organisation_is_refused(databases):
    source, target = databases
    _seed(source)
    with pytest.raises(tenant_copy.TenantCopyError, match="exactly one organisation"):
        tenant_copy.copy(source, target, "Nobody")
