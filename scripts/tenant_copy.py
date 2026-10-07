"""Copy one organisation, and nothing else, from one database to another.

Built to seed production with a real tenant out of the shared test database, which also
holds thousands of test organisations that must never reach production.

It works because tenancy is by column: every tenant table carries ``org_id``. The tool
copies ``organisations`` (the one row) and then every table that has an ``org_id`` column,
filtered to that organisation. A table with no ``org_id`` is never copied, so anything that
is not provably the tenant's stays behind. Nothing is ever written to the source.

    # what would be copied, table by table (reads only)
    python3 scripts/tenant_copy.py plan --source-url postgresql://... --org-name "Whistlebird Ltd"

    # copy, then verify row counts table by table
    python3 scripts/tenant_copy.py copy --source-url ... --target-url ... --org-name "Whistlebird Ltd" \\
        --skip-table xero_oauth_tokens --disable-user someone@example.test

Safety rules:
  * the target must be at the same migration revision as the source;
  * the target must not already hold the organisation, unless ``--replace`` is given, which
    deletes only that organisation's rows in the target first;
  * the whole copy is one transaction on the target, verified before commit.
"""

from __future__ import annotations

import argparse
import io
import json
import secrets
import sys
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine


class TenantCopyError(RuntimeError):
    """A precondition failed or verification did not match; nothing was committed."""


@dataclass(frozen=True)
class Table:
    name: str
    filter_column: str  # "id" for organisations, "org_id" for every tenant table


def _ident(name: str) -> str:
    """Quote an identifier taken from the catalogue (never from user input)."""
    return '"' + name.replace('"', '""') + '"'


def tenant_tables(conn: Connection, schema: str = "public") -> list[Table]:
    """``organisations`` plus every base table with an ``org_id`` column, parents first.

    Ordering is by foreign-key dependency so a plain insert order is valid. Tables in a
    cycle (or self-referencing) keep a stable alphabetical order; the copy defers constraint
    checks for those by running with ``session_replication_role = replica``.
    """
    names = [
        row[0]
        for row in conn.execute(
            text(
                "SELECT c.table_name FROM information_schema.columns c "
                "JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
                "WHERE c.table_schema = :schema AND c.column_name = 'org_id' AND t.table_type = 'BASE TABLE' "
                "ORDER BY c.table_name"
            ),
            {"schema": schema},
        )
    ]
    edges = conn.execute(
        text(
            "SELECT DISTINCT child.relname, parent.relname FROM pg_constraint k "
            "JOIN pg_class child ON child.oid = k.conrelid JOIN pg_class parent ON parent.oid = k.confrelid "
            "JOIN pg_namespace n ON n.oid = child.relnamespace "
            "WHERE k.contype = 'f' AND n.nspname = :schema"
        ),
        {"schema": schema},
    ).fetchall()
    return [Table("organisations", "id"), *[Table(name, "org_id") for name in dependency_order(names, edges)]]


def dependency_order(names: list[str], edges: list[tuple[str, str]]) -> list[str]:
    """Parents before children. Unknown tables and self-references are ignored; a cycle is
    broken alphabetically so the result is always complete and deterministic."""
    wanted = set(names)
    parents = {name: set() for name in names}
    for child, parent in edges:
        if child in wanted and parent in wanted and child != parent:
            parents[child].add(parent)
    ordered: list[str] = []
    remaining = set(names)
    while remaining:
        ready = sorted(name for name in remaining if not (parents[name] & remaining))
        if not ready:  # a cycle: take the alphabetically first and carry on
            ready = [sorted(remaining)[0]]
        ordered.extend(ready)
        remaining -= set(ready)
    return ordered


def _org_id(conn: Connection, org_name: str) -> str:
    rows = conn.execute(text("SELECT id FROM organisations WHERE name = :name"), {"name": org_name}).fetchall()
    if len(rows) != 1:
        raise TenantCopyError(f"expected exactly one organisation named {org_name!r}, found {len(rows)}")
    return str(rows[0][0])


def _revision(conn: Connection) -> str | None:
    try:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:  # a database with no schema yet
        raise TenantCopyError("no alembic_version table: migrate this database first") from exc


def _count(conn: Connection, table: Table, org_id: str) -> int:
    return conn.execute(
        text(f"SELECT count(*) FROM {_ident(table.name)} WHERE {_ident(table.filter_column)} = :org"), {"org": org_id}
    ).scalar_one()


def plan(source: Engine, org_name: str, skip_tables: frozenset[str] = frozenset()) -> dict[str, Any]:
    with source.connect() as conn:
        org_id = _org_id(conn, org_name)
        tables = tenant_tables(conn)
        all_tables = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            )
        }
        counts = {table.name: _count(conn, table, org_id) for table in tables if table.name not in skip_tables}
        return {
            "organisation": org_name,
            "org_id": org_id,
            "revision": _revision(conn),
            "tables": counts,
            "rows": sum(counts.values()),
            "skipped_tables": sorted(skip_tables & {table.name for table in tables}),
            "never_copied_no_org_id": sorted(all_tables - {table.name for table in tables}),
        }


def _columns(conn: Connection, table: str) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :table ORDER BY ordinal_position"
            ),
            {"table": table},
        )
    ]


def _copy_table(source_raw, target_raw, table: Table, columns: list[str], org_id: str) -> None:
    """Stream one table's tenant rows source -> target with COPY (binary-safe text format)."""
    column_list = ", ".join(_ident(column) for column in columns)
    buffer = io.StringIO()
    with source_raw.cursor() as cursor:
        select = cursor.mogrify(
            f"SELECT {column_list} FROM {_ident(table.name)} WHERE {_ident(table.filter_column)} = %s", (org_id,)
        ).decode()
        cursor.copy_expert(f"COPY ({select}) TO STDOUT", buffer)
    buffer.seek(0)
    with target_raw.cursor() as cursor:
        cursor.copy_expert(f"COPY {_ident(table.name)} ({column_list}) FROM STDIN", buffer)


