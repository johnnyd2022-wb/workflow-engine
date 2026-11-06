#!/usr/bin/env python3
"""Why do pipelines go red? Pull GitLab pipeline history into bize_dev (schema `ci`) and classify.

    python3 scripts/ci_health.py refresh [--mrs 100] [--main 200]   # fetch + classify + store
    python3 scripts/ci_health.py report                              # cause table (from the DB)
    python3 scripts/ci_health.py classify --trace FILE --job NAME    # debug one trace

Data: GitLab API through `glab api` (or $GITLAB_TOKEN / $CI_JOB_TOKEN-less personal token in
$GITLAB_API_TOKEN). Storage: bize_dev, schema `ci` (ci.pipelines, ci.failed_jobs). Locally the
SQL is piped to the bize_dev container as the admin role; when $BIZE_METRICS_PASSWORD is set
(CI) it connects with psycopg2 like scripts/tia.py. `refresh` is idempotent (upserts), so it
can be rerun at any time; reclassification is just `refresh --offline` (re-reads stored
trace tails).

The classifier is a list of ordered regex rules over the job name and the last ~12 kB of its
trace. The first rule that matches wins; anything unmatched is `unclassified` so it shows up
in the report instead of being silently counted as a real bug.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

PROJECT = "76311154"
CONTAINER = "workflow-engine-terraform-state-db-1"
ADMIN_ROLE = "bize_dev_admin"
DATABASE = "bize_dev"
TRACE_TAIL = 12_000
FAILED_LINES_MAX = 8_000

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS ci;
CREATE TABLE IF NOT EXISTS ci.pipelines (
    id bigint PRIMARY KEY,
    ref text NOT NULL,
    mr_iid int,
    kind text NOT NULL,              -- main | mr
    source text,
    status text NOT NULL,
    sha text,
    created_at timestamptz,
    finished_at timestamptz,
    duration_s int,
    fetched_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ci.failed_jobs (
    job_id bigint PRIMARY KEY,
    pipeline_id bigint NOT NULL REFERENCES ci.pipelines(id) ON DELETE CASCADE,
    name text NOT NULL,
    stage text,
    allow_failure boolean,
    retried boolean,
    started_at timestamptz,
    finished_at timestamptz,
    duration_s int,
    failure_reason text,
    cause text NOT NULL,
    detail text,
    trace_tail text,
    failed_lines text,               -- FAILED/ERROR lines + pytest summary, from the WHOLE trace
    classified_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE ci.failed_jobs ADD COLUMN IF NOT EXISTS failed_lines text;
CREATE INDEX IF NOT EXISTS failed_jobs_cause_idx ON ci.failed_jobs(cause);
-- A pipeline is "blocked" from its creation until the next green pipeline on the same ref.
CREATE OR REPLACE VIEW ci.pipeline_blocked AS
SELECT p.*,
       (SELECT min(n.created_at) FROM ci.pipelines n
         WHERE n.kind = p.kind AND n.status = 'success' AND n.created_at > p.created_at
           AND (CASE WHEN p.kind = 'mr' THEN n.mr_iid = p.mr_iid ELSE n.ref = p.ref END)) AS next_green_at
  FROM ci.pipelines p;
DROP VIEW IF EXISTS ci.cause_summary;
CREATE VIEW ci.cause_summary AS
WITH pc AS (  -- one row per (pipeline, cause): a pipeline with two causes counts in both
  SELECT DISTINCT f.pipeline_id, f.cause FROM ci.failed_jobs f WHERE NOT coalesce(f.allow_failure, false)
), jc AS (
  SELECT cause, count(*) AS jobs FROM ci.failed_jobs WHERE NOT coalesce(allow_failure, false) GROUP BY cause
)
SELECT pc.cause, jc.jobs,
       count(*) AS pipelines,
       count(*) FILTER (WHERE b.kind = 'main') AS main_pipelines,
       count(DISTINCT b.mr_iid) AS mrs,
       round(sum(extract(epoch FROM least(coalesce(b.next_green_at, now()), b.created_at + interval '24 hours')
                 - b.created_at) / 3600.0)::numeric, 1) AS blocked_hours,
       min(b.created_at)::date AS first_seen, max(b.created_at)::date AS last_seen
  FROM pc JOIN ci.pipeline_blocked b ON b.id = pc.pipeline_id JOIN jc ON jc.cause = pc.cause
 GROUP BY pc.cause, jc.jobs ORDER BY blocked_hours DESC NULLS LAST;
GRANT USAGE ON SCHEMA ci TO bize_dev_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ci TO bize_dev_rw;
"""

