"""Unit tests for scripts/e2e_coverage.py's matcher.

The coverage tool is only useful if its route matching is correct: a matcher that silently
UNDER-matches reports false gaps (agents waste tokens writing tests that exist); one that
OVER-matches reports false coverage (real gaps hide). These pin both directions.
"""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "e2e_coverage", Path(__file__).resolve().parents[1] / "scripts" / "e2e_coverage.py"
)
e2e_coverage = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(e2e_coverage)

path_matches_rule = e2e_coverage.path_matches_rule


@pytest.mark.parametrize(
    "url,rule",
    [
        ("/core/processes", "/core/processes"),
        ("/api/core/processes/{}", "/api/core/processes/<process_id>"),
        ("/api/core/inventory/{}/adjust", "/api/core/inventory/<item_id>/adjust"),
        (
            "/api/core/executions/{}/steps/{}/complete",
            "/api/core/executions/<execution_id>/steps/<execution_step_id>/complete",
        ),
        ("/org/users/{}", "/org/users/<user_id>"),
        ("/ui/shared/password-policy.js", "/ui/shared/<path:filename>"),  # <path:> swallows
    ],
)
def test_matches_when_it_should(url, rule):
    assert path_matches_rule(url, rule), f"{url} should match {rule}"


@pytest.mark.parametrize(
    "url,rule",
    [
        ("/api/core/processes", "/api/core/processes/<process_id>"),  # too few segments
        ("/api/core/processes/{}/steps", "/api/core/processes/<process_id>"),  # too many
        ("/api/core/inventory", "/api/core/executions"),  # different literal
        ("/core/processes", "/core/flows"),  # sibling page, not the same
    ],
)
def test_does_not_match_when_it_should_not(url, rule):
    assert not path_matches_rule(url, rule), f"{url} must NOT match {rule}"


def test_wildcard_is_symmetric():
    # A concrete tested id must match a rule's <param>, and a rule literal must match a
    # tested {expr} — either side may hold the wildcard.
    assert path_matches_rule("/api/core/inventory/abc123", "/api/core/inventory/<item_id>")
    assert path_matches_rule("/api/core/inventory/{}", "/api/core/inventory/<item_id>")


def test_build_coverage_shape_and_no_false_gap_for_known_covered():
    """End-to-end on the real app + real tests: known-covered routes are not false gaps."""
    data = e2e_coverage.build_coverage()
    assert set(data) >= {"summary", "gaps", "routes"}
    assert data["summary"]["considered"] > 0

    covered = {}
    for row in data["routes"]:
        covered.setdefault(row["rule"], set()).update(row["covered_methods"])

    # These are exercised by the committed suite; the matcher must see them.
    must_cover = [
        ("/api/core/processes", "POST"),
        ("/api/core/processes/<process_id>", "DELETE"),
        ("/api/core/inventory/<item_id>", "PUT"),
        ("/api/core/executions", "POST"),
        ("/org/users", "POST"),
        ("/auth/login", "POST"),  # UI-driven map
    ]
    missed = [(r, m) for r, m in must_cover if m not in covered.get(r, set())]
    assert not missed, f"matcher reports false gaps for known-covered routes: {missed}"
