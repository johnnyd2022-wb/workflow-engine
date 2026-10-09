"""Unit tests for scripts/metrics_db.py -- the dev-metrics store that replaced the repo files.

DB-free by construction: the outage path is forced by clearing credentials, so nothing here
touches the real `bize_dev` database. What these pin is the contract the rest of the tooling
leans on: an unreachable DB degrades to a local spool (a skill never loses its run and a
merge is never blocked), CI provenance ties rows to the commit/MR, and only main-branch CI
runs may feed a baseline.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_SPEC = importlib.util.spec_from_file_location("metrics_db", _SCRIPTS / "metrics_db.py")
metrics_db = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(metrics_db)


@pytest.fixture
def outage(tmp_path, monkeypatch):
    """No credentials and no unlocked vault: the DB is 'unavailable'. Spool goes to tmp."""
    monkeypatch.delenv("BIZE_METRICS_PASSWORD", raising=False)
    monkeypatch.delenv("KEEPASS_PASSWORD", raising=False)
    monkeypatch.setenv("BIZE_METRICS_SPOOL", str(tmp_path / "spool.jsonl"))
    return tmp_path / "spool.jsonl"


def test_connect_without_credentials_is_unavailable_not_a_crash(outage):
    with pytest.raises(metrics_db.MetricsDBUnavailableError):
        metrics_db.connect()


def test_store_spools_when_db_is_down(outage):
    where = metrics_db.store("run", {"ts": "2026-10-09T00:00:00+00:00", "skill": "x", "run_type": "chained",
                                     "verdict": "clean", "findings": 0, "ref": "r"})  # fmt: skip
    assert where == "spooled"
    spooled = metrics_db.spool_read()
    assert len(spooled) == 1
    assert spooled[0]["kind"] == "run"
    assert spooled[0]["record"]["skill"] == "x"
    assert "commit_sha" in spooled[0]["record"]  # provenance is captured at write time, not flush time


def test_outcomes_spool_without_run_provenance(outage):
    metrics_db.store("outcome", {"ts": "2026-10-09T00:00:00+00:00", "ref": "!1", "outcome": "merged"})
    record = metrics_db.spool_read()[0]["record"]
    assert record["outcome"] == "merged"
    assert "commit_sha" not in record


def test_spool_survives_a_torn_line(outage):
    metrics_db.spool_append("run", {"skill": "a"})
    with outage.open("a") as fh:
        fh.write('{"kind": "run", "record": {"skill"\n')  # a writer killed mid-line
    metrics_db.spool_append("run", {"skill": "b"})
    assert [e["record"]["skill"] for e in metrics_db.spool_read()] == ["a", "b"]


def test_fetch_raises_when_down_so_callers_choose_how_to_degrade(outage):
    with pytest.raises(metrics_db.MetricsDBUnavailableError):
        metrics_db.fetch("run")


def test_check_is_a_visible_skip_when_unreachable(outage, capsys):
    assert metrics_db.cmd_check() == 0  # an outage must never block a merge
    assert "SKIPPED" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("env", "is_main"),
    [
        ({"GITLAB_CI": "true", "CI_COMMIT_REF_NAME": "main", "CI_DEFAULT_BRANCH": "main"}, True),
        # an MR pipeline of a branch named main is still not a main-branch run
        ({"GITLAB_CI": "true", "CI_COMMIT_REF_NAME": "main", "CI_MERGE_REQUEST_IID": "7"}, False),
        ({"GITLAB_CI": "true", "CI_COMMIT_REF_NAME": "feat/x", "CI_DEFAULT_BRANCH": "main"}, False),
        # local runs never feed a baseline, even from the main branch
        ({"CI_COMMIT_REF_NAME": "main"}, False),
    ],
)
def test_only_main_branch_ci_runs_are_baseline_eligible(monkeypatch, env, is_main):
    for key in ("GITLAB_CI", "CI_COMMIT_REF_NAME", "CI_DEFAULT_BRANCH", "CI_MERGE_REQUEST_IID"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert metrics_db.provenance()["is_main"] is is_main


def test_provenance_carries_commit_mr_and_pipeline(monkeypatch):
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.setenv("CI_COMMIT_SHA", "abc123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "42")
    monkeypatch.setenv("CI_PIPELINE_ID", "9001")
    monkeypatch.setenv("CI_JOB_ID", "not-a-number")
    prov = metrics_db.provenance()
    assert (prov["commit_sha"], prov["mr_iid"], prov["pipeline_id"]) == ("abc123", 42, 9001)
    assert prov["job_id"] is None  # a malformed id must not crash a run
    assert prov["source"] == "ci"


def test_record_perf_reports_unavailable_without_raising(outage):
    result = {"route": "/r", "kind": "api", "metrics": {"queries": 3, "backend_ms": 9.0}, "over_budget": [],
              "over_ceiling": []}  # fmt: skip
    assert metrics_db.record_perf([result]) == "unavailable"


# ---- perf baseline gate (lives in the perf test module; loaded the same way) -------------


def _perf_module():
    spec = importlib.util.spec_from_file_location(
        "perf_budgets", Path(__file__).resolve().parent / "e2e" / "test_perf_budgets.py"
    )
    module = importlib.util.module_from_spec(spec)
    return spec, module


@pytest.mark.parametrize(
    ("median", "samples", "queries", "regressed"),
    [
        (10, 20, 12, False),  # within 25% and +2
        (10, 20, 13, True),  # > 12.5
        (2, 20, 4, False),  # tiny medians get the +2 allowance, not a 25% knife edge
        (2, 20, 5, True),
        (10, 4, 99, False),  # too little history: never gate on it
    ],
)
def test_baseline_regression_threshold(monkeypatch, median, samples, queries, regressed):
    pytest.importorskip("playwright")
    spec, module = _perf_module()
    try:
        spec.loader.exec_module(module)
    except Exception as e:  # noqa: BLE001 -- the e2e module needs the full e2e environment
        pytest.skip(f"perf module not importable here: {e}")
    monkeypatch.setattr(module, "_BASELINE", {("/r", "queries"): (float(median), samples)})
    assert bool(module._baseline_regression("/r", {"queries": queries})) is regressed