# (cause, job-name regex or None, trace regex) — first match wins. Order: most specific first.
RULES: list[tuple[str, str | None, str]] = [
    # main_green reports main's state; split "main busy" from "main really red".
    ("main_red_inherited", r"^main_green$", r"pipeline (failed|canceled)\b"),
    ("stale_main_gate", r"^main_green$", r"."),
    ("tooling_drift_ci_image", r"^ci_image_current$", r"."),
    ("ci_image_missing", None, r"manifest for registry\.gitlab\.com/\S+/ci:\S+ not found"),
    (
        "runner_infra",
        None,
        r"(?i)(no space left on device|runner system failure|Cannot connect to the Docker daemon"
        r"|failed to pull image|toomanyrequests|ERROR: Preparation failed|Job failed \(system failure\))",
    ),
    ("new_advisory", r"^(uv_audit|pip_audit)$", r"."),
    ("deploy_bootstrap", None, r"app:test-stable not found"),
    ("deploy_env", None, r"network \S+ not found|is already in use by container"),
    ("shared_db_migration_drift", None, r"Can't locate revision identified by"),
    ("terraform_review_gate", r"^terraform_", r"."),
    ("third_party_fonts", None, r"fonts\.(googleapis|gstatic)\.com"),
    ("deploy_not_ready", None, r"ERR_CONNECTION_REFUSED at https://localhost:8001"),
    ("ci_env_db", None, r"port 8401 failed: Connection refused"),
    ("ci_bootstrap", None, r"(pip|uv|python3?): command not found"),
    (
        "timeout",
        None,
        r"(?i)(execution took longer than|Timeout of \d+ seconds|\+{5,} Timeout \+{5,}"
        r"|subprocess\.TimeoutExpired|timed out after \d+)",
    ),
    (
        "network_flake",
        None,
        r"(?i)(net::ERR_[A-Z_]+|Temporary failure in name resolution|Connection reset by peer|ECONNRESET"
        r"|Could not resolve host|TLS handshake timeout|502 Bad Gateway|503 Service Unavailable|i/o timeout)",
    ),
    ("security_gate", r"^(socket_security|gitleaks|semgrep.*|sast)$", r"."),
    ("lockfile", r"^(lockfile_consistency|renovate)$", r"."),
    ("lint_format", r"^(ruff|backend_size|feature_index_routes|data_stores)$", r"."),
    ("migration", r"^migration_reversibility$", r"."),
    ("deploy", r"^(deploy_|promote_|rollback_|docker_build|ci_image_build)", r"."),
    (
        "shared_db_pollution",
        None,
        r"(?i)(UniqueViolation|duplicate key value violates unique constraint|deadlock detected)",
    ),
    ("time_tz", None, r"(?i)(zoneinfo|Pacific/Auckland|freeze_time|excise month)"),
    ("e2e_assertion", None, r"(?m)^(FAILED|ERROR) tests/e2e/"),
    ("test_failure", None, r"(?m)^(FAILED|ERROR) tests/|=+ .*\d+ failed"),
    ("script_error", None, r"(?i)(Traceback \(most recent call last\)|command not found|exit code \d+)"),
]

# After per-job rules: an MR test failure whose test also failed on main within this window was
# inherited from a red main (or a semantic conflict that landed there), not caused by the MR.
INHERIT_WINDOW = "3 days"
POSTPASS = f"""
UPDATE ci.failed_jobs f SET cause = 'main_red_inherited'
  FROM ci.pipelines p
 WHERE p.id = f.pipeline_id AND p.kind = 'mr' AND f.cause IN ('test_failure', 'e2e_assertion')
   AND EXISTS (
     SELECT 1 FROM ci.failed_jobs mf JOIN ci.pipelines mp ON mp.id = mf.pipeline_id
      WHERE mp.kind = 'main' AND mf.detail LIKE 'tests/%'
        AND mp.created_at BETWEEN p.created_at - interval '{INHERIT_WINDOW}' AND p.created_at + interval '{INHERIT_WINDOW}'
        AND EXISTS (SELECT 1 FROM unnest(string_to_array(f.detail, ' | ')) t
                     WHERE t LIKE 'tests/%' AND mf.detail LIKE '%' || split_part(t, '[', 1) || '%'));
"""


