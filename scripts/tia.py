#!/usr/bin/env python3
"""Test impact analysis: run only the tests a merge request's changed lines can affect.

main's full test run records which lines of which files every test executed (coverage with
per-test contexts, plus scripts/tia_probe.py for templates and static files) into the `tia`
schema of the bize_dev database. A merge request pipeline diffs its changes against the
newest recorded run that is an ancestor of its base, asks the database which tests executed
those lines, and runs only those. main still runs everything, so anything a selection missed
fails there, and `tia.selections` shows which MR skipped it.

    python3 scripts/tia.py migrate                         # admin, local: create/upgrade schema
    python3 scripts/tia.py status                          # connectivity + newest runs
    python3 scripts/tia.py record --coverage .coverage --probe tia-probe.json --sha SHA --ref main
    python3 scripts/tia.py select --base BASE --head HEAD [--record] --out targets.txt

Connection: $BIZE_METRICS_HOST/_PORT/_DB/_USER/_PASSWORD (CI project variables; job
containers reach the host as host.docker.internal:8402). See docs/test-impact-analysis.md.

`select` never fails a pipeline: when the database, the map or git history is unavailable it
writes the full-suite target and says why.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "workflow-engine-terraform-state-db-1"
ADMIN_ROLE = "bize_dev_admin"
DATABASE = "bize_dev"
FULL = ["tests/"]

# Inputs every test depends on: a change here can affect anything, so run everything.
GLOBAL_INPUTS = (
    re.compile(r"(^|/)conftest\.py$"),
    re.compile(r"^pyproject\.toml$"),
    re.compile(r"^uv\.lock$"),
    re.compile(r"^app/config/[^/]+\.ini$"),
    re.compile(r"^app/core/db/migrations/"),
    re.compile(r"^ci/setup_database\.sh$"),
    re.compile(r"^tests/factories"),
)
# Only these are measured by the map; anything else (docs, skills, reports) affects no test.
CODE = re.compile(r"^(app|scripts)/.+\.(py|html|jinja|js|css|json|sql)$")
TEST_MODULE = re.compile(r"^tests/(.+/)?test_[^/]+\.py$")
TEST_SUPPORT = re.compile(r"^tests/.+\.(py|js|json)$")
# Changes no test can observe: prose, agent skills, reports.
DOCS = re.compile(r"(^docs/|^\.agents/|^\.claude/|^skills/|\.md$)")


# --------------------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------------------


class UnavailableError(Exception):
    pass


def connect():
    env = os.environ
    if not env.get("BIZE_METRICS_PASSWORD"):
        raise UnavailableError("BIZE_METRICS_PASSWORD is not set")
    try:
        import psycopg2  # noqa: PLC0415
    except ImportError as e:
        raise UnavailableError("psycopg2 is not installed") from e
    try:
        return psycopg2.connect(
            host=env.get("BIZE_METRICS_HOST", "127.0.0.1"),
            port=env.get("BIZE_METRICS_PORT", "8402"),
            dbname=env.get("BIZE_METRICS_DB", DATABASE),
            user=env.get("BIZE_METRICS_USER", "bize_dev_rw"),
            password=env["BIZE_METRICS_PASSWORD"],
            connect_timeout=5,
            options="-c statement_timeout=60000",
        )
    except psycopg2.OperationalError as e:
        raise UnavailableError("database unreachable") from e


def migrate(_args) -> int:
    sql = (ROOT / "tia_db" / "schema.sql").read_text() + (ROOT / "tia_db" / "grants.sql").read_text()
    cmd = ["docker", "exec", "-i", CONTAINER, "psql", "-U", ADMIN_ROLE, "-d", DATABASE, "-v", "ON_ERROR_STOP=1", "-q"]
    return subprocess.run(cmd, input=sql, text=True).returncode


def status(_args) -> int:
    try:
        conn = connect()
    except UnavailableError as e:
        print(f"tia: unavailable ({e})")
        return 0
    with conn, conn.cursor() as cur:
        cur.execute("SELECT id, sha, ref, recorded_at, tests, failed FROM tia.runs ORDER BY id DESC LIMIT 5")
        for row in cur.fetchall():
            print("run", *row)
        cur.execute("SELECT count(*), count(*) FILTER (WHERE decision = 'select') FROM tia.selections")
        print("selections (total, narrowed):", *cur.fetchone())
    return 0


def covers(selection: list[str], test: str) -> bool:
    """Whether a recorded selection ran this test (node IDs, module paths, or everything)."""
    for target in selection:
        target = target.rstrip("/")
        if target == "tests" or test == target or test.startswith(target + "::") or test.startswith(target + "/"):
            return True
    return False


def find_escapes(failed: list[str], selections: list[tuple]) -> list[tuple]:
    """(mr, test) for every test that failed on main but a merged MR's selection skipped."""
    return [
        (mr, test)
        for mr, decision, tests in selections
        if decision in ("select", "none")
        for test in failed
        if not covers(tests, test)
    ]


