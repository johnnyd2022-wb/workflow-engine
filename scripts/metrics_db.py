#!/usr/bin/env python3
"""Biz-E development metrics database: connection, storage helpers and admin CLI.

Skill-run ledger and perf results used to live in repo files (.agents/metrics/*.jsonl,
.agents/reports/perf/last-run.json) that every MR rewrote, so they conflicted constantly.
They now live in the `bize_dev` database on the Terraform state-db container
(terraform/compose.yml), schema `metrics`, created from metrics_db/schema.sql.

Connection, in order:
  1. $BIZE_METRICS_HOST / _PORT / _DB / _USER / _PASSWORD  (CI: project CI/CD variables;
     job containers reach the host-published port as host.docker.internal:8402)
  2. KeePassXC entry workflow-engine/bize-dev-db-rw on 127.0.0.1:8402, only when
     $KEEPASS_PASSWORD is set -- an unattended skill must never block on a password prompt.
No credentials, or an unreachable DB, is "unavailable", never a crash: writes go to a local
spool file that the next successful call flushes; reads report the gap. The DB being down
must not be able to block a merge or lose a skill's run.

Admin (local only, drives the container via `docker exec`; needs $KEEPASS_PASSWORD):
    python3 scripts/metrics_db.py setup            # create db + roles + schema + grants
    python3 scripts/metrics_db.py migrate          # re-apply schema.sql + grants.sql
    python3 scripts/metrics_db.py status           # connectivity + row counts
    python3 scripts/metrics_db.py check            # CI: exit 0 if reachable-and-sane, or skipped
    python3 scripts/metrics_db.py import-legacy    # load the old JSONL / last-run.json files
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = REPO_ROOT / "metrics_db" / "schema.sql"
GRANTS_SQL = REPO_ROOT / "metrics_db" / "grants.sql"

CONTAINER = "workflow-engine-terraform-state-db-1"
DATABASE = "bize_dev"
SCHEMA = "metrics"
ADMIN_ROLE = "bize_dev_admin"
RW_ROLE = "bize_dev_rw"
ADMIN_ENTRY = "workflow-engine/bize-dev-db-admin"
RW_ENTRY = "workflow-engine/bize-dev-db-rw"
LOCAL_HOST, LOCAL_PORT = "127.0.0.1", "8402"
CONNECT_TIMEOUT_S = 3


class MetricsDBUnavailableError(RuntimeError):
    """No credentials, driver or server -- callers degrade (spool / skip), never crash."""


# --------------------------------------------------------------------------------------
# Credentials and connection
# --------------------------------------------------------------------------------------


def _keepass_password(entry: str) -> str | None:
    """The entry's Password field, but only without prompting: needs $KEEPASS_PASSWORD."""
    if not os.environ.get("KEEPASS_PASSWORD") or not shutil.which("keepassxc-cli"):
        return None
    sys.path.insert(0, str(REPO_ROOT / "terraform"))
    try:
        from tf import Secrets  # noqa: PLC0415

        return Secrets().read(entry, "Password")
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return None
    finally:
        sys.path.pop(0)


def connection_params() -> dict[str, str]:
    env = os.environ
    if env.get("BIZE_METRICS_PASSWORD"):
        return {
            "host": env.get("BIZE_METRICS_HOST", LOCAL_HOST),
            "port": env.get("BIZE_METRICS_PORT", LOCAL_PORT),
            "dbname": env.get("BIZE_METRICS_DB", DATABASE),
            "user": env.get("BIZE_METRICS_USER", RW_ROLE),
            "password": env["BIZE_METRICS_PASSWORD"],
        }
    password = _keepass_password(RW_ENTRY)
    if password is None:
        raise MetricsDBUnavailableError("no BIZE_METRICS_PASSWORD and KeePassXC is not unlocked ($KEEPASS_PASSWORD)")
    return {"host": LOCAL_HOST, "port": LOCAL_PORT, "dbname": DATABASE, "user": RW_ROLE, "password": password}