_STAMP = re.compile(r"(?m)^\d{4}-\d\d-\d\dT[\d:.]+Z \d+[OE]\+? ?")


def classify(job_name: str, trace: str, failure_reason: str | None = None) -> tuple[str, str]:
    trace = _STAMP.sub("", trace or "")  # runner 18 prefixes each line with "<time> 01O "
    if failure_reason in ("stuck_or_timeout_failure", "job_execution_timeout"):
        return "timeout", failure_reason
    if failure_reason in ("runner_system_failure", "scheduler_failure", "api_failure", "unknown_failure") and not trace:
        return "runner_infra", failure_reason
    for cause, name_rx, trace_rx in RULES:
        if name_rx and not re.search(name_rx, job_name):
            continue
        m = re.search(trace_rx, trace or "")
        if m:
            return cause, _detail(trace, m if trace_rx != "." else None)
    return "unclassified", _detail(trace, None)


def _detail(trace: str, m: re.Match | None) -> str:
    """The most telling line: the first FAILED test line, else the matching line, else the last line."""
    failed = re.findall(r"(?m)^(?:FAILED|ERROR) (tests/\S+)", trace or "")
    if failed:
        return " | ".join(sorted(set(failed))[:5])[:500]
    if m:
        start = trace.rfind("\n", 0, m.start()) + 1
        end = trace.find("\n", m.end())
        return trace[start : end if end != -1 else None].strip()[:500]
    noise = re.compile(r"^(\$ |Running after|Cleaning up|ERROR: Job failed|Uploading|section_|\S+ \d+O\s*$)")
    lines = [ln.strip() for ln in (trace or "").splitlines() if ln.strip() and not noise.match(ln.strip())]
    return (lines[-1] if lines else "")[:500]


# --------------------------------------------------------------------------------------
# GitLab
# --------------------------------------------------------------------------------------

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|section_(start|end):\d+:\S+\r?")