def escapes(_args) -> int:
    """Ongoing accuracy check: main's failures that an MR merged since the last run skipped."""
    try:
        conn = connect()
    except UnavailableError as e:
        print(f"tia: unavailable ({e})")
        return 0
    with conn, conn.cursor() as cur:
        cur.execute("SELECT id, sha, recorded_at FROM tia.runs WHERE ref = 'main' ORDER BY id DESC LIMIT 2")
        runs = cur.fetchall()
        if len(runs) < 2:
            print("tia: need two recorded main runs")
            return 0
        (latest, sha, until), (_, _, since) = runs
        cur.execute(
            "SELECT t.nodeid FROM tia.results r JOIN tia.tests t ON t.id = r.test_id "
            "WHERE r.run_id = %s AND r.outcome = 'failed'",
            (latest,),
        )
        failed = [row[0] for row in cur.fetchall()]
        cur.execute(
            "SELECT DISTINCT ON (mr_iid) mr_iid, decision, tests FROM tia.selections "
            "WHERE recorded_at > %s AND recorded_at <= %s ORDER BY mr_iid, id DESC",
            (since, until),
        )
        found = find_escapes(failed, cur.fetchall())
    print(f"tia: run {latest} ({sha[:12]}): {len(failed)} failing tests, {len(found)} selection escapes")
    for mr, test in found:
        print(f"  escape: !{mr} skipped {test}")
    return 1 if found else 0


# --------------------------------------------------------------------------------------
# Record (main)
# --------------------------------------------------------------------------------------


def _coverage_map(path: Path, root: Path) -> dict[tuple[str, str], set[int]]:
    from coverage.numbits import numbits_to_nums  # noqa: PLC0415

    db = sqlite3.connect(path)
    files = {i: os.path.relpath(p, root) for i, p in db.execute("SELECT id, path FROM file")}
    contexts = {i: name.split("|")[0] for i, name in db.execute("SELECT id, context FROM context")}
    out: dict[tuple[str, str], set[int]] = defaultdict(set)
    for file_id, context_id, numbits in db.execute("SELECT file_id, context_id, numbits FROM line_bits"):
        test = contexts.get(context_id)
        path_ = files[file_id]
        if test and not path_.startswith(".."):
            out[(test, path_)].update(numbits_to_nums(numbits))
    return out


def _ids(cur, table: str, column: str, values) -> dict[str, int]:
    values = sorted(set(values))
    from psycopg2.extras import execute_values  # noqa: PLC0415

    execute_values(cur, f"INSERT INTO tia.{table} ({column}) VALUES %s ON CONFLICT DO NOTHING", [(v,) for v in values])
    cur.execute(f"SELECT {column}, id FROM tia.{table} WHERE {column} = ANY(%s)", (values,))
    return dict(cur.fetchall())


