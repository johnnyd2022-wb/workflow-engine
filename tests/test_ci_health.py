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


def _long_e2e_trace():
    """A verbose E2E job: the pytest summary is followed by >12 kB of teardown/after_script noise."""
    head = "\n".join(f"{STAMP}tests/e2e/test_a.py::test_{i}[chromium] PASSED" for i in range(50))
    summary = (
        f"{STAMP}=========================== short test summary info ============================\n"
        f"{STAMP}FAILED tests/e2e/test_sales.py::test_overview[chromium-1440] - AssertionError: card\n"
        f"{STAMP}FAILED tests/e2e/test_sales.py::test_overview[chromium-1024] - AssertionError: card\n"
        f"{STAMP}=========== 2 failed, 198 passed, 149 warnings in 237.34s (0:03:57) ============\n"
    )
    noise = "\n".join(f"{STAMP}[info] server shutdown step {i} " + "x" * 80 for i in range(200))
    return head + "\n" + summary + noise + "\nERROR: Job failed: exit code 1\n"


def test_failed_lines_survive_when_the_summary_is_outside_the_tail():
    from scripts.ci_health import TRACE_TAIL, classify_job, failed_lines

    trace = _long_e2e_trace()
    tail = trace[-TRACE_TAIL:]
    assert "FAILED tests/" not in tail  # the 2026-11 "unreadable" case
    assert classify("relevant_tests", tail)[0] == "script_error"

    lines = failed_lines(trace)
    assert lines.splitlines() == [
        "=========================== short test summary info ============================",
        "FAILED tests/e2e/test_sales.py::test_overview[chromium-1440] - AssertionError: card",
        "FAILED tests/e2e/test_sales.py::test_overview[chromium-1024] - AssertionError: card",
        "=========== 2 failed, 198 passed, 149 warnings in 237.34s (0:03:57) ============",
    ]
    cause, detail = classify_job("relevant_tests", lines, tail)
    assert cause == "e2e_assertion"
    assert (
        detail
        == "tests/e2e/test_sales.py::test_overview[chromium-1024] | tests/e2e/test_sales.py::test_overview[chromium-1440]"
    )


def test_failed_lines_is_empty_for_a_trace_with_no_test_failures():
    from scripts.ci_health import classify_job, failed_lines

    assert failed_lines("$ ruff format --check\n1 file would be reformatted\n") == ""
    assert classify_job("ruff", "", "1 file would be reformatted")[0] == "lint_format"


@pytest.mark.parametrize(
    ("trace", "cause"),
    [
        (
            "collecting ... ERROR: not found: /builds/w/tests/test_sites.py::test_gone\n"
            "============================ no tests ran in 2.28s =============================",
            "selection_stale_nodeid",
        ),
        ("ERROR: file or directory not found: Gin\n=== no tests ran in 1s ===", "selection_stale_nodeid"),
        ("6 workers [0 items]\n\n============================ no tests ran in 1.80s ======", "no_tests_collected"),
        (
            "ERROR gw2 - Different tests were collected between gw1 and gw2. The difference is:",
            "xdist_collection_mismatch",
        ),
    ],
)
def test_collection_failures_are_named_not_lumped_into_script_error(trace, cause):
    """The 2026-11 report's nine "unreadable" jobs were these: pytest collected nothing."""
    assert classify("relevant_tests", trace + "\nERROR: Job failed: exit code 1")[0] == cause


def test_failed_lines_keep_a_collection_error_far_above_the_tail():
    from scripts.ci_health import TRACE_TAIL, classify_job, failed_lines

    trace = (
        f"{STAMP}collecting ... ERROR: not found: /builds/w/tests/test_sites.py::test_renamed\n"
        f"{STAMP}============================ no tests ran in 2.28s =============================\n"
        + "\n".join(f"{STAMP}[after_script] cleanup {i} " + "x" * 90 for i in range(200))
    )
    tail = trace[-TRACE_TAIL:]
    assert "not found" not in tail
    lines = failed_lines(trace)
    assert "ERROR: not found: /builds/w/tests/test_sites.py::test_renamed" in lines
    assert "no tests ran in 2.28s" in lines
    assert classify_job("relevant_tests", lines, tail)[0] == "selection_stale_nodeid"
