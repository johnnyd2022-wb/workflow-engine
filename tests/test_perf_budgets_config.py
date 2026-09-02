"""Static sanity checks for `.agents/perf/budgets.json`.

These are plain data assertions — no app boot, no DB, no browser — so they run in the
normal `uv run pytest tests/` suite, unlike the measurement itself in
`tests/e2e/test_perf_budgets.py` (which is `pytest.mark.e2e`).

Why this exists: a perf override can be committed with a deliberately loose *stub* budget
("15 / 80, recalibrate later") to unblock a merge, and nothing then fails until someone
remembers to do the measured run. `/api/core/hub/overview` sat that way from 2026-08-27
until a findings-sweep calibrated it on 2026-09-03. These guards make "there is an
un-calibrated override" a red test instead of a follow-up nobody greps.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

BUDGETS_FILE = Path(__file__).resolve().parents[1] / ".agents" / "perf" / "budgets.json"
BUDGETS = json.loads(BUDGETS_FILE.read_text(encoding="utf-8"))

OVERRIDES = BUDGETS.get("overrides", {})

# Future-tense phrases that mean "the measured run still has not happened". `PLACEHOLDER`
# is matched case-sensitively on purpose: the budgets file uses the upper-case word as a
# deliberate, grep-able marker (that is how the pre-2026-09-03 `/api/core/hub/overview`
# note flagged itself), so lower-case past-tense prose ("was a loose stub until X") in a
# real calibration record is not a hit.
_STUB_MARKERS = (
    "PLACEHOLDER",
    "pending a measured run",
    "pending a measured",
    "recalibrate later",
    "calibrate this later",
    "to be calibrated",
    "TODO",
    "FIXME",
)

# A real calibration record names the date it was measured. Any 20xx year in `_why` counts.
_DATED_CALIBRATION = re.compile(r"\b20\d{2}\b")


def test_budgets_file_parses_and_has_the_expected_top_level_shape():
    assert set(BUDGETS) >= {"defaults", "measure", "overrides"}
    assert BUDGETS["measure"]["api"], "measure.api list is empty"
    assert BUDGETS["measure"]["pages"], "measure.pages list is empty"


@pytest.mark.parametrize("route", sorted(OVERRIDES))
def test_override_carries_a_dated_calibration_note_not_a_stub(route):
    """Every override that ships must document a real, dated measurement in `_why` — not a
    'recalibrate later' stub. Belt (no stub phrase) and braces (a 20xx date is present)."""
    why_lines = OVERRIDES[route].get("_why", [])
    assert why_lines, f"override {route} has no _why calibration note"

    joined = " ".join(why_lines)
    offending = [line for line in why_lines if any(marker in line for marker in _STUB_MARKERS)]
    assert not offending, (
        f"override {route} still reads as an un-calibrated stub: {offending!r} — "
        "run the perf-guardrails measurement procedure and set the observed numbers"
    )
    assert _DATED_CALIBRATION.search(joined), (
        f"override {route} _why has no measurement date — a calibration record names when "
        "it was measured (see the perf-guardrails SKILL.md procedure)"
    )


@pytest.mark.parametrize("route", sorted(OVERRIDES))
def test_override_metrics_are_ordered_budget_le_ceiling(route):
    """An override may set only `budget` (inheriting the default ceiling), only `ceiling`, or
    both; whenever it sets both, budget must not exceed ceiling. When it sets a budget but no
    ceiling, that budget must still sit under the default ceiling for the route's kind — an
    override budget above the default ceiling makes the ceiling unreachable via the merge in
    ``test_perf_budgets.py::_limits``."""
    kind = "api" if route.startswith("/api/") else "page"
    for metric, levels in OVERRIDES[route].items():
        if metric == "_why":
            continue
        budget, ceiling = levels.get("budget"), levels.get("ceiling")
        if ceiling is None:
            ceiling = BUDGETS["defaults"][kind].get(metric, {}).get("ceiling")
        if budget is not None and ceiling is not None:
            assert budget <= ceiling, f"{route}.{metric}: budget {budget} > effective ceiling {ceiling}"


def test_hub_overview_query_budget_is_pinned_at_the_observed_floor():
    """The endpoint's whole value is a query count that does not scale with history, so its
    override pins `queries.budget` at the measured value as a ratchet. If a change pushes the
    real count up, the pin must come *down* to match a new (lower) measurement — never up."""
    q = OVERRIDES["/api/core/hub/overview"]["queries"]
    assert q["budget"] == 11, "calibrated 2026-09-03 at 11 queries; raising this pin hides an N+1"
    assert q["ceiling"] == 25