def _reset_sequences(conn: Connection, tables: list[Table]) -> int:
    """Move any serial sequence past the rows just copied, so new inserts do not collide."""
    moved = 0
    for table in tables:
        for (column,) in conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name = :table AND column_default LIKE 'nextval(%'"
            ),
            {"table": table.name},
        ).fetchall():
            conn.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence(:qualified, :column), "
                    f"GREATEST((SELECT COALESCE(MAX({_ident(column)}), 0) FROM {_ident(table.name)}), 1))"
                ),
                {"qualified": f"public.{table.name}", "column": column},
            )
            moved += 1
    return moved


def copy(
    source: Engine,
    target: Engine,
    org_name: str,
    *,
    skip_tables: frozenset[str] = frozenset(),
    disable_users: frozenset[str] = frozenset(),
    replace: bool = False,
) -> dict[str, Any]:
    """Copy the organisation and verify it. Raises ``TenantCopyError`` and commits nothing on
    any mismatch."""
    expected = plan(source, org_name, skip_tables)
    org_id = expected["org_id"]
    with source.connect() as source_conn, target.connect() as target_conn:
        if _revision(target_conn) != expected["revision"]:
            raise TenantCopyError(
                f"target is at migration {_revision(target_conn)!r}, source at {expected['revision']!r}: "
                "migrate the target to the same revision first"
            )
        tables = [table for table in tenant_tables(source_conn) if table.name not in skip_tables]
        target_tables = {table.name for table in tenant_tables(target_conn)}
        missing = [table.name for table in tables if table.name not in target_tables]
        if missing:
            raise TenantCopyError(f"target is missing tenant tables: {', '.join(missing)}")

        # SQLAlchemy opened the transaction with the first read above; everything from here to
        # the commit below is that one transaction on the target.
        try:
            exists = target_conn.execute(
                text("SELECT count(*) FROM organisations WHERE id = :org OR name = :name"),
                {"org": org_id, "name": org_name},
            ).scalar_one()
            # Constraint checks are deferred for the copy: a few tables reference each other
            # or themselves, and --disable-user keeps every referenced user row in place.
            target_conn.execute(text("SET LOCAL session_replication_role = replica"))
            if exists and not replace:
                raise TenantCopyError(
                    f"target already holds {org_name!r}; pass --replace to delete that organisation's rows "
                    "in the target and copy again"
                )
            deleted = 0
            if exists:
                for table in reversed([*tenant_tables(target_conn)]):
                    deleted += target_conn.execute(
                        text(f"DELETE FROM {_ident(table.name)} WHERE {_ident(table.filter_column)} = :org"),
                        {"org": org_id},
                    ).rowcount
            source_raw = source_conn.connection.driver_connection
            target_raw = target_conn.connection.driver_connection
            for table in tables:
                _copy_table(source_raw, target_raw, table, _columns(source_conn, table.name), org_id)

            disabled = 0
            for email in sorted(disable_users):
                # Kept, because other rows refer to the account, but it can never sign in.
                disabled += target_conn.execute(
                    text(
                        "UPDATE users SET is_active = false, password_hash = :unusable, totp_secret = NULL, "
                        "two_factor_enabled = false, invite_token_hash = NULL "
                        "WHERE org_id = :org AND lower(email) = lower(:email)"
                    ),
                    {"org": org_id, "email": email, "unusable": "!disabled-" + secrets.token_hex(24)},
                ).rowcount
            if disabled != len(disable_users):
                raise TenantCopyError(
                    f"--disable-user named {len(disable_users)} account(s) but {disabled} exist in {org_name!r}"
                )
            sequences = _reset_sequences(target_conn, tables)

            actual = {table.name: _count(target_conn, table, org_id) for table in tables}
            mismatched = {
                name: {"source": expected["tables"][name], "target": actual[name]}
                for name in actual
                if actual[name] != expected["tables"][name]
            }
            others = target_conn.execute(
                text("SELECT count(*) FROM organisations WHERE id <> :org"), {"org": org_id}
            ).scalar_one()
            if mismatched:
                raise TenantCopyError(f"row counts differ after copy: {json.dumps(mismatched, sort_keys=True)}")
            target_conn.commit()
        except BaseException:
            target_conn.rollback()
            raise
    return {
        **expected,
        "copied_rows": sum(actual.values()),
        "replaced_rows_deleted": deleted,
        "users_disabled": disabled,
        "sequences_reset": sequences,
        "other_organisations_in_target": others,
        "verified": True,
    }


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("plan", "copy"))
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--target-url")
    parser.add_argument("--org-name", required=True)
    parser.add_argument("--skip-table", action="append", default=[], help="A tenant table to leave behind.")
    parser.add_argument("--disable-user", action="append", default=[], help="Copy this account but lock it.")
    parser.add_argument("--replace", action="store_true", help="Delete the organisation in the target first.")
    args = parser.parse_args(argv)
    if args.command == "copy" and not args.target_url:
        parser.error("copy needs --target-url")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    source = create_engine(args.source_url)
    target = create_engine(args.target_url) if args.target_url else None
    try:
        if args.command == "plan":
            result = plan(source, args.org_name, frozenset(args.skip_table))
        else:
            result = copy(
                source,
                target,
                args.org_name,
                skip_tables=frozenset(args.skip_table),
                disable_users=frozenset(args.disable_user),
                replace=args.replace,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except TenantCopyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        source.dispose()
        if target is not None:
            target.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
