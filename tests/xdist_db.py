"""One test database per pytest-xdist worker.

Tests commit real rows and isolate by org, so parallel workers must not share a database.
`app.utils.config_loader` appends the worker ID (gw0, gw1, ...) to the database name inside a
worker. Before each worker starts, the controller clones its database from a private
template, `<db>_xdist_template`. Postgres refuses to clone a database anyone is connected to,
and locally the deployed test container stays connected to the shared test database, so the
template is never connected to by anything else. It is rebuilt with `alembic upgrade head`
only when its migration revision falls behind the shared database's.
"""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import psycopg2
import psycopg2.errors

from app.utils.config_loader import config

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_SUFFIX = "xdist_template"


def _admin():
    conn = psycopg2.connect(
        host=config.db_host, port=config.db_port, user=config.db_user, password=config.db_password, dbname="postgres"
    )
    conn.autocommit = True
    return conn


def _revision(cur, db: str) -> str | None:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,))
    if not cur.fetchone():
        return None
    try:
        conn = psycopg2.connect(
            host=config.db_host, port=config.db_port, user=config.db_user, password=config.db_password, dbname=db
        )
    except psycopg2.OperationalError:
        return None
    try:
        with conn.cursor() as c:
            c.execute("SELECT string_agg(version_num, ',' ORDER BY version_num) FROM alembic_version")
            return c.fetchone()[0]
    except psycopg2.Error:
        return None
    finally:
        conn.close()


def ensure_template() -> str:
    """The migrated template every worker database is cloned from, rebuilt only when stale."""
    base = config.db_name
    template = f"{base}_{TEMPLATE_SUFFIX}"
    with closing(_admin()) as conn, conn.cursor() as cur:
        wanted = _revision(cur, base)
        if wanted and _revision(cur, template) == wanted:
            return template
        cur.execute(f'DROP DATABASE IF EXISTS "{template}" WITH (FORCE)')
        try:
            # Fast path (CI): nothing else is connected to the freshly migrated database.
            cur.execute(f'CREATE DATABASE "{template}" TEMPLATE "{base}"')
            return template
        except psycopg2.errors.ObjectInUse:
            cur.execute(f'CREATE DATABASE "{template}"')
    # Locally something (the deployed test container) holds the shared database open, so
    # migrate an empty one; config_loader names it after PYTEST_XDIST_WORKER.
    env = {**os.environ, "PYTEST_XDIST_WORKER": TEMPLATE_SUFFIX}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True, capture_output=True
    )
    return template


def clone_for(worker: str, template: str) -> None:
    db = f"{config.db_name}_{worker}"
    with closing(_admin()) as conn, conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
        cur.execute(f'CREATE DATABASE "{db}" TEMPLATE "{template}"')