def gl(path: str, raw: bool = False):
    err = ""
    for attempt in range(6):
        try:
            out = subprocess.run(["glab", "api", path], capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            err = "timeout"
            time.sleep(5 * 2**attempt)
            continue
        err = out.stderr
        if out.returncode == 0:
            return out.stdout if raw else json.loads(out.stdout or "null")
        if "HTTP 429" not in out.stderr and "HTTP 5" not in out.stderr:
            break
        time.sleep(5 * 2**attempt)  # GitLab.com rate limit: back off and retry
    raise RuntimeError(f"glab api {path}: {err.strip()[-200:]}")


def gl_pages(path: str, limit: int) -> list:
    items, page = [], 1
    while len(items) < limit:
        sep = "&" if "?" in path else "?"
        batch = gl(f"{path}{sep}per_page=100&page={page}")
        if not batch:
            break
        items.extend(batch)
        page += 1
    return items[:limit]


_KEY_LINE = re.compile(r"^(FAILED|ERROR) tests/|^=+ .*\b(failed|error|errors|passed)\b.* in [\d.]+s")


def failed_lines(text: str) -> str:
    """The lines that say what failed, wherever they are in the trace.

    A verbose E2E run can push pytest's FAILED lines and summary out of the last 12 kB (9 jobs
    in the 2026-11 report were unreadable that way). Keeps pytest's "short test summary info"
    section and every FAILED/ERROR test line or final tally, in order, without duplicates.
    """
    lines, keep, in_summary = _STAMP.sub("", text).splitlines(), [], False
    for ln in lines:
        if re.match(r"^=+ short test summary info =+", ln):
            in_summary = True
        if in_summary or _KEY_LINE.match(ln):
            if ln not in keep:
                keep.append(ln)
        if in_summary and re.match(r"^=+ .* in [\d.]+s", ln):
            in_summary = False
    return "\n".join(keep)[:FAILED_LINES_MAX]


def fetch_trace(job_id: int) -> tuple[str, str]:
    """(failed_lines from the whole trace, last TRACE_TAIL chars)."""
    try:
        text = gl(f"projects/{PROJECT}/jobs/{job_id}/trace", raw=True)
    except (RuntimeError, UnicodeDecodeError):
        return "", ""
    text = _ANSI.sub("", text)
    return failed_lines(text), text[-TRACE_TAIL:]


def classify_job(name: str, failed: str, tail: str, failure_reason: str | None = None) -> tuple[str, str]:
    """Classify on the failure lines first (they hold the test ids), then the tail."""
    return classify(name, f"{failed}\n{tail}" if failed else tail, failure_reason)


def fetch(n_mrs: int, n_main: int) -> tuple[list[dict], list[dict]]:
    main = gl_pages(f"projects/{PROJECT}/pipelines?ref=main&order_by=id&sort=desc", n_main)
    pipelines = [dict(p, kind="main", mr_iid=None) for p in main]
    mrs = gl_pages(f"projects/{PROJECT}/merge_requests?state=all&order_by=created_at&sort=desc", n_mrs)

    def mr_pipes(mr):
        try:
            ps = gl(f"projects/{PROJECT}/merge_requests/{mr['iid']}/pipelines?per_page=100")
        except RuntimeError as e:
            print(f"skip MR !{mr['iid']}: {e}", file=sys.stderr)
            return []
        return [dict(p, kind="mr", mr_iid=mr["iid"]) for p in ps]

    with ThreadPoolExecutor(4) as ex:
        for ps in ex.map(mr_pipes, mrs):
            pipelines.extend(ps)
    seen, uniq = set(), []
    for p in pipelines:
        if p["id"] not in seen:
            seen.add(p["id"])
            uniq.append(p)

    def detail(p):
        # The list endpoint has no finished_at; updated_at is when the pipeline last changed state.
        p.setdefault(
            "finished_at", p.get("updated_at") if p["status"] not in ("running", "pending", "created") else None
        )
        jobs = []
        if p["status"] == "failed":
            try:
                jobs = gl(
                    f"projects/{PROJECT}/pipelines/{p['id']}/jobs?scope[]=failed&include_retried=true&per_page=100"
                )
            except RuntimeError as e:
                print(f"skip pipeline {p['id']} jobs: {e}", file=sys.stderr)
        return p, jobs

    failed_jobs = []
    with ThreadPoolExecutor(4) as ex:
        details = list(ex.map(detail, uniq))
    for p, jobs in details:
        for j in jobs:
            failed_jobs.append(dict(j, pipeline_id=p["id"]))

    def add_trace(j):
        j["failed_lines"], j["trace"] = fetch_trace(j["id"])
        return j

    with ThreadPoolExecutor(4) as ex:
        failed_jobs = list(ex.map(add_trace, failed_jobs))
    return [p for p, _ in details], failed_jobs


# --------------------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------------------


def lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(int(v))
    return "'" + str(v).replace("\x00", "").replace("'", "''") + "'"


def run_sql(sql: str, fetch_rows: bool = False):
    if os.environ.get("BIZE_METRICS_PASSWORD"):
        import psycopg2  # noqa: PLC0415

        env = os.environ
        conn = psycopg2.connect(
            host=env.get("BIZE_METRICS_HOST", "127.0.0.1"),
            port=env.get("BIZE_METRICS_PORT", "8402"),
            dbname=env.get("BIZE_METRICS_DB", DATABASE),
            user=env.get("BIZE_METRICS_USER", "bize_dev_rw"),
            password=env["BIZE_METRICS_PASSWORD"],
            connect_timeout=5,
        )
        with conn, conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall() if fetch_rows else None
    cmd = [
        "docker",
        "exec",
        "-i",
        CONTAINER,
        "psql",
        "-X",
        "-q",
        "-U",
        ADMIN_ROLE,
        "-d",
        DATABASE,
        "-v",
        "ON_ERROR_STOP=1",
    ]
    if fetch_rows:
        cmd += ["-A", "-t", "-F", "\t"]
    out = subprocess.run(cmd, input=sql, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-2000:])
    return [ln.split("\t") for ln in out.stdout.splitlines() if ln] if fetch_rows else None


