"""scripts/ci_health.py's classifier: the cause names the report ranks by must be stable."""

import pytest

from scripts.ci_health import classify

STAMP = "2026-11-02T07:58:44.477696Z 01O "


@pytest.mark.parametrize(
    ("job", "trace", "cause"),
    [
        ("main_green", "main 1234abcd: pipeline running\nMerge blocked until", "stale_main_gate"),
        ("main_green", "main 1234abcd: pipeline failed\nMerge blocked until", "main_red_inherited"),
        ("uv_audit", '{"id": "GHSA-42gh-23hr-vphw"}', "new_advisory"),
        (
            "cd_e2e",
            "failed requests:\n - GET https://fonts.gstatic.com/s/roboto — net::ERR_NETWORK_CHANGED",
            "third_party_fonts",
        ),
        ("cd_e2e", "Page.goto: net::ERR_CONNECTION_REFUSED at https://localhost:8001/", "deploy_not_ready"),
        (
            "relevant_tests",
            "manifest for registry.gitlab.com/whistlebird/workflow-engine/ci:4b42 not found",
            "ci_image_missing",
        ),
        ("relevant_tests", STAMP + "FAILED tests/test_x.py::test_y - assert 1 == 2", "test_failure"),
        ("relevant_tests", STAMP + "FAILED tests/e2e/test_x.py::test_y[chromium]", "e2e_assertion"),
        ("relevant_tests", "E   subprocess.TimeoutExpired: Command 'bash' timed out", "timeout"),
        ("rollback_test_on_failure", "manifest for .../app:test-stable not found", "deploy_bootstrap"),
        ("whatever", "nothing recognisable", "unclassified"),
    ],
)
def test_classify(job, trace, cause):
    assert classify(job, trace)[0] == cause


def test_detail_names_the_failed_tests_even_with_runner_timestamps():
    trace = f"{STAMP}FAILED tests/test_b.py::t2\n{STAMP}FAILED tests/test_a.py::t1\n"
    assert classify("relevant_tests", trace)[1] == "tests/test_a.py::t1 | tests/test_b.py::t2"
