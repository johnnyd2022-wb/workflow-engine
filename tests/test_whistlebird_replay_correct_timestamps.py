"""Unit tests for the replay timestamp-correction pass -- pure data in/out, no database."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_migration as wm  # noqa: E402
from whistlebird_replay_correct_timestamps import (  # noqa: E402
    _audit_days,
    _event_times,
    _execution_date_ranges,
    _marker_of,
    _purchase_audit_days,
)
from whistlebird_replay_timeline import ReplayEvent, _green_gold_events  # noqa: E402


def _green_gold_record() -> wm.GreenGoldRecord:
    return wm.GreenGoldRecord(
        source_vat=53,
        source_date=date(2026, 7, 31),
        source_quantity_l=Decimal("41"),
        bottles=Decimal("144"),
        bottle_size_ml=Decimal("500"),
        batch_label="GG01",
        source_table="production_sheet",
        source_id=2035,
    )


def test_green_gold_events_resolve_to_their_execution_marker():
    """Both Green Gold events must be dated against the same execution marker the replay stamped."""
    events = _green_gold_events(_green_gold_record(), {53: "wildflower-vat53"})

    assert [_marker_of(event) for event in events] == ["green-gold-gg01", "green-gold-gg01"]


def test_green_gold_execution_gets_its_recorded_business_date_range():
    events = _green_gold_events(_green_gold_record(), {53: "wildflower-vat53"})

    assert _execution_date_ranges(events) == {"green-gold-gg01": (date(2026, 7, 31), date(2026, 7, 31))}


def test_later_recorded_purchase_moves_audit_before_its_earliest_use():
    events = [
        ReplayEvent("purchase:lot", "create_inventory_item", date(2025, 8, 1), (), {"marker": "lot"}),
        ReplayEvent("step:first", "complete_step", date(2025, 5, 3), ("purchase:lot",), {}),
        ReplayEvent("step:later", "complete_step", date(2025, 6, 1), ("purchase:lot",), {}),
    ]

    assert _purchase_audit_days(events) == {"purchase:lot": date(2025, 5, 2)}
    timestamps = _event_times(events)
    assert timestamps["purchase:lot"].astimezone(wm.DERIVED_TIMEZONE).date() == date(2025, 5, 2)
    assert timestamps["purchase:lot"] < timestamps["step:first"]
    assert _event_times(events) == timestamps


def test_same_day_purchase_keeps_recorded_date_and_precedes_use():
    events = [
        ReplayEvent("purchase:lot", "create_inventory_item", date(2025, 5, 3), (), {"marker": "lot"}),
        ReplayEvent("step:first", "complete_step", date(2025, 5, 3), ("purchase:lot",), {}),
    ]

    assert _purchase_audit_days(events) == {}
    timestamps = _event_times(events)
    assert timestamps["purchase:lot"].astimezone(wm.DERIVED_TIMEZONE).date() == date(2025, 5, 3)
    assert timestamps["purchase:lot"] < timestamps["step:first"]


def test_production_prerequisites_move_before_earlier_dated_diversion():
    events = [
        ReplayEvent("execution:base", "create_execution", date(2026, 9, 1), (), {}),
        ReplayEvent("step:base", "complete_step", date(2026, 9, 1), ("execution:base",), {}),
        ReplayEvent("execution:diversion", "create_execution", date(2026, 7, 31), ("step:base",), {}),
        ReplayEvent("step:diversion", "complete_step", date(2026, 7, 31), ("execution:diversion",), {}),
    ]

    days = _audit_days(events)
    assert days["execution:base"] == days["step:base"] == date(2026, 7, 31)
    timestamps = _event_times(events)
    assert timestamps["execution:base"] < timestamps["step:base"] < timestamps["execution:diversion"]