def record(args) -> int:
    from psycopg2.extras import execute_values  # noqa: PLC0415

    probe = json.loads(Path(args.probe).read_text())
    results: dict[str, list] = probe["results"]
    lines = _coverage_map(Path(args.coverage), Path(args.root).resolve())
    for test, files in probe["files"].items():
        for path_ in files:
            lines.setdefault((test, path_), set()).add(-1)  # -1: the whole file counts
    if not results:
        print("tia: probe recorded no results; nothing to record")
        return 1
    try:
        conn = connect()
    except UnavailableError as e:
        print(f"tia: record skipped ({e})")
        return 0
    with conn, conn.cursor() as cur:
        test_ids = _ids(cur, "tests", "nodeid", list(results) + [t for t, _ in lines])
        file_ids = _ids(cur, "files", "path", [f for _, f in lines])
        failed = sum(1 for outcome, _ in results.values() if outcome == "failed")
        cur.execute(
            "INSERT INTO tia.runs (sha, ref, pipeline_id, tests, failed) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (args.sha, args.ref, args.pipeline_id, len(results), failed),
        )
        run_id = cur.fetchone()[0]
        execute_values(
            cur,
            "INSERT INTO tia.test_lines (run_id, file_id, test_id, lines) VALUES %s",
            [(run_id, file_ids[f], test_ids[t], None if -1 in ls else sorted(ls)) for (t, f), ls in lines.items()],
            page_size=5000,
        )
        execute_values(
            cur,
            "INSERT INTO tia.results (run_id, test_id, outcome, seconds) VALUES %s",
            [(run_id, test_ids[t], outcome, seconds) for t, (outcome, seconds) in results.items()],
            page_size=5000,
        )
    print(f"tia: recorded run {run_id} for {args.sha[:12]}: {len(results)} tests, {len(lines)} test/file rows")
    return 0


# --------------------------------------------------------------------------------------
# Select (merge requests)
# --------------------------------------------------------------------------------------


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def changed_paths(base: str, head: str) -> list[str]:
    return [p for p in git("diff", "--name-only", f"{base}...{head}").splitlines() if p]


def touched_lines(since: str, head: str, path: str) -> set[int]:
    """Lines of `path` as it was at `since` that changed by `head`; insertions touch neighbours."""
    lines: set[int] = set()
    for hunk in re.finditer(r"^@@ -(\d+)(?:,(\d+))? ", git("diff", "-U0", since, head, "--", path), re.M):
        start, count = int(hunk.group(1)), int(hunk.group(2) or 1)
        if count == 0:
            lines.update((start, start + 1))
        else:
            lines.update(range(start, start + count))
    return lines