def store(pipelines: list[dict], jobs: list[dict]) -> None:
    stmts = [SCHEMA, "BEGIN;"]
    for p in pipelines:
        stmts.append(
            "INSERT INTO ci.pipelines(id,ref,mr_iid,kind,source,status,sha,created_at,finished_at,duration_s) VALUES ("
            + ",".join(
                lit(x)
                for x in (
                    p["id"],
                    p["ref"],
                    p.get("mr_iid"),
                    p["kind"],
                    p.get("source"),
                    p["status"],
                    p.get("sha"),
                    p.get("created_at"),
                    p.get("finished_at"),
                    p.get("duration"),
                )
            )
            + ") ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status, finished_at=EXCLUDED.finished_at,"
            " duration_s=EXCLUDED.duration_s, fetched_at=now();"
        )
    for j in jobs:
        cause, det = classify_job(j["name"], j.get("failed_lines", ""), j.get("trace", ""), j.get("failure_reason"))
        stmts.append(
            "INSERT INTO ci.failed_jobs(job_id,pipeline_id,name,stage,allow_failure,retried,started_at,finished_at,"
            "duration_s,failure_reason,cause,detail,trace_tail,failed_lines) VALUES ("
            + ",".join(
                lit(x)
                for x in (
                    j["id"],
                    j["pipeline_id"],
                    j["name"],
                    j.get("stage"),
                    j.get("allow_failure"),
                    j.get("retried"),
                    j.get("started_at"),
                    j.get("finished_at"),
                    j.get("duration"),
                    j.get("failure_reason"),
                    cause,
                    det,
                    j.get("trace", ""),
                    j.get("failed_lines", ""),
                )
            )
            + ") ON CONFLICT (job_id) DO UPDATE SET cause=EXCLUDED.cause, detail=EXCLUDED.detail,"
            " retried=EXCLUDED.retried, trace_tail=EXCLUDED.trace_tail, failed_lines=EXCLUDED.failed_lines,"
            " classified_at=now();"
        )
    stmts += [POSTPASS, "COMMIT;"]
    run_sql("\n".join(stmts))


def reclassify() -> int:
    run_sql(SCHEMA)  # adds failed_lines to a table made before it existed

    def b64(col):
        return f"translate(encode(convert_to(coalesce({col},''),'UTF8'),'base64'),E'\\n','')"

    rows = run_sql(
        f"SELECT job_id, name, coalesce(failure_reason,''), {b64('failed_lines')}, {b64('trace_tail')} FROM ci.failed_jobs",
        fetch_rows=True,
    )
    import base64  # noqa: PLC0415

    def dec(v):
        return base64.b64decode(v).decode("utf-8", "replace") if v else ""

    stmts = ["BEGIN;"]
    for job_id, name, reason, failed, tail in rows:
        cause, det = classify_job(name, dec(failed), dec(tail), reason or None)
        stmts.append(
            f"UPDATE ci.failed_jobs SET cause={lit(cause)}, detail={lit(det)}, classified_at=now() WHERE job_id={job_id};"
        )
    stmts += [SCHEMA, POSTPASS, "COMMIT;"]
    run_sql("\n".join(stmts))
    return len(rows)


def report() -> None:
    rows = run_sql("SELECT * FROM ci.cause_summary", fetch_rows=True)
    print(f"{'cause':28} {'jobs':>5} {'pipes':>5} {'main':>5} {'mrs':>4} {'blocked_h':>9}  first..last")
    for r in rows:
        print(f"{r[0]:28} {r[1]:>5} {r[2]:>5} {r[3]:>5} {r[4]:>4} {r[5]:>9}  {r[6]}..{r[7]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh")
    r.add_argument("--mrs", type=int, default=100)
    r.add_argument("--main", type=int, default=200)
    r.add_argument("--offline", action="store_true", help="reclassify stored traces only")
    sub.add_parser("report")
    c = sub.add_parser("classify")
    c.add_argument("--trace", required=True)
    c.add_argument("--job", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "classify":
        print(*classify(a.job, open(a.trace).read()), sep="\t")
        return 0
    if a.cmd == "report":
        report()
        return 0
    if a.offline:
        print(f"reclassified {reclassify()} jobs")
    else:
        t0 = datetime.now()
        pipes, jobs = fetch(a.mrs, a.main)
        store(pipes, jobs)
        print(f"stored {len(pipes)} pipelines, {len(jobs)} failed jobs in {(datetime.now() - t0).seconds}s")
    report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