def connect():
    """A psycopg2 connection with search_path set, or MetricsDBUnavailableError."""
    try:
        import psycopg2  # noqa: PLC0415
    except ImportError as e:
        raise MetricsDBUnavailableError("psycopg2 is not installed (uv sync --extra dev)") from e
    params = connection_params()
    schema = os.environ.get("BIZE_METRICS_SCHEMA", SCHEMA)
    try:
        return psycopg2.connect(
            connect_timeout=CONNECT_TIMEOUT_S,
            options=f"-c search_path={schema} -c statement_timeout=15000",
            **params,
        )
    except psycopg2.OperationalError as e:
        # Deliberately not echoing e: libpq errors can carry the host/user, never the password,
        # but there is nothing useful to add beyond "unreachable".
        raise MetricsDBUnavailableError(f"cannot reach {params['host']}:{params['port']}/{params['dbname']}") from e


@contextlib.contextmanager
def session() -> Iterator[Any]:
    conn = connect()
    try:
        with conn:  # commit on success, roll back on error
            yield conn
    finally:
        conn.close()


# --------------------------------------------------------------------------------------
# Spool: where writes wait while the DB is unreachable
# --------------------------------------------------------------------------------------


def spool_path() -> Path:
    override = os.environ.get("BIZE_METRICS_SPOOL")
    return Path(override) if override else Path.home() / ".local" / "state" / "bize-metrics" / "spool.jsonl"


def spool_append(kind: str, record: dict[str, Any]) -> None:
    path = spool_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": kind, "record": record}, sort_keys=True) + "\n")


def spool_read() -> list[dict[str, Any]]:
    path = spool_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            with contextlib.suppress(json.JSONDecodeError):
                out.append(json.loads(line))
    return out


def spool_flush(conn) -> int:
    """Insert spooled records (idempotent via the identity indexes), then drop them.

    Several agents append to the spool. Claim it first by renaming it to a private name, so a
    line appended between the read and the unlink lands in a fresh spool instead of being
    deleted unflushed. A failed insert puts the claimed lines back for the next flush."""
    path = spool_path()
    claimed = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.flushing")
    try:
        os.replace(path, claimed)
    except FileNotFoundError:
        return 0
    entries = []
    for line in claimed.read_text(encoding="utf-8").splitlines():
        if line.strip():
            with contextlib.suppress(json.JSONDecodeError):
                entries.append(json.loads(line))
    try:
        for entry in entries:
            _insert(conn, entry["kind"], entry["record"])
    except Exception:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(claimed.read_text(encoding="utf-8"))
        claimed.unlink(missing_ok=True)
        raise
    claimed.unlink(missing_ok=True)
    return len(entries)


# --------------------------------------------------------------------------------------
# Provenance: tie every row to the commit / MR / pipeline that produced it
# --------------------------------------------------------------------------------------


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, cwd=REPO_ROOT, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def _int_env(name: str) -> int | None:
    value = os.environ.get(name, "")
    return int(value) if value.isdecimal() else None


def provenance() -> dict[str, Any]:
    env = os.environ
    branch = env.get("CI_COMMIT_REF_NAME") or _git("rev-parse", "--abbrev-ref", "HEAD")
    is_ci = env.get("GITLAB_CI") == "true"
    default_branch = env.get("CI_DEFAULT_BRANCH", "main")
    return {
        "commit_sha": env.get("CI_COMMIT_SHA") or _git("rev-parse", "HEAD"),
        "branch": branch,
        "is_main": bool(is_ci and branch == default_branch and not env.get("CI_MERGE_REQUEST_IID")),
        "mr_iid": _int_env("CI_MERGE_REQUEST_IID"),
        "pipeline_id": _int_env("CI_PIPELINE_ID"),
        "job_id": _int_env("CI_JOB_ID"),
        "source": "ci" if is_ci else "local",
    }


# --------------------------------------------------------------------------------------
# Skill ledger
# --------------------------------------------------------------------------------------

_RUN_COLS = ("ts", "skill", "run_type", "scope", "findings", "verdict", "ref", "duration_s", "notes")
_RUN_PROV = ("commit_sha", "mr_iid", "pipeline_id")
_OUTCOME_COLS = ("ts", "ref", "outcome", "skill", "notes")