def exists_at(commit: str, path: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{commit}:{path}"], cwd=ROOT, capture_output=True).returncode == 0


def code_lines(commit: str, path: str, lines: set[int]) -> set[int]:
    """Which of these line numbers hold code (not blank, not a comment) in path at commit."""
    if not lines or not exists_at(commit, path):
        return set()
    text = git("show", f"{commit}:{path}").splitlines()
    return {n for n in lines if 0 < n <= len(text) and text[n - 1].strip() and not text[n - 1].lstrip().startswith("#")}


def modules_naming(path: str) -> set[str]:
    """Python test modules that mention the file by name, directly or via a JS test that does."""
    name = Path(path).name
    if len(name) < 6:
        return set()
    hits = subprocess.run(
        ["git", "grep", "-l", "-F", name, "--", "tests"], cwd=ROOT, capture_output=True, text=True
    ).stdout.split()
    modules = {h for h in hits if TEST_MODULE.match(h)}
    if any(h.endswith((".test.js", ".test.mjs")) for h in hits):
        # A JS test names it; the Python modules that run the JS tests do so by glob.
        runners = subprocess.run(
            ["git", "grep", "-l", "-F", ".test.js", "--", "tests"], cwd=ROOT, capture_output=True, text=True
        ).stdout.split()
        modules |= {h for h in runners if TEST_MODULE.match(h)}
    return modules


def newest_ancestor_run(cur, base: str):
    cur.execute("SELECT id, sha FROM tia.runs WHERE ref = 'main' ORDER BY id DESC LIMIT 50")
    for run_id, sha in cur.fetchall():
        if subprocess.run(["git", "merge-base", "--is-ancestor", sha, base], cwd=ROOT).returncode == 0:
            return run_id, sha
    return None, None


def plan(cur, base: str, head: str) -> dict:
    """Decide what to run. Pure over the database and git; no side effects."""
    paths = changed_paths(base, head)
    reasons: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        if any(g.search(p) for g in GLOBAL_INPUTS):
            reasons["full"].append(f"global input: {p}")
    if reasons["full"]:
        return {"decision": "full", "tests": FULL, "reasons": reasons, "paths": paths, "run": None}

    code = [p for p in paths if CODE.match(p)]
    test_modules = [p for p in paths if TEST_MODULE.match(p) and exists_at(head, p)]
    other = [p for p in paths if not (CODE.match(p) or TEST_SUPPORT.match(p) or DOCS.search(p))]
    support = [p for p in paths if TEST_SUPPORT.match(p) and not TEST_MODULE.match(p)]
    if support:
        reasons["full"].extend(f"shared test support: {p}" for p in support)
        return {"decision": "full", "tests": FULL, "reasons": reasons, "paths": paths, "run": None}
    if not code and not test_modules and not other:
        return {
            "decision": "none",
            "tests": [],
            "reasons": {"none": ["no code or tests changed"]},
            "paths": paths,
            "run": None,
        }

    run_id, run_sha = newest_ancestor_run(cur, base)
    if run_id is None:
        reasons["full"].append("no recorded main run is an ancestor of the merge base")
        return {"decision": "full", "tests": FULL, "reasons": reasons, "paths": paths, "run": None}

    selected: set[str] = set(test_modules)
    for p in test_modules:
        reasons["changed test module"].append(p)
    for p in other:
        # CI config, shell scripts, Dockerfiles: the tests that read them do so by name.
        named = modules_naming(p)
        selected |= named
        reasons["named by tests"].append(f"{p}: {len(named)} test modules")
    for p in code:
        cur.execute(
            "SELECT t.nodeid, tl.lines FROM tia.test_lines tl "
            "JOIN tia.files f ON f.id = tl.file_id JOIN tia.tests t ON t.id = tl.test_id "
            "WHERE tl.run_id = %s AND f.path = %s",
            (run_id, p),
        )
        rows = cur.fetchall()
        if not rows:
            # No test executed this file in-process when main was recorded: a Node-tested
            # script, a template loaded by name, or a new file. Run the test modules that name
            # it; a file nothing names gets no signal from the full suite either, so it is
            # reported rather than paid for.
            named = modules_naming(p)
            selected |= named
            reasons["executed by no recorded test"].append(f"{p}: {len(named)} test modules name it")
            continue
        # Whole-file users (rendered or served it, or ran it in a child process) always count;
        # line-level users count when they executed a changed line.
        whole = {t for t, ls in rows if ls is None}
        line_rows = [(t, ls) for t, ls in rows if ls is not None]
        hit = set(whole)
        if whole:
            reasons["used as a whole file"].append(f"{p}: {len(whole)} tests")
        if line_rows:
            wanted = touched_lines(run_sha, head, p)
            by_line = {t for t, ls in line_rows if wanted.intersection(ls)}
            covered = set().union(*(ls for _, ls in line_rows))
            if code_lines(run_sha, p, wanted - covered):
                # Real code no test ran inside its own context: module level (imports, def
                # lines, constants, decorators) runs at import. Everything using the file counts.
                by_line = {t for t, _ in line_rows}
                reasons["module-level change"].append(f"{p}: {len(by_line)} tests")
            else:
                reasons["changed lines"].append(f"{p}: {len(wanted)} lines, {len(by_line)} tests")
            hit |= by_line
        selected |= hit
    if not selected:
        return {"decision": "none", "tests": [], "reasons": reasons, "paths": paths, "run": run_id}
    return {"decision": "select", "tests": sorted(selected), "reasons": reasons, "paths": paths, "run": run_id}


def cost(cur, run_id, tests: list[str]) -> tuple[float, float]:
    if run_id is None:
        cur.execute("SELECT id FROM tia.runs WHERE ref = 'main' ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if not row:
            return 0.0, 0.0
        run_id = row[0]
    cur.execute("SELECT coalesce(sum(seconds), 0) FROM tia.results WHERE run_id = %s", (run_id,))
    full = float(cur.fetchone()[0])
    if tests == FULL:
        return full, full
    modules = [t for t in tests if "::" not in t]
    nodes = [t for t in tests if "::" in t]
    cur.execute(
        "SELECT coalesce(sum(r.seconds), 0) FROM tia.results r JOIN tia.tests t ON t.id = r.test_id "
        "WHERE r.run_id = %s AND (t.nodeid = ANY(%s) OR split_part(t.nodeid, '::', 1) = ANY(%s))",
        (run_id, nodes, modules),
    )
    return float(cur.fetchone()[0]), full


def combine(result: dict, rules: list[str]) -> list[str]:
    """Merge with scripts/select_relevant_tests.py's path-rule targets.

    The rules still own environment needs and their hand-mapped areas; the map replaces only
    their full-suite fallback. A full decision here defers to the rules (which may be narrower).
    """
    rules_full = not rules or rules == FULL or "tests" in rules or "tests/" in rules
    if result["decision"] == "full":
        return rules or FULL
    if rules == ["__NO_TESTS__"]:
        return []
    narrowed = list(result["tests"])
    if not rules_full:
        narrowed += [t for t in rules if t not in narrowed]
    return narrowed


def select(args) -> int:
    out = Path(args.out)
    try:
        conn = connect()
    except UnavailableError as e:
        result = {"decision": "full", "tests": FULL, "reasons": {"full": [f"test-impact database unavailable: {e}"]}}
        conn = None
    else:
        try:
            with conn, conn.cursor() as cur:
                result = plan(cur, args.base, args.head)
                selected_s, full_s = cost(cur, result["run"], result["tests"])
                result["seconds"] = {"selected": round(selected_s, 1), "full": round(full_s, 1)}
                if args.record:
                    cur.execute(
                        "INSERT INTO tia.selections (mode, mr_iid, pipeline_id, base_sha, head_sha, map_run_id, decision, "
                        "reasons, selected_tests, selected_seconds, full_seconds, tests) "
                        "VALUES ('enforced', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            args.mr,
                            args.pipeline,
                            args.base,
                            args.head,
                            result["run"],
                            result["decision"],
                            json.dumps(result["reasons"]),
                            0 if result["tests"] == FULL else len(result["tests"]),
                            selected_s,
                            full_s,
                            result["tests"],
                        ),
                    )
        except Exception as e:  # noqa: BLE001 - selection must never be the reason a pipeline fails
            result = {
                "decision": "full",
                "tests": FULL,
                "reasons": {"full": [f"selection failed: {type(e).__name__}: {e}"]},
            }
        finally:
            conn.close()
    if args.rules_targets:
        result["tests"] = combine(result, Path(args.rules_targets).read_text().split())
    out.write_text("\n".join(result["tests"]) + ("\n" if result["tests"] else ""))
    summary = {k: v for k, v in result.items() if k not in {"tests", "paths"}}
    summary["selected_tests"] = "all" if result["tests"] == FULL else len(result["tests"])
    print(json.dumps(summary, indent=2, default=str))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate").set_defaults(func=migrate)
    sub.add_parser("status").set_defaults(func=status)
    sub.add_parser("escapes", help="tests main failed that a merged MR skipped").set_defaults(func=escapes)
    rec = sub.add_parser("record")
    rec.add_argument("--coverage", required=True)
    rec.add_argument("--probe", required=True)
    rec.add_argument("--sha", required=True)
    rec.add_argument("--ref", default="main")
    rec.add_argument("--pipeline-id", type=int)
    rec.add_argument("--root", default=str(ROOT), help="checkout the tests ran in (coverage paths are relative to it)")
    rec.set_defaults(func=record)
    sel = sub.add_parser("select")
    sel.add_argument("--base", required=True)
    sel.add_argument("--head", required=True)
    sel.add_argument("--out", required=True, help="file to write pytest targets to, one per line")
    sel.add_argument("--record", action="store_true", help="log the selection in tia.selections")
    sel.add_argument("--mr", type=int)
    sel.add_argument("--pipeline", type=int)
    sel.add_argument("--rules-targets", help="select_relevant_tests.py --format pytest output to merge with")
    sel.set_defaults(func=select)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
