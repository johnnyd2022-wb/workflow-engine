"""Unit tests for the replay ordering algorithm -- no database, pure data in/out.

`build_timeline()` itself (DB + manifest reading) is exercised as an integration check
in `scripts/whistlebird_replay.py`'s own dry-run; these tests only cover
`date_prioritised_topological_sort`, since that's the part where a subtle bug would
silently reorder a 600+ event replay instead of loudly failing.
"""

from datetime import date
from pathlib import Path

import pytest

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from whistlebird_replay_timeline import ReplayEvent, date_prioritised_topological_sort  # noqa: E402


def _event(event_id: str, real_date: str, depends_on: tuple[str, ...] = ()) -> ReplayEvent:
    return ReplayEvent(
        event_id=event_id,
        event_type="complete_step",
        real_date=date.fromisoformat(real_date),
        depends_on=depends_on,
    )


def test_sorts_independent_events_purely_by_date():
    events = [
        _event("c", "2025-03-01"),
        _event("a", "2025-01-01"),
        _event("b", "2025-02-01"),
    ]
    ordered = date_prioritised_topological_sort(events)
    assert [e.event_id for e in ordered] == ["a", "b", "c"]


def test_dependency_wins_over_a_later_dependent_date():
    # b depends on a, but a is dated AFTER b -- the hard dependency must still win:
    # a comes first in the output regardless of the date ordering.
    events = [
        _event("a", "2025-06-01"),
        _event("b", "2025-01-01", depends_on=("a",)),
    ]
    ordered = date_prioritised_topological_sort(events)
    assert [e.event_id for e in ordered] == ["a", "b"]


def test_dependency_chain_within_one_execution_stays_in_step_order():
    events = [
        _event("step5", "2025-01-05", depends_on=("step4",)),
        _event("step1", "2025-01-01"),
        _event("step3", "2025-01-03", depends_on=("step2",)),
        _event("step2", "2025-01-02", depends_on=("step1",)),
        _event("step4", "2025-01-04", depends_on=("step3",)),
    ]
    ordered = date_prioritised_topological_sort(events)
    assert [e.event_id for e in ordered] == ["step1", "step2", "step3", "step4", "step5"]


def test_two_independent_chains_interleave_by_date():
    events = [
        _event("a1", "2025-01-01"),
        _event("a2", "2025-01-10", depends_on=("a1",)),
        _event("b1", "2025-01-05"),
        _event("b2", "2025-01-06", depends_on=("b1",)),
    ]
    ordered = date_prioritised_topological_sort(events)
    # a1 (Jan 1) first; then b1 (Jan 5) and b2 (Jan 6) both become/stay ready before a2
    # (Jan 10) is reachable, so the whole b-chain runs before a2.
    assert [e.event_id for e in ordered] == ["a1", "b1", "b2", "a2"]


def test_missing_dependency_raises():
    events = [_event("a", "2025-01-01", depends_on=("ghost",))]
    with pytest.raises(ValueError, match="unknown event"):
        date_prioritised_topological_sort(events)


def test_dependency_cycle_raises():
    events = [
        _event("a", "2025-01-01", depends_on=("b",)),
        _event("b", "2025-01-02", depends_on=("a",)),
    ]
    with pytest.raises(ValueError, match="cycle"):
        date_prioritised_topological_sort(events)


def test_empty_timeline_is_fine():
    assert date_prioritised_topological_sort([]) == []


def test_tiebreak_on_identical_dates_is_deterministic_by_event_id():
    events = [_event("z", "2025-01-01"), _event("a", "2025-01-01"), _event("m", "2025-01-01")]
    ordered1 = date_prioritised_topological_sort(list(events))
    ordered2 = date_prioritised_topological_sort(list(reversed(events)))
    assert [e.event_id for e in ordered1] == [e.event_id for e in ordered2] == ["a", "m", "z"]