_INSERT_SQL = {
    "run": (
        "INSERT INTO skill_runs (ts, skill, run_type, scope, findings, verdict, ref, duration_s, notes, "
        "commit_sha, mr_iid, pipeline_id) VALUES (COALESCE(%s, now()), %s, %s, %s, COALESCE(%s, 0), %s, %s, "
        "%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING"
    ),
    "outcome": (
        "INSERT INTO skill_outcomes (ts, ref, outcome, skill, notes) "
        "VALUES (COALESCE(%s, now()), %s, %s, %s, %s) ON CONFLICT DO NOTHING"
    ),
}
_SELECT_SQL = {
    "run": "SELECT ts, skill, run_type, scope, findings, verdict, ref, duration_s, notes FROM skill_runs ORDER BY ts, id",
    "outcome": "SELECT ts, ref, outcome, skill, notes FROM skill_outcomes ORDER BY ts, id",
}


def _insert(conn, kind: str, record: dict[str, Any]) -> None:
    cols = _RUN_COLS + _RUN_PROV if kind == "run" else _OUTCOME_COLS
    with conn.cursor() as cur:
        cur.execute(_INSERT_SQL[kind], [record.get(c) for c in cols])


def store(kind: str, record: dict[str, Any]) -> str:
    """Insert one skill run/outcome. Returns 'db' or 'spooled'. Never raises on outage."""
    if kind == "run":
        prov = provenance()
        record = {**{k: prov[k] for k in _RUN_PROV}, **record}
    try:
        with session() as conn:
            spool_flush(conn)
            _insert(conn, kind, record)
        return "db"
    except MetricsDBUnavailableError:
        spool_append(kind, record)
        return "spooled"


def _iso(value: Any) -> Any:
    return value.astimezone(UTC).isoformat(timespec="seconds") if isinstance(value, datetime) else value


def fetch(kind: str) -> list[dict[str, Any]]:
    """All runs or outcomes in append order, plus anything still spooled locally. Raises
    MetricsDBUnavailableError when the DB is down -- the caller decides how to degrade."""
    cols = _RUN_COLS if kind == "run" else _OUTCOME_COLS
    with session() as conn:
        spool_flush(conn)
        with conn.cursor() as cur:
            cur.execute(_SELECT_SQL[kind])
            return [{c: _iso(v) for c, v in zip(cols, row, strict=True)} for row in cur.fetchall()]


# --------------------------------------------------------------------------------------
# Perf results
# --------------------------------------------------------------------------------------


def record_perf(results: list[dict[str, Any]]) -> str:
    """Store one perf run (the list perf tests build: route/kind/metrics/over_*)."""
    prov = provenance()
    rows = []
    for r in results:
        for metric, value in r["metrics"].items():
            if value is None:
                continue
            flagged = lambda lst, m=metric: any(item.startswith(f"{m}=") for item in lst)  # noqa: E731
            rows.append(
                (r["route"], r["kind"], metric, float(value), flagged(r["over_budget"]), flagged(r["over_ceiling"]))
            )
    try:
        with session() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO perf_runs (commit_sha, branch, is_main, mr_iid, pipeline_id, job_id, source) "
                "VALUES (%(commit_sha)s, %(branch)s, %(is_main)s, %(mr_iid)s, %(pipeline_id)s, %(job_id)s, %(source)s) "
                "RETURNING id",
                prov,
            )
            run_id = cur.fetchone()[0]
            cur.executemany(
                "INSERT INTO perf_results (run_id, route, kind, metric, value, over_budget, over_ceiling) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [(run_id, *row) for row in rows],
            )
        return "db"
    except MetricsDBUnavailableError:
        return "unavailable"


def latest_perf_run(branch: str | None = None) -> dict[str, Any] | None:
    """The most recent perf run in the shape perf_triage used to read from last-run.json."""
    with session() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, measured_at, commit_sha, branch FROM perf_runs "
            "WHERE (%s::text IS NULL OR branch = %s) ORDER BY measured_at DESC, id DESC LIMIT 1",
            (branch, branch),
        )
        head = cur.fetchone()
        if head is None:
            return None
        cur.execute(
            "SELECT route, kind, metric, value, over_budget, over_ceiling FROM perf_results "
            "WHERE run_id = %s ORDER BY route, metric",
            (head[0],),
        )
        by_route: dict[str, dict[str, Any]] = {}
        for route, kind, metric, value, over_budget, over_ceiling in cur.fetchall():
            entry = by_route.setdefault(
                route, {"route": route, "kind": kind, "metrics": {}, "over_budget": [], "over_ceiling": []}
            )
            entry["metrics"][metric] = round(value, 1)
            if over_budget:
                entry["over_budget"].append(metric)
            if over_ceiling:
                entry["over_ceiling"].append(metric)
    return {
        "generated": _iso(head[1]),
        "commit_sha": head[2],
        "branch": head[3],
        "results": sorted(by_route.values(), key=lambda r: r["route"]),
    }


