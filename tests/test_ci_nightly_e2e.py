"""The nightly E2E schedule runs every E2E file and must never deploy.

A pipeline schedule on main matches every `only: [main]` job, so without an opt-out the
nightly run would rebuild and redeploy the test environment every night.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NIGHTLY = '$E2E_NIGHTLY == "1"'


def _jobs() -> dict[str, str]:
    text = (ROOT / ".gitlab-ci.yml").read_text()
    parts = re.split(r"(?m)^([A-Za-z_][\w-]*):\n", text)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def _excludes_nightly(body: str) -> bool:
    m = re.search(r"(?m)^  except:\n((?:    .*\n)+)", body)
    return bool(m) and NIGHTLY in m.group(1)


def test_build_and_deploy_jobs_skip_the_nightly_pipeline():
    jobs = _jobs()
    shipping = [n for n, b in jobs.items() if re.search(r"(?m)^  stage: (build|deploy)\s*$", b)]
    assert {"deploy_test", "docker_build_publish", "cd_e2e", "promote_test_stable"} <= set(shipping)
    assert [n for n in shipping if not _excludes_nightly(jobs[n])] == []


def test_other_scheduled_jobs_skip_the_nightly_pipeline():
    jobs = _jobs()
    scheduled = [n for n, b in jobs.items() if n != "nightly_e2e" and re.search(r"(?m)^    - schedules\s*$", b)]
    assert scheduled, "expected renovate/lockfile_consistency to be schedule jobs"
    assert [n for n in scheduled if not _excludes_nightly(jobs[n])] == []


def test_nightly_job_runs_the_whole_e2e_directory_only_on_its_schedule():
    body = _jobs()["nightly_e2e"]
    assert re.search(r"pytest tests/e2e/(\s|$)", body)
    assert "- schedules" in body and NIGHTLY in body
    # Warn-only until the first green nightly: a red schedule pipeline is main's head pipeline,
    # which main_green would read as "main is red" and block every MR on it.
    assert "allow_failure: true" in body