def perf_baseline() -> dict[tuple[str, str], tuple[float, int]]:
    """{(route, metric): (median, samples)} over the last 20 main-branch runs."""
    with session() as conn, conn.cursor() as cur:
        cur.execute("SELECT route, metric, median, samples FROM perf_baseline")
        return {(route, metric): (float(median), int(n)) for route, metric, median, n in cur.fetchall()}


# --------------------------------------------------------------------------------------
# Admin CLI (local only)
# --------------------------------------------------------------------------------------


def _psql(sql: str, *, user: str, database: str) -> None:
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", user, "-d", database],
        input=sql,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        # stderr can echo statements containing passwords; show only the SQL error lines.
        errors = [line for line in result.stderr.splitlines() if "ERROR" in line and "PASSWORD" not in line.upper()]
        raise RuntimeError("psql failed: " + ("; ".join(errors) or f"exit {result.returncode}"))


def _vault():
    sys.path.insert(0, str(REPO_ROOT / "terraform"))
    from tf import Secrets  # noqa: PLC0415

    return Secrets()


def _stored_or_create(vault, entry: str, username: str) -> str:
    try:
        return vault.read(entry, "Password")
    except RuntimeError:
        password = secrets.token_hex(24)
        subprocess.run(
            [
                "keepassxc-cli",
                "add",
                "-q",
                "-p",
                "-u",
                username,
                "--url",
                f"postgres://{username}@{LOCAL_HOST}:{LOCAL_PORT}/{DATABASE}",
                vault.database,
                entry,
            ],
            input=vault.password + "\n" + password + "\n",
            text=True,
            capture_output=True,
            check=True,
        )
        return password


def cmd_setup() -> int:
    vault = _vault()
    admin_pw = _stored_or_create(vault, ADMIN_ENTRY, ADMIN_ROLE)
    rw_pw = _stored_or_create(vault, RW_ENTRY, RW_ROLE)
    roles = ""
    for role, password, extra in (
        (ADMIN_ROLE, admin_pw, "NOSUPERUSER CREATEDB NOCREATEROLE"),
        (RW_ROLE, rw_pw, "NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 20"),
    ):
        escaped = password.replace("'", "''")
        roles += (
            f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') "
            f"THEN CREATE ROLE {role} LOGIN; END IF; END $$;\n"
            f"ALTER ROLE {role} PASSWORD '{escaped}' {extra} NOREPLICATION NOBYPASSRLS;\n"
        )
    _psql(roles, user="terraform", database="terraform_state")
    exists = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "terraform", "-d", "terraform_state", "-Atc",
         f"SELECT 1 FROM pg_database WHERE datname = '{DATABASE}'"],
        capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip
    if not exists:
        _psql(f"CREATE DATABASE {DATABASE} OWNER {ADMIN_ROLE};\n", user="terraform", database="terraform_state")
    _psql(
        f"REVOKE ALL ON DATABASE {DATABASE} FROM PUBLIC;\n"
        f"GRANT CONNECT ON DATABASE {DATABASE} TO {RW_ROLE};\n"
        f"ALTER ROLE {RW_ROLE} IN DATABASE {DATABASE} SET search_path = {SCHEMA};\n"
        f"ALTER ROLE {RW_ROLE} IN DATABASE {DATABASE} SET statement_timeout = '15s';\n",
        user="terraform",
        database="terraform_state",
    )
    cmd_migrate()
    print(f"database {DATABASE}: roles {ADMIN_ROLE} (DDL) and {RW_ROLE} (INSERT/SELECT); credentials in KeePassXC")
    return 0


def cmd_migrate() -> int:
    _psql(SCHEMA_SQL.read_text(encoding="utf-8"), user=ADMIN_ROLE, database=DATABASE)
    _psql(GRANTS_SQL.read_text(encoding="utf-8"), user=ADMIN_ROLE, database=DATABASE)
    print(f"applied {SCHEMA_SQL.name} + {GRANTS_SQL.name} to {DATABASE}.{SCHEMA}")
    return 0


def cmd_status() -> int:
    try:
        with session() as conn, conn.cursor() as cur:
            print(f"connected: {conn.get_dsn_parameters()['host']}:{conn.get_dsn_parameters()['port']}/{DATABASE}")
            cur.execute(
                "SELECT 'skill_runs', count(*) FROM skill_runs UNION ALL "
                "SELECT 'skill_outcomes', count(*) FROM skill_outcomes UNION ALL "
                "SELECT 'perf_runs', count(*) FROM perf_runs UNION ALL "
                "SELECT 'perf_results', count(*) FROM perf_results"
            )
            for table, n in cur.fetchall():
                print(f"  {table}: {n}")
    except MetricsDBUnavailableError as e:
        print(f"unavailable: {e}", file=sys.stderr)
        return 1
    print(f"spooled locally: {len(spool_read())}")
    return 0


def cmd_check() -> int:
    """CI gate. Reachable-and-broken fails; unreachable/unconfigured is a visible skip."""
    try:
        with session() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = %s AND table_name = ANY(%s)",
                (
                    os.environ.get("BIZE_METRICS_SCHEMA", SCHEMA),
                    ["skill_runs", "skill_outcomes", "perf_runs", "perf_results"],
                ),
            )
            found = cur.fetchone()[0]
    except MetricsDBUnavailableError as e:
        print(f"SKIPPED: metrics DB not checked ({e}); this never blocks a merge")
        return 0
    if found != 4:
        print(
            f"metrics DB reachable but schema incomplete ({found}/4 tables) -- run metrics_db.py migrate",
            file=sys.stderr,
        )
        return 1
    print("metrics DB reachable, schema complete")
    return 0


def cmd_import_legacy(paths: list[str]) -> int:
    """Load the pre-DB files. Idempotent: re-running changes nothing."""
    base = Path(paths[0]) if paths else REPO_ROOT
    runs = _read_jsonl(base / ".agents/metrics/runs.jsonl")
    outcomes = _read_jsonl(base / ".agents/metrics/outcomes.jsonl")
    last_run = base / ".agents/reports/perf/last-run.json"
    with session() as conn:
        for rec in runs:
            _insert(conn, "run", rec)
        for rec in outcomes:
            _insert(conn, "outcome", rec)
        perf = json.loads(last_run.read_text(encoding="utf-8")) if last_run.exists() else None
        if perf:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM perf_runs WHERE source = 'local' AND measured_at = %s", (perf["generated"],))
                if cur.fetchone() is None:
                    cur.execute(
                        "INSERT INTO perf_runs (measured_at, commit_sha, branch, is_main, source) "
                        "VALUES (%s, 'legacy-import', 'main', false, 'local') RETURNING id",
                        (perf["generated"],),
                    )
                    run_id = cur.fetchone()[0]
                    rows = [
                        (
                            run_id,
                            r["route"],
                            r["kind"],
                            metric,
                            value,
                            any(i.startswith(f"{metric}=") for i in r["over_budget"]),
                            any(i.startswith(f"{metric}=") for i in r["over_ceiling"]),
                        )
                        for r in perf["results"]
                        for metric, value in r["metrics"].items()
                        if value is not None
                    ]
                    cur.executemany("INSERT INTO perf_results VALUES (%s, %s, %s, %s, %s, %s, %s)", rows)
    print(f"imported {len(runs)} runs, {len(outcomes)} outcomes, {1 if perf else 0} perf run")
    return 0


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("setup", "migrate", "status", "check"):
        sub.add_parser(name)
    imp = sub.add_parser("import-legacy")
    imp.add_argument("base", nargs="?", help="repo root holding the legacy files (default: this repo)")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "import-legacy":
            return cmd_import_legacy([args.base] if args.base else [])
        return {"setup": cmd_setup, "migrate": cmd_migrate, "status": cmd_status, "check": cmd_check}[args.cmd]()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
        print(f"metrics_db: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
